import pandas as pd
import numpy as np
import os
import sys
import glob 
from tqdm import tqdm
import random
import math

current_dir = os.path.dirname(os.path.abspath(__file__)) 
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from fusion.compute_joint import compute_joint
from fusion.interpolate import interpolate_missing
from fusion.kalman_filter import apply_kalman_filter
from fusion.normalize_pose import normalize_pose

CONFIG = {
    "RAW_KEYPOINTS_DIR": "data/keypoint",
    "CSV_DIR": "data", 
    "OUTPUT_ROOT": "data/fused_features",
    "TRAIN_CSV": "train.csv",
    "VAL_CSV": "val.csv",
    "NUM_AUG": 5,
    "MAX_FRAMES": 64
}

def aug_random_rotate(kpts):
    angle = random.uniform(-15, 15)
    rad = math.radians(angle)
    cos_val, sin_val = math.cos(rad), math.sin(rad)
    data = kpts.copy()

    for t in range(data.shape[0]):
        for v in range(data.shape[1]):
            x, z = data[t, v, 0], data[t, v, 2]
            data[t, v, 0] = x * cos_val - z * sin_val
            data[t, v, 2] = x * sin_val + z * cos_val
    return data

def process_one_sample(file_path, max_frames=64, augment=False):
    try:
        kpt = np.load(file_path) # Shape gốc: (T, 25, 3)
        
   
        kpt = kpt - kpt[:, 0:1, :] 
        
        kpt = normalize_pose(kpt)
        kpt = interpolate_missing(kpt)
        
        if augment:
            kpt = aug_random_rotate(kpt)
            
        kpt = apply_kalman_filter(kpt)

        T = kpt.shape[0]
        if T < max_frames:
            pad = np.zeros((max_frames - T, kpt.shape[1], kpt.shape[2]))
            kpt = np.concatenate([kpt, pad], axis=0)
        else:
            kpt = kpt[:max_frames]

        # Đảo trục cho GCN. Kết quả: (3, 64, 25)
        kpt = np.transpose(kpt, (2, 0, 1))
        return kpt

    except Exception as e:
        print(f"[LỖI] {file_path}: {e}")
        return None

def process_split(split_name, csv_filename, is_train=False):
    print(f"\n>>> ĐANG XỬ LÝ TẬP: {split_name.upper()}")

    csv_path = os.path.join(CONFIG["CSV_DIR"], csv_filename)
    if not os.path.exists(csv_path):
        print(f"[CẢNH BÁO] Không tìm thấy {csv_path}")
        return

    save_dir = os.path.join(CONFIG["OUTPUT_ROOT"], f"{split_name}_joint_only")
    os.makedirs(save_dir, exist_ok=True)

    df = pd.read_csv(csv_path, header=None, names=['filename', 'label'])
    new_csv_rows = []
    missing_count = 0

    for _, row in tqdm(df.iterrows(), total=len(df)):
        base_name = os.path.splitext(str(row['filename']))[0]
        label = row['label']

        search_pattern = os.path.join(CONFIG["RAW_KEYPOINTS_DIR"], f"{base_name}_ID_*.npy")
        matched_files = glob.glob(search_pattern)

        if len(matched_files) == 0:
            alt_path = os.path.join(CONFIG["RAW_KEYPOINTS_DIR"], f"{base_name}.npy")
            if os.path.exists(alt_path):
                matched_files = [alt_path]

        if len(matched_files) == 0:
            missing_count += 1
            continue

        for src_path in matched_files:
            actual_filename = os.path.basename(src_path)
            actual_base_name = os.path.splitext(actual_filename)[0]

            feat = process_one_sample(src_path, CONFIG["MAX_FRAMES"], augment=False)
            if feat is not None:
                np.save(os.path.join(save_dir, actual_filename), feat)
                new_csv_rows.append([actual_filename, label])

            if is_train and CONFIG["NUM_AUG"] > 0:
                for i in range(CONFIG["NUM_AUG"]):
                    aug_feat = process_one_sample(src_path, CONFIG["MAX_FRAMES"], augment=True)
                    if aug_feat is not None:
                        aug_name = f"{actual_base_name}_aug{i}.npy"
                        np.save(os.path.join(save_dir, aug_name), aug_feat)
                        new_csv_rows.append([aug_name, label])

    new_csv_path = os.path.join(save_dir, f"{split_name}_label.csv")
    pd.DataFrame(new_csv_rows).to_csv(new_csv_path, index=False, header=False)

    print(f"[HOÀN THÀNH] Đã lưu {len(new_csv_rows)} mẫu vào {save_dir}")
    if missing_count > 0:
        print(f"[CẢNH BÁO] Thiếu {missing_count} video gốc.")

if __name__ == "__main__":
    process_split("train", CONFIG["TRAIN_CSV"], is_train=True)
    process_split("val", CONFIG["VAL_CSV"], is_train=False)