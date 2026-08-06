# Frontend Dashboard

Frontend nằm trong `frontend/`, sử dụng React, TypeScript và Vite.

## Cài đặt và chạy

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

Mặc định Vite chạy tại `http://localhost:5173` và proxy `/api`, `/snapshots` sang backend port 8000.

## Environment

```dotenv
VITE_API_MODE=api
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Đặt `VITE_API_MODE=mock` để dùng MSW và dữ liệu giả khi backend chưa chạy. Khi kiểm thử tích hợp, luôn dùng `api`.

## Màn hình chính

- Overview: trạng thái hệ thống và số liệu cảnh báo.
- Cameras: danh sách, playback và cấu hình nguồn.
- Alerts: luồng cảnh báo, chi tiết và human review.
- History: lịch sử sự kiện.
- Family: hồ sơ người thân và face profile metadata.
- Settings: ngưỡng, thông báo, người dùng và camera.
- Statistics: thống kê hoạt động.

## Realtime alerts

Frontend kết nối SSE tại `/api/v1/alerts/stream`. Client phải:

- Tự reconnect khi mất mạng.
- Không coi heartbeat là alert.
- Fetch lại alert detail khi cần nguồn dữ liệu đầy đủ.
- Chịu được event trùng do reconnect.

## Build

```powershell
cd frontend
npm run build
npm run preview
```

Output nằm trong `frontend/dist/` và bị Git ignore.

## Quy ước tích hợp

- Dùng các module trong `frontend/src/api/`, không gọi `fetch` rải rác.
- Không hiển thị `source_uri` RTSP hoặc credential.
- Snapshot URL phải đến từ backend.
- TypeScript type cần khớp OpenAPI/schema backend.
