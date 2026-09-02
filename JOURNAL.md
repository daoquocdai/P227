# Development Journal — Team T-227

# Week 1: 2026-07-26 - 2026-08-01

## Mục tiêu tuần
- Chốt đề tài và phạm vi sản phẩm.
- Tìm hiểu dataset, bài toán nhận diện ngã và nhận diện người quen.
- Setup project, AI log và phân chia nhiệm vụ ban đầu.
- Hoàn thành Gate G1.

## Nhật ký theo ngày

### 2026-07-26
- Team T-227 được thành lập với 4 thành viên.
- Họp nhóm, giới thiệu và chọn đề tài.
- Chốt **DEV-12 — GuardianCam Home: phát hiện người lạ và té ngã người già**.
- Đào Quốc Đại tiếp tục nghiên cứu sổ tay kỹ thuật chương 1–2.
- Blocker được báo cáo: không có.

### 2026-07-27
- Tiếp tục học lab/lý thuyết và phân tích đề tài đã chọn.
- Nguyễn Đức Mạnh bắt đầu tìm hiểu setup AI log.
- Đỗ Đình Thi học codelab và thảo luận đề tài.
- Nguyễn Đức Trọng làm Lab 2.
- Blocker được báo cáo: không có.

### 2026-07-28
- Tiếp tục phân tích đề tài và tìm tài liệu liên quan.
- Đỗ Đình Thi bắt đầu tìm dataset trên Kaggle.
- Nguyễn Đức Trọng tìm tài liệu cho dự án.
- Blocker được báo cáo: không có.

### 2026-07-29
- Team tham gia mentor duty để làm rõ bài toán.
- Đỗ Đình Thi đã chọn tạm một dataset cho bài toán.
- Nguyễn Đức Trọng chuẩn bị phân chia công việc sau mentor duty.
- Đào Quốc Đại tiếp tục học lab/lý thuyết và tham gia mentor duty.
- Blocker được báo cáo: không có.

### 2026-07-30
- Team tiếp tục setup project và phân chia nhiệm vụ.
- Đỗ Đình Thi chốt dataset được mô tả là từ Đại học Harvard.
- Đỗ Đình Thi báo cáo đã train mô hình nhận diện ngã với accuracy 99%.
- Các thành viên còn lại tiếp tục lab, AI log, tài liệu và thảo luận hướng phát triển.
- Blocker được báo cáo: không có.

### 2026-07-31
- Team nộp **Gate G1 — Chốt đề tài**.
- Nguyễn Đức Trọng báo cáo đã hoàn thành thiết kế giao diện và bắt đầu chia task để triển khai.
- Đỗ Đình Thi chuyển sang phần nhận diện khuôn mặt người quen.
- Đào Quốc Đại tham gia phát triển/demo hackathon song song với project.
- Blocker được báo cáo: không có.

### 2026-08-01
- Team tiếp tục làm đề tài và mentor duty.
- Đào Quốc Đại tham gia mentor duty và tiếp tục phần project.
- Đỗ Đình Thi báo cáo hoàn thành nhận diện người quen bằng InsightFace và YOLO, chuẩn bị test realtime trên máy cá nhân.
- Blocker được báo cáo: không có.

## Đã hoàn thành
- Chốt đề DEV-12 GuardianCam Home.
- Hoàn thành Gate G1.
- Tìm và thử nghiệm dataset cho nhận diện ngã.
- Có mô hình nhận diện ngã thử nghiệm đạt accuracy 99% theo báo cáo daily.
- Có phiên bản nhận diện người quen ban đầu bằng InsightFace và YOLO.
- Bắt đầu setup project, AI log, giao diện và phân chia nhiệm vụ.

## Khó khăn & Giải pháp

| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Cần làm rõ hướng đi của đề tài | Thảo luận nhóm và mentor duty | Chốt phạm vi sản phẩm và bắt đầu chia task |
| Cần dataset phù hợp cho nhận diện ngã | Tìm trên Kaggle và đánh giá nhiều bộ dữ liệu | Có dataset để bắt đầu training |
| Cần thử nghiệm nhận diện người quen | Dùng InsightFace kết hợp YOLO | Có bản thử nghiệm để chuẩn bị chạy realtime |

