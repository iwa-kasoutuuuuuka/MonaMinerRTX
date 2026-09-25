import os
import sys
import webbrowser
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QFrame,
    QFileDialog, QMessageBox, QTabWidget, QRadioButton, QButtonGroup,
    QSpinBox, QDoubleSpinBox, QSlider, QStackedWidget, QScrollArea, QSizePolicy,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QTimer

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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MonaMiner RTX / RX v2.1.0 - 次世代モナコイン (Lyra2REv2) GPU/CPU マイニングスタジオ")
        self.setMinimumSize(920, 640)
        self.resize(1120, 880)
        self.setStyleSheet(MAIN_STYLE)

        self.config_mgr = ConfigManager()
        self.hw_mgr = HardwareManager()
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

        # Telemetry refresh timer (every 1 second)
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self._update_hardware_telemetry)
        self.telemetry_timer.start(1000)

        # Initial telemetry update
        self._update_hardware_telemetry()

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
        main_layout.setSpacing(8)
        scroll_area.setWidget(content_widget)

        # 1. Top Header Banner
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
        title = QLabel("MonaMiner RTX / RX v1.5.1 (Lyra2REv2)")
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

        # 2. Hardware Live Status Bar (Metric Cards)
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

        # 3. Middle Section: Device Selection & Profile Selection
        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(10)

        # 3A. Device Selection Card
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
        gpu_label = f"{gpu_badge} GPU のみ ({hw_info['short_name']})" if has_gpu else "⚡ GPU (未検出)"
        self.btn_dev_gpu = QRadioButton(gpu_label)
        self.btn_dev_cpu = QRadioButton("🧠 CPU のみ")
        self.btn_dev_hybrid = QRadioButton("🚀 ハイブリッド (GPU+CPU)")

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

        # CPU Quick Preset Buttons
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

        middle_layout.addWidget(device_card, stretch=2)

        # 3B. Mode Profiles
        rec_info = self.hw_mgr.get_mode_recommendation()
        mode_box = QFrame()
        mode_box.setObjectName("card")
        mode_box_layout = QVBoxLayout(mode_box)
        mode_box_layout.setContentsMargins(10, 8, 10, 8)
        mode_box_layout.setSpacing(6)

        lbl_profile_title = QLabel("⚙️ GPU動作プロファイル")
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

        middle_layout.addWidget(mode_box, stretch=3)
        main_layout.addLayout(middle_layout)

        # Highlight initially selected mode
        active_key = self.current_mode
        if active_key == "auto":
            active_key = rec_info["recommended_key"]
        self._highlight_mode(active_key)

        # 4. Mining Target Settings (Tabs for Pool vs Solo)
        self.tabs_target = QTabWidget()
        self.tabs_target.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #334155; border-radius: 8px; background-color: #1a202c; padding: 10px; }
            QTabBar::tab { background: #0f172a; color: #94a3b8; padding: 8px 16px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; font-weight: bold; }
            QTabBar::tab:selected { background: #1a202c; color: #fbbf24; border: 1px solid #334155; border-bottom: none; }
        """)

        # Tab 1: Pool Mining
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
        self.edit_custom_pool.textChanged.connect(lambda t: self.config_mgr.set("custom_pool_url", t.strip()))
        self.edit_custom_pool.setEnabled(self.combo_pool.currentIndex() == 2)
        tab_pool_layout.addWidget(self.edit_custom_pool, 0, 3)

        tab_pool_layout.addWidget(QLabel("ワーカー名:"), 1, 0)
        self.edit_worker = QLineEdit(self.config_mgr.get("worker_name", "rtx5080_worker"))
        self.edit_worker.setPlaceholderText("例: アカウント名.worker1 (VIPPOOL登録名)")
        self.edit_worker.setToolTip("VIPPOOL等の登録制プールでは「Web登録ユーザー名.ワーカー名」を入力してください。")
        self.edit_worker.textChanged.connect(lambda t: self.config_mgr.set("worker_name", t.strip()))
        tab_pool_layout.addWidget(self.edit_worker, 1, 1)

        tab_pool_layout.addWidget(QLabel("ワーカー パスワード:"), 1, 2)
        self.edit_pool_pass = QLineEdit(self.config_mgr.get("pool_password", "x"))
        self.edit_pool_pass.textChanged.connect(lambda t: self.config_mgr.set("pool_password", t.strip()))
        tab_pool_layout.addWidget(self.edit_pool_pass, 1, 3)

        lbl_pool_hint = QLabel("💡 ヒント: VIPPOOL等の登録制プールは『アカウント名.ワーカー名』を入力してください。アドレス直掘りプールはワーカー名単体でOKです。")
        lbl_pool_hint.setStyleSheet("color: #a5b4fc; font-size: 11px;")
        tab_pool_layout.addWidget(lbl_pool_hint, 2, 0, 1, 4)

        self.tabs_target.addTab(tab_pool, "🏊 プールマイニング (Stratum)")

        # Tab 2: Solo Mining
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

        self.tabs_target.addTab(tab_solo, "🏠 ソロマイニング (Monacoin Core RPC)")

        # Tab 3: Smart Idle Auto-Mining
        tab_idle = QWidget()
        tab_idle_layout = QGridLayout(tab_idle)
        tab_idle_layout.setContentsMargins(8, 8, 8, 8)
        tab_idle_layout.setHorizontalSpacing(10)
        tab_idle_layout.setVerticalSpacing(8)

        self.chk_idle_enable = QCheckBox("離席時の自動採掘を有効化 (PC操作停止で自動スタート)")
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

        self.tabs_target.addTab(tab_idle, "🤖 スマート・アイドル採掘")

        # Tab 4: Electricity & Profit Calculator
        tab_profit = QWidget()
        tab_profit_layout = QGridLayout(tab_profit)
        tab_profit_layout.setContentsMargins(8, 8, 8, 8)
        tab_profit_layout.setHorizontalSpacing(10)
        tab_profit_layout.setVerticalSpacing(8)

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
        self.lbl_profit_summary.setStyleSheet("color: #a7f3d0; font-size: 12px; font-weight: bold;")
        tab_profit_layout.addWidget(self.lbl_profit_summary, 1, 0, 1, 4)

        self.tabs_target.addTab(tab_profit, "💰 電気代・収益性計算")

        # Tab 5: Web Dashboard & Discord Webhook
        tab_remote = QWidget()
        tab_remote_layout = QGridLayout(tab_remote)
        tab_remote_layout.setContentsMargins(8, 8, 8, 8)
        tab_remote_layout.setHorizontalSpacing(10)
        tab_remote_layout.setVerticalSpacing(8)

        self.chk_web_enable = QCheckBox("スマホ対応 内蔵Webダッシュボードを起動 (LAN内ブラウザ閲覧)")
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

        self.tabs_target.addTab(tab_remote, "🌐 遠隔監視・通知")

        # Tab 6: Hardware & Multi-GPU
        tab_hw = QWidget()
        tab_hw_layout = QGridLayout(tab_hw)
        tab_hw_layout.setContentsMargins(8, 8, 8, 8)
        tab_hw_layout.setHorizontalSpacing(10)
        tab_hw_layout.setVerticalSpacing(8)

        tab_hw_layout.addWidget(QLabel("検出された OpenCL GPU デバイス (Multi-GPU 同時採掘):"), 0, 0, 1, 4)
        self.list_gpus = QListWidget()
        self.list_gpus.setStyleSheet("background-color: #0f172a; border: 1px solid #334155; border-radius: 4px; color: #f8fafc;")
        self.list_gpus.setFixedHeight(75)
        self._populate_gpu_list()
        tab_hw_layout.addWidget(self.list_gpus, 1, 0, 1, 4)

        # NVIDIA Hardware control row
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
        btn_apply_hw.setStyleSheet("background-color: #059669; color: white; border-radius: 4px; padding: 6px; font-weight: bold;")
        btn_apply_hw.setCursor(Qt.PointingHandCursor)
        btn_apply_hw.clicked.connect(self._apply_gpu_hardware_settings)
        tab_hw_layout.addWidget(btn_apply_hw, 3, 0, 1, 4)

        self.tabs_target.addTab(tab_hw, "🔧 ハードウェア制御 (Multi-GPU)")

        # Set saved tab
        if self.config_mgr.get("mining_target", "pool") == "solo":
            self.tabs_target.setCurrentIndex(1)
        else:
            self.tabs_target.setCurrentIndex(0)
        self.tabs_target.currentChanged.connect(self._on_target_tab_changed)

        main_layout.addWidget(self.tabs_target)

        # 5. Wallet Address & General Options Frame
        config_frame = QFrame()
        config_frame.setObjectName("card")
        cfg_layout = QGridLayout(config_frame)
        cfg_layout.setContentsMargins(10, 8, 10, 8)
        cfg_layout.setHorizontalSpacing(10)
        cfg_layout.setVerticalSpacing(6)

        cfg_layout.addWidget(QLabel("受取アドレス (Coinbase):"), 0, 0)
        self.edit_address = QLineEdit(self.config_mgr.get("wallet_address", ""))
        self.edit_address.setPlaceholderText("例: M... または mona1... (報酬受取用)")
        self.edit_address.textChanged.connect(self._validate_address_input)
        cfg_layout.addWidget(self.edit_address, 0, 1)

        self.lbl_addr_status = QLabel("")
        self.lbl_addr_status.setStyleSheet("font-size: 11px;")
        cfg_layout.addWidget(self.lbl_addr_status, 0, 2)

        # Options row
        self.chk_simulator = QCheckBox("テスト・シミュレーションモード (実採掘を行わずUI・負荷のみ検証)")
        self.chk_simulator.setChecked(self.config_mgr.get("use_simulator", False))
        self.chk_simulator.toggled.connect(lambda v: self.config_mgr.set("use_simulator", v))
        cfg_layout.addWidget(self.chk_simulator, 1, 1)

        btn_browse_miner = QPushButton("オプション: 外部マイナー指定 (ccminer / wildrig 等)...")
        btn_browse_miner.setStyleSheet("background-color: #334155; border: none; border-radius: 4px; padding: 4px 10px;")
        btn_browse_miner.clicked.connect(self._browse_custom_miner)
        cfg_layout.addWidget(btn_browse_miner, 1, 2)

        main_layout.addWidget(config_frame)

        # 6. Big Action Controls (Start / Stop Button)
        action_layout = QHBoxLayout()
        self.btn_toggle_mining = QPushButton("🚀 採掘開始 (Start Mining)")
        self.btn_toggle_mining.setObjectName("start_btn")
        self.btn_toggle_mining.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_mining.clicked.connect(self._toggle_mining)
        action_layout.addWidget(self.btn_toggle_mining)
        main_layout.addLayout(action_layout)

        # 7. Live Console / Log View
        self.console = LogConsole()
        main_layout.addWidget(self.console)

        # Initial validation check
        self._validate_address_input(self.edit_address.text())

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
                {"name": "バージョン", "value": "v2.1.0", "inline": True},
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

    def _get_web_status(self) -> dict:
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
            import time
            sec = int(time.time() - self.mining_start_time)
            hrs = sec // 3600
            mins = (sec % 3600) // 60
            secs = sec % 60
            uptime_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        shares_txt = self.card_shares.lbl_val.text()
        accepted = 0
        rejected = 0
        if "/" in shares_txt:
            parts = shares_txt.split("/")
            try:
                accepted = int(parts[0].strip())
                tot = int(parts[1].strip())
                rejected = max(0, tot - accepted)
            except Exception:
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
        # Trigger GUI toggle mining via QTimer
        QTimer.singleShot(0, lambda: self._toggle_mining() if not self.miner_ctrl.is_mining else None)

    def _remote_stop_mining(self):
        QTimer.singleShot(0, lambda: self._toggle_mining() if self.miner_ctrl.is_mining else None)

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

            import time
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

        # Update profit tab summary
        if self.miner_ctrl.is_mining and hr > 0:
            self.lbl_profit_summary.setText(
                f"【試算結果】 1時間電気代: ¥{calc['hourly_cost_yen']:.1f} / 24時間: ¥{calc['daily_cost_yen']:.0f} / "
                f"月間: ¥{calc['monthly_cost_yen']:.0f} ｜ 推定日収: {calc['est_daily_mona']:.3f} MONA (約¥{calc['est_daily_revenue_yen']:.0f}) ｜ "
                f"推定純利益: ¥{calc['est_daily_profit_yen']:.0f}/日"
            )

    def _on_miner_status_changed(self, status: str):
        self.setWindowTitle(f"MonaMiner RTX / RX v2.0.0 - [{status}]")
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

    def closeEvent(self, event):
        if self.miner_ctrl.is_mining:
            self.miner_ctrl.stop_mining()
        self.web_server.stop()
        self.idle_tracker.stop()
        self.gpu_ctrl.shutdown()
        self.hw_mgr.shutdown()
        event.accept()

