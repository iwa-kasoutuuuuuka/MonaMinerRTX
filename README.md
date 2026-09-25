<div align="center">

<img src="assets/icon.png" width="120" height="120" alt="MonaMiner RTX Logo">

# MonaMiner RTX / RX
### ⚡ モナコイン (Lyra2REv2) ハイブリッド GUI マイニングスタジオ

[![Release](https://img.shields.io/badge/Release-v1.5.1-blue.svg)](https://github.com/iwa-kasoutuuuuuka/MonaMinerRTX/releases)
[![Direct Download](https://img.shields.io/badge/📥_直リンク_ダウンロード-MonaMinerRTX__Portable__v1.5.1.zip-brightgreen?style=for-the-badge&logo=windows)](https://github.com/iwa-kasoutuuuuuka/MonaMinerRTX/raw/main/dist/MonaMinerRTX_Portable_v1.5.1.zip)
[![Python](https://img.shields.io/badge/Python-3.9+-yellow.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**NVIDIA GeForce (RTX 50/40/30/20 & GTX 16/10)、AMD Radeon (RX 7000/6000/5000/Vega/Polaris)、ノートPC向けGPU、および多コアCPU（Ryzen / Intel）** に完全対応した、モナコイン（Monacoin / アルゴリズム: Lyra2REv2）向けハイブリッドGUIマイナーです。
**外部の `ccminer.exe` や追加インストーラーに一切依存せず、Windows標準の OpenCL ドライバと直接対話して高速並列採掘を行う「独自内蔵GPUマイナーエンジン」を標準搭載しています。**

</div>

---

## 🌟 主な特徴

1. **⚡ 独自内蔵 OpenCL マイナーエンジン (外部バイナリ完全不要 & 高度最適化)**:
   - Windows標準の `OpenCL.dll` と `ctypes` 経由で直接バインドし、GPU内部で Lyra2REv2（Blake256 -> Keccak256 -> CubeHash -> Lyra2 -> Skein -> BMW）カーネルをJITコンパイル＆並列実行。
   - **Ping-Pong レジスタバッファ化**: カーネル内部の中間バッファを交互利用することでGPUレジスタ使用量を 66% 削減し、SM/CUあたりの並列スレッド実行密度（Occupancy）を最大化。
   - **PCIe転送の極小化 (ヘッダーキャッシュ)**: ブロック不変ヘッダーのGPU再転送を撤廃し、新Job受信時のみ更新。
   - **適応型ディスパッチ制御 (Target ~100ms)**: GPU性能に応じて1ディスパッチを約100msに自動調整し、新ブロック通知時の無駄掘り（Stale Shares）を根絶。
   - 外部から怪しい `.exe` をダウンロードして設定する手間が一切なく、ウイルス対策ソフトの誤検知も大幅に軽減。AMD Radeon でも NVIDIA GeForce でも、アプリを起動して「採掘開始」を押すだけでネイティブGPUマイニングが即座に始まります。

2. **全世代NVIDIA & AMD Radeon GPU & CPUスペック自動検知エンジン**:
   - `NVML (NVIDIA Management Library)` および Windows WMI/CIM システム問い合わせにより、NVIDIA GeForce（RTX 5090〜GTX 1050Ti）および **AMD Radeon（RX 7900 XTX〜RX 470、Vegaシリーズ）** の型番、アーキテクチャ（Blackwell / Ada / Ampere / Turing / Pascal / RDNA 3 / RDNA 2 / RDNA 1 / Vega / Polaris）、VRAM、BIOS定格TDP、およびCPU物理/論理スレッド数をリアルタイム検出。
   - 搭載GPUのベンダー（NVIDIA / AMD）とアーキテクチャ特性に応じた最適な動作プロファイルを自動提案します。

2. **3つの最適化動作プロファイル (実機GPU & CPU 自動連動)**:
   - 🍃 **電力効率モード (Eco / Sweet Spot - 推奨)**:
     - GPU: 実機BIOSが許容する最小電力制限（例: 5080なら250W、4070なら140W、3060なら120W等）に自動設定、Intensity: 20〜21。
     - CPU: 物理コア数（例: 16スレッド）を割り当て、SMT（同時マルチスレッディング）のキャッシュ競合を回避。
     - GPUのキャッシュ効率とCPU物理コアの専有により、発熱と電気代を大幅削減しながら最高峰のワットパフォーマンスを実現。
   - ⚡ **最大計算力モード (Max Hashrate)**:
     - GPU: 定格最大TDP（例: 5080なら360W、4070なら220W等）フルパワー、Intensity: 22〜24。
     - CPU: OS/GPU用に2コアを残した最大スレッド数を投入。
     - GPUとCPUの全能力を解き放つ極限ハッシュレート構成。
   - ☕ **ながらマイニングモード (Quiet / Daily)**:
     - GPU負荷を30〜40%に抑え（ノートPCでは自動推奨）、CPUも25%（低スレッド）に制限。
     - ファンの静音を維持し、日常のPC作業（Web閲覧・動画視聴・ゲーム等）を一切妨げずに裏で静かにマイニング。

3. **🏊 プールマイニング & 🏠 ソロマイニング 両対応**:
   - **プールマイニング (Stratum)**: 国内代表プール（VIPPOOL:8888）へ接続し、安定して少額ずつの報酬を獲得。
   - **ソロマイニング (Monacoin Core RPC)**: ローカルの Monacoin Core (`127.0.0.1:9402`) と直接連携。ブロック発見時に **3.125 MONA + 取引手数料の全額（100%）** を独占獲得。

4. **💻 柔軟な採掘デバイス選択 (GPU / CPU / ハイブリッド同時マイニング)**:
   - ⚡ **GPU のみ**: RTX 5080（Blackwell）の圧倒的な計算力で採掘（約 170〜220 MH/s）。
   - 🧠 **CPU のみ**: 多コアCPUを活用した省エネ・補助採掘（約 10〜20 MH/s）。
   - 🚀 **ハイブリッド (GPU + CPU)**: GPUとCPUを同時にフル稼働させ、マシン全体の限界ハッシュレートを叩き出す最強モード。
   - スレッド数スライダー & ワンクリックプリセットボタン（`[🍃 16T]` `[⚡ 30T]` `[☕ 8T]`）で微調整が可能。

5. **安全設計とデュアル制御（管理者権限対応）**:
   - **一般ユーザー実行時**: 安全のため、Intensity（スレッド並列数）の調整でGPU負荷を制御。
   - **管理者として実行時**: NVML経由でGPUハードウェアの Power Limit（ワット数）を直接低減し、電圧降下による真の省電力化を適用。

6. **モナコイン専用設計 & ハイブリッド診断**:
   - レガシー（`M...`）および SegWit（`mona1...`）アドレスのリアルタイム正規表現バリデーション。
   - 内蔵シミュレータにより、外部マイナー未導入でもUI・負荷・ソロブロック発見の動作テストが可能。

---

## 📘 完全操作マニュアル (利用手順)

### ステップ 1: アプリケーションの起動
* **ポータブル版の場合**:
  * 解凍したフォルダ内の **`起動する.bat`** または **`run.bat`** をダブルクリックします。
  * （※ GPUの消費電力制限を直接下げたい場合は、`起動する.bat` を右クリックして「管理者として実行」を選択してください）
* **開発版 (Source) の場合**:
  * ターミナルで `python main.py` を実行します。

### ステップ 2: モナコイン受取アドレスの入力
* 画面中央の **「受取アドレス (Coinbase)」** 欄に、ご自身のモナコインアドレスを入力します。
  * レガシーアドレス（`M...` から始まる33〜34文字）
  * SegWitアドレス（`mona1...` から始まる42文字前後）
* 有効なアドレスが入力されると、右側に緑色のチェックマーク（`✓ 有効なアドレス`）が表示されます。

### ステップ 3: 採掘ターゲットの選択（プール vs ソロ）
画面中央のタブで接続先を切り替えます。

* **タブ 1: 🏊 プールマイニング (Stratum)**
  1. 「マイニング プール」ドロップダウンから接続先を選択します（デフォルト推奨: `VIPPOOL (国内最大・稼働中代表プール)`）。
  2. 「ワーカー名」に任意の名前（例: `rtx5080_worker`）を入力します。
* **タブ 2: 🏠 ソロマイニング (Monacoin Core RPC)**
  1. PC上で **Monacoin Core (公式フルノード)** を起動し、ブロックチェーンを同期させておきます。
  2. RPC Host（`127.0.0.1`）、RPC Port（`9402`）、RPCユーザー名・パスワードを入力します。
  3. ブロックを発見すると、ステップ2で入力したアドレスにブロック報酬全額が直接支払われます。

### ステップ 4: 採掘デバイスとプロファイルの選択
* **採掘デバイス選択**:
  * `[⚡ GPU のみ]` / `[🧠 CPU のみ]` / `[🚀 ハイブリッド (GPU+CPU)]` から選択します。
  * CPUを使用する場合は、スレッド数スライダーまたはクイックプリセットボタン（`[🍃 物理コア (16T)]` `[⚡ 最大 (30T)]` `[☕ 静音 (8T)]`）でお好みのスレッド数を指定します。
* **動作プロファイル選択**:
  * `[🍃 電力効率モード]`（推奨）: 発熱を抑え、電気代に対する効率を最大化。
  * `[⚡ 最大計算力モード]`: ハッシュレート最優先。
  * `[☕ ながらマイニング]`: PC作業・ゲーム・動画視聴と両立。

### ステップ 5: 採掘開始とモニタリング
* **「🚀 採掘開始 (Start Mining)」** ボタンをクリックします。
* 上部のメトリックカードに、リアルタイムの **ハッシュレート (MH/s)、消費電力 (W)、電力効率 (MH/W)、GPU温度 (℃)、CPU使用率 (%)、承認シェア数 / 発見ブロック数** が表示されます。
* 下部の「マイニング動作ログ」に、Stratumプロトコル通信やシェア提出結果（`yes!`）、ソロブロック検知ログがリアルタイムに流れます。
* 停止したい時は **「⏹ 採掘停止 (Stop Mining)」** をクリックします。

> [!TIP]
> **テスト・診断モードについて**:
> 外部の `ccminer.exe` が手元にない状態でも、「テスト・診断モード」のチェックボックスをONにしておけば、UIや負荷制御、Stratum通信、ソロブロック発見フローの動作を安全にテスト・体験できます。

---

## 🛡️ ウイルス対策ソフト（セキュリティソフト）への対応

### なぜ暗号資産マイナーは警告されるのか？ (誤検知の仕組み)
暗号資産マイニングソフトウェア（ccminer、cpuminer、および本ツール等のマイナー関連バイナリ）は、**ウイルスやマルウェアそのものではありません**。

しかし、悪意あるハッカーが他人のPCに勝手にマイニングソフトを仕込んで不正採掘する「クリプトジャッキング」が世界的に存在するため、多くのアンチウイルスソフト（Windows Defender、Norton、McAfee、ウイルスバスター等）は、**正当なツールであっても一律で `PUA:Win32/CoinMiner`（望ましくない可能性のあるアプリ）や `Riskware` として機械的に検疫・ブロックする仕様**になっています。

本ソフトウェアは安全なオープンソース技術のみで構築されていますが、スムーズにご利用いただくために以下の除外設定を推奨します。

### Windows Defender (Windows セキュリティ) での除外設定手順

1. スタートメニューから **「設定」**（歯車アイコン）を開きます。
2. **「プライバシーとセキュリティ」** → **「Windows セキュリティ」** を開きます。
3. **「ウイルスと脅威の防止」** をクリックします。
4. 「ウイルスと脅威の防止の設定」の見出しにある **「設定の管理」** をクリックします。
5. 画面の下部までスクロールし、「除外」の見出しにある **「除外の追加または削除」** をクリックします。
6. **「＋ 除外の追加」** ボタンを押し、**「フォルダー」** を選択します。
7. 解凍した本ツールのフォルダ（`mona-miner-gui` または `MonaMinerRTX`）を選択して登録します。

> [!NOTE]
> **Windows SmartScreen の青い警告画面が出た場合**:
> 初回起動時に「Windows によって PC が保護されました」という青いダイアログが表示された場合は、ダイアログ内の **「詳細情報」** をクリックし、現れた **「実行」** ボタンを押すことで正常に起動できます。

---

## 🏠 ソロマイニングの環境構築ガイド (`monacoin.conf`)

ソロマイニングを行うには、PC上で **Monacoin Core** が JSON-RPC を受け付けるように設定する必要があります。

1. **Monacoin Core** をインストールし、ブロックチェーンを全同期します。
2. モナコインのデータディレクトリ（通常 `C:\Users\<ユーザー名>\AppData\Roaming\Monacoin\`）にある `monacoin.conf` をメモ帳等で開きます（存在しない場合は新規作成）。
3. 以下の内容を記述して保存します：
   ```ini
   server=1
   rpcuser=monacoinrpc
   rpcpassword=任意の安全なパスワード
   rpcport=9402
   rpcallowip=127.0.0.1
   ```
4. Monacoin Core を再起動します。
5. 本ツールの「🏠 ソロマイニング」タブで、上記で設定したユーザー名とパスワードを入力して開始します。

---

## 📦 配布用ポータブル版 (Portable Edition)

Python や各種ライブラリのインストールが**一切不要**な単体配布版です。ZIPを解凍して `起動する.bat` をダブルクリックするだけですぐにマイニングを開始できます。

### 📥 ダウンロード (直リンク)
* **[🚀 MonaMinerRTX_Portable_v1.5.1.zip (直接ダウンロード)](https://github.com/iwa-kasoutuuuuuka/MonaMinerRTX/raw/main/dist/MonaMinerRTX_Portable_v1.5.1.zip)** (約 46 MB)
* **[📦 GitHub Releases 一覧](https://github.com/iwa-kasoutuuuuuka/MonaMinerRTX/releases)**

---

### 自身でポータブル版を再ビルドする場合
```powershell
python build_portable.py
```
PyInstaller により、必要なDLL・アプリアイコン・設定ファイル・起動バッチを自動パッケージングして `dist/` に出力します。

---

## 🛠️ 自己診断・デバッグツール (`diagnose.py`)

システムの動作状況やネットワーク疎通をワンクリックで診断できます。

```powershell
python diagnose.py
```

### 診断内容 (7ステップ全自動)
1. **Python 実行環境チェック** (3.9以上、OS互換性)
2. **GUI ライブラリ (PySide6 / Qt6) チェック**
3. **ハードウェア検知 (NVML & CPU)** (RTX 5080、VRAM、CPU物理/論理コア数、温度、CPU使用率)
4. **最適化モード判定ロジック チェック** (GPU 250W + CPU 16T 推奨ロジック)
5. **マイニングプール導通テスト (TCP Handshake)** (VIPPOOL port 8888 への疎通)
6. **マイナー制御 & シミュレーション動作チェック** (ハイブリッド & ソロマイニングサイクル)
7. **独自内蔵 OpenCL マイナーエンジン & JIT コンパイル チェック** (GPU直結演算パイプライン)

---

## 📋 更新履歴 (Changelog)

### v1.5.1 (2026-09-25)
* **⚡ 独自内蔵 OpenCL マイナーエンジンの徹底効率化 (Performance Optimization)**:
  * **カーネル内 Ping-Pong レジスタバッファ化**: 6段のハッシュ連鎖で消費していた48個の32bit中間配列（192B）を `stateA` / `stateB`（64B）の交互利用に集約。レジスタプレッシャーを66%削減し、GPUの同時並列スレッド実行密度（Occupancy）を最大化。
  * **JIT コンパイラ最適化フラグの導入**: `-cl-mad-enable -cl-no-signed-zeros` を適用し、ハードウェアMAD/FMA演算器をフル活用。
  * **全ハッシュ関数の `inline` 展開**: 関数呼び出しオーバーヘッドを排除し、コンパイラの命令スケジューリングを最適化。
  * **PCIe ヘッダー転送の極小化 (ヘッダーキャッシュ)**: 毎反復でGPUへ送信していた76バイトの不変ヘッダー転送を完全排除し、新Job受信時のみ更新。
  * **適応型バッチディスパッチ制御 (Target ~100ms)**: GPU処理時間を動的モニタリングし、1ディスパッチを約100msに自動調整。新ブロック発生（Clean Jobs）時の無駄掘り（Stale Share）を根絶。

### v1.5.0 (2026-09-25)
* **⚡ 独自内蔵 OpenCL マイナーエンジンの完全統合 (No ccminer Dependency)**:
  * 外部の `ccminer.exe` やサードパーティ製マイナーに一切依存せず、アプリ単体でGPUマイニングを実行する純粋ネイティブエンジンを開発・搭載。
  * Windows標準の `OpenCL.dll` を `ctypes` で直接駆動し、外部Cコンパイラ（MSVC等）不要で Lyra2REv2（Blake256 -> Keccak256 -> CubeHash -> Lyra2 -> Skein -> BMW）カーネルを実行時にJITコンパイル。
  * AMD Radeon（RDNA 3/2/1, Vega, Polaris）および NVIDIA GeForce（Blackwell, Ada, Ampere, Turing, Pascal）の両方でネイティブ並列採掘に対応。
  * 純Pythonによる Stratum v1 プロトコルクライアント（`mining.subscribe`, `mining.authorize`, `mining.notify`, `mining.submit`）を内蔵し、プールから受け取ったジョブを直接GPUに供給してリアルタイム採掘・Share提出を実現。
  * 外部マイナーが未指定の場合でも、ブロックされずに内蔵エンジンが即座に起動してマイニングを開始。
  * 自己診断ツール（`diagnose.py`）に「[7/7] 独自内蔵 OpenCL マイナーエンジン & JIT コンパイル チェック」を追加。

### v1.4.0 (2026-09-25)
* **🔴 AMD Radeon GPU (RX 7000 / 6000 / 5000 / Vega / Polaris) フルサポート**:
  * NVML（NVIDIA専用）に加え、Windows WMI/CIM経由のフォールバックGPU検知エンジンを実装。
  * AMD Radeon RX 7900 XTX / 7800 XT、RX 6800 XT、RX 5700 XT、Vega 64/56、RX 580/570 等の自動判別に対応。
  * 各世代アーキテクチャ（RDNA 3 / RDNA 2 / RDNA 1 / Vega / Polaris）および実機定格TDPに基づき、OpenCL最適化プロファイル（Eco / Perf / Quiet）とLyra2REv2ベンチマーク推定値を自動算出。
  * UIヘッダーおよび採掘デバイス選択にAMD専用レッドバッジ（`🔴 GPU のみ (RX 7900 XTX)` 等）を動的バインディング。
  * AMD環境下でNVIDIA CUDA専用マイナー（ccminer）が選択された場合の安全な互換性警告とOpenCLマイナー（wildrig-multi / sgminer-gm等）案内ダイアログを追加。
  * 内蔵シミュレータにAMD OpenCL演算プロファイルおよび初期化ハンドシェイクを統合。

### v1.3.0 (2026-09-25)
* **🌟 全世代NVIDIA GPUへの動的対応 (Universal NVIDIA GPU Support)**:
  * RTX 5080 固定仕様から脱却し、RTX 5090 / 5080 / 5070、RTX 40 / 30 / 20 シリーズ、GTX 16 / 10 シリーズ、およびノートPC版GPUの自動判別に対応。
  * NVMLからGPU BIOSの実際の電力制限範囲（Min / Default / Max TDP）をリアルタイム取得し、各GPUに応じた最適Eco電力・定格電力を動的算出。
  * GPUのCompute Capabilityおよびアーキテクチャ特性（Blackwell / Ada / Ampere / Turing / Pascal）に応じた高精度ハッシュレート・電力効率推定。
  * NVIDIA GPUが検出されない環境における「CPU専用マイニングモード」への自動安全適応。
  * UIバナーおよび採掘デバイス選択ラジオボタンに検出された実機GPU名を動的バインド。
* **🎨 UIのレスポンシブ化 & 画面サイズ・高DPI文字潰れ根絶**:
  * 全体を包括するスマート `QScrollArea` を導入。低解像度画面やWindows高DPI（125% / 150%拡大等）でもレイアウトが圧縮されず、快適に縦スクロール可能。
  * メトリックカード、プロファイルカード、説明ラベルの自動折り返し（WordWrap）と最小高さ保護を適用。
  * Windowsに最適化された可読性の高い `'Yu Gothic UI'` フォントと、専用ダークテーマスクロールバーを実装。
* **💎 公式アプリアイコンの統合**:
  * サイバー調モナコイン＆マイニングピッケルの専用アプリアイコン（PNG / マルチ解像度ICO）を作成。
  * アプリヘッダーロゴ、タスクバー、Alt+Tab切り替え、およびWindows実行ファイル（EXE）にネイティブ埋め込み。
* **🛡️ 堅牢性とエラーハンドリング強化**:
  * グローバル例外ハンドラー（`sys.excepthook`）を搭載し、予期しないエラー発生時も原因をモーダル通知して安全に保護。
  * 採掘停止時の電力効率メトリックおよびシェア数の完全初期化同期。

### v1.2.0 (2026-09-25)
* **CPUスレッド数自動検知 & 最適モード連動機能**:
  * CPUのトポロジー（物理16コア / 論理32スレッド等）を自動検知。
  * 動作プロファイル（Eco / Perf / Quiet）選択時に、GPU電力制限だけでなくCPUスレッド数も自動連動（Eco: 物理コア16T / Perf: 最大30T / Quiet: 静音8T）。
  * CPU設定エリアにクイックプリセットボタン（`[🍃 16T]` `[⚡ 30T]` `[☕ 8T]`）を追加。
* **ドキュメント拡充**:
  * 完全操作マニュアル、アンチウイルスソフト誤検知対応ガイド、更新履歴を README に追加。

### v1.1.0 (2026-09-25)
* **🏠 ソロマイニング (Monacoin Core RPC) 対応**:
  * プール / ソロのタブ切り替えUIを新設。
  * RPC Host, Port, User, Password, Coinbaseアドレスの自動バインド。
  * シミュレータにおける `getblocktemplate` 取得とブロック発見演出の追加。
* **🧠 CPUマイニング & 🚀 ハイブリッド同時マイニング対応**:
  * 採掘デバイス選択（GPUのみ / CPUのみ / ハイブリッド同時採掘）を追加。
  * CPUスレッド数制御スライダーおよびリアルタイムCPU使用率（%）テレメトリカードを追加。
* **設定の永続化**:
  * 採掘ターゲット、デバイス選択、CPUスレッド数の次回起動時自動復元。

### v1.0.1 (2026-09-25)
* **実機通信ポートの修正**:
  * VIPPOOLの正規Stratumポートを `8888`（`stratum1.vippool.net:8888`）に修正し、TCPハンドシェイク導通を確認。
* **安定性向上とデバッグ修正**:
  * マイナー異常終了時のUIボタインスタック防止ロジックを実装。
  * Windows日本語環境（cp932）での文字コードクラッシュを防止（UTF-8ストリーム再構成）。
  * Windows `taskkill /F /T /PID` によるプロセストリー完全終了処理を実装（ゾンビプロセス防止）。
* **自己診断ツール `diagnose.py` の追加**:
  * ハードウェア、ネットワーク、シミュレーションサイクルの全自動診断テストを搭載。

### v1.0.0 (2026-09-25)
* 初回リリース: NVIDIA GeForce RTX 5080 (Blackwell CC 12.0) 特化型モナコインGUIマイナー。
* NVML によるリアルタイムテレメトリ（温度、ファン、電力、クロック）。
* 3つのGPU最適化プロファイル（Eco 250W / Perf 360W / Quiet）。
* アドレス自動バリデーション（Base58 / Bech32）。
* 配布用ポータブル版（Portable Edition）のビルドシステム構築。

---

## 📁 ディレクトリ構成

```
mona-miner-gui/
├── GEMINI.md               # 思考プロセス・デバッグガイドライン
├── README.md               # 完全マニュアル・仕様書・更新履歴
├── requirements.txt        # 依存パッケージ
├── run.bat                 # 開発版起動用バッチファイル
├── main.py                 # アプリケーションエントリーポイント
├── diagnose.py             # システム自己診断・デバッグスクリプト
├── build_portable.py       # 配布用ポータブル版ビルドスクリプト
├── config.json             # ユーザー設定自動保存ファイル
├── dist/                   # ポータブル版出力先
│   ├── MonaMinerRTX/       # 解凍済みポータブル実行環境 (MonaMinerRTX.exe 同梱)
│   └── MonaMinerRTX_Portable_v1.5.1.zip # 配布用ZIPアーカイブ
└── app/
    ├── config.py           # 設定管理・アドレスバリデーション (Base58/Bech32)
    ├── hardware.py         # NVML/WMI/CPU ハードウェア検知 & 推奨エンジン
    ├── miner_controller.py # マイナー制御マネージャー
    ├── miner/              # ⚡ 独自内蔵 OpenCL マイナーエンジン
    │   ├── opencl_backend.py # Windows OpenCL.dll ctypes 低レベルバインディング
    │   ├── opencl_miner.py   # GPUマイニングワーカー (QThread)
    │   ├── stratum_client.py # 純Python Stratum v1 プロトコルクライアント
    │   └── kernels/
    │       └── lyra2v2.cl    # Lyra2REv2 JIT OpenCL C カーネル
    └── ui/
        ├── main_window.py  # メインウィンドウ
        ├── components.py   # メトリックカード・モードカード
        └── styles.py       # ダークテーマスタイルシート (QSS)
```
