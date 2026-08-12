import argparse
import pickle
import os
import numpy as np
import pandas as pd
from tqdm import tqdm
import torch

# Thư viện vẽ đồ thị
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix

def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Unsupported value encountered.')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    
    # 🔥 THAM SỐ 4 ĐƯỜNG DẪN SCORE
    parser.add_argument('--s1', required=True, help='Score SDA-GCN Joint')
    parser.add_argument('--s2', required=True, help='Score SDA-GCN Bone')
    parser.add_argument('--s3', required=True, help='Score HDS-GCN Joint')
    parser.add_argument('--s4', required=True, help='Score HDS-GCN Bone')
    
    parser.add_argument('--label-csv', required=True, help='Đường dẫn file label .csv')
    
    # 🔥 THAM SỐ 4 TRỌNG SỐ
    parser.add_argument('--w1', type=float, default=1.0, help='Trọng số SDA-GCN Joint')
    parser.add_argument('--w2', type=float, default=1.0, help='Trọng số SDA-GCN Bone')
    parser.add_argument('--w3', type=float, default=1.0, help='Trọng số HDS-GCN Joint')
    parser.add_argument('--w4', type=float, default=1.0, help='Trọng số HDS-GCN Bone')
    
    arg = parser.parse_args()

    # 1. ĐỌC NHÃN (GROUND TRUTH) TỪ FILE CSV
    label_dict = {}
    try:
        df = pd.read_csv(arg.label_csv, header=None)
        df[0] = df[0].astype(str)
        df[1] = df[1].astype(int)
        
        if df[1].min() == 1:
            df[1] = df[1] - 1
            
        label_dict = dict(zip(df[0], df[1]))
        print(f"[INFO] Nạp thành công {len(label_dict)} nhãn từ: {arg.label_csv}")
    except Exception as e:
        print(f"[ERROR] Lỗi đọc file CSV: {e}")
        exit()

    # 2. NẠP KẾT QUẢ DỰ ĐOÁN (SCORES) CỦA 4 LUỒNG
    try:
        with open(arg.s1, 'rb') as f: score1 = pickle.load(f)
        with open(arg.s2, 'rb') as f: score2 = pickle.load(f)
        with open(arg.s3, 'rb') as f: score3 = pickle.load(f)
        with open(arg.s4, 'rb') as f: score4 = pickle.load(f)
        print(f"[INFO] Nạp thành công 4 file score PKL.")
    except Exception as e:
        print(f"[ERROR] Lỗi nạp file .pkl: {e}")
        exit()

    # 3. ĐỒNG BỘ DỮ LIỆU
    norm = lambda x: x / (np.linalg.norm(x) + 1e-10)
    y_true_list, list_s1, list_s2, list_s3, list_s4 = [], [], [], [], []
    
    print("[INFO] Đang đồng bộ hóa dữ liệu từ 4 luồng...")
    for video_name in score1.keys():
        if (video_name in label_dict and 
            video_name in score2 and 
            video_name in score3 and 
            video_name in score4):
            
            y_true_list.append(label_dict[video_name])
            list_s1.append(norm(np.array(score1[video_name])))
            list_s2.append(norm(np.array(score2[video_name])))
            list_s3.append(norm(np.array(score3[video_name])))
            list_s4.append(norm(np.array(score4[video_name])))

    labels = np.array(y_true_list)
    arr_s1 = np.array(list_s1)
    arr_s2 = np.array(list_s2)
    arr_s3 = np.array(list_s3)
    arr_s4 = np.array(list_s4)
    total_samples = len(labels)

    if total_samples == 0:
        print("[ERROR] Không tìm thấy dữ liệu khớp nhau giữa 4 file. Kiểm tra lại.")
        exit()

    # 4. TÍNH TOÁN ENSEMBLE 4 LUỒNG
    print(f"\n[INFO] >>> Đang tính toán: ({arg.w1}*S1) + ({arg.w2}*S2) + ({arg.w3}*S3) + ({arg.w4}*S4)")
    score_fusion = (arg.w1 * arr_s1) + (arg.w2 * arr_s2) + (arg.w3 * arr_s3) + (arg.w4 * arr_s4)
    pred = np.argmax(score_fusion, axis=1)
    
    # Accuracy
    top1_acc = (pred == labels).sum() / total_samples * 100
    
    # Top-5 Accuracy
    rank_5 = score_fusion.argsort()[:, -5:]
    correct_5 = sum([1 for i in range(total_samples) if labels[i] in rank_5[i]])
    top5_acc = (correct_5 / total_samples) * 100

    # 5. XUẤT KẾT QUẢ
    print("-" * 55)
    print(f"   KẾT QUẢ ENSEMBLE 4 STREAM CHỐT HẠ")
    print(f"   Tổng số mẫu đánh giá: {total_samples}")
    print(f"   TOP-1 ACCURACY: {top1_acc:.4f}%")
    print(f"   TOP-5 ACCURACY: {top5_acc:.4f}%")
    print("-" * 55)

    # 6. VẼ CONFUSION MATRIX
    print("[INFO] Đang tạo biểu đồ ma trận nhầm lẫn...")
    cm = confusion_matrix(labels, pred)
    plt.figure(figsize=(20, 20))
    sns.heatmap(cm, cmap='Blues', xticklabels=False, yticklabels=False)
    plt.title(f'Confusion Matrix 4-Stream (Acc: {top1_acc:.2f}%)', fontsize=20)
    
    if not os.path.exists('./results'): os.makedirs('./results')
    save_path = f'./results/ensemble_4stream_w{arg.w1}_{arg.w2}_{arg.w3}_{arg.w4}.png'
    plt.savefig(save_path, bbox_inches='tight')
    plt.close()
    print(f"[SUCCESS] Đã lưu biểu đồ tại: {save_path}")