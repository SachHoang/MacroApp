# MacroApp

Ứng dụng desktop Windows để ghi, chỉnh sửa và phát lại macro bàn phím, chuột với giao diện trực quan, có chế độ ghi thông minh và cơ chế dừng an toàn.

## Điểm nổi bật

- Ghi lại thao tác bàn phím và chuột theo thời gian thực
- Lưu cả nhấn, giữ, thả phím và quỹ đạo di chuyển chuột
- Phát macro tuần tự theo vòng lặp cho đến khi dừng
- Hỗ trợ tổ hợp phím như `Ctrl+C`, `Ctrl+V`, `Ctrl+Shift+S`
- Chỉnh sửa từng action trực tiếp trong timeline editor
- Dừng khẩn cấp bằng phím `F8` hoặc kéo chuột lên góc trên trái màn hình
- Tự động lưu dữ liệu macro cục bộ vào `macro_steps.json`

## Tải ứng dụng

Phiên bản `.exe` cho Windows sẽ được phát hành trong mục `Releases` của repo:

- Repo: <https://github.com/SachHoang/MacroApp>
- Releases: <https://github.com/SachHoang/MacroApp/releases>

Nếu bạn chỉ muốn dùng app mà không cần cài Python, hãy tải file `StudioMacro.exe` từ trang release.

## Công nghệ sử dụng

- Python 3
- PySide6
- pynput
- PyInstaller

## Chạy từ mã nguồn

```powershell
python -m pip install -r requirements.txt
python app.py
```

## Build file EXE

```powershell
build_exe.bat
```

Hoặc build thủ công:

```powershell
python -m PyInstaller --noconfirm --clean macro_studio.spec
```

File chạy sau khi build nằm tại:

```text
dist\StudioMacro.exe
```

## Cách sử dụng nhanh

### 1. Tạo macro

- Thêm phím đơn như `a`, `enter`, `space`
- Thêm tổ hợp phím với modifier và phím chính
- Thêm click chuột theo tọa độ
- Thêm bước chờ theo milliseconds

### 2. Ghi macro tự động

- Chọn `Ghi thêm` để nối tiếp macro cũ
- Chọn `Ghi thay thế` để xóa macro cũ và ghi lại từ đầu
- Thực hiện thao tác thật trên máy
- Nhấn `F8` hoặc bấm nút dừng để kết thúc ghi

### 3. Phát macro

- Nhấn `Bắt đầu`
- Macro sẽ chạy tuần tự từng bước
- Macro lặp liên tục cho đến khi bạn dừng

## Timeline editor

- Chọn một action trong danh sách để chỉnh sửa chi tiết
- Có thể đổi loại action, delay, key, click, combo hoặc quỹ đạo chuột
- Với `mouse move`, mỗi dòng dữ liệu có dạng `t,x,y`
- Có thể áp dụng thay đổi, nhân bản hoặc chèn action mới ngay dưới action hiện tại

## Lưu ý an toàn

- App macro có thể tự thao tác chuột và bàn phím trên máy thật
- Luôn kiểm tra kỹ trước khi chạy vòng lặp dài
- Dùng `F8` để dừng khẩn cấp nếu macro chạy sai
- Không đưa `macro_steps.json` lên GitHub vì file này có thể chứa dữ liệu thao tác riêng của bạn

## Đưa source lên GitHub an toàn

Repo đã được cấu hình để không commit các dữ liệu dễ lộ thông tin cá nhân:

- `build/`
- `dist/`
- `__pycache__/`
- `macro_steps.json`
- file `.env` và các file secret cục bộ

Chi tiết thêm có trong [GITHUB_UPLOAD_GUIDE.md](./GITHUB_UPLOAD_GUIDE.md).

## Cấu trúc dự án

```text
.
|-- app.py
|-- build_exe.bat
|-- macro_studio.spec
|-- requirements.txt
|-- macro_steps.example.json
|-- README.md
```

## Hướng phát triển

- Thêm import/export macro dễ dùng hơn
- Thêm preset macro mẫu
- Tối ưu giao diện và trải nghiệm chỉnh sửa timeline
- Thêm versioning cho file macro

## Giấy phép

Hiện repo chưa gắn license. Nếu bạn muốn public rộng rãi, nên thêm `MIT License`.
