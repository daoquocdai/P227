"""Mô phỏng output của Vision pipeline và kiểm thử Local Hub end-to-end.

Chạy backend trước, sau đó chạy: ``python mock_yolo.py``.
Code Vision thật khi được merge nên gọi ``vision_event_sink.publish`` trực tiếp;
HTTP ở đây là adapter để hai phần được phát triển và chạy ở process riêng.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

API_BASE_URL = "http://localhost:8000/api/v1"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def create_mock_snapshot(filename: str) -> None:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540">
<rect width="960" height="540" fill="#dbeafe"/><rect y="330" width="960" height="210" fill="#94a3b8"/>
<rect x="90" y="70" width="230" height="180" fill="#bae6fd" stroke="#475569" stroke-width="15"/>
<rect x="580" y="300" width="280" height="120" rx="12" fill="#64748b"/>
<g transform="translate(350 390) rotate(-8)"><rect width="260" height="55" rx="28" fill="#334155"/>
<circle cx="-32" cy="27" r="38" fill="#334155"/></g>
<rect x="24" y="22" width="215" height="48" rx="12" fill="#dc2626"/>
<text x="45" y="55" font-family="sans-serif" font-size="24" fill="white">MOCK FALL EVENT</text>
</svg>"""
    (SNAPSHOT_DIR / filename).write_text(svg, encoding="utf-8")


def request_json(path: str, method: str = "GET", payload: dict | None = None) -> dict | list:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API_BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    filename = f"mock-fall-{uuid4().hex[:8]}.svg"
    event_id = f"mock-{uuid4()}"
    create_mock_snapshot(filename)
    payload = {
        "schema_version": 1,
        "event_id": event_id,
        "camera_id": "camera-living",
        "camera_location": "Phòng khách",
        "event_type": "FALL_SUSPECTED",
        "occurred_at": datetime.now().astimezone().isoformat(),
        "confidence": 0.95,
        "track_id": "mock-track-1",
        "identity_status": "KNOWN",
        "identity_name": "Bà Lan",
        "snapshot_path": filename,
        "immobile_seconds": 12,
        "metadata": {"source": "mock_yolo", "pose": "horizontal"},
    }

    try:
        accepted = request_json("/vision/events", "POST", payload)
        alerts = request_json("/alerts")
        created = next(item for item in alerts if item["event_id"] == event_id)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(f"Không kết nối được backend tại {API_BASE_URL}: {exc}") from exc

    print("[OK] Vision event đã được backend tiếp nhận:")
    print(json.dumps(accepted, indent=2, ensure_ascii=False))
    print("[OK] Cảnh báo đã xuất hiện qua API cho frontend:")
    print(json.dumps(created, indent=2, ensure_ascii=False))
    print("Mở dashboard: http://localhost:5173/alerts")


if __name__ == "__main__":
    main()
