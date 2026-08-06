import sys
import numpy as np

sys.path.extend(['../'])
from graph import tools

# Đồng bộ với chuẩn NTU-25 (đánh index 0-24)
num_node = 25

class Graph:
    # Đặt CoM = 0 (Base of Spine) làm tâm như bạn đã chốt
    def __init__(self, CoM=0, labeling_mode='spatial'):
        self.num_node = num_node
        self.CoM = CoM
        self.A = self.get_adjacency_matrix(labeling_mode)

    def get_adjacency_matrix(self, labeling_mode=None):
        if labeling_mode is None:
            return self.A

        if labeling_mode == 'spatial':
            # Gọi dataset='NTU' để trỏ đúng vào mảng groups đã thiết lập trong tools.py
            A = tools.get_hierarchical_graph(self.num_node, tools.get_edgeset(dataset='NTU', CoM=self.CoM))
        else:
            raise ValueError("Chỉ hỗ trợ mode 'spatial'")

        return A, self.CoM


if __name__ == '__main__':
    import matplotlib.pyplot as plt

    # Graph().A trả về tuple (A_matrix, CoM). Ta lấy phần tử [0] là A_matrix
    # A_matrix của SDAGCN có shape dạng (Levels, 3, 25, 25)
    A_matrix, _ = Graph().A

    # Lấy Level đầu tiên của đồ thị (shape: 3, 25, 25)
    level_0_matrix = A_matrix[0]

    # Danh sách các kiểu kết nối trong Spatial Configuration
    titles = ['Self-Link (Identity)', 'Inward (Forward)', 'Outward (Reverse)']

    for i, g_ in enumerate(level_0_matrix):
        plt.figure(figsize=(6, 6))
        plt.imshow(g_, cmap='gray')
        plt.title(f"Adjacency Matrix: {titles[i]}")

        cb = plt.colorbar()
        plt.savefig('./graph_{}.png'.format(i))
        cb.remove()
        plt.show()