## Bài học
- Chốt rõ bài toán và trao đổi với mentor sớm giúp giảm rủi ro đi sai hướng.
- Nên thử nghiệm AI và dataset trước khi tích hợp vào backend/frontend.
- Các phần AI, backend, frontend và AI log có thể triển khai song song.

## Kế hoạch tuần sau
- Test realtime Vision trên máy cá nhân.
- Tiếp tục backend/frontend và kết nối các module AI.
- Thu thập/thử thêm dataset.
- Hoàn thiện luồng MVP đầu tiên.

---

# Week 2: 2026-08-02 - 2026-08-08

## Mục tiêu tuần
- Hoàn thiện backend/frontend cơ bản.
- Chạy Vision realtime bước đầu.
- Tiếp tục cải thiện dataset nhận diện ngã.
- Ghép Vision vào backend và hình thành MVP end-to-end.

## Nhật ký theo ngày

### 2026-08-02
- Đào Quốc Đại tiếp tục xây dựng backend.
- Nguyễn Đức Trọng tiếp tục xây dựng giao diện và thảo luận phân chia công việc.
- Đỗ Đình Thi đã chạy được nhận diện realtime trên máy cá nhân nhưng chưa mượt, tiếp tục tìm thêm dataset.
- Nguyễn Đức Mạnh ôn bài và theo dõi tiến độ project.
- Blocker chính thức: không có.

### 2026-08-03
- Đào Quốc Đại tiếp tục backend và trao đổi trong office hour.
- Nguyễn Đức Trọng thiết kế database và hoàn thiện frontend.
- Đỗ Đình Thi tiếp tục tìm dataset bổ sung cho nhận diện ngã.
- Nguyễn Đức Mạnh học lý thuyết và trao đổi project.
- Blocker chính thức: không có.

### 2026-08-04
- Đào Quốc Đại tiếp tục backend và đồng bộ frontend.
- Nguyễn Đức Trọng cập nhật frontend, database và họp nhóm.
- Đỗ Đình Thi tiếp tục kiểm tra/tìm dataset.
- Nguyễn Đức Mạnh tham gia project, học lý thuyết và lab.
- Blocker chính thức: không có.

### 2026-08-05
- Đào Quốc Đại báo cáo hoàn thành backend và kết nối backend với frontend.
- Nguyễn Đức Trọng tiếp tục frontend, dataset và test/fix bug.
- Đỗ Đình Thi vẫn chưa tìm được dataset bổ sung phù hợp.
- Team nộp mentor duty ngày 05/08.
- Blocker chính thức: không có.

### 2026-08-06
- Đào Quốc Đại bắt đầu thêm Vision và Agent vào dự án.
- Team quyết định tự tạo dataset thay vì tiếp tục phụ thuộc dataset bên ngoài.
- Đỗ Đình Thi bắt đầu thu thập dữ liệu từ các thành viên.
- Nguyễn Đức Trọng tiếp tục cải thiện giao diện và tìm data.
- Nguyễn Đức Mạnh tham gia tạo dataset cho dự án.
- Blocker chính thức: không có.

### 2026-08-07
- Đào Quốc Đại tiếp tục tích hợp Vision và dự kiến thêm Agent.
- Đỗ Đình Thi tiếp tục bổ sung dữ liệu tự quay của nhóm.
- Nguyễn Đức Mạnh tiếp tục học/lab và tham gia project.
- Blocker chính thức: không có.

### 2026-08-08
- Đỗ Đình Thi hoàn tất thu thập thêm data và tiến hành train nhận diện ngã để demo với mentor.
- Đào Quốc Đại đã ghép Vision vào backend và kiểm thử luồng hoạt động, tiếp tục sửa lỗi end-to-end.
- Nguyễn Đức Trọng kiểm tra dự án để hoàn thành MVP.
- Team nộp mentor duty ngày 08/08.
- Blocker chính thức: không có.

