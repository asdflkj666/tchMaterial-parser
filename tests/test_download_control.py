import threading
import time
import unittest
from unittest.mock import patch

from src.tchmaterial_parser import config
from src.tchmaterial_parser.download_control import DownloadCancelled, DownloadController


def make_controller(threshold: int = 3, cooldown: int = 30) -> DownloadController:
    controller = DownloadController()
    config.download_settings["circuit_threshold"] = threshold
    config.download_settings["cooldown_seconds"] = cooldown
    return controller


class ControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_settings = dict(config.download_settings)
        self.addCleanup(config.download_settings.update, self.saved_settings)

    # —— 熔断判定 ——

    def test_no_trip_below_threshold(self) -> None:
        controller = make_controller(threshold=3, cooldown=30)
        self.assertIsNone(controller.report_failure("https://example.com/a.pdf"))
        self.assertIsNone(controller.report_failure("https://example.com/b.pdf"))
        self.assertEqual(controller.cooldown_remaining(), 0.0)

    def test_trips_on_distinct_urls(self) -> None:
        controller = make_controller(threshold=3, cooldown=30)
        controller.report_failure("https://example.com/a.pdf")
        controller.report_failure("https://example.com/b.pdf")
        trip = controller.report_failure("https://example.com/c.pdf")

        self.assertIsNotNone(trip)
        self.assertEqual(trip.distinct_failures, 3)
        self.assertEqual(trip.trip_count, 1)
        self.assertGreater(controller.cooldown_remaining(), 0.0)
        self.assertLessEqual(controller.cooldown_remaining(), 30.0)

    def test_repeated_failure_of_same_url_never_trips(self) -> None:
        """单个坏文件反复失败只算一次，不应把整批拖进冷却。"""
        controller = make_controller(threshold=3, cooldown=30)
        url = "https://example.com/broken.pdf"
        for _ in range(6):
            self.assertIsNone(controller.report_failure(url))
        self.assertEqual(controller.cooldown_remaining(), 0.0)
        self.assertEqual(controller.distinct_failure_count(), 1)

    def test_consecutive_trips_escalate(self) -> None:
        controller = make_controller(threshold=1, cooldown=10)
        # 模拟长时间的稳定期，使倍数重新从 1 开始
        controller._last_trip_at = time.monotonic() - config.COOLDOWN_ESCALATION_RESET - 1
        first = controller.report_failure("https://example.com/a.pdf")
        self.assertIsNotNone(first)
        self.assertLessEqual(first.duration, 10.0)

        # 冷却结束后再次触发，倍数翻倍
        controller._cooldown_until = time.monotonic() - 1
        second = controller.report_failure("https://example.com/b.pdf")
        self.assertIsNotNone(second)
        self.assertEqual(second.trip_count, 2)
        self.assertGreater(second.duration, first.duration)
        self.assertLessEqual(second.duration, 20.0)

    def test_failures_outside_window_expire(self) -> None:
        controller = make_controller(threshold=2, cooldown=30)
        controller._failure_events.append(("https://example.com/old.pdf", time.monotonic() - config.CIRCUIT_FAILURE_WINDOW - 1))
        # 旧失败已滑出窗口，不与新的失败叠加
        self.assertIsNone(controller.report_failure("https://example.com/new.pdf"))
        self.assertEqual(controller.distinct_failure_count(), 1)

    # —— 探针信号 ——

    def test_success_signal_marks_when_platform_was_reachable(self) -> None:
        controller = make_controller()
        marker = controller.success_marker()
        controller.report_success()
        self.assertTrue(controller.has_success_since(marker)) # 成功后计数增长 → 平台当时是通的
        self.assertFalse(controller.has_success_since(controller.success_marker())) # 与当前计数相同则不算

    def test_reset_clears_success_signal(self) -> None:
        controller = make_controller()
        controller.report_success()
        controller.reset()
        self.assertFalse(controller.has_success_since(0))

    # —— 暂停 / 取消 / 冷却 ——

    def test_wait_to_start_returns_false_after_cancel(self) -> None:
        controller = make_controller()
        controller.cancel()
        self.assertFalse(controller.wait_to_start())
        self.assertTrue(controller.is_cancelled)

    def test_wait_to_start_blocks_while_paused(self) -> None:
        controller = make_controller()
        controller.pause()
        results: list[bool] = []

        def wait() -> None:
            results.append(controller.wait_to_start())

        thread = threading.Thread(target=wait, daemon=True)
        thread.start()
        time.sleep(0.3)
        self.assertTrue(thread.is_alive(), "暂停期间 wait_to_start 应当阻塞")
        self.assertEqual(results, [])

        controller.resume()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [True])

    def test_cooldown_blocks_until_cancelled(self) -> None:
        controller = make_controller(threshold=1, cooldown=30)
        controller.report_failure("https://example.com/a.pdf")
        self.assertGreater(controller.cooldown_remaining(), 0.0)
        controller.cancel() # 用取消解除阻塞，避免测试真的等 30 秒
        self.assertFalse(controller.wait_to_start())

    def test_reset_clears_all_state(self) -> None:
        controller = make_controller(threshold=1, cooldown=30)
        controller.report_failure("https://example.com/a.pdf")
        controller.pause()
        controller.cancel()
        controller.reset()
        self.assertFalse(controller.is_paused)
        self.assertFalse(controller.is_cancelled)
        self.assertEqual(controller.cooldown_remaining(), 0.0)
        self.assertEqual(controller.distinct_failure_count(), 0)

    def test_check_cancelled_raises(self) -> None:
        controller = make_controller()
        controller.cancel()
        with self.assertRaises(DownloadCancelled):
            controller.check_cancelled()


