# Bảo mật và quyền riêng tư

## Dữ liệu nhạy cảm

- RTSP URL và credential camera.
- Face image và embedding.
- Snapshot/video sự kiện.
- Thông tin người thân và lịch sử cảnh báo.
- API key cho LLM, logging và dịch vụ ngoài.

Không lưu các dữ liệu này trong Git, log debug hoặc payload gửi ra cloud nếu chưa có sự đồng ý rõ ràng.

## Xử lý local-first

Video thô, face recognition và fall detection chạy trên Local Hub. Backend chỉ lưu metadata và media cần thiết cho sự kiện. LLM là tùy chọn và không được nhận frame/embedding mặc định.

## Secret management

- `.env` bị Git ignore; `.env.example` chỉ chứa placeholder.
- Production dùng secret manager hoặc quyền file giới hạn.
- Rotate key nếu từng xuất hiện trong commit/log.
- Không trả `camera_sources.source_uri` cho frontend.

## Network

- Đặt Hub và camera trong VLAN/LAN tin cậy.
- Dashboard truy cập qua LAN hoặc VPN.
- Dùng TLS ở reverse proxy.
- Firewall chỉ mở port cần thiết.
- Không expose SQLite, webcam device hoặc RTSP trực tiếp ra Internet.

## Media và sinh trắc học

- Mã hóa ổ đĩa và backup.
- Áp dụng retention ngắn nhất đáp ứng nhu cầu.
- Xóa face profile khi người dùng rút consent.
- Tách quyền xem live stream, snapshot và quản trị người thân.
- Audit mọi thay đổi trạng thái cảnh báo.

## Giới hạn an toàn

Hệ thống có thể false positive hoặc false negative. Cảnh báo phải cho phép human review và không được quảng bá như thiết bị y tế được chứng nhận. Quy trình khẩn cấp cần có fallback không phụ thuộc duy nhất vào AI hoặc Internet.

## Checklist production

```text
[ ] Không dùng key placeholder
[ ] CORS allowlist cụ thể
[ ] TLS/VPN hoạt động
[ ] Backup và restore đã thử
[ ] Model có checksum và nguồn rõ ràng
[ ] Retention media được cấu hình
[ ] Credential RTSP không xuất hiện trong API response/log
[ ] Quy trình xóa dữ liệu người dùng đã kiểm thử
```
