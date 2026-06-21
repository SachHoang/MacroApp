# Macro Studio - Lịch sử làm việc

## Thông tin dự án
- **Đường dẫn**: `d:\Hoc\App_test\Macro\`
- **Files chính**: `app.py` (UI + logic), `macro_engine.py` (engine tách riêng, chưa tích hợp vào app.py hiện tại), `code_manager.py` (mới)
- **Framework**: PySide6 + pynput
- **Build**: PyInstaller → `dist/MacroStudio.exe`

## Trạng thái kiến trúc (2026-06-21)

### ⚠️ LƯU Ý QUAN TRỌNG
- File `app.py` hiện tại dùng **kiến trúc monolithic** (1616 dòng):
  - Logic record/play macro nằm TRỰC TIẾP trong class `MacroStudio`
  - Dùng `self.keyboard_controller` (pynput) và `self.mouse_controller` (pynput)
  - Dùng `self.is_running`, `self.stop_event`, `self.runner_thread` để quản lý state
  - Hàm `_execute_action()` ở dòng ~1225, `_run_macro_loop()` ở dòng ~1199
- File `macro_engine.py` có `MacroRunner` và `MacroRecorder` tách riêng, nhưng **CHƯA được tích hợp** vào `app.py` hiện tại
- File `app_backup.py` là bản sao lưu gốc (1640 dòng)

### Palette màu: Cream theme
```python
"bg": "#FDFBF7", "panel": "#FAF5F0", "panelSolid": "#F5EBE6",
"panelAlt": "#FAF5F0", "stroke": "#E8DCD8", "text": "#4A3F3C",
"muted": "#8C7A76", "accent": "#D4A5A5", "accent2": "#C28F8F",
"danger": "#E08283", "success": "#A3B899", "surface": "#FFFFFF"
```

### Cấu trúc UI (3 panels trong QSplitter)
1. **Left Panel** (240px): Điều khiển + Cài đặt chung + Code Manager (MỚI)
2. **Center Panel** (320px): Timeline (danh sách actions) + stats
3. **Right Panel** (480px): Inspector (Add/Edit actions)

## Phiên làm việc

### 2026-06-21: Tích hợp Code Manager
**Mục tiêu**: Thêm chức năng fetch code từ API `yumifang3.site/fang3/zfy` và tự động copy vào clipboard

**API website**:
- Endpoint: `GET https://yumifang3.site/fang3/zfy`
- Response: `{ data: [{ id: "1", context: "nội dung code" }, ...] }`
- Codes có id (số thứ tự) và context (nội dung)

**Thay đổi**:
1. ✅ Tạo `code_manager.py` — module fetch/cache/queue codes
2. ✅ Thêm action type `set_clipboard_code` vào `_execute_action()` trong `app.py`
3. ✅ Thêm panel "Code Manager" vào Left Panel
4. ✅ Thêm nút "Chèn bước nạp code" vào Right Panel (Add Actions)
5. ✅ Tích hợp `code_manager.setup_queue()` khi bắt đầu macro

**Quyết định thiết kế**:
- `set_clipboard_code` dùng `QApplication.clipboard().setText()` (chính xác 100%, không cần Ctrl+C)
- Khi hết code trong queue → macro tự dừng
- codes.json lưu cùng thư mục app, format: `{ "last_updated": "...", "codes": [...] }`

---

### 2026-06-06: Sửa lỗi combo_press trên giả lập
- Thêm delay giữa các phím trong combo (30ms press, 50ms settle, 20ms release)
- Thêm 20ms hold cho key_tap
- Sửa trong `macro_engine.py` (MacroRunner._execute_action)

### 2026-05-18: Refactoring & Theme
- Tách logic sang `macro_engine.py` (MacroRunner, MacroRecorder)
- Chuyển từ Dark theme sang Cream theme
- Sửa lỗi `mouse_controller` not defined → dùng `QtGui.QCursor.pos()`
- Build exe lần đầu

### 2026-05-17: Modernize UI
- Chuyển sang layout 3-column (Control, Timeline, Inspector)
- Áp dụng phong cách "Cruncher-style"
