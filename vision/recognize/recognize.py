import cv2
import numpy as np
from insightface.app import FaceAnalysis

# --- HÀM PHỤ TRỢ: Tính độ tương đồng (Cosine Similarity) ---
def compute_similarity(embedding1, embedding2):
    # Tính khoảng cách cosine giữa 2 vector khuôn mặt
    # Kết quả càng gần 1.0 thì càng giống nhau
    return np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))

# ==========================================
# PHẦN 1: KHỞI TẠO INSIGHTFACE
# ==========================================
print("Đang khởi tạo InsightFace...")
# Khởi tạo mô hình InsightFace với GPU
app = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))
print("Khởi tạo xong!")

# ==========================================
# PHẦN 2: LẤY DỮ LIỆU KHUÔN MẶT MẪU (ĐĂNG KÝ)
# ==========================================
# Đọc ảnh người quen đã chuẩn bị
img_reference = cv2.imread("nguoi_quen.jpg")

if img_reference is None:
    print("Lỗi: Không tìm thấy file nguoi_quen.jpg. Vui lòng kiểm tra lại!")
    exit()

# Phân tích ảnh mẫu để lấy vector đặc trưng (embedding)
faces_reference = app.get(img_reference)

if len(faces_reference) == 0:
    print("Lỗi: Không tìm thấy khuôn mặt nào trong ảnh mẫu!")
    exit()

# Giả sử ảnh mẫu chỉ có 1 người, ta lấy embedding của người đầu tiên tìm thấy
known_embedding = faces_reference[0].embedding
print("Đã trích xuất thành công dữ liệu khuôn mặt mẫu!")

# ==========================================
# PHẦN 3: MỞ WEBCAM NHẬN DIỆN
# ==========================================
cap = cv2.VideoCapture(0)

# Ngưỡng nhận diện (từ 0.0 đến 1.0). Thường InsightFace dùng ngưỡng 0.4 - 0.5
THRESHOLD = 0.45

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Đổi kích cỡ frame thành 1024x1024 không làm méo (Letterbox padding)
    h, w = frame.shape[:2]
    scale = 1024 / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    frame = cv2.resize(frame, (new_w, new_h))
    pad_w, pad_h = 1024 - new_w, 1024 - new_h
    frame = cv2.copyMakeBorder(frame, pad_h // 2, pad_h - pad_h // 2, pad_w // 2, pad_w - pad_w // 2, cv2.BORDER_CONSTANT, value=(0, 0, 0))

    # Đưa frame từ webcam vào InsightFace để tìm và phân tích khuôn mặt
    faces = app.get(frame)

    # Duyệt qua từng khuôn mặt phát hiện được trên webcam
    for face in faces:
        # 1. Lấy tọa độ khuôn mặt (Bounding Box)
        box = face.bbox.astype(int)
        x1, y1, x2, y2 = box[0], box[1], box[2], box[3]

        # 2. Lấy vector đặc trưng của khuôn mặt trên webcam
        current_embedding = face.embedding

        # 3. So sánh với khuôn mặt mẫu đã đăng ký
        similarity = compute_similarity(known_embedding, current_embedding)

        # 4. Kiểm tra xem có phải người quen không
        color = (0, 0, 255) # Mặc định màu Đỏ (Người lạ)
        name = f"Unknown ({similarity:.2f})"

        if similarity > THRESHOLD:
            color = (0, 255, 0) # Chuyển sang Xanh lá (Người quen)
            name = f"Nguoi Quen ({similarity:.2f})"

        # Vẽ khung và tên lên màn hình
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, name, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    # Hiển thị kết quả
    cv2.imshow('InsightFace - Independent Test', frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()