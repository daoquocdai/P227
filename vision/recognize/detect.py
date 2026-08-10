import cv2
from ultralytics import YOLO

# 1. Load model YOLOv8 (Bản 'n' - nano là bản nhẹ nhất, chạy mượt trên CPU)
# Lần đầu chạy, YOLO sẽ tự động tải file trọng số 'yolov8n.pt' (~6MB) về máy.
model = YOLO("yolov8n.pt")

# ID của lớp 'person' trong dataset COCO mặc định của YOLO là 0
PERSON_CLASS_ID = 0

# 2. Mở Webcam (Thay 0 bằng đường dẫn video "video.mp4" nếu muốn test file video)
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Không thể mở Webcam!")
    exit()

print("Bấm phím 'q' để thoát chương trình.")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Không nhận được luồng hình ảnh từ Camera/Video.")
        break

    # Đổi kích cỡ frame thành 1024x1024 không làm méo (Letterbox padding)
    h, w = frame.shape[:2]
    scale = 1024 / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    frame = cv2.resize(frame, (new_w, new_h))
    pad_w, pad_h = 1024 - new_w, 1024 - new_h
    frame = cv2.copyMakeBorder(frame, pad_h // 2, pad_h - pad_h // 2, pad_w // 2, pad_w - pad_w // 2, cv2.BORDER_CONSTANT, value=(0, 0, 0))

    # 3. Chạy YOLO detect
    # conf=0.5: Chỉ lấy những kết quả có độ tin cậy trên 50%
    # classes=[0]: Chỉ lọc và giữ lại duy nhất class 0 ('person')
    results = model(frame, conf=0.5, classes=[PERSON_CLASS_ID], verbose=False)

    # 4. Trích xuất thông tin Bounding Box người để xử lý
    for result in results:
        boxes = result.boxes
        for box in boxes:
            # Lấy tọa độ góc trên-trái và dưới-phải (x1, y1, x2, y2)
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            confidence = float(box.conf[0])

            # Vẽ khung chữ nhật quanh người được phát hiện
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

            # Hiển thị độ tin cậy (Confidence score)
            label = f"Person: {confidence:.2f}"
            cv2.putText(frame, label, (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            # --- MẸO DÙNG SAU NÀY CHO INSIGHTFACE ---
            # Để nhận diện khuôn mặt người quen, bước sau bạn chỉ cần crop khung hình người:
            # person_crop = frame[y1:y2, x1:x2]
            # Sau đó đẩy `person_crop` này vào InsightFace!

    # 5. Hiển thị kết quả lên màn hình
    cv2.imshow("YOLO Person Detection Only", frame)

    # Nhấn 'q' trên bàn phím để dừng
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Giải phóng bộ nhớ
cap.release()
cv2.destroyAllWindows()