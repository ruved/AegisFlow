from aegisflow.rag.chunking import ParentChunk, TextChunk
from aegisflow.rag.lexical_index import LexicalIndex, build_fts_query
from aegisflow.rag.vector_store import VectorStore


def test_identifier_tokens_match_across_punctuation_and_survive_reopen(tmp_path):
    path = tmp_path / "lexical.sqlite3"
    index = LexicalIndex(path)
    index.replace_documents(
        [],
        [
            TextChunk(
                "pool::chunk-0",
                "services/pool.md",
                "ERR_POOL_01 exhausted the checkout-service connection pool.",
            )
        ],
    )

    reopened = LexicalIndex(path)

    assert reopened.search("ERR_POOL_01")[0]["source"] == "services/pool.md"
    assert reopened.search("checkout-service")[0]["chunk_id"] == "pool::chunk-0"


def test_safe_query_builder_quotes_user_text_and_ignores_operators(tmp_path):
    fts_query = build_fts_query('ERR_POOL_01" OR *')

    assert fts_query == '"ERR_POOL_01" OR "OR"'
    assert build_fts_query('"() : *') == ""

    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    index.replace_documents(
        [],
        [TextChunk("pool", "pool.md", "ERR_POOL_01 connection exhausted")],
    )
    assert index.search('ERR_POOL_01" OR *')[0]["chunk_id"] == "pool"


def test_replacement_removes_stale_chunks_for_source(tmp_path):
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    index.replace_documents(
        [],
        [
            TextChunk("a::chunk-0", "a.md", "old passage"),
            TextChunk("a::chunk-1", "a.md", "obsolete tail"),
        ],
    )

    index.replace_documents(
        ["a.md"],
        [TextChunk("a::chunk-0", "a.md", "new passage")],
    )

    assert index.search("obsolete") == []
    assert index.search("new")[0]["text"] == "new passage"


def test_parent_and_child_metadata_round_trip(tmp_path):
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    parent = ParentChunk("a.md::parent-0", "a.md", "# Guide\nA useful passage", "Guide")
    child_text = "A useful passage"
    index.replace_documents(
        [],
        [
            TextChunk(
                "a.md::parent-0::child-0",
                "a.md",
                child_text,
                parent_id=parent.parent_id,
                parent_start=7,
                parent_end=7 + len(child_text),
            )
        ],
        parents=[parent],
    )

    match = index.search("useful")[0]
    fetched = index.get_parent_chunks([parent.parent_id])

    assert match["parent_id"] == parent.parent_id
    assert match["parent_start"] == 7
    assert fetched[parent.parent_id]["text"] == parent.text
    assert fetched[parent.parent_id]["heading"] == "Guide"


def test_exact_error_code_finds_lexical_result_dense_search_misses(tmp_path):
    store_path = tmp_path / "store"
    vector_store = VectorStore(path=store_path)
    chunks = [
        TextChunk(
            "generic::chunk-0",
            "payments.md",
            "A payment request failed after a retry.",
        ),
        TextChunk(
            "incident::chunk-0",
            "pool-incident.md",
            "ERR_POOL_01 means the checkout-service connection pool is exhausted.",
        ),
    ]
    vector_store.add_chunks(chunks, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    lexical = LexicalIndex(store_path / "lexical.sqlite3")
    lexical.replace_documents([], chunks)

    dense = vector_store.search([1.0, 0.0, 0.0], k=1)
    lexical_results = lexical.search("ERR_POOL_01", k=1)

    assert dense[0]["source"] == "payments.md"
    assert lexical_results[0]["source"] == "pool-incident.md"
    assert lexical_results[0]["score"] < 0
