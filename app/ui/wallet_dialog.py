"""
Wallet History and Balance Modal Dialog for MonaMiner RTX
Displays real-time address balance, total sent/received, and a detailed transaction history table.
"""
import webbrowser
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QCursor, QClipboard, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QMessageBox, QApplication
)
from app.services.wallet_service import fetch_wallet_history


class WalletFetchWorker(QThread):
    """バックグラウンドでウォレット情報を取得するスレッド"""
    finished = Signal(dict)

    def __init__(self, address: str):
        super().__init__()
        self.address = address

    def run(self):
        res = fetch_wallet_history(self.address)
        self.finished.emit(res)


class WalletHistoryDialog(QDialog):
    """モナコイン ウォレット入出金履歴ポップアップモーダル"""

    def __init__(self, address: str, parent=None):
        super().__init__(parent)
        self.address = address.strip()
        self.setWindowTitle("🪙 モナコイン ウォレット残高 ＆ 入出金履歴")
        self.resize(840, 580)
        self.setMinimumSize(720, 480)

        # Style sheet
        self.setStyleSheet("""
            QDialog {
                background-color: #0b1120;
                color: #f1f5f9;
                font-family: 'Yu Gothic UI', 'Segoe UI', sans-serif;
            }
            QFrame#card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QTableWidget {
                background-color: #0f172a;
                alternate-background-color: #1e293b;
                gridline-color: #334155;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #f1f5f9;
                selection-background-color: #0284c7;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: bold;
                font-size: 11px;
                padding: 6px;
                border: none;
                border-bottom: 2px solid #0284c7;
            }
            QPushButton {
                background-color: #334155;
                color: #f8fafc;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. Header Card: Address & Action
        header_card = QFrame()
        header_card.setObjectName("card")
        h_layout = QVBoxLayout(header_card)
        h_layout.setContentsMargins(14, 12, 14, 12)
        h_layout.setSpacing(6)

        title_row = QHBoxLayout()
        lbl_title = QLabel("🪙 モナコイン アドレス情報")
        lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #fbbf24;")
        title_row.addWidget(lbl_title)
        title_row.addStretch()

        self.btn_copy_addr = QPushButton("📋 アドレスをコピー")
        self.btn_copy_addr.setCursor(Qt.PointingHandCursor)
        self.btn_copy_addr.clicked.connect(self._copy_address)
        title_row.addWidget(self.btn_copy_addr)
        h_layout.addLayout(title_row)

        addr_row = QHBoxLayout()
        self.lbl_address_val = QLabel(self.address if self.address else "(アドレス未設定)")
        self.lbl_address_val.setStyleSheet("font-family: 'Consolas', monospace; font-size: 13px; color: #38bdf8; font-weight: bold;")
        self.lbl_address_val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        addr_row.addWidget(self.lbl_address_val)
        addr_row.addStretch()
        h_layout.addLayout(addr_row)

        layout.addWidget(header_card)

        # 2. Balance Summary Cards (4 Cards Grid)
        sum_grid = QGridLayout()
        sum_grid.setSpacing(10)

        # Balance Card
        self.card_bal = self._create_metric_frame("💰 現在残高", "-- MONA", "#10b981")
        # Total Received Card
        self.card_recv = self._create_metric_frame("🟢 総受取額", "-- MONA", "#38bdf8")
        # Total Sent Card
        self.card_sent = self._create_metric_frame("🔴 総出金額", "-- MONA", "#f43f5e")
        # Tx Count Card
        self.card_txs = self._create_metric_frame("🔢 取引総数", "-- 件", "#fbbf24")

        sum_grid.addWidget(self.card_bal, 0, 0)
        sum_grid.addWidget(self.card_recv, 0, 1)
        sum_grid.addWidget(self.card_sent, 0, 2)
        sum_grid.addWidget(self.card_txs, 0, 3)
        layout.addLayout(sum_grid)

        # 3. Status / Progress Label
        self.lbl_status = QLabel("⏳ ネットワークから最新の入出金履歴を取得中...")
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: bold;")
        layout.addWidget(self.lbl_status)

        # 4. Transaction History Table
        self.table_txs = QTableWidget(0, 5)
        self.table_txs.setHorizontalHeaderLabels(["日時", "区分", "変動額 (MONA)", "承認数", "トランザクションID (TxHash)"])
        self.table_txs.setAlternatingRowColors(True)
        self.table_txs.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_txs.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_txs.verticalHeader().setVisible(False)
        self.table_txs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_txs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_txs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_txs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_txs.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table_txs.itemDoubleClicked.connect(self._on_table_item_double_clicked)
        layout.addWidget(self.table_txs)

        # 5. Bottom Buttons Bar
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.btn_refresh = QPushButton("🔄 最新情報に更新")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh_data)
        btn_bar.addWidget(self.btn_refresh)

        self.btn_explorer = QPushButton("🌐 Webエクスプローラーで全履歴を見る")
        self.btn_explorer.setCursor(Qt.PointingHandCursor)
        self.btn_explorer.setStyleSheet("background-color: #0284c7; color: white;")
        self.btn_explorer.clicked.connect(self._open_web_explorer)
        btn_bar.addWidget(self.btn_explorer)

        btn_bar.addStretch()

        btn_close = QPushButton("閉じる")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        btn_bar.addWidget(btn_close)

        layout.addLayout(btn_bar)

        # Fetch Worker reference
        self.worker = None

        # Auto fetch on open
        if self.address:
            self.refresh_data()
        else:
            self.lbl_status.setText("⚠️ アドレスが設定されていません。メイン画面で受取アドレスを入力してください。")

    def _create_metric_frame(self, title: str, init_val: str, color_hex: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(10, 8, 10, 8)
        fl.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("font-size: 11px; color: #94a3b8; font-weight: bold;")
        lbl_v = QLabel(init_val)
        lbl_v.setObjectName("val")
        lbl_v.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {color_hex}; font-family: 'Consolas', monospace;")

        fl.addWidget(lbl_t)
        fl.addWidget(lbl_v)
        return frame

    def _set_metric_val(self, frame: QFrame, val_text: str):
        lbl = frame.findChild(QLabel, "val")
        if lbl:
            lbl.setText(val_text)

    def refresh_data(self):
        """非同期でウォレット情報を再取得"""
        if not self.address:
            self.lbl_status.setText("⚠️ アドレスが入力されていません。")
            return

        self.btn_refresh.setEnabled(False)
        self.lbl_status.setText("⏳ ネットワークから最新の入出金履歴を取得中...")

        self.worker = WalletFetchWorker(self.address)
        self.worker.finished.connect(self._on_data_loaded)
        self.worker.start()

    def _on_data_loaded(self, res: dict):
        self.btn_refresh.setEnabled(True)

        if not res.get("success", False):
            err = res.get("error", "取得エラー")
            self.lbl_status.setText(f"❌ エラー: {err}")
            return

        bal = res.get("balance", 0.0)
        recv = res.get("total_received", 0.0)
        sent = res.get("total_sent", 0.0)
        tx_count = res.get("tx_count", 0)
        txs = res.get("transactions", [])

        self._set_metric_val(self.card_bal, f"{bal:.8f} MONA")
        self._set_metric_val(self.card_recv, f"{recv:.8f} MONA")
        self._set_metric_val(self.card_sent, f"{sent:.8f} MONA")
        self._set_metric_val(self.card_txs, f"{tx_count:,} 件")

        self.lbl_status.setText(f"✓ 取得完了: 最新 {len(txs)} 件のトランザクションを表示中 (全 {tx_count:,} 件)")

        # Populate Table
        self.table_txs.setRowCount(0)
        for row_idx, tx in enumerate(txs):
            self.table_txs.insertRow(row_idx)

            # 0. Time
            item_time = QTableWidgetItem(tx.get("time", "--"))
            item_time.setTextAlignment(Qt.AlignCenter)
            self.table_txs.setItem(row_idx, 0, item_time)

            # 1. Type
            is_recv = tx.get("is_receive", True)
            type_text = "🟢 入金 (+)" if is_recv else "🔴 出金 (-)"
            item_type = QTableWidgetItem(type_text)
            item_type.setTextAlignment(Qt.AlignCenter)
            self.table_txs.setItem(row_idx, 1, item_type)

            # 2. Delta Amount
            delta = tx.get("delta", 0.0)
            sign = "+" if delta >= 0 else ""
            delta_str = f"{sign}{delta:.8f} MONA"
            item_amt = QTableWidgetItem(delta_str)
            item_amt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_amt.setFont(QFont("Consolas", 10, QFont.Bold))
            if is_recv:
                item_amt.setForeground(QColor("#10b981"))
            else:
                item_amt.setForeground(QColor("#f43f5e"))
            self.table_txs.setItem(row_idx, 2, item_amt)

            # 3. Confirmations
            confs = tx.get("confirmations", 0)
            item_conf = QTableWidgetItem(f"{confs:,}")
            item_conf.setTextAlignment(Qt.AlignCenter)
            if confs >= 6:
                item_conf.setForeground(QColor("#38bdf8"))
            else:
                item_conf.setForeground(QColor("#fbbf24"))
            self.table_txs.setItem(row_idx, 3, item_conf)

            # 4. TxHash
            txid = tx.get("txid", "")
            short_txid = f"{txid[:12]}...{txid[-12:]}" if len(txid) > 24 else txid
            item_txid = QTableWidgetItem(short_txid)
            item_txid.setToolTip(f"TxHash: {txid}\n(ダブルクリックでハッシュ全体をコピー)")
            item_txid.setFont(QFont("Consolas", 9))
            item_txid.setData(Qt.UserRole, txid)
            self.table_txs.setItem(row_idx, 4, item_txid)

    def _copy_address(self):
        if self.address:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(self.address)
            self.btn_copy_addr.setText("✓ コピーしました！")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self.btn_copy_addr.setText("📋 アドレスをコピー"))

    def _on_table_item_double_clicked(self, item: QTableWidgetItem):
        row = item.row()
        txid_item = self.table_txs.item(row, 4)
        if txid_item:
            full_txid = txid_item.data(Qt.UserRole) or txid_item.text()
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(full_txid)
            self.lbl_status.setText(f"✓ TxHash をクリップボードにコピーしました: {full_txid[:20]}...")

    def _open_web_explorer(self):
        if self.address:
            url = f"https://blockbook.electrum-mona.org/address/{self.address}"
            webbrowser.open(url)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(1000)
        super().closeEvent(event)

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(1000)
        super().reject()
