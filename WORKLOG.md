# Worklog — Team T-227

> Ghi lại tất cả công việc đã làm theo ngày. Ai làm gì, kết quả gì.
>
> **Nguồn:** lịch sử commit của repository P227, branch `main`.
> **Quy ước:** cột `Time` để `-` vì Git history không cung cấp thời lượng làm việc thực tế. Các commit cùng ngày có nội dung liên quan được gom thành một task để Worklog dễ đọc.

---

## 2026-08-01

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Hoàn thiện tài liệu khởi tạo GuardianCam Home và dựng backend ban đầu | ✅ Done | `c5d3bb75`, `fa957aad` | - |
| GitHub: `trong20033` | Thêm frontend GuardianCam và cấu hình bỏ qua file sinh tự động | ✅ Done | `a9ff4359`, `f9f45607` | - |
| Đào Quốc Đại | Hợp nhất tài liệu GuardianCam Home vào nhánh chính của dự án | ✅ Done | `ba70cd41` | - |

**Tổng kết ngày:** Repository đã có tài liệu sản phẩm ban đầu, backend cơ bản và frontend đầu tiên để bắt đầu triển khai hệ thống.

---

## 2026-08-03

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Bổ sung sơ đồ kiến trúc cho dự án | ✅ Done | `dcee632f` | - |
| GitHub: `trong20033` / `trongndph53331` | Phát triển frontend v2, SQLite, Family Directory và chỉnh layout cảnh báo | ✅ Done | `da7affbd`, `8952940f`, `cbbb31f6` | - |
| Đào Quốc Đại | Hợp nhất các thay đổi frontend vào lịch sử dự án | ✅ Done | `fa7e350c` | - |

**Tổng kết ngày:** Frontend được mở rộng đáng kể, bổ sung persistence bằng SQLite và tài liệu kiến trúc.

---

## 2026-08-04

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Sửa backend và kết nối backend với frontend | ✅ Done | `202309b9`, `35c1fee3` | - |
| Đào Quốc Đại | Hợp nhất nhánh backend/frontend | ✅ Done | `01e0ada6` | - |

**Tổng kết ngày:** Backend và frontend bắt đầu hoạt động như một hệ thống thống nhất thay vì hai phần tách rời.

---

## 2026-08-05

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đỗ Đình Thi | Bổ sung code nhận diện té ngã cho Vision | ✅ Done | `9fee7743` | - |

**Tổng kết ngày:** Thành phần AI nhận diện té ngã được đưa vào codebase để chuẩn bị tích hợp với hệ thống.

---

## 2026-08-06

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Tách Vision thành module riêng và tích hợp module Vision vào ứng dụng | ✅ Done | `afb7706a`, `766c070a` | - |
| Đào Quốc Đại | Sửa dependency/requirements phục vụ Vision | ✅ Done | `558270a4` | - |
| Đào Quốc Đại | Đồng bộ tài liệu với kiến trúc single-hub và tăng ổn định backend/frontend | ✅ Done | `5a240e88`, `44e4d996` | - |

**Tổng kết ngày:** Vision được tổ chức lại thành module độc lập hơn, đồng thời tài liệu và dependency được đồng bộ với kiến trúc của dự án.

---

## 2026-08-09

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Hoàn thiện luồng video và luồng E2E với mock Vision | ✅ Done | `9f39da74`, `f2c9f6a4`, `e47eeaff` | - |
| Đào Quốc Đại | Tích hợp Legacy Vision V1 với temporal fidelity tracking | ✅ Done | `2a16ec72` | - |
| Đào Quốc Đại | Cấu hình Git ignore và chuyển video sang Git LFS | ✅ Done | `0d7ef255`, `fa1e4995`, `f64c973e` | - |

**Tổng kết ngày:** Luồng video và E2E được hoàn thiện, Vision V1 được nối vào hệ thống và file video lớn được quản lý bằng Git LFS.

---

## 2026-08-10

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Sửa lỗi frontend, làm sạch Vision và tích hợp Vision V2 | ✅ Done | `8d1bfa0a`, `c0e56b8d` | - |
| Đào Quốc Đại | Sửa các vấn đề sau review và ngăn frontend polling chồng lặp | ✅ Done | `aecdc50a`, `48fe2fe6` | - |
| Đào Quốc Đại | Dọn file lỗi tạm và hoàn tất merge Vision V2 backend/frontend | ✅ Done | `6ab6ba0a`, `fc4925e4` | - |

