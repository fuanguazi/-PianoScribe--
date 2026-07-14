"""PianoScribe 设置对话框：4 Tab（音色 / 分离 / 高级 / 音频）。

使用：
    dialog = SettingsDialog(parent)
    dialog.settings_changed.connect(self._apply_settings)
    if dialog.exec() == QDialog.Accepted:
        ...
"""
import os
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QLineEdit, QProgressBar, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox,
    QSlider, QHeaderView, QButtonGroup, QMessageBox, QFrame, QGroupBox,
    QFormLayout, QRadioButton,
)
from PySide6.QtGui import QFont

import app_settings
from soundfont_manager import (
    SOUNDFONT_PRESETS, scan_installed_soundfonts, get_download_dir,
    SoundFontDownloader, verify_sf2,
)


# ============================================================
# 简易样式（跟随主题色，避免依赖 design_tokens 的复杂接口）
# ============================================================
def _build_dialog_style(theme_name: str = 'light') -> str:
    """根据主题返回对话框全局样式表。"""
    if theme_name == 'dark':
        return """
QDialog { background-color: #1A1E24; }
QTabWidget::pane { border: 1px solid #3a3a3f; border-radius: 8px; top: -1px; }
QTabBar::tab {
    background: #2a2a30; color: #b0b0b8; padding: 8px 16px;
    border-radius: 6px 6px 0 0; margin-right: 2px; font-size: 13px;
}
QTabBar::tab:selected { background: #3FA9C4; color: #ffffff; }
QGroupBox {
    border: 1px solid #3a3a3f; border-radius: 8px;
    margin-top: 12px; padding-top: 12px; font-weight: bold; color: #d0d0d8;
}
QGroupBox::title { left: 12px; padding: 0 6px; color: #3FA9C4; }
QPushButton {
    background-color: #3FA9C4; color: #ffffff; border: none;
    border-radius: 6px; padding: 6px 16px; font-size: 12px;
}
QPushButton:hover { background-color: #3594AC; }
QPushButton:pressed { background-color: #2B8095; }
QPushButton:disabled { background-color: #3a3a44; color: #666670; }
QPushButton#secondary { background-color: #2a2a30; color: #d0d0d8; }
QPushButton#secondary:hover { background-color: #3a3a44; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    border: 1px solid #3a3a3f; border-radius: 4px; padding: 4px 8px;
    background: #252830; color: #d0d0d8; font-size: 12px;
}
QSlider::groove:horizontal {
    height: 4px; background: #3a3a3f; border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #3FA9C4, stop:0.5 #3FB0A0, stop:1 #52BD8E);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #2a2a30; border: 2px solid #3FA9C4;
    width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
}
QListWidget, QTableWidget {
    border: 1px solid #3a3a3f; border-radius: 4px; background: #252830;
    font-size: 12px; color: #d0d0d8;
}
QLabel { color: #d0d0d8; }
QLabel#hint { color: #808088; font-size: 11px; }
QLabel#section { color: #3FA9C4; font-weight: bold; font-size: 13px; }
QCheckBox { color: #d0d0d8; }
QRadioButton { color: #d0d0d8; }
QTableView { color: #d0d0d8; background: #252830; }
QHeaderView::section { background: #2a2a30; color: #b0b0b8; }
"""
    return """
QDialog { background-color: #f5f5f7; }
QTabWidget::pane { border: 1px solid #d2d2d7; border-radius: 8px; top: -1px; }
QTabBar::tab {
    background: #e5e5ea; color: #1d1d1f; padding: 8px 16px;
    border-radius: 6px 6px 0 0; margin-right: 2px; font-size: 13px;
}
QTabBar::tab:selected { background: #3F95C0; color: white; }
QGroupBox {
    border: 1px solid #d2d2d7; border-radius: 8px;
    margin-top: 12px; padding-top: 12px; font-weight: bold;
}
QGroupBox::title { left: 12px; padding: 0 6px; color: #3F95C0; }
QPushButton {
    background-color: #3F95C0; color: white; border: none;
    border-radius: 6px; padding: 6px 16px; font-size: 12px;
}
QPushButton:hover { background-color: #3FB0A0; }
QPushButton:pressed { background-color: #2B8095; }
QPushButton:disabled { background-color: #d2d2d7; color: #8e8e93; }
QPushButton#secondary { background-color: #e5e5ea; color: #1d1d1f; }
QPushButton#secondary:hover { background-color: #d2d2d7; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    border: 1px solid #d2d2d7; border-radius: 4px; padding: 4px 8px;
    background: white; font-size: 12px;
}
QSlider::groove:horizontal {
    height: 4px; background: #d2d2d7; border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #3F95C0, stop:0.5 #3FB0A0, stop:1 #52BD8E);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: white; border: 2px solid #3F95C0;
    width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
}
QListWidget, QTableWidget {
    border: 1px solid #d2d2d7; border-radius: 4px; background: white;
    font-size: 12px;
}
QLabel { color: #1d1d1f; }
QLabel#hint { color: #8e8e93; font-size: 11px; }
QLabel#section { color: #3F95C0; font-weight: bold; font-size: 13px; }
"""


