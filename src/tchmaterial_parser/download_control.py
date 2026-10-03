# -*- coding: utf-8 -*-
# 下载控制器：限流熔断冷却、按文件边界的暂停与整批取消，以及供「探针」判断用的成功信号
#
# 三种全局状态由同一个条件变量保护，供下载线程与 UI 线程协作：
# - 暂停（pause）：正在下载中的文件会继续下完（含其内部的重试），
#   排队中未开始的文件在 wait_to_start() 处阻塞，恢复后继续。
# - 冷却（cooldown）：熔断器触发后所有新文件的开始被挂起，倒计时结束后自动继续。
#   连续触发会按 1x、2x、4x… 递增冷却时长（封顶见 config.COOLDOWN_MAX_SECONDS）；
#   距上次触发超过 config.COOLDOWN_ESCALATION_RESET 后倍数回到 1。
# - 取消（cancel）：新文件不再开始，正在传输的文件在分块写入点中断并清理 .tmp。
#
# 熔断判定按 **不同 URL** 去重：单个文件反复失败只算一次，只有「一批不同文件在
# 短时间内接连失败」才视为限流。这样坏文件不会把整批拖进冷却。
#
# 失败定性（是限流还是文件自身不可用）不在这里做：它要看“失败在时间上的疏密”，
# 是批次级判断，由 download_panel.classify_failures() 对全部下载状态的失败时刻聚类完成。
# 这里只做熔断，并保证报告失败时的时间点由调用方自己记录（download_file 写 failed_at）。

import threading, time
from collections import deque
from typing import NamedTuple

from . import config

class DownloadCancelled(Exception):
    """下载线程在检查点发现批次已取消时抛出，用于中断传输并清理临时文件。"""

class TripInfo(NamedTuple):
    """一次限流熔断的详情，供界面日志展示。"""

    distinct_failures: int # 触发时的不同文件失败数
    duration: float # 本次冷却时长（秒）
    trip_count: int # 连续第几次触发

class DownloadController:
    """跨线程共享的下载控制状态。所有方法线程安全。"""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._paused = False
        self._cancelled = False
        self._cooldown_until = 0.0 # time.monotonic() 时间戳
        self._trip_count = 0 # 连续触发次数，决定冷却倍数
        self._last_trip_at = 0.0
        self._failure_events: deque[tuple[str, float]] = deque() # (失败 URL, 时刻)

    # —— UI 线程的操作 ——————————————————————————————————————

    def pause(self) -> None:
        with self._cond:
            self._paused = True
            self._cond.notify_all()

    def resume(self) -> None:
        with self._cond:
            self._paused = False
            self._cond.notify_all()

    def cancel(self) -> None:
        with self._cond:
            self._cancelled = True
            self._cond.notify_all()

    def reset(self) -> None:
        """批次结束后复位全部状态，供下一批干净开始。"""
        with self._cond:
            self._paused = False
            self._cancelled = False
            self._cooldown_until = 0.0
            self._trip_count = 0
            self._last_trip_at = 0.0
            self._failure_events.clear()
            self._cond.notify_all()

    # —— 状态查询 ——————————————————————————————————————————

    @property
    def is_paused(self) -> bool:
        with self._cond:
            return self._paused

    @property
    def is_cancelled(self) -> bool:
        with self._cond:
            return self._cancelled

    def cooldown_remaining(self) -> float:
        """距冷却结束还剩多少秒；未触发时为 0。"""
        with self._cond:
            return max(self._cooldown_until - time.monotonic(), 0.0)

    def distinct_failure_count(self) -> int:
        """统计当前时间窗内失败过的不同 URL 数量。"""
        with self._cond:
            self._prune_failures(time.monotonic())
            return len({url for url, _ in self._failure_events})

    # —— 下载线程的检查点 ————————————————————————————————————

    def wait_to_start(self) -> bool:
        """开始一个新文件前调用：暂停或冷却期间阻塞，批次取消时返回 False。"""
        with self._cond:
            while not self._cancelled:
                remaining = self._cooldown_until - time.monotonic()
                if not self._paused and remaining <= 0:
                    return True
                if remaining > 0:
                    self._cond.wait(timeout=min(remaining, 0.5))
                else:
                    self._cond.wait(timeout=0.2)
            return False

    def check_cancelled(self) -> None:
        """传输过程中的检查点：取消时抛出 DownloadCancelled。"""
        if self.is_cancelled:
            raise DownloadCancelled("下载已被用户取消")

    # —— 熔断器 ————————————————————————————————————————————

    def _prune_failures(self, now: float) -> None:
        window = config.CIRCUIT_FAILURE_WINDOW
        while self._failure_events and now - self._failure_events[0][1] > window:
            self._failure_events.popleft()

    def report_failure(self, url: str) -> TripInfo | None:
        """记录一次疑似限流失败。达到「窗口内不同文件失败数」阈值时触发冷却。

        同一 URL 在窗口内重复失败只计一次，因此单个坏文件不会误触发冷却；
        阈值与基准冷却时长实时读取 config.download_settings，设置窗口保存后立即生效。
        """
        threshold = int(config.download_settings["circuit_threshold"])
        base_cooldown = int(config.download_settings["cooldown_seconds"])

        with self._cond:
            now = time.monotonic()
            self._failure_events.append((url, now))
            self._prune_failures(now)

            distinct_failures = len({failed_url for failed_url, _ in self._failure_events})
            if distinct_failures < threshold or now < self._cooldown_until:
                return None

            # 长时间平稳（没有新触发）后，冷却倍数重新从 1 开始
            if now - self._last_trip_at > config.COOLDOWN_ESCALATION_RESET:
                self._trip_count = 0
            self._trip_count += 1
            duration = min(base_cooldown * (2 ** (self._trip_count - 1)), config.COOLDOWN_MAX_SECONDS)
            self._cooldown_until = now + duration
            self._last_trip_at = now
            self._failure_events.clear()
            self._cond.notify_all() # 唤醒 wait_to_start 的线程以感知新的冷却结束时刻
            return TripInfo(distinct_failures, duration, self._trip_count)

controller = DownloadController() # 全局唯一实例，download_panel 与 UI 共享
