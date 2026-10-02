# -*- coding: utf-8 -*-
# 下载面板：解析并复制直链、下载资源文件与进度反馈
# 本模块持有与下载相关的几个控件句柄，因此这些控件的读写不必跨模块

import os, re, threading, time, traceback
import tkinter as tk
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from tkinter import ttk, messagebox, filedialog
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from requests import RequestException

from . import runtime
from .runtime import thread_it, ui_call
from .. import config
from ..api import ResourceInfo, parse
from ..bookmarks import add_bookmarks
from ..download_control import DownloadCancelled, controller
from ..network import REQUEST_TIMEOUT, request_headers, session
from ..platform_utils import print_error

download_states: list[dict] = [] # 初始化下载状态
@dataclass
class PanelWidgets:
    """下载面板用到的界面控件。

    由 app.py 在装配完界面后经 bind_widgets() 一次性注入。以前这些句柄是 9 个模块级
    全局变量，新增控件必须先在模块级声明 None，否则单独运行某个流程会 NameError；
    现在统一放进这个容器，未绑定即为 None。
    """

    url_text: tk.Text | None = None
    bookmark_var: tk.BooleanVar | None = None
    download_btn: ttk.Button | None = None
    copy_btn: ttk.Button | None = None
    download_progress_bar: ttk.Progressbar | None = None
    progress_label: ttk.Label | None = None
    pause_btn: ttk.Button | None = None
    cancel_btn: ttk.Button | None = None
    log_text: tk.Text | None = None

widgets = PanelWidgets() # 全局唯一实例；测试可直接替换其中某个控件
PRIVATE_DOWNLOAD_HOSTS = tuple(f"r{index}-ndr-private.ykt.cbern.com.cn" for index in range(1, 4))
# 私有 CDN 在短时间连打时会回 400（有时带 InvalidArgument，有时几乎空包）。
# 立刻换 r2/r3 只会把限流打得更死；同地址稍等再签一次即可。
# 重试次数由 “下载设置” 窗口中的 http400_retries 控制（见 apply_download_settings）。
_400_RETRY_DELAYS = (1.0, 3.0)
_MIN_REQUEST_INTERVAL = 0.2 # 同样由设置窗口的 min_request_interval 控制
_rate_lock = threading.Lock()
_last_request_at = 0.0
_PROGRESS_REFRESH_INTERVAL = 0.2 # 进度界面刷新的最小间隔（秒），见 refresh_download_progress
_last_progress_refresh = 0.0

# 常见 HTTP 状态码的中文解释，写入日志与失败原因，避免用户看不懂纯状态码
HTTP_STATUS_HINTS = {
    400: "请求无效：多为被平台限流，或该资源地址已失效",
    401: "未登录或登录已过期",
    403: "无权限访问该资源",
    404: "资源不存在：该文件可能已从平台下架",
    408: "请求超时",
    429: "请求过于频繁：已被平台限流",
    500: "平台服务器内部错误",
    502: "平台网关错误",
    503: "平台服务暂不可用",
    504: "平台响应超时",
}

def status_hint(status_code: int) -> str | None:
    """返回状态码的中文解释；未知的 5xx 归入「服务器暂时异常」。"""
    hint = HTTP_STATUS_HINTS.get(status_code)
    if hint is None and 500 <= status_code < 600:
        hint = "平台服务器暂时异常"
    return hint

class NetworkDownloadError(RuntimeError):
    """网络层异常（连接失败、超时等）导致的下载失败。这类失败冷却后重试通常可以恢复。"""

def apply_download_settings() -> None:
    """把 config.download_settings 中的两个模块级参数同步为本模块使用的形式。

    其余配置（并发数、冷却、重试次数、超时）在使用点实时读取，无需同步。
    """
    global _MIN_REQUEST_INTERVAL, _400_RETRY_DELAYS
    _MIN_REQUEST_INTERVAL = float(config.download_settings["min_request_interval"])
    retries = int(config.download_settings["http400_retries"])
    _400_RETRY_DELAYS = tuple(2 * index + 1.0 for index in range(retries)) # 1s、3s、5s…

# —— 日志 ——

def log_message(message: str) -> None: # 追加一行日志；可在任意线程调用
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line) # 无界面运行时（或打包后排查）也能在控制台看到
    ui_call(_append_log_line, line)

def _append_log_line(line: str) -> None: # 仅主线程调用：写入日志控件并滚动到底部
    if widgets.log_text is None:
        return
    try:
        widgets.log_text.configure(state="normal")
        widgets.log_text.insert("end", line + "\n")
        widgets.log_text.see("end")
        widgets.log_text.configure(state="disabled")
    except tk.TclError: # 主窗口已销毁
        pass

