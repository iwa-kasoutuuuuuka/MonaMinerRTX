import os
import subprocess
import sys
import time
import webbrowser
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QFrame,
    QFileDialog, QMessageBox, QTabWidget, QRadioButton, QButtonGroup,
    QSpinBox, QDoubleSpinBox, QScrollArea, QProgressBar,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread

from app.hardware import HardwareManager
from app.miner_controller import MinerController
from app.config import ConfigManager, DEFAULT_POOLS, validate_mona_address
from app.ui.components import MetricCard, ModeCard, LogConsole
from app.ui.styles import MAIN_STYLE
from app.services import (
    IdleTracker, ProfitCalculator, DiscordNotifier,
    GpuHardwareController, WebMonitoringServer
)
from app.miner.opencl_backend import OpenCLBackend
from app.miner.benchmark import BenchmarkWorker


def _app_root() -> str:
    # Frozen: node/ is copied next to the exe, while __file__ points into _internal/.
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _launch_bat_in_new_window(bat_path: str):
    # The empty "" is start's window title; without it a quoted path (one containing spaces)
    # is taken as the title and the script never runs.
    subprocess.Popen(["cmd.exe", "/c", "start", "", bat_path], cwd=os.path.dirname(bat_path))


class NodeSyncWorker(QThread):
    """バックグラウンドでローカルノードのブロック同期状態を取得するスレッド"""
    sync_result = Signal(dict)

    def __init__(self, host="127.0.0.1", port=9402, user="monacoinrpc", password="rpcpassword"):
        super().__init__()
        self.host = host
        self.port = port
        self.user = user
        self.password = password

    def run(self):
        from app.services.node_service import fetch_node_sync_info
        info = fetch_node_sync_info(self.host, self.port, self.user, self.password, timeout=1.5)
        self.sync_result.emit(info)


