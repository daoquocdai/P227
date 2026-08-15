# API contract

Base URL: `/api/v1`. `/docs` và `/openapi.json` là schema runtime chính xác nhất.

## 1. System

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/health` | Process health/environment |
| `GET` | `/api/v1/status` | Service readiness |
| `GET` | `/api/v1/overview` | Overview metrics/cameras/alerts |

## 2. Cameras

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/cameras` | Danh sách desired + observed state |
| `GET` | `/api/v1/cameras/{id}` | Camera detail |
| `PATCH` | `/api/v1/cameras/{id}` | Update name/location/source |
| `PATCH` | `/api/v1/cameras/{id}/source` | Update source và restart nếu desired ON |
| `DELETE` | `/api/v1/cameras/{id}` | Xóa camera inactive nếu không bị history constraint |
| `POST` | `/api/v1/cameras/{id}/start` | Persist Camera ON và start capture |
| `POST` | `/api/v1/cameras/{id}/stop` | Persist Camera OFF và stop capture |
| `GET` | `/api/v1/cameras/{id}/runtime/status` | Capture status/metrics |
| `GET` | `/api/v1/cameras/{id}/preview` | Latest raw JPEG |
| `GET` | `/api/v1/cameras/{id}/stream` | MJPEG stream |

Stream query parameters:

| Parameter | Default | Scope |
|---|---:|---|
| `boxes` | `true` | Per-viewer presentation only |
| `identity` | `true` | Per-viewer display only; camera gate vẫn thắng |

Fall display luôn ON trong current UI/API. Các presentation flags không restart
camera, Vision hoặc model.

Preview trả `404` trước frame đầu tiên. Stream trả `409` nếu camera chưa online.

## 3. Vision controls

| Method | Path | Ý nghĩa |
|---|---|---|
| `POST` | `/api/v1/cameras/{id}/vision/enable` | Persist + enable Vision |
| `POST` | `/api/v1/cameras/{id}/vision/disable` | Persist + disable/reset Vision session |
| `GET` | `/api/v1/cameras/{id}/vision/status` | Structured result/device/realtime metrics |
| `PATCH` | `/api/v1/cameras/{id}/vision/identity` | Camera-level Unknown workflow gate |

Identity payload:

```json
{ "enabled": false }
```

Identity setting ảnh hưởng mọi viewer của camera. OFF được persist trước khi
runtime workflow bị hủy để chặn queued/in-flight Unknown commit. Fall không bị
ảnh hưởng.

## 4. Alerts

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/alerts` | Alerts persisted |
| `GET` | `/api/v1/alerts/{id}` | Alert detail |
| `GET` | `/api/v1/alerts/stream` | SSE ready/alert/heartbeat |
| `PATCH` | `/api/v1/alerts/{id}` | Review status/note |
| `POST` | `/api/v1/alerts/{id}/read` | Mark read |
| `POST` | `/api/v1/alerts/confirm` | Compatibility review endpoint |

SSE chỉ publish alert sau persistence thành công. Rejected Unknown khi Identity
OFF không được persist hoặc broadcast. Fall luôn bypass Identity lookup.

Snapshot URL có thể `null` nếu privacy/write/media step không an toàn/thành
công. Alert vẫn hợp lệ.

## 5. Internal Vision ingestion compatibility

`POST /api/v1/vision/events` nhận event từ integration ngoài. Internal Local Hub
dùng in-process dispatcher, không HTTP loopback.

```json
{
  "schema_version": 1,
  "event_id": "incident-id:fall_confirmed",
  "camera_id": "camera-id",
  "camera_location": "Phòng khách",
  "event_type": "FALL_SUSPECTED",
  "occurred_at": "2026-08-15T10:00:00Z",
  "confidence": 0.91,
  "track_id": "37",
  "identity_status": "UNKNOWN",
  "identity_name": null,
  "snapshot_path": null,
  "metadata": {}
}
```

Cùng `event_id` là idempotent.

## 6. Persons/FaceGallery

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/persons` | Active/inactive persons |
| `POST` | `/api/v1/persons` | Create person |
| `PATCH` | `/api/v1/persons/{id}` | Update person |
| `POST` | `/api/v1/persons/{id}/faces` | Validate image, create embedding/profile |
| `DELETE` | `/api/v1/persons/{id}/faces/{face_id}` | Delete face profile |

Face mutation refreshes in-memory `FaceGallery`. Enrollment image không trở
thành public static asset mặc định.

## 7. Settings

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/settings` | General/notifications/users/cameras |
| `PATCH` | `/api/v1/settings/general` | Update retention/threshold/sensitive hours |
| `PATCH` | `/api/v1/settings/notifications` | Notification preferences |
| `POST` | `/api/v1/settings/users` | Create user |
| `PATCH` | `/api/v1/settings/users/{id}` | Activate/deactivate user |
| `PATCH` | `/api/v1/settings/users/{id}/permissions/{permission}` | Update permission |
| `PATCH` | `/api/v1/settings/cameras/{id}` | Update Camera/Vision desired state |

`stranger_threshold` và `fall_threshold` được `VisionProductPolicy` đọc live từ
SQLite. Không cần restart camera/model.

## 8. History

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/history` | Persisted events/media audit |

## 9. Status codes

| Code | Ý nghĩa |
|---|---|
| `200` | Success |
| `201` | Created |
| `202` | Accepted/start requested |
| `204` | Deleted |
| `404` | Resource hoặc preview chưa tồn tại |
| `409` | Runtime/state/history constraint |
| `422` | Payload/source validation error |

## 10. Invariants

- Camera online phản ánh capture, không phản ánh Vision.
- Vision error không làm Camera offline.
- Start/Stop/Enable/Disable là persisted desired-state actions.
- Raw preview khác event evidence snapshot.
- RTSP credentials không được phản chiếu ra public payload.
- Event ID idempotent.
- Viewer count không làm tăng inference.
- Identity OFF chặn Unknown ở runtime, commit boundary và EventService.
