import json

import pytest

from aegisflow.rag.document_parser import parse_document
from aegisflow.rag.ingest_state import CorpusManifest, content_hash, document_id


def test_content_hash_is_sha256_of_cleaned_text():
    assert content_hash("alpha\nbeta") == content_hash("alpha\nbeta")
    assert content_hash("alpha\nbeta") != content_hash("alpha\r\nbeta")
    assert content_hash(parse_document("alpha\r\nbeta", ".md")) == content_hash(
        "alpha\nbeta"
    )


def test_document_id_uses_corpus_relative_posix_path(tmp_path):
    root = tmp_path / "corpus"
    path = root / "services" / "payment.md"

    assert document_id(path, root) == "services/payment.md"


def test_manifest_starts_at_version_zero_and_bumps_for_new_documents(tmp_path):
    path = tmp_path / "store" / "ingestion_manifest.json"
    initial = CorpusManifest.load(path)

    updated = initial.commit(path, {"a.md": content_hash("one")})

    assert initial.corpus_version == 0
    assert updated.corpus_version == 1
    assert CorpusManifest.load(path) == updated


def test_manifest_does_not_bump_for_unchanged_mapping(tmp_path):
    path = tmp_path / "ingestion_manifest.json"
    first = CorpusManifest.load(path).commit(path, {"a.md": content_hash("one")})

    second = CorpusManifest.load(path).commit(path, {"a.md": content_hash("one")})

    assert second == first
    assert json.loads(path.read_text(encoding="utf-8"))["corpus_version"] == 1


def test_manifest_bumps_when_chunking_pipeline_changes(tmp_path):
    path = tmp_path / "ingestion_manifest.json"
    documents = {"a.md": content_hash("one")}
    first = CorpusManifest.load(path).commit(
        path, documents, pipeline_version="flat-v1"
    )

    updated = CorpusManifest.load(path).commit(
        path, documents, pipeline_version="parent-child-v1:p800:c175"
    )

    assert updated.corpus_version == first.corpus_version + 1
    assert updated.documents == documents
    assert updated.pipeline_version == "parent-child-v1:p800:c175"


@pytest.mark.parametrize(
    "new_documents",
    [
        {"a.md": content_hash("changed")},
        {"a.md": content_hash("one"), "b.md": content_hash("added")},
        {},
    ],
)
def test_manifest_bumps_for_edit_addition_or_deletion(tmp_path, new_documents):
    path = tmp_path / "ingestion_manifest.json"
    first = CorpusManifest.load(path).commit(path, {"a.md": content_hash("one")})

    updated = CorpusManifest.load(path).commit(path, new_documents)

    assert updated.corpus_version == first.corpus_version + 1
    assert updated.documents == new_documents


def test_manifest_rejects_corrupt_data(tmp_path):
    path = tmp_path / "ingestion_manifest.json"
    path.write_text('{"corpus_version": -1, "documents": {}}', encoding="utf-8")

    with pytest.raises(ValueError, match="corpus_version"):
        CorpusManifest.load(path)
