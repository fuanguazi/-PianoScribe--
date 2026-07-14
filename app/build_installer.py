"""PianoScribe Installer Builder

Creates a single-file installer EXE with a GUI installer.
The installer will:
1. Show a welcome screen with PianoScribe branding
2. Let user choose install directory
3. Extract all files from embedded payload
4. Create desktop and start menu shortcuts
5. Create uninstaller
"""
import os
import sys
import shutil
import subprocess

DIST_DIR = r'D:\多多\PianoTraining\app\dist\PianoScribe'
ICON_PATH = r'D:\多多\PianoTraining\app\pianoscribe_icon.ico'
OUTPUT_DIR = r'D:\多多\PianoTraining\app\installer_output'

INSTALLER_SCRIPT = r"""
import os
import sys
import shutil
import subprocess
import ctypes

APP_NAME = "PianoScribe"
APP_VERSION = "0.7 beta"
PUBLISHER = "PianoScribe Team"
EXE_NAME = "PianoScribe.exe"
ICON_RES = "pianoscribe_icon.ico"

def create_shortcut(target, shortcut_path, description="", icon_path=""):
    target = str(target).replace("'", "''")
    shortcut_path = str(shortcut_path).replace("'", "''")
    icon_path = str(icon_path).replace("'", "''") if icon_path else ""
    ps_cmd = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$sc = $ws.CreateShortcut('" + shortcut_path + "'); "
        "$sc.TargetPath = '" + target + "'; "
        "$sc.WorkingDirectory = '" + os.path.dirname(target) + "'; "
        "$sc.Description = '" + description + "'; "
    )
    if icon_path:
        ps_cmd += "$sc.IconLocation = '" + icon_path + "'; "
    ps_cmd += "$sc.Save()"
    subprocess.run(['powershell', '-NoProfile', '-Command', ps_cmd],
                   capture_output=True, timeout=10)

def main():
    from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QLineEdit, QPushButton, QFileDialog, QProgressBar, QCheckBox, QMessageBox)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette, QColor, QIcon

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#1a1a2e"))
    palette.setColor(QPalette.WindowText, QColor("#e0e0e0"))
    palette.setColor(QPalette.Base, QColor("#16213e"))
    palette.setColor(QPalette.AlternateBase, QColor("#1a1a2e"))
    palette.setColor(QPalette.Text, QColor("#e0e0e0"))
    palette.setColor(QPalette.Button, QColor("#0f3460"))
    palette.setColor(QPalette.ButtonText, QColor("#e0e0e0"))
    palette.setColor(QPalette.Highlight, QColor("#6ea8fe"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    window = QWidget()
    window.setWindowTitle(APP_NAME + " Setup")
    window.setFixedSize(600, 450)
    window.setStyleSheet("background-color: #1a1a2e; color: #e0e0e0;")

    layout = QVBoxLayout(window)
    layout.setContentsMargins(40, 30, 40, 30)
    layout.setSpacing(15)

    title = QLabel(APP_NAME)
    title.setAlignment(Qt.AlignCenter)
    title.setStyleSheet("font-size: 36px; font-weight: bold; color: #6ea8fe; border: none;")
    layout.addWidget(title)

    subtitle = QLabel("Professional AI Piano Sheet Music Generator v" + APP_VERSION)
    subtitle.setAlignment(Qt.AlignCenter)
    subtitle.setStyleSheet("font-size: 14px; color: #a0a0c0; border: none;")
    layout.addWidget(subtitle)

    layout.addSpacing(20)

    dir_label = QLabel("\u5b89\u88c5\u76ee\u5f55:")
    dir_label.setStyleSheet("font-size: 13px; border: none;")
    layout.addWidget(dir_label)

    dir_layout = QHBoxLayout()
    default_dir = os.path.join(os.environ.get('PROGRAMFILES', r'C:\Program Files'), APP_NAME)
    dir_input = QLineEdit(default_dir)
    dir_input.setStyleSheet("padding: 8px; border-radius: 4px; background: #16213e; color: #e0e0e0; border: 1px solid #0f3460;")
    dir_layout.addWidget(dir_input)

    browse_btn = QPushButton("\u6d4f\u89c8...")
    browse_btn.setStyleSheet("padding: 8px 16px; border-radius: 4px; background: #0f3460; color: #e0e0e0; border: none;")
    browse_btn.setCursor(Qt.PointingHandCursor)

    def browse():
        path = QFileDialog.getExistingDirectory(window, "\u9009\u62e9\u5b89\u88c5\u76ee\u5f55")
        if path:
            dir_input.setText(path)
    browse_btn.clicked.connect(browse)
    dir_layout.addWidget(browse_btn)
    layout.addLayout(dir_layout)

    desktop_cb = QCheckBox("\u521b\u5efa\u684c\u9762\u5feb\u6377\u65b9\u5f0f")
    desktop_cb.setChecked(True)
    desktop_cb.setStyleSheet("border: none; color: #e0e0e0;")
    layout.addWidget(desktop_cb)

    startmenu_cb = QCheckBox("\u521b\u5efa\u5f00\u59cb\u83dc\u5355\u5feb\u6377\u65b9\u5f0f")
    startmenu_cb.setChecked(True)
    startmenu_cb.setStyleSheet("border: none; color: #e0e0e0;")
    layout.addWidget(startmenu_cb)

    layout.addSpacing(10)

    progress = QProgressBar()
    progress.setVisible(False)
    progress.setStyleSheet("border-radius: 4px; text-align: center; background: #16213e; border: none;")
    progress.setMaximum(100)
    layout.addWidget(progress)

    status_label = QLabel("")
    status_label.setAlignment(Qt.AlignCenter)
    status_label.setStyleSheet("font-size: 12px; color: #a0a0c0; border: none;")
    layout.addWidget(status_label)

    btn_layout = QHBoxLayout()
    btn_layout.addStretch()

    install_btn = QPushButton("\u5b89\u88c5")
    install_btn.setStyleSheet(
        "QPushButton { padding: 10px 40px; border-radius: 6px; background: #6ea8fe; "
        "color: #0a0e27; font-weight: bold; font-size: 14px; border: none; }"
        "QPushButton:hover { background: #8ec0ff; }"
    )
    install_btn.setCursor(Qt.PointingHandCursor)
    install_btn.setMinimumWidth(120)
    btn_layout.addWidget(install_btn)

    close_btn = QPushButton("\u5173\u95ed")
    close_btn.setVisible(False)
    close_btn.setStyleSheet(
        "QPushButton { padding: 10px 40px; border-radius: 6px; background: #0f3460; "
        "color: #e0e0e0; font-size: 14px; border: none; }"
        "QPushButton:hover { background: #1a4a8a; }"
    )
    close_btn.setCursor(Qt.PointingHandCursor)
    close_btn.setMinimumWidth(120)
    btn_layout.addWidget(close_btn)

    layout.addLayout(btn_layout)

    def do_install():
        install_dir = dir_input.text()
        if not install_dir:
            QMessageBox.warning(window, "\u9519\u8bef", "\u8bf7\u9009\u62e9\u5b89\u88c5\u76ee\u5f55")
            return

        install_btn.setEnabled(False)
        browse_btn.setEnabled(False)
        dir_input.setEnabled(False)
        desktop_cb.setEnabled(False)
        startmenu_cb.setEnabled(False)
        progress.setVisible(True)

        payload_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'payload')
        if not os.path.isdir(payload_dir):
            payload_dir = os.path.join(getattr(sys, '_MEIPASS', ''), 'payload')
        if not os.path.isdir(payload_dir):
            QMessageBox.critical(window, "\u9519\u8bef", "\u627e\u4e0d\u5230\u5b89\u88c5\u6587\u4ef6")
            install_btn.setEnabled(True)
            return

        all_files = []
        for root, dirs, files in os.walk(payload_dir):
            for f in files:
                src = os.path.join(root, f)
                rel = os.path.relpath(src, payload_dir)
                all_files.append((src, rel))

        total = len(all_files)
        os.makedirs(install_dir, exist_ok=True)

        for i, (src, rel) in enumerate(all_files):
            dst = os.path.join(install_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            pct = int((i + 1) / total * 90)
            progress.setValue(pct)
            status_label.setText("\u6b63\u5728\u5b89\u88c5: " + rel[:50] + "...")
            app.processEvents()

        exe_path = os.path.join(install_dir, EXE_NAME)
        icon_path = os.path.join(install_dir, ICON_RES)

        if desktop_cb.isChecked():
            desktop = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop')
            create_shortcut(exe_path, os.path.join(desktop, APP_NAME + ".lnk"), APP_NAME,
                          icon_path if os.path.exists(icon_path) else "")

        if startmenu_cb.isChecked():
            start_menu = os.path.join(os.environ.get('APPDATA', ''),
                                      r'Microsoft\Windows\Start Menu\Programs')
            os.makedirs(os.path.join(start_menu, APP_NAME), exist_ok=True)
            create_shortcut(exe_path,
                          os.path.join(start_menu, APP_NAME, APP_NAME + ".lnk"),
                          APP_NAME, icon_path if os.path.exists(icon_path) else "")

        # Create uninstaller
        uninstall_lines = [
            "@echo off",
            "chcp 65001 >nul",
            "echo Uninstalling " + APP_NAME + "...",
            'set /p confirm=Uninstall ' + APP_NAME + ' ? (Y/N):',
            'if /i "%confirm%"=="Y" (',
            "  echo Removing files...",
            '  rd /s /q "' + install_dir + '"',
            "  echo Removing shortcuts...",
            '  del /q "%USERPROFILE%\\Desktop\\' + APP_NAME + '.lnk" 2>nul',
            '  rd /s /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\' + APP_NAME + '" 2>nul',
            "  echo Done!",
            "  pause",
            ") else (",
            "  echo Cancelled.",
            "  pause",
            ")",
        ]
        with open(os.path.join(install_dir, "uninstall.bat"), 'w', encoding='utf-8') as f:
            f.write('\n'.join(uninstall_lines))

        # Register uninstaller
        try:
            import winreg
            key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\\" + APP_NAME)
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ,
                os.path.join(install_dir, "uninstall.bat"))
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ,
                icon_path if os.path.exists(icon_path) else exe_path)
            winreg.CloseKey(key)
        except Exception:
            pass

        progress.setValue(100)
        status_label.setText("\u5b89\u88c5\u5b8c\u6210!")
        install_btn.setVisible(False)
        close_btn.setVisible(True)
        QMessageBox.information(window, "\u5b89\u88c5\u5b8c\u6210",
            APP_NAME + " \u5df2\u6210\u529f\u5b89\u88c5\u5230:\n" + install_dir)

    install_btn.clicked.connect(do_install)
    close_btn.clicked.connect(window.close)

    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
"""