## Đã hoàn thành
- Backend đã được kết nối với frontend.
- Vision realtime đã chạy bước đầu trên máy cá nhân.
- Team chuyển hướng sang tự quay/tạo dataset để cải thiện bài toán.
- Vision được ghép vào backend và bắt đầu kiểm thử end-to-end.
- MVP bắt đầu hình thành.

## Khó khăn & Giải pháp

| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Realtime Vision chưa mượt | Tiếp tục test trên máy cá nhân và tối ưu dần | Có bản chạy được để tiếp tục tích hợp |
| Dataset bổ sung khó tìm | Quyết định tự quay/tạo dataset trong team | Có thêm dữ liệu phục vụ training |
| Luồng Vision-backend còn lỗi | Ghép Vision vào backend và test end-to-end | Xác định được các lỗi cần sửa tiếp |

## Bài học
- Tự tạo dataset có thể phù hợp hơn khi dữ liệu công khai không sát bài toán thực tế.
- Tích hợp sớm giúp phát hiện vấn đề luồng end-to-end sớm.
- Realtime performance cần được đánh giá cùng lúc với độ chính xác model.

## Kế hoạch tuần sau
- Hoàn thiện tích hợp Vision V2.
- Sửa lỗi end-to-end.
- Bổ sung metrics.
- Tiếp tục Agent và phân quyền/frontend.
- Chuẩn bị cho Gate G2.

---

# Week 3: 2026-08-09 - 2026-08-15

## Mục tiêu tuần
- Hoàn thiện tích hợp Vision vào hệ thống.
- Bắt đầu đo metrics cho Vision và luồng end-to-end.
- Hoàn thiện Agent, login/phân quyền.
- Cải thiện model nhận diện ngã và chuẩn bị Gate G2.

## Nhật ký theo ngày

### 2026-08-09
- Đào Quốc Đại tiếp tục sửa luồng hoạt động và lỗi runtime của dự án.
- Đỗ Đình Thi gần hoàn thành phần nhận diện ngã và tiếp tục cải thiện model.
- Nguyễn Đức Mạnh nhận thêm task cho dự án.
- **Gate G1 chính thức PASS**.
- Blocker chính thức: không có.

### 2026-08-10
- Đào Quốc Đại báo cáo hoàn thành tích hợp Vision vào dự án và tiếp tục sửa lỗi phát sinh.
- Đỗ Đình Thi chuẩn bị merge các branch để chạy demo.
- Nguyễn Đức Mạnh làm Agent ngữ cảnh và thông báo.
- Nguyễn Đức Trọng xây dựng login và phân quyền.
- Blocker chính thức: không có.

### 2026-08-11
- Đào Quốc Đại tích hợp Vision V2, chỉnh lại cấu trúc thư mục và bắt đầu thêm metrics.
- Đỗ Đình Thi tìm hiểu SLM, thử Ollama và Gemma.
- Nguyễn Đức Mạnh tiếp tục Agent ngữ cảnh/thông báo.
- Nguyễn Đức Trọng tiếp tục cải thiện frontend.
- Blocker chính thức: không có.

### 2026-08-12
- Đào Quốc Đại sửa lại phần kết nối Vision-backend và xác định metrics cho luồng end-to-end.
- Đỗ Đình Thi tích hợp AI lên web để demo nhận diện người quen/cảnh báo ngã và đo metrics Computer Vision.
- Nguyễn Đức Mạnh tiếp tục Agent.
- Team nộp mentor duty ngày 12/08.
- Blocker chính thức: không có.

### 2026-08-13
- Đào Quốc Đại tiếp tục làm metrics và họp nhóm hoàn thiện dự án.
- Đỗ Đình Thi báo cáo demo với mentor bị fail và chuyển sang sửa code để cải thiện nhận diện ngã.
- Nguyễn Đức Mạnh test Agent.
- Gate G2 còn 3 ngày.
- Blocker chính thức vẫn được báo cáo là không có.

