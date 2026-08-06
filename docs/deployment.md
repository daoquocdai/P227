# Triển khai và vận hành

## Mô hình khuyến nghị

Tất cả camera thường truyền video về một Local Hub trong LAN. Local Hub duy nhất chạy camera ingest, toàn bộ Vision AI, event engine, backend, agent, database và media. Dashboard có thể được phục vụ trong LAN hoặc qua VPN. Không triển khai một edge computer cho từng camera và không mở trực tiếp RTSP, SQLite hay thư mục dữ liệu ra Internet.

## Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
docker compose logs -f backend
```

Backend được publish tại port 8000. Hai volume local được mount:

- `./data:/app/data`
- `./snapshots:/app/snapshots`

Dừng service:

```powershell
docker compose down
```

Không thêm `-v` nếu muốn giữ database và snapshot.

## Lưu ý image hiện tại

Dockerfile cài requirements hợp nhất, bao gồm PyTorch và vision dependencies nên image khá lớn. Vision realtime cần camera/device mapping và model weights riêng; Compose hiện tại chủ yếu chạy backend. Khi production hóa nên tách image backend và vision worker để tối ưu kích thước và quyền truy cập thiết bị.

## Environment production

- Đặt `APP_ENV=production`.
- Giới hạn `CORS_ORIGINS` vào domain dashboard.
- Cung cấp secret qua secret manager hoặc environment của host.
- Không dùng placeholder trong `.env.example`.
- Mount model weights chỉ đọc.
- Dùng TLS tại reverse proxy và truy cập từ LAN/VPN.

## Health và observability

- Liveness: `GET /health`.
- API docs chỉ nên mở nội bộ ở production.
- Theo dõi CPU/RAM, queue depth, inference latency, camera disconnect và disk usage.
- Đặt retention cho `snapshots/` và backup SQLite định kỳ.

## Nâng cấp an toàn

1. Backup `data/app.db` và cấu hình.
2. Pull image/commit mới.
3. Chạy test và kiểm tra model checksum.
4. Restart một hub trong maintenance window.
5. Kiểm tra health, camera source, SSE và một event giả lập.
6. Có phương án rollback code và database backup.
