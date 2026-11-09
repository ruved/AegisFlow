"""Typed, allowlisted tools with centralized policy and hashed audit records."""

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import aiosqlite
from pydantic import BaseModel, ConfigDict, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = PROJECT_ROOT / "data" / "corpus"
DEFAULT_POLICY_PATH = PROJECT_ROOT / "policy.yaml"
logger = logging.getLogger("aegisflow.tools")


# ---------------------------------------------------------------------------
# Declarative policy loader
# ---------------------------------------------------------------------------


@dataclass
class ToolPolicy:
    """Per-tool declarative policy loaded from policy.yaml."""

    enabled: bool = True
    max_runs: int = 0  # 0 = unlimited
    require_approval_override: bool | None = None


@dataclass
class ExecutorPolicy:
    """Global + per-tool policy parsed from a YAML config file."""

    max_total_calls: int = 0  # 0 = unlimited
    tools: dict[str, ToolPolicy] = field(default_factory=dict)

    @staticmethod
    def load(path: Path | None = None) -> "ExecutorPolicy":
        """Load policy from *path* (defaults to policy.yaml at project root).

        Returns a permissive default policy if the file is absent or unparseable,
        so the system degrades safely without crashing.
        """
        resolved = path or DEFAULT_POLICY_PATH
        if not resolved.exists():
            return ExecutorPolicy()
        try:
            import yaml  # type: ignore[import-untyped]

            raw: dict[str, Any] = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover – bad yaml is non-fatal
            logger.warning("Could not parse policy file %s; using defaults.", resolved)
            return ExecutorPolicy()

        global_cfg: dict[str, Any] = raw.get("global", {}) or {}
        tools_cfg: dict[str, Any] = raw.get("tools", {}) or {}
        tools: dict[str, ToolPolicy] = {}
        for name, cfg in tools_cfg.items():
            if not isinstance(cfg, dict):
                continue
            tools[name] = ToolPolicy(
                enabled=bool(cfg.get("enabled", True)),
                max_runs=int(cfg.get("max_runs", 0)),
                require_approval_override=cfg.get("require_approval_override"),
            )
        return ExecutorPolicy(
            max_total_calls=int(global_cfg.get("max_total_calls", 0)),
            tools=tools,
        )

    def tool_policy(self, name: str) -> ToolPolicy:
        return self.tools.get(name, ToolPolicy())


_INJECTION_PATTERNS = {
    "instruction_override": re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I
    ),
    "secret_request": re.compile(
        r"(reveal|print|exfiltrate).{0,40}(secret|prompt|key)", re.I
    ),
    "tool_directive": re.compile(r"(call|invoke|use)\s+the\s+\w+\s+tool", re.I),
    "policy_override": re.compile(
        r"(disable|bypass|override).{0,30}(policy|approval|safety)", re.I
    ),
}
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
)


def redact_sensitive(value: str) -> str:
    """Redact common secret and email patterns before application logging."""
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def mark_untrusted(text: str) -> dict[str, Any]:
    """Mark retrieved text as data and note common instruction-like content."""
    flags = [
        name for name, pattern in _INJECTION_PATTERNS.items() if pattern.search(text)
    ]
    if flags:
        logger.warning(
            "Suspicious instruction-like pattern detected in untrusted content: %s",
            ", ".join(flags),
            extra={"flags": flags},
        )
    safe_text = text.replace(
        "<UNTRUSTED_EVIDENCE>", "&lt;UNTRUSTED_EVIDENCE&gt;"
    ).replace("</UNTRUSTED_EVIDENCE>", "&lt;/UNTRUSTED_EVIDENCE&gt;")
    return {
        "content": f"<UNTRUSTED_EVIDENCE>\n{safe_text}\n</UNTRUSTED_EVIDENCE>",
        "instruction_like": bool(flags),
        "flags": flags,
    }


class ToolRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchLogsInput(ToolInput):
    query: str = Field(min_length=2, max_length=200)
    service: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,64}$")
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def validate_query_path(cls, value: str) -> str:
        if "/" in value or "\\" in value or ".." in value:
            raise ValueError("Log search text cannot contain path separators")
        return value


class FetchRunbookInput(ToolInput):
    name: str = Field(min_length=3, max_length=100, pattern=r"^RB-[0-9]{3}[-a-z0-9]*$")


class ServiceDepsInput(ToolInput):
    service: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")


class QueryMetricsInput(ToolInput):
    service: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    metric: Literal["latency_p95_ms", "error_rate_pct", "db_connections"]
    window_minutes: int = Field(default=15, ge=1, le=1440)


class SimulatedWriteInput(ToolInput):
    action: str = Field(min_length=3, max_length=100)
    target: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")


class ToolProposal(BaseModel):
    """One model-proposed registry call; authorization stays with the executor."""

    model_config = ConfigDict(extra="forbid")
    tool_name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[ToolInput]
    handler: Callable[..., dict[str, Any]]
    risk: ToolRisk
    timeout_seconds: float
    requires_approval: bool

    def json_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()


def _search_logs(query: str, service: str | None, limit: int) -> dict[str, Any]:
    terms = [term.lower() for term in re.findall(r"[\w-]+", query) if len(term) > 1]
    if not terms:
        return {"matches": []}
    log_root = CORPUS_ROOT / "logs"
    paths = sorted(
        path
        for path in log_root.glob("*.md")
        if path.resolve().is_relative_to(log_root.resolve())
    )
    if service:
        paths = [path for path in paths if service in path.name.lower()]
    matches = []
    for path in paths:
        with path.open(encoding="utf-8") as source:
            text = source.read(1_000_000)
        if any(term in text.lower() for term in terms):
            matches.append({"source": path.name, "text": mark_untrusted(text[:4000])})
            if len(matches) >= limit:
                break
    return {"matches": matches}


def _fetch_runbook(name: str) -> dict[str, Any]:
    root = CORPUS_ROOT / "runbooks"
    path = root / f"{name}.md"
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        return {"found": False}
    with path.open(encoding="utf-8") as source:
        text = source.read(8000)
    return {
        "found": True,
        "name": path.name,
        "text": mark_untrusted(text),
    }


def _get_service_deps(service: str) -> dict[str, Any]:
    dependencies = {
        "api-gateway": ["order-service", "catalog-service", "payment-service"],
        "order-service": ["order-db", "inventory-service", "payment-service"],
        "payment-service": ["payment-provider", "order-db"],
        "inventory-service": ["inventory-db", "catalog-service"],
        "search-service": ["search-index", "catalog-service"],
    }
    if service not in dependencies:
        return {"service": service, "dependencies": [], "found": False}
    return {"service": service, "dependencies": dependencies[service], "found": True}


def _query_metrics(service: str, metric: str, window_minutes: int) -> dict[str, Any]:
    known = {"latency_p95_ms": 840, "error_rate_pct": 2.7, "db_connections": 48}
    return {
        "service": service,
        "metric": metric,
        "value": known.get(metric),
        "window_minutes": window_minutes,
        "simulated": True,
    }


def _simulate_write(action: str, target: str) -> dict[str, Any]:
    return {"simulated": True, "action": action, "target": target, "applied": False}


TOOL_REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "search_logs",
            "Search incident logs for matching terms.",
            SearchLogsInput,
            _search_logs,
            ToolRisk.LOW,
            2.0,
            False,
        ),
        ToolSpec(
            "fetch_runbook",
            "Fetch one known runbook by ID.",
            FetchRunbookInput,
            _fetch_runbook,
            ToolRisk.LOW,
            2.0,
            False,
        ),
        ToolSpec(
            "get_service_deps",
            "Return dependencies for a known service.",
            ServiceDepsInput,
            _get_service_deps,
            ToolRisk.LOW,
            1.0,
            False,
        ),
        ToolSpec(
            "query_metrics",
            "Return simulated service metrics.",
            QueryMetricsInput,
            _query_metrics,
            ToolRisk.LOW,
            1.0,
            False,
        ),
        ToolSpec(
            "simulate_write",
            "Preview a configuration change; never applies it.",
            SimulatedWriteInput,
            _simulate_write,
            ToolRisk.HIGH,
            1.0,
            True,
        ),
    )
}


