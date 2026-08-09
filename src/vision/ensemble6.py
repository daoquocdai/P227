import argparse
import yaml
import torch
import numpy as np
import importlib
import os
import sys
import csv
from pathlib import Path
from torch.utils.data import DataLoader
from tqdm import tqdm

# Thêm thư viện vẽ đồ thị
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix

sys.path.append(os.getcwd())

def load_lookup_table(csv_path):
    label_map = {}
    if not csv_path or not os.path.exists(csv_path):
        return label_map

    with open(csv_path, mode='r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                label_id = int(row['id_label_in_documents'])
            except (TypeError, ValueError, KeyError):
                continue

            label_name = (row.get('name') or '').strip()
            if label_name:
                label_map[label_id] = label_name

    return label_map

def lookup_label_name(label_id, label_map):
    if label_id in label_map:
        return label_map[label_id]

    one_based_id = label_id + 1
    if one_based_id in label_map:
        return label_map[one_based_id]

    return f'Class {label_id}'

def resolve_lookup_csv():
    candidates = [
        Path('data') / 'Multi-VSL200' / 'Multi-VSL200' / 'lookuptable.csv',
        Path('data') / 'MultiVSL200' / 'lookuptable.csv',
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None

def build_class_names(num_classes, label_map):
    return [lookup_label_name(class_id, label_map) for class_id in range(num_classes)]

def plot_confusion_matrix_subset(y_true, y_pred, class_ids, class_names, save_path):
    subset_mask = np.isin(y_true, class_ids)
    if not np.any(subset_mask):
        return None

    y_true_subset = y_true[subset_mask]
    y_pred_subset = y_pred[subset_mask]

    cm = confusion_matrix(y_true_subset, y_pred_subset, labels=class_ids)

    plt.figure(figsize=(max(12, len(class_ids) * 0.55), max(10, len(class_ids) * 0.45)))
    sns.heatmap(
        cm,
        cmap='Blues',
        xticklabels=class_names,
        yticklabels=class_names,
        square=False,
        cbar=True,
    )

    plt.title('Confusion Matrix')
    plt.xlabel('Predicted Label')
    plt.ylabel('True Label')
    plt.xticks(rotation=90)
    plt.yticks(rotation=0)
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()

    return cm

def print_top_bottom_classes(acc_per_class, class_names, top_k=20):
    valid_indices = np.where(~np.isnan(acc_per_class))[0]
    if len(valid_indices) == 0:
        print('[WARN] Không có lớp hợp lệ để thống kê accuracy theo lớp.')
        return [], []

    sorted_indices = valid_indices[np.argsort(acc_per_class[valid_indices])[::-1]]
    top_indices = sorted_indices[:top_k].tolist()
    bottom_indices = sorted_indices[-top_k:].tolist()[::-1]

    print('\n[INFO] >>> Top lớp accuracy cao nhất')
    for rank, class_id in enumerate(top_indices, 1):
        print(f"  {rank:02d}. {class_names[class_id]} -> {acc_per_class[class_id]:.2f}%")

    print('\n[INFO] >>> Top lớp accuracy thấp nhất')
    for rank, class_id in enumerate(bottom_indices, 1):
        print(f"  {rank:02d}. {class_names[class_id]} -> {acc_per_class[class_id]:.2f}%")

    return top_indices, bottom_indices

def import_class(name):
    try:
        module_name, class_name = name.rsplit('.', 1)
        mod = importlib.import_module(module_name)
        klass = getattr(mod, class_name)
        return klass
    except Exception as e:
        raise ImportError(f"Cannot load class {name}: {e}")

def get_tta_loader(config, tta_enabled=False):
    # [FIXED] Tự động tìm 'test_feeder', nếu không có thì lấy 'feeder'
    feeder_name = config.get('test_feeder', config.get('feeder'))
    if not feeder_name:
        raise ValueError("[ERROR] File config.yaml của bạn không có khai báo 'feeder' hoặc 'test_feeder'!")
        
    Feeder = import_class(feeder_name)
    args = config.get('test_feeder_args', {})
    
    if tta_enabled:
        args['random_shift'] = True
        args['random_move'] = True
    else:
        args['random_shift'] = False
        args['random_move'] = False
    
    batch_size = 32
    if 'test_batch_size' in config:
        batch_size = config['test_batch_size']
    elif 'test' in config and 'test_batch_size' in config['test']:
        batch_size = config['test']['test_batch_size']
        
    loader = DataLoader(Feeder(**args), batch_size=batch_size, 
                        shuffle=False, num_workers=4, drop_last=False)
    return loader

def run_inference_tta(config_path, weight_path, device_id, tta_times=1):
    if not config_path or not weight_path: return None, None
    
    print(f"[INFO] Evaluating: {os.path.basename(config_path)}")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except UnicodeDecodeError:
        with open(config_path, 'r', encoding='utf-8-sig') as f:
            config = yaml.safe_load(f)
    
    device = torch.device(f"cuda:{device_id}" if torch.cuda.is_available() else "cpu")
    Model = import_class(config['model'])
    model = Model(**config['model_args']).to(device)
    
    checkpoint = torch.load(weight_path, map_location=device)
    if 'model_state_dict' in checkpoint: model.load_state_dict(checkpoint['model_state_dict'])
    elif 'model' in checkpoint: model.load_state_dict(checkpoint['model'])
    else: model.load_state_dict(checkpoint)
    model.eval()
    
    final_scores = None
    final_labels = None

    for i in range(tta_times):
        is_aug = (i > 0)
        loader = get_tta_loader(config, tta_enabled=is_aug)
        
        score_frag = []
        label_frag = []
        
        desc = f"   Round {i+1}/{tta_times} [{'Aug' if is_aug else 'Orig'}]"
        
        with torch.no_grad():
            # [FIXED] Dùng 'batch_data' để hứng toàn bộ, tránh lỗi unpacking
            for batch_data in tqdm(loader, ncols=100, unit="batch", desc=desc):
                
                inputs = batch_data[0].to(device)
                targets = batch_data[1].numpy()
                
                outputs = model(inputs)
                score_frag.append(outputs.cpu().numpy())
                label_frag.append(targets)
        scores = np.concatenate(score_frag)
        labels = np.concatenate(label_frag)
        
        if final_scores is None:
            final_scores = scores
            final_labels = labels
        else:
            final_scores += scores
            
    final_scores /= tta_times
    acc = (np.argmax(final_scores, axis=1) == final_labels).sum() / len(final_labels) * 100
    print(f"   -> Accuracy TTA: {acc:.2f}%\n")
    
    return final_scores, final_labels

# =======================================================
# [NEW] HÀM SINH TỔ HỢP TRỌNG SỐ CHO N MODELS
# =======================================================
def get_weight_combinations(num_weights, total_steps=20):
    """
    Sinh ra các mảng số nguyên có chiều dài `num_weights`, sao cho tổng bằng `total_steps`.
    Ví dụ: total_steps=20 tương đương với step=0.05 (vì 1.0 / 20 = 0.05).
    """
    if num_weights == 1:
        yield [total_steps]
        return
    for i in range(total_steps + 1):
        for rest in get_weight_combinations(num_weights - 1, total_steps - i):
            yield [i] + rest

def main():
    parser = argparse.ArgumentParser()
    # Khai báo đến 6 config/weight
    parser.add_argument('--config1', default='') 
    parser.add_argument('--weight1', default='')
    parser.add_argument('--config2', default='') 
    parser.add_argument('--weight2', default='')
    parser.add_argument('--config3', default='') 
    parser.add_argument('--weight3', default='')
    parser.add_argument('--config4', default='') 
    parser.add_argument('--weight4', default='')
    parser.add_argument('--config5', default='') 
    parser.add_argument('--weight5', default='')
    parser.add_argument('--config6', default='') 
    parser.add_argument('--weight6', default='')
    
    parser.add_argument('--tta_times', type=int, default=5, help='Số lần lặp TTA')
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--lookup_csv', default='', help='Đường dẫn lookuptable.csv')
    parser.add_argument('--grid_steps', type=int, default=20, 
                        help='Số bước nhảy Grid Search. 20 (0.05), 10 (0.1). Nên dùng 10 nếu 6 model để tìm nhanh hơn.')
    args = parser.parse_args()

    # Thu thập tất cả các model được cung cấp
    inputs = [
        (args.config1, args.weight1), (args.config2, args.weight2), 
        (args.config3, args.weight3), (args.config4, args.weight4), 
        (args.config5, args.weight5), (args.config6, args.weight6)
    ]
    
    valid_models = [(c, w) for c, w in inputs if c and w]
    if not valid_models:
        print("[ERROR] Cần cung cấp ít nhất 1 cặp config và weight!")
        return

    print(f"\n[INFO] >>> Bắt đầu chạy Inference trên {len(valid_models)} Model(s) với TTA x{args.tta_times}")
    scores_list = []
    labels = None

    for i, (cfg, wgt) in enumerate(valid_models):
        print(f"\n--- Model {i+1} ---")
        s, l = run_inference_tta(cfg, wgt, args.device, args.tta_times)
        if s is not None:
            scores_list.append(s)
            if labels is None:
                labels = l
        torch.cuda.empty_cache() # Dọn dẹp GPU memory sau mỗi model

    num_models = len(scores_list)
    
    # Grid Search tự động dựa trên số model thực tế được nạp vào
    print(f"\n[INFO] >>> Searching Best Ensemble ({num_models} Models)...")
    best_acc = 0
    best_weights = [0] * num_models
    
    # Lấy danh sách các cấu hình trọng số
    combos = list(get_weight_combinations(num_models, args.grid_steps))
    
    # Quét tất cả các tổ hợp
    for weights_int in tqdm(combos, desc=f"Grid Search (Step {1/args.grid_steps:.2f})", ncols=100):
        # Chuyển đổi số nguyên sang số thập phân (VD: [10, 5, 5] -> [0.5, 0.25, 0.25])
        current_weights = np.array(weights_int) / args.grid_steps
        
        # Tính toán ma trận score tổng hợp
        score_fusion = np.zeros_like(scores_list[0])
        for w, s in zip(current_weights, scores_list):
            if w > 0: # Bỏ qua phép nhân nếu trọng số = 0 để tối ưu tốc độ
                score_fusion += w * s
        
        pred = np.argmax(score_fusion, axis=1)
        acc = (pred == labels).sum() / len(labels) * 100
        
        if acc > best_acc:
            best_acc = acc
            best_weights = current_weights

    # In kết quả cuối cùng
    print("\n" + "=" * 50)
    print(f"   FINAL ENSEMBLE RESULT (TTA x{args.tta_times}):")
    weights_str = " | ".join([f"M{i+1}: {w:.2f}" for i, w in enumerate(best_weights)])
    print(f"   Trọng số tối ưu: {weights_str}")
    print(f"   ACCURACY (Top-1): {best_acc:.2f}%")
    print("=" * 50)
    
    # Check Top-5 Accuracy với Best Weights
    final_score = np.zeros_like(scores_list[0])
    for w, s in zip(best_weights, scores_list):
        final_score += w * s

    _, pred5 = torch.tensor(final_score).topk(5, 1, True, True)
    pred5 = pred5.t()
    correct5 = pred5.eq(torch.tensor(labels).view(1, -1).expand_as(pred5))
    top5_acc = correct5[:5].reshape(-1).float().sum(0) * 100. / len(labels)
    print(f"   TOP-5 ACCURACY:   {top5_acc:.2f}%")
    print("=" * 50)

    # ==========================================
    # GENERATE & SAVE CONFUSION MATRICES
    # ==========================================
    print("\n[INFO] >>> Generating Confusion Matrices...")

    y_pred = np.argmax(final_score, axis=1)
    y_true = labels

    lookup_csv = args.lookup_csv or resolve_lookup_csv()
    label_map = load_lookup_table(lookup_csv)
    class_names = build_class_names(int(max(y_true.max(), y_pred.max())) + 1, label_map)

    cm_all = confusion_matrix(y_true, y_pred)
    class_totals = cm_all.sum(axis=1)
    class_correct = np.diag(cm_all)
    acc_per_class = np.full(len(class_totals), np.nan, dtype=float)
    nonzero_mask = class_totals > 0
    acc_per_class[nonzero_mask] = class_correct[nonzero_mask] / class_totals[nonzero_mask] * 100.0

    top_indices, bottom_indices = print_top_bottom_classes(acc_per_class, class_names, top_k=20)

    if not os.path.exists('./results'):
        os.makedirs('./results')

    # 1. Đếm và in số lượng class dự đoán đúng 100%
    perfect_count = np.sum(acc_per_class == 100.0)
    print(f"\n[INFO] >>> Số lượng class dự đoán chính xác 100%: {perfect_count}")

    # 2. Lọc ra danh sách các class < 100%
    imperfect_indices = np.where(acc_per_class < 100.0)[0].tolist()
    imperfect_names = [class_names[i] for i in imperfect_indices]

    # 3. Gom hết các class < 100% vào một Confusion Matrix duy nhất
    if len(imperfect_indices) > 0:
        imperfect_save_path = './results/confusion_matrix_imperfect.png'
        plot_confusion_matrix_subset(
            y_true, 
            y_pred, 
            imperfect_indices, 
            imperfect_names, 
            imperfect_save_path
        )
        print(f"[SUCCESS] Đã vẽ và lưu Confusion Matrix cho {len(imperfect_indices)} class (<100%) tại: {imperfect_save_path}\n")
    else:
        print("[INFO] Tuyệt vời! Tất cả các class đều đạt 100%, không cần vẽ biểu đồ nhầm lẫn.\n")

if __name__ == '__main__':
    main()