def clear_log() -> None: # 清空日志区（由界面按钮调用）
    if widgets.log_text is None:
        return
    widgets.log_text.configure(state="normal")
    widgets.log_text.delete("1.0", "end")
    widgets.log_text.configure(state="disabled")
    log_message("日志已清空")

def redact_access_token(text: str) -> str:
    """隐藏查询串里可能残留的 accessToken。本工具不再主动拼接该参数，但异常或用户粘贴的 URL 仍可能带上。"""
    return re.sub(r"([?&]accessToken=)[^&\s'\"]+", r"\1<已隐藏>", text, flags=re.IGNORECASE)

def download_mirror_urls(url: str) -> list[str]:
    """按原地址优先的顺序生成私有 CDN 镜像，普通下载地址保持不变。"""
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    if hostname not in PRIVATE_DOWNLOAD_HOSTS:
        return [url]

    ordered_hosts = [hostname, *(host for host in PRIVATE_DOWNLOAD_HOSTS if host != hostname)]
    return [urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment)) for host in ordered_hosts]

def _pace_request() -> None:
    """避免批量任务在同一瞬间打出一串私有 CDN 请求。"""
    global _last_request_at
    interval = _MIN_REQUEST_INTERVAL
    if interval <= 0:
        return
    with _rate_lock:
        wait = interval - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()

def request_download(url: str):
    """请求资源并在镜像出错时自动切换，返回最终响应和已尝试的无凭据地址。

    鉴权只放在 request_headers 生成的 X-ND-AUTH 里，URL 保持原样。
    官网谁拼 ?accessToken=：不是 UC SDK，是阅读器。普通教材用站点 pdf.js，不拼；
    专题课用 x-edu-microapp-detail 的 docplayer，会拼，但头里仍有按完整 URL
    现算的 MAC。我们的抉择是永远不拼，避免 2efcd89 那种无效 Token 进查询串
    导致的 400 InvalidArgument（#81）。有真实 MAC 时，#76 和专题课都不需要它。

    400 也按鉴权/限流处理：同地址用新 nonce 退避重试，不要立刻改打 r2/r3。

    疑似限流的失败（400/429/网络异常）会上报全局熔断器；达到阈值时整批
    进入冷却，由 controller.wait_to_start 挂起后续任务。
    """
    attempted_urls: list[str] = []
    last_response = None
    last_exception: RequestException | None = None
    # 读超时由 “下载设置” 控制；连接超时沿用全局默认
    timeout = (REQUEST_TIMEOUT[0], float(config.download_settings["download_timeout"]))

    for candidate_url in download_mirror_urls(url):
        attempted_urls.append(candidate_url)
        retry = 0
        while True:
            try:
                _pace_request()
                response = session.get(
                    candidate_url,
                    headers=request_headers(candidate_url),
                    stream=True,
                    timeout=timeout,
                )
            except RequestException as e:
                last_exception = e
                break

            if last_response is not None:
                last_response.close()
            last_response = response

            if response.ok:
                return response, attempted_urls

            # 401/403 换镜像也过不了；404 说明该对象在三个镜像上都不存在（同一存储后端），
            # 再打 r2/r3 只是白白增加请求量。400 多半是突发限流，连打镜像会更糟。
            if response.status_code in (401, 403, 404):
                return last_response, attempted_urls
            if response.status_code == 400:
                if retry < len(_400_RETRY_DELAYS):
                    time.sleep(_400_RETRY_DELAYS[retry])
                    retry += 1
                    continue
                report_rate_limit_failure(url) # 已退避重试过，仍按限流上报
                return last_response, attempted_urls
            if response.status_code == 429:
                report_rate_limit_failure(url) # 明确的限流响应
                break
            break

    if last_response is not None:
        return last_response, attempted_urls
    if last_exception is not None:
        # requests 的异常文字通常包含完整请求 URL，此处重新包装以清除查询参数中的 Token。
        report_rate_limit_failure(url) # 网络异常风暴同样按限流处理
        raise NetworkDownloadError(redact_access_token(str(last_exception))) from None
    raise RuntimeError("没有可用的下载地址")

def format_duration(seconds: float) -> str:
    """把秒数格式化成“X 分 Y 秒”/“Y 秒”，用于日志与提示。"""
    total = int(seconds + 0.5)
    minutes, remainder = divmod(total, 60)
    return f"{minutes} 分 {remainder} 秒" if minutes else f"{remainder} 秒"

def report_rate_limit_failure(url: str) -> None:
    """上报一次疑似限流失败；触发熔断时在日志中说明判定依据与冷却时长。

    注意这是“疑似”：熔断器按不同 URL 去重，只有一批不同文件接连失败才会真正触发。
    """
    trip = controller.report_failure(url)
    if trip is None:
        return
    escalation = f"（连续第 {trip.trip_count} 次触发，冷却时长已加大）" if trip.trip_count > 1 else ""
    log_message(
        f"[限流] 60 秒内已有 {trip.distinct_failures} 个不同文件下载失败 → 判定为限流，"
        f"暂停 {format_duration(trip.duration)} 后自动继续{escalation}"
    )