class MainWindow(QMainWindow):
    # Emitted by the web-server thread; delivered to the GUI thread (QTimer.singleShot never fires
    # when called from a thread that has no Qt event loop).
    remote_toggle = Signal(bool)

    def __init__(self):
        super().__init__()
        self._web_snapshot = {}
        self._last_node_info = {}
        self._node_worker = None
        self.setWindowTitle("MonaMiner RTX / RX v2.1.1 - 次世代モナコイン (Lyra2REv2) GPU/CPU マイニングスタジオ")
        self.setMinimumSize(920, 640)
        self.resize(1120, 880)
        self.setStyleSheet(MAIN_STYLE)

        self.config_mgr = ConfigManager()
        self.hw_mgr = HardwareManager()
        bench = self.config_mgr.get("benchmark", {}) or {}
        self.hw_mgr.set_measured(bench.get("gpu_mhs"), bench.get("cpu_mhs_per_thread"))
        self._benchmark_worker = None
        self.miner_ctrl = MinerController(self.hw_mgr)

        # v2.0.0 Services
        self.profit_calc = ProfitCalculator(
            electricity_rate_yen=self.config_mgr.get("electricity_rate_yen", 31.0),
            mona_jpy_price=self.config_mgr.get("mona_jpy_price", 45.0)
        )
        self.discord_notifier = DiscordNotifier(
            webhook_url=self.config_mgr.get("discord_webhook_url", "")
        )
        self.gpu_ctrl = GpuHardwareController()
        self.idle_tracker = IdleTracker(check_interval_ms=1000)
        self.idle_tracker.set_threshold_minutes(self.config_mgr.get("idle_mining_minutes", 5))

        self.web_server = WebMonitoringServer(
            port=self.config_mgr.get("web_dashboard_port", 8888)
        )

        self.current_mode = self.config_mgr.get("miner_mode", "auto")
        self.target_type = self.config_mgr.get("mining_target", "pool") # 'pool' or 'solo'
        self.device_target = self.config_mgr.get("device_target", "gpu") # 'gpu', 'cpu', 'hybrid'
        self.mode_cards = {}
        self.mining_start_time = None
        self.auto_started_by_idle = False

        self._setup_ui()
        self._connect_signals()
        self._setup_services()
        self.remote_toggle.connect(self._on_remote_toggle)

        # Telemetry refresh timer (every 1 second)
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self._update_hardware_telemetry)
        self.telemetry_timer.start(1000)

        # Node sync status timer (every 3 seconds)
        self.node_sync_timer = QTimer(self)
        self.node_sync_timer.timeout.connect(self._check_node_sync_async)
        self.node_sync_timer.start(3000)

        # Initial updates
        self._update_hardware_telemetry()
        self._check_node_sync_async()

    def _setup_ui(self):
        # 0. Main Scroll Area for small resolutions & high DPI
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setCentralWidget(scroll_area)

        content_widget = QWidget()
        content_widget.setObjectName("content_widget")
        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(10)
        scroll_area.setWidget(content_widget)

        # 1. Top Header Banner (Persistent across all tabs)
        banner = QFrame()
        banner.setObjectName("banner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(10, 8, 10, 8)
        banner_layout.setSpacing(8)

        # Icon & Title Header
        header_left = QHBoxLayout()
        header_left.setSpacing(10)

        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icon.png")
        if os.path.exists(icon_path):
            from PySide6.QtGui import QPixmap
            lbl_logo = QLabel()
            pix = QPixmap(icon_path).scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl_logo.setPixmap(pix)
            header_left.addWidget(lbl_logo)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        title = QLabel("MonaMiner RTX / RX v2.1.1 (Lyra2REv2)")
        title.setObjectName("title")

        hw_info = self.hw_mgr.device_info
        cpu_info = self.hw_mgr.cpu_info

        if hw_info.get("is_amd", False):
            sub_text = f"🔴 AMD Radeon ({hw_info['short_name']}) & 多コアCPU ハイブリッド | プール / ソロ両用"
        elif self.hw_mgr.has_nvml and self.hw_mgr.device_count > 0:
            sub_text = f"⚡ NVIDIA GPU ({hw_info['short_name']}) & 多コアCPU ハイブリッド | プール / ソロ両用"
        else:
            sub_text = f"多コアCPU ({cpu_info['logical_cores']}T) マイニングスタジオ | プール / ソロ両用"

        subtitle = QLabel(sub_text)
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        header_left.addLayout(title_layout)
        banner_layout.addLayout(header_left, stretch=1)

        # Hardware Badge & Admin Status
        badge_layout = QVBoxLayout()
        badge_layout.setSpacing(4)
        badge_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        if hw_info.get("is_amd", False):
            lbl_hw = QLabel(f"🔴 {hw_info['name']} ({hw_info['arch_name']}) | 🧠 CPU ({cpu_info['logical_cores']}T)")
        elif self.hw_mgr.has_nvml and self.hw_mgr.device_count > 0:
            lbl_hw = QLabel(f"⚡ {hw_info['name']} ({hw_info['arch_name']}) | 🧠 CPU ({cpu_info['logical_cores']}T)")
        else:
            lbl_hw = QLabel(f"🧠 CPU 専用 ({cpu_info['logical_cores']} Threads)")
        lbl_hw.setObjectName("badge_rtx")
        lbl_hw.setWordWrap(True)
        badge_layout.addWidget(lbl_hw)

        if self.hw_mgr.is_admin:
            lbl_admin = QLabel("🔒 管理者権限: 有効 (NVML PowerLimit直接制御)")
            lbl_admin.setObjectName("badge_admin_ok")
        else:
            lbl_admin = QLabel("ℹ️ 一般権限 (Intensity強度制御)")
            lbl_admin.setObjectName("badge_admin_no")
        lbl_admin.setWordWrap(True)
        badge_layout.addWidget(lbl_admin)

        banner_layout.addLayout(badge_layout)
        main_layout.addWidget(banner)

        # 2. Hardware Live Status Bar (Metric Cards - Persistent across all tabs)
        status_bar = QHBoxLayout()
        status_bar.setSpacing(8)
        self.card_hashrate = MetricCard("ハッシュレート", "0.0", "MH/s")
        self.card_power = MetricCard("消費電力", "0.0", "W")
        self.card_cost = MetricCard("推定電気代 (1日)", "¥0.0", "目安")
        self.card_eff = MetricCard("電力効率", "--", "W/MH")
        self.card_gpu_temp = MetricCard("GPU 温度 / ファン", "--", "℃ / %")
        self.card_shares = MetricCard("承認シェア / ブロック", "0 / 0", "")

        status_bar.addWidget(self.card_hashrate)
        status_bar.addWidget(self.card_power)
        status_bar.addWidget(self.card_cost)
        status_bar.addWidget(self.card_eff)
        status_bar.addWidget(self.card_gpu_temp)
        status_bar.addWidget(self.card_shares)
        main_layout.addLayout(status_bar)

        # 3. Main Navigation Tab Widget (2-Tier UX)
        self.tabs_main = QTabWidget()
        self.tabs_main.setObjectName("tabs_main")

        # =========================================================================
        # TAB 1: 🏠 かんたん採掘 (ダッシュボード)
        # =========================================================================
        tab_dashboard = QWidget()
        dash_layout = QVBoxLayout(tab_dashboard)
        dash_layout.setContentsMargins(6, 8, 6, 8)
        dash_layout.setSpacing(10)

        # 1-A. Wallet Address Card (最重要: 目立つ位置に配置)
        addr_card = QFrame()
        addr_card.setObjectName("card")
        addr_layout = QVBoxLayout(addr_card)
        addr_layout.setContentsMargins(12, 10, 12, 10)
        addr_layout.setSpacing(6)

        lbl_addr_title = QLabel("🪙 モナコイン受取アドレス (Coinbase Wallet)")
        lbl_addr_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #fbbf24;")
        addr_layout.addWidget(lbl_addr_title)

        addr_row = QHBoxLayout()
        addr_row.setSpacing(8)
        self.edit_address = QLineEdit(self.config_mgr.get("wallet_address", ""))
        self.edit_address.setPlaceholderText("例: M... または mona1... (報酬受取用アドレス)")
        self.edit_address.setStyleSheet("font-size: 13px; font-weight: bold; padding: 8px 12px; background-color: #0f172a; border: 1px solid #475569; border-radius: 6px;")
        self.edit_address.textChanged.connect(self._validate_address_input)
        addr_row.addWidget(self.edit_address, stretch=4)

        self.lbl_addr_status = QLabel("")
        self.lbl_addr_status.setStyleSheet("font-size: 11px;")
        addr_row.addWidget(self.lbl_addr_status, stretch=1)

        self.btn_wallet_history = QPushButton("📜 入出金履歴 (残高確認)")
        self.btn_wallet_history.setCursor(Qt.PointingHandCursor)
        self.btn_wallet_history.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; padding: 8px 14px; border-radius: 6px; font-size: 12px;")
        self.btn_wallet_history.clicked.connect(self._open_wallet_history_dialog)
        addr_row.addWidget(self.btn_wallet_history)

        addr_layout.addLayout(addr_row)

        lbl_addr_hint = QLabel("💡 初めての方: ご自身のモナコイン受取アドレスを入力するだけで、すぐにマイニングを開始できます。「📜 入出金履歴」でリアルタイム残高や送受金履歴を確認できます。")
        lbl_addr_hint.setStyleSheet("color: #94a3b8; font-size: 11px;")
        addr_layout.addWidget(lbl_addr_hint)

        dash_layout.addWidget(addr_card)

        # 1-A2. Blockchain Node Sync Status Card (ブロックチェーン同期状況)
        sync_card = QFrame()
        sync_card.setObjectName("card")
        sync_layout = QVBoxLayout(sync_card)
        sync_layout.setContentsMargins(12, 10, 12, 10)
        sync_layout.setSpacing(6)

        sync_header = QHBoxLayout()
        lbl_sync_title = QLabel("⛓️ ブロックチェーン同期状況 (Blockchain Sync)")
        lbl_sync_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8;")
        sync_header.addWidget(lbl_sync_title)
        sync_header.addStretch()

        self.lbl_sync_badge = QLabel("⏹ ノード停止中")
        self.lbl_sync_badge.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 4px; background-color: #334155; color: #94a3b8;")
        sync_header.addWidget(self.lbl_sync_badge)

        self.btn_sync_refresh = QPushButton("🔄 更新")
        self.btn_sync_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_sync_refresh.setStyleSheet("background-color: #1e293b; color: #cbd5e1; border: 1px solid #475569; padding: 3px 10px; font-size: 11px; font-weight: bold; border-radius: 4px;")
        self.btn_sync_refresh.clicked.connect(self._manual_refresh_node_sync)
        sync_header.addWidget(self.btn_sync_refresh)

        self.btn_start_mainnet_node = QPushButton("⚡ 本番ノード起動")
        self.btn_start_mainnet_node.setCursor(Qt.PointingHandCursor)
        self.btn_start_mainnet_node.setStyleSheet("background-color: #10b981; color: white; padding: 3px 10px; font-size: 11px; font-weight: bold; border-radius: 4px;")
        self.btn_start_mainnet_node.clicked.connect(self._launch_mainnet_environment)
        sync_header.addWidget(self.btn_start_mainnet_node)

        sync_layout.addLayout(sync_header)

        # Progress bar
        self.progress_sync = QProgressBar()
        self.progress_sync.setRange(0, 1000)
        self.progress_sync.setValue(0)
        self.progress_sync.setTextVisible(True)
        self.progress_sync.setFormat("ノード未起動")
        self.progress_sync.setStyleSheet("""
            QProgressBar {
                border: 1px solid #334155;
                border-radius: 4px;
                text-align: center;
                background-color: #0f172a;
                color: #f8fafc;
                font-weight: bold;
                height: 20px;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #10b981);
                border-radius: 3px;
            }
        """)
        sync_layout.addWidget(self.progress_sync)

        # Block Numbers Details Row
        sync_num_row = QHBoxLayout()
        self.lbl_net_best_block = QLabel("🌐 ネットワーク最新: --")
        self.lbl_net_best_block.setStyleSheet("font-size: 12px; color: #94a3b8;")
        sync_num_row.addWidget(self.lbl_net_best_block)

        self.lbl_local_held_block = QLabel("💻 このPCの所持ブロック: 未接続")
        self.lbl_local_held_block.setStyleSheet("font-size: 12px; font-weight: bold; color: #e2e8f0;")
        sync_num_row.addWidget(self.lbl_local_held_block)

        self.lbl_sync_detail = QLabel("ノード未起動 (「⚡ 本番ノード起動」で起動できます)")
        self.lbl_sync_detail.setStyleSheet("font-size: 12px; color: #94a3b8;")
        sync_num_row.addWidget(self.lbl_sync_detail)
        sync_num_row.addStretch()

        sync_layout.addLayout(sync_num_row)
        dash_layout.addWidget(sync_card)

        # 1-B. Device & Optimization Profile (左右並列カード)
        mid_row = QHBoxLayout()
        mid_row.setSpacing(10)

        # Left: Device Selection Card
        device_card = QFrame()
        device_card.setObjectName("card")
        dev_layout = QVBoxLayout(device_card)
        dev_layout.setContentsMargins(10, 8, 10, 8)
        dev_layout.setSpacing(6)

        lbl_dev_title = QLabel("💻 採掘デバイス選択")
        lbl_dev_title.setStyleSheet("font-weight: bold; color: #94a3b8; font-size: 12px;")
        dev_layout.addWidget(lbl_dev_title)

        dev_btn_layout = QHBoxLayout()
        has_gpu = self.hw_mgr.has_gpu or (self.hw_mgr.has_nvml and self.hw_mgr.device_count > 0)
        gpu_badge = "🔴" if hw_info.get("is_amd", False) else "⚡"
        gpu_label = f"{gpu_badge} GPU ({hw_info['short_name']})" if has_gpu else "⚡ GPU (未検出)"
        self.btn_dev_gpu = QRadioButton(gpu_label)
        self.btn_dev_cpu = QRadioButton("🧠 CPU")
        self.btn_dev_hybrid = QRadioButton("🚀 ハイブリッド")

        if not has_gpu:
            self.btn_dev_gpu.setEnabled(False)
            self.btn_dev_hybrid.setEnabled(False)

        self.dev_group = QButtonGroup(self)
        self.dev_group.addButton(self.btn_dev_gpu, 1)
        self.dev_group.addButton(self.btn_dev_cpu, 2)
        self.dev_group.addButton(self.btn_dev_hybrid, 3)

        saved_dev = self.config_mgr.get("device_target", "gpu")
        if not has_gpu:
            self.btn_dev_cpu.setChecked(True)
        elif saved_dev == "cpu":
            self.btn_dev_cpu.setChecked(True)
        elif saved_dev == "hybrid":
            self.btn_dev_hybrid.setChecked(True)
        else:
            self.btn_dev_gpu.setChecked(True)

        self.dev_group.buttonClicked.connect(self._on_device_changed)
        dev_btn_layout.addWidget(self.btn_dev_gpu)
        dev_btn_layout.addWidget(self.btn_dev_cpu)
        dev_btn_layout.addWidget(self.btn_dev_hybrid)
        dev_layout.addLayout(dev_btn_layout)

        # CPU Thread Control
        cpu_ctrl_layout = QHBoxLayout()
        cpu_ctrl_layout.addWidget(QLabel("CPUスレッド数:"))
        self.spin_threads = QSpinBox()
        max_threads = self.hw_mgr.cpu_info["logical_cores"]
        self.spin_threads.setRange(1, max_threads)
        self.spin_threads.setValue(self.config_mgr.get("cpu_threads", min(16, max_threads)))
        self.spin_threads.valueChanged.connect(lambda v: self.config_mgr.set("cpu_threads", v))
        cpu_ctrl_layout.addWidget(self.spin_threads)
        lbl_thread_hint = QLabel(f"/ 最大 {max_threads}T")
        lbl_thread_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        cpu_ctrl_layout.addWidget(lbl_thread_hint)
        cpu_ctrl_layout.addStretch()
        dev_layout.addLayout(cpu_ctrl_layout)

        # CPU Presets
        rec_info = self.hw_mgr.get_mode_recommendation()
        btn_preset_layout = QHBoxLayout()
        btn_preset_layout.setSpacing(6)

        btn_cpu_eco = QPushButton(f"🍃 物理コア ({rec_info['modes']['eco']['cpu_threads']}T)")
        btn_cpu_eco.setStyleSheet("background-color: #1e293b; border: 1px solid #334155; border-radius: 4px; padding: 3px 6px; font-size: 11px; color: #cbd5e1;")
        btn_cpu_eco.setCursor(Qt.PointingHandCursor)
        btn_cpu_eco.clicked.connect(lambda: self.spin_threads.setValue(rec_info['modes']['eco']['cpu_threads']))

        btn_cpu_perf = QPushButton(f"⚡ 最大 ({rec_info['modes']['perf']['cpu_threads']}T)")
        btn_cpu_perf.setStyleSheet("background-color: #1e293b; border: 1px solid #334155; border-radius: 4px; padding: 3px 6px; font-size: 11px; color: #cbd5e1;")
        btn_cpu_perf.setCursor(Qt.PointingHandCursor)
        btn_cpu_perf.clicked.connect(lambda: self.spin_threads.setValue(rec_info['modes']['perf']['cpu_threads']))

        btn_cpu_quiet = QPushButton(f"☕ 静音 ({rec_info['modes']['quiet']['cpu_threads']}T)")
        btn_cpu_quiet.setStyleSheet("background-color: #1e293b; border: 1px solid #334155; border-radius: 4px; padding: 3px 6px; font-size: 11px; color: #cbd5e1;")
        btn_cpu_quiet.setCursor(Qt.PointingHandCursor)
        btn_cpu_quiet.clicked.connect(lambda: self.spin_threads.setValue(rec_info['modes']['quiet']['cpu_threads']))

        btn_preset_layout.addWidget(btn_cpu_eco)
        btn_preset_layout.addWidget(btn_cpu_perf)
        btn_preset_layout.addWidget(btn_cpu_quiet)
        btn_preset_layout.addStretch()
        dev_layout.addLayout(btn_preset_layout)

        mid_row.addWidget(device_card, stretch=2)

        # Right: GPU Profile Selection Card
        mode_box = QFrame()
        mode_box.setObjectName("card")
        mode_box_layout = QVBoxLayout(mode_box)
        mode_box_layout.setContentsMargins(10, 8, 10, 8)
        mode_box_layout.setSpacing(6)

        lbl_profile_title = QLabel("⚙️ 動作プロファイル (ワンクリック自動最適化)")
        lbl_profile_title.setStyleSheet("font-weight: bold; color: #94a3b8; font-size: 12px;")
        mode_box_layout.addWidget(lbl_profile_title)

        mode_btn_row = QHBoxLayout()
        mode_btn_row.setSpacing(6)
        modes = rec_info["modes"]
        for key in ["eco", "perf", "quiet"]:
            m = modes[key]
            card = ModeCard(key, m["name"], m["badge"], m["description"], m["est_hashrate"])
            card.selected.connect(self._on_mode_selected)
            self.mode_cards[key] = card
            mode_btn_row.addWidget(card)
        mode_box_layout.addLayout(mode_btn_row)

        mid_row.addWidget(mode_box, stretch=3)
        dash_layout.addLayout(mid_row)

        # Highlight initially selected mode
        active_key = self.current_mode
        if active_key == "auto":
            active_key = rec_info["recommended_key"]
        self._highlight_mode(active_key)

        # 1-C. Action Card: Current Destination Summary + Big Start/Stop Button
        action_card = QFrame()
        action_card.setObjectName("card")
        action_layout = QVBoxLayout(action_card)
        action_layout.setContentsMargins(12, 10, 12, 10)
        action_layout.setSpacing(8)

        dest_row = QHBoxLayout()
        self.lbl_current_target_summary = QLabel("")
        self.lbl_current_target_summary.setObjectName("summary_badge")
        self.lbl_current_target_summary.setWordWrap(True)
        dest_row.addWidget(self.lbl_current_target_summary, stretch=1)

        btn_go_settings = QPushButton("⚙️ 接続先・詳細を変更...")
        btn_go_settings.setStyleSheet("background-color: #334155; color: #93c5fd; border-radius: 4px; padding: 5px 12px; font-size: 11px; font-weight: bold;")
        btn_go_settings.setCursor(Qt.PointingHandCursor)
        btn_go_settings.clicked.connect(lambda: self.tabs_main.setCurrentIndex(1))
        dest_row.addWidget(btn_go_settings)
        action_layout.addLayout(dest_row)

        self.btn_toggle_mining = QPushButton("🚀 採掘開始 (Start Mining)")
        self.btn_toggle_mining.setObjectName("start_btn")
        self.btn_toggle_mining.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_mining.clicked.connect(self._toggle_mining)
        action_layout.addWidget(self.btn_toggle_mining)

        dash_layout.addWidget(action_card)

        # 1-D. Live Console
        lbl_console_title = QLabel("📋 リアルタイム動作ログ")
        lbl_console_title.setStyleSheet("font-weight: bold; color: #94a3b8; font-size: 12px; margin-top: 4px;")
        dash_layout.addWidget(lbl_console_title)
        self.console = LogConsole()
        dash_layout.addWidget(self.console)

        self.tabs_main.addTab(tab_dashboard, "🏠 かんたん採掘 (ダッシュボード)")

        # =========================================================================
        # TAB 2: ⚙️ 詳細設定・高度なツール
        # =========================================================================
        tab_advanced = QWidget()
        adv_layout = QVBoxLayout(tab_advanced)
        adv_layout.setContentsMargins(6, 8, 6, 8)
        adv_layout.setSpacing(10)

        lbl_adv_desc = QLabel("⚙️ プール接続、ソロマイニング、スマートアイドル、収益性計算、遠隔監視、GPU制御の詳細設定です。")
        lbl_adv_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        adv_layout.addWidget(lbl_adv_desc)

        self.tabs_settings = QTabWidget()
        self.tabs_settings.setObjectName("tabs_settings")

        # Sub-tab 1: 🏊 プール・ソロ接続
        tab_conn = QWidget()
        conn_layout = QVBoxLayout(tab_conn)
        conn_layout.setContentsMargins(8, 8, 8, 8)
        conn_layout.setSpacing(10)

        # Internal target tabs (Pool vs Solo)
        self.tabs_target = QTabWidget()
        self.tabs_target.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #334155; border-radius: 8px; background-color: #1e293b; padding: 10px; }
            QTabBar::tab { background: #0f172a; color: #94a3b8; padding: 6px 14px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; font-weight: bold; }
            QTabBar::tab:selected { background: #1e293b; color: #fbbf24; border: 1px solid #334155; border-bottom: none; }
        """)

        # Tab Pool
        tab_pool = QWidget()
        tab_pool_layout = QGridLayout(tab_pool)
        tab_pool_layout.setContentsMargins(8, 8, 8, 8)
        tab_pool_layout.setHorizontalSpacing(10)
        tab_pool_layout.setVerticalSpacing(8)

        tab_pool_layout.addWidget(QLabel("マイニング プール:"), 0, 0)
        self.combo_pool = QComboBox()
        for p in DEFAULT_POOLS:
            self.combo_pool.addItem(p["name"], p["url"])
        self.combo_pool.setCurrentIndex(self.config_mgr.get("pool_index", 0))
        self.combo_pool.currentIndexChanged.connect(self._on_pool_changed)
        tab_pool_layout.addWidget(self.combo_pool, 0, 1)

        tab_pool_layout.addWidget(QLabel("カスタム URL:"), 0, 2)
        self.edit_custom_pool = QLineEdit(self.config_mgr.get("custom_pool_url", ""))
        self.edit_custom_pool.setPlaceholderText("stratum+tcp://host:port (カスタム時)")
        self.edit_custom_pool.textChanged.connect(self._on_custom_pool_changed)
        self.edit_custom_pool.setEnabled(self.combo_pool.currentIndex() == 2)
        tab_pool_layout.addWidget(self.edit_custom_pool, 0, 3)

        tab_pool_layout.addWidget(QLabel("ワーカー名:"), 1, 0)
        self.edit_worker = QLineEdit(self.config_mgr.get("worker_name", "rtx5080_worker"))
        self.edit_worker.setPlaceholderText("例: アカウント名.worker1 (VIPPOOL登録名)")
        self.edit_worker.setToolTip("VIPPOOL等の登録制プールでは「Web登録ユーザー名.ワーカー名」を入力してください。")
        self.edit_worker.textChanged.connect(self._on_worker_changed)
        tab_pool_layout.addWidget(self.edit_worker, 1, 1)

        tab_pool_layout.addWidget(QLabel("ワーカー パスワード:"), 1, 2)
        self.edit_pool_pass = QLineEdit(self.config_mgr.get("pool_password", "x"))
        self.edit_pool_pass.textChanged.connect(lambda t: self.config_mgr.set("pool_password", t.strip()))
        tab_pool_layout.addWidget(self.edit_pool_pass, 1, 3)

        lbl_pool_hint = QLabel("💡 ヒント: VIPPOOL等の登録制プールは『アカウント名.ワーカー名』を入力してください。アドレス直掘りプールはワーカー名単体でOKです。")
        lbl_pool_hint.setStyleSheet("color: #a5b4fc; font-size: 11px;")
        tab_pool_layout.addWidget(lbl_pool_hint, 2, 0, 1, 4)

        self.tabs_target.addTab(tab_pool, "🏊 プールマイニング (Stratum)")

        # Tab Solo
        tab_solo = QWidget()
        tab_solo_layout = QGridLayout(tab_solo)
        tab_solo_layout.setContentsMargins(8, 8, 8, 8)
        tab_solo_layout.setHorizontalSpacing(10)
        tab_solo_layout.setVerticalSpacing(8)

        tab_solo_layout.addWidget(QLabel("RPC Host:"), 0, 0)
        self.edit_solo_host = QLineEdit(self.config_mgr.get("solo_host", "127.0.0.1"))
        self.edit_solo_host.textChanged.connect(lambda t: self.config_mgr.set("solo_host", t.strip()))
        tab_solo_layout.addWidget(self.edit_solo_host, 0, 1)

        tab_solo_layout.addWidget(QLabel("RPC Port:"), 0, 2)
        self.spin_solo_port = QSpinBox()
        self.spin_solo_port.setRange(1, 65535)
        self.spin_solo_port.setValue(self.config_mgr.get("solo_port", 9402))
        self.spin_solo_port.valueChanged.connect(lambda v: self.config_mgr.set("solo_port", v))
        tab_solo_layout.addWidget(self.spin_solo_port, 0, 3)

        tab_solo_layout.addWidget(QLabel("RPC ユーザー名:"), 1, 0)
        self.edit_solo_user = QLineEdit(self.config_mgr.get("solo_user", "monacoinrpc"))
        self.edit_solo_user.textChanged.connect(lambda t: self.config_mgr.set("solo_user", t.strip()))
        tab_solo_layout.addWidget(self.edit_solo_user, 1, 1)

        tab_solo_layout.addWidget(QLabel("RPC パスワード:"), 1, 2)
        self.edit_solo_pass = QLineEdit(self.config_mgr.get("solo_pass", "rpcpassword"))
        self.edit_solo_pass.setEchoMode(QLineEdit.Password)
        self.edit_solo_pass.textChanged.connect(lambda t: self.config_mgr.set("solo_pass", t.strip()))
        tab_solo_layout.addWidget(self.edit_solo_pass, 1, 3)

        lbl_solo_hint = QLabel("💡 ヒント: Monacoin Core の monacoin.conf に server=1, rpcuser, rpcpassword, rpcport=9402 を設定して起動してください。")
        lbl_solo_hint.setStyleSheet("color: #a5b4fc; font-size: 11px;")
        tab_solo_layout.addWidget(lbl_solo_hint, 2, 0, 1, 4)

        # Solo Action Buttons (RPC test & Launch regtest testbed)
        solo_btn_row = QHBoxLayout()
        btn_test_rpc = QPushButton("🔍 ノード接続テスト (RPC Check)")
        btn_test_rpc.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; border-radius: 6px; padding: 6px 12px;")
        btn_test_rpc.setCursor(Qt.PointingHandCursor)
        btn_test_rpc.clicked.connect(self._test_solo_rpc_connection)
        solo_btn_row.addWidget(btn_test_rpc)

        btn_launch_regtest = QPushButton("⚡ 即座テスト環境起動 (Regtest ノード起動)")
        btn_launch_regtest.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; border-radius: 6px; padding: 6px 12px;")
        btn_launch_regtest.setCursor(Qt.PointingHandCursor)
        btn_launch_regtest.clicked.connect(self._launch_regtest_environment)
        solo_btn_row.addWidget(btn_launch_regtest)

        btn_solo_wallet = QPushButton("📜 ウォレット履歴 (残高確認)")
        btn_solo_wallet.setStyleSheet("background-color: #6366f1; color: white; font-weight: bold; border-radius: 6px; padding: 6px 12px;")
        btn_solo_wallet.setCursor(Qt.PointingHandCursor)
        btn_solo_wallet.clicked.connect(self._open_wallet_history_dialog)
        solo_btn_row.addWidget(btn_solo_wallet)

        tab_solo_layout.addLayout(solo_btn_row, 3, 0, 1, 4)

        self.tabs_target.addTab(tab_solo, "🏠 ソロマイニング (Monacoin Core RPC)")

        if self.config_mgr.get("mining_target", "pool") == "solo":
            self.tabs_target.setCurrentIndex(1)
        else:
            self.tabs_target.setCurrentIndex(0)
        self.tabs_target.currentChanged.connect(self._on_target_tab_changed)

        conn_layout.addWidget(self.tabs_target)

        # Options card (Simulator & External Miner)
        opt_card = QFrame()
        opt_card.setObjectName("card")
        opt_layout = QHBoxLayout(opt_card)
        opt_layout.setContentsMargins(10, 8, 10, 8)
        self.chk_simulator = QCheckBox("テスト・シミュレーションモード (実採掘を行わずUI・負荷のみ検証)")
        self.chk_simulator.setChecked(self.config_mgr.get("use_simulator", False))
        self.chk_simulator.toggled.connect(lambda v: self.config_mgr.set("use_simulator", v))
        opt_layout.addWidget(self.chk_simulator)

        btn_browse_miner = QPushButton("オプション: 外部マイナー指定 (ccminer / wildrig 等)...")
        btn_browse_miner.setStyleSheet("background-color: #334155; border: none; border-radius: 4px; padding: 4px 10px;")
        btn_browse_miner.clicked.connect(self._browse_custom_miner)
        opt_layout.addWidget(btn_browse_miner)
        conn_layout.addWidget(opt_card)
        conn_layout.addStretch()

        self.tabs_settings.addTab(tab_conn, "🏊 接続設定 (プール/ソロ)")

        # Sub-tab 2: 🤖 スマート・アイドル採掘
        tab_idle = QWidget()
        tab_idle_layout = QGridLayout(tab_idle)
        tab_idle_layout.setContentsMargins(12, 12, 12, 12)
        tab_idle_layout.setHorizontalSpacing(10)
        tab_idle_layout.setVerticalSpacing(12)

        self.chk_idle_enable = QCheckBox("離席時の自動採掘を有効化 (PC操作停止で自動スタート)")
        self.chk_idle_enable.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8;")
        self.chk_idle_enable.setChecked(self.config_mgr.get("idle_mining_enabled", False))
        self.chk_idle_enable.toggled.connect(self._on_idle_enable_toggled)
        tab_idle_layout.addWidget(self.chk_idle_enable, 0, 0, 1, 2)

        tab_idle_layout.addWidget(QLabel("放置判定時間:"), 1, 0)
        idle_row = QHBoxLayout()
        self.spin_idle_min = QSpinBox()
        self.spin_idle_min.setRange(1, 120)
        self.spin_idle_min.setValue(self.config_mgr.get("idle_mining_minutes", 5))
        self.spin_idle_min.valueChanged.connect(self._on_idle_min_changed)
        idle_row.addWidget(self.spin_idle_min)
        idle_row.addWidget(QLabel("分間放置で採掘開始 (キーボード・マウス操作再開で即停止)"))
        idle_row.addStretch()
        tab_idle_layout.addLayout(idle_row, 1, 1)

        tab_idle_layout.addWidget(QLabel("現在の状態:"), 2, 0)
        self.lbl_idle_state = QLabel("PC操作検知中 (アイドル待機)")
        self.lbl_idle_state.setStyleSheet("color: #38bdf8; font-weight: bold;")
        tab_idle_layout.addWidget(self.lbl_idle_state, 2, 1)

        lbl_idle_desc = QLabel("💡 作業やゲームの邪魔をせず、離席中や就寝中だけ自動でマイニングしたい場合に最適です。\nユーザーがマウスを動かしたりキーボードを触ると、わずか0.1秒で即座に採掘を一時中断します。")
        lbl_idle_desc.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.4;")
        tab_idle_layout.addWidget(lbl_idle_desc, 3, 0, 1, 2)
        tab_idle_layout.setRowStretch(4, 1)

        self.tabs_settings.addTab(tab_idle, "🤖 スマート・アイドル")

        # Sub-tab 3: 💰 収益性・電気代計算
        tab_profit = QWidget()
        tab_profit_layout = QGridLayout(tab_profit)
        tab_profit_layout.setContentsMargins(12, 12, 12, 12)
        tab_profit_layout.setHorizontalSpacing(10)
        tab_profit_layout.setVerticalSpacing(12)

        tab_profit_layout.addWidget(QLabel("電気料金単価 (円/kWh):"), 0, 0)
        self.spin_elec_rate = QDoubleSpinBox()
        self.spin_elec_rate.setRange(1.0, 100.0)
        self.spin_elec_rate.setSingleStep(0.5)
        self.spin_elec_rate.setValue(self.config_mgr.get("electricity_rate_yen", 31.0))
        self.spin_elec_rate.valueChanged.connect(self._on_elec_rate_changed)
        tab_profit_layout.addWidget(self.spin_elec_rate, 0, 1)

        tab_profit_layout.addWidget(QLabel("MONA参考価格 (円):"), 0, 2)
        self.spin_mona_price = QDoubleSpinBox()
        self.spin_mona_price.setRange(1.0, 10000.0)
        self.spin_mona_price.setValue(self.config_mgr.get("mona_jpy_price", 45.0))
        self.spin_mona_price.valueChanged.connect(self._on_mona_price_changed)
        tab_profit_layout.addWidget(self.spin_mona_price, 0, 3)

        self.lbl_profit_summary = QLabel("採掘稼働時にリアルタイムで電気代と推定純利益が計算されます。")
        self.lbl_profit_summary.setStyleSheet("color: #a7f3d0; font-size: 13px; font-weight: bold; background-color: #064e3b; border: 1px solid #059669; border-radius: 6px; padding: 10px;")
        self.lbl_profit_summary.setWordWrap(True)
        tab_profit_layout.addWidget(self.lbl_profit_summary, 1, 0, 1, 4)

        lbl_profit_desc = QLabel("💡 ご契約の電力会社（東京電力、関西電力等）の従量料金単価を入力することで、画面上部の「推定電気代」および損益シミュレーションが正確になります。")
        lbl_profit_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        tab_profit_layout.addWidget(lbl_profit_desc, 2, 0, 1, 4)
        tab_profit_layout.setRowStretch(3, 1)

        self.tabs_settings.addTab(tab_profit, "💰 収益性・電気代")

        # Sub-tab 4: 🌐 遠隔監視・通知
        tab_remote = QWidget()
        tab_remote_layout = QGridLayout(tab_remote)
        tab_remote_layout.setContentsMargins(12, 12, 12, 12)
        tab_remote_layout.setHorizontalSpacing(10)
        tab_remote_layout.setVerticalSpacing(12)

        self.chk_web_enable = QCheckBox("スマホ対応 内蔵Webダッシュボードを起動 (LAN内ブラウザ閲覧)")
        self.chk_web_enable.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8;")
        self.chk_web_enable.setChecked(self.config_mgr.get("web_dashboard_enabled", True))
        self.chk_web_enable.toggled.connect(self._on_web_server_toggled)
        tab_remote_layout.addWidget(self.chk_web_enable, 0, 0, 1, 2)

        tab_remote_layout.addWidget(QLabel("Webポート:"), 1, 0)
        web_port_row = QHBoxLayout()
        self.spin_web_port = QSpinBox()
        self.spin_web_port.setRange(1024, 65535)
        self.spin_web_port.setValue(self.config_mgr.get("web_dashboard_port", 8888))
        self.spin_web_port.valueChanged.connect(lambda v: self.config_mgr.set("web_dashboard_port", v))
        web_port_row.addWidget(self.spin_web_port)

        btn_open_browser = QPushButton("🌐 ブラウザでダッシュボードを開く")
        btn_open_browser.setStyleSheet("background-color: #2563eb; color: white; border-radius: 4px; padding: 4px 10px; font-weight: bold;")
        btn_open_browser.setCursor(Qt.PointingHandCursor)
        btn_open_browser.clicked.connect(self._open_web_dashboard)
        web_port_row.addWidget(btn_open_browser)
        web_port_row.addStretch()
        tab_remote_layout.addLayout(web_port_row, 1, 1, 1, 3)

        tab_remote_layout.addWidget(QLabel("Discord Webhook URL:"), 2, 0)
        self.edit_discord = QLineEdit(self.config_mgr.get("discord_webhook_url", ""))
        self.edit_discord.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.edit_discord.textChanged.connect(self._on_discord_url_changed)
        tab_remote_layout.addWidget(self.edit_discord, 2, 1, 1, 2)

        btn_test_discord = QPushButton("🔔 テスト送信")
        btn_test_discord.setStyleSheet("background-color: #4f46e5; color: white; border-radius: 4px; padding: 4px 10px;")
        btn_test_discord.clicked.connect(self._test_discord_notification)
        tab_remote_layout.addWidget(btn_test_discord, 2, 3)

        lbl_remote_desc = QLabel("💡 外出先やベッドからスマホで稼働状況・温度・ハッシュレートを確認可能。Discord Webhook を登録すると採掘開始/停止やエラー発生時に自動通知されます。")
        lbl_remote_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        tab_remote_layout.addWidget(lbl_remote_desc, 3, 0, 1, 4)
        tab_remote_layout.setRowStretch(4, 1)

        self.tabs_settings.addTab(tab_remote, "🌐 遠隔監視・通知")

        # Sub-tab 5: 🔧 GPUハードウェア (Multi-GPU)
        tab_hw = QWidget()
        tab_hw_layout = QGridLayout(tab_hw)
        tab_hw_layout.setContentsMargins(12, 12, 12, 12)
        tab_hw_layout.setHorizontalSpacing(10)
        tab_hw_layout.setVerticalSpacing(10)

        tab_hw_layout.addWidget(QLabel("検出された OpenCL GPU デバイス (Multi-GPU 同時採掘):"), 0, 0, 1, 4)
        self.list_gpus = QListWidget()
        self.list_gpus.setStyleSheet("background-color: #0f172a; border: 1px solid #334155; border-radius: 4px; color: #f8fafc;")
        self.list_gpus.setFixedHeight(85)
        self._populate_gpu_list()
        tab_hw_layout.addWidget(self.list_gpus, 1, 0, 1, 4)

        tab_hw_layout.addWidget(QLabel("GPU 電力リミット (W):"), 2, 0)
        self.spin_power_limit = QSpinBox()
        self.spin_power_limit.setRange(0, 800)
        self.spin_power_limit.setValue(self.config_mgr.get("power_limit_watts", 0))
        self.spin_power_limit.setSpecialValueText("自動 (制限なし)")
        tab_hw_layout.addWidget(self.spin_power_limit, 2, 1)

        tab_hw_layout.addWidget(QLabel("目標ファン速度 (%):"), 2, 2)
        self.spin_fan_speed = QSpinBox()
        self.spin_fan_speed.setRange(0, 100)
        self.spin_fan_speed.setValue(self.config_mgr.get("target_fan_percent", 0))
        self.spin_fan_speed.setSpecialValueText("自動 (VBIOS制御)")
        tab_hw_layout.addWidget(self.spin_fan_speed, 2, 3)

        btn_apply_hw = QPushButton("⚡ ハードウェア設定 (電力・ファン) を即時適用")
        btn_apply_hw.setStyleSheet("background-color: #059669; color: white; border-radius: 4px; padding: 7px; font-weight: bold;")
        btn_apply_hw.setCursor(Qt.PointingHandCursor)
        btn_apply_hw.clicked.connect(self._apply_gpu_hardware_settings)
        tab_hw_layout.addWidget(btn_apply_hw, 3, 0, 1, 4)

        lbl_hw_desc = QLabel("💡 複数GPUを搭載しているPCでは、チェックを入れたすべてのGPUで並列採掘が行われます。\n※ NVML電力リミット設定には管理者権限が必要です。")
        lbl_hw_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        tab_hw_layout.addWidget(lbl_hw_desc, 4, 0, 1, 4)

        btn_bench = QPushButton("📊 ベンチマーク実行 (GPU・CPUの実測ハッシュレートを計測 / 約10秒)")
        btn_bench.setStyleSheet("background-color: #2563eb; color: white; border-radius: 4px; padding: 7px; font-weight: bold;")
        btn_bench.setCursor(Qt.PointingHandCursor)
        btn_bench.clicked.connect(self._run_benchmark)
        self.btn_bench = btn_bench
        tab_hw_layout.addWidget(btn_bench, 5, 0, 1, 4)
        self.lbl_bench = QLabel(self._benchmark_text())
        self.lbl_bench.setWordWrap(True)
        self.lbl_bench.setStyleSheet("color: #a7f3d0; font-size: 12px;")
        tab_hw_layout.addWidget(self.lbl_bench, 6, 0, 1, 4)
        tab_hw_layout.setRowStretch(7, 1)

        self.tabs_settings.addTab(tab_hw, "🔧 ハードウェア制御 (Multi-GPU)")

        adv_layout.addWidget(self.tabs_settings)
        self.tabs_main.addTab(tab_advanced, "⚙️ 詳細設定・高度なツール")

        main_layout.addWidget(self.tabs_main)

        # Initial validation & target summary
        self._validate_address_input(self.edit_address.text())
        self._update_target_summary()

    def _connect_signals(self):
        self.miner_ctrl.status_changed.connect(self._on_miner_status_changed)
        self.miner_ctrl.hashrate_changed.connect(self._on_hashrate_changed)
        self.miner_ctrl.shares_changed.connect(self._on_shares_changed)
        self.miner_ctrl.log_received.connect(self.console.append_log)

    def _on_device_changed(self, button):
        if self.btn_dev_cpu.isChecked():
            dev = "cpu"
        elif self.btn_dev_hybrid.isChecked():
            dev = "hybrid"
        else:
            dev = "gpu"
        self.device_target = dev
        self.config_mgr.set("device_target", dev)
        self.console.append_log(f"マイニングデバイスを [{dev.upper()}] に変更しました。", "info")

    def _on_target_tab_changed(self, index: int):
        target = "solo" if index == 1 else "pool"
        self.target_type = target
        self.config_mgr.set("mining_target", target)
        if target == "solo":
            self.card_shares.lbl_title.setText("発見ブロック数")
            self.console.append_log("マイニングターゲットを [ソロマイニング (Monacoin Core RPC)] に設定しました。", "info")
        else:
            self.card_shares.lbl_title.setText("承認シェア数")
            self.console.append_log("マイニングターゲットを [プールマイニング (Stratum)] に設定しました。", "info")
        self._update_target_summary()

    def _on_mode_selected(self, mode_key: str):
        self.current_mode = mode_key
        self.config_mgr.set("miner_mode", mode_key)
        self._highlight_mode(mode_key)

        recs = self.hw_mgr.get_mode_recommendation()
        mode_data = recs["modes"].get(mode_key, recs["modes"]["eco"])
        target_threads = mode_data.get("cpu_threads", 16)
        self.spin_threads.setValue(target_threads)

        self.console.append_log(
            f"プロファイルを [{mode_key.upper()}] に変更しました (GPU: {mode_data['target_pwr_w']:.0f}W / CPU: {target_threads}T)。",
            "info"
        )

    def _highlight_mode(self, active_key: str):
        for key, card in self.mode_cards.items():
            card.setChecked(key == active_key)

    def _on_pool_changed(self, index: int):
        self.config_mgr.set("pool_index", index)
        if hasattr(self, "edit_custom_pool"):
            self.edit_custom_pool.setEnabled(index == 2)
        self._update_target_summary()

    def _on_custom_pool_changed(self, text: str):
        self.config_mgr.set("custom_pool_url", text.strip())
        self._update_target_summary()

    def _on_worker_changed(self, text: str):
        self.config_mgr.set("worker_name", text.strip())
        self._update_target_summary()

    def _update_target_summary(self):
        if not hasattr(self, "lbl_current_target_summary"):
            return
        if self.target_type == "solo":
            host = self.config_mgr.get("solo_host", "127.0.0.1")
            port = self.config_mgr.get("solo_port", 9402)
            self.lbl_current_target_summary.setText(f"📍 接続先: ソロマイニング (Monacoin Core RPC: {host}:{port})")
        else:
            p_idx = self.combo_pool.currentIndex() if hasattr(self, "combo_pool") else 0
            if p_idx == 2:
                url = self.edit_custom_pool.text().strip() if hasattr(self, "edit_custom_pool") else ""
                pool_name = f"カスタム ({url or '未設定'})"
            else:
                pool_name = self.combo_pool.currentText() if hasattr(self, "combo_pool") else "VIPPOOL"
            worker = self.edit_worker.text().strip() if hasattr(self, "edit_worker") else "worker1"
            self.lbl_current_target_summary.setText(f"📍 接続先: {pool_name} ｜ ワーカー: {worker or '未設定'}")

    def _validate_address_input(self, text: str):
        self.config_mgr.set("wallet_address", text.strip())
        valid, msg = validate_mona_address(text)
        if valid:
            self.lbl_addr_status.setText(f"✓ {msg}")
            self.lbl_addr_status.setStyleSheet("color: #34d399; font-size: 11px;")
        else:
            self.lbl_addr_status.setText(f"⚠ {msg}")
            self.lbl_addr_status.setStyleSheet("color: #fbbf24; font-size: 11px;")

    def _browse_custom_miner(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "外部マイナー実行ファイルを選択 (ccminer / wildrig 等)", "", "Executable (*.exe);;All Files (*.*)"
        )
        if path:
            self.config_mgr.set("custom_miner_path", path)
            self.config_mgr.set("use_simulator", False)
            self.chk_simulator.setChecked(False)
            self.console.append_log(f"外部マイナー設定: {path}", "info")
            QMessageBox.information(self, "設定完了", f"外部マイナーを設定しました:\n{path}")

    def _setup_services(self):
        # Idle Tracker signals
        self.idle_tracker.idle_changed.connect(self._on_idle_changed)
        self.idle_tracker.idle_seconds_updated.connect(self._on_idle_seconds_updated)
        if self.config_mgr.get("idle_mining_enabled", False):
            self.idle_tracker.start()

        # Web Monitoring Server
        if self.config_mgr.get("web_dashboard_enabled", True):
            self._start_web_server()

    def _start_web_server(self):
        port = self.config_mgr.get("web_dashboard_port", 8888)
        self.web_server.port = port
        try:
            self.web_server.start(
                get_status_fn=self._get_web_status,
                start_fn=self._remote_start_mining,
                stop_fn=self._remote_stop_mining
            )
            self.console.append_log(f"🌐 Web監視ダッシュボード起動完了: http://localhost:{port}", "info")
        except Exception as e:
            self.console.append_log(f"Web監視サーバー起動エラー: {e}", "warn")

    def _on_web_server_toggled(self, checked: bool):
        self.config_mgr.set("web_dashboard_enabled", checked)
        if checked:
            self._start_web_server()
        else:
            self.web_server.stop()
            self.console.append_log("Web監視サーバーを停止しました。", "info")

    def _open_web_dashboard(self):
        port = self.config_mgr.get("web_dashboard_port", 8888)
        webbrowser.open(f"http://localhost:{port}")

    def _on_idle_enable_toggled(self, checked: bool):
        self.config_mgr.set("idle_mining_enabled", checked)
        if checked:
            self.idle_tracker.start()
            self.console.append_log("🤖 スマート・アイドル自動採掘を有効化しました。", "info")
        else:
            self.idle_tracker.stop()
            self.lbl_idle_state.setText("機能無効 (手動マイニングのみ)")
            self.lbl_idle_state.setStyleSheet("color: #94a3b8;")
            self.console.append_log("スマート・アイドル自動採掘を無効化しました。", "info")

    def _on_idle_min_changed(self, val: int):
        self.config_mgr.set("idle_mining_minutes", val)
        self.idle_tracker.set_threshold_minutes(val)

    def _on_idle_changed(self, is_idle: bool):
        if is_idle and not self.miner_ctrl.is_mining:
            self.auto_started_by_idle = True
            self.console.append_log("💤 PCアイドルを検知: スマート自動マイニングを開始しました。", "success")
            self._toggle_mining()
        elif not is_idle and self.miner_ctrl.is_mining and self.auto_started_by_idle:
            self.auto_started_by_idle = False
            self.console.append_log("⚡ PC操作を検知: スマート自動マイニングを一時停止しました。", "warn")
            self._toggle_mining()

    def _on_idle_seconds_updated(self, sec: int):
        if not self.config_mgr.get("idle_mining_enabled", False):
            return
        threshold = self.idle_tracker.idle_threshold_seconds
        if sec >= threshold:
            self.lbl_idle_state.setText(f"💤 放置中 ({sec}秒経過) - 自動採掘稼働中")
            self.lbl_idle_state.setStyleSheet("color: #34d399; font-weight: bold;")
        else:
            remaining = threshold - sec
            self.lbl_idle_state.setText(f"● ユーザー操作検知中 (残り {remaining}秒 で自動採掘開始)")
            self.lbl_idle_state.setStyleSheet("color: #38bdf8; font-weight: bold;")

    def _on_elec_rate_changed(self, val: float):
        self.config_mgr.set("electricity_rate_yen", val)
        self.profit_calc.electricity_rate_yen = val

    def _on_mona_price_changed(self, val: float):
        self.config_mgr.set("mona_jpy_price", val)
        self.profit_calc.mona_jpy_price = val

    def _on_discord_url_changed(self, url: str):
        self.config_mgr.set("discord_webhook_url", url.strip())
        self.discord_notifier.set_webhook_url(url.strip())

    def _test_discord_notification(self):
        url = self.edit_discord.text().strip()
        if not url:
            QMessageBox.warning(self, "エラー", "Discord Webhook URL を入力してください。")
            return
        self.discord_notifier.set_webhook_url(url)
        self.discord_notifier.send_embed(
            title="🔔 MonaMinerRTX 接続テスト",
            description="Discord Webhook への接続に成功しました！採掘通知を受信できます。",
            color=0x38BDF8,
            fields=[
                {"name": "バージョン", "value": "v2.1.1", "inline": True},
                {"name": "ステータス", "value": "Ready", "inline": True}
            ]
        )
        self.console.append_log("Discord へテスト通知を送信しました。", "info")

    def _populate_gpu_list(self):
        self.list_gpus.clear()
        saved_indices = self.config_mgr.get("selected_gpu_indices", [0])
        try:
            devs = OpenCLBackend.get_all_gpu_devices()
            if not devs:
                item = QListWidgetItem("利用可能な OpenCL GPU が検出されませんでした")
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                self.list_gpus.addItem(item)
                return

            for d in devs:
                idx = d["global_index"]
                label = f"GPU #{idx}: {d['name']} ({d['platform_name']} - VRAM {d['global_mem_gb']}GB)"
                item = QListWidgetItem(label)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                check_state = Qt.Checked if (idx in saved_indices or len(devs) == 1) else Qt.Unchecked
                item.setCheckState(check_state)
                item.setData(Qt.UserRole, idx)
                self.list_gpus.addItem(item)
        except Exception as e:
            item = QListWidgetItem(f"デバイス列挙エラー: {e}")
            self.list_gpus.addItem(item)

    def _get_selected_gpu_indices(self) -> list:
        indices = []
        for i in range(self.list_gpus.count()):
            item = self.list_gpus.item(i)
            if item.checkState() == Qt.Checked:
                idx = item.data(Qt.UserRole)
                if idx is not None:
                    indices.append(idx)
        if not indices:
            indices = [0]
        self.config_mgr.set("selected_gpu_indices", indices)
        return indices

    def _apply_gpu_hardware_settings(self):
        pwr = self.spin_power_limit.value()
        fan = self.spin_fan_speed.value()
        self.config_mgr.set("power_limit_watts", pwr)
        self.config_mgr.set("target_fan_percent", fan)

        if not self.gpu_ctrl.is_available:
            QMessageBox.information(self, "ハードウェア制御", "NVML が利用できない環境です (AMD GPU またはドライバ未検出)。")
            return

        msg_list = []
        if pwr > 0:
            ok, msg = self.gpu_ctrl.set_power_limit(0, pwr)
            msg_list.append(f"電力リミット: {msg}")
        if fan > 0:
            ok, msg = self.gpu_ctrl.set_fan_speed(0, fan)
            msg_list.append(f"ファン制御: {msg}")

        result_txt = "\n".join(msg_list) if msg_list else "自動制御に設定されています。"
        self.console.append_log(f"[HW制御] {result_txt}", "info")
        QMessageBox.information(self, "設定結果", result_txt)

    def _benchmark_text(self) -> str:
        m = self.hw_mgr.measured
        if not m.get("gpu_mhs") and not m.get("cpu_mhs_per_thread"):
            return "未測定です。ボタンを押すと、この PC の実際のハッシュレートを計測して「予想」表示に反映します。"
        parts = []
        if m.get("gpu_mhs"):
            parts.append(f"GPU: {m['gpu_mhs']:.1f} MH/s")
        if m.get("cpu_mhs_per_thread"):
            parts.append(f"CPU: {m['cpu_mhs_per_thread']:.2f} MH/s / スレッド")
        return "実測値 → " + " ｜ ".join(parts)

    def _run_benchmark(self):
        if self.miner_ctrl.is_mining:
            QMessageBox.information(self, "ベンチマーク", "採掘中は実行できません。採掘を停止してから実行してください。")
            return
        if self._benchmark_worker and self._benchmark_worker.isRunning():
            return
        self.btn_bench.setEnabled(False)
        self.lbl_bench.setText("計測中... (GPU 約3秒 + CPU 約2秒)")
        self._benchmark_worker = BenchmarkWorker(self.spin_threads.value())
        self._benchmark_worker.progress.connect(self.lbl_bench.setText)
        self._benchmark_worker.result.connect(self._on_benchmark_result)
        self._benchmark_worker.start()

    def _on_benchmark_result(self, res: dict):
        self.btn_bench.setEnabled(True)
        self.hw_mgr.set_measured(res.get("gpu_mhs"), res.get("cpu_mhs_per_thread"))
        self.config_mgr.set("benchmark", {k: v for k, v in res.items() if not k.endswith("_error")})
        modes = self.hw_mgr.get_mode_recommendation()["modes"]
        for key, card in self.mode_cards.items():
            card.set_est_hashrate(modes[key]["est_hashrate"])
        text = self._benchmark_text()
        errors = [res[k] for k in ("gpu_error", "cpu_error") if k in res]
        if errors:
            text += "  ⚠ " + " / ".join(errors)
        self.lbl_bench.setText(text)
        self.console.append_log(f"ベンチマーク完了: {self._benchmark_text()}", "info")

    def _get_web_status(self) -> dict:
        """Called from the HTTP server thread: only returns the snapshot built on the GUI thread."""
        return self._web_snapshot

    def _build_web_status(self) -> dict:
        m = self.hw_mgr.get_live_metrics()
        hr_val = float(self.card_hashrate.lbl_val.text().replace(" MH/s", "") or "0.0")
        pwr_val = float(self.card_power.lbl_val.text().replace(" W", "") or "0.0")
        calc = self.profit_calc.calculate(hr_val, pwr_val)

        gpu_info = self.gpu_ctrl.get_device_info(0) if self.gpu_ctrl.is_available else {}
        temp_val = gpu_info.get("temp_c", m.get("temp_c", 0))
        fan_val = gpu_info.get("fan_percent", 0)

        # Uptime string
        uptime_str = "00:00:00"
        if self.mining_start_time and self.miner_ctrl.is_mining:
            sec = int(time.time() - self.mining_start_time)
            hrs = sec // 3600
            mins = (sec % 3600) // 60
            secs = sec % 60
            uptime_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        shares_txt = self.card_shares.lbl_val.text()
        accepted = 0
        rejected = 0
        try:
            if "/" in shares_txt:  # pool: "accepted / total"
                parts = shares_txt.split("/")
                accepted = int(parts[0].strip())
                rejected = max(0, int(parts[1].strip()) - accepted)
            else:  # solo: "N blocks"
                accepted = int(shares_txt.split()[0])
        except (ValueError, IndexError):
            pass

        # Logs
        logs = []
        if hasattr(self, 'console') and hasattr(self.console, 'text_edit'):
            plain = self.console.text_edit.toPlainText()
            lines = plain.strip().split("\n")
            logs = lines[-12:]

        return {
            "is_mining": self.miner_ctrl.is_mining,
            "hashrate_mhs": hr_val,
            "power_w": pwr_val,
            "watt_per_mh": calc.get("watt_per_mh", 0.0),
            "temp_c": temp_val,
            "fan_percent": fan_val,
            "accepted_shares": accepted,
            "rejected_shares": rejected,
            "hourly_cost_yen": calc.get("hourly_cost_yen", 0.0),
            "daily_cost_yen": calc.get("daily_cost_yen", 0.0),
            "uptime_str": uptime_str,
            "recent_logs": logs
        }

    def _remote_start_mining(self):
        self.remote_toggle.emit(True)

    def _remote_stop_mining(self):
        self.remote_toggle.emit(False)

    def _on_remote_toggle(self, start: bool):
        if start != self.miner_ctrl.is_mining:
            self._toggle_mining()

    def _toggle_mining(self):
        if self.miner_ctrl.is_mining:
            self.miner_ctrl.stop_mining()
            self.mining_start_time = None
            if self.discord_notifier.enabled:
                self.discord_notifier.send_embed(
                    title="⏹ マイニング停止",
                    description="マイニングプロセスが停止しました。",
                    color=0xEF4444
                )
        else:
            addr = self.edit_address.text().strip()
            valid, msg = validate_mona_address(addr)
            if not valid:
                if self.auto_started_by_idle:
                    self.console.append_log("⚠ 受取アドレスが未入力または不正なため、スマート・アイドル自動採掘を保留しました。", "warn")
                    self.auto_started_by_idle = False
                    return
                reply = QMessageBox.warning(
                    self, "アドレス確認",
                    f"入力されたモナコインアドレスに警告があります:\n{msg}\n\nこのままテスト採掘を続行しますか？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return

            target_type = self.target_type
            dev = self.device_target
            if self.combo_pool.currentIndex() == 2:
                custom_url = self.edit_custom_pool.text().strip()
                if not custom_url:
                    QMessageBox.warning(self, "入力エラー", "カスタムプールのURL (stratum+tcp://host:port) を入力してください。")
                    return
                pool_url = custom_url
            else:
                pool_url = self.combo_pool.currentData() or "stratum+tcp://stratum1.vippool.net:8888"
            worker = self.edit_worker.text().strip() or "worker1"
            pool_pass = self.edit_pool_pass.text().strip() or "x"
            solo_host = self.edit_solo_host.text().strip() or "127.0.0.1"
            solo_port = self.spin_solo_port.value()
            solo_user = self.edit_solo_user.text().strip()
            solo_pass = self.edit_solo_pass.text()
            cpu_threads = self.spin_threads.value()

            use_sim = self.chk_simulator.isChecked()
            custom_path = self.config_mgr.get("custom_miner_path", "")

            # If custom miner path is specified, validate compatibility
            if not use_sim and custom_path and os.path.exists(custom_path):
                is_amd = self.hw_mgr.device_info.get("is_amd", False)
                if is_amd and "ccminer" in os.path.basename(custom_path).lower():
                    reply = QMessageBox.warning(
                        self, "AMD GPU 互換性警告",
                        "指定された外部マイナーは 'ccminer' (NVIDIA CUDA専用) の可能性があります。\n"
                        "AMD Radeon GPU で外部マイナーを使用する場合は OpenCL 対応マイナー (wildrig / sgminer等) を指定するか、指定をクリアして内蔵独自マイナーをご利用ください。\n\n"
                        "このまま実行を試みますか？",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.No:
                        return
            elif not use_sim:
                self.console.append_log("⚡ 独自内蔵 OpenCL マイナーエンジン (GPU直結 Multi-GPU) で採掘を開始します。", "info")

            mode = self.current_mode
            if mode == "auto":
                mode = self.hw_mgr.get_mode_recommendation()["recommended_key"]

            selected_gpus = self._get_selected_gpu_indices()

            self.mining_start_time = time.time()

            self.miner_ctrl.start_mining(
                mode=mode,
                target_type=target_type,
                device_target=dev,
                pool_url=pool_url,
                wallet=addr,
                worker=worker,
                solo_host=solo_host,
                solo_port=solo_port,
                solo_user=solo_user,
                solo_pass=solo_pass,
                cpu_threads=cpu_threads,
                custom_path=custom_path,
                use_sim=use_sim,
                selected_gpu_indices=selected_gpus,
                pool_password=pool_pass
            )

            if self.discord_notifier.enabled:
                self.discord_notifier.send_embed(
                    title="🚀 マイニング開始",
                    description=f"モナコインの採掘を開始しました ({target_type.upper()})",
                    color=0x22C55E,
                    fields=[
                        {"name": "ターゲット", "value": pool_url if target_type == "pool" else f"{solo_host}:{solo_port}", "inline": False},
                        {"name": "プロファイル", "value": mode.upper(), "inline": True},
                        {"name": "GPU台数", "value": f"{len(selected_gpus)} 台", "inline": True}
                    ]
                )

    def _update_hardware_telemetry(self):
        m = self.hw_mgr.get_live_metrics()
        gpu_info = self.gpu_ctrl.get_device_info(0) if self.gpu_ctrl.is_available else {}
        temp_val = gpu_info.get("temp_c", m.get("temp_c", 0))
        fan_val = gpu_info.get("fan_percent", 0)

        self.card_gpu_temp.set_value(f"{temp_val} / {fan_val}")
        
        # Calculate live electricity cost
        pwr = m.get("power_w", 0.0)
        if not self.miner_ctrl.is_mining:
            self.card_power.set_value(f"{pwr:.1f}")
        else:
            pwr = float(self.card_power.lbl_val.text().replace(" W", "") or "0.0")

        hr = float(self.card_hashrate.lbl_val.text().replace(" MH/s", "") or "0.0")
        calc = self.profit_calc.calculate(hr, pwr)
        self.card_cost.set_value(f"¥{calc['daily_cost_yen']:.0f}")

        if calc["watt_per_mh"] > 0:
            self.card_eff.set_value(f"{calc['watt_per_mh']:.3f}")
        else:
            self.card_eff.set_value("--")

        self._web_snapshot = self._build_web_status()

        # Update profit tab summary
        if self.miner_ctrl.is_mining and hr > 0:
            self.lbl_profit_summary.setText(
                f"【試算結果】 1時間電気代: ¥{calc['hourly_cost_yen']:.1f} / 24時間: ¥{calc['daily_cost_yen']:.0f} / "
                f"月間: ¥{calc['monthly_cost_yen']:.0f} ｜ 推定日収: {calc['est_daily_mona']:.3f} MONA (約¥{calc['est_daily_revenue_yen']:.0f}) ｜ "
                f"推定純利益: ¥{calc['est_daily_profit_yen']:.0f}/日"
            )

    def _on_miner_status_changed(self, status: str):
        self.setWindowTitle(f"MonaMiner RTX / RX v2.1.1 - [{status}]")
        if not self.miner_ctrl.is_mining:
            self.btn_toggle_mining.setObjectName("start_btn")
            self.btn_toggle_mining.setText("🚀 採掘開始 (Start Mining)")
            self.btn_toggle_mining.setStyle(self.btn_toggle_mining.style())
            self.card_hashrate.set_value("0.0")
            self.card_eff.set_value("--")
            self.card_cost.set_value("¥0")
        else:
            self.btn_toggle_mining.setObjectName("stop_btn")
            self.btn_toggle_mining.setText("⏹ 採掘停止 (Stop Mining)")
            self.btn_toggle_mining.setStyle(self.btn_toggle_mining.style())

    def _on_hashrate_changed(self, hr: float, pwr: float, eff: float):
        self.card_hashrate.set_value(f"{hr:.1f}")
        self.card_power.set_value(f"{pwr:.1f}")
        calc = self.profit_calc.calculate(hr, pwr)
        self.card_cost.set_value(f"¥{calc['daily_cost_yen']:.0f}")
        self.card_eff.set_value(f"{calc['watt_per_mh']:.3f}" if calc['watt_per_mh'] > 0 else "--")

    def _on_shares_changed(self, accepted: int, rejected: int):
        if self.target_type == "solo":
            self.card_shares.set_value(f"{accepted} blocks")
        else:
            self.card_shares.set_value(f"{accepted} / {accepted + rejected}")

    def _test_solo_rpc_connection(self):
        from app.miner.rpc_solo_client import RpcSoloClient
        host = self.edit_solo_host.text().strip() or "127.0.0.1"
        port = self.spin_solo_port.value()
        user = self.edit_solo_user.text().strip()
        pwd = self.edit_solo_pass.text()

        self.console.append_log(f"🔍 Monacoin Core RPC 接続テスト中: http://{host}:{port}...", "info")
        client = RpcSoloClient(host=host, port=port, user=user, password=pwd)
        ok, msg, info = client.test_connection()
        if ok:
            self.console.append_log(f"✓ {msg}", "success")
            QMessageBox.information(
                self, "RPC 接続成功",
                f"Monacoin Core ノードへの接続を確認しました！\n\n{msg}\n\nソロマイニングの準備が整っています。"
            )
        else:
            self.console.append_log(f"✗ {msg}", "error")
            QMessageBox.warning(
                self, "RPC 接続失敗",
                f"Monacoin Core ノードへの接続に失敗しました:\n\n{msg}\n\n"
                "・Monacoin Core が起動しているか確認してください。\n"
                "・monacoin.conf に server=1, rpcuser, rpcpassword, rpcport が正しく設定されているか確認してください。"
            )

    def _launch_regtest_environment(self):
        bat_path = os.path.join(_app_root(), "node", "start_regtest_solo.bat")
        if not os.path.exists(bat_path):
            QMessageBox.warning(self, "エラー", f"起動スクリプトが見つかりません:\n{bat_path}")
            return
        if self._node_rpc_in_use("Regtest 環境"):
            return

        try:
            _launch_bat_in_new_window(bat_path)
            self.console.append_log("⚡ 即座テスト用 Regtest ソロマイニング環境の別ウィンドウ起動を要求しました。", "info")
            QMessageBox.information(
                self, "Regtest 環境起動",
                "即時テスト用のローカル Regtest ノードクラスタを別ウィンドウで起動しました。\n\n"
                "1. 黒いコンソール画面で『GPU ソロマイニング待機状態に入りました！』と表示されるまで約5秒お待ちください。\n"
                "2. その後、本アプリの『採掘開始』ボタンを押すと、RTX 5080等で即座にブロック発見・報酬獲得テストが行えます。"
            )
        except Exception as e:
            QMessageBox.warning(self, "起動エラー", f"Regtest 環境の起動に失敗しました: {e}")

    def _open_wallet_history_dialog(self):
        from app.ui.wallet_dialog import WalletHistoryDialog
        addr = self.edit_address.text().strip()
        if not addr:
            addr = self.config_mgr.get("wallet_address", "").strip()

        if not addr:
            QMessageBox.warning(
                self, "アドレス未入力",
                "モナコイン受取アドレスが入力されていません。\n"
                "入力欄にご自身のモナコインアドレスを入力してからボタンを押してください。"
            )
            return

        for old in self.findChildren(WalletHistoryDialog):
            if not (old.worker and old.worker.isRunning()):
                old.deleteLater()
        dlg = WalletHistoryDialog(addr, self)
        dlg.exec()

    def _manual_refresh_node_sync(self):
        self.btn_sync_refresh.setEnabled(False)
        self.lbl_sync_badge.setText("⏳ 問い合わせ中...")
        self._check_node_sync_async()
        QTimer.singleShot(1500, lambda: self.btn_sync_refresh.setEnabled(True))

    def _check_node_sync_async(self):
        if self._node_worker is not None and self._node_worker.isRunning():
            return

        host = self.config_mgr.get("solo_host", "127.0.0.1")
        port = self.config_mgr.get("solo_port", 9402)
        user = self.config_mgr.get("solo_user", "monacoinrpc")
        passwd = self.config_mgr.get("solo_pass", "rpcpassword")

        self._node_worker = NodeSyncWorker(host, port, user, passwd)
        self._node_worker.sync_result.connect(self._on_node_sync_updated)
        self._node_worker.start()

    def _on_node_sync_updated(self, info: dict):
        self._last_node_info = info
        is_running = info.get("is_running", False)
        is_loading = info.get("is_loading", False)
        blocks = info.get("blocks", 0)
        headers = info.get("headers", 0)
        prog = info.get("progress", 0.0)
        ibd = info.get("ibd", False)
        chain = info.get("chain", "")

        if not is_running:
            self.lbl_sync_badge.setText("⏹ ノード停止中")
            self.lbl_sync_badge.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 4px; background-color: #334155; color: #94a3b8;")
            self.lbl_net_best_block.setText("🌐 ネットワーク最新: --")
            self.lbl_local_held_block.setText("💻 このPCの所持ブロック: 未接続")
            self.lbl_sync_detail.setText("ノード未起動 (「⚡ 本番ノード起動」で起動できます)")
            self.lbl_sync_detail.setStyleSheet("font-size: 12px; color: #94a3b8;")
            self.progress_sync.setValue(0)
            self.progress_sync.setFormat("ノード未起動")
        elif info.get("auth_error"):
            self.lbl_sync_badge.setText("⚠ RPC 認証エラー")
            self.lbl_sync_badge.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 4px; background-color: #b91c1c; color: white;")
            self.lbl_net_best_block.setText("🌐 ネットワーク最新: --")
            self.lbl_local_held_block.setText("💻 このPCの所持ブロック: 取得不可")
            self.lbl_sync_detail.setText("ノードは稼働中ですが RPC ユーザー名/パスワードが一致しません (ソロマイニング設定を確認)")
            self.lbl_sync_detail.setStyleSheet("font-size: 12px; color: #f87171;")
            self.progress_sync.setValue(0)
            self.progress_sync.setFormat("RPC 認証エラー")
        elif is_loading:
            self.lbl_sync_badge.setText("⏳ 初期化中...")
            self.lbl_sync_badge.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 4px; background-color: #d97706; color: white;")
            self.lbl_net_best_block.setText("🌐 ネットワーク最新: 読込中")
            self.lbl_local_held_block.setText("💻 このPCの所持ブロック: インデックス読込中")
            self.lbl_sync_detail.setText("LevelDBインデックス読込中...")
            self.lbl_sync_detail.setStyleSheet("font-size: 12px; color: #fbbf24;")
            self.progress_sync.setValue(0)
            self.progress_sync.setFormat("インデックス読込中")
        elif ibd:
            self.lbl_sync_badge.setText(f"⏳ 同期検証中 ({chain.upper()})")
            self.lbl_sync_badge.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 4px; background-color: #d97706; color: white;")
            self.lbl_net_best_block.setText(f"🌐 ネットワーク最新: {headers:,}")
            self.lbl_local_held_block.setText(f"💻 このPCの所持ブロック: {blocks:,}")
            remaining = max(0, headers - blocks)
            self.lbl_sync_detail.setText(f"残り: {remaining:,} ブロック")
            self.lbl_sync_detail.setStyleSheet("font-size: 12px; color: #fbbf24; font-weight: bold;")
            self.progress_sync.setValue(int(prog * 10))
            self.progress_sync.setFormat(f"検証進捗: {prog:.1f}% ({blocks:,} / {headers:,})")
        else:
            self.lbl_sync_badge.setText(f"✅ 同期完了 ({chain.upper()})")
            self.lbl_sync_badge.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 4px; background-color: #059669; color: white;")
            self.lbl_net_best_block.setText(f"🌐 ネットワーク最新: {headers:,}")
            self.lbl_local_held_block.setText(f"💻 このPCの所持ブロック: {blocks:,}")
            self.lbl_sync_detail.setText("✓ ソロ採掘可能 (最新ブロック到達)")
            self.lbl_sync_detail.setStyleSheet("font-size: 12px; color: #34d399; font-weight: bold;")
            self.progress_sync.setValue(1000)
            self.progress_sync.setFormat(f"同期 100% (最新 #{blocks:,})")

    def _node_rpc_in_use(self, what: str) -> bool:
        """Both bundled launchers bind RPC port 9402; a second node there cannot start."""
        info = self._last_node_info
        if not info.get("is_running") or info.get("port") != 9402:
            return False
        chain = str(info.get("chain", "")).upper() or "不明"
        QMessageBox.information(
            self, f"{what}の起動",
            f"RPC ポート 9402 ではすでに Monacoin Core ノード (チェーン: {chain}) が稼働中です。\n"
            f"同じポートを使うため、{what}は起動できません。\n\n"
            "別のノードを使う場合は、先に稼働中のノードを停止してください "
            "(Regtest: node/stop_nodes.bat、本番: .\\node\\monacoin_cli.bat stop)。"
        )
        return True

    def _launch_mainnet_environment(self):
        bat_path = os.path.join(_app_root(), "node", "start_mainnet_solo.bat")
        if not os.path.exists(bat_path):
            QMessageBox.warning(self, "エラー", f"起動スクリプトが見つかりません:\n{bat_path}")
            return
        if self._node_rpc_in_use("本番ノード"):
            return

        try:
            _launch_bat_in_new_window(bat_path)
            self.console.append_log("🌐 本番メインネット Monacoin Core ノードの別ウィンドウ起動を要求しました。", "info")
            QMessageBox.information(
                self, "メインネット ノード起動",
                "本番メインネットの Monacoin Core ノードを別ウィンドウで起動しました。\n\n"
                "ブロック検証がバックグラウンドで進行します。\n"
                "上の『🔄 更新』ボタンで現在のブロック高と進捗状況をリアルタイムに確認できます。"
            )
            QTimer.singleShot(3000, self._manual_refresh_node_sync)
        except Exception as e:
            QMessageBox.warning(self, "起動エラー", f"メインネット ノードの起動に失敗しました: {e}")

    def closeEvent(self, event):
        if hasattr(self, "node_sync_timer"):
            self.node_sync_timer.stop()
        # Python drops these QThread wrappers when the window goes away; destroying a QThread
        # that is still running aborts the whole process.
        from app.ui.wallet_dialog import WalletHistoryDialog
        pending = [self._node_worker, self._benchmark_worker]
        pending += [dlg.worker for dlg in self.findChildren(WalletHistoryDialog)]
        for worker in pending:
            if worker is not None and worker.isRunning():
                worker.wait(20000)
        if self.miner_ctrl.is_mining:
            self.miner_ctrl.stop_mining()
        self.web_server.stop()
        self.idle_tracker.stop()
        self.gpu_ctrl.shutdown()
        self.hw_mgr.shutdown()
        event.accept()