### 2026-08-14
- Đào Quốc Đại bổ sung metrics cho MVP và bắt đầu thêm Agent ngữ cảnh.
- Nguyễn Đức Trọng hoàn thành frontend/backend login, tiếp tục test sản phẩm.
- Đỗ Đình Thi tiếp tục cải thiện độ phán đoán nhận diện ngã.
- Nguyễn Đức Mạnh chỉnh lại cấu trúc Agent và đo metrics.
- Blocker chính thức: không có.

### 2026-08-15
- Đào Quốc Đại cải tiến luồng hoạt động, thêm Agent ngữ cảnh và đo metrics.
- Nguyễn Đức Mạnh kiểm tra Agent và chạy thử dự án.
- Đỗ Đình Thi thử VideoPose3D, trích xuất trục Z và train lại model để tối ưu realtime.
- Team nộp mentor duty ngày 15/08.
- Gate G2 còn 1 ngày.
- Blocker chính thức: không có.

## Đã hoàn thành
- Vision được tích hợp sâu hơn vào hệ thống.
- Bắt đầu có metrics cho Computer Vision và luồng end-to-end.
- Agent ngữ cảnh/thông báo được phát triển.
- Login/phân quyền được triển khai.
- Model nhận diện ngã tiếp tục được tối ưu cho realtime.
- Gate G1 đã pass.

## Khó khăn & Giải pháp

| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Demo Vision/AI với mentor bị fail | Tiếp tục sửa code và cải thiện model | Có hướng sửa cụ thể trước Gate G2 |
| Cần đo hiệu năng toàn hệ thống | Xác định và thêm các metrics Vision/E2E | Có dữ liệu để đánh giá MVP |
| Realtime nhận diện ngã cần cải thiện | Thử VideoPose3D và retrain | Có hướng tối ưu mới cho model |

## Bài học
- Demo fail là tín hiệu quan trọng để phát hiện vấn đề trước Gate.
- Metrics cần được xây song song với tính năng để biết bottleneck nằm ở đâu.
- Agent và Vision nên được tách module rõ ràng để dễ đo và sửa lỗi.

## Kế hoạch tuần sau
- Hoàn thiện Gate G2.
- Tối ưu hiệu năng hệ thống.
- Tiếp tục sửa false positive và báo động giả.
- Chuẩn hóa Vision/backend để dễ mở rộng phần cứng.

---

# Week 4: 2026-08-16 - 2026-08-22

## Mục tiêu tuần
- Hoàn thiện và nộp Gate G2.
- Cải thiện hiệu năng Vision/backend.
- Giảm nhận dạng sai, false positive và báo động giả.
- Tái cấu trúc Vision/SDA-GCN.
- Chuẩn hóa hệ thống cho nhiều loại GPU.

## Nhật ký theo ngày

### 2026-08-16
- Đào Quốc Đại tập trung cải thiện hiệu năng hệ thống và hoàn thiện yêu cầu Gate G2.
- Nguyễn Đức Mạnh hỗ trợ hoàn thiện Gate G2.
- **Gate G2 được nộp lúc 23:42**.
- Blocker chính thức: không có.

### 2026-08-17
- Đào Quốc Đại tiếp tục cải thiện hiệu năng sau Gate G2.
- Đỗ Đình Thi tập trung tìm nguyên nhân false positive trong nhận diện ngã.
- Nguyễn Đức Trọng tiếp tục frontend, test dự án và trang thống kê.
- Nguyễn Đức Mạnh tiếp tục cải thiện project.
- Blocker chính thức: không có.

### 2026-08-18
- Nguyễn Đức Trọng tiếp tục tìm bug, cải tiến frontend và tạo dataset.
- Nguyễn Đức Mạnh tiếp tục học/lab và workshop.
- Đào Quốc Đại không có daily trong phần Discord được cung cấp cho ngày này.
- Blocker chính thức trong các daily có mặt: không có.

### 2026-08-19
- Đào Quốc Đại báo cáo đã tái cấu trúc pipeline Vision, mô-đun hóa SDA-GCN và tách logic model khỏi logic điều phối.
- Đào Quốc Đại chuyển sang đo lại metrics thủ công và thu thập evidence.
- Đỗ Đình Thi tiếp tục hoàn thiện AI nhận diện ngã.
- Nguyễn Đức Mạnh tiếp tục Agent.
- Team nộp mentor duty ngày 19/08.
- Blocker chính thức: không có.

