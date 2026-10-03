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
        self.warning.assert_called_once()
        self.notice.assert_not_called()
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

        self.warning.assert_called_once()
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
        failed_message = self.warning.call_args[0][1]
        self.assertIn("已跳过重试", failed_message)
        self.assertNotIn("疑似限流", failed_message)

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
        self.warning.assert_called_once()

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
