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


# Xác định vị trí lưu macro_steps.json
# Nếu chạy từ .exe (PyInstaller), lưu cùng thư mục với .exe
# Nếu chạy từ source code, lưu cùng thư mục với app.py
if getattr(sys, 'frozen', False):
    CONFIG_PATH = Path(sys.executable).parent / "macro_steps.json"
else:
    CONFIG_PATH = Path(__file__).with_name("macro_steps.json")
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


class MacroStudio(QtWidgets.QMainWindow):
    refresh_actions_requested = QtCore.Signal()
    status_changed = QtCore.Signal(str)
    loop_changed = QtCore.Signal(str)
    position_captured = QtCore.Signal(int, int)
    stop_recording_requested = QtCore.Signal()
    stop_macro_requested = QtCore.Signal()

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

        self.keyboard_controller = keyboard.Controller()
        self.mouse_controller = mouse.Controller()

        self.palette = {
            "bg": "#08111D",
            "panel": "rgba(18, 31, 49, 0.88)",
            "panelSolid": "#122033",
            "panelAlt": "rgba(20, 37, 59, 0.92)",
            "stroke": "rgba(124, 155, 196, 0.25)",
            "text": "#EAF2FF",
            "muted": "#9FB2CE",
            "accent": "#74C0FC",
            "accent2": "#4DABF7",
            "danger": "#FF7B72",
            "success": "#8CE99A",
            "surface": "rgba(12, 21, 35, 0.94)",
        }

        self.record_mode_text = "Thêm vào"
        self._updating_editor = False

        self._build_ui()
        self._connect_signals()
        self._apply_styles()
        self._apply_window_effects()
        self._load_actions()
        self._start_hotkey_listener()

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
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        hero = QtWidgets.QFrame()
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(8, 0, 8, 0)
        hero_layout.setSpacing(4)

        title = QtWidgets.QLabel("Macro Studio")
        title.setObjectName("HeroTitle")
        subtitle = QtWidgets.QLabel(
            "Ghi lại các thao tác thực tế, lưu quỹ đạo chuột, phát lại tuần tự vô hạn và dừng an toàn bằng phím F8."
        )
        subtitle.setObjectName("HeroSubtitle")
        subtitle.setWordWrap(True)
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        root.addWidget(hero)

        self.body_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.setHandleWidth(10)
        root.addWidget(self.body_splitter, 1)

        left_host = QtWidgets.QWidget()
        left_stack = QtWidgets.QVBoxLayout(left_host)
        left_stack.setContentsMargins(0, 0, 0, 0)
        left_stack.setSpacing(12)
        self.body_splitter.addWidget(left_host)

        left_card = self._create_card()
        left_layout = QtWidgets.QVBoxLayout(left_card)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(14)
        left_stack.addWidget(left_card, 5)

        left_header = QtWidgets.QVBoxLayout()
        left_header.setSpacing(4)
        timeline_title = QtWidgets.QLabel("Dòng thời gian Macro")
        timeline_title.setObjectName("SectionTitle")
        timeline_subtitle = QtWidgets.QLabel("Mỗi bước sẽ chạy tuần tự. Ví dụ: Nếu có 3 bước A, B, C thì sẽ thực hiện A xong mới đến B, rồi C.")
        timeline_subtitle.setObjectName("MutedLabel")
        timeline_subtitle.setWordWrap(True)
        left_header.addWidget(timeline_title)
        left_header.addWidget(timeline_subtitle)
        left_layout.addLayout(left_header)

        stats = QtWidgets.QHBoxLayout()
        stats.setSpacing(10)
        steps_card, self.steps_value = self._create_stat_card("Số bước", "0")
        loop_card, self.loop_value = self._create_stat_card("Vòng lặp", "0")
        mode_card, self.mode_value = self._create_stat_card("Chế độ ghi", "Thêm vào")
        stats.addWidget(steps_card)
        stats.addWidget(loop_card)
        stats.addWidget(mode_card)
        left_layout.addLayout(stats)

        self.action_list = QtWidgets.QListWidget()
        self.action_list.setObjectName("TimelineList")
        self.action_list.currentRowChanged.connect(self._load_selected_action_into_editor)
        left_layout.addWidget(self.action_list, 1)

        timeline_actions = QtWidgets.QGridLayout()
        timeline_actions.setHorizontalSpacing(8)
        timeline_actions.setVerticalSpacing(8)
        buttons = [
            ("Xóa bước", self._remove_selected),
            ("Xóa tất cả", self._clear_actions),
            ("Lên", lambda: self._move_selected(-1)),
            ("Xuống", lambda: self._move_selected(1)),
            ("Lưu file", self._save_actions),
            ("Nạp file", self._load_actions),
        ]
        for index, (label, handler) in enumerate(buttons):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(handler)
            button.setProperty("variant", "secondary")
            timeline_actions.addWidget(button, 0, index)
        left_layout.addLayout(timeline_actions)

        editor_card = self._create_card(alt=True)
        editor_layout = QtWidgets.QVBoxLayout(editor_card)
        editor_layout.setContentsMargins(18, 18, 18, 18)
        editor_layout.setSpacing(10)
        left_stack.addWidget(editor_card, 4)

        editor_title = QtWidgets.QLabel("Trình chỉnh sửa Macro")
        editor_title.setObjectName("SectionTitleAlt")
        editor_text = QtWidgets.QLabel(
            "Chọn một bước trong dòng thời gian để chỉnh sửa độ trễ, tọa độ, phím, tổ hợp phím hoặc từng điểm quỹ đạo chuột."
        )
        editor_text.setObjectName("MutedLabelAlt")
        editor_text.setWordWrap(True)
        editor_layout.addWidget(editor_title)
        editor_layout.addWidget(editor_text)

        editor_form = QtWidgets.QFormLayout()
        editor_form.setSpacing(8)
        self.editor_action_type = QtWidgets.QComboBox()
        self.editor_action_type.addItems(
            ["key_tap", "key_down", "key_up", "combo_press", "mouse_click", "mouse_move", "wait"]
        )
        self.editor_action_type.currentTextChanged.connect(self._update_editor_stack_visibility)
        self.editor_post_delay = QtWidgets.QLineEdit("250")
        editor_form.addRow("Loại action", self.editor_action_type)
        editor_form.addRow("Delay sau bước (ms)", self.editor_post_delay)
        editor_layout.addLayout(editor_form)

        self.editor_stack = QtWidgets.QStackedWidget()
        editor_layout.addWidget(self.editor_stack)

        self.editor_page_key = self._make_editor_page()
        key_form = QtWidgets.QFormLayout(self.editor_page_key)
        self.editor_key_input = QtWidgets.QLineEdit()
        key_form.addRow("Key", self.editor_key_input)
        self.editor_stack.addWidget(self.editor_page_key)

        self.editor_page_combo = self._make_editor_page()
        combo_form = QtWidgets.QFormLayout(self.editor_page_combo)
        self.editor_combo_keys_input = QtWidgets.QLineEdit()
        combo_hint = QtWidgets.QLabel("Ví dụ: ctrl_l,c (Ctrl+C) hoặc ctrl_l,shift_l,s (Ctrl+Shift+S)")
        combo_hint.setObjectName("MutedLabelAlt")
        combo_hint.setWordWrap(True)
        combo_form.addRow("Danh sách key", self.editor_combo_keys_input)
        combo_form.addRow(combo_hint)
        self.editor_stack.addWidget(self.editor_page_combo)

        self.editor_page_click = self._make_editor_page()
        click_form = QtWidgets.QFormLayout(self.editor_page_click)
        self.editor_x_input = QtWidgets.QLineEdit()
        self.editor_y_input = QtWidgets.QLineEdit()
        self.editor_button_input = QtWidgets.QComboBox()
        self.editor_button_input.addItems(["left", "right", "middle"])
        click_form.addRow("X", self.editor_x_input)
        click_form.addRow("Y", self.editor_y_input)
        click_form.addRow("Nút", self.editor_button_input)
        self.editor_stack.addWidget(self.editor_page_click)

        self.editor_page_move = self._make_editor_page()
        move_layout = QtWidgets.QVBoxLayout(self.editor_page_move)
        move_info = QtWidgets.QLabel("Mỗi dòng là một điểm: thời gian(ms),x,y. Ví dụ: 120,500,300 (sau 120ms di chuyển đến 500,300)")
        move_info.setObjectName("MutedLabelAlt")
        move_info.setWordWrap(True)
        self.editor_points_input = QtWidgets.QPlainTextEdit()
        self.editor_points_input.setPlaceholderText("0,100,200\n35,120,210\n80,180,260")
        move_layout.addWidget(move_info)
        move_layout.addWidget(self.editor_points_input)
        self.editor_stack.addWidget(self.editor_page_move)

        self.editor_page_wait = self._make_editor_page()
        wait_form = QtWidgets.QFormLayout(self.editor_page_wait)
        self.editor_duration_input = QtWidgets.QLineEdit()
        wait_form.addRow("Thời gian chờ (ms)", self.editor_duration_input)
        self.editor_stack.addWidget(self.editor_page_wait)

        editor_buttons = QtWidgets.QGridLayout()
        editor_buttons.setHorizontalSpacing(8)
        editor_buttons.setVerticalSpacing(8)
        self.apply_edit_button = QtWidgets.QPushButton("Áp dụng thay đổi")
        self.apply_edit_button.setProperty("variant", "primary")
        self.apply_edit_button.clicked.connect(self._apply_selected_action_edits)
        self.duplicate_action_button = QtWidgets.QPushButton("Nhân bản")
        self.duplicate_action_button.setProperty("variant", "secondary")
        self.duplicate_action_button.clicked.connect(self._duplicate_selected_action)
        self.insert_action_button = QtWidgets.QPushButton("Chèn dưới")
        self.insert_action_button.setProperty("variant", "secondary")
        self.insert_action_button.clicked.connect(self._insert_action_below_selected)
        self.reload_action_button = QtWidgets.QPushButton("Nạp lại")
        self.reload_action_button.setProperty("variant", "secondary")
        self.reload_action_button.clicked.connect(
            lambda: self._load_selected_action_into_editor(self.action_list.currentRow())
        )
        editor_buttons.addWidget(self.apply_edit_button, 0, 0)
        editor_buttons.addWidget(self.duplicate_action_button, 0, 1)
        editor_buttons.addWidget(self.insert_action_button, 0, 2)
        editor_buttons.addWidget(self.reload_action_button, 0, 3)
        editor_layout.addLayout(editor_buttons)

        right_scroll = QtWidgets.QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        right_scroll.setObjectName("RightScroll")
        self.body_splitter.addWidget(right_scroll)

        right_host = QtWidgets.QWidget()
        right_scroll.setWidget(right_host)
        right_stack = QtWidgets.QVBoxLayout(right_host)
        right_stack.setContentsMargins(0, 0, 4, 0)
        right_stack.setSpacing(10)

        control_card = self._create_card()
        control_layout = QtWidgets.QGridLayout(control_card)
        control_layout.setContentsMargins(18, 18, 18, 18)
        control_layout.setHorizontalSpacing(8)
        control_layout.setVerticalSpacing(8)
        right_stack.addWidget(control_card)

        control_title = QtWidgets.QLabel("Điều khiển Macro")
        control_title.setObjectName("SectionTitle")
        control_text = QtWidgets.QLabel(
            "Bắt đầu chạy macro vô hạn. Dừng bằng nút Stop, phím F8, hoặc kéo chuột lên góc trên trái màn hình. Chế độ Ghi Thay thế sẽ xóa macro cũ khi bắt đầu ghi."
        )
        control_text.setObjectName("MutedLabel")
        control_text.setWordWrap(True)
        control_layout.addWidget(control_title, 0, 0, 1, 3)
        control_layout.addWidget(control_text, 1, 0, 1, 3)

        self.start_button = QtWidgets.QPushButton("Bắt đầu")
        self.start_button.setProperty("variant", "primary")
        self.start_button.clicked.connect(self._start_macro)
        control_layout.addWidget(self.start_button, 2, 0)

        self.stop_button = QtWidgets.QPushButton("Dừng")
        self.stop_button.setProperty("variant", "danger")
        self.stop_button.clicked.connect(self._stop_macro)
        control_layout.addWidget(self.stop_button, 2, 1)

        capture_button = QtWidgets.QPushButton("Chụp vị trí chuột")
        capture_button.setProperty("variant", "secondary")
        capture_button.clicked.connect(self._capture_mouse_position)
        control_layout.addWidget(capture_button, 2, 2)

        record_append = QtWidgets.QPushButton("Ghi thêm")
        record_append.setProperty("variant", "secondary")
        record_append.clicked.connect(lambda: self._toggle_recording(False))
        control_layout.addWidget(record_append, 3, 0)

        record_replace = QtWidgets.QPushButton("Ghi thay thế")
        record_replace.setProperty("variant", "primary")
        record_replace.clicked.connect(lambda: self._toggle_recording(True))
        control_layout.addWidget(record_replace, 3, 1)

        stop_record = QtWidgets.QPushButton("Dừng ghi")
        stop_record.setProperty("variant", "secondary")
        stop_record.clicked.connect(self._stop_recording)
        control_layout.addWidget(stop_record, 3, 2)

        settings_card = self._create_card(alt=True)
        settings_layout = QtWidgets.QFormLayout(settings_card)
        settings_layout.setContentsMargins(18, 18, 18, 18)
        settings_layout.setSpacing(10)
        right_stack.addWidget(settings_card)

        settings_title = QtWidgets.QLabel("Cài đặt chung")
        settings_title.setObjectName("SectionTitleAlt")
        settings_layout.addRow(settings_title)

        self.default_delay_input = QtWidgets.QLineEdit(str(DEFAULT_DELAY_MS))
        self.record_after_input = QtWidgets.QLineEdit("2")
        settings_layout.addRow("Độ trễ mặc định sau mỗi bước (ms)", self.default_delay_input)
        settings_layout.addRow("Chờ trước khi ghi (giây)", self.record_after_input)

        info = QtWidgets.QLabel(
            "Chế độ ghi thông minh sẽ ghi lại việc nhấn giữ/thả phím, click chuột và quỹ đạo di chuyển chuột với thời gian thực giữa các bước."
        )
        info.setWordWrap(True)
        info.setObjectName("MutedLabelAlt")
        settings_layout.addRow(info)

        key_card = self._create_card()
        key_layout = QtWidgets.QFormLayout(key_card)
        key_layout.setContentsMargins(18, 18, 18, 18)
        key_layout.setSpacing(10)
        right_stack.addWidget(key_card)

        key_title = QtWidgets.QLabel("Thêm phím nhanh")
        key_title.setObjectName("SectionTitle")
        key_layout.addRow(key_title)
        self.key_name_input = QtWidgets.QLineEdit("a")
        self.key_delay_input = QtWidgets.QLineEdit(str(DEFAULT_DELAY_MS))
        key_layout.addRow("Phím", self.key_name_input)
        key_hint = QtWidgets.QLabel("Thêm hành động nhấn một phím đơn giản. Ví dụ: a (phím A), enter (Enter), space (Space), tab (Tab), esc (Escape), f1 (F1), ctrl_l (Ctrl trái)")
        key_hint.setWordWrap(True)
        key_hint.setObjectName("MutedLabel")
        key_layout.addRow(key_hint)
        key_layout.addRow("Nghỉ sau bước (ms)", self.key_delay_input)
        add_key = QtWidgets.QPushButton("Thêm phím")
        add_key.setProperty("variant", "secondary")
        add_key.clicked.connect(self._add_key_action)
        key_layout.addRow(add_key)

        combo_card = self._create_card()
        combo_layout = QtWidgets.QFormLayout(combo_card)
        combo_layout.setContentsMargins(18, 18, 18, 18)
        combo_layout.setSpacing(10)
        right_stack.addWidget(combo_card)

        combo_title = QtWidgets.QLabel("Thêm tổ hợp phím")
        combo_title.setObjectName("SectionTitle")
        combo_layout.addRow(combo_title)
        combo_modifiers = QtWidgets.QHBoxLayout()
        self.combo_ctrl = QtWidgets.QCheckBox("Ctrl")
        self.combo_shift = QtWidgets.QCheckBox("Shift")
        self.combo_alt = QtWidgets.QCheckBox("Alt")
        self.combo_win = QtWidgets.QCheckBox("Win")
        for checkbox in [self.combo_ctrl, self.combo_shift, self.combo_alt, self.combo_win]:
            combo_modifiers.addWidget(checkbox)
        self.combo_key_input = QtWidgets.QLineEdit("c")
        self.combo_delay_input = QtWidgets.QLineEdit(str(DEFAULT_DELAY_MS))
        combo_hint_2 = QtWidgets.QLabel("Thêm hành động nhấn tổ hợp phím (nhiều phím cùng lúc). Ví dụ: Ctrl+C (sao chép), Ctrl+V (dán), Ctrl+Shift+S (lưu dưới dạng)")
        combo_hint_2.setObjectName("MutedLabel")
        combo_hint_2.setWordWrap(True)
        combo_layout.addRow("Modifier", combo_modifiers)
        combo_layout.addRow("Key chính", self.combo_key_input)
        combo_layout.addRow("Nghỉ sau bước (ms)", self.combo_delay_input)
        combo_layout.addRow(combo_hint_2)
        add_combo = QtWidgets.QPushButton("Thêm tổ hợp")
        add_combo.setProperty("variant", "secondary")
        add_combo.clicked.connect(self._add_combo_action)
        combo_layout.addRow(add_combo)

        mouse_card = self._create_card()
        mouse_layout = QtWidgets.QFormLayout(mouse_card)
        mouse_layout.setContentsMargins(18, 18, 18, 18)
        mouse_layout.setSpacing(10)
        right_stack.addWidget(mouse_card)

        mouse_title = QtWidgets.QLabel("Thêm click chuột")
        mouse_title.setObjectName("SectionTitle")
        mouse_layout.addRow(mouse_title)
        self.mouse_x_input = QtWidgets.QLineEdit("0")
        self.mouse_y_input = QtWidgets.QLineEdit("0")
        self.mouse_button_input = QtWidgets.QComboBox()
        self.mouse_button_input.addItems(["left", "right", "middle"])
        self.mouse_delay_input = QtWidgets.QLineEdit(str(DEFAULT_DELAY_MS))
        mouse_hint = QtWidgets.QLabel("Thêm hành động click chuột tại vị trí cụ thể. Sử dụng nút 'Chụp vị trí chuột' để lấy tọa độ hiện tại của con trỏ.")
        mouse_hint.setObjectName("MutedLabel")
        mouse_hint.setWordWrap(True)
        mouse_layout.addRow("X", self.mouse_x_input)
        mouse_layout.addRow("Y", self.mouse_y_input)
        mouse_layout.addRow("Nút", self.mouse_button_input)
        mouse_layout.addRow("Nghỉ sau bước (ms)", self.mouse_delay_input)
        mouse_layout.addRow(mouse_hint)
        add_mouse = QtWidgets.QPushButton("Thêm click")
        add_mouse.setProperty("variant", "secondary")
        add_mouse.clicked.connect(self._add_mouse_action)
        mouse_layout.addRow(add_mouse)

        wait_card = self._create_card()
        wait_layout = QtWidgets.QFormLayout(wait_card)
        wait_layout.setContentsMargins(18, 18, 18, 18)
        wait_layout.setSpacing(10)
        right_stack.addWidget(wait_card)

        wait_title = QtWidgets.QLabel("Thêm bước chờ")
        wait_title.setObjectName("SectionTitle")
        wait_layout.addRow(wait_title)
        self.wait_input = QtWidgets.QLineEdit("1000")
        wait_hint = QtWidgets.QLabel("Thêm thời gian chờ giữa các bước để ứng dụng có thời gian phản hồi. Ví dụ: Chờ 1000ms (1 giây) sau khi click.")
        wait_hint.setObjectName("MutedLabel")
        wait_hint.setWordWrap(True)
        wait_layout.addRow("Thời gian chờ (ms)", self.wait_input)
        wait_layout.addRow(wait_hint)
        add_wait = QtWidgets.QPushButton("Thêm chờ")
        add_wait.setProperty("variant", "secondary")
        add_wait.clicked.connect(self._add_wait_action)
        wait_layout.addRow(add_wait)
        right_stack.addStretch(1)

        self.body_splitter.setStretchFactor(0, 7)
        self.body_splitter.setStretchFactor(1, 5)
        self.body_splitter.setSizes([760, 520])

        status_card = QtWidgets.QFrame()
        status_card.setObjectName("StatusCard")
        status_layout = QtWidgets.QHBoxLayout(status_card)
        status_layout.setContentsMargins(14, 12, 14, 12)
        self.status_label = QtWidgets.QLabel(
            "Sẵn sàng. Dừng macro bằng phím F8, nút Dừng, hoặc kéo chuột lên góc trên trái màn hình."
        )
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        root.addWidget(status_card)

    def _apply_styles(self) -> None:
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: #08111D;
            }}
            QWidget#AppRoot {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(8, 17, 29, 240),
                    stop:0.45 rgba(10, 22, 37, 235),
                    stop:1 rgba(16, 32, 54, 245)
                );
            }}
            QFrame[card="true"] {{
                background: {self.palette["panel"]};
                border: 1px solid {self.palette["stroke"]};
                border-radius: 22px;
            }}
            QFrame[cardAlt="true"] {{
                background: {self.palette["panelAlt"]};
                border: 1px solid {self.palette["stroke"]};
                border-radius: 22px;
            }}
            #HeroTitle {{
                color: {self.palette["text"]};
                font-size: 34px;
                font-weight: 700;
            }}
            #HeroSubtitle {{
                color: {self.palette["muted"]};
                font-size: 13px;
            }}
            #SectionTitle, #SectionTitleAlt {{
                color: {self.palette["text"]};
                font-size: 18px;
                font-weight: 650;
            }}
            #MutedLabel, #MutedLabelAlt {{
                color: {self.palette["muted"]};
                font-size: 12px;
            }}
            QLabel[statTitle="true"] {{
                color: {self.palette["muted"]};
                font-size: 11px;
            }}
            QLabel[statValue="true"] {{
                color: {self.palette["text"]};
                font-size: 26px;
                font-weight: 700;
            }}
            QListWidget#TimelineList {{
                background: {self.palette["surface"]};
                color: {self.palette["text"]};
                border: 1px solid {self.palette["stroke"]};
                border-radius: 18px;
                padding: 8px;
                outline: none;
                font-family: Consolas;
                font-size: 12px;
            }}
            QListWidget#TimelineList::item {{
                padding: 10px 12px;
                border-radius: 12px;
                margin: 3px 4px;
            }}
            QListWidget#TimelineList::item:selected {{
                background: rgba(116, 192, 252, 0.92);
                color: #08111D;
            }}
            QPushButton {{
                min-height: 42px;
                border-radius: 14px;
                border: 1px solid transparent;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton[variant="primary"] {{
                background: {self.palette["accent"]};
                color: #08111D;
            }}
            QPushButton[variant="secondary"] {{
                background: rgba(28, 44, 69, 0.96);
                color: {self.palette["text"]};
                border: 1px solid {self.palette["stroke"]};
            }}
            QPushButton[variant="danger"] {{
                background: {self.palette["danger"]};
                color: #180A10;
            }}
            QPushButton:hover {{
                border: 1px solid rgba(255, 255, 255, 0.18);
            }}
            QLineEdit, QComboBox {{
                background: rgba(11, 22, 36, 0.92);
                color: {self.palette["text"]};
                border: 1px solid {self.palette["stroke"]};
                border-radius: 12px;
                min-height: 38px;
                padding: 0 12px;
                selection-background-color: {self.palette["accent2"]};
            }}
            QPlainTextEdit {{
                background: rgba(11, 22, 36, 0.92);
                color: {self.palette["text"]};
                border: 1px solid {self.palette["stroke"]};
                border-radius: 12px;
                padding: 10px 12px;
                selection-background-color: {self.palette["accent2"]};
            }}
            QCheckBox {{
                color: {self.palette["text"]};
                font-size: 12px;
                spacing: 8px;
            }}
            QScrollArea#RightScroll {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: rgba(8, 17, 29, 0.35);
                width: 10px;
                border-radius: 5px;
                margin: 4px 0 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(116, 192, 252, 0.55);
                border-radius: 5px;
                min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QComboBox QAbstractItemView {{
                background: {self.palette["panelSolid"]};
                color: {self.palette["text"]};
                selection-background-color: {self.palette["accent2"]};
            }}
            QFormLayout QLabel {{
                color: {self.palette["muted"]};
                font-size: 12px;
            }}
            #StatusCard {{
                background: rgba(8, 17, 29, 0.92);
                border: 1px solid {self.palette["stroke"]};
                border-radius: 18px;
            }}
            #StatusLabel {{
                color: {self.palette["text"]};
                font-size: 12px;
            }}
            """
        )

    def _create_card(self, alt: bool = False) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        if alt:
            frame.setProperty("cardAlt", True)
        else:
            frame.setProperty("card", True)
        effect = QtWidgets.QGraphicsDropShadowEffect(frame)
        effect.setBlurRadius(34)
        effect.setOffset(0, 14)
        effect.setColor(QtGui.QColor(0, 0, 0, 55))
        frame.setGraphicsEffect(effect)
        return frame

    def _create_stat_card(self, title: str, value: str) -> tuple[QtWidgets.QFrame, QtWidgets.QLabel]:
        card = QtWidgets.QFrame()
        card.setProperty("cardAlt", True)
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title_label = QtWidgets.QLabel(title)
        title_label.setProperty("statTitle", True)
        value_label = QtWidgets.QLabel(value)
        value_label.setProperty("statValue", True)
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

    def _add_key_action(self) -> None:
        try:
            delay = self._read_int(self.key_delay_input.text(), "Delay sau phím", 0)
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Sai dữ liệu", str(exc))
            return

        key_name = self.key_name_input.text().strip().lower()
        if not key_name:
            QtWidgets.QMessageBox.critical(self, "Thiếu dữ liệu", "Bạn cần nhập tên phím.")
            return

        with self.actions_lock:
            self.actions.append(MacroAction(action_type="key_tap", key=key_name, post_delay_ms=delay))
        self.refresh_actions_requested.emit()
        self._save_actions(silent=True)
        self.status_changed.emit(f"Đã thêm phím '{key_name}'.")

    def _add_combo_action(self) -> None:
        try:
            delay = self._read_int(self.combo_delay_input.text(), "Delay sau tổ hợp", 0)
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Sai dữ liệu", str(exc))
            return

        main_key = self.combo_key_input.text().strip().lower()
        if not main_key:
            QtWidgets.QMessageBox.critical(self, "Thiếu dữ liệu", "Bạn cần nhập key chính cho tổ hợp.")
            return

        keys: list[str] = []
        if self.combo_ctrl.isChecked():
            keys.append("ctrl_l")
        if self.combo_shift.isChecked():
            keys.append("shift_l")
        if self.combo_alt.isChecked():
            keys.append("alt_l")
        if self.combo_win.isChecked():
            keys.append("cmd")
        keys.append(main_key)

        with self.actions_lock:
            self.actions.append(MacroAction(action_type="combo_press", keys=keys, post_delay_ms=delay))
        self.refresh_actions_requested.emit()
        self._save_actions(silent=True)
        self.status_changed.emit(f"Đã thêm tổ hợp {' + '.join(keys)}.")

    def _add_mouse_action(self) -> None:
        try:
            x = self._read_int(self.mouse_x_input.text(), "Tọa độ X")
            y = self._read_int(self.mouse_y_input.text(), "Tọa độ Y")
            delay = self._read_int(self.mouse_delay_input.text(), "Delay sau click", 0)
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Sai dữ liệu", str(exc))
            return

        button = self.mouse_button_input.currentText().strip().lower() or "left"
        with self.actions_lock:
            self.actions.append(
                MacroAction(action_type="mouse_click", x=x, y=y, button=button, post_delay_ms=delay)
            )
        self.refresh_actions_requested.emit()
        self._save_actions(silent=True)
        self.status_changed.emit(f"Đã thêm click {button} tại ({x}, {y}).")

    def _add_wait_action(self) -> None:
        try:
            duration_ms = self._read_int(self.wait_input.text(), "Thời gian chờ", 1)
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Sai dữ liệu", str(exc))
            return

        with self.actions_lock:
            self.actions.append(MacroAction(action_type="wait", duration_ms=duration_ms))
        self.refresh_actions_requested.emit()
        self._save_actions(silent=True)
        self.status_changed.emit(f"Đã thêm bước chờ {duration_ms}ms.")

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
        self.mouse_x_input.setText(str(x))
        self.mouse_y_input.setText(str(y))
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
            key_name = self._normalize_recorded_key(key_pressed)
            if key_name:
                self._record_discrete_action(
                    MacroAction(action_type="key_down", key=key_name, post_delay_ms=default_delay)
                )

        def on_release(key_released) -> None:
            key_name = self._normalize_recorded_key(key_released)
            if key_name:
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

        self.stop_event.clear()
        self.is_running = True
        self.loop_changed.emit("0")
        self.hide()
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
            for key_obj in reversed(parsed_keys):
                self.keyboard_controller.release(key_obj)
            self._sleep_with_stop(action.post_delay_ms / 1000)
            return

        if action.action_type == "mouse_move":
            self._play_mouse_path(action)
            self._sleep_with_stop(action.post_delay_ms / 1000)
            return

        if action.action_type == "wait":
            self._sleep_with_stop(action.duration_ms / 1000)

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

    def _normalize_recorded_key(self, recorded_key) -> Optional[str]:
        if hasattr(recorded_key, "char") and recorded_key.char:
            char = recorded_key.char.lower()
            if char == "\x08":
                return "backspace"
            return char
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
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
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
        self.editor_key_input.setText(action.key)
        self.editor_combo_keys_input.setText(", ".join(action.keys))
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
        self.editor_key_input.clear()
        self.editor_combo_keys_input.clear()
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
            key_name = self.editor_key_input.text().strip().lower()
            if not key_name:
                raise ValueError("Bạn cần nhập key.")
            action.key = key_name
            return action

        if action_type == "combo_press":
            raw_keys = [item.strip().lower() for item in self.editor_combo_keys_input.text().split(",")]
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