def storage_error_code(response) -> str | None:
    """读取对象存储返回的 XML 错误码；非 XML 响应保持原有通用提示。"""
    try:
        root = ElementTree.fromstring(response.content)
        return root.findtext("Code")
    except (AttributeError, ElementTree.ParseError, TypeError):
        return None

def download_failure_reason(response, attempted_urls: list[str]) -> str:
    status_code = response.status_code
    error_code = storage_error_code(response)
    reason = f"服务器返回 HTTP 状态码 {status_code}"
    hint = status_hint(status_code)
    if hint:
        reason += f"（{hint}）"
    if error_code:
        reason += f"（对象存储返回 {error_code}）"

    if status_code in (401, 403):
        if config.access_token:
            reason += "，Access Token 可能已过期或无效，请重新设置"
        else:
            reason += "，该资源需要有效的 Access Token，请先设置"
    elif status_code == 400 and error_code == "InvalidArgument":
        # 占位头、过期 Token、或短时间连打私有 CDN 都会回这个码。前面已经同地址重试过。
        if config.access_token:
            reason += "，私有资源暂时无法访问。请稍后重试；若持续失败，请重新设置 Access Token"
        else:
            reason += "，该私有资源需要有效的 Access Token，请先设置"

    if len(attempted_urls) > 1:
        reason += f"，已尝试 {len(attempted_urls)} 个下载镜像"
    return reason

# Windows 禁止在文件名中使用半角 ? * : / 等；改为对应全角字符，尽量保留原标题读法（#86）。
_INVALID_FILENAME_REPLACEMENTS = str.maketrans({
    "<": "＜",
    ">": "＞",
    ":": "：",
    '"': "＂",
    "/": "／",
    "\\": "＼",
    "|": "｜",
    "?": "？",
    "*": "＊",
})
_CONTROL_FILENAME_CHARS = re.compile(r"[\x00-\x1f]")
_WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
})

def sanitize_filename(filename: str) -> str:
    """将非法文件名字符换成全角对应字符，并避开 Windows 保留设备名。"""
    filename = _CONTROL_FILENAME_CHARS.sub("_", filename.translate(_INVALID_FILENAME_REPLACEMENTS))
    filename = filename.rstrip(" .")
    if not filename:
        return "download"

    stem, extension = os.path.splitext(filename)
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        return f"_{stem}{extension}"
    return filename

def download_filename(resource: ResourceInfo) -> str:
    return sanitize_filename(f"{resource.title or 'download'}.{resource.file_format}")

def filename_key(filename: str) -> str:
    """以跨平台保守方式比较文件名，提前避开 Windows/macOS 上的大小写冲突。"""
    return os.path.normcase(filename).casefold()

def allocate_download_paths(resources: list[ResourceInfo], directory: str) -> list[str]:
    """在线程启动前为批量任务分配唯一目标路径，防止多个线程共用同一个 .tmp 文件。"""
    base_filenames = [download_filename(resource) for resource in resources]
    base_counts = Counter(filename_key(filename) for filename in base_filenames)

    edition_filenames: list[str] = []
    for resource, filename in zip(resources, base_filenames):
        # 例如人教版与北师大版的 “普通高中教科书·英语必修 第三册” 同名时，优先使用易读的版别前缀区分。
        if base_counts[filename_key(filename)] > 1 and resource.edition:
            filename = sanitize_filename(f"[{resource.edition}] {filename}")
        edition_filenames.append(filename)

    reserved_paths: set[str] = set()
    allocated_paths: list[str] = []
    for resource, filename in zip(resources, edition_filenames):
        # 按资源的分类层级（学段/学科/版本）归入子目录，段名中的非法字符换为全角
        subdirectory = os.path.join(directory, *(sanitize_filename(part) for part in resource.relative_dir))
        candidate = os.path.join(subdirectory, filename)
        stem, extension = os.path.splitext(candidate)
        sequence = 2

        # 同时检查最终文件和可辨识的 “最终文件.tmp”；后者可能属于另一个仍在运行的程序实例。
        while (
            filename_key(candidate) in reserved_paths
            or os.path.exists(candidate)
            or os.path.exists(f"{candidate}.tmp")
        ):
            candidate = f"{stem} ({sequence}){extension}"
            sequence += 1

        reserved_paths.add(filename_key(candidate))
        allocated_paths.append(candidate)
    return allocated_paths

