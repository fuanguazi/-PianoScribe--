# -*- mode: python ; coding: utf-8 -*-
"""PianoScribe PyInstaller spec file."""

import os
import sys
import importlib

APP_DIR = r'D:\PianoTraining\app'

# Collect hidden imports
hiddenimports = [
    'PySide6.QtWidgets',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    'pretty_midi',
    'pretty_midi.fluidsynth',
    'basic_pitch',
    'basic_pitch.inference',
    'music21',
    'music21.converter',
    'music21.stream',
    'music21.note',
    'music21.meter',
    'music21.key',
    'music21.clef',
    'music21.layout',
    'music21.lily.translate',
    'pygame',
    'numpy',
    'scipy',
    'scipy.signal',
    'scipy.ndimage',
    'torch',
    'torch.nn',
    'torch.utils',
    'torch.utils.data',
    'onnxruntime',
    'pydub',
    'pyfluidsynth',
    'soundfile',
    'resampy',
    'librosa',
    'mido',
    'py7zr',
    'PIL',
]

# Collect data files
datas = [
    # FluidR3_GM soundfont
    (os.path.join(APP_DIR, 'FluidR3_GM.sf2'), '.'),
    # Application icon
    (os.path.join(APP_DIR, 'pianoscribe_icon.ico'), '.'),
    (os.path.join(APP_DIR, 'pianoscribe_icon.png'), '.'),
    # LilyPond
    (os.path.join(APP_DIR, 'lilypond-2.24.4'), 'lilypond-2.24.4'),
    # pretty_midi default soundfont
    (os.path.join(os.path.dirname(importlib.import_module('pretty_midi').__file__), 'TimGM6mb.sf2'), 'pretty_midi'),
    # basic_pitch model
    (os.path.dirname(importlib.import_module('basic_pitch').__file__), 'basic_pitch'),
]

# Collect binary files (FluidSynth DLL)
binaries = []
fs_dll_dir = r'C:\tools\fluidsynth-temp\bin'
if os.path.isdir(fs_dll_dir):
    for f in os.listdir(fs_dll_dir):
        if f.endswith('.dll'):
            binaries.append((os.path.join(fs_dll_dir, f), 'fluidsynth_bin'))

a = Analysis(
    [os.path.join(APP_DIR, 'piano_app.py')],
    pathex=[APP_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'tkinter', 'IPython', 'jupyter',
        'notebook', 'sphinx', 'pytest', 'setuptools',
        'pip', 'wheel', 'distutils',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='PianoScribe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=os.path.join(APP_DIR, 'pianoscribe_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='PianoScribe',
)
