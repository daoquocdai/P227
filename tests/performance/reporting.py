from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

COLUMNS = [
    "scenario",
    "load",
    "sent",
    "success",
    "failed",
    "error_rate",
    "throughput",
    "p50",
    "p95",
    "p99",
    "min",
    "max",
    "stdev",
    "cpu_p95",
    "ram_max_mb",
    "stored",
    "lost",
    "duplicates",
    "result",
]


def write_reports(results: list[dict], report_dir: Path, metadata: dict) -> tuple[Path, Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path, csv_path, md_path = (report_dir / f"perf-{stamp}.{ext}" for ext in ("json", "csv", "md"))
    json_path.write_text(
        json.dumps({"metadata": metadata, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    rows = [
        "# Báo cáo hiệu năng GuardianCam",
        "",
        "```json",
        json.dumps(metadata, indent=2, ensure_ascii=False),
        "```",
        "",
        "| Kịch bản | Tải | Requests | Success | Error rate | P50 | P95 | P99 | CPU P95 | RAM max | Event mất | Event trùng | Kết quả |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    def fmt(value):
        if value is None:
            return "NOT MEASURED"
        return f"{value:.2f}" if isinstance(value, float) else str(value)
    for r in results:
        rows.append(
            "| "
            + " | ".join(
                fmt(r.get(key))
                for key in (
                    "scenario",
                    "load",
                    "sent",
                    "success",
                    "error_rate",
                    "p50",
                    "p95",
                    "p99",
                    "cpu_p95",
                    "ram_max_mb",
                    "lost",
                    "duplicates",
                    "result",
                )
            )
            + " |"
        )
    rows += [
        "",
        "## Ngưỡng đánh giá",
        "",
        "API: P50 ≤ 100 ms; P95 ≤ 300 ms; P99 ≤ 500 ms; tỷ lệ lỗi < 1%. Backend: CPU P95 ≤ 70%; RAM tối đa ≤ 1024 MB. Chỉ số thiếu instrumentation được ghi là NOT MEASURED.",
    ]
    md_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return json_path, csv_path, md_path
