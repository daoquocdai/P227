# Cài đặt và cấu hình

## Yêu cầu

- Python 3.11 64-bit.
- Node.js 20+ và npm.
- Windows 10/11 hoặc Linux x86-64.
- Webcam, video file hoặc RTSP source cho vision.
- Khoảng trống đĩa bổ sung cho PyTorch và model weights.

Wheel có nhãn `win_amd64` dùng đúng cho cả CPU Intel 64-bit và AMD 64-bit.

## Cài đặt trên Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e vision\torchlight

Copy-Item .env.example .env
cd frontend
npm ci
Copy-Item .env.example .env
cd ..
```

## Cấu hình backend

Giá trị local tối thiểu trong `.env`:

```dotenv
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=sqlite:///./data/app.db
CORS_ORIGINS=http://localhost:5173
```

`OPENAI_API_KEY` chỉ cần khi bật luồng LLM. Phát hiện, lưu sự kiện và cảnh báo cốt lõi vẫn phải hoạt động khi không có key.

Không commit `.env`; chỉ commit `.env.example` với placeholder.

## Khởi tạo database

```powershell
.\.venv\Scripts\python.exe -c "from src.database import initialize_database; print(initialize_database())"
```

Để có dữ liệu demo, tạo database mới từ `database/schema.sql` rồi áp dụng `database/seed.sql`. Không chạy seed lặp lại trên database đang có dữ liệu vì các ID mẫu là cố định.

## Chạy ứng dụng

```powershell
# Backend
.\.venv\Scripts\python.exe -m uvicorn src.main:app --reload --port 8000

# Frontend, terminal khác
cd frontend
npm run dev
```

Kiểm tra `http://localhost:8000/health`, `http://localhost:8000/docs` và `http://localhost:5173`.

## Chạy bằng Make

```text
make install
make db-init
make dev-backend
make dev-frontend
make check
```

Trên Windows cần GNU Make; nếu không có, dùng trực tiếp các lệnh PowerShell phía trên.
