"""Report abstention, citation, and score-threshold metrics from answer CSVs."""

import argparse
import csv
import json
import random
import re
from pathlib import Path


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def metrics(rows: list[dict[str, str]]) -> dict[str, object]:
    answerable = [row for row in rows if json.loads(row["gold_sources"])]
    unanswerable = [row for row in rows if not json.loads(row["gold_sources"])]

    def abstained(row: dict[str, str]) -> bool:
        value = row.get("abstained", "").lower()
        if value in {"true", "false"}:
            return value == "true"
        if int(row.get("failed_runs", "0") or 0):
            return False
        return "don't have enough information" in row.get("answer", "").lower()

    cited = 0
    correct_cited = 0
    covered_gold = 0
    total_gold = 0
    for row in answerable:
        gold = {
            (item["doc"].replace("\\", "/"), item["section"])
            for item in json.loads(row["gold_source_details"])
            if item.get("section")
        }
        total_gold += len(gold)
        citations = json.loads(row.get("citations", "[]"))
        if not citations:
            used_ids = set(re.findall(r"\[(\d+)\]", row.get("answer", "")))
            citations = [
                {
                    "source": chunk.get("source", ""),
                    "heading": chunk.get("heading"),
                }
                for chunk in json.loads(row.get("retrieved_chunks", "[]"))
                if str(chunk.get("evidence_id", "")) in used_ids
            ]
        cited += len(citations)
        for citation in citations:
            target = (citation["source"].replace("\\", "/"), citation.get("heading"))
            correct_cited += target in gold
        covered_gold += len(
            gold
            & {
                (item["source"].replace("\\", "/"), item.get("heading"))
                for item in citations
            }
        )
    return {
        "questions": len(rows),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "answerable_abstention_rate": _rate(
            sum(abstained(r) for r in answerable), len(answerable)
        ),
        "unanswerable_abstention_recall": _rate(
            sum(abstained(r) for r in unanswerable), len(unanswerable)
        ),
        "coverage_on_answerable": _rate(
            sum(not abstained(r) for r in answerable), len(answerable)
        ),
        "citation_precision": _rate(correct_cited, cited),
        "citation_recall": _rate(covered_gold, total_gold),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _gold_docs(row: dict[str, str]) -> set[str]:
    return {
        (item if isinstance(item, str) else item["doc"]).replace("\\", "/")
        for item in json.loads(row["gold_sources"])
    }


def threshold_curve(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    """Show coverage and retrieval evidence-hit rate at candidate RRF cutoffs."""
    output = []
    for threshold in (0.0, 0.01, 0.015, 0.02, 0.025, 0.03):
        eligible = []
        for row in rows:
            chunks = json.loads(row.get("retrieved_chunks", "[]"))
            score = max((c.get("rrf_score", 0.0) for c in chunks), default=0.0)
            if score >= threshold:
                eligible.append(row)
        answerable_n = sum(bool(_gold_docs(row)) for row in eligible)
        answerable_hits = sum(
            bool(
                _gold_docs(row)
                & {
                    x["source"].replace("\\", "/")
                    for x in json.loads(row.get("retrieved_chunks", "[]"))
                }
            )
            for row in eligible
            if _gold_docs(row)
        )
        output.append(
            {
                "min_rrf_score": threshold,
                "coverage_rate": _rate(len(eligible), len(rows)),
                "answerable_evidence_hit_rate": _rate(answerable_hits, answerable_n),
                "unanswerable_false_accept_rate": _rate(
                    sum(not _gold_docs(row) for row in eligible),
                    sum(not _gold_docs(row) for row in rows),
                ),
            }
        )
    return output


def judge_agreement(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"labeled_answers": 0, "raw_agreement": None, "cohen_kappa": None}
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    labeled = [row for row in rows if row.get("human_correct_0_or_1", "") in {"0", "1"}]
    if not labeled:
        return {"labeled_answers": 0, "raw_agreement": None, "cohen_kappa": None}
    pairs = [
        (
            row.get("judge_sufficient", "").lower() == "true",
            row["human_correct_0_or_1"] == "1",
        )
        for row in labeled
    ]
    observed = sum(left == right for left, right in pairs) / len(pairs)
    judge_acceptance = sum(left for left, _ in pairs) / len(pairs)
    human_correctness = sum(right for _, right in pairs) / len(pairs)
    expected = judge_acceptance * human_correctness + (1 - judge_acceptance) * (
        1 - human_correctness
    )
    kappa = (observed - expected) / (1 - expected) if expected < 1 else None
    return {
        "labeled_answers": len(labeled),
        "raw_agreement": observed,
        "cohen_kappa": kappa,
        "target": 20,
    }


def write_tradeoff_svg(
    tuning: list[dict[str, object]], heldout: list[dict[str, object]], path: Path
) -> None:
    """Plot abstention rate against answerable evidence-hit rate (a proxy)."""
    width, height = 820, 510
    left, top, plot_width, plot_height = 90, 75, 650, 340
    colors = ("#2457a7", "#d45b20")
    series = (("Tuning: G001-G030", tuning), ("Held out: G031-G041", heldout))
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',  # noqa: E501
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="410" y="32" text-anchor="middle" font-family="Arial" font-size="18">Retrieval score threshold tradeoff</text>',  # noqa: E501
    ]
    for tick in range(6):
        fraction = tick / 5
        x = left + fraction * plot_width
        y = top + plot_height - fraction * plot_height
        elements.extend(
            [
                f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_height}" stroke="#ddd"/>',  # noqa: E501
                f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="#ddd"/>',  # noqa: E501
                f'<text x="{x:.1f}" y="{top + plot_height + 22}" text-anchor="middle" font-family="Arial" font-size="12">{fraction:.1f}</text>',  # noqa: E501
                f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end" font-family="Arial" font-size="12">{fraction:.1f}</text>',  # noqa: E501
            ]
        )
    elements.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#222"/>',  # noqa: E501
            f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#222"/>',  # noqa: E501
            f'<text x="{left + plot_width / 2}" y="{height - 58}" text-anchor="middle" font-family="Arial" font-size="14">Abstention rate (1 - coverage)</text>',  # noqa: E501
            f'<text x="22" y="{top + plot_height / 2}" transform="rotate(-90 22 {top + plot_height / 2})" text-anchor="middle" font-family="Arial" font-size="14">Answerable evidence hit rate (proxy)</text>',  # noqa: E501
        ]
    )
    for index, (label, points) in enumerate(series):
        color = colors[index]
        coords = []
        for point in points:
            coverage = point["coverage_rate"]
            hit_rate = point["answerable_evidence_hit_rate"]
            if coverage is None or hit_rate is None:
                continue
            x = left + (1 - float(coverage)) * plot_width
            y = top + (1 - float(hit_rate)) * plot_height
            coords.append(f"{x:.1f},{y:.1f}")
        if coords:
            elements.append(
                f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="3"/>'  # noqa: E501
            )
            for coordinate in coords:
                x, y = coordinate.split(",")
                elements.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')
        legend_y = height - 35
        elements.append(
            f'<line x1="{left + index * 210}" y1="{legend_y}" x2="{left + 25 + index * 210}" y2="{legend_y}" stroke="{color}" stroke-width="3"/><text x="{left + 32 + index * 210}" y="{legend_y + 4}" font-family="Arial" font-size="12">{label}</text>'  # noqa: E501
        )
    elements.append(
        '<text x="410" y="499" text-anchor="middle" font-family="Arial" font-size="11" fill="#555">Retrieval-hit rate is an evidence proxy, not a human correctness grade.</text>'  # noqa: E501
    )
    elements.append("</svg>")
    path.write_text("\n".join(elements) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--e1", type=Path, required=True)
    parser.add_argument("--e2", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("results/answer_quality_summary.json")
    )
    parser.add_argument(
        "--review-sheet", type=Path, default=Path("results/judge_human_review.csv")
    )
    args = parser.parse_args()
    e1 = load_rows(args.e1)
    e2 = load_rows(args.e2) if args.e2 else None
    report = {
        "E1_without_verifier": metrics(e1),
        "E2_with_verifier": metrics(e2) if e2 is not None else None,
        "threshold_tuning_G001_G030": threshold_curve(
            [row for row in e1 if int(row["question_id"][1:]) <= 30]
        ),
        "heldout_threshold_curve_G031_plus": threshold_curve(
            [row for row in e1 if int(row["question_id"][1:]) > 30]
        ),
        "judge_human_agreement": (
            judge_agreement(args.review_sheet) if e2 is not None else None
        ),
    }
    tuning = report["threshold_tuning_G001_G030"]
    heldout = report["heldout_threshold_curve_G031_plus"]
    write_tradeoff_svg(
        tuning if isinstance(tuning, list) else [],
        heldout if isinstance(heldout, list) else [],
        args.output.with_name("abstention_tradeoff.svg"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if e2 is None:
        print(json.dumps(report, indent=2))
        return
    candidates = [row for row in e2 if row.get("answer", "").strip()]
    selected = sorted(candidates, key=lambda row: row["question_id"])
    if len(selected) > 20:
        selected = random.Random(20261030).sample(selected, 20)
    args.review_sheet.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "question_id",
        "question",
        "answer",
        "gold_key_facts",
        "citations",
        "judge_sufficient",
        "human_correct_0_or_1",
        "review_notes",
    ]
    if not args.review_sheet.exists():
        with args.review_sheet.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in sorted(selected, key=lambda item: item["question_id"]):
                writer.writerow(
                    {
                        "question_id": row["question_id"],
                        "question": row["question"],
                        "answer": row["answer"],
                        "gold_key_facts": row["gold_key_facts"],
                        "citations": row.get("citations", "[]"),
                        "judge_sufficient": row.get("verifier_sufficient", ""),
                        "human_correct_0_or_1": "",
                        "review_notes": "",
                    }
                )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
