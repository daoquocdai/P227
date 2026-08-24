import cv2
import os
import glob

def process_video(video_path, output_dir, window_size=64, step_size=10):
    """
    Cắt video thành các đoạn ngắn (sliding window).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error opening video {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        fps = 30.0 # Giá trị mặc định nếu không đọc được FPS

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    video_name = os.path.basename(video_path)
    name_no_ext, ext = os.path.splitext(video_name)
    
    # Chuyển sang dùng codec XVID và lưu thành file .avi để tránh lỗi OpenH264 và vẫn mượt mà
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    
    buffer = []
    current_frame = 0
    window_idx = 0
    
    print(f"  - Starting: {video_name} (FPS: {fps}, {width}x{height})")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        buffer.append(frame)
        if len(buffer) > window_size:
            buffer.pop(0) # Loại bỏ frame cũ nhất để giữ kích thước cửa sổ là 64
            
        # Nếu buffer đã đủ 64 frames
        if len(buffer) == window_size:
            # Kiểm tra xem có đúng bước nhảy k=20 không (tính từ frame cuối cùng của window)
            # Window 0: 0 -> 63 (current_frame = 63)
            # Window 1: 20 -> 83 (current_frame = 83)
            if (current_frame - (window_size - 1)) % step_size == 0:
                start_frame = current_frame - window_size + 1
                out_name = f"{name_no_ext}_{start_frame:04d}_to_{current_frame:04d}.avi"
                out_path = os.path.join(output_dir, out_name)
                
                out = cv2.VideoWriter(out_path, fourcc, fps, (width, height))
                for f in buffer:
                    out.write(f)
                out.release()
                
                window_idx += 1
                
        current_frame += 1

    cap.release()
    print(f"  -> Finished {video_name}, generated {window_idx} clips.\n")

def main():
    input_dir = 'thi'
    output_dir = 'Videotrain_cut1'
    
    # Tạo folder mới nếu chưa có
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")
        
    # Lấy tất cả các file video mp4, mov
    video_files = []
    for ext in ('*.mp4', '*.mov', '*.MP4', '*.MOV'):
        video_files.extend(glob.glob(os.path.join(input_dir, ext)))
        
    if not video_files:
        print(f"No videos found in {input_dir}")
        return
        
    print(f"Found {len(video_files)} videos. Starting processing...")
    
    for vf in video_files:
        process_video(vf, output_dir, window_size=64, step_size=20)

if __name__ == '__main__':
    main()
