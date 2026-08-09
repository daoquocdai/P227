import numpy as np

file_path = "data/hdcgcn28/val_joint_only/01_Co-Hien_1-100_1-2-3_0108___center_device02_signer01_center_ord1_2.npy"
data = np.load(file_path)

print("Shape:", data.shape)