### 2026-08-20
- Đào Quốc Đại nghiên cứu các lỗi nhận dạng sai và báo động giả, sau đó tiếp tục sửa Vision mới và backend.
- Nguyễn Đức Trọng tiếp tục frontend và dataset.
- Nguyễn Đức Mạnh tiếp tục Agent.
- Blocker chính thức: không có.

### 2026-08-21
- Đào Quốc Đại chỉnh backend theo hướng non-blocking và tiếp tục tối ưu luồng Vision → backend → frontend.
- Đỗ Đình Thi tiếp tục hoàn thiện bài toán nhận diện hành động ngã.
- Nguyễn Đức Trọng tiếp tục test và hoàn thiện dự án.
- Nguyễn Đức Mạnh tiếp tục Agent.
- Blocker chính thức: không có.

### 2026-08-22
- Đào Quốc Đại thay Vision cũ bằng Vision mới, nối lại backend và chuẩn hóa phiên bản hỗ trợ nhiều loại GPU.
- Dự kiến tiếp tục sửa luồng hoạt động chính và thêm Agent chi tiết hơn.
- Nguyễn Đức Trọng tiếp tục frontend và chuẩn bị mentor duty.
- Nguyễn Đức Mạnh tiếp tục Agent.
- Team nộp mentor duty ngày 22/08.
- Blocker chính thức: không có.

## Đã hoàn thành
- Nộp Gate G2.
- Tái cấu trúc Vision/SDA-GCN theo module.
- Backend được điều chỉnh theo hướng non-blocking.
- Vision mới được nối lại với backend.
- Bắt đầu chuẩn hóa runtime cho nhiều loại GPU.
- Tiếp tục điều tra false positive và báo động giả.

## Khó khăn & Giải pháp

| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| False positive trong nhận diện ngã | Điều tra nguyên nhân và tiếp tục cải thiện model | Có hướng xử lý rõ hơn sau Gate |
| Báo động giả/nhận dạng sai | Rà lại Vision và backend | Giảm rủi ro logic sai trong luồng cảnh báo |
| Vision cũ khó mở rộng | Tái cấu trúc SDA-GCN và tách model khỏi orchestration | Kiến trúc sạch hơn và dễ tích hợp |
| Khác biệt phần cứng | Chuẩn hóa hỗ trợ nhiều loại GPU | Hệ thống linh hoạt hơn khi chạy trên máy khác nhau |

## Bài học
- Tách model khỏi logic điều phối giúp backend ít phụ thuộc Vision internals hơn.
- Non-blocking backend quan trọng với pipeline realtime.
- False positive cần được đánh giá cùng cả model lẫn logic event/cảnh báo.

## Kế hoạch tuần sau
- Ổn định hệ thống sau tái cấu trúc.
- Tối ưu agent và frontend.
- Benchmark multi-camera/Vision.
- Chuẩn bị demo day.

---

# Week 5: 2026-08-23 - 2026-08-29

## Mục tiêu tuần
- Ổn định hệ thống sau khi thay Vision mới.
- Tối ưu Agent, frontend và trải nghiệm người dùng.
- Thử deploy web.
- Benchmark multi-camera và hiệu năng Vision.
- Chuẩn bị demo day.

## Nhật ký theo ngày

### 2026-08-23
- Đào Quốc Đại báo cáo hệ thống đã chạy ổn định với các chức năng chính.
- Tiếp tục nâng cấp hệ thống, tối ưu Agent và thử deploy lên web.
- Nguyễn Đức Trọng tiếp tục kiểm tra sản phẩm/frontend.
- Blocker chính thức: không có.