class SettingParseTest(unittest.TestCase):
    def test_parses_valid_values(self) -> None:
        spec = next(spec for spec in config.DOWNLOAD_SETTING_SPECS if spec.key == "download_workers")
        self.assertEqual(config._parse_setting_value(spec, "3"), 3)
        self.assertEqual(config._parse_setting_value(spec, "6"), 6)

    def test_rejects_out_of_range(self) -> None:
        spec = next(spec for spec in config.DOWNLOAD_SETTING_SPECS if spec.key == "download_workers")
        for raw in ("0", "7", "100"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    config._parse_setting_value(spec, raw)

    def test_rejects_non_numeric(self) -> None:
        spec = next(spec for spec in config.DOWNLOAD_SETTING_SPECS if spec.key == "min_request_interval")
        for raw in ("abc", "", "  ", "nan", "inf"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    config._parse_setting_value(spec, raw)

    def test_integer_spec_rejects_fraction(self) -> None:
        spec = next(spec for spec in config.DOWNLOAD_SETTING_SPECS if spec.key == "cooldown_seconds")
        with self.assertRaises(ValueError):
            config._parse_setting_value(spec, "3.5")

    def test_float_spec_accepts_fraction(self) -> None:
        spec = next(spec for spec in config.DOWNLOAD_SETTING_SPECS if spec.key == "min_request_interval")
        self.assertAlmostEqual(config._parse_setting_value(spec, "0.15"), 0.15)

    def test_load_download_settings_ignores_invalid_saved_values(self) -> None:
        original = dict(config.download_settings)
        try:
            config.download_settings["download_workers"] = 5
            config.load_download_settings({"download_workers": "999999", "cooldown_seconds": "abc"})
            self.assertEqual(config.download_settings["download_workers"], 5) # 非法值被忽略
            self.assertEqual(config.download_settings["cooldown_seconds"], original["cooldown_seconds"])
        finally:
            config.download_settings.clear()
            config.download_settings.update(original)

    def test_saving_settings_notifies_listeners(self) -> None:
        """设置保存后应通知注册的回调（下载模块靠它同步派生参数，无需被设置窗口直接依赖）。"""
        calls: list[int] = []
        config.on_download_settings_changed(lambda: calls.append(1))
        self.addCleanup(config._download_settings_listeners.clear)
        original = dict(config.download_settings)
        self.addCleanup(config.download_settings.update, original)

        with patch.object(config, "save_config"):
            config.set_download_settings({spec.key: str(spec.default) for spec in config.DOWNLOAD_SETTING_SPECS})

        self.assertEqual(calls, [1])

    def test_same_listener_is_registered_once(self) -> None:
        def listener() -> None:
            pass

        self.addCleanup(config._download_settings_listeners.clear)

        config.on_download_settings_changed(listener)
        config.on_download_settings_changed(listener)

        self.assertEqual(config._download_settings_listeners.count(listener), 1)


if __name__ == "__main__":
    unittest.main()