**Tổng kết ngày:** Vision V2 được tích hợp sâu hơn với backend/frontend; frontend được chỉnh để ổn định hơn khi polling và đọc dữ liệu.

---

## 2026-08-11

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Sửa các vấn đề PR/merge và lỗi tích hợp sau khi hợp nhất Vision V2 | ✅ Done | `6b58e23c`, `d109ed94`, `71ee68b3`, `b1fe5721` | - |
| Đào Quốc Đại | Dọn dependency/requirements thừa và hợp nhất nhánh develop | ✅ Done | `fd47ee1e`, `930567a9` | - |

**Tổng kết ngày:** Các lỗi hậu merge được xử lý và dependency được dọn lại để codebase ổn định hơn.

---

## 2026-08-12

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| AI Assistant (automation) | Tái cấu trúc và tối ưu `realtime.py` | ✅ Done | `954db27e` / lịch sử tương đương | - |

**Tổng kết ngày:** Có commit do AI Assistant thực hiện; Worklog giữ nguyên tác giả automation và không quy gán cho thành viên cụ thể.

---

## 2026-08-13

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| GitHub: `trongndph53331` | Thêm authentication và phân quyền tài khoản | ✅ Done | `9a0904cf` | - |

**Tổng kết ngày:** Hệ thống được bổ sung lớp xác thực và quyền truy cập người dùng.

---

## 2026-08-14

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Nâng cấp độ ổn định tổng thể của hệ thống | ✅ Done | `1f9853d8` | - |

**Tổng kết ngày:** Tập trung xử lý các vấn đề ổn định trước khi tiếp tục tối ưu Vision và cảnh báo.

---

## 2026-08-15

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Cải thiện hiệu suất thông báo và đơn giản hóa Vision flow, tăng regression test | ✅ Done | `2ed11b21`, `f1e59f71` | - |
| GitHub: `trongndph53331` | Thêm dashboard thống kê và thu thập system metrics | ✅ Done | `47bdc0c3` | - |
| Đào Quốc Đại | Hợp nhất runtime Vision theo phần cứng và sửa cấu hình thư viện/dependency | ✅ Done | `d94f4f56`, `1846f06c`, `b863082b` | - |
| Đào Quốc Đại | Bổ sung thống kê metrics và cooldown cho cảnh báo | ✅ Done | `0fba04c9`, `f98e09a9` | - |

**Tổng kết ngày:** Vision được tối ưu cả luồng xử lý lẫn runtime phần cứng, đồng thời hệ thống có thêm metrics và cơ chế kiểm soát cảnh báo.

---

## 2026-08-16

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Tích hợp agent vào hệ thống và bổ sung evidence | ✅ Done | `c3dc6f5e`, `b1ad751b` | - |
| Nguyễn Đức Mạnh | Bổ sung ví dụ Queries phục vụ sử dụng/kiểm thử hệ thống | ✅ Done | `20b647aa` | - |
| Đào Quốc Đại | Hợp nhất nhánh tối ưu Vision performance | ✅ Done | `3dfd0225` | - |

**Tổng kết ngày:** Dự án mở rộng sang agent, evidence và hoàn thiện thêm phần tài liệu/truy vấn mẫu.

---

## 2026-08-18

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| GitHub: `trongndph53331` | Tái cấu trúc SDA-GCN và dọn dẹp Vision | ✅ Done | `1ecfcc02` | - |
| Đào Quốc Đại | Hợp nhất thay đổi tái cấu trúc SDA-GCN vào dự án | ✅ Done | `d8d8d64f` | - |

**Tổng kết ngày:** SDA-GCN được tổ chức lại để giảm phần Vision dư thừa và thuận lợi hơn cho tích hợp production.

---

## 2026-08-21

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Dọn repository và thống nhất quy trình setup | ✅ Done | `4b85a09e` | - |
| Đào Quốc Đại | Hoàn thiện CI dependency và test runner cho SDA package | ✅ Done | `5cac1766`, `5d5ad249` | - |
| Đào Quốc Đại | Tăng tốc Action/Identity theo capability phần cứng | ✅ Done | `992b87a6` | - |
| Đào Quốc Đại | Sửa alert, snapshot và dữ liệu bounding box | ✅ Done | `fbc1dcd3` | - |

