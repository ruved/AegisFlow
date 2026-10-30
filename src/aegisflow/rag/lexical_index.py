"""Persistent SQLite FTS5 index for exact and keyword retrieval."""

import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from aegisflow.rag.chunking import ParentChunk, TextChunk

_QUERY_TOKEN_PATTERN = re.compile(r"[\w-]+", re.UNICODE)


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def build_fts_query(query: str) -> str:
    """Turn free-form input into quoted FTS5 terms joined with OR."""
    terms = [
        match.group(0)
        for match in _QUERY_TOKEN_PATTERN.finditer(query)
        if any(character.isalnum() for character in match.group(0))
    ]
    return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


class LexicalIndex:
    """Store searchable chunk text and source metadata in a local FTS5 table."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _connect(self.path) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(chunks_fts)")
            }
            if columns and "parent_id" not in columns:
                connection.execute("DROP TABLE chunks_fts")
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    source UNINDEXED,
                    parent_id UNINDEXED,
                    parent_start UNINDEXED,
                    parent_end UNINDEXED,
                    text,
                    tokenize = "unicode61 tokenchars '-_'"
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS parent_chunks (
                    parent_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    heading TEXT,
                    text TEXT NOT NULL
                )
                """
            )

    def list_document_ids(self) -> set[str]:
        """Return all sources represented in the lexical index."""
        with _connect(self.path) as connection:
            rows = connection.execute(
                "SELECT DISTINCT source FROM chunks_fts"
            ).fetchall()
        return {row[0] for row in rows if isinstance(row[0], str)}

    def replace_documents(
        self,
        document_ids: Sequence[str],
        chunks: Sequence[TextChunk],
        parents: Sequence[ParentChunk] = (),
    ) -> None:
        """Atomically remove prior chunks for sources and insert replacements."""
        with _connect(self.path) as connection:
            connection.executemany(
                "DELETE FROM chunks_fts WHERE source = ?",
                [(document_id,) for document_id in document_ids],
            )
            connection.executemany(
                "DELETE FROM parent_chunks WHERE source = ?",
                [(document_id,) for document_id in document_ids],
            )
            connection.executemany(
                """
                INSERT INTO parent_chunks (parent_id, source, heading, text)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (parent.parent_id, parent.source, parent.heading, parent.text)
                    for parent in parents
                ],
            )
            connection.executemany(
                """
                INSERT INTO chunks_fts (
                    chunk_id, source, parent_id, parent_start, parent_end, text
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.source,
                        chunk.parent_id,
                        chunk.parent_start,
                        chunk.parent_end,
                        chunk.text,
                    )
                    for chunk in chunks
                ],
            )

    def get_parent_chunks(self, parent_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Fetch complete parent context for retrieved child parent IDs."""
        if not parent_ids:
            return {}
        placeholders = ", ".join("?" for _ in parent_ids)
        with _connect(self.path) as connection:
            rows = connection.execute(
                f"""
                SELECT parent_id, source, heading, text
                FROM parent_chunks
                WHERE parent_id IN ({placeholders})
                """,
                list(parent_ids),
            ).fetchall()
        return {
            parent_id: {
                "parent_id": parent_id,
                "source": source,
                "heading": heading,
                "text": text,
            }
            for parent_id, source, heading, text in rows
        }

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Return lexical matches ranked by FTS5 BM25 (best score first)."""
        if k <= 0:
            raise ValueError("k must be positive")

        fts_query = build_fts_query(query)
        if not fts_query:
            return []

        with _connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT
                    chunk_id, source, parent_id, parent_start, parent_end, text,
                    bm25(chunks_fts) AS score
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY score ASC, chunk_id ASC
                LIMIT ?
                """,
                (fts_query, k),
            ).fetchall()

        return [
            {
                "chunk_id": chunk_id,
                "source": source,
                "parent_id": parent_id,
                "parent_start": parent_start,
                "parent_end": parent_end,
                "text": text,
                "score": score,
            }
            for (
                chunk_id,
                source,
                parent_id,
                parent_start,
                parent_end,
                text,
                score,
            ) in rows
        ]
