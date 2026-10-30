"""Structure-aware parent and child chunking for Markdown documents."""

import math
import re
from dataclasses import dataclass

from aegisflow.rag.chunking import ParentChunk, TextChunk

DEFAULT_PARENT_TOKENS = 800
DEFAULT_CHILD_TOKENS = 175
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: str


def approximate_token_count(text: str) -> int:
    """Estimate tokens consistently as roughly one token per four characters."""
    return math.ceil(len(text) / 4)


def parent_child_chunks(
    text: str,
    source: str,
    parent_tokens: int = DEFAULT_PARENT_TOKENS,
    child_tokens: int = DEFAULT_CHILD_TOKENS,
) -> tuple[list[ParentChunk], list[TextChunk]]:
    """Pack Markdown blocks into context parents and smaller matching children."""
    if parent_tokens <= 0:
        raise ValueError("parent_tokens must be positive")
    if child_tokens <= 0:
        raise ValueError("child_tokens must be positive")
    if not text.strip():
        return [], []

    blocks = _markdown_blocks(text)
    parent_ranges = _parent_ranges(text, blocks, parent_tokens)
    parents: list[ParentChunk] = []
    children: list[TextChunk] = []

    for parent_index, (start, end) in enumerate(parent_ranges):
        parent_text = text[start:end].strip()
        if not parent_text:
            continue
        parent_id = f"{source}::parent-{parent_index}"
        heading = _first_heading(parent_text)
        parents.append(ParentChunk(parent_id, source, parent_text, heading))

        child_blocks = _split_oversized_blocks(
            parent_text, _markdown_blocks(parent_text), child_tokens
        )
        child_ranges = _group_blocks(parent_text, child_blocks, child_tokens)
        for child_index, (child_start, child_end) in enumerate(child_ranges):
            raw_child = parent_text[child_start:child_end]
            leading = len(raw_child) - len(raw_child.lstrip())
            child_text = raw_child.strip()
            if not child_text:
                continue
            children.append(
                TextChunk(
                    chunk_id=f"{parent_id}::child-{child_index}",
                    source=source,
                    text=child_text,
                    parent_id=parent_id,
                    parent_start=child_start + leading,
                    parent_end=child_start + leading + len(child_text),
                )
            )

    return parents, children


def _markdown_blocks(text: str) -> list[_Block]:
    lines = text.splitlines(keepends=True)
    blocks: list[_Block] = []
    offset = 0
    active_kind: str | None = None
    active_start = 0
    active_end = 0
    fence_char: str | None = None
    fence_size = 0

    for line in lines:
        content = line.rstrip("\r\n")
        fence = _FENCE.match(content)
        if fence_char is not None:
            kind = "code"
            if fence and fence.group(1)[0] == fence_char:
                if len(fence.group(1)) >= fence_size:
                    fence_char = None
                    fence_size = 0
        elif fence:
            kind = "code"
            fence_char = fence.group(1)[0]
            fence_size = len(fence.group(1))
        elif _HEADING.match(content):
            kind = "heading"
        elif content.lstrip().startswith("|"):
            kind = "table"
        elif not content.strip():
            kind = "blank"
        else:
            kind = "paragraph"

        if active_kind is None:
            active_kind = kind
            active_start = offset
        elif kind != active_kind or kind == "heading":
            blocks.append(_Block(active_start, offset, active_kind))
            active_kind = kind
            active_start = offset
        active_end = offset + len(line)
        offset = active_end

    if active_kind is not None and active_end > active_start:
        blocks.append(_Block(active_start, active_end, active_kind))
    return blocks


def _split_oversized_blocks(
    text: str, blocks: list[_Block], token_limit: int
) -> list[_Block]:
    result: list[_Block] = []
    max_chars = token_limit * 4
    for block in blocks:
        if (
            block.kind in {"code", "table", "heading", "blank"}
            or approximate_token_count(text[block.start : block.end]) <= token_limit
        ):
            result.append(block)
            continue

        start = block.start
        while start < block.end:
            limit = min(start + max_chars, block.end)
            end = limit
            if limit < block.end:
                boundary = max(
                    text.rfind(" ", start + 1, limit),
                    text.rfind("\n", start + 1, limit),
                )
                if boundary > start:
                    end = boundary + 1
            result.append(_Block(start, end, block.kind))
            start = end
    return result


def _group_blocks(
    text: str, blocks: list[_Block], token_limit: int
) -> list[tuple[int, int]]:
    groups: list[tuple[int, int]] = []
    group_start: int | None = None
    group_end = 0
    for block in blocks:
        if group_start is None:
            group_start, group_end = block.start, block.end
            continue

        if approximate_token_count(text[group_start : block.end]) > token_limit:
            groups.append((group_start, group_end))
            group_start, group_end = block.start, block.end
        else:
            group_end = block.end

    if group_start is not None:
        groups.append((group_start, group_end))
    return groups


def _parent_ranges(
    text: str, blocks: list[_Block], token_limit: int
) -> list[tuple[int, int]]:
    """Split at headings first, then pack each section to the parent budget."""
    sections: list[list[_Block]] = []
    section: list[_Block] = []
    has_headings = any(block.kind == "heading" for block in blocks)

    for block in blocks:
        if has_headings and block.kind == "heading" and section:
            sections.append(section)
            section = []
        section.append(block)
    if section:
        sections.append(section)

    ranges: list[tuple[int, int]] = []
    for blocks_in_section in sections:
        sized_blocks = _split_oversized_blocks(text, blocks_in_section, token_limit)
        if not has_headings:
            ranges.extend(_group_blocks(text, sized_blocks, token_limit))
            continue

        groups: list[tuple[int, int]] = []
        group_start: int | None = None
        group_end = 0
        heading_prefix = True
        for block in sized_blocks:
            if group_start is None:
                group_start, group_end = block.start, block.end
                if block.kind not in {"heading", "blank"}:
                    heading_prefix = False
                continue

            exceeds_limit = (
                approximate_token_count(text[group_start : block.end]) > token_limit
            )
            if exceeds_limit and not heading_prefix:
                groups.append((group_start, group_end))
                group_start, group_end = block.start, block.end
                heading_prefix = block.kind in {"heading", "blank"}
            else:
                group_end = block.end
                if block.kind not in {"heading", "blank"}:
                    heading_prefix = False

        if group_start is not None:
            groups.append((group_start, group_end))
        ranges.extend(groups)

    return ranges


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            return match.group(1).strip()
    return None
