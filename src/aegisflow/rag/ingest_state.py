"""Stable document hashes and persisted corpus version state."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def document_id(source_path: str | Path, docs_root: str | Path) -> str:
    """Return a stable corpus-relative ID for a document path."""
    return Path(source_path).resolve().relative_to(Path(docs_root).resolve()).as_posix()


def content_hash(text: str) -> str:
    """Hash already-parsed text, so irrelevant raw-file formatting is excluded."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CorpusManifest:
    """Persisted mapping from document IDs to hashes and a monotonic version."""

    corpus_version: int
    documents: dict[str, str]
    pipeline_version: str = "flat-v1"

    @classmethod
    def load(cls, path: str | Path) -> "CorpusManifest":
        """Read a manifest, or return an empty version-zero snapshot."""
        manifest_path = Path(path)
        if not manifest_path.exists():
            return cls(corpus_version=0, documents={})

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(
                f"Could not read ingestion manifest: {manifest_path}"
            ) from exc

        if not isinstance(payload, dict):
            raise ValueError("Ingestion manifest must contain a JSON object")
        version = payload.get("corpus_version")
        documents = payload.get("documents")
        pipeline_version = payload.get("pipeline_version", "flat-v1")
        if type(version) is not int or version < 0:
            raise ValueError(
                "Ingestion manifest corpus_version must be a non-negative integer"
            )
        if not isinstance(documents, dict) or any(
            not isinstance(doc_id, str)
            or not isinstance(digest, str)
            or _SHA256_PATTERN.fullmatch(digest) is None
            for doc_id, digest in documents.items()
        ):
            raise ValueError(
                "Ingestion manifest documents must map IDs to SHA-256 hashes"
            )
        if not isinstance(pipeline_version, str) or not pipeline_version.strip():
            raise ValueError("Ingestion manifest pipeline_version must be non-empty")

        return cls(
            corpus_version=version,
            documents=documents,
            pipeline_version=pipeline_version,
        )

    def commit(
        self,
        path: str | Path,
        documents: dict[str, str],
        pipeline_version: str = "flat-v1",
    ) -> "CorpusManifest":
        """Write a new snapshot, bumping the version only when content changes."""
        if any(
            not isinstance(doc_id, str)
            or not isinstance(digest, str)
            or _SHA256_PATTERN.fullmatch(digest) is None
            for doc_id, digest in documents.items()
        ):
            raise ValueError("Documents must map IDs to SHA-256 hashes")
        if not pipeline_version.strip():
            raise ValueError("pipeline_version must be non-empty")

        if documents == self.documents and pipeline_version == self.pipeline_version:
            return self

        updated = CorpusManifest(
            corpus_version=self.corpus_version + 1,
            documents=dict(sorted(documents.items())),
            pipeline_version=pipeline_version,
        )
        manifest_path = Path(path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(
                {
                    "corpus_version": updated.corpus_version,
                    "documents": updated.documents,
                    "pipeline_version": updated.pipeline_version,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)
        return updated
