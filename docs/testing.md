# Kiểm thử GuardianCam

Tài liệu này mô tả các bước kiểm tra được hỗ trợ trong current checkout.

## Chuẩn bị môi trường

Hoàn thành phần cài đặt trong [QUICKSTART.md](../QUICKSTART.md), bao gồm package
SDA editable và dependency dành cho phát triển:

```cmd
.venv\Scripts\activate
python -m pip install -e .\SDA-GCN
python -m pip install -r requirements\dev.txt
cd frontend
npm.cmd ci
cd ..
```

## Kiểm tra tự động

Chạy từ thư mục gốc repository:

```cmd
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m ruff format --check src tests
cd frontend
npm.cmd run build
cd ..
git diff --check
```

`pytest` kiểm tra API, persistence, camera services, event contracts và Vision
integration. Frontend build kiểm tra TypeScript và khả năng đóng gói Vite.

Các test boundary inject mock/model-free seams ở application layer; chúng không
biến `CameraRuntime`/`VisionManager` thành production Vision path. Regression
scope gồm latest-frame/source epoch, restore desired state, supplied face
gallery, Known/Unknown và face-miss inconclusive, Fall độc lập Identity,
ProductPolicy/cooldown, privacy snapshot fail-closed, event persistence/SSE và
hardware resolver/reporting.

## Smoke test khi chạy ứng dụng

Sau khi backend và frontend đã khởi động theo Quickstart:

```cmd
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/status
curl http://127.0.0.1:8000/api/v1/cameras
```

Kết quả mong đợi là HTTP 200. Sau đó kiểm tra tuần tự camera start/stop, raw
stream, Vision enable/disable, Identity và dữ liệu lịch sử. Với Fall Detection,
chỉ sử dụng video ngã quay sẵn an toàn; không thực hiện ngã thật để thử nghiệm.

## Điều kiện môi trường

- Chỉ cài một profile Vision phù hợp với máy.
- Identity unavailable phải được cô lập; Vision/Fall vẫn chạy khi thiếu `buffalo_l`.
- Không cần OpenAI API key khi `ALERT_AGENT_ENABLED=false`.
- Test tự động cô lập native model ở application boundary; smoke/E2E mới xác
  nhận camera, model và accelerator trên máy chạy thực tế.
- Native smoke phải xác nhận webcam/video/RTSP cần dùng, model assets, effective
  Action/Identity provider và restart restore trên chính hardware mục tiêu.
- Dùng prerecorded fall video; không thực hiện fall vật lý nguy hiểm.
