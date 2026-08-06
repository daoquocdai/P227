import numpy as np

def compute_joint(kpts, max_frames=64):
    """
    kpts: numpy (T, V, 3)
    Output: (3, max_frames, V)
    """

    T, V, C = kpts.shape
    assert C == 3, "Keypoints must have 3 channels (x,y,z)"

    # ==============================
    # CASE 1: T < max_frames (CENTER PAD)
    # ==============================
    if T < max_frames:
        pad_total = max_frames - T

        # ưu tiên bên trái nhiều hơn nếu lẻ
        pad_left = (pad_total + 1) // 2
        pad_right = pad_total - pad_left

        pad_l = np.zeros((pad_left, V, 3), dtype=kpts.dtype)
        pad_r = np.zeros((pad_right, V, 3), dtype=kpts.dtype)

        kpts = np.concatenate([pad_l, kpts, pad_r], axis=0)

    # ==============================
    # CASE 2: T > max_frames (DOWNSAMPLE - GIỮ NGUYÊN)
    # ==============================
    elif T > max_frames:
        num_blocks = max_frames
        base = T // num_blocks
        extra = T % num_blocks

        sizes = [base] * num_blocks

        left = 0
        right = num_blocks - 1
        toggle = True

        # phân phối phần dư
        while extra > 0:
            if toggle:
                sizes[left] += 1
                left += 1
            else:
                sizes[right] += 1
                right -= 1
            toggle = not toggle
            extra -= 1

        indices = []
        start = 0

        for i in range(num_blocks):
            size = sizes[i]
            end = start + size

            if i < num_blocks // 2:
                idx = end - 1   # lấy phải
            else:
                idx = start     # lấy trái

            indices.append(idx)
            start = end

        kpts = kpts[indices]

    # ==============================
    # CASE 3: T == max_frames
    # ==============================
    # giữ nguyên

    # (T, V, 3) → (3, T, V)
    joints = kpts.transpose(2, 0, 1)

    return joints.astype(np.float32)