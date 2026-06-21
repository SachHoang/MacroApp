# MacroStudio

Ứng dụng desktop Windows để ghi, chỉnh sửa và phát lại macro bàn phím, chuột với giao diện hiện đại, trực quan, có chế độ ghi thông minh và cơ chế dừng an toàn.

## 🚀 Các tính năng nổi bật & Cập nhật mới nhất

- **Giao diện hiện đại & thân thiện (Mới):** Cập nhật toàn diện với ngôn ngữ thiết kế phẳng, tông màu sáng thanh lịch, hiệu ứng đổ bóng và bo góc cao cấp. Giao diện được chia bố cục thông minh với **Bảng Cài đặt Chi tiết (Right Panel)** giúp thao tác dễ dàng.
- **Tự động lọc tìm phím (Mới):** Các ô chọn phím (Dropdown) được tích hợp bộ máy Auto-complete, tự động lọc danh sách phím theo các ký tự bạn gõ (ví dụ gõ `E` sẽ ra `enter`, `esc`, v.v.), giúp bạn thao tác siêu tốc mà không cần gõ thủ công.
- **Tổ hợp phím trực quan (Mới):** Cấu hình tổ hợp phím (Combo) trực tiếp qua 3 thẻ chọn riêng biệt thay vì nhập tay chuỗi ký tự dài dòng, hạn chế tối đa rủi ro gõ sai định dạng.
- **Bắt tọa độ thông minh (Mới):** Nút "Chụp tọa độ" liên kết trực tiếp vào khu vực chỉnh sửa để tự động điền giá trị tọa độ X và Y của con trỏ chuột trong 2 giây.
- Khắc phục triệt để các lỗi về lưu thông số và làm mới giao diện.
- **Chức năng gốc:**
  - Ghi lại thao tác bàn phím và chuột theo thời gian thực (Lưu cá nhân, giữ, thả phím và quỹ đạo di chuyển chuột).
  - Ghi đè hoặc ghi nối tiếp macro linh hoạt.
  - Hỗ trợ dừng khẩn cấp bằng phím `F8`.
  - Tự động lưu dữ liệu macro nội bộ vào file `macro_steps.json`.

## 📦 Tải xuống & Cài đặt

Phiên bản có thể chạy ngay không cần cài đặt `.exe` dành cho Windows đã được phát hành trong mục **Releases**:

- **Trang Releases**: [Nhấp vào đây để tải về bản mới nhất](https://github.com/SachHoang/MacroApp/releases)
- **Tải tệp ZIP**: Tải tệp `MacroStudio.zip` mới nhất, giải nén và mở file `MacroStudio.exe` để sử dụng ngay mà không cần cài đặt Python.

## 💻 Dành cho Lập trình viên (Chạy từ mã nguồn)

Công nghệ sử dụng:
- Python 3.13+
- PySide6 (Giao diện)
- pynput (Xử lý thiết bị ngoại vi)
- PyInstaller (Build exe)

Cách chạy lệnh:
```powershell
python -m pip install -r requirements.txt
python app.py
```

Cách build file exe (Windows):
```powershell
python -m PyInstaller --noconfirm --onedir --windowed --name "MacroStudio" "app.py"
```

Thư mục thành phẩm sẽ xuất hiện tại `dist/MacroStudio/`.

## 📖 Hướng dẫn sử dụng nhanh

### 1. Tạo và chỉnh sửa Macro
- Bấm vào một bước ở danh sách bên trái để mở ra **Bảng Cài đặt Chi tiết** bên phải.
- Ở đây bạn có thể chọn **Loại hành động**, đổi phím, đổi thời gian **Delay (ms)**, hoặc sửa **Tọa độ (X, Y)**.
- Gõ thẳng chữ cái mong muốn vào khung chọn phím để tự động lọc ra phím.
- Nhấn **Lưu thay đổi** để cập nhật thay đổi cho bước macro đó.

### 2. Ghi Macro tự động
- Chọn `Ghi thêm` để nối tiếp macro cũ.
- Chọn `Ghi đè` để xóa macro cũ và ghi lại từ đầu.
- Thực hiện thao tác thật trên máy.
- Nhấn `F8` hoặc bấm nút dừng để kết thúc quá trình ghi.

### 3. An toàn thông tin & Git
Dự án đã được thiết lập sẵn `.gitignore` để không tự động đẩy các file chứa thông tin nhạy cảm (như file `macro_steps.json` lưu giữ macro thao tác cá nhân của bạn) lên môi trường Public. Bạn hoàn toàn có thể yên tâm khi tải ứng dụng của mình lên GitHub.

## 🛡️ Giấy phép
Mã nguồn được cung cấp nội bộ, có thể gắn thêm `MIT License` nếu muốn phát hành công khai.
