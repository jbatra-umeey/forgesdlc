"""Release-aware synthetic observations. Correlation is not proof of causality."""
import math


def percentile(values, percentile):
    if not values:
        raise ValueError("empty sample")
    values = sorted(values)
    return values[max(0, math.ceil(percentile * len(values)) - 1)]


def generate(release, baseline_release):
    rows = []
    for window, version, base, timestamp in [
        ("before", baseline_release, 100, "2026-01-01T11:50:"),
        ("after", release, 650, "2026-01-01T12:05:")]:
        for index in range(30):
            rows.append({"trace_id": f"synthetic-{window}-{index:03}", "release": version,
                         "environment": "sandbox", "route": "GET /subscriptions/{id}",
                         "timestamp": timestamp + f"{index:02}Z", "window": window,
                         "latency_ms": base + index % 9, "status": 200,
                         "source": "synthetic-fixture", "cohort": "same-sandbox-profile"})
    return rows


def correlate(rows, deployment, min_samples=20, threshold_ratio=2.0):
    relevant = [row for row in rows if row.get("environment") == deployment["environment"]
                and row.get("route") == deployment["route"]
                and row.get("cohort") == deployment["cohort"]]
    before = [r for r in relevant if r.get("window") == "before"
              and r.get("release") == deployment["baseline_release"]
              and r["timestamp"] < deployment["deployed_at"]]
    after = [r for r in relevant if r.get("window") == "after"
             and r.get("release") == deployment["release"]
             and r["timestamp"] >= deployment["deployed_at"]]
    if min(len(before), len(after)) < min_samples:
        return {"status": "inconclusive", "reason": "insufficient comparable samples",
                "before_count": len(before), "after_count": len(after)}
    for row in before + after:
        latency = row.get("latency_ms")
        if not isinstance(latency, (int, float)) or not math.isfinite(latency) or latency < 0:
            raise ValueError("invalid latency sample")
    pre = percentile([r["latency_ms"] for r in before], .95)
    post = percentile([r["latency_ms"] for r in after], .95)
    ratio = post / pre if pre > 0 else (math.inf if post > 0 else 1)
    return {"status": "regression" if ratio >= threshold_ratio else "healthy",
            "baseline_p95_ms": pre, "candidate_p95_ms": post, "ratio": round(ratio, 3),
            "before_count": len(before), "after_count": len(after),
            "release": deployment["release"], "baseline_release": deployment["baseline_release"],
            "route": deployment["route"], "trace_ids": [r["trace_id"] for r in after[:5]],
            "source": "synthetic-fixture", "causal_claim": False,
            "finding": "Latency increase is temporally associated with this sandbox release; investigate causality."}
