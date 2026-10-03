from pathlib import Path
from contextlib import ExitStack
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from src.tchmaterial_parser.api import ResourceInfo
from src.tchmaterial_parser.ui import download_panel as panel


class LogRecorder:
    """日志控件的替身：记录写进日志区的每一行。"""

    def __init__(self):
        self.lines: list[str] = []

    def config(self, **kwargs):
        pass

    def configure(self, **kwargs):
        pass

    def insert(self, index, text):
        self.lines.append(text.strip())

    def see(self, index):
        pass


class DownloadBatchTest(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.callbacks = queue.Queue()
        self.threads = []
        self.root_directory = Path(__file__).resolve().parents[1] / ".tmp"
        self.root_directory.mkdir(exist_ok=True)
        self.directory = self.context.enter_context(tempfile.TemporaryDirectory(dir=self.root_directory))
        self.context.enter_context(patch.object(panel, "download_states", []))
        for name in ("progress_label", "download_progress_bar", "download_btn"):
            self.context.enter_context(patch.object(panel.widgets, name, Mock()))
        self.notice = self.context.enter_context(patch.object(panel.messagebox, "showinfo"))
        self.warning = self.context.enter_context(patch.object(panel.messagebox, "showwarning"))
        # 默认「不打开清单」：返回真值的话 open_path 会真的去调系统默认程序打开文件
        self.ask_yes_no = self.context.enter_context(patch.object(panel.messagebox, "askyesno", return_value=False))
        self.open_path = self.context.enter_context(patch.object(panel, "open_path"))
        self.context.enter_context(patch.object(panel, "ui_call", lambda fn, *args, **kwargs: self.callbacks.put((fn, args, kwargs))))
        self.addCleanup(panel.controller.reset) # 每个用例结束后清理暂停/取消状态

        def thread_it(fn):
            thread = threading.Thread(target=fn, daemon=True)
            self.threads.append(thread)
            thread.start()

        self.context.enter_context(patch.object(panel, "thread_it", thread_it))

    def targets(self, count):
        return [(ResourceInfo(f"教材{index}", f"https://example.com/{index}.pdf", "pdf", []), str(Path(self.directory) / f"教材{index}.pdf")) for index in range(count)]

    def finish(self):
        for thread in self.threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), "批次线程没有退出")
        while not self.callbacks.empty():
            fn, args, kwargs = self.callbacks.get_nowait()
            fn(*args, **kwargs)

    def test_all_tasks_registered_before_fast_failure_and_queued_work(self):
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        observed = []

        def download(url, path, chapters, state):
            observed.append(len(panel.download_states))
            if url.endswith("/0.pdf"):
                state["failed_reason"] = "HTTP 404"
            else:
                entered.set()
                release.wait(timeout=5)
            state["finished"] = True

        with patch.object(panel, "download_file", download):
            panel.start_download_batch(self.targets(5), self.directory)
            self.assertTrue(entered.wait(timeout=3))
            self.assertTrue(panel.downloads_active())
            # 队列中此时只有状态轮询回调（schedule_status_updates），
            # 关键是没有触发批次结束：下载按钮不应被恢复
            panel.widgets.download_btn.config.assert_not_called()
            release.set()
            self.finish()

        self.assertEqual(observed, [5] * 5)
        self.ask_yes_no.assert_called_once()
        self.warning.assert_not_called()
        panel.widgets.download_btn.config.assert_called_once_with(state="normal")

    def test_concurrent_downloads_emit_one_batch_notice(self):
        barrier = threading.Barrier(2)

        class Response:
            ok = False
            status_code = 404
            content = b""

            def close(self):
                barrier.wait(timeout=3)

        with patch.object(panel, "request_download", side_effect=lambda url: (Response(), [url])):
            panel.start_download_batch(self.targets(2), self.directory)
            self.finish()

        self.ask_yes_no.assert_called_once()
        self.assertFalse(panel.downloads_active())
        self.assertTrue(all(state["failed_reason"] for state in panel.download_states))

    def test_successful_batch_creates_subdirectories_and_reports_root(self):
        class Response:
            ok = True
            headers = {"Content-Length": "2"}

            def iter_content(self, **kwargs):
                yield b"ok"

            def close(self):
                pass

        targets = [(resource, str(Path(self.directory) / resource.title / "book.pdf")) for resource, _ in self.targets(2)]
        with patch.object(panel, "request_download", side_effect=lambda url: (Response(), [url])):
            panel.start_download_batch(targets, self.directory)
            self.finish()

        self.notice.assert_called_once_with("下载完成", f"文件已下载到：{self.directory}")
        self.warning.assert_not_called()
        self.assertFalse((Path(self.directory) / panel.FAILURE_LIST_FILENAME).exists()) # 全成功就不写清单
        for _, path in targets:
            self.assertEqual(Path(path).read_bytes(), b"ok")
            self.assertFalse(Path(f"{path}.tmp").exists())

    def test_burst_failures_are_retried_once_at_the_end(self):
        """成片失败（多个文件几乎同时失败）判定为限流，末尾再试一次。"""
        attempts: dict[str, int] = {}

        def download(url, path, chapters, state):
            attempts[url] = attempts.get(url, 0) + 1
            if attempts[url] == 1:
                state["failed_reason"] = "服务器返回 HTTP 状态码 400"
                state["retryable"] = True
                state["failed_at"] = time.monotonic()
            else:
                state["failed_reason"] = None
                state["retryable"] = False
            state["finished"] = True

        with patch.object(panel, "download_file", download), \
             patch.dict(panel.config.download_settings, {"retry_rounds": 1}):
            panel.start_download_batch(self.targets(2), self.directory)
            self.finish()

        self.assertEqual(sorted(attempts.values()), [2, 2]) # 每个文件都被重试了一次
        self.notice.assert_called_once_with("下载完成", f"文件已下载到：{self.directory}")
        self.warning.assert_not_called()

    def test_burst_failures_are_retried_even_when_later_downloads_succeed(self):
        """回归：失败之后隔很久还有别的文件成功，也仍然算限流，不能被判成文件自身问题。

        旧实现看的是「失败之后直到批次结束之间有没有文件成功」——大批量任务里这个条件
        恒为真（批次动辄跑几小时），实测一次 6 小时批次 213 个失败全部被跳过、重试 0 个。
        """
        attempts: dict[str, int] = {}

        def download(url, path, chapters, state):
            attempts[url] = attempts.get(url, 0) + 1
            if url.endswith("/2.pdf"): # 第三个文件正常下载成功
                state["finished"] = True
                return
            if attempts[url] == 1:
                state["failed_reason"] = "服务器返回 HTTP 状态码 400"
                state["retryable"] = True
                state["failed_at"] = time.monotonic()
            else:
                state["failed_reason"] = None
            state["finished"] = True

        with patch.object(panel, "download_file", download), \
             patch.dict(panel.config.download_settings, {"retry_rounds": 1}):
            panel.start_download_batch(self.targets(3), self.directory)
            self.finish()

        self.assertEqual(sorted(attempts.values()), [1, 2, 2]) # 成片失败的 2 个被重试
        self.notice.assert_called_once_with("下载完成", f"文件已下载到：{self.directory}")
        self.warning.assert_not_called()

    def test_burst_failures_are_not_retried_when_retry_is_disabled(self):
        """末尾重试次数设为 0 时，成片失败的文件也不再重试。"""
        attempts: dict[str, int] = {}

        def download(url, path, chapters, state):
            attempts[url] = attempts.get(url, 0) + 1
            state["failed_reason"] = "服务器返回 HTTP 状态码 400"
            state["retryable"] = True
            state["failed_at"] = time.monotonic()
            state["finished"] = True

        with patch.object(panel, "download_file", download), \
             patch.dict(panel.config.download_settings, {"retry_rounds": 0}):
            panel.start_download_batch(self.targets(2), self.directory)
            self.finish()

        self.assertEqual(sorted(attempts.values()), [1, 1])

    def test_isolated_failure_is_not_retried(self):
        """孤立失败（前后没有别的文件也在失败）判定为文件自身不可用，不重试。"""
        attempts: dict[str, int] = {}

        def download(url, path, chapters, state):
            attempts[url] = attempts.get(url, 0) + 1
            if url.endswith("/0.pdf"):
                state["failed_reason"] = "服务器返回 HTTP 状态码 400"
                state["retryable"] = True
                state["failed_at"] = time.monotonic()
            state["finished"] = True

        with patch.object(panel, "download_file", download), \
             patch.dict(panel.config.download_settings, {"retry_rounds": 1}):
            panel.start_download_batch(self.targets(2), self.directory)
            self.finish()

        self.assertEqual(sorted(attempts.values()), [1, 1]) # 坏文件未被重试
        failed_message = self.ask_yes_no.call_args[0][1]
        self.assertIn("已跳过重试", failed_message)
        self.assertNotIn("疑似限流", failed_message)

    def test_failure_list_is_saved_and_opened_on_confirm(self):
        """失败清单写成下载目录下的文件；只在用户确认时才去打开，弹窗本身保持简短。"""
        def download(url, path, chapters, state):
            state["failed_reason"] = "服务器返回 HTTP 状态码 404（资源不存在：该文件可能已从平台下架）"
            state["retryable"] = False
            state["finished"] = True

        self.ask_yes_no.return_value = True
        with patch.object(panel, "download_file", download):
            panel.start_download_batch(self.targets(2), self.directory)
            self.finish()

        list_path = Path(self.directory) / panel.FAILURE_LIST_FILENAME
        content = list_path.read_text(encoding="utf-8")
        self.assertIn("教材0.pdf", content)
        self.assertIn("教材1.pdf", content)
        self.assertIn("404", content)
        self.open_path.assert_called_once_with(str(list_path))

        # 弹窗只报数字与清单位置，不再把每一条失败原因塞进去（这才是它撑满屏幕的原因）
        dialog = self.ask_yes_no.call_args[0][1]
        self.assertNotIn("服务器返回", dialog)
        self.assertLess(len(dialog), 400)

    def test_failure_list_is_not_opened_when_declined(self):
        def download(url, path, chapters, state):
            state["failed_reason"] = "服务器返回 HTTP 状态码 404"
            state["retryable"] = False
            state["finished"] = True

        with patch.object(panel, "download_file", download):
            panel.start_download_batch(self.targets(1), self.directory)
            self.finish()

        self.assertTrue((Path(self.directory) / panel.FAILURE_LIST_FILENAME).exists())
        self.open_path.assert_not_called()

    def test_failure_list_is_written_to_the_log(self):
        """失败清单必须落进日志区：只弹对话框的话，关掉就再也拿不到名单。"""
        def download(url, path, chapters, state):
            state["failed_reason"] = "服务器返回 HTTP 状态码 404"
            state["retryable"] = False
            state["finished"] = True

        recorder = LogRecorder()
        with patch.object(panel.widgets, "log_text", recorder), \
             patch.object(panel, "download_file", download):
            panel.start_download_batch(self.targets(2), self.directory)
            self.finish()

        log = "\n".join(recorder.lines)
        self.assertIn("[清单]", log)
        self.assertIn("已跳过重试", log)
        self.assertIn("教材0.pdf", log)
        self.assertIn("教材1.pdf", log)

    def test_non_retryable_failures_are_not_requeued(self):
        """404 等永久失败不会被重新排队。"""
        attempts: dict[str, int] = {}

        def download(url, path, chapters, state):
            attempts[url] = attempts.get(url, 0) + 1
            state["failed_reason"] = "服务器返回 HTTP 状态码 404"
            state["retryable"] = False
            state["finished"] = True

        with patch.object(panel, "download_file", download), \
             patch.dict(panel.config.download_settings, {"retry_rounds": 1}):
            panel.start_download_batch(self.targets(2), self.directory)
            self.finish()

        self.assertEqual(sorted(attempts.values()), [1, 1]) # 没有重试
        self.ask_yes_no.assert_called_once()

    def test_log_panel_records_progress_and_result(self):
        """日志区应记录开始、每个文件的结果与批次汇总。"""
        class Response:
            def __init__(self, status_code):
                self.ok = status_code < 400
                self.status_code = status_code
                self.content = b""
                self.headers = {"Content-Length": "2"}

            def iter_content(self, **kwargs):
                yield b"ok"

            def close(self):
                pass

        recorder = LogRecorder()
        targets = self.targets(2)
        responses = {targets[0][0].url: Response(404), targets[1][0].url: Response(200)}
        with patch.object(panel.widgets, "log_text", recorder), \
             patch.object(panel, "request_download", side_effect=lambda url: (responses[url], [url])):
            panel.start_download_batch(targets, self.directory)
            self.finish()

        log = "\n".join(recorder.lines)
        self.assertIn("[开始]", log)
        self.assertIn("[完成]", log)
        self.assertIn("[失败]", log)
        self.assertIn("资源不存在", log) # 状态码附带中文解释
        self.assertIn("[结束]", log)

    def test_shutdown_cancels_and_waits_for_downloads(self):
        """退出前应取消下载并等待收尾，避免 .tmp 残留与进程在后台滞留。"""
        states = [panel.create_download_state("https://example.com/a.pdf", str(Path(self.directory) / "a.pdf"))]
        with patch.object(panel, "download_states", states):
            def finish_soon():
                time.sleep(0.2)
                states[0]["finished"] = True

            worker = threading.Thread(target=finish_soon, daemon=True)
            worker.start()
            panel.shutdown_downloads(timeout=3)
            worker.join(timeout=1)

            self.assertTrue(panel.controller.is_cancelled)
            self.assertTrue(states[0]["finished"])

    def test_shutdown_does_nothing_when_nothing_is_running(self):
        with patch.object(panel, "download_states", []):
            panel.shutdown_downloads(timeout=0.1)
        self.assertFalse(panel.controller.is_cancelled)

    def test_next_failure_list_path_adds_timestamp_when_name_is_taken(self):
        """回归 B5：同名清单已存在时改用带时间戳的名字，绝不覆盖。"""
        base = Path(self.directory) / panel.FAILURE_LIST_FILENAME
        self.assertEqual(panel.next_failure_list_path(self.directory), str(base))

        base.write_text("第一批", encoding="utf-8")
        second = panel.next_failure_list_path(self.directory)

        self.assertNotEqual(second, str(base))
        self.assertEqual(Path(second).parent, Path(self.directory))
        self.assertTrue(Path(second).name.startswith("下载失败清单_"))
        self.assertTrue(second.endswith(".txt"))
        self.assertEqual(base.read_text(encoding="utf-8"), "第一批")  # 第一批内容原样保留

    def test_failure_lists_from_two_batches_do_not_overwrite_each_other(self):
        """回归 B5：同目录连跑两批，「先下一批→看清单→再补下」的第二次不能盖掉第一次的清单。"""
        def download(url, path, chapters, state):
            state["failed_reason"] = "服务器返回 HTTP 状态码 404"
            state["retryable"] = False
            state["finished"] = True

        with patch.object(panel, "download_file", download):
            panel.start_download_batch(self.targets(1), self.directory)
            self.finish()
            panel.start_download_batch(self.targets(1), self.directory)
            self.finish()

        names = sorted(path.name for path in Path(self.directory).glob("下载失败清单*.txt"))
        self.assertEqual(len(names), 2)
        self.assertIn(panel.FAILURE_LIST_FILENAME, names)

    def test_shutdown_timeout_follows_the_chunk_read_timeout(self):
        """回归 B6：退出等待上限不能死写 5 秒；分块读超时最长就是 download_timeout。"""
        with patch.dict(panel.config.download_settings, {"download_timeout": 60}):
            self.assertEqual(panel.shutdown_timeout(), 62.0)
        with patch.dict(panel.config.download_settings, {"download_timeout": 10}):
            self.assertEqual(panel.shutdown_timeout(), 12.0)

    def test_shutdown_without_explicit_timeout_uses_the_configured_limit(self):
        states = [panel.create_download_state("https://example.com/a.pdf", str(Path(self.directory) / "a.pdf"))]
        with patch.object(panel, "download_states", states), \
             patch.object(panel, "shutdown_timeout", return_value=0.2) as configured:
            panel.shutdown_downloads()

        configured.assert_called_once()
        self.assertTrue(panel.controller.is_cancelled)

    def test_unparsed_urls_warn_only_counts_and_log_details(self):
        """回归 B8：几百条坏链接只弹一个数量提示，明细（脱敏后）进日志区。"""
        logged: list[str] = []
        failed = {f"https://example.com/bad{index}?accessToken=secret{index}" for index in range(5)}
        with patch.object(panel, "log_message", logged.append):
            panel.warn_unparsed_urls(failed)

        self.warning.assert_called_once()
        message = self.warning.call_args[0][1]
        self.assertIn("5", message)
        self.assertLess(len(message), 200)  # 弹窗只报数量，不再把每条链接堆进去
        for url in failed:
            self.assertNotIn(url, message)

        log = "\n".join(logged)
        self.assertIn("无法解析", log)
        self.assertIn("https://example.com/bad0", log)
        self.assertNotIn("secret0", log)  # accessToken 已被脱敏
        self.assertIn("<已隐藏>", log)

    def test_unparsed_urls_do_not_warn_when_nothing_failed(self):
        with patch.object(panel, "log_message"):
            panel.warn_unparsed_urls(set())
        self.warning.assert_not_called()

    def test_parse_and_copy_disables_download_button_while_parsing(self):
        """回归 B10：解析期间「下载」也要禁用。

        否则解析还没结束用户就能再点一次，跑起第二条解析流水线：两条共享进度标签互相覆盖、
        各弹一个对话框、还都会去 reset 控制器。
        """
        copy_btn = self.context.enter_context(patch.object(panel.widgets, "copy_btn", Mock()))
        url_text = self.context.enter_context(patch.object(panel.widgets, "url_text", Mock()))
        url_text.get.return_value = "https://example.com/1\n"

        captured: dict = {}
        self.context.enter_context(patch.object(
            panel, "parse_urls_in_background",
            lambda urls, bookmarks, on_finished: captured.update(on_finished=on_finished),
        ))

        panel.parse_and_copy()

        copy_btn.config.assert_called_with(state="disabled")
        panel.widgets.download_btn.config.assert_called_with(state="disabled")

        panel.widgets.download_btn.config.reset_mock()
        copy_btn.config.reset_mock()
        captured["on_finished"]([], set())  # 模拟后台解析完成

        panel.widgets.download_btn.config.assert_called_with(state="normal")
        copy_btn.config.assert_called_with(state="normal")
