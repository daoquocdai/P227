import numpy as np

def normalize_pose(pose):
    """
    pose shape: (T, 25, 3)
    Hàm này làm nhiệm vụ Chuẩn hóa tỷ lệ (Scaling) dựa trên chiều dài thân mình
    (khoảng cách cột sống) để quy đổi kích thước cơ thể về một chuẩn chung.
    """
    data = np.copy(pose)
    T, V, C = data.shape

    # Theo sơ đồ NTU-25 (chuyển sang index 0-24):
    # Điểm 1 (Base of Spine) -> index 0
    # Điểm 21 (Spine / Center of Shoulders) -> index 20
    SPINE_BASE = 0
    SPINE_UPPER = 20

    x = data[:, :, 0]
    y = data[:, :, 1]

    # 1. Tính khoảng cách Euclidean giữa Hông và Cột sống trên ở từng frame
    dx = x[:, SPINE_BASE] - x[:, SPINE_UPPER]
    dy = y[:, SPINE_BASE] - y[:, SPINE_UPPER]
    dist = np.sqrt(dx ** 2 + dy ** 2)

    # 2. Lấy khoảng cách trung bình của cả video làm hệ số Scale (giữ độ sâu tự nhiên)
    scale = dist.mean()

    if scale < 1e-6:
        scale = 1  # Tránh lỗi chia cho 0 nếu data bị rác

    # 3. Scale toàn bộ tọa độ
    # Lúc này chiều dài thân mình của mọi đối tượng đều được ép về hệ số ~ 1.0
    data[:, :, 0] /= scale
    data[:, :, 1] /= scale

    if C > 2:
        # Scale luôn cả trục Z (chiều sâu) nếu có
        data[:, :, 2] /= scale

    return data.astype(np.float32)