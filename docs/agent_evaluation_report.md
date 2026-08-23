# BÁO CÁO TỔNG HỢP VÀ ĐÁNH GIÁ HỆ THỐNG AI AGENT
## GuardianCam Local Hub (P-227)

---

## 1. TỔNG QUAN HỆ THỐNG (EXECUTIVE SUMMARY)

Dự án **GuardianCam Local Hub** là hệ thống giám sát an toàn local-first cho gia đình, cung cấp khả năng phát hiện té ngã (**Fall Detection**), nhận diện người lạ/người thân (**Stranger & Identity Recognition**), và lưu trữ nhật ký sự cố cục bộ.

Để nâng cao khả năng tự động hóa, suy luận ngữ cảnh và hỗ trợ người dùng, hệ thống đã được tích hợp thành công **3 AI Agent chuyên trách**:
1. **Reasoning / Triage Agent**: Suy luận và phân loại mức độ nguy hiểm của sự cố (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`).
2. **Security Log Q&A Assistant Agent**: Trợ lý hỏi-đáp nhật ký an ninh bằng tiếng Việt tự nhiên, có tích hợp bảo vệ Prompt Injection và từ chối câu hỏi ngoài phạm vi.
3. **Incident Summary & Timeline Generator Agent**: Tự động tổng hợp chuỗi mốc thời gian (Timeline) và viết bài tóm tắt diễn biến sự cố.

### Nguyên tắc Kiến trúc Cốt lõi:
- **Local-First & Privacy Preserved**: Dữ liệu video, ảnh snapshot và database SQLite lưu trữ 100% cục bộ. Không gửi dữ liệu thô ra internet.
- **Async & Non-Blocking**: Tất cả Agent hoạt động bất đồng bộ, không gây ảnh hưởng đến luồng suy luận realtime 15Hz của Vision Engine.
- **Dual-Layer Architecture**: Trang bị bộ máy suy luận **Deterministic Engine local** (hoạt động offline 100% không cần internet/API key) song song với **LLM Provider** (khi có OpenAI API key).

### 1.1. Các Chế độ Vận hành & Mô hình AI (Operating Modes):

Hệ thống Agent hỗ trợ **3 Chế độ Vận hành Linh hoạt (Flexible Modes)** tùy theo hạ tầng của người dùng:

| Chế độ Vận hành | Công nghệ / Mô hình | Đặc điểm & Kịch bản Sử dụng |
|---|---|---|
| **Chế độ 1: Deterministic Engine (Offline Default)** | Thuật toán Python & Parameterized SQL Queries | **Chế độ mặc định**: **100% Offline**, độ trễ $< 5\text{ms}$, 0% chi phí. Dùng khi không có API Key hoặc mất mạng. |
| **Chế độ 2: LLM Cloud (OpenAI Integration)** | OpenAI API (`gpt-4o-mini` / `gpt-5-mini`) | **Chế độ Cloud**: Dùng **Tool-Calling** hiểu ngữ cảnh tiếng Việt phức tạp khi điền `OPENAI_API_KEY`. |
| **Chế độ 3: SLM Local (Ollama / vLLM)** | Mô hình Local (`Qwen2.5-7B`, `Llama-3.2-3B`) | **Chế độ AI Cục bộ**: Sẵn sàng kết nối mô hình AI nhỏ chạy offline trên GPU nhà người dùng qua Ollama/vLLM. |

---

## 2. CHI TIẾT 3 AI AGENT MỚI DỰ ÁN

### 2.1. Reasoning / Triage Agent (Phân loại Mức độ Nguy hiểm)
- **Mã nguồn**: [`src/agents/nodes/reasoning.py`] & [`src/agents/alert_provider.py`]
- **Mục đích**: Tự động phân loại độ nghiêm trọng của sự cố dựa trên dữ liệu thực tế từ hệ thống vision.
- **Thông số đầu vào**:
  - Tư thế người dùng (`posture`: `lying`, `sitting`, `standing`, `transitioning`)
  - Thời gian nằm bất động (`immobility_duration_ms`)
  - Độ tin cậy AI (`ai_confidence`)
  - Số lần lặp lại sự cố (`occurrence_count`)
  - Trạng thái danh tính (`is_known_person`) và Vị trí camera (`location_label`)
- **Bảng phân loại mức độ (Threat Matrix)**:

| Mức độ (Severity) | Điều kiện kích hoạt | Hành vi hệ thống |
|---|---|---|
| **`CRITICAL`** | Nằm bất động > 3000ms HOẶC ngã không rõ tư thế | Cảnh báo đỏ nguy cấp, yêu cầu xác nhận khẩn |
| **`HIGH`** | Tư thế nằm `lying` HOẶC người lạ xuất hiện $\ge 5$ lần | Cảnh báo mức cao, ưu tiên xử lý |
| **`MEDIUM`** | Tư thế `sitting`/`transitioning` HOẶC người lạ lặp lại 2-4 lần | Cảnh báo mức trung bình |
| **`LOW`** | Người thân đã xác nhận HOẶC confidence AI thấp | Ghi log theo dõi, không làm phiền người dùng |

---

### 2.2. Security Log Q&A Assistant Agent (Trợ lý Hỏi-Đáp An ninh)
- **Mã nguồn**: [`src/agents/qa_agent.py`] & [`src/agents/tools/qa_tools.py`]
- **Giao diện WebUI**: [`src/components/AgentChatWidget.tsx`] (Widget chat nổi góc dưới màn hình).
- **Endpoint API**: `POST /api/v1/agent/chat`
- **Tính năng nổi bật**:
  - Trả lời thắc mắc bằng tiếng Việt tự nhiên về trạng thái camera, danh sách sự cố té ngã, người lạ và danh bạ người thân.
  - Định dạng hiển thị mượt mà: Tự động quy đổi mốc thời gian UTC sang **Giờ địa phương Việt Nam (UTC+7)** (Ví dụ: `13:26:12 ngày 23/08/2026`).
  - Phân dòng thụt lề trực quan với biểu tượng sinh động (`🔹`, `•`, `📋`).

---

### 2.3. Incident Summary & Timeline Generator Agent (Tóm tắt Sự cố & Timeline)
- **Mã nguồn**: [`src/agents/summary_agent.py`] & [`src/api/agent.py`]
- **Endpoint API**: `POST /api/v1/agent/summary/{incident_id}`
- **Tính năng nổi bật**:
  - Truy vết toàn bộ các `events` kết nối với `incident_id` qua bảng `incident_events`.
  - Khởi tạo chuỗi mốc thời gian **Timeline chi tiết** (Thời điểm kích hoạt $\rightarrow$ Các lần cập nhật posture/confidence $\rightarrow$ Thời điểm kết thúc).
  - Viết tóm tắt diễn biến (Executive Summary) và lưu trực tiếp vào trường `agent_summary` trong cơ sở dữ liệu SQLite.

---

## 3. KIẾN TRÚC BẢO MẬT VÀ AN TOÀN DỮ LIỆU (SECURITY & SAFETY)

Hệ thống Agent được bảo vệ bằng 3 lớp an ninh nghiêm ngặt:

1. **Anti-Jailbreak & Prompt Injection Guard**:
   - Tự động quét và phát hiện các mẫu lệnh cố tình can thiệp prompt hệ thống (`"ignore previous instructions"`, `"act as DAN"`, `"show system prompt"`, `"drop table"`...).
   - Lập tức từ chối và cảnh báo an ninh mà không chuyển tiếp câu lệnh tới LLM.

2. **Domain Scope Guardrail**:
   - Sử dụng bộ lọc từ khóa phạm vi (`DOMAIN_KEYWORDS`). Mọi câu hỏi ngoài vùng an ninh gia đình (thời tiết, công thức nấu ăn, kiến thức chung...) đều bị từ chối an toàn.

3. **Data Isolation & Read-Only Whitelist**:
   - Các tool truy vấn SQLite (`QATools`) được thiết kế dạng Read-Only.
   - Loại bỏ hoàn toàn các trường dữ liệu nhạy cảm (`password_hash`, `face_embedding`) khỏi danh sách truy vấn của Agent.
   - Sử dụng SQL Parameterized Queries chống lại SQL Injection.

---

## 4. KẾT QUẢ ĐÁNH GIÁ BENCHMARK VÀ KIỂM THỬ

Hệ thống đánh giá tự động [`eval/evaluate_agents.py`] đã thực hiện kiểm thử toàn bộ 3 Agent:

### Bảng Kết quả Đánh giá Benchmark (Benchmark Metrics Report)

| Hạng mục Agent | Tiêu chí Đánh giá | Kết quả (Accuracy %) | Thời gian phản hồi (Avg Latency) |
|---|---|:---:|:---:|
| **Reasoning / Triage Agent** | Khả năng phân loại đúng mức độ nguy hiểm (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) | **100.0%** | `< 0.01 ms` |
| **Security Q&A & Guardrails** | Khả năng trả lời đúng domain, từ chối câu hỏi lề & chặn Prompt Injection | **100.0%** | `5.07 ms` |
| **Incident Summary & Timeline** | Độ hoàn thiện chuỗi Timeline & khả năng ghi tóm tắt vào DB | **100.0%** | `22.48 ms` |

### Kết quả Kiểm thử Đơn vị (Unit Tests):
- **Bộ Test Agent (`tests/test_agents/`)**: `20/20 PASSED` (100%)
- **Toàn bộ Test Suite Dự án**: `260/260 PASSED` (100%)

---

## 5. HƯỚNG DẪN KHỞI CHẠY VÀ DÙNG THỬ

### 5.1. Chạy Đánh giá Tự động (Benchmark Script)
```cmd
.venv\Scripts\activate
python -m eval.evaluate_agents
```

### 5.2. Khởi chạy Ứng dụng Web
1. **Khởi động Backend**:
   ```cmd
   .venv\Scripts\activate
   python -m uvicorn src.main:app --reload --port 8000
   ```
2. **Khởi động Frontend**:
   ```cmd
   cd frontend
   npm run dev
   ```
3. Truy cập **`http://localhost:5173`** và bấm vào nút **✨ Hỏi AI An Ninh** ở góc dưới bên phải để trải nghiệm trực tiếp!
