import cv2
import os

def main():
    # 1. Yêu cầu nhập tên người từ trước
    print("=== HƯỚNG DẪN THU THẬP DỮ LIỆU ===")
    name = input("=> Nhập tên người cần thu thập (viết liền không dấu, VD: Nam): ").strip()
    if not name:
        print("[LỖI] Tên không hợp lệ. Đang thoát...")
        return

    # 2. Tạo thư mục 'register face/<name>'
    save_dir = os.path.join("register face", name)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    # 3. Mở Webcam
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("[LỖI] Không thể kết nối tới Webcam. Vui lòng kiểm tra lại thiết bị hoặc quyền truy cập camera!")
        return

    print(f"=== ĐÃ SẴN SÀNG CHO: {name} ===")
    print(" - Nhìn thẳng vào camera.")
    print(" - Bấm phím 'c' để BẮT ĐẦU / DỪNG quay video liên tục.")
    print(" - Bấm phím 'q' để THOÁT.")

    is_recording = False
    frame_count = 0
    tick_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[LỖI] Không thể đọc được hình ảnh từ Webcam.")
            break

        # Đổi kích cỡ frame thành 1024x1024 không làm méo (Letterbox padding)
        h, w = frame.shape[:2]
        scale = 1024 / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        frame = cv2.resize(frame, (new_w, new_h))
        pad_w, pad_h = 1024 - new_w, 1024 - new_h
        frame = cv2.copyMakeBorder(frame, pad_h // 2, pad_h - pad_h // 2, pad_w // 2, pad_w - pad_w // 2, cv2.BORDER_CONSTANT, value=(0, 0, 0))

        display_frame = frame.copy()

        if is_recording:
            tick_count += 1
            if tick_count % 4 == 0:
                # Lưu ảnh
                file_path = os.path.join(save_dir, f"frame_{frame_count:04d}.jpg")
                cv2.imwrite(file_path, frame)
                frame_count += 1
            cv2.putText(display_frame, f"Recording: {frame_count}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        else:
            cv2.putText(display_frame, "Ready - Press 'c' to record", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        cv2.imshow("Thu Thap Du Lieu Khuon Mat", display_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('c'):
            is_recording = not is_recording
            if is_recording:
                print(f"[INFO] Đã BẮT ĐẦU quay liên tục. Ảnh được lưu vào: {save_dir}")
            else:
                print(f"[INFO] Đã DỪNG quay. Tổng số ảnh đã lưu cho {name}: {frame_count}")
        elif key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()