def bind_widgets(
    text: tk.Text,
    bookmark: tk.BooleanVar,
    button: ttk.Button,
    copy_button: ttk.Button,
    progress_bar: ttk.Progressbar,
    label: ttk.Label,
    pause_button: ttk.Button | None = None,
    cancel_button: ttk.Button | None = None,
    log_widget: tk.Text | None = None,
) -> None: # 由 app.py 在创建控件后写入
    widgets.url_text = text
    widgets.bookmark_var = bookmark
    widgets.download_btn = button
    widgets.copy_btn = copy_button
    widgets.download_progress_bar = progress_bar
    widgets.progress_label = label
    widgets.pause_btn = pause_button
    widgets.cancel_btn = cancel_button
    widgets.log_text = log_widget

def _set_control_buttons(pause_state: str | None, cancel_state: str | None, pause_text: str | None = None) -> None:
    """更新暂停/取消按钮的可用状态与文字；旧测试可能未绑定这两个按钮。"""
    if widgets.pause_btn is not None:
        widgets.pause_btn.config(**({"state": pause_state} if pause_state else {}), **({"text": pause_text} if pause_text else {}))
    if widgets.cancel_btn is not None and cancel_state is not None:
        widgets.cancel_btn.config(state=cancel_state)

def toggle_pause() -> None: # 暂停/继续：进行中的文件会下完，未开始的排队等待
    if not downloads_active():
        return
    if controller.is_paused:
        controller.resume()
        log_message("[提示] 已继续下载")
    else:
        controller.pause()
        log_message("[提示] 已暂停：进行中的文件下载完成后不再开始新任务")
    _set_control_buttons(pause_state="normal", cancel_state="normal", pause_text="继续" if controller.is_paused else "暂停")

def cancel_downloads() -> None: # 取消全部：新任务不再开始，进行中的文件在分块处中断
    if not downloads_active() or controller.is_cancelled:
        return
    controller.cancel()
    log_message("[提示] 已取消剩余任务，正在中断进行中的下载")
    _set_control_buttons(pause_state="disabled", cancel_state="disabled")

def shutdown_downloads(timeout: float = 5.0) -> None: # 退出程序前取消下载并等待线程收尾
    """退出时不能直接销毁窗口：下载线程会在分块检查点清理 .tmp，线程池线程又是非 daemon 的，
    不等它们结束就会留下半成品文件、甚至让进程在后台滞留到下载完成。"""
    if not downloads_active():
        return
    controller.cancel()
    deadline = time.monotonic() + timeout
    while downloads_active() and time.monotonic() < deadline:
        time.sleep(0.05)

def downloads_active() -> bool: # 是否存在尚未完成的下载任务
    return bool(download_states) and not all(state["finished"] for state in download_states)

def show_parse_progress(current: int, total: int) -> None: # 后台解析大量链接时在进度标签上反馈进度；下载进行中则让位给下载进度
    if downloads_active():
        return
    ui_call(widgets.progress_label.config, text=f"正在解析链接 {current}/{total}")

def special_status_active() -> bool: # 暂停/冷却/取消期间由 update_special_status 独占进度标签的文案
    return controller.is_cancelled or controller.is_paused or controller.cooldown_remaining() > 0

def refresh_download_progress(force: bool = False) -> None: # 汇总全部任务状态刷新进度条与标签，没有 Content-Length 或出现失败时也能看到进展
    global _last_progress_refresh
    now = time.monotonic()
    # 分块下载时每 128KB~512KB 就会调用一次，远超肉眼需要；节流以免淹没主线程的事件队列
    if not force and now - _last_progress_refresh < _PROGRESS_REFRESH_INTERVAL:
        return
    _last_progress_refresh = now

    states = list(download_states)
    all_downloaded_size = sum(state["downloaded_size"] for state in states)
    all_total_size = sum(state["total_size"] for state in states)
    finished_number = len([state for state in states if state["finished"]])
    failed_number = len([state for state in states if state["failed_reason"]])
    cancelled_number = len([state for state in states if state.get("cancelled")])
    total_number = len(states)
    if all_total_size > 0: # 防止下面一行代码除以 0 而报错
        download_progress = (all_downloaded_size / all_total_size) * 100
        ui_call(widgets.download_progress_bar.config, value=download_progress) # 更新进度条
        progress_text = f"{format_bytes(all_downloaded_size)}/{format_bytes(all_total_size)} ({download_progress:.2f}%) 已下载 {finished_number}/{total_number}"
    else:
        progress_text = f"已下载 {format_bytes(all_downloaded_size)}，已完成 {finished_number}/{total_number} 个文件"
    if failed_number:
        progress_text += f"，{failed_number} 个失败"
    if cancelled_number:
        progress_text += f"，{cancelled_number} 个已取消"
    # 暂停/冷却/取消时让位给 update_special_status，避免进行中文件的进度刷新把提示文案冲掉
    if not special_status_active():
        ui_call(widgets.progress_label.config, text=progress_text) # 更新标签以显示当前下载进度

