# GuardianCam Quickstart — evaluator mới

Native Windows là đường khuyến nghị cho webcam/GPU. Docker hiện tại chỉ chạy CPU.

## 1. Cài đặt

Yêu cầu Git, Python 3.11 64-bit và Node.js 20+.

```cmd
git clone https://github.com/AI20K-Build-Phase-Cohort-3/P-227.git
cd P-227
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

Chỉ cài **một** profile hardware:

```cmd
rem Intel Iris Xe / Windows
python -m pip install -r requirements\vision-intel.txt
rem Hoặc NVIDIA CUDA 12.4
python -m pip install -r requirements\vision-cuda.txt
rem Hoặc CPU
python -m pip install -r requirements\vision-cpu.txt
rem Hoặc AMD / Windows DirectML
python -m pip install -r requirements\vision-amd.txt
```

Không trộn profile trong một `.venv`. Cài Identity riêng bằng `--no-deps` để
InsightFace không kéo thêm ORT/OpenCV xung đột:

```cmd
python -m pip install --no-deps -r requirements\vision-identity.txt
python -m pip install -e .\SDA-GCN
python -m pip install -r requirements\dev.txt
python -m pip list | findstr /I "insightface onnxruntime opencv torch"
cd frontend
npm.cmd ci
cd ..
copy /Y .env.example .env
```

Chỉ nên có một gói `onnxruntime*` và một OpenCV (`opencv-contrib-python`).
`pip check` có thể báo InsightFace thiếu `onnxruntime`/`opencv-python` dù profile
đã cung cấp ORT hardware-specific và `opencv-contrib-python`; đây là metadata
caveat. Không cài các package CPU/duplicate đó chỉ để làm `pip check` xanh.
Baseline E2E an toàn trong `.env`:

```dotenv
VISION_ENGINE=sda
VISION_DEVICE=auto
ALERT_AGENT_ENABLED=false
```

Sản phẩm chính không cần OpenAI API key. Alert Agent là tùy chọn và sẽ tiếp tục
được cải thiện; không bật nó trong lần E2E đầu tiên.

## 2. Identity hiện tại

```text
Family UI/API
  → SDA FaceEncoder
  → SQLite persons + face_profiles
  → gallery revision
  → live supplied Identity gallery
  → Identity child đang chạy
```

Không cần restart camera/backend sau khi thêm khuôn mặt. Integrated mode không
dùng `register face/` làm nguồn dữ liệu. CLI SDA standalone có thể vẫn dùng chế
độ filesystem/NPZ. Muốn bật Identity, model
`<VISION_INSIGHTFACE_ROOT>\models\buffalo_l\` phải sẵn sàng.

## 3. Khởi động, đăng nhập và API smoke

Terminal 1:

```cmd
cd /d <duong-dan-den-P-227>
.venv\Scripts\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```cmd
cd /d <duong-dan-den-P-227>\frontend
npm.cmd run dev
```

Terminal 3:

```cmd
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/status
curl http://127.0.0.1:8000/api/v1/cameras
```

Mở `http://localhost:5173` và `http://127.0.0.1:8000/docs`.

Lần khởi tạo database đầu tiên tạo admin development
`admin@example.local`. Password lấy từ `ANTAM_INITIAL_ADMIN_PASSWORD`; nếu chưa
đặt thì fallback development là `AnTam@123`. Nên đặt biến môi trường này trước
lần chạy backend đầu tiên. Đăng nhập rồi đổi ngay mật khẩu (tối thiểu 8 ký tự)
khi UI bắt buộc. Fallback không phải credential production.

## 4. Checklist E2E tuần tự

1. Khởi động backend, chờ `Application startup complete`.
2. Khởi động frontend và xác nhận dashboard tải được.
3. Đăng nhập bằng admin bootstrap và hoàn tất đổi mật khẩu bắt buộc.
4. Chạy ba API smoke ở trên.
5. Start webcam từ Camera UI.
6. Xác nhận raw stream chuyển động bình thường.
7. Tắt Vision: raw stream phải tiếp tục.
8. Bật Vision: Fall Detection và overlay phải khởi động.
9. Bật `Phát hiện người lạ`/Identity.
10. Family Known: tạo person, thêm ảnh mặt hợp lệ, không restart camera/backend,
   đứng trong khung; phải thấy `KNOWN`, đúng tên và không có Unknown alert.
11. Unknown: dùng người chưa đăng ký; mong đợi
    `UNVERIFIED → UNKNOWN → LOCKED_UNKNOWN`. Không có khuôn mặt dùng được thì
    không được thành Unknown. Kiểm tra Unknown alert/history; product warning có
    cooldown xấp xỉ 60 giây.
12. Fall: chỉ dùng video ngã quay sẵn an toàn, **không tự ngã**. Mong đợi
    candidate → confirmation → `FALL_CONFIRMED`, rồi kiểm tra History/Alert.
    Không hạ threshold để ép pass. Fall phải chạy với Known, Unknown hoặc khi
    Identity tắt.
13. Kiểm tra snapshot/privacy theo chính sách hiện tại.
14. Với Agent OFF, alert/history vẫn phải hoạt động.
15. Stop camera, start lại và xác nhận stream/Vision phục hồi.
16. Dừng frontend rồi backend bằng `Ctrl+C`; chờ shutdown hoàn tất.

Các control độc lập: Camera ON mở source; Vision ON bật Fall Detection;
`Phát hiện người lạ` bật Identity/Unknown; `Hiện khung` chỉ đổi presentation,
không bật/tắt model.

## 5. Docker CPU-only

```cmd
docker compose up --build --detach
docker compose ps
```

Mở `http://localhost:5173`. Compose ép `VISION_DEVICE=cpu` và
`VISION_IDENTITY_PROVIDER=cpu`. Dùng video file/RTSP; cấu hình hiện tại không
cam kết webcam USB passthrough trên Docker Desktop. Xem [setup](docs/setup.md)
cho volume Identity và troubleshooting.

## 6. Quality checks

```cmd
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m ruff format --check src tests
cd frontend
npm.cmd run build
cd ..
git diff --check
```

## 7. Troubleshooting

- `ECONNREFUSED`/port 8000: dùng `curl /health` và `netstat -ano | findstr :8000`.
- Camera busy/đen: đóng app khác giữ camera, kiểm tra quyền camera và raw MJPEG.
- Sai Vision profile: tạo `.venv` sạch và chỉ cài một profile.
- SDA model initialization: kiểm tra model path, startup device log và Vision status.
- Thiếu `buffalo_l`: đặt model dưới `VISION_INSIGHTFACE_ROOT` trước khi bật Identity.
- Identity worker not ready: kiểm tra model, gallery revision và worker status.
- Nhiều ORT/OpenCV: tạo lại `.venv`; giữ một `onnxruntime*`, một
  `opencv-contrib-python`, và cài InsightFace bằng `--no-deps`.
