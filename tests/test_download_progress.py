import time
import unittest
from unittest.mock import patch

from src.tchmaterial_parser.network import REQUEST_TIMEOUT
from src.tchmaterial_parser.ui import download_panel


class RecordingWidget:
    def __init__(self) -> None:
        self.configs: list[dict] = []

    def config(self, **kwargs: dict) -> None:
        self.configs.append(kwargs)


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.ok = status_code < 400
        self.status_code = status_code

    def close(self) -> None:
        pass


class TimeoutRecordingSession:
    def __init__(self) -> None:
        self.timeouts: list[tuple | None] = []

    def get(self, url: str, **kwargs: dict) -> FakeResponse:
        self.timeouts.append(kwargs.get("timeout"))
        return FakeResponse(200)


class DownloadProgressTest(unittest.TestCase):
    def setUp(self) -> None:
        # 让 ui_call 直接同步执行，便于断言标签与进度条的实际更新内容
        previous_call = download_panel.ui_call
        self.addCleanup(setattr, download_panel, "ui_call", previous_call)
        download_panel.ui_call = lambda func, *args, **kwargs: func(*args, **kwargs)

        previous_states = download_panel.download_states
        self.addCleanup(setattr, download_panel, "download_states", previous_states)
        download_panel.download_states = []

        # 关闭进度节流，否则同一时间窗内的连续刷新会被丢弃，断言不稳定
        previous_interval = download_panel._PROGRESS_REFRESH_INTERVAL
        self.addCleanup(setattr, download_panel, "_PROGRESS_REFRESH_INTERVAL", previous_interval)
        download_panel._PROGRESS_REFRESH_INTERVAL = 0

        self.label = RecordingWidget()
        self.bar = RecordingWidget()
        for name, widget in (("progress_label", self.label), ("download_progress_bar", self.bar)):
            widget_patch = patch.object(download_panel.widgets, name, widget)
            widget_patch.start()
            self.addCleanup(widget_patch.stop)

    def latest_label_text(self) -> str:
        return self.label.configs[-1]["text"]

    def test_shows_percentage_when_total_size_known(self) -> None:
        download_panel.download_states = [
            {"downloaded_size": 50, "total_size": 100, "finished": True, "failed_reason": None},
            {"downloaded_size": 50, "total_size": 100, "finished": False, "failed_reason": None},
        ]

        download_panel.refresh_download_progress()

        self.assertIn("50.00%", self.latest_label_text())
        self.assertIn("已下载 1/2", self.latest_label_text())
        self.assertEqual(self.bar.configs[-1], {"value": 50.0})

    def test_shows_finished_count_without_total_size(self) -> None:
        download_panel.download_states = [
            {"downloaded_size": 0, "total_size": 0, "finished": True, "failed_reason": None},
            {"downloaded_size": 0, "total_size": 0, "finished": False, "failed_reason": None},
        ]

        download_panel.refresh_download_progress()

        self.assertIn("已完成 1/2 个文件", self.latest_label_text())
        self.assertEqual(self.bar.configs, []) # 未知总大小时不驱动进度条

    def test_counts_failed_downloads(self) -> None:
        download_panel.download_states = [
            {"downloaded_size": 0, "total_size": 0, "finished": True, "failed_reason": "服务器返回 HTTP 状态码 403"},
            {"downloaded_size": 0, "total_size": 0, "finished": False, "failed_reason": None},
        ]

        download_panel.refresh_download_progress()

        self.assertIn("1 个失败", self.latest_label_text())

    def test_private_download_requests_carry_timeout(self) -> None:
        fake_session = TimeoutRecordingSession()
        previous_session = download_panel.session
        self.addCleanup(setattr, download_panel, "session", previous_session)
        download_panel.session = fake_session
        previous_interval = download_panel._MIN_REQUEST_INTERVAL
        self.addCleanup(setattr, download_panel, "_MIN_REQUEST_INTERVAL", previous_interval)
        download_panel._MIN_REQUEST_INTERVAL = 0

        response, _attempted_urls = download_panel.request_download("https://r1-ndr-private.ykt.cbern.com.cn/edu_product/esp/assets/test.pkg/book.pdf")

        self.assertTrue(response.ok)
        self.assertTrue(fake_session.timeouts)
        self.assertTrue(all(timeout == REQUEST_TIMEOUT for timeout in fake_session.timeouts))

    def test_paused_state_suppresses_progress_label(self) -> None:
        """暂停期间进行中文件的进度刷新不应覆盖 “已暂停” 提示。"""
        controller = download_panel.controller
        self.addCleanup(controller.reset)
        download_panel.download_states = [
            {"downloaded_size": 50, "total_size": 100, "finished": False, "failed_reason": None},
        ]
        controller.pause()

        download_panel.refresh_download_progress()
        self.assertEqual(self.label.configs, []) # 标签未被进度文案覆盖
        self.assertEqual(self.bar.configs[-1], {"value": 50.0}) # 进度条仍会更新

    def test_special_status_shows_pause_and_cooldown_text(self) -> None:
        controller = download_panel.controller
        self.addCleanup(controller.reset)

        controller.pause()
        download_panel.update_special_status()
        self.assertIn("已暂停", self.latest_label_text())

        controller.resume()
        controller._cooldown_until = time.monotonic() + 90
        download_panel.update_special_status()
        self.assertIn("已触发限流保护", self.latest_label_text())
        self.assertIn("1 分 30 秒", self.latest_label_text())

    def test_progress_refresh_is_throttled_but_can_be_forced(self) -> None:
        """分块下载时的连续刷新会被节流，强制刷新不受限制。"""
        previous_interval = download_panel._PROGRESS_REFRESH_INTERVAL
        self.addCleanup(setattr, download_panel, "_PROGRESS_REFRESH_INTERVAL", previous_interval)
        download_panel._PROGRESS_REFRESH_INTERVAL = 60 # 大到足以吃掉紧接着的第二次刷新

        download_panel.download_states = [
            {"downloaded_size": 50, "total_size": 100, "finished": False, "failed_reason": None},
        ]
        download_panel.refresh_download_progress()
        calls_after_first = len(self.label.configs)

        download_panel.refresh_download_progress() # 距上次不足间隔，应被丢弃
        self.assertEqual(len(self.label.configs), calls_after_first)

        download_panel.refresh_download_progress(force=True) # 强制刷新应当生效
        self.assertEqual(len(self.label.configs), calls_after_first + 1)


if __name__ == "__main__":
    unittest.main()
