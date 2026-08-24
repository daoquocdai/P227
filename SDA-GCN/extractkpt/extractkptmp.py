import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['GLOG_minloglevel'] = '2'

import warnings
warnings.filterwarnings("ignore")

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor

# ==============================
# CẤU HÌNH JOINTS
# ==============================
TOTAL_JOINTS = 25  # Chuẩn NTU RGB+D

# ==============================
# CÁC HÀM TIỀN XỬ LÝ DỮ LIỆU (GIỮ NGUYÊN 100%)
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
        neck = frame_data[2]
        spine_length = np.linalg.norm(neck) 
        
        # 3. Chia tỷ lệ (Scale) 
        if spine_length > 0:
            frame_data = frame_data / spine_length
            
        norm_kpts[f] = frame_data
        
    return norm_kpts


# ==============================
# Trích xuất và Remap tọa độ (ĐÃ ĐƠN GIẢN HÓA VÌ KHÔNG CÒN CROP)
# ==============================
def extract_from_landmarks(landmarks):
    """
    Trích xuất 25 điểm trên ảnh gốc.
    Do dùng MediaPipe full frame, x và y đã tự động được chuẩn hóa 0.0 -> 1.0
    """
    keypoints = np.zeros((TOTAL_JOINTS, 3), dtype=np.float32)
    lm = landmarks # Lấy List các điểm do MediaPipe Tasks trả về
    
    def get_pt(idx):
        return np.array([lm[idx].x, lm[idx].y, lm[idx].z], dtype=np.float32)

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
# Xử lý 1 video trọn vẹn (CHỈ DÙNG MEDIAPIPE)
# ==============================
def process_video_task(task):
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
    except:
        pass
        
    video_path, out_dir = task 
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False
        
    # Tính toán thông số timestamp cho VIDEO mode
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or np.isnan(fps):
        fps = 30.0

    # Khởi tạo MediaPipe Tasks API (VIDEO MODE)
    base_options = python.BaseOptions(model_asset_path='pose_landmarker_full.task')
    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO, # Chế độ theo dõi mượt mà
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )

    frames_kpts = []
    frame_idx = 0

    with vision.PoseLandmarker.create_from_options(options) as pose_model:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            
            # API mới yêu cầu timestamp tính bằng mili giây, tăng dần đều
            timestamp_ms = int(frame_idx * (1000.0 / fps))
            
            # Suy luận trên video nguyên bản
            result = pose_model.detect_for_video(mp_image, timestamp_ms)
            
            if result.pose_landmarks:
                kpts = extract_from_landmarks(result.pose_landmarks[0])
                frames_kpts.append(kpts)
                
            frame_idx += 1

    cap.release()

    # ==============================
    # 5. XUẤT FILE VÀ CHUẨN HÓA DỮ LIỆU
    # ==============================
    name_only = os.path.splitext(os.path.basename(video_path))[0]
    saved_any = False
    
    if len(frames_kpts) >= 10: 
        raw_array = np.array(frames_kpts) # Shape: (Frames, 25, 3)
        
        # BƯỚC A: Lọc nhiễu văng viền
        cleaned_array = clean_out_of_bounds_data(raw_array)
        
        # BƯỚC B: Chuẩn hóa không gian
        normalized_array = normalize_skeleton_dynamic(cleaned_array)
        
        # BƯỚC C: Lưu file
        # Chú ý: Vì không còn YOLO tách ID, ta lưu trực tiếp tên file
        save_path = os.path.join(out_dir, f"{name_only}.npy")
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
                  desc="Extracting MP Keypoints (VIDEO MODE)"))

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--video_dir", type=str, required=True)
    parser.add_argument("--out_dir", type=str, required=True)
    args = parser.parse_args()

    extract_keypoints_folder(args.video_dir, args.out_dir)