def schedule_status_updates() -> None: # 主线程中定期刷新暂停/冷却倒计时；批次结束后自动停止
    if runtime.app_closing or not downloads_active():
        return
    update_special_status()
    try:
        runtime.root.after(500, schedule_status_updates)
    except Exception: # 主窗口已销毁时忽略
        pass

def update_special_status() -> None: # 特殊状态优先于普通进度显示：取消 > 暂停 > 冷却倒计时
    if controller.is_cancelled:
        widgets.progress_label.config(text="正在取消，等待进行中的任务结束…")
    elif controller.is_paused:
        widgets.progress_label.config(text="已暂停：进行中的文件下载完成后将停止开始新任务")
    elif controller.cooldown_remaining() > 0:
        remaining = int(controller.cooldown_remaining() + 0.999) # 向上取整，避免显示 0 分 0 秒
        minutes, seconds = divmod(remaining, 60)
        widgets.progress_label.config(text=f"已触发限流保护，{minutes} 分 {seconds:02d} 秒后自动继续并重试失败文件")
    else:
        refresh_download_progress()

def collect_parsed_resources(
    parse_fn: Callable[[str, bool], list[ResourceInfo] | None],
    urls: list[str],
    bookmarks: bool,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[ResourceInfo], set[str]]:
    """逐条解析链接并汇总结果：按资源直链去重，解析失败的链接单独收集。"""
    resources_info_list: list[ResourceInfo] = []
    resource_urls: set[str] = set()
    failed_urls: set[str] = set()
    for index, url in enumerate(urls):
        if on_progress:
            on_progress(index + 1, len(urls))
        resources_info = parse_fn(url, bookmarks)
        if not resources_info:
            failed_urls.add(url)
            continue
        for resource in resources_info:
            if resource.url in resource_urls: # 直接使用 resources_info_list 会报错（list 不可哈希）
                continue
            resources_info_list.append(resource)
            resource_urls.add(resource.url)
    return resources_info_list, failed_urls

def parse_urls_in_background(
    urls: list[str],
    bookmarks: bool,
    on_finished: Callable[[list[ResourceInfo], set[str]], None],
) -> None:
    """在后台线程逐条解析链接，完成后回到主线程执行 on_finished(资源列表, 失败链接集合)。

    批量选择的链接可能多达上百条，逐条解析需多次网络请求，放在主线程会让界面未响应。
    """
    def worker() -> None:
        resources_info_list, failed_urls = collect_parsed_resources(parse, urls, bookmarks, show_parse_progress)
        ui_call(on_finished, resources_info_list, failed_urls)

    thread_it(worker)

def parse_and_copy() -> None: # 解析并复制链接
    urls = {line.strip() for line in widgets.url_text.get("1.0", "end").splitlines() if line.strip()} # 获取所有非空行并去重
    if not urls:
        return

    widgets.copy_btn.config(state="disabled") # 解析期间禁用按钮，避免重复触发

    def copy_urls(resources_info_list: list[ResourceInfo], failed_urls: set[str]) -> None: # 解析完成后在主线程复制链接
        widgets.copy_btn.config(state="normal") # 恢复按钮为启用状态
        if not downloads_active():
            widgets.progress_label.config(text="等待下载") # 解析进度已无用，恢复默认文案

        resource_urls = {resource.url for resource in resources_info_list}
        if failed_urls:
            messagebox.showwarning("警告", "以下 “行” 无法解析：\n" + "\n".join(failed_urls))

        if resource_urls:
            try:
                resource_urls_str = "\n".join(resource_urls)
                widgets.url_text.clipboard_clear()
                widgets.url_text.clipboard_append(resource_urls_str) # 将链接复制到剪贴板
                if widgets.url_text.clipboard_get() == resource_urls_str: # 检查剪贴板内容是否正确
                    # 真实 X-ND-AUTH 必须按每条 URL 现算，不能把某一次的 nonce/mac 当作通用头复制出去。
                    messagebox.showinfo(
                        "提示",
                        f'资源链接已复制到剪贴板。\n注意：链接可能无法直接下载。官网私有资源使用按地址单独计算的 X-ND-AUTH，请优先用本工具下载。{"若需手动请求，至少带上以下标头（含隐私信息，请勿分享）：" if config.access_token else "未登录时可以尝试："}\n\nAuthorization: Bearer {config.access_token or "0"}\nX-ND-AUTH: MAC id="{config.access_token or "0"}",nonce="0",mac="0"',
                    )
                else:
                    messagebox.showerror("错误", "无法将链接复制到剪贴板，请手动复制。")
            except Exception as e:
                print_error(e)
                messagebox.showerror("错误", "无法将链接复制到剪贴板，请手动复制。")

    parse_urls_in_background(list(urls), False, copy_urls)

