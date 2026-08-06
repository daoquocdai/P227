import os
import cv2
import numpy as np
import mediapipe as mp

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['GLOG_minloglevel'] = '2'
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import logging
logging.getLogger('absl').setLevel(logging.ERROR)

mp_hands = mp.solutions.hands
mp_pose = mp.solutions.pose

TOTAL_JOINTS = 28
TARGET_HAND_INDICES = [0, 1, 4, 5, 8, 9, 12, 13, 16, 17, 20]

def extract_from_frame(rgb_frame, hands_model, pose_model):
    keypoints = np.zeros((TOTAL_JOINTS, 3), dtype=np.float32)

    # 1) Pose landmarks (Thân người)
    pose = pose_model.process(rgb_frame)
    if pose.pose_landmarks:
        lm = pose.pose_landmarks.landmark
        keypoints[22] = [lm[11].x, lm[11].y, lm[11].z] # LEFT SHOULDER
        keypoints[23] = [lm[12].x, lm[12].y, lm[12].z] # RIGHT SHOULDER
        keypoints[24] = [lm[0].x, lm[0].y, lm[0].z]    # NECK ≈ Nose
        
        lx, ly, lz = lm[23].x, lm[23].y, lm[23].z
        rx, ry, rz = lm[24].x, lm[24].y, lm[24].z
        keypoints[25] = [(lx + rx) / 2, (ly + ry) / 2, (lz + rz) / 2] # HIP_CENTER

        keypoints[26] = [lm[13].x, lm[13].y, lm[13].z] # LEFT ELBOW
        keypoints[27] = [lm[14].x, lm[14].y, lm[14].z] # RIGHT ELBOW

    # 2) Hand landmarks (Bàn tay)
    hands = hands_model.process(rgb_frame)
    if hands.multi_hand_landmarks and hands.multi_handedness:
        for hand_landmarks, handedness in zip(hands.multi_hand_landmarks, hands.multi_handedness):
            label = handedness.classification[0].label
            base = 0 if label == "Right" else 11

            for i, idx in enumerate(TARGET_HAND_INDICES):
                if idx < len(hand_landmarks.landmark):
                    lm_h = hand_landmarks.landmark[idx]
                    keypoints[base + i] = [lm_h.x, lm_h.y, lm_h.z]

    return keypoints

def process_video_to_npy(input_video, output_npy, target_size=512):
    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        print(f"[!] Không thể mở video: {input_video}")
        return False

    fps = cap.get(cv2.CAP_PROP_FPS)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print("[*] Đang quét video để tìm vị trí Cổ (Neck center)...")
    
    # ---------------------------------------------------------
    # PASS 1: Quét tìm vị trí Cổ trung bình
    # ---------------------------------------------------------
    sum_ls_x, sum_ls_y, count_ls = 0, 0, 0
    sum_rs_x, sum_rs_y, count_rs = 0, 0, 0

    with mp_pose.Pose(static_image_mode=False, model_complexity=1, min_detection_confidence=0.5) as pose:
        while True:
            ok, frame = cap.read()
            if not ok: break

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb_frame)

            if results.pose_landmarks:
                lm = results.pose_landmarks.landmark
                sum_ls_x += lm[11].x * W; sum_ls_y += lm[11].y * H; count_ls += 1
                sum_rs_x += lm[12].x * W; sum_rs_y += lm[12].y * H; count_rs += 1

    avg_ls_x = sum_ls_x / count_ls if count_ls > 0 else W / 2
    avg_ls_y = sum_ls_y / count_ls if count_ls > 0 else H / 2
    avg_rs_x = sum_rs_x / count_rs if count_rs > 0 else W / 2
    avg_rs_y = sum_rs_y / count_rs if count_rs > 0 else H / 2

    neck_x = int((avg_ls_x + avg_rs_x) / 2)
    neck_y = int((avg_ls_y + avg_rs_y) / 2)
    print("[*] Đang Crop và Trích xuất 28 Keypoints...")
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    
    side_length = int(H * 0.9)
    half_side = side_length // 2
    frames_kpts = []

    with mp_hands.Hands(max_num_hands=2, min_detection_confidence=0.5, min_tracking_confidence=0.5) as hands, \
         mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:

        while True:
            ok, frame = cap.read()
            if not ok: break

            # Padding
            padded = cv2.copyMakeBorder(frame, half_side, half_side, half_side, half_side, cv2.BORDER_CONSTANT, value=[0, 0, 0])
            py, px = neck_y + half_side, neck_x + half_side
            y1, y2 = py - half_side, py + half_side
            x1, x2 = px - half_side, px + half_side

            # Crop & Resize
            crop = padded[int(y1):int(y2), int(x1):int(x2)]
            if crop.size != 0:
                crop_resized = cv2.resize(crop, (target_size, target_size))
            else:
                crop_resized = cv2.resize(frame, (target_size, target_size))

            # Trích xuất thẳng từ ảnh đã crop
            frame_rgb = cv2.cvtColor(crop_resized, cv2.COLOR_BGR2RGB)
            kpts = extract_from_frame(frame_rgb, hands, pose)
            frames_kpts.append(kpts)

    cap.release()

    # Lưu thành file .npy
    if len(frames_kpts) > 0:
        frames_kpts = np.array(frames_kpts)
        np.save(output_npy, frames_kpts)
        print(f"🎉 Hoàn thành! File .npy đã được lưu tại: {output_npy}")
        print(f"   Shape của dữ liệu: {frames_kpts.shape} (Frames, Joints, 3)")
        return True
    
    print("[!] Không có frame nào được trích xuất.")
    return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Directly process raw video to .npy keypoints")
    parser.add_argument("--video", required=True, help="Đường dẫn đến file video gốc")
    parser.add_argument("--out_npy", required=True, help="Đường dẫn xuất file .npy")
    args = parser.parse_args()

    process_video_to_npy(args.video, args.out_npy)