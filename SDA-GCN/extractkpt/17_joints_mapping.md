# Bảng Ánh Xạ 17 Khớp Xương (Skeleton 17-Joints)
*Dành cho việc tích hợp mô hình YOLO 2D vào mạng VideoPose3D*

Khi bạn nhận kết quả tọa độ từ YOLO (hoặc bất kì thuật toán dò 2D nào), bạn **bắt buộc** phải sắp xếp mảng 2D đầu ra (đầu vào của VideoPose3D) theo đúng thứ tự 17 chỉ số (index) dưới đây để thuật toán hoạt động chính xác.

Khớp gốc của vũ trụ (Root) là điểm số `0` (Pelvis). Hệ thống sẽ tự động trừ tọa độ của Pelvis cho mọi điểm khác.

| Chỉ Số (Index) | Tên Khớp (Tiếng Anh) | Mô tả (Tiếng Việt) | Khớp Gốc Tương Ứng Ở NTU RGB+D |
| :---: | :--- | :--- | :--- |
| **0** | **Pelvis** | Khớp hông trung tâm (Root) | Điểm số 0 (Spine Base) |
| **1** | **R Hip** | Hông bên phải | Điểm số 16 (Hip Right) |
| **2** | **R Knee** | Đầu gối bên phải | Điểm số 17 (Knee Right) |
| **3** | **R Ankle** | Cổ chân bên phải | Điểm số 18 (Ankle Right) |
| **4** | **R Foot** | Bàn chân bên phải | Điểm số 19 (Foot Right) |
| **5** | **L Hip** | Hông bên trái | Điểm số 12 (Hip Left) |
| **6** | **L Knee** | Đầu gối bên trái | Điểm số 13 (Knee Left) |
| **7** | **L Ankle** | Cổ chân bên trái | Điểm số 14 (Ankle Left) |
| **8** | **L Foot** | Bàn chân bên trái | Điểm số 15 (Foot Left) |
| **9** | **Spine / Neck** | Xương sống trên / Cổ | Điểm số 20 (Spine Shoulder) |
| **10** | **Head** | Đầu | Điểm số 3 (Head) |
| **11** | **L Shoulder** | Vai bên trái | Điểm số 4 (Shoulder Left) |
| **12** | **L Elbow** | Khuỷu tay bên trái | Điểm số 5 (Elbow Left) |
| **13** | **L Wrist** | Cổ tay bên trái | Điểm số 6 (Wrist Left) |
| **14** | **R Shoulder** | Vai bên phải | Điểm số 8 (Shoulder Right) |
| **15** | **R Elbow** | Khuỷu tay bên phải | Điểm số 9 (Elbow Right) |
| **16** | **R Wrist** | Cổ tay bên phải | Điểm số 10 (Wrist Right) |

---
**Ví dụ code ghép với YOLO:**
Khi xuất ra list tọa độ, bạn cấu trúc như sau:
```python
keypoints_17 = [
    pelvis_xy,        # 0
    right_hip_xy,     # 1
    right_knee_xy,    # 2
    right_ankle_xy,   # 3
    right_foot_xy,    # 4
    left_hip_xy,      # 5
    left_knee_xy,     # 6
    left_ankle_xy,    # 7
    left_foot_xy,     # 8
    neck_xy,          # 9
    head_xy,          # 10
    left_shoulder_xy, # 11
    left_elbow_xy,    # 12
    left_wrist_xy,    # 13
    right_shoulder_xy,# 14
    right_elbow_xy,   # 15
    right_wrist_xy    # 16
]
```
