import cv2
import numpy as np
import mediapipe as mp
import os
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor
from ultralytics import YOLO  # Thêm thư viện YOLO

os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# ==============================
# Mediapipe Modules
# ==============================
mp_pose = mp.solutions.pose
TOTAL_JOINTS = 25  # Chuẩn NTU RGB+D

# ==============================
# CÁC HÀM TIỀN XỬ LÝ DỮ LIỆU (MỚI THÊM)
# ==============================
def clean_out_of_bounds_data(data):
    """
    Làm sạch các điểm khớp bị văng ra khỏi video (AI đoán mò).
    Ép mọi giá trị X và Y chỉ được nằm trong khoảng 0.0 đến 1.0.
    """
    clean_data = data.copy()
    clean_data[:, :, 0] = np.clip(clean_data[:, :, 0], 0.0, 1.0) # Trục X
    clean_data[:, :, 1] = np.clip(clean_data[:, :, 1], 0.0, 1.0) # Trục Y
    return clean_data

def normalize_skeleton_dynamic(kpts_array):
    """
    Chuẩn hóa từng khung hình (Frame-wise Normalization):
    1. Dời gốc (0,0,0) về khớp Hông (Base of Spine - index 0)
    2. Cố định kích thước bằng chiều dài Cột sống (Hông -> Cổ)
    """
    norm_kpts = np.zeros_like(kpts_array)
    num_frames = kpts_array.shape[0]

    for f in range(num_frames):
        frame_data = kpts_array[f].copy()

        # 1. Dời tâm về Hông (Index 0)
        center_hip = frame_data[0].copy()
        frame_data = frame_data - center_hip

        # 2. Tính độ dài Cột sống (Từ Hông [0] đến Cổ [2])
        # Vì Hông giờ đã là (0,0,0), khoảng cách chính là độ lớn của vector Cổ
        neck = frame_data[2]
        spine_length = np.linalg.norm(neck)

        # 3. Chia tỷ lệ (Scale)
        if spine_length > 0:
            frame_data = frame_data / spine_length

        norm_kpts[f] = frame_data

    return norm_kpts


# ==============================
# Trích xuất và Remap tọa độ từ vùng cắt (Crop)
# ==============================
def extract_from_crop(rgb_crop, pose_model, x_min, y_min, crop_w, crop_h, orig_w, orig_h):
    """
    Trích xuất 25 điểm trên ảnh crop, sau đó map ngược tọa độ về video gốc.
    Return: (25, 3) - Cấu trúc 25 điểm NTU (Tọa độ chuẩn hóa 0.0 -> 1.0 theo khung hình gốc)
    """
    keypoints = np.zeros((TOTAL_JOINTS, 3), dtype=np.float32)
    pose = pose_model.process(rgb_crop)

    if pose.pose_landmarks:
        lm = pose.pose_landmarks.landmark

        def get_pt(idx):
            # 1. Chuyển sang tọa độ pixel tuyệt đối trên ảnh gốc
            abs_x = (lm[idx].x * crop_w) + x_min
            abs_y = (lm[idx].y * crop_h) + y_min

            # 2. Chuẩn hóa lại (0.0 -> 1.0) theo khung hình gốc
            norm_x = abs_x / orig_w
            norm_y = abs_y / orig_h

            # Trục Z của MP scale theo chiều rộng ảnh crop, cần scale lại theo ảnh gốc
            norm_z = lm[idx].z * (crop_w / orig_w)

            return np.array([norm_x, norm_y, norm_z], dtype=np.float32)

        # CÁC ĐIỂM TRỤC GIỮA
        keypoints[0] = (get_pt(23) + get_pt(24)) / 2.0     # 1. Base of spine (HÔNG)
        keypoints[20] = (get_pt(11) + get_pt(12)) / 2.0    # 21. Spine Shoulder
        keypoints[1] = (keypoints[0] + keypoints[20]) / 2.0 # 2. Middle of spine
        keypoints[2] = (get_pt(0) + keypoints[20]) / 2.0    # 3. Neck (CỔ)
        keypoints[3] = get_pt(0)                            # 4. Head

        # TAY TRÁI (LEFT ARM)
        keypoints[4] = get_pt(11)
        keypoints[5] = get_pt(13)
        keypoints[6] = get_pt(15)
        keypoints[7] = (get_pt(17) + get_pt(19)) / 2.0
        keypoints[21] = get_pt(19)
        keypoints[22] = get_pt(21)

        # TAY PHẢI (RIGHT ARM)
        keypoints[8] = get_pt(12)
        keypoints[9] = get_pt(14)
        keypoints[10] = get_pt(16)
        keypoints[11] = (get_pt(18) + get_pt(20)) / 2.0
        keypoints[23] = get_pt(20)
        keypoints[24] = get_pt(22)

        # CHÂN TRÁI & PHẢI (LEGS)
        keypoints[12] = get_pt(23)
        keypoints[13] = get_pt(25)
        keypoints[14] = get_pt(27)
        keypoints[15] = get_pt(31)

        keypoints[16] = get_pt(24)
        keypoints[17] = get_pt(26)
        keypoints[18] = get_pt(28)
        keypoints[19] = get_pt(32)

    return keypoints

