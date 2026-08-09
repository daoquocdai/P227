import cv2
import numpy as np
import os
import torch
from ultralytics import YOLO
from insightface.app import FaceAnalysis

# --- HÀM TÍNH ĐỘ TƯƠNG ĐỒNG ---
def compute_similarity(embedding1, embedding2):
    return np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))

def main():
    # ==========================================
    # 1. KHỞI TẠO MÔ HÌNH
    # ==========================================
    print("Đang tải YOLOv8...")
    yolo_model = YOLO("yolov8n.pt")
    if torch.cuda.is_available():
        yolo_model.to('cuda')
    
    print("Đang khởi tạo InsightFace...")
    app = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(640, 640))

    # ==========================================
    # 2. TẢI DỮ LIỆU NGƯỜI QUEN TỪ THƯ MỤC 'data'
    # ==========================================
    known_faces = {}
    data_dir = "register face"
    
    if os.path.exists(data_dir):
        print(f"Đang đọc dữ liệu từ thư mục '{data_dir}'...")
        for item in os.listdir(data_dir):
            item_path = os.path.join(data_dir, item)
            
            if os.path.isdir(item_path):
                # Đây là thư mục của một người (item là tên người)
                name = item
                embeddings = []
                for filename in os.listdir(item_path):
                    if filename.endswith(('.jpg', '.png', '.jpeg')):
                        img_path = os.path.join(item_path, filename)
                        img = cv2.imread(img_path)
                        faces = app.get(img)
                        if len(faces) > 0:
                            embeddings.append(faces[0].embedding)
                
                if len(embeddings) > 0:
                    # Lấy trung bình cộng các vector để độ nhận diện chính xác và ổn định hơn
                    avg_embedding = np.mean(embeddings, axis=0)
                    known_faces[name] = avg_embedding
                    print(f" -> Đã đăng ký khuôn mặt: {name} (tổng hợp từ {len(embeddings)} ảnh)")
                else:
                    print(f" -> [CẢNH BÁO] Không tìm thấy khuôn mặt hợp lệ nào trong thư mục: {name}")
                    
            elif item.endswith(('.jpg', '.png', '.jpeg')):
                # Hỗ trợ đọc các ảnh cũ được lưu trực tiếp trong thư mục 'data'
                name = os.path.splitext(item)[0]
                img_path = os.path.join(data_dir, item)
                
                # Đọc ảnh và trích xuất embedding
                img = cv2.imread(img_path)
                faces = app.get(img)
                if len(faces) > 0:
                    known_faces[name] = faces[0].embedding
                    print(f" -> Đã đăng ký khuôn mặt: {name} (từ 1 ảnh gốc)")
                else:
                    print(f" -> [LỖI] Không tìm thấy khuôn mặt trong file: {item}")
    else:
        print(f"[CẢNH BÁO] Chưa có thư mục '{data_dir}'. Hãy chạy file capture_data.py trước!")

    # ==========================================
    # 3. MỞ WEBCAM & PIPELINE NHẬN DIỆN
    # ==========================================
    cap = cv2.VideoCapture(0)
    
    THRESHOLD = 0.45 
    print("Hệ thống đã sẵn sàng. Bấm 'q' để thoát.")

    while True:
        ret, frame = cap.read()
        if not ret: break
        
        # Đổi kích cỡ frame thành 1024x1024 không làm méo (Letterbox padding)
        h, w = frame.shape[:2]
        scale = 1024 / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        frame = cv2.resize(frame, (new_w, new_h))
        pad_w, pad_h = 1024 - new_w, 1024 - new_h
        frame = cv2.copyMakeBorder(frame, pad_h // 2, pad_h - pad_h // 2, pad_w // 2, pad_w - pad_w // 2, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        
        # Lấy kích thước khung hình để tránh crop lỗi
        h_frame, w_frame = frame.shape[:2]

        # [A] YOLO DETECT NGƯỜI (class 0)
        results = yolo_model(frame, conf=0.5, classes=[0], verbose=False)
        
        for result in results:
            for box in result.boxes:
                # 1. Lấy tọa độ bounding box người từ YOLO
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                
                # Đảm bảo tọa độ không vượt quá mép ảnh
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w_frame, x2), min(h_frame, y2)
                
                # 2. Cắt (Crop) toàn thân người ra
                person_crop = frame[y1:y2, x1:x2]
                
                # Nếu vùng crop quá nhỏ (nhiễu), bỏ qua
                if person_crop.shape[0] < 50 or person_crop.shape[1] < 50:
                    continue
                
                name_display = "Unknown"
                color = (0, 0, 255) # Đỏ

                # [B] INSIGHTFACE NHẬN DIỆN KHUÔN MẶT (Trong vùng đã crop)
                faces = app.get(person_crop)
                
                if len(faces) > 0:
                    # Lấy khuôn mặt lớn nhất trong vùng crop
                    main_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                    current_embedding = main_face.embedding
                    
                    # So sánh với database người quen
                    best_score = 0
                    for name, known_emb in known_faces.items():
                        score = compute_similarity(known_emb, current_embedding)
                        if score > best_score:
                            best_score = score
                            name_display = name
                    
                    # Nếu giống trên mức Threshold
                    if best_score > THRESHOLD:
                        color = (0, 255, 0) # Xanh lá
                        name_display = f"{name_display} ({best_score:.2f})"
                    else:
                        name_display = "Unknown"

                # 3. Vẽ Bounding Box và Tên lên màn hình chính
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, name_display, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        cv2.imshow("He Thong Nhan Dien", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()