### 2026-08-24
- Đào Quốc Đại cập nhật tài liệu giới thiệu, hướng dẫn và cấu trúc dự án theo phiên bản mới.
- Nguyễn Đức Trọng tiếp tục xử lý deploy web và tối ưu hiệu năng sau deploy.
- Đỗ Đình Thi tiếp tục hoàn thiện các phần còn lại của dự án.
- Nguyễn Đức Mạnh tiếp tục cải thiện Agent.
- Blocker chính thức: không có.

### 2026-08-25
- Đào Quốc Đại hoàn thiện các tài liệu liên quan cho phase/gate và tiếp tục bổ sung chức năng mới.
- Nguyễn Đức Trọng sửa phân quyền và chỉnh frontend/backend phục vụ demo web.
- Nguyễn Đức Mạnh tiếp tục hoàn thiện/thêm mới Agent.
- Đỗ Đình Thi tiếp tục hoàn thiện các phần còn lại.
- Blocker chính thức: không có.

### 2026-08-26
- Đào Quốc Đại nghiên cứu hướng nâng cấp hệ thống, thay đổi luồng phát video và khả năng xử lý đồng thời nhiều camera.
- Nguyễn Đức Trọng tiếp tục tối ưu trải nghiệm người dùng.
- Nguyễn Đức Mạnh tiếp tục Agent.
- Team nộp mentor duty ngày 26/08.
- Blocker chính thức: không có.

### 2026-08-27
- Đào Quốc Đại benchmark Vision đa camera, xác định MediaPipe CPU và nguồn 4K là các bottleneck đáng chú ý.
- Tiếp tục đánh giá phương án giảm tải Pose và benchmark các mức FPS.
- Nguyễn Đức Trọng và Đỗ Đình Thi tiếp tục hoàn thiện dự án cho demo day.
- **Gate G2 chính thức PASS**.
- Blocker chính thức: không có.

### 2026-08-28
- Đào Quốc Đại hoàn thiện hệ thống đa camera thử nghiệm.
- Tiến hành đo hiệu năng giữa hai phiên bản để chọn hướng phát triển.
- Nguyễn Đức Trọng tiếp tục cải thiện UX và kiểm tra hệ thống sau deploy.
- Nguyễn Đức Mạnh nghiên cứu SLM.
- Blocker chính thức: không có.

### 2026-08-29
- Đào Quốc Đại sau khi so sánh đã chọn kiến trúc cũ làm hướng tiếp tục phát triển.
- Tiếp tục sửa backend để cải thiện truyền video và kết nối với chức năng Vision mới.
- Nguyễn Đức Trọng tiếp tục chuẩn bị báo cáo/demo.
- Đỗ Đình Thi tiếp tục hoàn thiện các phần còn thiếu.
- Team nộp mentor duty ngày 29/08.
- Blocker chính thức: không có.

## Đã hoàn thành
- Hệ thống ổn định với các chức năng chính.
- Có thử nghiệm deploy web.
- Bắt đầu hỗ trợ luồng nhiều camera.
- Benchmark đa camera và xác định bottleneck MediaPipe CPU/nguồn 4K.
- So sánh hai kiến trúc và chọn phương án tiếp tục phát triển.
- Gate G2 chính thức pass.

## Khó khăn & Giải pháp

| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Hiệu năng multi-camera | Benchmark thực tế và đo nhiều mức FPS | Xác định MediaPipe CPU và 4K là bottleneck |
| Khác biệt giữa hai kiến trúc | Đo hiệu năng trực tiếp | Chọn lại kiến trúc cũ để tiếp tục phát triển |
| Deploy web phát sinh vấn đề hiệu năng | Tối ưu frontend/backend và trải nghiệm người dùng | Tiếp tục cải thiện demo web |
| Luồng video và Vision mới cần đồng bộ | Sửa backend và kết nối lại chức năng Vision | Hướng tích hợp rõ hơn |

## Bài học
- Benchmark thực tế quan trọng hơn suy đoán khi chọn kiến trúc.
- Nguồn video 4K có thể gây tải lớn ngay cả khi model không đổi.
- Multi-camera cần xem xét riêng media plane và Vision plane.

## Kế hoạch tuần sau
- Tiếp tục hoàn thiện demo day.
- Sửa bug còn lại.
- Hoàn thiện Agent và frontend.
- Tiếp tục ổn định Vision/backend.

