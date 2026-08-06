import numpy as np
import os
import pandas as pd
from torch.utils.data import Dataset
from feeders import tools


class Feeder(Dataset):
    def __init__(self, data_path, label_path=None, p_interval=[1], split='train', random_choose=False,
                 random_shift=False, random_move=False, random_rot=False, window_size=64, normalization=False, 
                 debug=False, use_mmap=False, bone=False):

        self.debug = debug
        self.data_path = data_path
        self.label_path = label_path
        self.split = split
        self.random_choose = random_choose
        self.random_shift = random_shift
        self.random_move = random_move
        self.window_size = window_size
        self.normalization = normalization
        self.use_mmap = use_mmap
        self.p_interval = p_interval
        self.random_rot = random_rot
        self.bone = bone
        self.load_data()

    def load_data(self):
        # Đọc danh sách tất cả các file .npy trong thư mục
        all_files = sorted([f for f in os.listdir(self.data_path) if f.endswith('.npy')])

        if self.label_path:
            df = pd.read_csv(self.label_path, header=None)
            df[0] = df[0].astype(str)
            df[1] = df[1].astype(int)

            # Convert label về 0-based nếu cần
            if df[1].min() == 1:
                df[1] = df[1] - 1

            label_dict = dict(zip(df[0], df[1]))

            self.file_list = []
            self.label = []

            for f in all_files:
                if f in label_dict:
                    self.file_list.append(f)
                    self.label.append(label_dict[f])

            self.sample_name = self.file_list
            print(f" Loaded {len(self.label)} samples for {self.split}")
        else:
            self.file_list = all_files
            self.label = [0] * len(all_files)
            self.sample_name = self.file_list

        if self.debug:
            self.file_list = self.file_list[:100]
            self.label = self.label[:100]
            self.sample_name = self.sample_name[:100]

    def __len__(self):
        return len(self.file_list)

    def __iter__(self):
        return self

    def __getitem__(self, index):
        # 1. Đọc từng file .npy dựa vào index
        file_name = self.file_list[index]
        file_path = os.path.join(self.data_path, file_name)

        try:
            data_numpy = np.load(file_path, mmap_mode='r' if self.use_mmap else None)
            data_numpy = np.array(data_numpy)
        except Exception as e:
            print(f"⚠️ Lỗi load file {file_name}: {e}")
            # ĐÃ SỬA: Đổi mảng zeros dự phòng từ 48 thành 25 điểm
            data_numpy = np.zeros((3, self.window_size, 25, 1))

        label = self.label[index]

        # Đảm bảo shape (C, T, V, M)
        if len(data_numpy.shape) == 3:
            data_numpy = data_numpy[:, :, :, np.newaxis]

        # 2. NORMALIZATION (LẤY GỐC TỌA ĐỘ TẠI BASE OF SPINE - INDEX 0)
        # Thực ra bước dời tâm đã làm ở bước sinh feature, nhưng code cứ chạy lại cho an toàn
        if self.normalization:
            # ĐÃ SỬA: Lấy khớp 0 (index 0:1) làm tâm thay vì khớp 44
            main_center = data_numpy[:, :, 0:1, :]
            data_numpy = data_numpy - main_center

        valid_frame_num = np.sum(data_numpy.sum(0).sum(-1).sum(-1) != 0)
        if valid_frame_num == 0:
            valid_frame_num = data_numpy.shape[1]

        # 3. Augmentation (Crop, Resize, Rot)
        data_numpy = tools.valid_crop_resize(data_numpy, valid_frame_num, self.p_interval, self.window_size)

        if self.random_rot:
            data_numpy = tools.random_rot(data_numpy)

        # 4. TÍNH ĐỘ DÀI XƯƠNG (BONE) CHO BỘ 25 ĐIỂM
        if self.bone:
            from .bone_pairs import ntu_pairs 
            bone_data_numpy = np.zeros_like(data_numpy)
            for v1, v2 in ntu_pairs:
                bone_data_numpy[:, :, v1] = data_numpy[:, :, v1] - data_numpy[:, :, v2]          
            data_numpy = bone_data_numpy
            
        return data_numpy, label, index

    def top_k(self, score, top_k):
        rank = score.argsort()
        hit_top_k = [l in rank[i, -top_k:] for i, l in enumerate(self.label)]
        return sum(hit_top_k) * 1.0 / len(hit_top_k)


def import_class(name):
    components = name.split('.')
    mod = __import__(components[0])
    for comp in components[1:]:
        mod = getattr(mod, comp)
    return mod