def download() -> None: # 下载资源文件
    global download_states
    widgets.download_btn.config(state="disabled") # 设置下载按钮为禁用状态
    widgets.download_progress_bar.config(value=0) # 重置上一批任务可能残留的进度
    download_states = [] # 初始化下载状态
    controller.reset() # 清理上一批遗留的暂停/取消/冷却状态
    _set_control_buttons(pause_state="disabled", cancel_state="disabled", pause_text="暂停")
    urls = {line.strip() for line in widgets.url_text.get("1.0", "end").splitlines() if line.strip()} # 获取所有非空行并去重

    if config.access_token and not config.access_token.isascii(): # 判断 Access Token 中是否包含非 ASCII 字符
        messagebox.showwarning("警告", "Access Token 不正确（包含非 ASCII 字符），请点击“设置 Token”按钮重新填写。")
        widgets.download_btn.config(state="normal") # 恢复下载按钮为启用状态
        return

    if not urls:
        widgets.download_btn.config(state="normal") # 恢复下载按钮为启用状态
        return

    log_message(f"[开始] 收到 {len(urls)} 行链接，正在解析资源信息…")

    def start_downloads(resources_info_list: list[ResourceInfo], failed_urls: set[str]) -> None: # 解析完成后在主线程选择保存位置并开始下载
        def restore_download_btn() -> None: # 未产生下载任务时恢复界面状态
            if not downloads_active():
                widgets.progress_label.config(text="等待下载")
            widgets.download_btn.config(state="normal") # 设置下载按钮为启用状态

        if len(resources_info_list) > 1:
            messagebox.showinfo("提示", "您将下载多个文件，请选择要下载文件的位置。本程序将在该文件夹中按教材分类创建子文件夹，并以资源名称命名文件。")
            dir_path = filedialog.askdirectory() # 选择文件夹
            if not dir_path: # 用户取消或关闭对话框
                restore_download_btn()
                return
            dir_path = os.path.normpath(dir_path)
            # 路径必须在任何线程启动前统一预留，否则同名资源仍可能同时打开同一个 .tmp 文件。
            download_targets = list(zip(resources_info_list, allocate_download_paths(resources_info_list, dir_path)))
        elif resources_info_list:
            download_targets: list[tuple[ResourceInfo, str]] = []
            for resource in resources_info_list:
                save_path = filedialog.asksaveasfilename( # 选择保存路径
                    defaultextension=f".{resource.file_format}",
                    filetypes=[(f"{resource.file_format.upper()} 文件", f"*.{resource.file_format}"), ("所有文件", "*.*")],
                    initialfile=sanitize_filename(resource.title or "download"),
                )
                if not save_path: # 用户取消了文件保存操作
                    restore_download_btn()
                    return
                save_path = os.path.normpath(save_path)
                download_targets.append((resource, save_path))
        else: # 没有可下载的资源
            restore_download_btn()
            if failed_urls:
                messagebox.showwarning("警告", "以下 “行” 无法解析：\n" + "\n".join(failed_urls)) # 显示警告对话框
            return

        widgets.progress_label.config(text=f"正在下载 {len(download_targets)} 个文件")
        directory = dir_path if len(resources_info_list) > 1 else os.path.dirname(download_targets[0][1])
        start_download_batch(download_targets, directory)

        if failed_urls:
            messagebox.showwarning("警告", "以下 “行” 无法解析：\n" + "\n".join(failed_urls)) # 显示警告对话框

    parse_urls_in_background(list(urls), widgets.bookmark_var.get(), start_downloads)

def create_download_state(url: str, save_path: str) -> dict:
    return {
        "download_url": url,
        "save_path": save_path,
        "downloaded_size": 0,
        "total_size": 0,
        "finished": False,
        "failed_reason": None,
        "retryable": False, # 疑因限流/网络波动失败，末尾可能值得再试一次
        "cancelled": False, # 用户取消，不计入失败清单
        "failed_marker": 0, # 失败时的成功计数，供“探针”判断失败时平台是否仍可用
        "retried": False, # 是否已在批次末尾重试过
    }

def classify_failures(states: list[dict]) -> tuple[list[dict], list[dict]]:
    """用“探针”信号把失败分成两类：

    - 「文件自身问题」：401/403/404 等明确不可重试，或失败之后仍有别的文件下载成功
      （说明当时平台是通的，那么这个文件是自己不可用）。
    - 「疑似限流」：失败之后再没有任何文件成功过，更可能是被限流，值得在末尾重试。

    首轮失败的文件不会立刻重试，直接放过、继续下一个，保证效率。
    """
    file_problems: list[dict] = []
    throttled: list[dict] = []
    for state in states:
        if not state["failed_reason"] or state.get("cancelled"):
            continue
        if state.get("retried"):
            throttled.append(state) # 已在末尾重试过仍失败，归入“疑似限流仍失败”
        elif not state.get("retryable") or controller.has_success_since(state.get("failed_marker", 0)):
            file_problems.append(state) # 明确不可重试，或失败时别的文件仍能下载
        else:
            throttled.append(state)
    return file_problems, throttled

