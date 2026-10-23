import pytest

from aegisflow.rag.chunking import chunk_text


def test_empty_text_returns_no_chunks():
    assert chunk_text("", "sample.md") == []


def test_short_text_returns_one_chunk():
    chunks = chunk_text("Hello RAG", "sample.md")
    assert len(chunks) == 1
    assert chunks[0].source == "sample.md"
    assert chunks[0].text == "Hello RAG"


def test_long_text_chunks_overlap():
    text = "A" * 1500
    chunks = chunk_text(text, "sample.md", chunk_size=800, overlap=100)

    assert len(chunks) == 3
    assert chunks[0].text[-100:] == chunks[1].text[:100]
    assert chunks[0].chunk_id != chunks[1].chunk_id


def test_invalid_chunk_size_fails():
    with pytest.raises(ValueError):
        chunk_text("hello", "sample.md", chunk_size=0)
