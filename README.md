# Studio Macro - Trình Ghi và Phát Macro Tự Động

Ứng dụng desktop Windows để tạo và phát lại macro chuỗi thao tác bàn phím và chuột với chế độ ghi thông minh.

## Tính năng chính

- **Thêm bước thủ công**: Thêm các hành động như nhấn phím, click chuột, chờ thời gian
- **Phát macro tuần tự**: Chạy các bước theo đúng thứ tự đã thiết lập
- **Lặp vô hạn**: Macro sẽ chạy liên tục cho đến khi bạn dừng
- **Dừng an toàn**: Dừng bằng nút "Dừng", phím nóng F8, hoặc kéo chuột lên góc trên trái màn hình
- **Ghi thông minh**: Ghi lại thao tác với thời gian thực giữa các bước
- **Ghi giữ/thả phím**: Tự động ghi cả việc giữ và thả phím
- **Ghi quỹ đạo chuột**: Lưu lại đường di chuyển của chuột theo thời gian
- **Chế độ ghi**: "Ghi thêm" (nối vào macro cũ) hoặc "Ghi thay thế" (xóa macro cũ)
- **Chỉnh sửa chi tiết**: Sửa từng bước trong trình chỉnh sửa timeline
- **Tổ hợp phím**: Hỗ trợ thêm tổ hợp như Ctrl+C, Ctrl+V, Ctrl+Shift+S
- **Tự động lưu**: Macro được lưu vào file `macro_steps.json`
- **Giao diện hiện đại**: Thiết kế với hiệu ứng kính mờ/acrylic trên Windows

## Cài đặt và chạy

```powershell
python -m pip install -r requirements.txt
python app.py
```

## Xuất file EXE

```powershell
build_exe.bat
```

- Sau khi build xong, file chạy sẽ nằm ở `dist\StudioMacro.exe`
- Nếu muốn build thủ công: `python -m PyInstaller --noconfirm --clean macro_studio.spec`

## Hướng dẫn sử dụng

### 1. Thêm bước macro

Ở panel bên phải, sử dụng các phần:

- **Thêm phím nhanh**: Nhập phím đơn như 'a', 'enter', 'space'. Ví dụ: Nhấn 'a' để nhập chữ a.
- **Thêm tổ hợp phím**: Chọn modifier (Ctrl, Shift, Alt, Win) và phím chính. Ví dụ: Ctrl + C để sao chép.
- **Thêm click chuột**: Nhập tọa độ X,Y và chọn nút chuột. Sử dụng "Chụp vị trí chuột" để lấy vị trí hiện tại.
- **Thêm bước chờ**: Nhập thời gian chờ tính bằng ms. Ví dụ: 1000ms = 1 giây chờ.

### 2. Sắp xếp thứ tự

Sử dụng nút "Lên" và "Xuống" để di chuyển bước trong timeline.

### 3. Phát macro

- Bấm "Bắt đầu" để chạy vòng lặp vô hạn
- Macro sẽ lặp lại liên tục cho đến khi dừng

### 4. Ghi macro tự động

- Bấm "Ghi thêm" hoặc "Ghi thay thế"
- App sẽ chờ số giây đã cấu hình rồi bắt đầu ghi
- Thực hiện các thao tác cần ghi
- Bấm "Dừng ghi" hoặc F8 để kết thúc
- Ví dụ: Mở Notepad, ghi macro nhấn 'H', 'e', 'l', 'l', 'o' với thời gian thực

## Ví dụ sử dụng

### Macro chào hỏi

1. Thêm phím: 'H' (delay 100ms)
2. Thêm phím: 'i' (delay 100ms)
3. Thêm phím: '!' (delay 100ms)
4. Bắt đầu phát - sẽ nhập "Hi!" liên tục

### Macro sao chép-dán

1. Thêm tổ hợp: Ctrl + C
2. Thêm bước chờ: 200ms
3. Thêm tổ hợp: Ctrl + V
4. Bắt đầu phát - sẽ sao chép và dán liên tục

### Macro click tự động

1. Chụp vị trí chuột tại nút cần click
2. Thêm click chuột tại tọa độ đó
3. Thêm bước chờ: 1000ms
4. Bắt đầu phát - sẽ click nút mỗi giây

## Lưu ý

- Sử dụng F8 để dừng khẩn cấp khi macro chạy
- Kéo chuột lên góc trên trái cũng dừng macro
- Macro được lưu tự động vào `macro_steps.json`
- Có thể chỉnh sửa chi tiết từng bước trong timeline editor

## Timeline editor

- Chọn một action trong timeline để xem và chỉnh trực tiếp.
- Có thể đổi loại action, delay, key, tổ hợp key, click chuột, hoặc toàn bộ quỹ đạo `mouse move`.
- Với `mouse move`, mỗi dòng có dạng `t,x,y`.
- Có nút áp dụng, nhân bản, chèn thêm ngay dưới action đang chọn.

## Tổ hợp phím

- Dùng panel `Thêm tổ hợp phím` để thêm nhanh các macro như `Ctrl+C`, `Ctrl+V`.
- App sẽ nhấn các modifier trước, nhấn key chính, rồi nhả theo thứ tự ngược lại.

## Ghi chú

- Macro chạy tuần tự từng bước, không chạy song song.
- Ví dụ chuỗi `A, A, A` sẽ chạy xong `A` đầu rồi mới tới `A` tiếp theo.
- File macro hiện tại được lưu ở `macro_steps.json`.
