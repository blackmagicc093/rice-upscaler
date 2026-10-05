# -*- mode: python ; coding: utf-8 -*-
# Build with PyInstaller spec:
#   pyinstaller --clean UpscaleApp.spec
# Or with CLI flags:
#   pyinstaller --noconfirm --onedir --windowed --icon assets/icon/rice.ico --name RiceUpscale src/main.py

a = Analysis(
    ['src\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('tools', 'tools'), ('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [('O', None, 'OPTION'), ('O', None, 'OPTION')],
    name='RiceUpscale',
    icon=['assets\\icon\\rice.ico'],
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