**Tổng kết ngày:** Codebase được chuẩn hóa setup/CI, Vision được tăng tốc theo phần cứng và các lỗi liên quan alert/snapshot/bounding box được sửa.

---

## 2026-08-22

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| GitHub: `trongndph53331` | Đồng bộ tài liệu setup, API và architecture với nhánh develop | ✅ Done | `2545ca53` | - |

**Tổng kết ngày:** Tài liệu kỹ thuật được cập nhật để phản ánh đúng trạng thái triển khai hiện tại.

---

## 2026-08-23

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Nguyễn Đức Mạnh | Thêm agent chatbot và chức năng phân loại mức độ nguy hiểm | ✅ Done | `241aba8c` | - |
| Nguyễn Đức Mạnh | Dọn file log/error tạm khỏi repository | ✅ Done | `2cd6935e` | - |

**Tổng kết ngày:** Agent được mở rộng để hỗ trợ chatbot và phân loại nguy hiểm, đồng thời repository tiếp tục được làm sạch.

---

## 2026-08-24

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Hợp nhất nhánh develop vào lịch sử chính đang theo dõi | ✅ Done | `2ba9ca9b` | - |

**Tổng kết ngày:** Các thay đổi phát triển gần nhất được gom về một trạng thái tích hợp chung.

---

## 2026-08-25

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Hợp nhất nhánh test vào dự án | ✅ Done | `bdf45f12` | - |

**Tổng kết ngày:** Bộ thay đổi trên nhánh test được merge để củng cố khả năng kiểm thử của dự án.

---

## 2026-08-27

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đỗ Đình Thi | Bổ sung Mock SLM, YOLO Object Caching và Vision Web Contracts | ✅ Done | `9c1a462b` | - |

**Tổng kết ngày:** Vision có thêm mock SLM, cơ chế cache object YOLO và contract phục vụ tích hợp với web.

---

## 2026-08-28

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Sửa luồng video và hợp nhất thay đổi từ develop/SDA-GCN | ✅ Done | `145c0ab5`, `0dc87d3a`, `2cf1661e` | - |
| Đào Quốc Đại | Sửa lỗi frontend phát sinh sau merge | ✅ Done | `eb6d20b` | - |

**Tổng kết ngày:** Luồng video và quá trình hợp nhất SDA-GCN được xử lý, sau đó frontend được sửa để ổn định lại sau merge.

---

## 2026-08-29

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Ổn định Identity, thống nhất overlay và chuẩn hóa Vision input | ✅ Done | `4b46fe70` | - |

**Tổng kết ngày:** Identity lifecycle, cách hiển thị overlay và không gian đầu vào Vision được chuẩn hóa trong một đợt refactor lớn.

---


## 2026-09-01

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Nguyễn Đức Mạnh | Bổ sung tra cứu sự cố theo tên người thân và cập nhật link model Hugging Face | ✅ Done | `4afa80a4` | - |

**Tổng kết ngày:** Agent/tra cứu sự cố được mở rộng theo tên người thân và tài liệu/link model được cập nhật.

---

## 2026-09-02

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Đào Quốc Đại | Merge nhánh `test` vào `main` qua Pull Request #17 | ✅ Done | `f5acb612` | - |

---

## Ghi chú về độ đầy đủ

- Worklog này được dựng theo **lịch sử commit của branch `main`**.
- Git history cung cấp thời điểm commit nhưng không cho biết thời lượng làm việc thực tế, vì vậy cột `Time` được để `-`.
- Các commit cùng ngày có nội dung liên quan được gom thành một task để Worklog dễ đọc; mã commit vẫn được giữ ở cột `Output` để truy vết.
- Ánh xạ tài khoản team dùng trong Worklog:
  - `daoquocdai`  → **Đào Quốc Đại**
  - `manhndgenius` → **Nguyễn Đức Mạnh**
  - `thithi777` → **Đỗ Đình Thi**
  - `trongndph53331` → **Nguyễn Đúc Trọng**