---

# Week 6: 2026-08-30 - 2026-09-05

## Mục tiêu tuần
- Hoàn thiện sản phẩm cho demo day.
- Sửa các bug còn lại.
- Hoàn thiện Agent và UI/UX.
- Ôn tập các nội dung học song song với hoàn thiện dự án.

## Nhật ký theo ngày

### 2026-08-30
- Đỗ Đình Thi tiếp tục hoàn thiện các phần còn thiếu của dự án để chuẩn bị demo.
- Các thành viên khác không có daily trong phần Discord được cung cấp cho ngày này.
- Blocker chính thức trong daily có mặt: không có.

### 2026-08-31
- Nguyễn Đức Mạnh tiếp tục hoàn thiện Agent và các phần còn thiếu.
- Nguyễn Đức Trọng tiếp tục cải thiện frontend, deploy và sửa bug.
- Đỗ Đình Thi tiếp tục hoàn thiện project cho demo day.
- Blocker chính thức: không có.

### 2026-09-01
- Đào Quốc Đại dành thời gian ôn lại kiến thức đã học.
- Nguyễn Đức Mạnh tiếp tục hoàn thiện dự án và ôn tập cho bài thi.
- Blocker chính thức: không có.

### 2026-09-02
- Đào Quốc Đại tiếp tục ôn lại kiến thức.
- Nguyễn Đức Trọng kiểm tra lại các phần cần thiết và chuẩn bị cho demo day.
- Nguyễn Đức Mạnh tiếp tục hoàn thiện dự án và ôn thi.
- Blocker chính thức: không có.

## Đã hoàn thành
- Tiếp tục hoàn thiện project phục vụ demo day.
- Agent tiếp tục được chỉnh sửa và hoàn thiện.
- Frontend/deploy tiếp tục được rà soát.
- Team bắt đầu chuyển một phần thời gian sang ôn tập.

## Khó khăn & Giải pháp

| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Cần hoàn thiện nhiều phần nhỏ trước demo | Tiếp tục rà soát bug, Agent và UI | Sản phẩm được hoàn thiện dần |
| Phải cân bằng project và ôn tập | Chia thời gian cho cả hai | Vẫn tiếp tục duy trì tiến độ dự án |

## Bài học
- Giai đoạn cuối cần ưu tiên ổn định và demo flow hơn là thêm quá nhiều chức năng mới.
- Checklist trước demo giúp tránh bỏ sót lỗi nhỏ.
- Cần cân bằng thời gian giữa project và học tập.

## Kế hoạch tiếp theo
- Hoàn thiện demo day.
- Sửa các lỗi còn lại nếu phát hiện.
- Giữ hệ thống ổn định.
- Tiếp tục hoàn thiện tài liệu/evidence nếu cần.

---

# Tổng kết Development Journal

## Các mốc chính
- **26/07:** Team T-227 hình thành và chốt đề DEV-12.
- **31/07:** Nộp Gate G1.
- **09/08:** Gate G1 PASS.
- **16/08:** Nộp Gate G2.
- **27/08:** Gate G2 PASS.
- **Cuối tháng 8:** Hệ thống chuyển sang giai đoạn ổn định, benchmark multi-camera, tối ưu Vision/backend và chuẩn bị demo day.

## Tiến trình kỹ thuật nổi bật
- Bắt đầu từ nhận diện ngã và người quen riêng lẻ.
- Kết nối backend với frontend.
- Tích hợp Vision vào backend và kiểm thử end-to-end.
- Chuyển sang Vision V2 và đo metrics.
- Tái cấu trúc SDA-GCN để tách model khỏi orchestration.
- Chuẩn hóa runtime cho nhiều GPU.
- Cải thiện backend non-blocking.
- Benchmark multi-camera và phát hiện bottleneck MediaPipe CPU/4K.
- So sánh kiến trúc và chọn phương án phù hợp hơn để tiếp tục phát triển.
- Song song phát triển Agent, authentication, frontend và deploy web.

