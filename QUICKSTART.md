# GuardianCam Quickstart — Windows CMD

Hướng dẫn chạy hệ thống Phase 5 hiện tại trên Windows. Với webcam USB, nên chạy native.

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
python -m pip check
python -m pip list | findstr /I "insightface onnxruntime opencv torch"
cd frontend
npm.cmd ci
cd ..
copy /Y .env.example .env
```

Chỉ nên có một gói `onnxruntime*` và một OpenCV (`opencv-contrib-python`).
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

## 3. Khởi động và API smoke

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

## 4. Checklist E2E tuần tự

1. Khởi động backend, chờ `Application startup complete`.
2. Khởi động frontend và xác nhận dashboard tải được.
3. Chạy ba API smoke ở trên.
4. Start webcam từ Camera UI.
5. Xác nhận raw stream chuyển động bình thường.
6. Tắt Vision: raw stream phải tiếp tục.
7. Bật Vision: Fall Detection và overlay phải khởi động.
8. Bật `Phát hiện người lạ`/Identity.
9. Family Known: tạo person, thêm ảnh mặt hợp lệ, không restart camera/backend,
   đứng trong khung; phải thấy `KNOWN`, đúng tên và không có Unknown alert.
10. Unknown: dùng người chưa đăng ký; mong đợi
    `UNVERIFIED → UNKNOWN → LOCKED_UNKNOWN`. Không có khuôn mặt dùng được thì
    không được thành Unknown. Kiểm tra Unknown alert/history; product warning có
    cooldown xấp xỉ 60 giây.
11. Fall: chỉ dùng video ngã quay sẵn an toàn, **không tự ngã**. Mong đợi
    candidate → confirmation → `FALL_CONFIRMED`, rồi kiểm tra History/Alert.
    Không hạ threshold để ép pass. Fall phải chạy với Known, Unknown hoặc khi
    Identity tắt.
12. Kiểm tra snapshot/privacy theo chính sách hiện tại.
13. Với Agent OFF, alert/history vẫn phải hoạt động.
14. Stop camera, start lại và xác nhận stream/Vision phục hồi.
15. Dừng frontend rồi backend bằng `Ctrl+C`; chờ shutdown hoàn tất.

## 5. Quality checks

```cmd
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m ruff format --check src tests
cd frontend
npm.cmd run build
cd ..
git diff --check
```

## 6. Troubleshooting

- `ECONNREFUSED`/port 8000: dùng `curl /health` và `netstat -ano | findstr :8000`.
- Camera busy/đen: đóng app khác giữ camera, kiểm tra quyền camera và raw MJPEG.
- Sai Vision profile: tạo `.venv` sạch và chỉ cài một profile.
- SDA model initialization: kiểm tra model path, startup device log và Vision status.
- Thiếu `buffalo_l`: đặt model dưới `VISION_INSIGHTFACE_ROOT` trước khi bật Identity.
- Identity worker not ready: kiểm tra model, gallery revision và worker status.
- Nhiều ORT/OpenCV: tạo lại `.venv`; giữ một `onnxruntime*`, một
  `opencv-contrib-python`, và cài InsightFace bằng `--no-deps`.