def tool_catalog() -> list[dict[str, Any]]:
    """Return model-facing tool descriptions and JSON schemas from the registry."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "risk": spec.risk.value,
            "requires_approval": spec.requires_approval,
            "parameters": spec.json_schema(),
        }
        for spec in TOOL_REGISTRY.values()
    ]


class ToolAuditStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS tool_audit ("
            "id TEXT PRIMARY KEY, run_id TEXT, tool TEXT NOT NULL, "
            "args_hash TEXT NOT NULL, risk TEXT NOT NULL, decision TEXT NOT NULL, "
            "outcome TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        await self.db.commit()

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
            self.db = None

    async def record(
        self,
        *,
        run_id: str | None,
        tool: str,
        args_hash: str,
        risk: str,
        decision: str,
        outcome: str,
    ) -> str:
        if self.db is None:
            raise RuntimeError("Tool audit store is not open")
        audit_id = uuid4().hex
        safe_run_id = run_id
        if safe_run_id is not None and not re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", safe_run_id
        ):
            safe_run_id = (
                "invalid-" + hashlib.sha256(safe_run_id.encode()).hexdigest()[:24]
            )
        async with self._lock:
            await self.db.execute(
                "INSERT INTO tool_audit VALUES(?,?,?,?,?,?,?,?)",
                (
                    audit_id,
                    safe_run_id,
                    redact_sensitive(tool)[:100],
                    args_hash,
                    risk,
                    decision,
                    outcome,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await self.db.commit()
        return audit_id

    async def rows(self) -> list[tuple[Any, ...]]:
        if self.db is None:
            raise RuntimeError("Tool audit store is not open")
        async with self._lock:
            cursor = await self.db.execute("SELECT * FROM tool_audit ORDER BY rowid")
            return [tuple(row) for row in await cursor.fetchall()]


class ToolResult(BaseModel):
    tool: str
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    audit_id: str


class ToolExecutor:
    def __init__(
        self,
        audit: ToolAuditStore,
        policy: ExecutorPolicy | None = None,
    ) -> None:
        self.audit = audit
        self.policy: ExecutorPolicy = policy or ExecutorPolicy.load()
        self._total_calls: int = 0
        self._tool_calls: dict[str, int] = {}

    async def execute(
        self,
        name: str,
        arguments: object,
        *,
        run_id: str | None = None,
        approval_granted: bool = False,
    ) -> ToolResult:
        try:
            serialized = json.dumps(
                arguments, sort_keys=True, separators=(",", ":"), default=str
            )
        except (TypeError, ValueError):
            serialized = type(arguments).__name__
        args_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        # ---- Global call-budget check -----------------------------------------
        if (
            self.policy.max_total_calls > 0
            and self._total_calls >= self.policy.max_total_calls
        ):
            audit_id = await self.audit.record(
                run_id=run_id,
                tool=redact_sensitive(name[:100]),
                args_hash=args_hash,
                risk="unknown",
                decision="deny",
                outcome="budget_exceeded",
            )
            logger.warning(
                "tool denied: global call budget exhausted",
                extra={"tool": name, "audit_id": audit_id},
            )
            return ToolResult(
                tool=name,
                ok=False,
                error="Global execution budget exceeded.",
                audit_id=audit_id,
            )

        spec = TOOL_REGISTRY.get(name)
        if spec is None:
            audit_id = await self.audit.record(
                run_id=run_id,
                tool=redact_sensitive(name[:100]),
                args_hash=args_hash,
                risk="unknown",
                decision="deny",
                outcome="unregistered_tool",
            )
            logger.info(
                "tool denied",
                extra={
                    "tool": redact_sensitive(name[:100]),
                    "args_hash": args_hash,
                    "decision": "deny",
                    "audit_id": audit_id,
                },
            )
            return ToolResult(
                tool=name, ok=False, error="Tool is not registered.", audit_id=audit_id
            )

        # ---- Declarative YAML policy checks ----------------------------------
        tool_policy = self.policy.tool_policy(name)

        if not tool_policy.enabled:
            audit_id = await self.audit.record(
                run_id=run_id,
                tool=name,
                args_hash=args_hash,
                risk=spec.risk.value,
                decision="deny",
                outcome="policy_disabled",
            )
            logger.info(
                "tool denied by policy (disabled)",
                extra={"tool": name, "audit_id": audit_id},
            )
            return ToolResult(
                tool=name,
                ok=False,
                error="Tool is disabled by policy.",
                audit_id=audit_id,
            )

        per_tool_count = self._tool_calls.get(name, 0)
        if tool_policy.max_runs > 0 and per_tool_count >= tool_policy.max_runs:
            audit_id = await self.audit.record(
                run_id=run_id,
                tool=name,
                args_hash=args_hash,
                risk=spec.risk.value,
                decision="deny",
                outcome="per_tool_budget_exceeded",
            )
            logger.warning(
                "tool denied: per-tool call budget exhausted",
                extra={"tool": name, "audit_id": audit_id},
            )
            return ToolResult(
                tool=name,
                ok=False,
                error="Per-tool execution budget exceeded.",
                audit_id=audit_id,
            )

        # Approval: YAML override wins when explicitly set.
        needs_approval = (
            tool_policy.require_approval_override
            if tool_policy.require_approval_override is not None
            else spec.requires_approval
        )

        try:
            parsed = spec.input_model.model_validate(arguments)
        except Exception:
            audit_id = await self.audit.record(
                run_id=run_id,
                tool=name,
                args_hash=args_hash,
                risk=spec.risk.value,
                decision="deny",
                outcome="invalid_arguments",
            )
            logger.info(
                "tool denied",
                extra={
                    "tool": name,
                    "args_hash": args_hash,
                    "decision": "deny",
                    "audit_id": audit_id,
                },
            )
            return ToolResult(
                tool=name,
                ok=False,
                error="Tool arguments are invalid.",
                audit_id=audit_id,
            )
        if needs_approval and not approval_granted:
            audit_id = await self.audit.record(
                run_id=run_id,
                tool=name,
                args_hash=args_hash,
                risk=spec.risk.value,
                decision="deny",
                outcome="approval_required",
            )
            logger.info(
                "tool requires approval",
                extra={
                    "tool": name,
                    "args_hash": args_hash,
                    "decision": "deny",
                    "audit_id": audit_id,
                },
            )
            return ToolResult(
                tool=name,
                ok=False,
                error="Human approval is required.",
                audit_id=audit_id,
            )
        decision = "allow"
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(spec.handler, **parsed.model_dump()),
                timeout=spec.timeout_seconds,
            )
            outcome = "ok"
        except TimeoutError:
            result = None
            outcome = "timeout"
        except Exception:
            result = None
            outcome = "error"

        self._total_calls += 1
        self._tool_calls[name] = per_tool_count + 1

        audit_id = await self.audit.record(
            run_id=run_id,
            tool=name,
            args_hash=args_hash,
            risk=spec.risk.value,
            decision=decision,
            outcome=outcome,
        )
        logger.info(
            "tool completed",
            extra={
                "tool": name,
                "args_hash": args_hash,
                "decision": decision,
                "outcome": outcome,
                "audit_id": audit_id,
            },
        )
        if outcome != "ok":
            return ToolResult(
                tool=name, ok=False, error=f"Tool {outcome}.", audit_id=audit_id
            )
        return ToolResult(tool=name, ok=True, result=result, audit_id=audit_id)


def audit_hash(arguments: object) -> str:
    """Stable digest helper for tests and observability; never returns raw args."""
    serialized = json.dumps(
        arguments, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