def run_download_pass(executor: ThreadPoolExecutor, targets: list[tuple[ResourceInfo, str]], states: list[dict]) -> None:
    """把一批任务提交给线程池并等待全部结束。"""
    futures = [
        executor.submit(download_file, resource.url, save_path, resource.chapters, state)
        for (resource, save_path), state in zip(targets, states)
    ]
    for future in futures:
        future.result()

def start_download_batch(targets: list[tuple[ResourceInfo, str]], directory: str) -> None:
    global download_states
    controller.reset() # 批次开始前确保暂停/取消/冷却状态干净
    # 所有排队任务先登记，快速失败或完成的线程也不会漏算尚未启动的任务。
    states = [create_download_state(resource.url, save_path) for resource, save_path in targets]
    download_states = states
    _set_control_buttons(pause_state="normal", cancel_state="normal", pause_text="暂停")
    ui_call(schedule_status_updates) # 主线程中定期刷新暂停/冷却倒计时
    workers = int(config.download_settings["download_workers"])
    log_message(f"[开始] 共 {len(targets)} 个文件，并发 {workers}")

    def worker() -> None:
        # 批量勾选可能产生数千个文件，仅保留少量工作线程，其余任务排队。
        # 并发数由 “下载设置” 中的 download_workers 控制。
        retries_left = int(config.download_settings["retry_rounds"])
        target_of_state = {id(state): target for target, state in zip(targets, states)}
        file_problems: list[dict] = []
        throttled: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # 首轮：失败立即放过、继续下一个，不做任何原地重试
            run_download_pass(executor, targets, states)

            if not controller.is_cancelled:
                file_problems, throttled = classify_failures(states)
                if file_problems:
                    log_message(f"[提示] {len(file_problems)} 个文件失败时其它文件仍能下载，判定为文件自身问题，已跳过重试")
                if throttled and retries_left > 0:
                    log_message(f"[提示] {len(throttled)} 个文件疑似限流，等待冷却结束后再试一次")
                    if controller.wait_to_start(): # 冷却期间挂起，结束后再重试
                        retry_targets = [target_of_state[id(state)] for state in throttled]
                        for state in throttled:
                            state.update(finished=False, failed_reason=None, retryable=False, retried=True, downloaded_size=0, total_size=0)
                        run_download_pass(executor, retry_targets, throttled)
                        # 重试后再裁决一次：已经成功的文件不再计入失败清单
                        file_problems, throttled = classify_failures(states)
                elif throttled:
                    log_message("[提示] 疑似限流文件末尾重试次数为 0，本次不再重试")
        ui_call(finish_download_batch, states, directory, file_problems, throttled) # 全部线程退出后，仅由批次通知一次

    thread_it(worker)

def finish_download_batch(
    states: list[dict],
    directory: str,
    file_problems: list[dict] | None = None,
    throttled: list[dict] | None = None,
) -> None: # 在主线程统一恢复控件并显示整批结果
    # 分类要用探针信号（成功计数），必须在 controller.reset() 之前完成，否则信号会被清掉
    if file_problems is None or throttled is None:
        file_problems, throttled = classify_failures(states)
    controller.reset() # 复位暂停/取消状态，供下一批干净开始
    widgets.download_progress_bar.config(value=0)
    widgets.progress_label.config(text="等待下载")
    widgets.download_btn.config(state="normal")
    _set_control_buttons(pause_state="disabled", cancel_state="disabled", pause_text="暂停")

    succeeded = [state for state in states if not state["failed_reason"] and not state.get("cancelled")]
    cancelled_states = [state for state in states if state.get("cancelled")]
    log_message(
        f"[结束] 成功 {len(succeeded)}，资源不可用 {len(file_problems)}，疑似限流仍失败 {len(throttled)}"
        + (f"，已取消 {len(cancelled_states)}" if cancelled_states else "")
    )

    if cancelled_states and not file_problems and not throttled:
        messagebox.showinfo("下载已取消", f"已取消剩余任务。已完成的文件保留在：\n{directory}")
        return

    if not file_problems and not throttled:
        messagebox.showinfo("下载完成", f"文件已下载到：{directory}")
        return

    sections: list[str] = []
    if file_problems:
        sections.append(
            "以下文件下载失败（资源不可用，已跳过重试）：\n"
            + "\n\n".join(f"{os.path.relpath(state['save_path'], directory)}\n{state['failed_reason']}" for state in file_problems)
        )
    if throttled:
        sections.append(
            "以下文件疑似限流，重试后仍失败：\n"
            + "\n\n".join(f"{os.path.relpath(state['save_path'], directory)}\n{state['failed_reason']}" for state in throttled)
        )
    if cancelled_states:
        sections.append(f"另有 {len(cancelled_states)} 个文件因取消未下载。")
    messagebox.showwarning("下载完成", f"文件已下载到：{directory}\n\n" + "\n\n".join(sections))