# ==============================
# Xử lý 1 video trọn vẹn (Tích hợp YOLO)
# ==============================
def process_video_task(task):
    video_path, out_dir = task
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False

    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    try:
        yolo_model = YOLO("yolov8n.pt", verbose=False)
    except Exception:
        return False

    kpts_by_id = {}

    with mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            results = yolo_model.track(frame, persist=True, classes=0, verbose=False)

            if results[0].boxes is not None and results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.cpu().numpy().astype(int)

                for box, track_id in zip(boxes, track_ids):
                    x1, y1, x2, y2 = map(int, box)

                    pad = 30
                    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
                    x2, y2 = min(orig_w, x2 + pad), min(orig_h, y2 + pad)

                    crop_w, crop_h = x2 - x1, y2 - y1
                    if crop_w < 20 or crop_h < 20:
                        continue

                    crop_frame = frame[y1:y2, x1:x2]
                    crop_rgb = cv2.cvtColor(crop_frame, cv2.COLOR_BGR2RGB)

                    kpts = extract_from_crop(crop_rgb, pose, x1, y1, crop_w, crop_h, orig_w, orig_h)

                    if track_id not in kpts_by_id:
                        kpts_by_id[track_id] = []
                    kpts_by_id[track_id].append(kpts)

    cap.release()

    # ==============================
    # 5. XUẤT FILE VÀ CHUẨN HÓA DỮ LIỆU
    # ==============================
    name_only = os.path.splitext(os.path.basename(video_path))[0]
    saved_any = False

    for track_id, frames_kpts in kpts_by_id.items():
        if len(frames_kpts) >= 10:
            raw_array = np.array(frames_kpts) # Shape: (Frames, 25, 3)

            # BƯỚC A: Lọc nhiễu văng viền (Chân bị đoán mò)
            cleaned_array = clean_out_of_bounds_data(raw_array)

            # BƯỚC B: Chuẩn hóa không gian (Hông làm gốc, Cột sống làm tỷ lệ)
            normalized_array = normalize_skeleton_dynamic(cleaned_array)

            # BƯỚC C: Lưu file đã hoàn thiện
            save_path = os.path.join(out_dir, f"{name_only}_ID_{track_id}.npy")
            np.save(save_path, normalized_array)
            saved_any = True

    return saved_any

# ==============================
# Xử lý song song thư mục
# ==============================
def extract_keypoints_folder(video_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    videos = [v for v in os.listdir(video_dir) if v.lower().endswith((".mp4", ".avi", ".mov"))]

    tasks = [(os.path.join(video_dir, v), out_dir) for v in videos]

    with ProcessPoolExecutor(max_workers=5) as executor:
        list(tqdm(executor.map(process_video_task, tasks),
                  total=len(tasks),
                  desc="Extracting YOLO+MP Keypoints"))

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--video_dir", type=str, required=True)
    parser.add_argument("--out_dir", type=str, required=True)
    args = parser.parse_args()

    extract_keypoints_folder(args.video_dir, args.out_dir)