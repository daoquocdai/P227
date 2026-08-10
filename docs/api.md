# API Contract

Base URL nghiệp vụ: `/api/v1`.

> `/docs` và `/openapi.json` là nguồn schema thực thi chính xác nhất. Tài liệu này mô tả contract sản phẩm và các invariant quan trọng; nếu payload chi tiết khác tài liệu, kiểm tra OpenAPI/runtime trước.

## 1. System

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/health` | Process health và environment |
| `GET` | `/api/v1/status` | Trạng thái dịch vụ |
| `GET` | `/api/v1/overview` | Metrics/alerts/cameras cho Tổng quan |

## 2. Cameras

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/cameras` | Danh sách camera và observed state |
| `GET` | `/api/v1/cameras/{id}` | Chi tiết camera, source public và event gần đây |
| `PATCH` | `/api/v1/cameras/{id}` | Sửa metadata/source theo schema hiện tại |
| `DELETE` | `/api/v1/cameras/{id}` | Xoá camera nếu đáp ứng constraint |
| `PATCH` | `/api/v1/cameras/{id}/source` | Đổi source |
| `POST` | `/api/v1/cameras/{id}/start` | Persist desired ON + start runtime |
| `POST` | `/api/v1/cameras/{id}/stop` | Persist desired OFF + stop runtime |
| `GET` | `/api/v1/cameras/{id}/stream` | Live MJPEG |
| `GET` | `/api/v1/cameras/{id}/preview` | Latest JPEG preview |
| `GET` | `/api/v1/cameras/{id}/runtime/status` | Observed capture status |
| `POST` | `/api/v1/cameras/{id}/vision/enable` | Persist Vision desired ON |
| `POST` | `/api/v1/cameras/{id}/vision/disable` | Persist Vision desired OFF + reset session |
| `GET` | `/api/v1/cameras/{id}/vision/status` | Device, result, dispatcher, temporal status |

### Source privacy

`source_uri` có thể chứa RTSP credential.

Frontend chỉ nên nhận các trường public/sanitized do backend cung cấp. Không log hoặc phản chiếu raw credential.

### Preview

Preview là latest static JPEG, không phải event evidence.

Nếu chưa có frame:

- API có thể trả `404` hoặc contract `preview_url=null` ở object tổng hợp;
- frontend phải dùng placeholder;
- không retry broken image vô hạn.

## 3. Alerts

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/alerts` | Danh sách alerts mới nhất |
| `GET` | `/api/v1/alerts/{id}` | Chi tiết alert |
| `GET` | `/api/v1/alerts/stream` | SSE ready/alert/heartbeat |
| `PATCH` | `/api/v1/alerts/{id}` | Human review status/note |
| `POST` | `/api/v1/alerts/{id}/read` | Đánh dấu đã đọc |
| `POST` | `/api/v1/alerts/confirm` | Compatibility endpoint cho client cũ |

UI status hiện hành có thể gồm:

```text
pending
checking
need_help
safe
false_alarm
resolved
```

SSE contract:

1. Client tải state ban đầu bằng REST.
2. Client mở SSE.
3. Server publish alert chỉ sau persistence thành công.
4. Client phải chịu được reconnect.
5. Khi nhận event, client refresh/merge state mà không tạo duplicate UI item.

## 4. Vision event ingestion

`POST /api/v1/vision/events` là compatibility boundary cho nguồn Vision ngoài internal dispatcher.

Ví dụ:

```json
{
  "schema_version": 1,
  "event_id": "incident-id:fall_confirmed",
  "camera_id": "camera-id",
  "camera_location": "Khu vực ngủ",
  "event_type": "FALL_CONFIRMED",
  "occurred_at": "2026-08-09T11:23:31Z",
  "confidence": 0.91,
  "track_id": "37",
  "identity_status": "UNKNOWN",
  "identity_name": null,
  "snapshot_path": "vision-camera-123-abcd.jpg",
  "immobile_seconds": 2.0,
  "metadata": {}
}
```

Cùng `event_id` phải idempotent: retry không được tạo alert thứ hai.

Internal Local Hub Vision không cần đi HTTP vòng ra ngoài nếu dispatcher/service đã kết nối trực tiếp.

## 5. Persons / Face Profiles

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/persons` | Danh sách người thân từ database |
| `POST` | `/api/v1/persons` | Tạo hồ sơ |
| `PATCH` | `/api/v1/persons/{id}` | Sửa hoặc active/deactivate |
| `POST` | `/api/v1/persons/{id}/faces` | Trích xuất và lưu face embedding |
| `DELETE` | `/api/v1/persons/{id}/faces/{face_id}` | Xoá face profile |

Mutation face profile phải làm refresh/invalidate FaceGallery.

Ảnh enrollment không được tự trở thành public static file.

## 6. Settings

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/settings` | General/notification/camera settings |
| `PATCH` | `/api/v1/settings/general` | Cập nhật cấu hình chung |
| `PATCH` | `/api/v1/settings/notifications` | Cập nhật notification settings |
| `POST` | `/api/v1/settings/users` | Tạo người dùng |
| `PATCH` | `/api/v1/settings/users/{id}` | Bật/tắt người dùng |
| `PATCH` | `/api/v1/settings/users/{id}/permissions/{permission}` | Cập nhật quyền |
| `PATCH` | `/api/v1/settings/cameras/{id}` | Đồng bộ camera/Vision desired state |

Nếu Settings thay camera/Vision ON/OFF, backend phải đồng bộ cả persistence và runtime; không chỉ sửa UI.

## 7. History

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/history` | Event + media history đã persist |

History là audit/review lịch sử, không phải live incident list.

## 8. Status codes

| Code | Ý nghĩa |
|---|---|
| `200` | Thành công đồng bộ |
| `202` | Action/ingestion đã được chấp nhận |
| `204` | Xoá thành công |
| `404` | Resource/preview không tồn tại |
| `409` | Xung đột trạng thái/constraint |
| `422` | Payload/source/path không hợp lệ |

Không suy luận lỗi chỉ từ message frontend; kiểm tra status code và response body trong Browser Network hoặc Swagger.

## 9. API invariants

- Camera ONLINE chỉ phản ánh capture/source health, không phản ánh Vision health.
- Vision ERROR không làm Camera OFFLINE.
- Start/Stop và Vision Enable/Disable là persisted desired-state actions.
- `preview` và event `snapshot` là hai loại media khác nhau.
- RTSP credential không được phản chiếu ra frontend.
- Event ID phải idempotent.
- Face identity production dùng database-backed gallery.