# ============================================================
# 音色管理 Tab
# ============================================================
class SoundFontTab(QWidget):
    """音色管理：已安装列表 + 预设下载 + 自定义 URL + 乐器选择。"""

    soundfont_changed = Signal()  # 用户切换了选中的 SF2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._downloader = None
        self._build_ui()
        self._refresh_installed()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- 已安装音色 ---
        installed_label = QLabel("已安装音色")
        installed_label.setObjectName("section")
        layout.addWidget(installed_label)

        self.installed_list = QListWidget()
        self.installed_list.setMinimumHeight(120)
        self.installed_list.currentRowChanged.connect(self._on_select_installed)
        layout.addWidget(self.installed_list)

        # 自定义 URL 下载
        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        url_label = QLabel("自定义 URL:")
        url_label.setMinimumWidth(80)
        url_row.addWidget(url_label)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/soundfont.sf2")
        url_row.addWidget(self.url_edit, 1)
        self.btn_download_url = QPushButton("下载")
        self.btn_download_url.clicked.connect(self._on_download_url)
        url_row.addWidget(self.btn_download_url)
        layout.addLayout(url_row)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setFixedHeight(24)
        self.progress.setMinimumWidth(300)
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        self.progress.setFormat("")
        self.progress.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.progress)

        # --- 预设音色 ---
        presets_label = QLabel("预设音色（点击下载）")
        presets_label.setObjectName("section")
        layout.addWidget(presets_label)

        self.presets_table = QTableWidget(len(SOUNDFONT_PRESETS), 5)
        self.presets_table.setHorizontalHeaderLabels(
            ["名称", "大小", "许可", "说明", "操作"]
        )
        self.presets_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.presets_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.presets_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.presets_table.verticalHeader().setVisible(False)
        self.presets_table.setEditTriggers(QTableWidget.NoEditTriggers)

        for i, preset in enumerate(SOUNDFONT_PRESETS):
            self.presets_table.setItem(i, 0, QTableWidgetItem(preset["name"]))
            self.presets_table.setItem(i, 1, QTableWidgetItem(f'{preset["size_mb"]} MB'))
            self.presets_table.setItem(i, 2, QTableWidgetItem(preset["license"]))
            self.presets_table.setItem(i, 3, QTableWidgetItem(preset["description"]))
            btn = QPushButton("下载")
            btn.clicked.connect(lambda checked=False, p=preset: self._on_download_preset(p))
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(2, 2, 2, 2)
            cell_layout.addWidget(btn)
            cell_layout.addStretch()
            self.presets_table.setCellWidget(i, 4, cell)

        layout.addWidget(self.presets_table)

        # --- 乐器选择 ---
        instr_row = QHBoxLayout()
        instr_label = QLabel("乐器 (MIDI Program):")
        instr_label.setMinimumWidth(120)
        instr_row.addWidget(instr_label)
        self.program_spin = QSpinBox()
        self.program_spin.setRange(0, 127)
        self.program_spin.setValue(app_settings.get_instrument_program())
        instr_row.addWidget(self.program_spin)
        instr_hint = QLabel("0=钢琴 40=小提琴 73=长笛 0~127可选")
        instr_hint.setObjectName("hint")
        instr_row.addWidget(instr_hint)
        instr_row.addStretch()
        layout.addLayout(instr_row)

        layout.addStretch()

    def _refresh_installed(self):
        """刷新已安装音色列表。"""
        self.installed_list.blockSignals(True)
        self.installed_list.clear()
        installed = scan_installed_soundfonts()
        current_path = app_settings.get_soundfont_path()

        # 第一个选项：自动检测
        auto_item = QListWidgetItem("🔄 自动检测（推荐）")
        auto_item.setData(Qt.UserRole, "")  # 空路径 = auto
        self.installed_list.addItem(auto_item)

        for sf in installed:
            label = f"🎹 {sf['name']}  ({sf['size_mb']} MB)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, sf["path"])
            self.installed_list.addItem(item)

        # 恢复选中状态（在 addItem 后设置，避免 setSelected 被忽略）
        self.installed_list.blockSignals(False)
        if not current_path:
            self.installed_list.setCurrentRow(0)
        else:
            for i in range(self.installed_list.count()):
                if self.installed_list.item(i).data(Qt.UserRole) == current_path:
                    self.installed_list.setCurrentRow(i)
                    break

    def _on_select_installed(self, row):
        """用户选了某个已安装 SF2。"""
        if row < 0:
            return
        item = self.installed_list.item(row)
        if not item:
            return
        path = item.data(Qt.UserRole)
        app_settings.set_many({"sf2.selected_path": path})
        self.soundfont_changed.emit()

    def _on_download_preset(self, preset):
        """点预设的下载按钮。"""
        dest = os.path.join(get_download_dir(), preset["name"] + ".sf2")
        if os.path.exists(dest):
            QMessageBox.information(
                self, "已存在",
                f"{preset['name']} 已下载。请在上方列表选中使用。"
            )
            return
        self._start_download(preset["url"], dest, preset["name"])

    def _on_download_url(self):
        """点自定义 URL 下载按钮。"""
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入 .sf2 的下载 URL")
            return
        if not url.lower().endswith(".sf2") and ".sf2?" not in url:
            reply = QMessageBox.question(
                self, "URL 看起来不是 .sf2",
                "URL 末尾不是 .sf2，确定继续下载？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        # 从 URL 提取文件名
        name = url.split("/")[-1].split("?")[0] or "custom.sf2"
        if not name.endswith(".sf2"):
            name += ".sf2"
        dest = os.path.join(get_download_dir(), name)
        self._start_download(url, dest, name)

    def _start_download(self, url, dest, label):
        """启动下载。"""
        if self._downloader is not None:
            QMessageBox.warning(self, "提示", "已有下载在跑，请等待或取消。")
            return

        self.progress.setVisible(True)
        self.progress.setRange(0, 100)  # 重置为确定模式
        self.progress.setValue(0)
        self.progress.setFormat(f"下载 {label}...")

        self._downloader = SoundFontDownloader()
        self._downloader.progress.connect(self._on_progress)
        self._downloader.finished.connect(lambda path: self._on_finished(path, label))
        self._downloader.failed.connect(self._on_failed)
        self._downloader.start_download(url, dest, label)

    def _on_progress(self, pct, msg):
        if pct >= 0:
            self.progress.setValue(pct)
        else:
            # 无 Content-Length 时，用 busy 动画（0-100 循环）
            self.progress.setRange(0, 0)  # 切换为不确定模式
        self.progress.setFormat(msg)

    def _on_finished(self, path, label):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat(f"{label} 下载完成")
        self._downloader = None
        # 自动选中新下载的 SF2
        app_settings.set_many({"sf2.selected_path": path})
        self._refresh_installed()
        QMessageBox.information(
            self, "下载成功",
            f"{label} 已下载并选中。点「应用」保存设置。"
        )

    def _on_failed(self, error):
        self.progress.setVisible(False)
        self._downloader = None
        QMessageBox.warning(self, "下载失败", error)

    def save(self):
        """保存当前 Tab 的设置到 app_settings。"""
        app_settings.set_many({
            "sf2.program": self.program_spin.value(),
        })


# ============================================================
# 分离模型 Tab
# ============================================================
class SeparationTab(QWidget):
    """分离模型参数：模型选择 / 下载源 / inference_params / 设备。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- 模型选择 ---
        model_group = QGroupBox("模型选择")
        model_layout = QFormLayout(model_group)
        self.model_combo = QComboBox()
        self.model_combo.addItem("Mel-Band RoFormer (big_beta7)", "big_beta7")
        self.model_combo.addItem("BS-RoFormer (HyperACE v2)", "bs_roformer_voc_hyperacev2")
        self.model_combo.addItem("SCNet (快速兜底)", "scnet_checkpoint_musdb18")
        model_layout.addRow("主模型:", self.model_combo)

        self.source_combo = QComboBox()
        self.source_combo.addItem("自动选择", "auto")
        self.source_combo.addItem("ModelScope (国内推荐)", "modelscope")
        self.source_combo.addItem("HF-Mirror (国外推荐)", "hf-mirror")
        model_layout.addRow("下载源:", self.source_combo)
        layout.addWidget(model_group)

        # --- 推理参数 ---
        infer_group = QGroupBox("推理参数（高级）")
        infer_layout = QFormLayout(infer_group)

        self.chunk_spin = QSpinBox()
        self.chunk_spin.setRange(1, 32)
        self.chunk_spin.setSuffix(" 秒")
        infer_layout.addRow("chunk_size:", self.chunk_spin)

        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 16)
        infer_layout.addRow("batch_size:", self.batch_spin)

        self.overlap_spin = QDoubleSpinBox()
        self.overlap_spin.setRange(0.1, 0.75)
        self.overlap_spin.setSingleStep(0.05)
        self.overlap_spin.setSuffix(" (比例)")
        infer_layout.addRow("overlap_size:", self.overlap_spin)

        hint = QLabel("值越大越精确但越慢。chunk_size 默认 8 秒，overlap 0.25 = 25% 重叠。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        infer_layout.addRow(hint)
        layout.addWidget(infer_group)

        # --- 设备 ---
        device_group = QGroupBox("设备")
        device_layout = QFormLayout(device_group)

        self.sep_device_combo = QComboBox()
        self.sep_device_combo.addItem("自动", "auto")
        self.sep_device_combo.addItem("CUDA (GPU)", "cuda")
        self.sep_device_combo.addItem("CPU", "cpu")
        device_layout.addRow("分离设备:", self.sep_device_combo)

        self.trans_device_combo = QComboBox()
        self.trans_device_combo.addItem("自动", "auto")
        self.trans_device_combo.addItem("CUDA (GPU)", "cuda")
        self.trans_device_combo.addItem("CPU", "cpu")
        device_layout.addRow("转录设备:", self.trans_device_combo)
        layout.addWidget(device_group)

        layout.addStretch()

    def _load_values(self):
        cfg = app_settings.load_settings()
        sep = cfg.get("sep", {})
        # 找 model_combo 的索引
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == sep.get("model_name", "big_beta7"):
                self.model_combo.setCurrentIndex(i)
                break
        for i in range(self.source_combo.count()):
            if self.source_combo.itemData(i) == sep.get("source", "auto"):
                self.source_combo.setCurrentIndex(i)
                break
        inf = sep.get("inference", {})
        self.chunk_spin.setValue(int(inf.get("chunk_size", 8)))
        self.batch_spin.setValue(int(inf.get("batch_size", 2)))
        self.overlap_spin.setValue(float(inf.get("overlap_size", 0.25)))

        dev = cfg.get("device", {})
        for i in range(self.sep_device_combo.count()):
            if self.sep_device_combo.itemData(i) == dev.get("separation", "auto"):
                self.sep_device_combo.setCurrentIndex(i)
                break
        for i in range(self.trans_device_combo.count()):
            if self.trans_device_combo.itemData(i) == dev.get("transcription", "auto"):
                self.trans_device_combo.setCurrentIndex(i)
                break

    def save(self):
        app_settings.set_many({
            "sep.model_name": self.model_combo.currentData(),
            "sep.source": self.source_combo.currentData(),
            "sep.inference.chunk_size": self.chunk_spin.value(),
            "sep.inference.batch_size": self.batch_spin.value(),
            "sep.inference.overlap_size": self.overlap_spin.value(),
            "device.separation": self.sep_device_combo.currentData(),
            "device.transcription": self.trans_device_combo.currentData(),
        })


# ============================================================
# 高级参数 Tab（灵敏度 + 降噪的持久化默认值）
# ============================================================
class AdvancedTab(QWidget):
    """高级参数：镜像分析页的灵敏度/降噪滑块，作为启动默认值。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        hint = QLabel("这里是分析页滑块的启动默认值。修改后下次启动 app 会自动加载到分析页。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # --- 人声 ---
        vocal_group = QGroupBox("人声转录参数")
        vlayout = QFormLayout(vocal_group)

        self.vocal_onset = QSlider(Qt.Horizontal)
        self.vocal_onset.setRange(30, 80)
        self.vocal_onset_label = QLabel("50")
        self.vocal_onset.valueChanged.connect(
            lambda v: self.vocal_onset_label.setText(str(v)))
        onset_row = QHBoxLayout()
        onset_row.addWidget(self.vocal_onset, 1)
        onset_row.addWidget(self.vocal_onset_label)
        vlayout.addRow("onset 阈值 (30-80):", onset_row)

        self.vocal_frame = QSlider(Qt.Horizontal)
        self.vocal_frame.setRange(10, 60)
        self.vocal_frame_label = QLabel("30")
        self.vocal_frame.valueChanged.connect(
            lambda v: self.vocal_frame_label.setText(str(v)))
        frame_row = QHBoxLayout()
        frame_row.addWidget(self.vocal_frame, 1)
        frame_row.addWidget(self.vocal_frame_label)
        vlayout.addRow("frame 阈值 (10-60):", frame_row)

        self.vocal_minlen = QSlider(Qt.Horizontal)
        self.vocal_minlen.setRange(40, 200)
        self.vocal_minlen_label = QLabel("80")
        self.vocal_minlen.valueChanged.connect(
            lambda v: self.vocal_minlen_label.setText(f"{v}ms"))
        minlen_row = QHBoxLayout()
        minlen_row.addWidget(self.vocal_minlen, 1)
        minlen_row.addWidget(self.vocal_minlen_label)
        vlayout.addRow("最短音符 (40-200ms):", minlen_row)

        layout.addWidget(vocal_group)

        # --- 伴奏 ---
        accomp_group = QGroupBox("伴奏转录参数")
        alayout = QFormLayout(accomp_group)

        self.accomp_sens = QSlider(Qt.Horizontal)
        self.accomp_sens.setRange(0, 100)
        self.accomp_sens_label = QLabel("50")
        self.accomp_sens.valueChanged.connect(
            lambda v: self.accomp_sens_label.setText(str(v)))
        sens_row = QHBoxLayout()
        sens_row.addWidget(self.accomp_sens, 1)
        sens_row.addWidget(self.accomp_sens_label)
        alayout.addRow("灵敏度 (0-100):", sens_row)

        self.accomp_min_dur = QSlider(Qt.Horizontal)
        self.accomp_min_dur.setRange(40, 300)
        self.accomp_min_dur_label = QLabel("80ms")
        self.accomp_min_dur.valueChanged.connect(
            lambda v: self.accomp_min_dur_label.setText(f"{v}ms"))
        dur_row = QHBoxLayout()
        dur_row.addWidget(self.accomp_min_dur, 1)
        dur_row.addWidget(self.accomp_min_dur_label)
        alayout.addRow("最短音符 (40-300ms):", dur_row)

        self.accomp_max_poly = QSlider(Qt.Horizontal)
        self.accomp_max_poly.setRange(2, 10)
        self.accomp_max_poly_label = QLabel("6")
        self.accomp_max_poly.valueChanged.connect(
            lambda v: self.accomp_max_poly_label.setText(str(v)))
        poly_row = QHBoxLayout()
        poly_row.addWidget(self.accomp_max_poly, 1)
        poly_row.addWidget(self.accomp_max_poly_label)
        alayout.addRow("最大和弦 (2-10):", poly_row)

        layout.addWidget(accomp_group)

        # --- 降噪 ---
        denoise_group = QGroupBox("降噪参数")
        dlayout = QFormLayout(denoise_group)

        self.denoise_threshold = QSlider(Qt.Horizontal)
        self.denoise_threshold.setRange(0, 50)
        self.denoise_threshold_label = QLabel("25")
        self.denoise_threshold.valueChanged.connect(
            lambda v: self.denoise_threshold_label.setText(str(v)))
        dt_row = QHBoxLayout()
        dt_row.addWidget(self.denoise_threshold, 1)
        dt_row.addWidget(self.denoise_threshold_label)
        dlayout.addRow("删除阈值 (0-50):", dt_row)

        self.denoise_min_dur = QSlider(Qt.Horizontal)
        self.denoise_min_dur.setRange(20, 200)
        self.denoise_min_dur_label = QLabel("80ms")
        self.denoise_min_dur.valueChanged.connect(
            lambda v: self.denoise_min_dur_label.setText(f"{v}ms"))
        dd_row = QHBoxLayout()
        dd_row.addWidget(self.denoise_min_dur, 1)
        dd_row.addWidget(self.denoise_min_dur_label)
        dlayout.addRow("最短音符 (20-200ms):", dd_row)

        self.denoise_chord = QSlider(Qt.Horizontal)
        self.denoise_chord.setRange(0, 100)
        self.denoise_chord_label = QLabel("25")
        self.denoise_chord.valueChanged.connect(
            lambda v: self.denoise_chord_label.setText(str(v)))
        dc_row = QHBoxLayout()
        dc_row.addWidget(self.denoise_chord, 1)
        dc_row.addWidget(self.denoise_chord_label)
        dlayout.addRow("和弦严格度 (0-100):", dc_row)

        self.denoise_max_jump = QSlider(Qt.Horizontal)
        self.denoise_max_jump.setRange(6, 24)
        self.denoise_max_jump_label = QLabel("12")
        self.denoise_max_jump.valueChanged.connect(
            lambda v: self.denoise_max_jump_label.setText(str(v)))
        dj_row = QHBoxLayout()
        dj_row.addWidget(self.denoise_max_jump, 1)
        dj_row.addWidget(self.denoise_max_jump_label)
        dlayout.addRow("最大音程跳 (6-24):", dj_row)

        self.denoise_max_poly = QSlider(Qt.Horizontal)
        self.denoise_max_poly.setRange(2, 10)
        self.denoise_max_poly_label = QLabel("6")
        self.denoise_max_poly.valueChanged.connect(
            lambda v: self.denoise_max_poly_label.setText(str(v)))
        dp_row = QHBoxLayout()
        dp_row.addWidget(self.denoise_max_poly, 1)
        dp_row.addWidget(self.denoise_max_poly_label)
        dlayout.addRow("最大和弦 (2-10):", dp_row)

        layout.addWidget(denoise_group)

        # 重置按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_reset = QPushButton("重置为默认值")
        btn_reset.setObjectName("secondary")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_row.addWidget(btn_reset)
        layout.addLayout(btn_row)

        layout.addStretch()

    def _load_values(self):
        cfg = app_settings.load_settings()
        s = cfg.get("sensitivity", {})
        self.vocal_onset.setValue(int(s.get("vocal_onset", 50)))
        self.vocal_frame.setValue(int(s.get("vocal_frame", 30)))
        self.vocal_minlen.setValue(int(s.get("vocal_minlen", 80)))
        self.accomp_sens.setValue(int(s.get("accomp_sens", 50)))
        self.accomp_min_dur.setValue(int(s.get("accomp_min_dur", 80)))
        self.accomp_max_poly.setValue(int(s.get("accomp_max_poly", 6)))

        d = cfg.get("denoise", {})
        self.denoise_threshold.setValue(int(d.get("threshold", 25)))
        self.denoise_min_dur.setValue(int(d.get("min_duration_ms", 80)))
        self.denoise_chord.setValue(int(d.get("chord_strictness", 25)))
        self.denoise_max_jump.setValue(int(d.get("max_jump", 12)))
        self.denoise_max_poly.setValue(int(d.get("max_polyphony", 6)))

    def _reset_defaults(self):
        self.vocal_onset.setValue(50)
        self.vocal_frame.setValue(30)
        self.vocal_minlen.setValue(80)
        self.accomp_sens.setValue(50)
        self.accomp_min_dur.setValue(80)
        self.accomp_max_poly.setValue(6)
        self.denoise_threshold.setValue(25)
        self.denoise_min_dur.setValue(80)
        self.denoise_chord.setValue(25)
        self.denoise_max_jump.setValue(12)
        self.denoise_max_poly.setValue(6)

    def save(self):
        app_settings.set_many({
            "sensitivity.vocal_onset": self.vocal_onset.value(),
            "sensitivity.vocal_frame": self.vocal_frame.value(),
            "sensitivity.vocal_minlen": self.vocal_minlen.value(),
            "sensitivity.accomp_sens": self.accomp_sens.value(),
            "sensitivity.accomp_min_dur": self.accomp_min_dur.value(),
            "sensitivity.accomp_max_poly": self.accomp_max_poly.value(),
            "denoise.threshold": self.denoise_threshold.value(),
            "denoise.min_duration_ms": self.denoise_min_dur.value(),
            "denoise.chord_strictness": self.denoise_chord.value(),
            "denoise.max_jump": self.denoise_max_jump.value(),
            "denoise.max_polyphony": self.denoise_max_poly.value(),
        })


# ============================================================
# 音频输出 Tab
# ============================================================
class AudioTab(QWidget):
    """音频输出：采样率 / 增益 / 混响。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        group = QGroupBox("音频输出")
        form = QFormLayout(group)

        self.sr_combo = QComboBox()
        self.sr_combo.addItem("22050 Hz (低质量)", 22050)
        self.sr_combo.addItem("44100 Hz (CD 质量)", 44100)
        self.sr_combo.addItem("48000 Hz (DVD 质量)", 48000)
        form.addRow("采样率:", self.sr_combo)

        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(0.1, 1.0)
        self.gain_spin.setSingleStep(0.1)
        self.gain_spin.setSuffix(" (0-1)")
        form.addRow("增益:", self.gain_spin)

        self.reverb_check = QCheckBox("启用混响")
        form.addRow("", self.reverb_check)

        self.room_spin = QDoubleSpinBox()
        self.room_spin.setRange(0.0, 1.0)
        self.room_spin.setSingleStep(0.1)
        self.room_spin.setSuffix(" (0-1)")
        form.addRow("混响大小:", self.room_spin)

        hint = QLabel("增益 0.5 = 默认，1.0 = 最响。混响会让钢琴声音更有空间感。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow(hint)

        layout.addWidget(group)
        layout.addStretch()

    def _load_values(self):
        cfg = app_settings.load_settings().get("audio", {})
        sr = int(cfg.get("sample_rate", 44100))
        for i in range(self.sr_combo.count()):
            if self.sr_combo.itemData(i) == sr:
                self.sr_combo.setCurrentIndex(i)
                break
        self.gain_spin.setValue(float(cfg.get("gain", 0.5)))
        rev = cfg.get("reverb", {})
        self.reverb_check.setChecked(bool(rev.get("active", True)))
        self.room_spin.setValue(float(rev.get("room_size", 0.7)))

    def save(self):
        app_settings.set_many({
            "audio.sample_rate": self.sr_combo.currentData(),
            "audio.gain": self.gain_spin.value(),
            "audio.reverb.active": self.reverb_check.isChecked(),
            "audio.reverb.room_size": self.room_spin.value(),
        })


# ============================================================
# 性能与模型 Tab
# ============================================================
class PerformanceTab(QWidget):
    """性能与模型：硬件检测 + GPU/CUDA 状态 + 模型选择入口。

    此 Tab 显示硬件信息，并提供「打开性能与模型对话框」按钮，
    点击后调用 parent（PianoApp）的 _show_gpu_model_dialog。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 标题
        title = QLabel("性能与模型")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # 硬件信息显示区
        self.hw_label = QLabel("正在检测硬件...")
        self.hw_label.setWordWrap(True)
        layout.addWidget(self.hw_label)

        # 状态提示
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 13px; padding: 8px;")
        layout.addWidget(self.status_label)

        layout.addStretch()

        # 打开性能对话框按钮
        self.btn_open_dialog = QPushButton("打开性能与模型对话框")
        self.btn_open_dialog.setMinimumHeight(40)
        self.btn_open_dialog.setStyleSheet("""
            QPushButton {
                background-color: #3FA9C4; color: white; border: none;
                border-radius: 10px; padding: 10px; font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3594AC; }
        """)
        layout.addWidget(self.btn_open_dialog)

        # 首次显示时检测硬件
        self._detect_hardware()

    def _detect_hardware(self):
        """检测硬件并更新显示。"""
        import platform
        import subprocess

        # CPU
        cpu_name = platform.processor() or '未知'
        cpu_cores = os.cpu_count() or 4

        # 内存
        ram_gb = 0.0
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            ram_gb = round(stat.ullTotalPhys / 1024**3, 1)
        except Exception:
            pass

        # NVIDIA GPU
        has_nvidia = False
        gpu_name = ''
        gpu_vram = 0.0
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                line = result.stdout.strip().split('\n')[0]
                parts = [p.strip() for p in line.split(',')]
                has_nvidia = True
                gpu_name = parts[0] if parts else 'NVIDIA GPU'
                if len(parts) > 1:
                    try:
                        gpu_vram = round(float(parts[1]) / 1024, 1)
                    except (ValueError, IndexError):
                        pass
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

        # torch CUDA
        has_cuda = False
        try:
            import torch
            has_cuda = torch.cuda.is_available()
        except Exception:
            pass

        # 更新显示
        hw_text = f"CPU: {cpu_name}\n核心数: {cpu_cores}  |  内存: {ram_gb} GB"
        if has_nvidia:
            hw_text += f"\nGPU: {gpu_name}  (VRAM: {gpu_vram} GB)"
            if has_cuda:
                hw_text += "  [CUDA 已启用 ✓]"
                self.status_label.setText("✓ CUDA 加速已启用，分离速度正常")
                self.status_label.setStyleSheet("color: #3FA9C4; font-size: 13px; padding: 8px;")
            else:
                hw_text += "  [CUDA 未启用]"
                self.status_label.setText(
                    "⚠ 检测到 NVIDIA 显卡，但未安装 CUDA 版 torch。\n"
                    "点击下方按钮安装 CUDA 版 torch 以获得 10-20 倍加速。")
                self.status_label.setStyleSheet("color: #FF6B6B; font-size: 13px; padding: 8px;")
        else:
            hw_text += "\nGPU: 未检测到 NVIDIA 显卡"
            self.status_label.setText(
                "⚠ 当前使用 CPU 运行，音频分离较慢。\n"
                "点击下方按钮查看推荐的快速模型。")
            self.status_label.setStyleSheet("color: #FF6B6B; font-size: 13px; padding: 8px;")
        self.hw_label.setText(hw_text)


# ============================================================
# 主对话框
# ============================================================
class SettingsDialog(QDialog):
    """设置对话框：5 Tab（音色 / 分离 / 性能 / 高级 / 音频）。"""

    settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(640, 580)
        # 检测当前主题并应用对应样式
        self._current_dialog_theme = 'light'
        try:
            from design_tokens import get_current_theme_name
            self._current_dialog_theme = get_current_theme_name()
        except Exception:
            pass
        self.setStyleSheet(_build_dialog_style(self._current_dialog_theme))

        self.sf2_tab = SoundFontTab()
        self.sep_tab = SeparationTab()
        self.perf_tab = PerformanceTab()
        self.adv_tab = AdvancedTab()
        self.audio_tab = AudioTab()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.sf2_tab, "音色管理")
        self.tabs.addTab(self.sep_tab, "分离模型")
        self.tabs.addTab(self.perf_tab, "性能与模型")
        self.tabs.addTab(self.adv_tab, "高级参数")
        self.tabs.addTab(self.audio_tab, "音频输出")

        # 音色切换时立即通知（让用户能马上听到效果，不用等确定）
        self.sf2_tab.soundfont_changed.connect(self.settings_changed)

        # 性能与模型 Tab 的按钮 → 调用主窗口的对话框
        self.perf_tab.btn_open_dialog.clicked.connect(self._open_perf_dialog)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(btn_ok)

        btn_apply = QPushButton("应用")
        btn_apply.setObjectName("secondary")
        btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(btn_apply)

        layout.addLayout(btn_row)

    def _on_ok(self):
        self._save_all()
        self.settings_changed.emit()
        self.accept()

    def _on_apply(self):
        self._save_all()
        self.settings_changed.emit()

    def _open_perf_dialog(self):
        """打开主窗口的性能与模型对话框。"""
        parent = self.parent()
        if parent is not None and hasattr(parent, '_show_gpu_model_dialog'):
            parent._show_gpu_model_dialog()

    def _save_all(self):
        self.sf2_tab.save()
        self.sep_tab.save()
        self.adv_tab.save()
        self.audio_tab.save()
