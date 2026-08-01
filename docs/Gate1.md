# TÀI LIỆU GATE 1: GUARDIANCAM HOME

---

## 1-PAGE BRIEF: GUARDIANCAM HOME

* **Tên đề tài:** GuardianCam Home - An ninh gia đình on-device: phát hiện người lạ & té ngã người già.
* **Mục tiêu cốt lõi:** Xây dựng hệ thống camera an ninh gia đình xử lý hoàn toàn cục bộ (On-device), giải quyết triệt để rủi ro rò rỉ quyền riêng tư video qua cloud. Loại bỏ thông báo rác do thú cưng/bóng râm, đồng thời tích hợp phát hiện té ngã cho người già sống một mình với độ trễ tối thiểu thông qua phân tích chuỗi thời gian.
* **Persona mục tiêu đủ hẹp:** Gia đình có người cao tuổi sống một mình hoặc con cái đi làm xa cần giám sát an ninh ngoại vi và sức khỏe người thân. Khách hàng yêu cầu tuyệt đối về bảo mật hình ảnh cá nhân và không muốn phụ thuộc vào dịch vụ lưu trữ đám mây trả phí có nguy cơ lộ lọt dữ liệu.

---

## PRODUCT REQUIREMENTS DOCUMENT (PRD)

### 1. Problem Statement (Phát biểu nỗi đau)
"Các hệ thống camera an ninh truyền thống bắt buộc phải đẩy luồng video thô lên Cloud để xử lý AI, dẫn đến nguy cơ lộ lọt hình ảnh nhạy cảm trong không gian riêng tư của gia đình, tiêu tốn băng thông đường truyền. Đồng thời, người dùng gặp phiền toái nghiêm trọng vì các thông báo báo động giả liên tục (do thú cưng, bóng râm, chuyển động lá cây) và đối mặt với nguy cơ bỏ sót các tình huống khẩn cấp như người già té ngã bất động khi ở nhà một mình."

### 2. AI Leverage (Lý do sắc bén về AI)
* **Xử lý On-device toàn diện:** Sử dụng các mô hình siêu nhẹ (YOLOv8-nano, MobileFaceNet chạy qua ONNX/TFLite) kết hợp Pose Estimation để nhận diện người, khuôn mặt và trích xuất khung xương ngay trên thiết bị biên mà không gửi frame video thô ra ngoài internet.
* **Time-series & Agent lập luận ngữ cảnh:** Xử lý bài toán ngã theo chuỗi thời gian (Time-series action detection) thay vì ảnh tĩnh để phân biệt ngã thật và chủ động nằm. Kết hợp **Security Orchestration Agent** để phân tích ngữ cảnh thời gian, không gian (ví dụ: phân biệt người lạ xuất hiện lúc 2h sáng với người nhà đi làm về muộn), từ đó giảm triệt để báo động giả và tự động quyết định hành động (báo cáo, hú còi).
* **Guardrails & An toàn tuyệt đối:** Làm mờ/ẩn danh khuôn mặt người lạ, mã hóa cục bộ toàn bộ dữ liệu lưu trữ, ưu tiên tuyệt đối chỉ số Recall cho bài toán phát hiện té ngã.

### 3. MVP Scope (Phạm vi sản phẩm tối thiểu)
* **Tính năng cơ bản (Core MVP):**
  * App phát hiện người lạ & té ngã trên video mô phỏng (staged data), hiển thị cảnh báo trực quan có mô tả ngữ cảnh từ Agent.
  * Đăng nhập phân quyền vai trò (Thành viên gia đình & Quản trị/Người chăm sóc).
  * Cơ chế HITL (Human-in-the-Loop) để người dùng bấm xác nhận báo động Đúng/Sai, giúp hệ thống học hỏi. Tính năng làm mờ danh tính người lạ chưa rõ ràng (Uncertain).
* **Công nghệ & Kiến trúc:**
  * Computer Vision: YOLOv8-nano + MobileFaceNet + YOLO-Pose (ONNX/TFLite).
  * Backend Agent: FastAPI + Logic phân tích chuỗi thời gian | Frontend: React/Vite (Family Dashboard) | Giao tiếp: MQTT | Triển khai: Docker Compose.

### 4. Metrics (Thước đo đánh giá)
* **Fall Detection Recall:** Đạt > 95% (Ưu tiên tuyệt đối an toàn, không được bỏ sót sự cố té ngã bất động của người già).
* **False Alarm/Hour (Intrusion & Fall):** Giảm thiểu tối đa báo động giả (False Positive) do vật nuôi, bóng râm hoặc người ngồi chơi dưới sàn (Mục tiêu: < 1 cảnh báo giả/giờ/camera).
* **Edge Performance:** Tốc độ xử lý khung hình đạt >= 15 FPS trên phần cứng biên, độ trễ cảnh báo (Time-to-alert) < 10 giây kể từ khi kết thúc cú ngã.

---

## WIREFRAME & UI FLOW (Luồng giao diện)

### 1. Màn hình Đăng nhập (Login Screen):
* Người dùng chọn vai trò (Thành viên hoặc Quản trị/Người chăm sóc).
* Xác thực bảo mật cục bộ.

### 2. Bảng điều khiển chính (Dashboard):
* Hiển thị danh sách các camera đang kết nối (Active/Offline) và FPS hiện tại.
* Luồng video trực tiếp (tùy chọn bật/tắt) đã được tự động làm mờ danh tính người lạ.
* Một góc hiển thị Agent Log (dòng suy luận của hệ thống).

### 3. Màn hình Cảnh báo khẩn cấp (Alert Stream):
* Nhận push notification kèm đoạn mô tả bằng tiếng Việt (ví dụ: *"Phát hiện người lạ ở hành lang lúc 2h sáng"* hoặc *"Phát hiện sự cố té ngã bất động tại phòng khách”*).
* Giao diện HITL Popup cho phép bấm xác nhận: **Báo động thật (True Positive)** hoặc **Báo động giả (False Positive)** để dán nhãn dữ liệu thực tế.

### 4. Màn hình Quản lý thành viên & Cài đặt:
* Đăng ký khuôn mặt thành viên gia đình (tránh báo động giả cho người quen).
* Thiết lập khung giờ an ninh (temporal logic) và ngưỡng thời gian nằm bất động (5s, 10s, 30s).

---

## GITHUB REPO SETUP (Cấu trúc mã nguồn Monorepo)

```text
guardiancam-home/
│
├── docs/                  # Tài liệu
├── data_collection/       # Chứa Staged videos để test (Ngã thật, Hành vi nhiễu)
│
├── src/                   # 1. BACKEND & AI AGENT (FastAPI)
│   ├── agents/            # Orchestration Agent (State, Workflow, Tools)
│   ├── api/               # Router quản lý cảnh báo, lịch sử
│   └── main.py            # Khởi chạy Uvicorn & Lắng nghe MQTT
│
├── frontend/              # 2. FRONTEND DASHBOARD (React)
│   ├── src/components/    # UI (AlertPopup, HITL buttons, FaceEnrollment)
│   └── src/pages/         # Dashboard views
│
├── edge_ai/               # 3. EDGE INFERENCE (CV Models)
│   ├── models/            # Weights của YOLO, Pose, FaceNet (ONNX/TFLite)
│   ├── core/              # Logic Time-series Fall Detection
│   └── main_edge.py       # Pipeline phân tích frame & đẩy MQTT Event
│
├── docker-compose.yml     # Khởi chạy đồng bộ toàn hệ thống cục bộ
└── .env                   # Quản lý Database URL, MQTT port
