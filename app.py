import ctypes
import json
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional
from PySide6 import QtCore, QtGui, QtWidgets
from pynput import keyboard, mouse
from code_manager import CodeManager, CodeItem


# Xác định vị trí lưu macro_steps.json
# Nếu chạy từ .exe (PyInstaller), lưu cùng thư mục với .exe
# Nếu chạy từ source code, lưu cùng thư mục với app.py
if getattr(sys, 'frozen', False):
    CONFIG_PATH = Path(sys.executable).parent / "macro_steps.json"
    CODES_PATH = Path(sys.executable).parent / "codes.json"
else:
    CONFIG_PATH = Path(__file__).with_name("macro_steps.json")
    CODES_PATH = Path(__file__).with_name("codes.json")
DEFAULT_DELAY_MS = 250
FAILSAFE_X = 0
FAILSAFE_Y = 0
MOVE_SAMPLE_MS = 18
MOVE_MIN_DISTANCE = 3


@dataclass
class MacroAction:
    action_type: str
    key: str = ""
    keys: list[str] = field(default_factory=list)
    x: int = 0
    y: int = 0
    button: str = "left"
    duration_ms: int = 0
    post_delay_ms: int = DEFAULT_DELAY_MS
    points: list[dict[str, int]] = field(default_factory=list)

    def describe(self) -> str:
        if self.action_type == "key_tap":
            return f"Tap phím {self.key} | nghỉ {self.post_delay_ms}ms"
        if self.action_type == "key_down":
            return f"Giữ phím xuống {self.key} | nghỉ {self.post_delay_ms}ms"
        if self.action_type == "key_up":
            return f"Nhả phím {self.key} | nghỉ {self.post_delay_ms}ms"
        if self.action_type == "mouse_click":
            return f"Click {self.button} tại ({self.x}, {self.y}) | nghỉ {self.post_delay_ms}ms"
        if self.action_type == "combo_press":
            combo = " + ".join(self.keys) if self.keys else self.key
            return f"Tổ hợp {combo} | nghỉ {self.post_delay_ms}ms"
        if self.action_type == "mouse_move":
            return f"Di chuột theo quỹ đạo {len(self.points)} điểm | nghỉ {self.post_delay_ms}ms"
        if self.action_type == "wait":
            return f"Chờ {self.duration_ms}ms"
        if self.action_type == "set_clipboard_code":
            return f"📋 Nạp code tiếp theo vào clipboard | nghỉ {self.post_delay_ms}ms"
        if self.action_type == "type_code":
            return f"✍️ Gõ thẳng code tiếp theo | nghỉ {self.post_delay_ms}ms"
        return f"Không rõ: {self.action_type}"


class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint32),
        ("AnimationId", ctypes.c_int),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


COMMON_KEYS = [
    *("abcdefghijklmnopqrstuvwxyz"),
    *("0123456789"),
    "enter", "space", "tab", "esc", "shift", "shift_l", "shift_r",
    "ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "cmd",
    "backspace", "delete", "home", "end", "page_up", "page_down",
    "up", "down", "left", "right", "caps_lock",
    *([f"f{i}" for i in range(1, 13)])
]