def download_file(url: str, save_path: str, chapters: list[dict] | None = None, current_state: dict | None = None) -> None: # 下载文件
    if current_state is None: # 保留单独下载文件的调用方式
        current_state = create_download_state(url, save_path)
        download_states.append(current_state)
    temp_path = f"{save_path}.tmp"

    if not controller.wait_to_start(): # 暂停或冷却期间挂起；批次取消时直接结束
        current_state["cancelled"] = True
        current_state["finished"] = True
        refresh_download_progress(force=True)
        return

    response = None
    try:
        response, attempted_urls = request_download(url)

        if not response.ok: # 服务器返回表示错误的 HTTP 状态码
            current_state["failed_reason"] = download_failure_reason(response, attempted_urls)
            # 瞬态失败（限流/服务端错误）末尾可能值得重试；401/403 需要用户重新设置 Token，404 资源不存在，重试无意义
            current_state["retryable"] = response.status_code not in (401, 403, 404) and response.status_code >= 400
            current_state["failed_marker"] = controller.success_marker()
        else:
            current_state["total_size"] = int(response.headers.get("Content-Length", 0))

            os.makedirs(os.path.dirname(save_path), exist_ok=True) # 分类下载时子目录可能尚不存在
            with open(temp_path, "wb") as file:
                for chunk in response.iter_content( # 分块下载
                    chunk_size=131072 if current_state["total_size"] < 20971520 else 262144 if current_state["total_size"] < 52428800 else 524288
                ):
                    controller.check_cancelled() # 每个分块前检查取消，及时中断传输
                    if chunk: # 过滤掉 Keep-Alive 块
                        file.write(chunk)
                        current_state["downloaded_size"] += len(chunk)
                        refresh_download_progress()

            if current_state["total_size"] > 0 and current_state["downloaded_size"] != current_state["total_size"]: # 文件下载不完整
                current_state["failed_reason"] = f"文件下载不完整，需下载 {current_state['total_size']} 字节，实际下载 {current_state['downloaded_size']} 字节"
                current_state["retryable"] = True # 网络波动导致的截断，重试通常可以恢复
                current_state["failed_marker"] = controller.success_marker()
                current_state["downloaded_size"], current_state["total_size"] = 0, 0
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            else:
                if chapters: # 添加书签
                    ui_call(widgets.progress_label.config, text="添加书签")
                    add_bookmarks(temp_path, chapters)

                os.replace(temp_path, save_path) # 重命名临时文件为目标文件
                controller.report_success() # 探针信号：此刻平台是通的

    except DownloadCancelled: # 用户取消：清理半成品并标记取消（不计入失败清单）
        current_state["cancelled"] = True
        current_state["downloaded_size"], current_state["total_size"] = 0, 0
        log_message(f"[取消] {os.path.basename(save_path)}（进行中，已中断并清理临时文件）")
        try:
            os.remove(temp_path)
        except Exception:
            pass
    except Exception as e:
        print_error(e)
        current_state["downloaded_size"], current_state["total_size"] = 0, 0
        current_state["failed_reason"] = redact_access_token(traceback.format_exc().rstrip())
        current_state["retryable"] = isinstance(e, NetworkDownloadError) # 网络异常按瞬态处理
        current_state["failed_marker"] = controller.success_marker()
        try:
            os.remove(temp_path)
        except Exception:
            pass
    finally:
        if response is not None:
            response.close()
        current_state["finished"] = True

    log_download_result(current_state)
    refresh_download_progress(force=True) # 每个任务结束时强制刷新一次，完成数与失败数立即可见

def log_download_result(state: dict) -> None: # 把一个文件的最终结果写进日志区
    name = os.path.basename(state["save_path"])
    if state.get("cancelled"):
        return # 取消的开始前排队的文件不逐条记日志，批次结束时统一汇总
    if state["failed_reason"]:
        summary = state["failed_reason"].splitlines()[0] if state["failed_reason"] else "未知原因"
        log_message(f"[失败] {name} — {summary}（已放过，继续下一个文件）")
    else:
        size = state["total_size"] or state["downloaded_size"]
        log_message(f"[完成] {name}（{format_bytes(size)}）")

def format_bytes(size: float) -> str: # 将数据单位进行格式化，返回以 KB、MB、GB、TB、PB 为单位的数据大小
    for x in ["字节", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:3.1f} {x}"
        size /= 1024.0
    return f"{size:3.1f} PB"
