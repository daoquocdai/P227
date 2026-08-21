# GuardianCam Quickstart — Windows CMD

Luồng ngắn nhất để chạy backend, frontend và canonical Vision trên Windows.
Chạy native nếu dùng webcam USB; Docker phù hợp hơn với video file/RTSP.

## 1. Chuẩn bị

- Git
- Python 3.11 64-bit
- Node.js 20+

```cmd
git --version
python --version
node --version
npm.cmd --version
```

## 2. Clone và tạo môi trường sạch

Repo mới:

```cmd
git clone https://github.com/AI20K-Build-Phase-Cohort-3/P-227.git
cd P-227
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

Nếu đã cài nhầm profile hoặc từng cài nhiều biến thể Torch/ONNX Runtime/OpenCV,
**không** sửa bằng cách uninstall từng package trong môi trường cũ. Các wheel
`onnxruntime*` và `opencv*` dùng chung module nên uninstall có thể để lại hoặc
xóa nhầm file của provider khác. Đóng backend/Python đang dùng `.venv`, rồi tạo
lại toàn bộ môi trường; thao tác này không xóa `data`, model hay `.env`:

```cmd
cd /d <duong-dan-den-P-227>
if defined VIRTUAL_ENV deactivate
rmdir /S /Q .venv
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

Chọn **đúng một** dependency profile phù hợp với máy. Không cài nhiều profile
vào cùng `.venv` vì các gói ONNX Runtime và Torch của chúng loại trừ lẫn nhau.

### Intel Iris Xe / Windows

```cmd
python -m pip install -r requirements/vision-intel.txt
```

### NVIDIA CUDA 12.4

```cmd
python -m pip install -r requirements/vision-cuda.txt
```

Profile này cài PyTorch CUDA 12.4 và ONNX Runtime GPU. Kiểm tra ngay sau khi
cài; cả Torch và ORT phải nhìn thấy CUDA trước khi chạy ứng dụng:

```cmd
nvidia-smi
python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"
python -c "import torch; import onnxruntime as ort; print(ort.__version__); print(ort.get_available_providers())"
```

Kết quả mong đợi gồm `True`, tên GPU NVIDIA và
`CUDAExecutionProvider`. Lệnh ORT import `torch` trước để preload CUDA/cuDNN
DLL đi kèm PyTorch. Nếu thiếu một trong các kết quả này, không coi runtime CUDA
đã sẵn sàng; kiểm tra lại NVIDIA driver và cài lại profile trong `.venv` sạch.

### CPU fallback

```cmd
python -m pip install -r requirements/vision-cpu.txt
```

Sau profile hardware, cài InsightFace riêng với `--no-deps`. Dependency cần
thiết đã nằm trong profile; tùy chọn này ngăn InsightFace kéo thêm ORT CPU và
`opencv-python` chồng lên provider đã chọn và `opencv-contrib-python`:

```cmd
python -m pip install --no-deps -r requirements/vision-identity.txt
python -m pip install -e .\SDA-GCN
python -m pip check
python -m pip list | findstr /I "insightface onnxruntime opencv torch torchvision"
```

Danh sách phải chỉ có **một** ORT (`onnxruntime-directml`, `onnxruntime-gpu` hoặc
`onnxruntime`) và **một** OpenCV (`opencv-contrib-python`). Nếu thấy nhiều biến
thể, xóa và tạo lại `.venv` bằng quy trình trên.

Cài frontend và tạo `.env`:

```cmd
cd frontend
npm.cmd ci
cd ..
copy /Y .env.example .env
```

## 3. Kiểm tra model và Identity

Canonical Fall Vision cần:

```text
src\vision\yolov8n.pt
SDA-GCN\config\production.yaml
SDA-GCN\weights\fall-detection-joint.pt
```

Giữ cấu hình sau nếu chưa cài InsightFace `buffalo_l`:

```dotenv
VISION_ENGINE=canonical
VISION_DEVICE=auto
VISION_IDENTITY_ENABLED=false
```

Muốn bật `Phát hiện người lạ`, đảm bảo thư mục sau tồn tại rồi đổi thành
`VISION_IDENTITY_ENABLED=true`:

```text
<VISION_INSIGHTFACE_ROOT>\models\buffalo_l\
```

Known-person profiles được đăng ký từ UI/API và lưu trong SQLite. Không cần copy
ảnh vào `register face`.

Nếu chỉ muốn kiểm tra backend/frontend không cần AI thật:

```dotenv
VISION_ENGINE=mock
VISION_IDENTITY_ENABLED=false
```

## 4. Chạy

CMD 1 — backend:

```cmd
cd /d <duong-dan-den-P-227>
.venv\Scripts\activate
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

Chờ log:

```text
Application startup complete.
Uvicorn running on http://127.0.0.1:8000
```

CMD 2 — frontend:

```cmd
cd /d <duong-dan-den-P-227>\frontend
npm.cmd run dev
```

Mở:

- <http://localhost:5173>
- <http://127.0.0.1:8000/docs>
- <http://127.0.0.1:8000/health>

## 5. Smoke check

CMD 3:

```cmd
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/status
curl http://127.0.0.1:8000/api/v1/cameras
curl http://127.0.0.1:8000/api/v1/alerts
```

Backend tự restore desired state từ SQLite. Trên Camera page:

- Vision ON đồng nghĩa Fall Detection luôn ON.
- `Hiện khung` chỉ ẩn/hiện overlay.
- `Phát hiện người lạ` bật/tắt identity inference và Unknown alerts.
- Video vẫn phải realtime khi Vision chậm; overlay có thể hơi stale nhưng chỉ
  được dùng trong giới hạn `0.75s` và cùng source epoch.

Dừng frontend/backend bằng `Ctrl+C`. Chờ terminal backend hoàn tất shutdown;
nếu port vẫn bị giữ, xác định đúng PID trước khi dừng process.

## 6. Chạy test

Từ root:

```cmd
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests
cd frontend
npm.cmd run build
cd ..
git diff --check
```

## 7. Docker tùy chọn

```cmd
docker compose config --quiet
docker compose up --build --detach
docker compose ps
docker compose logs --follow --tail=200
```

Docker profile là CPU-only. Dừng mà vẫn giữ data/model:

```cmd
docker compose down
```

Không thêm `--volumes` nếu muốn giữ InsightFace model volume.

## 8. Lỗi nhanh

### Frontend báo `ECONNREFUSED`

```cmd
curl http://127.0.0.1:8000/health
netstat -ano | findstr :8000
```

Nếu alerts, cameras và overview cùng `ECONNREFUSED`, backend không còn listen.

### Port 8000 đã dùng

```cmd
netstat -ano | findstr :8000
tasklist /FI "PID eq <PID>"
```

### Camera đen

Kiểm tra camera `status=online`, `stream_ready=true`, preview trả JPEG và Browser
Network có MJPEG response. Vision status không quyết định Camera online/offline.

### Vision lỗi

```text
GET /api/v1/cameras/{id}/vision/status
```

Kiểm tra `current_error` và realtime metrics tại endpoint trên. Backend ghi
hardware/backend đã chọn vào startup log; đối chiếu log đó với model paths và
InsightFace root. Chi tiết tại [docs/setup.md](docs/setup.md).
