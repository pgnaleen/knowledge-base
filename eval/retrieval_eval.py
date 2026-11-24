"""Retrieval-only evaluation: does /retrieve return the right documents?

No LLM answer generation is involved, so this measures the knowledge base itself.

Input CSV columns (see eval/testset.csv):
    Question      the query
    Source        expected source URL(s); several separated by ``|``
    Must_Contain  (optional) exact strings that must appear in the retrieved text of the top-k,
                  separated by ``|`` — use for numeric facts (rates, limits) and as a
                  citation/support check: the figure must be backed by a retrieved chunk.
    Topic         (optional) label used for per-topic reporting

Metrics: hit@k, MRR, recall of Must_Contain strings, filter correctness, latency P50/P95.

Usage:
    python eval/retrieval_eval.py --api http://localhost:8000 --k 5 --mode hybrid
    python eval/retrieval_eval.py --min-hit 0.9 --min-mrr 0.7      # exits 1 if below targets
    python eval/retrieval_eval.py --baseline eval/baseline.json     # exits 1 on > 5 point drop
"""

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx

_DEFAULT_TESTSET = Path(__file__).with_name("testset.csv")


def normalise_url(url: str) -> str:
    """Compare URLs ignoring scheme, ``www.``, query/fragment and trailing slash."""
    p = urlparse(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    return f"{host}{p.path.rstrip('/')}".lower()


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = []
        for r in csv.DictReader(f):
            question = (r.get("Question") or "").strip()
            if not question:
                continue
            rows.append(
                {
                    "question": question,
                    "expected": {normalise_url(u) for u in (r.get("Source") or "").split("|") if u.strip()},
                    "must_contain": [s.strip() for s in (r.get("Must_Contain") or "").split("|") if s.strip()],
                    "topic": (r.get("Topic") or urlparse((r.get("Source") or "").split("|")[0]).netloc or "unknown"),
                }
            )
    return rows


def rank_of_first_hit(results: list[dict], expected: set[str]) -> int | None:
    for i, res in enumerate(results, 1):
        if normalise_url(res.get("source_url", "")) in expected:
            return i
    return None


def filters_respected(results: list[dict], applied: dict) -> bool:
    """Every result must satisfy the filters the API says it applied."""
    sources = {s.lower() for s in (applied.get("source") or [])}
    if sources and any(r.get("source_name", "").lower() not in sources for r in results):
        return False
    for key, field in (("property_type", "property_types"), ("citizenship_type", "citizenship_types"),
                       ("topic", "topic_tags")):
        wanted = set(applied.get(key) or [])
        if wanted and any(not wanted.intersection(r.get(field) or []) for r in results):
            return False
    return True


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def evaluate(api: str, rows: list[dict], k: int, mode: str, timeout: float) -> dict:
    per_row, latencies = [], []
    with httpx.Client(timeout=timeout) as client:
        for row in rows:
            resp = client.post(f"{api}/retrieve", json={"query": row["question"], "top_k": k, "search_mode": mode})
            resp.raise_for_status()
            body = resp.json()
            results = body["results"]
            latencies.append(body.get("latency_ms", 0.0))
            rank = rank_of_first_hit(results, row["expected"]) if row["expected"] else None
            blob = " ".join(r["text"] for r in results)
            missing = [s for s in row["must_contain"] if s not in blob]
            per_row.append(
                {
                    "question": row["question"],
                    "topic": row["topic"],
                    "rank": rank,
                    "has_expected": bool(row["expected"]),
                    "missing_facts": missing,
                    "has_facts": bool(row["must_contain"]),
                    "filters_ok": filters_respected(results, body.get("applied_filters") or {}),
                    "top_urls": [r["source_url"] for r in results],
                }
            )

    scored = [r for r in per_row if r["has_expected"]]
    fact_rows = [r for r in per_row if r["has_facts"]]
    by_topic: dict[str, list] = defaultdict(list)
    for r in scored:
        by_topic[r["topic"]].append(r)

    def hit(rs): return sum(r["rank"] is not None for r in rs) / len(rs) if rs else 0.0
    def mrr(rs): return sum(1 / r["rank"] for r in rs if r["rank"]) / len(rs) if rs else 0.0

    return {
        "k": k,
        "mode": mode,
        "questions": len(per_row),
        "hit_at_k": round(hit(scored), 4),
        "mrr": round(mrr(scored), 4),
        "fact_support_rate": round(sum(not r["missing_facts"] for r in fact_rows) / len(fact_rows), 4) if fact_rows else None,
        "filter_correctness": round(sum(r["filters_ok"] for r in per_row) / len(per_row), 4) if per_row else 0.0,
        "latency_ms_p50": round(statistics.median(latencies), 1) if latencies else 0.0,
        "latency_ms_p95": round(percentile(latencies, 0.95), 1),
        "by_topic": {t: {"n": len(rs), "hit_at_k": round(hit(rs), 4), "mrr": round(mrr(rs), 4)} for t, rs in by_topic.items()},
        "failures": [r for r in per_row if (r["has_expected"] and r["rank"] is None) or r["missing_facts"] or not r["filters_ok"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--testset", type=Path, default=_DEFAULT_TESTSET)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--mode", choices=["vector", "hybrid"], default="hybrid")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--out", type=Path, default=Path("eval/last_run.json"))
    ap.add_argument("--min-hit", type=float, default=None)
    ap.add_argument("--min-mrr", type=float, default=None)
    ap.add_argument("--baseline", type=Path, default=None, help="fail if hit@k or MRR drop > 0.05 vs this file")
    args = ap.parse_args()

    report = evaluate(args.api, load_rows(args.testset), args.k, args.mode, args.timeout)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "failures"}, indent=2))
    print(f"{len(report['failures'])} failing question(s); details in {args.out}")

    failed = False
    if args.min_hit is not None and report["hit_at_k"] < args.min_hit:
        print(f"FAIL: hit@{args.k} {report['hit_at_k']} < {args.min_hit}")
        failed = True
    if args.min_mrr is not None and report["mrr"] < args.min_mrr:
        print(f"FAIL: MRR {report['mrr']} < {args.min_mrr}")
        failed = True
    if report["filter_correctness"] < 1.0:
        print("FAIL: some results violate the applied filters")
        failed = True
    if args.baseline and args.baseline.exists():
        base = json.loads(args.baseline.read_text(encoding="utf-8"))
        for metric in ("hit_at_k", "mrr"):
            if report[metric] < base.get(metric, 0) - 0.05:
                print(f"FAIL: {metric} dropped {base[metric]} -> {report[metric]} (> 0.05)")
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
