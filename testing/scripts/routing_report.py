"""
Routing Accuracy Report — SG Property Advisor
==============================================
Standalone demo script. No pytest needed.

Reads golden_dataset.json, calls /chat/inspect for each case,
prints a formatted table + summary, and saves a JSON report.

Usage:
    # Inside the backend container (volume mounted at /app/testing):
    docker exec sg-property-backend python /app/testing/scripts/routing_report.py

    # Or locally if httpx is installed and backend is on port 8001:
    python testing/scripts/routing_report.py
"""

import json
import sys
import time
import datetime
import uuid
from pathlib import Path

try:
    import httpx
except ImportError:
    print("httpx not found. Install with: pip install httpx")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

BACKEND = "http://localhost:8001"
INSPECT_ENDPOINT = f"{BACKEND}/chat/inspect"
TIMEOUT = 90  # seconds

DATASET_PATH = Path(__file__).parent.parent / "datasets" / "queries" / "golden_dataset.json"
REPORTS_DIR  = Path(__file__).parent.parent / "reports"

LATENCY_TARGET = 5.0   # seconds
ACCURACY_TARGET = 0.90  # 90%

# ── Helpers ───────────────────────────────────────────────────────────────────

def call_inspect(query: str, case_id: str) -> dict:
    r = httpx.post(
        INSPECT_ENDPOINT,
        json={"question": query, "thread_id": f"report-{case_id}-{uuid.uuid4().hex[:6]}"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def intent_abbrev(intent: str) -> str:
    return {
        "eligibility_financial": "elig_financial",
        "knowledge_advisory":    "advisory",
    }.get(intent, intent)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not DATASET_PATH.exists():
        print(f"Dataset not found: {DATASET_PATH}")
        sys.exit(1)

    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║          SG Property Advisor — Routing Accuracy Report              ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"  Backend : {BACKEND}")
    print(f"  Dataset : {len(cases)} cases")
    print(f"  Time    : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print(f"  Running {len(cases)} test cases ...")
    print()

    # ── Column widths ──────────────────────────────────────────────────────
    COL = {
        "id":       6,
        "query":   48,
        "expected":15,
        "actual":  15,
        "time":     6,
        "result":   8,
    }
    hdr = (
        f"  {'ID':<{COL['id']}} "
        f"{'Query':<{COL['query']}} "
        f"{'Expected':<{COL['expected']}} "
        f"{'Actual':<{COL['actual']}} "
        f"{'Time':>{COL['time']}} "
        f"  Result"
    )
    sep = "  " + "─" * (sum(COL.values()) + len(COL) + 4)
    print(sep)
    print(hdr)
    print(sep)

    rows: list[dict] = []
    passed = 0
    latencies: list[float] = []
    errors: list[str] = []

    for case in cases:
        t0 = time.perf_counter()
        try:
            result = call_inspect(case["query"], case["id"])
            actual = result.get("intent", "unknown")
            ok = actual == case["expected_intent"]
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            actual = f"HTTP {status}"
            # 400 on a security probe (expected=chitchat) is an acceptable defence
            ok = status == 400 and case["expected_intent"] == "chitchat"
        except Exception as exc:
            actual = "ERROR"
            ok = False
            errors.append(f"{case['id']}: {exc}")

        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)
        if ok:
            passed += 1

        row = {
            "id":       case["id"],
            "query":    case["query"],
            "expected": case["expected_intent"],
            "actual":   actual,
            "time":     elapsed,
            "passed":   ok,
        }
        rows.append(row)

        symbol = "✓" if ok else "✗"
        print(
            f"  {row['id']:<{COL['id']}} "
            f"{truncate(row['query'], COL['query']):<{COL['query']}} "
            f"{intent_abbrev(row['expected']):<{COL['expected']}} "
            f"{intent_abbrev(row['actual']):<{COL['actual']}} "
            f"{elapsed:>{COL['time']}.1f}s "
            f"  {symbol} {'PASS' if ok else 'FAIL'}"
        )

    print(sep)
    print()

    # ── Summary ────────────────────────────────────────────────────────────
    total    = len(cases)
    accuracy = passed / total
    mean_lat = sum(latencies) / len(latencies) if latencies else 0.0
    failed   = [r for r in rows if not r["passed"]]

    acc_ok = accuracy >= ACCURACY_TARGET
    lat_ok = mean_lat < LATENCY_TARGET

    acc_sym = "✓" if acc_ok else "✗"
    lat_sym = "✓" if lat_ok else "✗"

    print(f"  ══════════════════════════════════════════════════════════════")
    print(f"  ROUTING ACCURACY : {passed}/{total}  =  {accuracy:.0%}"
          f"   [target ≥ {ACCURACY_TARGET:.0%}]   {acc_sym} {'MEETS' if acc_ok else 'BELOW'} TARGET")
    print(f"  MEAN LATENCY     : {mean_lat:.1f}s"
          f"            [target < {LATENCY_TARGET:.0f}s]   {lat_sym} {'MEETS' if lat_ok else 'ABOVE'} TARGET")

    if failed:
        print(f"  FAILED CASES     : {', '.join(r['id'] for r in failed)}")
        for r in failed:
            print(f"    → \"{truncate(r['query'], 60)}\"")
            print(f"       expected={r['expected']}  got={r['actual']}")
    else:
        print(f"  FAILED CASES     : none — all cases passed")

    if errors:
        print()
        print(f"  CONNECTION ERRORS:")
        for e in errors:
            print(f"    {e}")

    print(f"  ══════════════════════════════════════════════════════════════")

    # ── Save JSON report ───────────────────────────────────────────────────
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORTS_DIR / f"routing_report_{datetime.date.today()}.json"
    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "backend": BACKEND,
        "total": total,
        "passed": passed,
        "accuracy": round(accuracy, 4),
        "mean_latency_s": round(mean_lat, 2),
        "target_accuracy": ACCURACY_TARGET,
        "target_latency_s": LATENCY_TARGET,
        "meets_accuracy_target": acc_ok,
        "meets_latency_target": lat_ok,
        "cases": [
            {
                "id":       r["id"],
                "query":    r["query"],
                "expected": r["expected"],
                "actual":   r["actual"],
                "time_s":   round(r["time"], 2),
                "passed":   r["passed"],
            }
            for r in rows
        ],
    }
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"  Report saved → {report_file}")
    print()

    sys.exit(0 if acc_ok else 1)


if __name__ == "__main__":
    main()
