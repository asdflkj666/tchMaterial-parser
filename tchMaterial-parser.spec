# -*- mode: python ; coding: utf-8 -*-
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

is_mac = sys.platform.startswith('darwin')

def package_version() -> str:
    """从 pyproject.toml 读取版本号，让产物文件名自动带上版本。

    版本号只维护两处：pyproject.toml（程序显示用）与 version_info.txt（exe 属性用）。
    这里现读现用，改版本时不必再改 spec；读不到就退回不带版本号的文件名。
    """
    try:
        text = Path("pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else ""

pkg_version = package_version()
# 产物文件名里不用 PEP 440 本地版本段的 '+'（4.3+fork.1 → 4.3-fork.1），
# 与 GitHub tag（v4.3-fork.1）写法保持一致。
version_label = pkg_version.replace("+", "-")
app_name = f"tchMaterial-parser-v{version_label}" if version_label else "tchMaterial-parser"

# sv-ttk 通过 Path(__file__).with_name() 加载主题文件，需把随包的 .tcl 与 .png 一并收集进来；图标文件是程序运行时读取的自有资源
runtime_assets = [
    (str(path), "tchmaterial_parser/assets")
    for path in Path("src/tchmaterial_parser/assets").glob("*.png")
]
data_files = collect_data_files("sv_ttk") + runtime_assets

a = Analysis(
    # 入口位于包外：PyInstaller 会把入口脚本当作 __main__ 分析，包内脚本的相对导入在此情形下不成立
    # pathex 指向 src/，使入口里的 import tchmaterial_parser 能被解析到
    ['src/main.py'],
    pathex=['src'],
    binaries=[],
    datas=data_files,
    # Pillow 的 _imagingtk 在非 Windows 平台通过 C 层动态导入此模块，PyInstaller 无法静态发现
    hiddenimports=["PIL._tkinter_finder"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)


if is_mac:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=app_name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=True,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name=app_name,
    )

    app = BUNDLE(
        coll,
        name=f'{app_name}.app',
        icon='assets/logo.icns',
        bundle_identifier=None,
    )

else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=app_name,
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
        version='version_info.txt',
        icon=['assets/icon.ico'],
    )