def build_installer():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Write installer script
    installer_py = os.path.join(OUTPUT_DIR, 'pianoscribe_setup.py')
    with open(installer_py, 'w', encoding='utf-8') as f:
        f.write(INSTALLER_SCRIPT)

    # Build with PyInstaller - embed the entire dist as payload
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', 'PianoScribe_Setup',
        '--windowed',
        '--icon', ICON_PATH,
        '--add-data', f'{DIST_DIR};payload',
        '--noconfirm',
        '--clean',
        '--exclude-module', 'tensorflow',
        '--exclude-module', 'torch',
        '--exclude-module', 'keras',
        installer_py,
    ]

    print("Building installer (this may take a while)...")
    print(f"Payload: {DIST_DIR}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=OUTPUT_DIR)

    if result.returncode != 0:
        print(f"STDERR: {result.stderr[-3000:]}")
        print("Build failed!")
        return False

    # Check output
    exe_path = os.path.join(OUTPUT_DIR, 'dist', 'PianoScribe_Setup', 'PianoScribe_Setup.exe')
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / 1024 / 1024
        print(f"Installer created: {exe_path} ({size_mb:.1f} MB)")
        return True
    else:
        print("Installer EXE not found!")
        # Try to find it
        for root, dirs, files in os.walk(os.path.join(OUTPUT_DIR, 'dist')):
            for f in files:
                if f.endswith('.exe'):
                    print(f"  Found: {os.path.join(root, f)}")
        return False


if __name__ == '__main__':
    build_installer()
