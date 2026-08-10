# P-227

Repository gồm module thị giác máy tính trong thư mục `vision/` và các thành phần
tích hợp khác ở cấp repository.

## Chạy module vision

Các script vision sử dụng đường dẫn tương đối. Vì vậy, hãy chạy lệnh từ thư mục
`vision`:

```bash
cd vision
pip install -r ../requirements.txt
pip install -e torchlight
```

Đăng ký khuôn mặt:

```bash
python recognize/capture_data.py
```

Nhấn `c` để bắt đầu hoặc dừng lấy ảnh, nhấn `q` để thoát.

Chạy nhận diện thời gian thực:

```bash
python realtime.py
```

Không sử dụng `realtimentu.py` làm entry point chính.
