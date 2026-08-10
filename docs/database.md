# Database

MVP dùng SQLite tại `data/app.db`, cấu hình bằng:

```dotenv
DATABASE_URL=sqlite:///./data/app.db
```

Backend hiện chỉ hỗ trợ URL bắt đầu bằng `sqlite:///`.

## Files

- `database/schema.sql`: schema đầy đủ và constraints.
- `database/seed.sql`: dữ liệu demo cố định.
- `database/queries.sql`: truy vấn tham khảo.
- `src/database.py`: khởi tạo và runtime migrations nhỏ.

## Nhóm bảng

| Nhóm | Bảng |
|---|---|
| Người dùng | `users`, `user_permissions` |
| Gia đình | `persons`, `face_profiles` |
| Camera | `cameras`, `camera_sources` |
| Vision | `events`, `event_persons`, `fall_event_details` |
| Media | `media_assets` |
| Cảnh báo | `alerts`, `alert_actions` |
| Cấu hình | `system_settings` |
| Đánh giá | `evaluation_runs`, `inference_metrics` |

## Khởi tạo

```powershell
.\.venv\Scripts\python.exe -c "from src.database import initialize_database; print(initialize_database())"
```

Ứng dụng tự chạy schema khi chưa có bảng `events`, sau đó áp dụng migration idempotent cần thiết.

## Seed demo

`seed.sql` chứa người dùng, hai camera, event và alert mẫu. Chỉ áp dụng trên database mới. Trước khi seed lại, sao lưu hoặc dùng một file SQLite khác; seed có ID cố định và không được thiết kế để chạy lặp.

## Quy tắc dữ liệu

- Bật `PRAGMA foreign_keys = ON` cho mọi connection.
- `event_id` từ vision là khóa idempotency ở biên tích hợp.
- `alert_actions` là audit trail, không sửa lịch sử cũ.
- Face embedding là dữ liệu nhạy cảm; mã mẫu không được xem là cơ chế mã hóa production.
- File `.db` và `.sqlite3` bị Git ignore.

## Backup

Khi backend dừng ghi, sao chép `data/app.db` sang vùng backup được mã hóa. Khi hệ thống đang chạy, dùng SQLite backup API thay vì copy file tùy ý.

## Chuyển sang PostgreSQL

Chỉ nên chuyển khi cần nhiều writer, HA hoặc nhiều hub. Việc này yêu cầu repository/driver mới; thay `DATABASE_URL` thôi là chưa đủ vì implementation hiện dùng module `sqlite3` trực tiếp.
