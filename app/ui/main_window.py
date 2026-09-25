import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QFrame,
    QFileDialog, QMessageBox, QTabWidget, QRadioButton, QButtonGroup,
    QSpinBox, QSlider, QStackedWidget, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer

from app.hardware import HardwareManager
from app.miner_controller import MinerController
from app.config import ConfigManager, DEFAULT_POOLS, validate_mona_address
from app.ui.components import MetricCard, ModeCard, LogConsole
from app.ui.styles import MAIN_STYLE

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MonaMiner RTX - モナコイン (Lyra2REv2) GPU/CPU マイニングスタジオ")
        self.setMinimumSize(880, 600)
        self.resize(1060, 840)
        self.setStyleSheet(MAIN_STYLE)

        self.config_mgr = ConfigManager()
        self.hw_mgr = HardwareManager()
        self.miner_ctrl = MinerController(self.hw_mgr)

        self.current_mode = self.config_mgr.get("miner_mode", "auto")
        self.target_type = self.config_mgr.get("mining_target", "pool") # 'pool' or 'solo'
        self.device_target = self.config_mgr.get("device_target", "gpu") # 'gpu', 'cpu', 'hybrid'
        self.mode_cards = {}

        self._setup_ui()
        self._connect_signals()

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
        title = QLabel("MonaMiner RTX (Lyra2REv2)")
        title.setObjectName("title")
        subtitle = QLabel("RTX 5080 (Blackwell) & 多コアCPU ハイブリッド | プール / ソロ両用")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        header_left.addLayout(title_layout)
        banner_layout.addLayout(header_left, stretch=1)

        # Hardware Badge & Admin Status
        hw_info = self.hw_mgr.device_info
        cpu_info = self.hw_mgr.cpu_info
        badge_layout = QVBoxLayout()
        badge_layout.setSpacing(4)
        badge_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        lbl_hw = QLabel(f"⚡ {hw_info['name']} | 🧠 CPU ({cpu_info['logical_cores']}T)")
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
        self.card_eff = MetricCard("電力効率", "--", "MH/W")
        self.card_gpu_temp = MetricCard("GPU 温度", "--", "℃")
        self.card_cpu_util = MetricCard("CPU 使用率", "--", "%")
        self.card_shares = MetricCard("承認シェア / ブロック", "0 / 0", "")

        status_bar.addWidget(self.card_hashrate)
        status_bar.addWidget(self.card_power)
        status_bar.addWidget(self.card_eff)
        status_bar.addWidget(self.card_gpu_temp)
        status_bar.addWidget(self.card_cpu_util)
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
        self.btn_dev_gpu = QRadioButton("⚡ GPU のみ (RTX 5080)")
        self.btn_dev_cpu = QRadioButton("🧠 CPU のみ")
        self.btn_dev_hybrid = QRadioButton("🚀 ハイブリッド (GPU+CPU)")
        
        self.dev_group = QButtonGroup(self)
        self.dev_group.addButton(self.btn_dev_gpu, 1)
        self.dev_group.addButton(self.btn_dev_cpu, 2)
        self.dev_group.addButton(self.btn_dev_hybrid, 3)

        saved_dev = self.config_mgr.get("device_target", "gpu")
        if saved_dev == "cpu":
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

        tab_pool_layout.addWidget(QLabel("ワーカー名:"), 0, 2)
        self.edit_worker = QLineEdit(self.config_mgr.get("worker_name", "rtx5080_worker"))
        self.edit_worker.textChanged.connect(lambda t: self.config_mgr.set("worker_name", t.strip()))
        tab_pool_layout.addWidget(self.edit_worker, 0, 3)

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
        self.chk_simulator = QCheckBox("テスト・診断モード (実マイナー未導入でもUI・負荷テスト可能)")
        self.chk_simulator.setChecked(self.config_mgr.get("use_simulator", True))
        self.chk_simulator.toggled.connect(lambda v: self.config_mgr.set("use_simulator", v))
        cfg_layout.addWidget(self.chk_simulator, 1, 1)

        btn_browse_miner = QPushButton("外部 ccminer.exe 指定...")
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
            self, "ccminer.exe を選択", "", "Executable (*.exe);;All Files (*.*)"
        )
        if path:
            self.config_mgr.set("custom_miner_path", path)
            self.config_mgr.set("use_simulator", False)
            self.chk_simulator.setChecked(False)
            self.console.append_log(f"外部マイナー設定: {path}", "info")
            QMessageBox.information(self, "設定完了", f"外部マイナーを設定しました:\n{path}")

    def _toggle_mining(self):
        if self.miner_ctrl.is_mining:
            self.miner_ctrl.stop_mining()
        else:
            addr = self.edit_address.text().strip()
            valid, msg = validate_mona_address(addr)
            if not valid:
                reply = QMessageBox.warning(
                    self, "アドレス確認",
                    f"入力されたモナコインアドレスに警告があります:\n{msg}\n\nこのままテスト採掘を続行しますか？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return

            target_type = self.target_type
            dev = self.device_target
            pool_url = self.combo_pool.currentData()
            worker = self.edit_worker.text().strip() or "worker1"
            solo_host = self.edit_solo_host.text().strip() or "127.0.0.1"
            solo_port = self.spin_solo_port.value()
            solo_user = self.edit_solo_user.text().strip()
            solo_pass = self.edit_solo_pass.text()
            cpu_threads = self.spin_threads.value()

            use_sim = self.chk_simulator.isChecked()
            custom_path = self.config_mgr.get("custom_miner_path", "")

            # If user wants real mining but no binary set
            if not use_sim and (not custom_path or not os.path.exists(custom_path)):
                reply = QMessageBox.question(
                    self, "ccminer未設定",
                    "外部の ccminer.exe が指定されていません。\n"
                    "テスト・診断モード (Simulator) で動作検証を行いますか？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    use_sim = True
                    self.chk_simulator.setChecked(True)
                else:
                    return

            mode = self.current_mode
            if mode == "auto":
                mode = self.hw_mgr.get_mode_recommendation()["recommended_key"]

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
                use_sim=use_sim
            )

    def _update_hardware_telemetry(self):
        m = self.hw_mgr.get_live_metrics()
        self.card_gpu_temp.set_value(f"{m.get('temp_c', 0)}")
        self.card_cpu_util.set_value(f"{m.get('cpu_util_pct', 0)}")
        if not self.miner_ctrl.is_mining:
            self.card_power.set_value(f"{m.get('power_w', 0.0):.1f}")

    def _on_miner_status_changed(self, status: str):
        self.setWindowTitle(f"MonaMiner RTX - [{status}]")
        if not self.miner_ctrl.is_mining:
            self.btn_toggle_mining.setObjectName("start_btn")
            self.btn_toggle_mining.setText("🚀 採掘開始 (Start Mining)")
            self.btn_toggle_mining.setStyle(self.btn_toggle_mining.style())
            self.card_hashrate.set_value("0.0")
            self.card_eff.set_value("--")
        else:
            self.btn_toggle_mining.setObjectName("stop_btn")
            self.btn_toggle_mining.setText("⏹ 採掘停止 (Stop Mining)")
            self.btn_toggle_mining.setStyle(self.btn_toggle_mining.style())

    def _on_hashrate_changed(self, hr: float, pwr: float, eff: float):
        self.card_hashrate.set_value(f"{hr:.1f}")
        self.card_power.set_value(f"{pwr:.1f}")
        self.card_eff.set_value(f"{eff:.2f}" if eff > 0 else "--")

    def _on_shares_changed(self, accepted: int, rejected: int):
        if self.target_type == "solo":
            self.card_shares.set_value(f"{accepted} blocks")
        else:
            self.card_shares.set_value(f"{accepted} / {accepted + rejected}")

    def closeEvent(self, event):
        if self.miner_ctrl.is_mining:
            self.miner_ctrl.stop_mining()
        self.hw_mgr.shutdown()
        event.accept()
