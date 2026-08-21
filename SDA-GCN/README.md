B1: pip install -r requirements
B2: pip install -e torchlight
B3; chạy file recognize/capture_data.py để đăng kí khuôn mặt,bấm c để bắt đầu lấy ảnh, c để dừng. Muốn thoát thì bấm q
Muốn chạy thì chạy file realtime.py, đừng chạy realtimentu.py
Lệnh tải model mediapipe:
 Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task" -OutFile "pose_landmarker_full.task"
