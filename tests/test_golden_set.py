import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = PROJECT_ROOT / "data" / "corpus"
GOLDEN_PATH = PROJECT_ROOT / "data" / "eval" / "golden_v0.jsonl"

EXPECTED_FIELDS = {
    "id",
    "question",
    "slice",
    "gold_key_facts",
    "gold_sources",
    "difficulty",
}
ALLOWED_SLICES = {"single_hop", "multi_part", "unanswerable"}
ALLOWED_DIFFICULTIES = {"easy", "medium", "hard"}
EXPECTED_SLICE_COUNTS = {
    "single_hop": 20,
    "multi_part": 5,
    "unanswerable": 5,
}


def load_jsonl() -> list[dict[str, object]]:
    assert GOLDEN_PATH.is_file(), f"Golden dataset missing: {GOLDEN_PATH}"

    records: list[dict[str, object]] = []

    for line_number, line in enumerate(
        GOLDEN_PATH.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        assert line.strip(), f"Blank JSONL line at line {line_number}"

        record = json.loads(line)
        assert isinstance(record, dict), (
            f"Line {line_number} must contain a JSON object"
        )
        records.append(record)

    return records


def test_golden_jsonl_schema_and_slice_distribution() -> None:
    records = load_jsonl()

    assert len(records) == 30, "Expected exactly 30 gold records"

    ids: list[str] = []
    slice_values: list[str] = []

    for index, record in enumerate(records, start=1):
        context = f"Record {index}"

        assert set(record) == EXPECTED_FIELDS, (
            f"{context} has missing or unexpected fields"
        )

        record_id = record["id"]
        assert isinstance(record_id, str) and record_id.strip(), (
            f"{context} must have a non-empty string id"
        )
        ids.append(record_id)

        question = record["question"]
        assert isinstance(question, str) and question.strip(), (
            f"{record_id}: question must be a non-empty string"
        )

        slice_name = record["slice"]
        assert isinstance(slice_name, str) and slice_name in ALLOWED_SLICES, (
            f"{record_id}: invalid slice"
        )
        slice_values.append(slice_name)

        facts = record["gold_key_facts"]
        assert isinstance(facts, list) and facts, (
            f"{record_id}: gold_key_facts must be a non-empty list"
        )
        assert all(isinstance(fact, str) and fact.strip() for fact in facts), (
            f"{record_id}: every gold key fact must be a non-empty string"
        )

        difficulty = record["difficulty"]
        assert isinstance(difficulty, str) and (difficulty in ALLOWED_DIFFICULTIES), (
            f"{record_id}: invalid difficulty"
        )

        sources = record["gold_sources"]
        assert isinstance(sources, list), f"{record_id}: gold_sources must be a list"

        if slice_name == "unanswerable":
            assert not sources, (
                f"{record_id}: unanswerable record must not claim gold sources"
            )
        else:
            assert sources, f"{record_id}: answerable record must have gold sources"

    assert len(ids) == len(set(ids)), "Record IDs must be unique"
    assert Counter(slice_values) == Counter(EXPECTED_SLICE_COUNTS), (
        "Expected 20 single_hop, 5 multi_part, and 5 unanswerable records"
    )


def test_gold_sources_reference_existing_documents_and_sections() -> None:
    records = load_jsonl()
    corpus_root = CORPUS_DIR.resolve()

    assert corpus_root.is_dir(), f"Corpus directory missing: {corpus_root}"

    for record in records:
        record_id = str(record["id"])
        sources = record["gold_sources"]

        assert isinstance(sources, list)

        for source in sources:
            assert isinstance(source, dict), (
                f"{record_id}: each source must be a JSON object"
            )
            assert set(source) == {"doc", "section"}, (
                f"{record_id}: source must contain only doc and section"
            )

            doc = source["doc"]
            section = source["section"]

            assert isinstance(doc, str) and doc.strip(), (
                f"{record_id}: source doc must be a non-empty string"
            )
            assert isinstance(section, str) and section.strip(), (
                f"{record_id}: source section must be a non-empty string"
            )

            target = (corpus_root / doc).resolve()

            assert target.is_relative_to(corpus_root), (
                f"{record_id}: source path escapes the corpus directory: {doc}"
            )
            assert target.is_file(), (
                f"{record_id}: source document does not exist: {doc}"
            )

            headings = {
                line.strip().lstrip("#").strip()
                for line in target.read_text(encoding="utf-8").splitlines()
                if re.match(r"^#{1,3}\s+", line)
            }

            assert section in headings, (
                f"{record_id}: heading {section!r} not found in {doc}"
            )
