B1: pip install -r requirements
B2: pip install -e torchlight
B2.1: từ repository root cài package Vision reusable:

```powershell
pip install -e .\SDA-GCN
python -c "import sda_vision; print(sda_vision.__file__)"
```
B3; chạy file recognize/capture_data.py để đăng kí khuôn mặt,bấm c để bắt đầu lấy ảnh, c để dừng. Muốn thoát thì bấm q
Muốn chạy thì chạy file realtime.py.

Hardware backend:

```powershell
python realtime.py                    # auto: NVIDIA CUDA > AMD ROCm/DirectML > OpenVINO GPU > CPU
python realtime.py --device cpu       # manual override
python realtime.py --device cuda
python realtime.py --device amd
python realtime.py --device intel
```

Mặc định application chạy standalone, hiển thị annotated frame trong cửa sổ
OpenCV và không gửi request tới P-227 backend. Nhấn `q` để thoát.

```powershell
python realtime.py --preview web       # http://127.0.0.1:8001/
python realtime.py --preview none      # inference không render
python realtime.py --send-events       # opt-in async event delivery
python realtime.py --send-events --backend-url http://127.0.0.1:8000/api/v1/vision/events
python realtime.py --identity off      # Fall Detection without loading/running InsightFace
python realtime.py --vision-fps 15 --identity-interval 0.5 --face-det-size 416
python realtime.py --rebuild-face-cache
python realtime.py --log-level debug --identity-debug
```

Nguồn vào có thể là camera index (mặc định `0`) hoặc video local. Video được
phát theo timeline realtime và tự thoát sạch tại EOF:

```powershell
python realtime.py --source 0 --device auto --identity on
python realtime.py --source 1 --device auto --identity on
python realtime.py --source "D:\Videos\fall_test.mp4" --device auto --identity off
```

Chỉ dùng `--source-fps 30` khi cần override metadata FPS video bị thiếu/sai.

## Reusable package API

Standalone CLI và tích hợp application dùng chung một implementation trong
`sda_vision`. Public surface cố ý nhỏ:

```python
from sda_vision import (
    VisionCallbacks,
    VisionDetection,
    VisionEvent,
    VisionFrameResult,
    VisionSession,
    VisionSessionConfig,
)
```

`VisionSession` phát structured result/event qua callback. HTTP event delivery,
OpenCV window và Flask MJPEG là standalone adapters; core không import FastAPI,
SQLite hoặc `src.*`. Các module `runtime.*` cũ chỉ là compatibility re-export và
không chứa implementation thứ hai.

MediaPipe chạy asynchronous. Metric `pose_callback_latency_ms` là thời gian từ
lúc submit frame tới callback tương ứng; `total_vision_ms` là processing time của
camera-loop cycle hiện tại. `sda_gcn_inference_ms` là `N/A` ở cycle không chạy
SDA-GCN. Thời gian model init/export/compile và warmup được log riêng lúc startup.
Các metric `*_window_avg_ms` chỉ lấy trung bình những inference thực sự xảy ra
trong cửa sổ 30 frame; chúng không reuse latency từ cửa sổ trước.

Realtime orchestration dùng capture producer + latest-frame slot, Fall scheduler
15 Hz và Identity process riêng. Identity input queue có `maxsize=1`; frame cũ
được thay bằng frame mới thay vì tạo backlog. Identity association hiện dựa trên
presence timeout và IoU của bbox MediaPipe, không phải person tracker thật.

Identity states: `UNVERIFIED`, `KNOWN`, `UNKNOWN`, `LOCKED_KNOWN`,
`LOCKED_UNKNOWN`. Known match được lock cho tới khi person biến mất hoặc bbox
association thay đổi; unknown retry sau cooldown và lock sau số lần thất bại.
InsightFace chỉ load detection + recognition modules ở detector size mặc định
416x416.

Registered embeddings được cache incremental tại
`work_dir/identity_cache/identity_gallery.npz`. Cache lưu metadata path/size/mtime
và embedding từng ảnh, dùng atomic replace, tự rebuild nếu corrupt hoặc
recognition-model fingerprint thay đổi. Worker chưa ready sẽ không nhận live
identity jobs.

`--log-level info` in metrics gọn và chỉ log Identity state transitions. Debug
thêm queue/rate metrics, third-party initialization detail; `--identity-debug`
thêm kết quả từng matching attempt nhưng không log embedding.

Cài `requirements.txt` cùng đúng một file backend phù hợp. CUDA/ROCm PyTorch
wheel phải được cài theo hướng dẫn của pytorch.org; không trộn các backend wheel.
OpenVINO export của SDA-GCN được cache trong `work_dir/runtime_cache/`.

MediaPipe Tasks Python hiện không cung cấp OpenVINO execution provider. Vì vậy
pose giữ nguyên MediaPipe CPU để không thay đổi keypoint/preprocessing; SDA-GCN
dùng OpenVINO GPU trên Intel khi conversion và compile thực tế thành công.
Lệnh tải model mediapipe:
 Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task" -OutFile "pose_landmarker_full.task"