class MacroStudio(QtWidgets.QMainWindow):
    refresh_actions_requested = QtCore.Signal()
    status_changed = QtCore.Signal(str)
    loop_changed = QtCore.Signal(str)
    position_captured = QtCore.Signal(int, int)
    stop_recording_requested = QtCore.Signal()
    stop_macro_requested = QtCore.Signal()
    clipboard_set_requested = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Studio Macro - Ghi và Phát Macro Tự Động")
        self._aspect_ratio = 16 / 9
        self._resizing_guard = False
        self.resize(1280, 720)
        self.setMinimumSize(960, 540)

        self.actions: list[MacroAction] = []
        self.actions_lock = threading.Lock()
        self.is_running = False
        self.is_recording = False
        self.record_replace_mode = False
        self.stop_event = threading.Event()
        self.runner_thread: Optional[threading.Thread] = None
        self.record_keyboard_listener: Optional[keyboard.Listener] = None
        self.record_mouse_listener: Optional[mouse.Listener] = None
        self.hotkey_listener: Optional[keyboard.GlobalHotKeys] = None
        self.record_start_timer: Optional[threading.Thread] = None
        self.record_last_event_time: Optional[float] = None
        self.record_last_action_index: Optional[int] = None
        self.record_current_move_index: Optional[int] = None
        self.record_current_move_start: Optional[float] = None
        self.record_current_move_last_sample: Optional[float] = None
        self.record_current_move_last_position: Optional[tuple[int, int]] = None
        self.record_active_modifiers: set[str] = set()
        self.record_combo_down_keys: set[str] = set()

        self.keyboard_controller = keyboard.Controller()
        self.mouse_controller = mouse.Controller()

        self.palette = {
            "bg": "#FDFBF7",
            "panel": "#FAF5F0",
            "panelSolid": "#F5EBE6",
            "panelAlt": "#FAF5F0",
            "stroke": "#E8DCD8",
            "text": "#4A3F3C",
            "muted": "#8C7A76",
            "accent": "#D4A5A5",
            "accent2": "#C28F8F",
            "danger": "#E08283",
            "success": "#A3B899",
            "surface": "#FFFFFF",
        }

        self.record_mode_text = "Thêm vào"
        self._updating_editor = False

        self._build_ui()
        self._connect_signals()
        self._apply_styles()
        self._apply_window_effects()
        self._load_actions()
        self._start_hotkey_listener()

        # Code Manager
        self.code_manager = CodeManager(CODES_PATH)
        self.code_manager.codes_loaded.connect(self._on_codes_loaded)
        self.code_manager.error_occurred.connect(lambda msg: QtWidgets.QMessageBox.warning(self, "Code Manager", msg))
        
        self.clipboard_set_requested.connect(self._set_clipboard_text)

    @QtCore.Slot(str)
    def _set_clipboard_text(self, text: str) -> None:
        QtWidgets.QApplication.clipboard().setText(text)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if getattr(self, '_resizing_guard', False):
            return
            
        scale = max(0.75, min(2.0, self.width() / 1280.0))
        if not hasattr(self, '_last_scale_factor') or abs(self._last_scale_factor - scale) > 0.05:
            self._last_scale_factor = scale
            if not hasattr(self, '_resize_timer'):
                self._resize_timer = QtCore.QTimer(self)
                self._resize_timer.setSingleShot(True)
                self._resize_timer.timeout.connect(self._apply_styles)
            self._resize_timer.start(50)

    def _connect_signals(self) -> None:
        self.refresh_actions_requested.connect(self._refresh_action_list)
        self.status_changed.connect(self._set_status)
        self.loop_changed.connect(self.loop_value.setText)
        self.position_captured.connect(self._apply_captured_position)
        self.stop_recording_requested.connect(self._stop_recording)
        self.stop_macro_requested.connect(self._stop_macro)

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        central.setObjectName("AppRoot")
        self.setCentralWidget(central)

        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        
        # ==========================================
        # TOP HEADER BAR
        # ==========================================
        header = QtWidgets.QWidget()
        header.setObjectName("TopHeader")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)
        header_layout.setSpacing(16)
        
        # Left side: Title & Status
        title_layout = QtWidgets.QVBoxLayout()
        title_layout.setSpacing(2)
        hero_title = QtWidgets.QLabel("Macro Studio")
        hero_title.setObjectName("HeroTitle")
        self.status_label = QtWidgets.QLabel("Sẵn sàng. Dừng macro bằng phím F8 hoặc kéo chuột lên góc trái màn hình.")
        self.status_label.setObjectName("StatusLabel")
        title_layout.addWidget(hero_title)
        title_layout.addWidget(self.status_label)
        header_layout.addLayout(title_layout)
        
        header_layout.addStretch(1)
        
        # Right side: Main Controls
        controls_layout = QtWidgets.QHBoxLayout()
        controls_layout.setSpacing(8)
        
        self.start_button = QtWidgets.QPushButton("▶ Bắt đầu (F8)")
        self.start_button.setProperty("variant", "primary")
        self.start_button.clicked.connect(self._start_macro)
        
        self.stop_button = QtWidgets.QPushButton("■ Dừng")
        self.stop_button.setProperty("variant", "danger")
        self.stop_button.clicked.connect(self._stop_macro)
        
        record_append = QtWidgets.QPushButton("● Ghi thêm")
        record_append.setProperty("variant", "secondary")
        record_append.clicked.connect(lambda: self._toggle_recording(False))
        
        record_replace = QtWidgets.QPushButton("● Ghi đè")
        record_replace.setProperty("variant", "secondary")
        record_replace.clicked.connect(lambda: self._toggle_recording(True))
        
        stop_record = QtWidgets.QPushButton("■ Dừng ghi")
        stop_record.setProperty("variant", "secondary")
        stop_record.clicked.connect(self._stop_recording)
        
        capture_button = QtWidgets.QPushButton("◎ Chụp tọa độ")
        capture_button.setProperty("variant", "secondary")
        capture_button.clicked.connect(self._capture_mouse_position)
        
        controls_layout.addWidget(capture_button)
        controls_layout.addWidget(record_replace)
        controls_layout.addWidget(record_append)
        controls_layout.addWidget(stop_record)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addWidget(self.start_button)
        
        header_layout.addLayout(controls_layout)
        root.addWidget(header)
        
        # ==========================================
        # MAIN BODY (3-Column Splitter)
        # ==========================================
        body_container = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(body_container)
        body_layout.setContentsMargins(16, 16, 16, 16)
        
        self.body_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.body_splitter.setHandleWidth(8)
        body_layout.addWidget(self.body_splitter)
        root.addWidget(body_container, 1)

        # ------------------------------------------
        # 1. LEFT PANEL (Palette: Tools, Code, Settings)
        # ------------------------------------------
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self.left_tabs = QtWidgets.QTabWidget()
        self.left_tabs.setObjectName("SidebarTabs")
        left_layout.addWidget(self.left_tabs)
        
        # TAB: Thêm hành động
        tools_tab = QtWidgets.QWidget()
        tools_layout = QtWidgets.QVBoxLayout(tools_tab)
        tools_layout.setContentsMargins(12, 16, 12, 12)
        tools_layout.setSpacing(10)
        tools_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        
        def _add_tool_btn(icon, text, handler):
            btn = QtWidgets.QPushButton(f"{icon}  {text}")
            btn.setProperty("variant", "tool")
            btn.clicked.connect(handler)
            tools_layout.addWidget(btn)
            
        _add_tool_btn("⌨️", "Thêm phím (Key)", self._add_key_action)
        _add_tool_btn("🔠", "Thêm tổ hợp phím (Combo)", self._add_combo_action)
        _add_tool_btn("🖱️", "Thêm click chuột (Mouse)", self._add_mouse_action)
        _add_tool_btn("⏱️", "Thêm chờ (Wait)", self._add_wait_action)
        _add_tool_btn("📋", "Dán Code (Clipboard)", self._add_clipboard_code_action)
        _add_tool_btn("✍️", "Gõ Code (Type)", self._add_type_code_action)
        
        tools_layout.addStretch(1)
        self.left_tabs.addTab(tools_tab, "🛠️ Công cụ")
        
        # TAB: Code Manager
        code_tab = QtWidgets.QWidget()
        code_layout = QtWidgets.QVBoxLayout(code_tab)
        code_layout.setContentsMargins(12, 16, 12, 12)
        code_layout.setSpacing(12)
        
        code_form = QtWidgets.QFormLayout()
        code_form.setSpacing(8)
        self.code_range_input = QtWidgets.QLineEdit("1-50")
        code_form.addRow("Phạm vi", self.code_range_input)
        code_layout.addLayout(code_form)
        
        code_btn_grid = QtWidgets.QGridLayout()
        code_btn_grid.setSpacing(8)
        fetch_btn = QtWidgets.QPushButton("🌐 Tải web")
        fetch_btn.setProperty("variant", "secondary")
        fetch_btn.clicked.connect(self._fetch_codes)
        load_json_btn = QtWidgets.QPushButton("📂 Tải file")
        load_json_btn.setProperty("variant", "secondary")
        load_json_btn.clicked.connect(self._load_codes_from_json)
        code_btn_grid.addWidget(fetch_btn, 0, 0)
        code_btn_grid.addWidget(load_json_btn, 0, 1)
        code_layout.addLayout(code_btn_grid)
        
        self.code_status_label = QtWidgets.QLabel("Chưa tải code")
        self.code_status_label.setObjectName("MutedLabel")
        code_layout.addWidget(self.code_status_label)
        
        self.code_list_widget = QtWidgets.QListWidget()
        self.code_list_widget.setObjectName("CodeList")
        code_layout.addWidget(self.code_list_widget, 1)
        
        self.left_tabs.addTab(code_tab, "🎮 Code")
        
        # TAB: Cài đặt
        settings_tab = QtWidgets.QWidget()
        settings_layout = QtWidgets.QFormLayout(settings_tab)
        settings_layout.setContentsMargins(12, 16, 12, 12)
        settings_layout.setSpacing(12)
        
        self.default_delay_input = QtWidgets.QLineEdit(str(DEFAULT_DELAY_MS))
        self.record_after_input = QtWidgets.QLineEdit("2")
        settings_layout.addRow("Delay mặc định (ms)", self.default_delay_input)
        settings_layout.addRow("Chờ trước ghi (giây)", self.record_after_input)
        
        self.left_tabs.addTab(settings_tab, "⚙️ Cài đặt")
        
        self.body_splitter.addWidget(left_panel)

        # ------------------------------------------
        # 2. CENTER PANEL (Canvas / Timeline)
        # ------------------------------------------
        center_panel = self._create_card()
        center_layout = QtWidgets.QVBoxLayout(center_panel)
        center_layout.setContentsMargins(16, 16, 16, 16)
        center_layout.setSpacing(12)
        
        # Stats Header
        stats = QtWidgets.QHBoxLayout()
        stats.setSpacing(16)
        
        def _create_mini_stat(title, val):
            vbox = QtWidgets.QVBoxLayout()
            vbox.setSpacing(2)
            t_lbl = QtWidgets.QLabel(title)
            t_lbl.setObjectName("MutedLabel")
            v_lbl = QtWidgets.QLabel(val)
            v_lbl.setObjectName("StatValue")
            vbox.addWidget(t_lbl)
            vbox.addWidget(v_lbl)
            return vbox, v_lbl
            
        box1, self.steps_value = _create_mini_stat("Số bước", "0")
        box2, self.loop_value = _create_mini_stat("Vòng lặp", "0")
        box3, self.mode_value = _create_mini_stat("Chế độ", "Thêm vào")
        stats.addLayout(box1)
        stats.addLayout(box2)
        stats.addLayout(box3)
        stats.addStretch(1)
        center_layout.addLayout(stats)
        
        # Timeline List
        self.action_list = QtWidgets.QListWidget()
        self.action_list.setObjectName("TimelineList")
        self.action_list.currentRowChanged.connect(self._handle_timeline_selection)
        center_layout.addWidget(self.action_list, 1)
        
        # Timeline Toolbar
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        
        btn_up = QtWidgets.QPushButton("▲ Lên")
        btn_up.setProperty("variant", "ghost")
        btn_up.clicked.connect(lambda: self._move_selected(-1))
        
        btn_down = QtWidgets.QPushButton("▼ Xuống")
        btn_down.setProperty("variant", "ghost")
        btn_down.clicked.connect(lambda: self._move_selected(1))
        
        btn_del = QtWidgets.QPushButton("✖ Xóa")
        btn_del.setProperty("variant", "ghost")
        btn_del.clicked.connect(self._remove_selected)
        
        btn_clear = QtWidgets.QPushButton("Xóa hết")
        btn_clear.setProperty("variant", "ghost")
        btn_clear.clicked.connect(self._clear_actions)
        
        btn_save = QtWidgets.QPushButton("💾 Lưu")
        btn_save.setProperty("variant", "secondary")
        btn_save.clicked.connect(self._save_actions)
        
        btn_load = QtWidgets.QPushButton("📂 Nạp")
        btn_load.setProperty("variant", "secondary")
        btn_load.clicked.connect(self._load_actions)
        
        toolbar.addWidget(btn_up)
        toolbar.addWidget(btn_down)
        toolbar.addWidget(btn_del)
        toolbar.addWidget(btn_clear)
        toolbar.addStretch(1)
        toolbar.addWidget(btn_load)
        toolbar.addWidget(btn_save)
        
        center_layout.addLayout(toolbar)
        self.body_splitter.addWidget(center_panel)

        # ------------------------------------------
        # 3. RIGHT PANEL (Inspector)
        # ------------------------------------------
        right_panel = self._create_card(alt=True)
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)
        
        self.inspector_stack = QtWidgets.QStackedWidget()
        right_layout.addWidget(self.inspector_stack)
        
        # Page 0: Empty State
        empty_page = QtWidgets.QWidget()
        empty_layout = QtWidgets.QVBoxLayout(empty_page)
        empty_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        empty_lbl = QtWidgets.QLabel("📝 Chọn một hành động để chỉnh sửa")
        empty_lbl.setObjectName("EmptyLabel")
        empty_layout.addWidget(empty_lbl)
        self.inspector_stack.addWidget(empty_page)
        
        # Page 1: Edit Action
        edit_scroll = QtWidgets.QScrollArea()
        edit_scroll.setWidgetResizable(True)
        edit_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        edit_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        edit_host = QtWidgets.QWidget()
        edit_scroll.setWidget(edit_host)
        edit_layout = QtWidgets.QVBoxLayout(edit_host)
        edit_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(16)
        
        editor_title = QtWidgets.QLabel("Thuộc tính")
        editor_title.setObjectName("SectionTitle")
        edit_layout.addWidget(editor_title)
        
        editor_form = QtWidgets.QFormLayout()
        editor_form.setSpacing(12)
        self.editor_action_type = QtWidgets.QComboBox()
        self.editor_action_type.addItems(["key_tap", "key_down", "key_up", "combo_press", "mouse_click", "mouse_move", "wait", "set_clipboard_code", "type_code"])
        self.editor_action_type.currentTextChanged.connect(self._update_editor_stack_visibility)
        self.editor_post_delay = QtWidgets.QLineEdit("250")
        editor_form.addRow("Loại action", self.editor_action_type)
        editor_form.addRow("Delay sau bước (ms)", self.editor_post_delay)
        edit_layout.addLayout(editor_form)
        
        self.editor_stack = QtWidgets.QStackedWidget()
        edit_layout.addWidget(self.editor_stack)
        
        # Edit Pages
        self.editor_page_key = self._make_editor_page()
        key_form2 = QtWidgets.QFormLayout(self.editor_page_key)
        self.editor_key_input = QtWidgets.QComboBox()
        self.editor_key_input.addItems(COMMON_KEYS)
        self.editor_key_input.setEditable(True)
        completer = QtWidgets.QCompleter(COMMON_KEYS)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        completer.setFilterMode(QtCore.Qt.MatchContains)
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.editor_key_input.setCompleter(completer)
        key_form2.addRow("Key", self.editor_key_input)
        self.editor_stack.addWidget(self.editor_page_key)
        
        self.editor_page_combo = self._make_editor_page()
        combo_form2 = QtWidgets.QFormLayout(self.editor_page_combo)
        self.editor_combo_key1 = QtWidgets.QComboBox()
        self.editor_combo_key1.addItems([""] + COMMON_KEYS)
        self.editor_combo_key1.setEditable(True)
        completer = QtWidgets.QCompleter([""] + COMMON_KEYS)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        completer.setFilterMode(QtCore.Qt.MatchContains)
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.editor_combo_key1.setCompleter(completer)
        self.editor_combo_key2 = QtWidgets.QComboBox()
        self.editor_combo_key2.addItems([""] + COMMON_KEYS)
        self.editor_combo_key2.setEditable(True)
        completer = QtWidgets.QCompleter([""] + COMMON_KEYS)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        completer.setFilterMode(QtCore.Qt.MatchContains)
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.editor_combo_key2.setCompleter(completer)
        self.editor_combo_key3 = QtWidgets.QComboBox()
        self.editor_combo_key3.addItems([""] + COMMON_KEYS)
        self.editor_combo_key3.setEditable(True)
        completer = QtWidgets.QCompleter([""] + COMMON_KEYS)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        completer.setFilterMode(QtCore.Qt.MatchContains)
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.editor_combo_key3.setCompleter(completer)
        combo_form2.addRow("Phím 1", self.editor_combo_key1)
        combo_form2.addRow("Phím 2", self.editor_combo_key2)
        combo_form2.addRow("Phím 3", self.editor_combo_key3)
        self.editor_stack.addWidget(self.editor_page_combo)
        
        self.editor_page_click = self._make_editor_page()
        click_form2 = QtWidgets.QFormLayout(self.editor_page_click)
        self.editor_x_input = QtWidgets.QLineEdit()
        self.editor_y_input = QtWidgets.QLineEdit()
        self.editor_button_input = QtWidgets.QComboBox()
        self.editor_button_input.addItems(["left", "right", "middle"])
        click_form2.addRow("X", self.editor_x_input)
        click_form2.addRow("Y", self.editor_y_input)
        click_form2.addRow("Nút", self.editor_button_input)
        self.editor_stack.addWidget(self.editor_page_click)
        
        self.editor_page_move = self._make_editor_page()
        move_layout2 = QtWidgets.QVBoxLayout(self.editor_page_move)
        move_info = QtWidgets.QLabel("Mỗi dòng 1 điểm: t(ms),x,y")
        move_info.setObjectName("MutedLabel")
        self.editor_points_input = QtWidgets.QPlainTextEdit()
        move_layout2.addWidget(move_info)
        move_layout2.addWidget(self.editor_points_input)
        self.editor_stack.addWidget(self.editor_page_move)
        
        self.editor_page_empty = self._make_editor_page()
        self.editor_stack.addWidget(self.editor_page_empty)

        self.editor_page_wait = self._make_editor_page()
        wait_form2 = QtWidgets.QFormLayout(self.editor_page_wait)
        self.editor_duration_input = QtWidgets.QLineEdit()
        wait_form2.addRow("Chờ (ms)", self.editor_duration_input)
        self.editor_stack.addWidget(self.editor_page_wait)
        
        editor_buttons = QtWidgets.QGridLayout()
        editor_buttons.setSpacing(8)
        self.apply_edit_button = QtWidgets.QPushButton("Áp dụng")
        self.apply_edit_button.setProperty("variant", "primary")
        self.apply_edit_button.clicked.connect(self._apply_selected_action_edits)
        
        self.duplicate_action_button = QtWidgets.QPushButton("Nhân bản")
        self.duplicate_action_button.setProperty("variant", "secondary")
        self.duplicate_action_button.clicked.connect(self._duplicate_selected_action)
        
        self.insert_action_button = QtWidgets.QPushButton("Chèn dưới")
        self.insert_action_button.setProperty("variant", "secondary")
        self.insert_action_button.clicked.connect(self._insert_action_below_selected)
        
        self.reload_action_button = QtWidgets.QPushButton("Hủy đổi")
        self.reload_action_button.setProperty("variant", "ghost")
        self.reload_action_button.clicked.connect(lambda: self._load_selected_action_into_editor(self.action_list.currentRow()))
        
        editor_buttons.addWidget(self.apply_edit_button, 0, 0)
        editor_buttons.addWidget(self.duplicate_action_button, 0, 1)
        editor_buttons.addWidget(self.insert_action_button, 1, 0)
        editor_buttons.addWidget(self.reload_action_button, 1, 1)
        edit_layout.addLayout(editor_buttons)
        
        self.inspector_stack.addWidget(edit_scroll)
        self.body_splitter.addWidget(right_panel)
        
        # Set splitter ratios
        self.body_splitter.setStretchFactor(0, 1)
        self.body_splitter.setStretchFactor(1, 3)
        self.body_splitter.setStretchFactor(2, 1)
        self.body_splitter.setSizes([260, 500, 300])

    def _handle_timeline_selection(self, current_row: int) -> None:
        self._load_selected_action_into_editor(current_row)
        if current_row >= 0:
            self.inspector_stack.setCurrentIndex(1)
        else:
            self.inspector_stack.setCurrentIndex(0)

    def _apply_styles(self) -> None:
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)
        
        scale = getattr(self, '_last_scale_factor', 1.0)
        
        def spx(val: int) -> int:
            return max(1, int(val * scale))

        font_11 = spx(11)
        font_12 = spx(12)
        font_13 = spx(13)
        font_14 = spx(14)
        font_16 = spx(16)
        font_20 = spx(20)

        # UI/UX Pro Max Palette (Slate/Indigo inspired)
        c_bg = "#F8FAFC" # slate-50
        c_surface = "#FFFFFF"
        c_panel = "#FFFFFF"
        c_stroke = "#E2E8F0" # slate-200
        c_text = "#0F172A" # slate-900
        c_muted = "#64748B" # slate-500
        c_primary = "#4F46E5" # indigo-600
        c_primary_hover = "#4338CA" # indigo-700
        c_danger = "#EF4444" # red-500
        c_danger_hover = "#DC2626" # red-600

        self.setStyleSheet(
            f'''
            QMainWindow {{
                background: {c_bg};
            }}
            QWidget#AppRoot {{
                background: {c_bg};
            }}
            QWidget#TopHeader {{
                background: {c_surface};
                border-bottom: 1px solid {c_stroke};
            }}
            QFrame[card="true"], QFrame[cardAlt="true"] {{
                background: {c_panel};
                border: 1px solid {c_stroke};
                border-radius: 12px;
            }}
            #HeroTitle {{
                color: {c_text};
                font-size: {font_20}px;
                font-weight: 800;
            }}
            #StatusLabel {{
                color: {c_muted};
                font-size: {font_12}px;
                font-weight: 500;
            }}
            #SectionTitle, #SectionTitleAlt {{
                color: {c_text};
                font-size: {font_16}px;
                font-weight: 700;
            }}
            #MutedLabel, #EmptyLabel {{
                color: {c_muted};
                font-size: {font_13}px;
                font-weight: 500;
            }}
            #StatValue {{
                color: {c_primary};
                font-size: {font_20}px;
                font-weight: 800;
            }}
            
            QLabel {{
                color: {c_text};
            }}
            
            /* Scroll Area */
            QScrollArea, QScrollArea > QWidget > QWidget {{
                background: transparent;
            }}
            
            /* Tabs */
            QTabWidget::pane {{
                border: 1px solid {c_stroke};
                background: {c_surface};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {c_muted};
                padding: 10px 16px;
                border-bottom: 2px solid transparent;
                font-size: {font_13}px;
                font-weight: 600;
            }}
            QTabBar::tab:selected {{
                color: {c_primary};
                border-bottom: 2px solid {c_primary};
            }}
            QTabBar::tab:hover:!selected {{
                color: {c_text};
            }}
            
            /* List Widgets */
            QListWidget#TimelineList, QListWidget#CodeList {{
                background: {c_bg};
                color: {c_text};
                border: 1px solid {c_stroke};
                border-radius: 8px;
                padding: 6px;
                outline: none;
                font-size: {font_13}px;
                font-weight: 500;
            }}
            QListWidget#TimelineList::item, QListWidget#CodeList::item {{
                padding: 10px 12px;
                border-radius: 6px;
                margin: 2px 2px;
            }}
            QListWidget#TimelineList::item:selected, QListWidget#CodeList::item:selected {{
                background: {c_primary};
                color: #FFFFFF;
            }}
            QListWidget#TimelineList::item:hover:!selected, QListWidget#CodeList::item:hover:!selected {{
                background: {c_stroke};
            }}
            
            /* Buttons */
            QPushButton {{
                min-height: 38px;
                border-radius: 8px;
                border: none;
                padding: 0 16px;
                font-size: {font_13}px;
                font-weight: 600;
            }}
            QPushButton[variant="primary"] {{
                background: {c_primary};
                color: #FFFFFF;
            }}
            QPushButton[variant="primary"]:hover {{
                background: {c_primary_hover};
            }}
            QPushButton[variant="danger"] {{
                background: {c_danger};
                color: #FFFFFF;
            }}
            QPushButton[variant="danger"]:hover {{
                background: {c_danger_hover};
            }}
            QPushButton[variant="secondary"] {{
                background: {c_surface};
                color: {c_text};
                border: 1px solid {c_stroke};
            }}
            QPushButton[variant="secondary"]:hover {{
                background: {c_bg};
                border-color: {c_muted};
            }}
            QPushButton[variant="ghost"] {{
                background: transparent;
                color: {c_text};
            }}
            QPushButton[variant="ghost"]:hover {{
                background: {c_stroke};
            }}
            QPushButton[variant="tool"] {{
                background: {c_surface};
                color: {c_text};
                border: 1px solid {c_stroke};
                text-align: left;
                padding-left: 16px;
                min-height: 44px;
            }}
            QPushButton[variant="tool"]:hover {{
                border-color: {c_primary};
                color: {c_primary};
                background: {c_bg};
            }}
            
            /* Inputs */
            QLineEdit, QComboBox, QPlainTextEdit {{
                background: {c_surface};
                color: {c_text};
                border: 1px solid {c_stroke};
                border-radius: 6px;
                min-height: 36px;
                padding: 0 10px;
                font-size: {font_13}px;
                font-weight: 500;
            }}
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{
                border: 2px solid {c_primary};
            }}
            QPlainTextEdit {{
                padding: 10px;
            }}
            QFormLayout QLabel {{
                color: {c_text};
                font-size: {font_13}px;
                font-weight: 500;
            }}
            
            QComboBox QAbstractItemView {{
                background-color: {c_surface};
                color: {c_text};
                selection-background-color: {c_primary};
                selection-color: #FFFFFF;
                outline: none;
            }}
            '''
        )

    def _create_card(self, alt: bool = False) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        if alt:
            frame.setProperty("cardAlt", "true")
        else:
            frame.setProperty("card", "true")
        effect = QtWidgets.QGraphicsDropShadowEffect(frame)
        effect.setBlurRadius(34)
        effect.setOffset(0, 14)
        effect.setColor(QtGui.QColor(0, 0, 0, 55))
        frame.setGraphicsEffect(effect)
        return frame

    def _create_stat_card(self, title: str, value: str) -> tuple[QtWidgets.QFrame, QtWidgets.QLabel]:
        card = QtWidgets.QFrame()
        card.setProperty("cardAlt", "true")
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title_label = QtWidgets.QLabel(title)
        title_label.setProperty("statTitle", "true")
        value_label = QtWidgets.QLabel(value)
        value_label.setProperty("statValue", "true")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return card, value_label

    def _apply_window_effects(self) -> None:
        try:
            hwnd = int(self.winId())
            accent = ACCENT_POLICY()
            accent.AccentState = 3
            accent.AccentFlags = 2
            accent.GradientColor = 0xFF101C2D
            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = 19
            data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
            data.SizeOfData = ctypes.sizeof(accent)
            ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        except Exception:
            pass

    def _snapshot_actions(self) -> list[MacroAction]:
        with self.actions_lock:
            return [
                MacroAction(
                    action_type=action.action_type,
                    key=action.key,
                    keys=list(action.keys),
                    x=action.x,
                    y=action.y,
                    button=action.button,
                    duration_ms=action.duration_ms,
                    post_delay_ms=action.post_delay_ms,
                    points=[dict(point) for point in action.points],
                )
                for action in self.actions
            ]

    def _refresh_action_list(self) -> None:
        current_row = self.action_list.currentRow()
        self.action_list.clear()
        actions = self._snapshot_actions()
        for index, action in enumerate(actions, start=1):
            self.action_list.addItem(f"{index:02d}. {action.describe()}")
        if actions and 0 <= current_row < len(actions):
            self.action_list.setCurrentRow(current_row)
        self.steps_value.setText(str(len(actions)))
        self.mode_value.setText(self.record_mode_text)
        self._update_editor_button_state()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _read_int(self, value: str, field_name: str, minimum: int = 0) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} phải là số nguyên.") from exc
        if parsed < minimum:
            raise ValueError(f"{field_name} phải lớn hơn hoặc bằng {minimum}.")
        return parsed

    def _default_delay(self) -> int:
        return self._read_int(self.default_delay_input.text(), "Delay mặc định", 0)

    def _add_action_and_select(self, action: MacroAction) -> None:
        with self.actions_lock:
            self.actions.append(action)
            index = len(self.actions) - 1
        self.refresh_actions_requested.emit()
        self.action_list.setCurrentRow(index)
        self._save_actions(silent=True)
        self.status_changed.emit(f"Đã thêm: {action.describe()}")

    def _add_key_action(self) -> None:
        self._add_action_and_select(MacroAction(action_type="key_tap", key="a", post_delay_ms=50))

    def _add_combo_action(self) -> None:
        self._add_action_and_select(MacroAction(action_type="combo_press", keys=["ctrl_l", "c"], post_delay_ms=50))

    def _add_mouse_action(self) -> None:
        self._add_action_and_select(MacroAction(action_type="mouse_click", x=0, y=0, button="left", post_delay_ms=50))

    def _add_wait_action(self) -> None:
        self._add_action_and_select(MacroAction(action_type="wait", duration_ms=1000))

    def _add_clipboard_code_action(self) -> None:
        self._add_action_and_select(MacroAction(action_type="set_clipboard_code", post_delay_ms=50))

    def _add_type_code_action(self) -> None:
        self._add_action_and_select(MacroAction(action_type="type_code", post_delay_ms=50))

    def _fetch_codes(self) -> None:
        self.code_status_label.setText("Đang tải code từ web...")
        self.code_manager.fetch_from_api()

    def _load_codes_from_json(self) -> None:
        self.code_status_label.setText("Đang đọc codes.json...")
        self.code_manager.load_from_json()

    def _on_codes_loaded(self, codes: list) -> None:
        range_text = self.code_range_input.text().strip()
        filtered = self.code_manager.get_filtered(range_text)

        self.code_list_widget.clear()
        for code in filtered:
            self.code_list_widget.addItem(code.preview(40))

        self.code_status_label.setText(
            f"Đã tải {len(codes)} code tổng | Hiển thị {len(filtered)} code"
        )
        self.status_changed.emit(f"Code Manager: Đã tải {len(codes)} code từ yumifang3.site.")

    def _remove_selected(self) -> None:
        row = self.action_list.currentRow()
        if row < 0:
            return
        with self.actions_lock:
            if row >= len(self.actions):
                return
            removed = self.actions.pop(row)
        self.refresh_actions_requested.emit()
        self._save_actions(silent=True)
        self.status_changed.emit(f"Đã xóa bước: {removed.describe()}")
        self._load_selected_action_into_editor(self.action_list.currentRow())

    def _clear_actions(self) -> None:
        with self.actions_lock:
            if not self.actions:
                return
            self.actions.clear()
        self.refresh_actions_requested.emit()
        self._save_actions(silent=True)
        self.status_changed.emit("Đã xóa toàn bộ macro.")
        self._clear_editor()

    def _move_selected(self, direction: int) -> None:
        row = self.action_list.currentRow()
        if row < 0:
            return
        with self.actions_lock:
            target = row + direction
            if target < 0 or target >= len(self.actions):
                return
            self.actions[row], self.actions[target] = self.actions[target], self.actions[row]
        self.refresh_actions_requested.emit()
        self.action_list.setCurrentRow(target)
        self._save_actions(silent=True)

    def _save_actions(self, silent: bool = False) -> None:
        try:
            with self.actions_lock:
                payload = [asdict(action) for action in self.actions]
            CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            if not silent:
                QtWidgets.QMessageBox.critical(self, "Lỗi lưu file", str(exc))
            return
        if not silent:
            self.status_changed.emit(f"Đã lưu macro vào {CONFIG_PATH.name}.")

    def _load_actions(self) -> None:
        if not CONFIG_PATH.exists():
            self.refresh_actions_requested.emit()
            return

        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            actions = [MacroAction(**item) for item in raw]
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            QtWidgets.QMessageBox.critical(self, "Lỗi nạp file", str(exc))
            return
        with self.actions_lock:
            self.actions = actions
        self.refresh_actions_requested.emit()
        self.status_changed.emit(f"Đã nạp {len(actions)} bước từ {CONFIG_PATH.name}.")
        if actions:
            self.action_list.setCurrentRow(0)
        else:
            self._clear_editor()

    def _capture_mouse_position(self) -> None:
        self.hide()
        self.status_changed.emit("Di chuột đến vị trí cần lấy. App sẽ đọc tọa độ sau 2 giây.")

        def capture() -> None:
            time.sleep(2)
            x, y = self.mouse_controller.position
            self.position_captured.emit(int(x), int(y))

        threading.Thread(target=capture, daemon=True).start()

    @QtCore.Slot(int, int)
    def _apply_captured_position(self, x: int, y: int) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if hasattr(self, 'editor_x_input'):
            self.editor_x_input.setText(str(x))
        if hasattr(self, 'editor_y_input'):
            self.editor_y_input.setText(str(y))
        self.status_changed.emit(f"Đã lấy tọa độ chuột: ({x}, {y}).")

    def _toggle_recording(self, replace_existing: bool) -> None:
        if self.is_recording:
            self._stop_recording()
            return
        self._start_recording(replace_existing)

    def _start_recording(self, replace_existing: bool) -> None:
        if self.is_running:
            QtWidgets.QMessageBox.warning(self, "Đang chạy", "Hãy stop macro trước khi record.")
            return

        try:
            wait_seconds = self._read_int(self.record_after_input.text(), "Thời gian chờ record", 0)
            default_delay = self._default_delay()
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Sai dữ liệu", str(exc))
            return

        self.is_recording = True
        self.record_replace_mode = replace_existing
        self.record_mode_text = "Thay thế" if replace_existing else "Thêm vào"
        self._reset_record_state()
        self.refresh_actions_requested.emit()

        mode_text = "thay thế" if replace_existing else "nối thêm"
        self.status_changed.emit(
            f"Sẽ bắt đầu record {mode_text} sau {wait_seconds}s. Nhấn F8 hoặc Dừng record để stop."
        )
        self.hide()

        def on_press(key_pressed) -> None:
            # Cập nhật trạng thái modifier keys
            modifier_name = self._get_modifier_key_name(key_pressed)
            if modifier_name:
                self.record_active_modifiers.add(modifier_name)
            
            # Lấy tên phím bình thường
            key_name = self._normalize_recorded_key(key_pressed)
            if key_name:
                # Nếu có modifier keys đang giữ và key này không phải modifier, ghi combo_press
                if self.record_active_modifiers and not modifier_name:
                    combo_keys = sorted(list(self.record_active_modifiers)) + [key_name]
                    self._record_discrete_action(
                        MacroAction(action_type="combo_press", keys=combo_keys, post_delay_ms=default_delay)
                    )
                    self.record_combo_down_keys.add(key_name)
                elif not modifier_name:
                    # Chỉ ghi key_down nếu không phải modifier key
                    self._record_discrete_action(
                        MacroAction(action_type="key_down", key=key_name, post_delay_ms=default_delay)
                    )

        def on_release(key_released) -> None:
            # Cập nhật trạng thái modifier keys
            modifier_name = self._get_modifier_key_name(key_released)
            if modifier_name:
                self.record_active_modifiers.discard(modifier_name)
            
            # Lấy tên phím bình thường
            key_name = self._normalize_recorded_key(key_released)
            if key_name and not modifier_name:
                # Nếu phím này là phần của combo_press vừa ghi, bỏ qua key_up riêng lẻ
                if key_name in self.record_combo_down_keys:
                    self.record_combo_down_keys.discard(key_name)
                else:
                    self._record_discrete_action(
                        MacroAction(action_type="key_up", key=key_name, post_delay_ms=default_delay)
                    )

        def on_move(x, y) -> None:
            self._record_mouse_move(int(x), int(y), default_delay)

        def on_click(x, y, button_clicked, pressed) -> None:
            if not pressed:
                return
            button_name = str(button_clicked).split(".")[-1]
            self._record_discrete_action(
                MacroAction(
                    action_type="mouse_click",
                    x=int(x),
                    y=int(y),
                    button=button_name,
                    post_delay_ms=default_delay,
                )
            )

        def delayed_start() -> None:
            time.sleep(wait_seconds)
            if not self.is_recording:
                return
            if self.record_replace_mode:
                with self.actions_lock:
                    self.actions.clear()
                self.refresh_actions_requested.emit()
            self.record_last_event_time = time.perf_counter()
            self.record_keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self.record_mouse_listener = mouse.Listener(on_move=on_move, on_click=on_click)
            self.record_keyboard_listener.start()
            self.record_mouse_listener.start()
            self.status_changed.emit(
                "Đang record thông minh. App ghi giữ/nhả phím, click và cả quỹ đạo di chuột."
            )

        self.record_start_timer = threading.Thread(target=delayed_start, daemon=True)
        self.record_start_timer.start()

    def _stop_recording(self) -> None:
        if not self.is_recording:
            return
        self.is_recording = False
        self._finalize_pending_move()

        if self.record_keyboard_listener is not None:
            self.record_keyboard_listener.stop()
            self.record_keyboard_listener = None
        if self.record_mouse_listener is not None:
            self.record_mouse_listener.stop()
            self.record_mouse_listener = None

        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._save_actions(silent=True)
        self.status_changed.emit(f"Đã dừng record. Hiện có {len(self._snapshot_actions())} bước.")
        self._reset_record_state()

    def _reset_record_state(self) -> None:
        self.record_last_event_time = None
        self.record_last_action_index = None
        self.record_current_move_index = None
        self.record_current_move_start = None
        self.record_current_move_last_sample = None
        self.record_current_move_last_position = None
        self.record_active_modifiers.clear()
        self.record_combo_down_keys.clear()

    def _record_discrete_action(self, action: MacroAction) -> None:
        if not self.is_recording:
            return
        now = time.perf_counter()
        with self.actions_lock:
            self._finalize_pending_move_locked()
            self._close_gap_before_new_action_locked(now)
            self.actions.append(action)
            self.record_last_action_index = len(self.actions) - 1
        self.record_last_event_time = now
        self.refresh_actions_requested.emit()

    def _record_mouse_move(self, x: int, y: int, fallback_delay_ms: int) -> None:
        if not self.is_recording:
            return

        now = time.perf_counter()
        current_position = (x, y)

        with self.actions_lock:
            if self.record_current_move_index is None:
                self._close_gap_before_new_action_locked(now)
                action = MacroAction(
                    action_type="mouse_move",
                    post_delay_ms=fallback_delay_ms,
                    points=[{"t": 0, "x": x, "y": y}],
                )
                self.actions.append(action)
                self.record_current_move_index = len(self.actions) - 1
                self.record_current_move_start = now
                self.record_current_move_last_sample = now
                self.record_current_move_last_position = current_position
                self.record_last_action_index = self.record_current_move_index
                self.record_last_event_time = now
                self.refresh_actions_requested.emit()
                return

            if self.record_current_move_last_position is not None:
                last_x, last_y = self.record_current_move_last_position
                if abs(last_x - x) < MOVE_MIN_DISTANCE and abs(last_y - y) < MOVE_MIN_DISTANCE:
                    return

            if self.record_current_move_last_sample is not None:
                elapsed_ms = int(round((now - self.record_current_move_last_sample) * 1000))
                if elapsed_ms < MOVE_SAMPLE_MS:
                    return

            offset_ms = int(round((now - (self.record_current_move_start or now)) * 1000))
            self.actions[self.record_current_move_index].points.append({"t": offset_ms, "x": x, "y": y})
            self.record_current_move_last_sample = now
            self.record_current_move_last_position = current_position
            self.record_last_event_time = now
        self.refresh_actions_requested.emit()

    def _close_gap_before_new_action_locked(self, now: float) -> None:
        if self.record_last_action_index is None or self.record_last_event_time is None:
            return
        elapsed_ms = max(0, int(round((now - self.record_last_event_time) * 1000)))
        if 0 <= self.record_last_action_index < len(self.actions):
            self.actions[self.record_last_action_index].post_delay_ms = elapsed_ms

    def _finalize_pending_move(self) -> None:
        with self.actions_lock:
            self._finalize_pending_move_locked()

    def _finalize_pending_move_locked(self) -> None:
        if self.record_current_move_index is None:
            return
        if not (0 <= self.record_current_move_index < len(self.actions)):
            self.record_current_move_index = None
            return
        move_action = self.actions[self.record_current_move_index]
        if len(move_action.points) <= 1:
            point = move_action.points[0]
            move_action.points.append({"t": 1, "x": point["x"], "y": point["y"]})
        self.record_current_move_index = None
        self.record_current_move_start = None
        self.record_current_move_last_sample = None
        self.record_current_move_last_position = None

    def _start_macro(self) -> None:
        if self.is_recording:
            self._stop_recording()
        if self.is_running:
            return

        actions = self._snapshot_actions()
        if not actions:
            QtWidgets.QMessageBox.warning(self, "Chưa có macro", "Bạn cần thêm ít nhất một bước.")
            return

        # Nếu macro có bước liên quan đến code, setup queue
        has_code_action = any(a.action_type in ("set_clipboard_code", "type_code") for a in actions)
        if has_code_action:
            range_text = self.code_range_input.text().strip()
            queue_size = self.code_manager.setup_queue(range_text)
            if queue_size == 0:
                QtWidgets.QMessageBox.warning(
                    self, "Chưa có code",
                    "Macro có bước 'Nạp code' hoặc 'Gõ code' nhưng chưa tải code.\nHãy tải code từ web hoặc file trước."
                )
                return

        self.stop_event.clear()
        self.is_running = True
        self.loop_changed.emit("0")
        self.hide()
        if has_code_action:
            current, total = self.code_manager.get_progress()
            self.status_changed.emit(
                f"Macro đang chạy với {total} code. Nhấn F8 hoặc đưa chuột lên góc trái để dừng."
            )
        else:
            self.status_changed.emit(
                "Macro đang chạy vô hạn. Nhấn F8, Stop hoặc đưa chuột lên góc trên trái để dừng."
            )
        self.runner_thread = threading.Thread(target=self._run_macro_loop, daemon=True)
        self.runner_thread.start()

    def _stop_macro(self) -> None:
        self.stop_event.set()
        self.is_running = False
        self.status_changed.emit("Đã gửi lệnh dừng macro.")

    def _run_macro_loop(self) -> None:
        completed_loops = 0
        try:
            while not self.stop_event.is_set():
                actions = self._snapshot_actions()
                for action in actions:
                    if self.stop_event.is_set():
                        break
                    if self._failsafe_triggered():
                        self.stop_event.set()
                        self.status_changed.emit("Đã dừng do failsafe: chuột chạm góc trên trái màn hình.")
                        break
                    self._execute_action(action)
                else:
                    completed_loops += 1
                    self.loop_changed.emit(str(completed_loops))
                    continue
                break
        finally:
            self.is_running = False
            self._save_actions(silent=True)
            self.showNormal()
            self.raise_()
            self.activateWindow()
            self.status_changed.emit("Macro đã dừng." if self.stop_event.is_set() else "Macro đã kết thúc.")

    def _execute_action(self, action: MacroAction) -> None:
        if action.action_type == "key_tap":
            key_obj = self._parse_key(action.key)
            self.keyboard_controller.press(key_obj)
            time.sleep(0.03)  # 30ms hold cho emulator nhận diện
            self.keyboard_controller.release(key_obj)
            self._sleep_with_stop(action.post_delay_ms / 1000)
            return

        if action.action_type == "key_down":
            self.keyboard_controller.press(self._parse_key(action.key))
            self._sleep_with_stop(action.post_delay_ms / 1000)
            return

        if action.action_type == "key_up":
            self.keyboard_controller.release(self._parse_key(action.key))
            self._sleep_with_stop(action.post_delay_ms / 1000)
            return

        if action.action_type == "mouse_click":
            self.mouse_controller.position = (action.x, action.y)
            self.mouse_controller.click(self._parse_button(action.button), 1)
            self._sleep_with_stop(action.post_delay_ms / 1000)
            return

        if action.action_type == "combo_press":
            combo_keys = action.keys or ([action.key] if action.key else [])
            parsed_keys = [self._parse_key(key_name) for key_name in combo_keys]
            for key_obj in parsed_keys:
                self.keyboard_controller.press(key_obj)
                time.sleep(0.04)  # 40ms giữa các phím (ví dụ ctrl -> 40ms -> v)
            
            time.sleep(0.03)  # Giữ toàn bộ combo trong 30ms
            
            for key_obj in reversed(parsed_keys):
                self.keyboard_controller.release(key_obj)
                time.sleep(0.02)  # 20ms release
            self._sleep_with_stop(action.post_delay_ms / 1000)
            return

        if action.action_type == "mouse_move":
            self._play_mouse_path(action)
            self._sleep_with_stop(action.post_delay_ms / 1000)
            return

        if action.action_type == "wait":
            self._sleep_with_stop(action.duration_ms / 1000)
            return

        if action.action_type == "set_clipboard_code":
            code_text = self.code_manager.next_code()
            if code_text is None:
                self.stop_event.set()
                current, total = self.code_manager.get_progress()
                self.status_changed.emit(f"Đã nhập xong {total} code.")
                return
            
            # Gửi tín hiệu sang luồng chính để copy
            self.clipboard_set_requested.emit(code_text)
            # Chờ một lúc để luồng chính có thời gian xử lý và giả lập kịp nhận diện thay đổi clipboard
            time.sleep(0.5)
            
            code_id = self.code_manager.get_current_code_id()
            current, total = self.code_manager.get_progress()
            self.status_changed.emit(f"📋 Code #{code_id} ({current}/{total}) → clipboard")
            self._sleep_with_stop(action.post_delay_ms / 1000)
            return

        if action.action_type == "type_code":
            code_text = self.code_manager.next_code()
            if code_text is None:
                self.stop_event.set()
                current, total = self.code_manager.get_progress()
                self.status_changed.emit(f"Đã gõ xong {total} code.")
                return
            
            # Gõ trực tiếp từng ký tự
            for char in code_text:
                self.keyboard_controller.type(char)
                time.sleep(0.02)  # Delay nhỏ giữa các phím để giả lập nhận diện
            
            code_id = self.code_manager.get_current_code_id()
            current, total = self.code_manager.get_progress()
            self.status_changed.emit(f"✍️ Đã gõ Code #{code_id} ({current}/{total})")
            self._sleep_with_stop(action.post_delay_ms / 1000)
            return

    def _play_mouse_path(self, action: MacroAction) -> None:
        if not action.points:
            return
        previous_t = 0
        for point in action.points:
            if self.stop_event.is_set() or self._failsafe_triggered():
                self.stop_event.set()
                return
            target_t = point.get("t", previous_t)
            wait_ms = max(0, target_t - previous_t)
            if wait_ms:
                self._sleep_with_stop(wait_ms / 1000)
            self.mouse_controller.position = (point.get("x", 0), point.get("y", 0))
            previous_t = target_t

    def _sleep_with_stop(self, seconds: float) -> None:
        end_time = time.perf_counter() + seconds
        while time.perf_counter() < end_time:
            if self.stop_event.is_set() or self._failsafe_triggered():
                self.stop_event.set()
                return
            time.sleep(0.01)

    def _failsafe_triggered(self) -> bool:
        x, y = self.mouse_controller.position
        return x <= FAILSAFE_X and y <= FAILSAFE_Y

    def _parse_key(self, key_name: str):
        if len(key_name) == 1:
            return key_name

        key_aliases = {
            "enter": keyboard.Key.enter,
            "space": keyboard.Key.space,
            "tab": keyboard.Key.tab,
            "esc": keyboard.Key.esc,
            "escape": keyboard.Key.esc,
            "shift": keyboard.Key.shift,
            "shift_l": keyboard.Key.shift_l,
            "shift_r": keyboard.Key.shift_r,
            "ctrl": keyboard.Key.ctrl,
            "ctrl_l": keyboard.Key.ctrl_l,
            "ctrl_r": keyboard.Key.ctrl_r,
            "alt": keyboard.Key.alt,
            "alt_l": keyboard.Key.alt_l,
            "alt_r": keyboard.Key.alt_r,
            "cmd": keyboard.Key.cmd,
            "cmd_l": keyboard.Key.cmd_l,
            "cmd_r": keyboard.Key.cmd_r,
            "backspace": keyboard.Key.backspace,
            "delete": keyboard.Key.delete,
            "home": keyboard.Key.home,
            "end": keyboard.Key.end,
            "page_up": keyboard.Key.page_up,
            "page_down": keyboard.Key.page_down,
            "up": keyboard.Key.up,
            "down": keyboard.Key.down,
            "left": keyboard.Key.left,
            "right": keyboard.Key.right,
            "caps_lock": keyboard.Key.caps_lock,
            "insert": keyboard.Key.insert,
        }
        if key_name in key_aliases:
            return key_aliases[key_name]
        if key_name.startswith("f") and key_name[1:].isdigit():
            return getattr(keyboard.Key, key_name, key_name)
        return key_name

    def _parse_button(self, button_name: str) -> mouse.Button:
        button_map = {
            "left": mouse.Button.left,
            "right": mouse.Button.right,
            "middle": mouse.Button.middle,
        }
        return button_map.get(button_name, mouse.Button.left)

    def _get_modifier_key_name(self, recorded_key) -> Optional[str]:
        """Kiểm tra xem phím có phải modifier key không, trả về tên modifier nếu đúng."""
        modifier_names = {
            "shift_l", "shift_r",
            "ctrl_l", "ctrl_r",
            "alt_l", "alt_r",
            "cmd", "cmd_l", "cmd_r",
        }
        text = str(recorded_key)
        if text.startswith("Key."):
            key_name = text.split(".", 1)[1].lower()
            if key_name in modifier_names:
                return key_name
        return None

    def _normalize_recorded_key(self, recorded_key) -> Optional[str]:
        """Chuyển đổi phím ghi được thành tên phím chuẩn, xử lý cả control characters."""
        # Map control characters thành tổ hợp phím
        control_char_map = {
            "\x01": "a",      # Ctrl+A
            "\x03": "c",      # Ctrl+C
            "\x06": "f",      # Ctrl+F
            "\x16": "v",      # Ctrl+V (SYN character)
            "\x18": "x",      # Ctrl+X
            "\x19": "y",      # Ctrl+Y
            "\x1a": "z",      # Ctrl+Z
        }
        
        if hasattr(recorded_key, "char") and recorded_key.char:
            char = recorded_key.char
            # Kiểm tra xem có phải control character không
            if char in control_char_map:
                return control_char_map[char]
            # Kiểm tra xem có phải regular character không
            if ord(char) >= 32:  # Printable characters
                return char.lower()
            if char == "\x08":  # Backspace
                return "backspace"
            return None
        
        text = str(recorded_key)
        if text.startswith("Key."):
            key_name = text.split(".", 1)[1].lower()
            if key_name == "f8":
                return None
            return key_name
        return None

    def _start_hotkey_listener(self) -> None:
        def stop_all() -> None:
            self.stop_recording_requested.emit()
            self.stop_macro_requested.emit()

        self.hotkey_listener = keyboard.GlobalHotKeys({"<f8>": stop_all})
        self.hotkey_listener.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._stop_recording()
        self._stop_macro()
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
        super().closeEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        if self._resizing_guard:
            super().resizeEvent(event)
            return

        new_size = event.size()
        expected_height = int(round(new_size.width() / self._aspect_ratio))
        if abs(new_size.height() - expected_height) > 2:
            self._resizing_guard = True
            target_width = max(self.minimumWidth(), new_size.width())
            target_height = max(self.minimumHeight(), int(round(target_width / self._aspect_ratio)))
            self.resize(target_width, target_height)
            self._resizing_guard = False

        super().resizeEvent(event)

    def _make_editor_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        return page

    def _update_editor_stack_visibility(self, action_type: str) -> None:
        page_map = {
            "key_tap": self.editor_page_key,
            "key_down": self.editor_page_key,
            "key_up": self.editor_page_key,
            "combo_press": self.editor_page_combo,
            "mouse_click": self.editor_page_click,
            "mouse_move": self.editor_page_move,
            "wait": self.editor_page_wait,
            "set_clipboard_code": self.editor_page_empty,
            "type_code": self.editor_page_empty,
        }
        self.editor_stack.setCurrentWidget(page_map.get(action_type, self.editor_page_key))

    def _load_selected_action_into_editor(self, row: int) -> None:
        actions = self._snapshot_actions()
        if row < 0 or row >= len(actions):
            self._clear_editor()
            return

        action = actions[row]
        self._updating_editor = True
        self.editor_action_type.setCurrentText(action.action_type)
        self.editor_post_delay.setText(str(action.post_delay_ms))
        self.editor_key_input.setCurrentText(action.key)
        self.editor_combo_key1.setCurrentText(action.keys[0] if len(action.keys) > 0 else "")
        self.editor_combo_key2.setCurrentText(action.keys[1] if len(action.keys) > 1 else "")
        self.editor_combo_key3.setCurrentText(action.keys[2] if len(action.keys) > 2 else "")
        self.editor_x_input.setText(str(action.x))
        self.editor_y_input.setText(str(action.y))
        self.editor_button_input.setCurrentText(action.button or "left")
        self.editor_duration_input.setText(str(action.duration_ms))
        self.editor_points_input.setPlainText(
            "\n".join(f"{point.get('t', 0)},{point.get('x', 0)},{point.get('y', 0)}" for point in action.points)
        )
        self._update_editor_stack_visibility(action.action_type)
        self._updating_editor = False
        self._update_editor_button_state()

    def _clear_editor(self) -> None:
        self._updating_editor = True
        self.editor_action_type.setCurrentText("key_tap")
        self.editor_post_delay.setText(str(DEFAULT_DELAY_MS))
        self.editor_key_input.setCurrentText("")
        self.editor_combo_key1.setCurrentText("")
        self.editor_combo_key2.setCurrentText("")
        self.editor_combo_key3.setCurrentText("")
        self.editor_x_input.clear()
        self.editor_y_input.clear()
        self.editor_button_input.setCurrentText("left")
        self.editor_duration_input.clear()
        self.editor_points_input.clear()
        self._updating_editor = False
        self._update_editor_stack_visibility("key_tap")
        self._update_editor_button_state()

    def _update_editor_button_state(self) -> None:
        has_selection = self.action_list.currentRow() >= 0
        for button in [
            self.apply_edit_button,
            self.duplicate_action_button,
            self.insert_action_button,
            self.reload_action_button,
        ]:
            button.setEnabled(has_selection)

    def _build_action_from_editor(self) -> MacroAction:
        action_type = self.editor_action_type.currentText()
        post_delay_ms = self._read_int(self.editor_post_delay.text(), "Delay sau bước", 0)
        action = MacroAction(action_type=action_type, post_delay_ms=post_delay_ms)

        if action_type in {"key_tap", "key_down", "key_up"}:
            key_name = self.editor_key_input.currentText().strip().lower()
            if not key_name:
                raise ValueError("Bạn cần nhập key.")
            action.key = key_name
            return action

        if action_type == "combo_press":
            raw_keys = [
                self.editor_combo_key1.currentText().strip().lower(),
                self.editor_combo_key2.currentText().strip().lower(),
                self.editor_combo_key3.currentText().strip().lower()
            ]
            keys = [item for item in raw_keys if item]
            if not keys:
                raise ValueError("Bạn cần nhập ít nhất một key cho tổ hợp.")
            action.keys = keys
            return action

        if action_type == "mouse_click":
            action.x = self._read_int(self.editor_x_input.text(), "Tọa độ X")
            action.y = self._read_int(self.editor_y_input.text(), "Tọa độ Y")
            action.button = self.editor_button_input.currentText().strip().lower() or "left"
            return action

        if action_type == "mouse_move":
            points = self._parse_points_text(self.editor_points_input.toPlainText())
            if len(points) < 2:
                raise ValueError("Mouse move cần ít nhất 2 điểm quỹ đạo.")
            action.points = points
            return action

        if action_type == "wait":
            action.duration_ms = self._read_int(self.editor_duration_input.text(), "Thời gian chờ", 1)
            return action

        if action_type in ("set_clipboard_code", "type_code"):
            return action

        raise ValueError("Loại action không được hỗ trợ.")

    def _parse_points_text(self, raw_text: str) -> list[dict[str, int]]:
        points: list[dict[str, int]] = []
        for line in raw_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            pieces = [part.strip() for part in stripped.split(",")]
            if len(pieces) != 3:
                raise ValueError("Mỗi dòng quỹ đạo phải có dạng t,x,y.")
            t_value, x_value, y_value = (int(piece) for piece in pieces)
            if t_value < 0:
                raise ValueError("Thời gian điểm quỹ đạo phải >= 0.")
            points.append({"t": t_value, "x": x_value, "y": y_value})
        if any(points[index]["t"] < points[index - 1]["t"] for index in range(1, len(points))):
            raise ValueError("Các mốc thời gian quỹ đạo phải tăng dần.")
        return points

    def _apply_selected_action_edits(self) -> None:
        row = self.action_list.currentRow()
        if row < 0:
            return
        try:
            updated = self._build_action_from_editor()
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Sai dữ liệu", str(exc))
            return

        with self.actions_lock:
            if row >= len(self.actions):
                return
            self.actions[row] = updated
        self.refresh_actions_requested.emit()
        self.action_list.setCurrentRow(row)
        self._save_actions(silent=True)
        self.status_changed.emit(f"Đã cập nhật bước {row + 1}.")

    def _duplicate_selected_action(self) -> None:
        row = self.action_list.currentRow()
        if row < 0:
            return
        with self.actions_lock:
            if row >= len(self.actions):
                return
            action = self.actions[row]
            clone = MacroAction(
                action_type=action.action_type,
                key=action.key,
                keys=list(action.keys),
                x=action.x,
                y=action.y,
                button=action.button,
                duration_ms=action.duration_ms,
                post_delay_ms=action.post_delay_ms,
                points=[dict(point) for point in action.points],
            )
            self.actions.insert(row + 1, clone)
        self.refresh_actions_requested.emit()
        self.action_list.setCurrentRow(row + 1)
        self._save_actions(silent=True)
        self.status_changed.emit(f"Đã nhân bản bước {row + 1}.")

    def _insert_action_below_selected(self) -> None:
        row = self.action_list.currentRow()
        if row < 0:
            return
        try:
            new_action = self._build_action_from_editor()
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Sai dữ liệu", str(exc))
            return
        with self.actions_lock:
            insert_at = min(row + 1, len(self.actions))
            self.actions.insert(insert_at, new_action)
        self.refresh_actions_requested.emit()
        self.action_list.setCurrentRow(row + 1)
        self._save_actions(silent=True)
        self.status_changed.emit(f"Đã chèn bước mới dưới vị trí {row + 1}.")


def main() -> None:
    app = QtWidgets.QApplication([])
    app.setApplicationName("Macro Studio")
    window = MacroStudio()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
