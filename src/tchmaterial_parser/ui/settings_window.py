# -*- coding: utf-8 -*-
# 下载设置窗口：并发、限流熔断、重试等下载技术配置

import tkinter as tk
from tkinter import ttk, messagebox

from . import runtime
from .runtime import scaled
from .theme import ACCENT_BUTTON_STYLE, apply_titlebar_theme
from .widgets import center_window
from .. import config

def _format_default(spec: config.DownloadSettingSpec) -> str:
    unit = f" {spec.unit}" if spec.unit else ""
    value = spec.default
    return f"{value:g}{unit}" if not spec.integer else f"{value}{unit}"

def show_download_settings_window() -> None: # 打开下载设置的窗口
    settings_window = tk.Toplevel(runtime.root)
    settings_window.title("下载设置")
    settings_window.resizable(False, False) # 禁止调整窗口大小
    settings_window.focus() # 自动获得焦点
    settings_window.grab_set() # 阻止主窗口操作
    settings_window.transient(runtime.root) # 使窗口依赖于主窗口
    settings_window.bind("<Escape>", lambda event: settings_window.destroy()) # 绑定 Esc 键关闭窗口

    frame = ttk.Frame(settings_window, padding=scaled(20))
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="下载与限流设置", style="Heading.TLabel").pack(anchor="w")
    ttk.Label(
        frame,
        text="这些参数控制批量下载的并发、限流保护与失败重试。若不了解含义，保持默认即可。",
        style="Caption.TLabel",
        wraplength=scaled(420),
        justify="left",
    ).pack(anchor="w", pady=(scaled(2), scaled(12)))

    # 表单卡片
    form_card = ttk.Frame(frame, style="Card.TFrame", padding=(scaled(14), scaled(12)))
    form_card.pack(fill="both", expand=True)
    form_card.columnconfigure(1, weight=1)

    entries: dict[str, ttk.Spinbox] = {}
    for row, spec in enumerate(config.DOWNLOAD_SETTING_SPECS):
        current = config.download_settings[spec.key]
        ttk.Label(form_card, text=spec.label, style="Heading.TLabel").grid(row=row, column=0, sticky="nw", pady=(0, scaled(10)))
        ttk.Label(
            form_card,
            text=f"{spec.description}\n默认 {_format_default(spec)}，范围 {spec.minimum:g} ~ {spec.maximum:g}",
            style="Caption.TLabel",
            wraplength=scaled(300),
            justify="left",
        ).grid(row=row, column=1, sticky="nw", padx=(scaled(10), 0), pady=(0, scaled(2)))

        spinbox = ttk.Spinbox(
            form_card,
            from_=spec.minimum,
            to=spec.maximum,
            increment=1 if spec.integer else 0.1,
            width=10,
        )
        spinbox.set(f"{current:g}")
        spinbox.grid(row=row, column=2, sticky="ne", padx=(scaled(12), 0), pady=(0, scaled(10)))
        entries[spec.key] = spinbox

    def save_settings() -> None:
        values = {key: spinbox.get() for key, spinbox in entries.items()}
        try:
            # 保存成功后 config 会通知下载模块同步派生参数（见 on_download_settings_changed）
            tip_info = config.set_download_settings(values)
        except ValueError as error:
            messagebox.showerror("保存失败", str(error), parent=settings_window)
            return
        messagebox.showinfo("保存成功", tip_info, parent=settings_window)
        settings_window.destroy()

    def restore_defaults() -> None:
        for spec in config.DOWNLOAD_SETTING_SPECS:
            entries[spec.key].set(f"{spec.default:g}")

    # 底部按钮栏：左侧为恢复默认，右侧为保存
    button_frame = ttk.Frame(frame)
    button_frame.pack(fill="x", pady=(scaled(12), 0))
    ttk.Button(button_frame, text="恢复默认值", command=restore_defaults).pack(side="left")
    ttk.Button(button_frame, text="保存", style=ACCENT_BUTTON_STYLE, command=save_settings).pack(side="right")

    center_window(settings_window, runtime.root) # 让弹窗居中
    apply_titlebar_theme(settings_window) # 让标题栏跟随主题
    settings_window.lift() # 置顶可见
