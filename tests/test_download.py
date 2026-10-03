import unittest
from urllib.parse import urlsplit

from requests import ConnectionError

from src.tchmaterial_parser.ui import download_panel, runtime


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.ok = status_code < 400
        self.status_code = status_code
        self.content = content

    def close(self) -> None:
        pass


class FakeSession:
    def __init__(self, status_code: int | list[int]) -> None:
        self.status_codes = status_code if isinstance(status_code, list) else [status_code]
        self.requested_urls: list[str] = []
        self.requested_headers: list[dict | None] = []

    def get(self, *args: tuple, **kwargs: dict) -> FakeResponse:
        self.requested_urls.append(args[0])
        self.requested_headers.append(kwargs.get("headers"))
        status_code = self.status_codes[min(len(self.requested_urls) - 1, len(self.status_codes) - 1)]
        return FakeResponse(status_code)


class FakeWidget:
    def config(self, **kwargs: dict) -> None:
        pass


class FailingSession:
    def get(self, url: str, **kwargs: dict) -> FakeResponse:
        raise ConnectionError(f"无法访问 {url}")


class DownloadFailureTest(unittest.TestCase):
    def setUp(self) -> None:
        # 置为关闭状态后 ui_call() 不会真正执行回调，因此桩控件只需提供 config 属性
        runtime.app_closing = True
        self.addCleanup(setattr, runtime, "app_closing", False)
        self.addCleanup(setattr, download_panel, "session", download_panel.session)
        previous_token = download_panel.config.access_token
        previous_mac = download_panel.config.mac_key
        previous_diff = download_panel.config.token_diff
        self.addCleanup(setattr, download_panel.config, "access_token", previous_token)
        self.addCleanup(setattr, download_panel.config, "mac_key", previous_mac)
        self.addCleanup(setattr, download_panel.config, "token_diff", previous_diff)
        download_panel.config.mac_key = None
        download_panel.config.token_diff = 0
        previous_interval = download_panel._MIN_REQUEST_INTERVAL
        self.addCleanup(setattr, download_panel, "_MIN_REQUEST_INTERVAL", previous_interval)
        download_panel._MIN_REQUEST_INTERVAL = 0
        widget = FakeWidget()
        download_panel.bind_widgets(widget, widget, widget, widget, widget, widget)

    def failure_reason(self, status_code: int) -> str:
        download_panel.session = FakeSession(status_code)
        download_panel.download_states = []
        download_panel.download_file("https://example.invalid/book.pdf", "book.pdf")
        return download_panel.download_states[0]["failed_reason"]

    def test_reports_server_errors_unrelated_to_the_token(self) -> None:
        self.assertEqual(
            self.failure_reason(404),
            "服务器返回 HTTP 状态码 404（资源不存在：该文件可能已从平台下架）",
        )

    def test_explains_status_codes_in_chinese(self) -> None:
        # 用户可能不认识状态码，日志与提示都要给出中文解释
        self.assertEqual(download_panel.status_hint(429), "请求过于频繁：已被平台限流")
        self.assertEqual(download_panel.status_hint(403), "无权限访问该资源")
        self.assertEqual(download_panel.status_hint(501), "平台服务器暂时异常") # 未逐条列举的 5xx
        self.assertIsNone(download_panel.status_hint(200))

    def test_appends_a_token_hint_to_authentication_failures(self) -> None:
        download_panel.config.access_token = "private-token"
        expected = {
            401: "服务器返回 HTTP 状态码 401（未登录或登录已过期），Access Token 可能已过期或无效，请重新设置",
            403: "服务器返回 HTTP 状态码 403（无权限访问该资源），Access Token 可能已过期或无效，请重新设置",
        }
        for status_code, text in expected.items():
            with self.subTest(status_code=status_code):
                self.assertEqual(self.failure_reason(status_code), text)

    def test_asks_for_token_when_anonymous_request_requires_authentication(self) -> None:
        download_panel.config.access_token = None
        self.assertEqual(
            self.failure_reason(401),
            "服务器返回 HTTP 状态码 401（未登录或登录已过期），该资源需要有效的 Access Token，请先设置",
        )

    def test_keeps_token_out_of_private_request_url(self) -> None:
        token = "private-token"
        download_panel.config.access_token = token
        fake_session = FakeSession(404)
        download_panel.session = fake_session
        original_url = "https://r1-ndr-private.ykt.cbern.com.cn/book.pdf?source=catalog"

        download_panel.download_states = []
        download_panel.download_file(original_url, "book.pdf")

        requested_url = fake_session.requested_urls[0]
        self.assertEqual(requested_url, original_url)
        self.assertNotIn("accessToken", requested_url)
        self.assertEqual(
            fake_session.requested_headers[0]["X-ND-AUTH"],
            'MAC id="private-token",nonce="0",mac="0"',
        )
        self.assertEqual(download_panel.download_states[0]["download_url"], original_url)
        self.assertNotIn(token, download_panel.download_states[0]["failed_reason"])

    def test_signs_private_download_when_mac_key_is_present(self) -> None:
        download_panel.config.access_token = "tok"
        download_panel.config.mac_key = "key"
        download_panel.config.token_diff = 0
        fake_session = FakeSession(200)
        download_panel.session = fake_session
        url = "https://r1-ndr-private.ykt.cbern.com.cn/book.pdf"

        download_panel.request_download(url)

        auth = fake_session.requested_headers[0]["X-ND-AUTH"]
        self.assertTrue(auth.startswith('MAC id="tok",nonce="'))
        self.assertNotIn('nonce="0"', auth)
        self.assertNotIn("accessToken", fake_session.requested_urls[0])

    def test_retries_private_download_on_the_next_mirror(self) -> None:
        download_panel.config.access_token = "private-token"
        fake_session = FakeSession([500, 200])
        download_panel.session = fake_session
        original_url = "https://r1-ndr-private.ykt.cbern.com.cn/book.pdf"

        response, attempted_urls = download_panel.request_download(original_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([url.split("/", 3)[2] for url in attempted_urls], [
            "r1-ndr-private.ykt.cbern.com.cn",
            "r2-ndr-private.ykt.cbern.com.cn",
        ])
        self.assertEqual(fake_session.requested_urls, [
            "https://r1-ndr-private.ykt.cbern.com.cn/book.pdf",
            "https://r2-ndr-private.ykt.cbern.com.cn/book.pdf",
        ])
        self.assertTrue(all("accessToken" not in url for url in attempted_urls))

    def test_retries_same_host_on_transient_400(self) -> None:
        download_panel.config.access_token = "tok"
        download_panel.config.mac_key = "key"
        previous_delays = download_panel._400_RETRY_DELAYS
        download_panel._400_RETRY_DELAYS = (0,)
        self.addCleanup(setattr, download_panel, "_400_RETRY_DELAYS", previous_delays)
        fake_session = FakeSession([400, 200])
        download_panel.session = fake_session
        original_url = "https://r1-ndr-private.ykt.cbern.com.cn/book.pdf"

        response, attempted_urls = download_panel.request_download(original_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(attempted_urls, [original_url])
        self.assertEqual(fake_session.requested_urls, [original_url, original_url])
        self.assertNotEqual(
            fake_session.requested_headers[0]["X-ND-AUTH"],
            fake_session.requested_headers[1]["X-ND-AUTH"],
        )
        self.assertTrue(all("accessToken" not in url for url in fake_session.requested_urls))

    def test_does_not_spray_mirrors_after_persistent_400(self) -> None:
        download_panel.config.access_token = "tok"
        download_panel.config.mac_key = "key"
        previous_delays = download_panel._400_RETRY_DELAYS
        download_panel._400_RETRY_DELAYS = (0,)
        self.addCleanup(setattr, download_panel, "_400_RETRY_DELAYS", previous_delays)
        fake_session = FakeSession(400)
        download_panel.session = fake_session
        original_url = "https://r1-ndr-private.ykt.cbern.com.cn/book.pdf"

        response, attempted_urls = download_panel.request_download(original_url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(attempted_urls, [original_url])
        self.assertEqual(fake_session.requested_urls, [original_url, original_url])

    def test_does_not_spray_mirrors_after_rate_limit(self) -> None:
        """429 是平台在明说“你太快了”，此时接着打 r2/r3 只会把限流打得更死。

        这里曾经写成 break —— 它只跳出内层 while，外层 for 会继续换镜像，把请求量翻成三倍。
        """
        download_panel.config.access_token = "tok"
        download_panel.config.mac_key = "key"
        self.addCleanup(download_panel.controller.reset) # 本用例会上报一次限流，别把冷却状态漏给后续用例
        fake_session = FakeSession(429)
        download_panel.session = fake_session
        url = "https://r1-ndr-private.ykt.cbern.com.cn/book.pdf"

        response, attempted_urls = download_panel.request_download(url)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(attempted_urls, [url])
        self.assertEqual(fake_session.requested_urls, [url])

    def test_keeps_port_when_rebuilding_mirror_urls(self) -> None:
        """urlsplit().hostname 不含端口，重建时丢掉它会让请求静默打到 443。"""
        urls = download_panel.download_mirror_urls("https://r1-ndr-private.ykt.cbern.com.cn:8443/book.pdf")

        self.assertEqual(len(urls), 3)
        self.assertEqual([urlsplit(url).port for url in urls], [8443, 8443, 8443])
        self.assertEqual(urlsplit(urls[1]).hostname, "r2-ndr-private.ykt.cbern.com.cn")
        self.assertEqual(
            download_panel.download_mirror_urls("https://example.com:8443/book.pdf"),
            ["https://example.com:8443/book.pdf"], # 公开地址原样返回
        )

    def test_does_not_retry_authentication_failures_or_public_urls(self) -> None:
        private_url = "https://r1-ndr-private.ykt.cbern.com.cn/book.pdf"
        public_url = "https://example.com/book.pdf"

        private_session = FakeSession(401)
        download_panel.session = private_session
        _response, private_attempts = download_panel.request_download(private_url)
        self.assertEqual(private_attempts, [private_url])

        public_session = FakeSession(500)
        download_panel.session = public_session
        _response, public_attempts = download_panel.request_download(public_url)
        self.assertEqual(public_attempts, [public_url])

    def test_does_not_try_other_mirrors_for_missing_object(self) -> None:
        """404 说明对象在三个镜像上都不存在（同一存储后端），不该再打 r2/r3。"""
        fake_session = FakeSession(404)
        download_panel.session = fake_session
        url = "https://r1-ndr-private.ykt.cbern.com.cn/book.pdf"

        response, attempted_urls = download_panel.request_download(url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(attempted_urls, [url])
        self.assertEqual(fake_session.requested_urls, [url])

    def test_explains_private_storage_authentication_errors(self) -> None:
        response = FakeResponse(400, b"<Error><Code>InvalidArgument</Code></Error>")
        attempted_urls = ["https://r1.example/book.pdf", "https://r2.example/book.pdf"]

        download_panel.config.access_token = None
        self.assertEqual(
            download_panel.download_failure_reason(response, attempted_urls),
            "服务器返回 HTTP 状态码 400（请求无效：多为被平台限流，或该资源地址已失效）（对象存储返回 InvalidArgument），该私有资源需要有效的 Access Token，请先设置，已尝试 2 个下载镜像",
        )

        download_panel.config.access_token = "private-token"
        self.assertEqual(
            download_panel.download_failure_reason(response, attempted_urls),
            "服务器返回 HTTP 状态码 400（请求无效：多为被平台限流，或该资源地址已失效）（对象存储返回 InvalidArgument），私有资源暂时无法访问。请稍后重试；若持续失败，请重新设置 Access Token，已尝试 2 个下载镜像",
        )

    def test_redacts_token_from_network_exceptions(self) -> None:
        token = "private-token"
        download_panel.config.access_token = token
        download_panel.session = FailingSession()

        with self.assertRaises(RuntimeError) as context:
            download_panel.request_download("https://r1-ndr-private.ykt.cbern.com.cn/book.pdf")

        self.assertNotIn(token, str(context.exception))
        self.assertIn("ndr-private.ykt.cbern.com.cn/book.pdf", str(context.exception))
        self.assertNotIn("accessToken", str(context.exception))


class PanelWidgetsTest(unittest.TestCase):
    def test_widgets_default_to_none(self) -> None:
        """控件句柄未绑定时应为 None，而不是“未定义的名字”。"""
        fresh = download_panel.PanelWidgets()

        self.assertIsNone(fresh.url_text)
        self.assertIsNone(fresh.download_btn)
        self.assertIsNone(fresh.progress_label)
        self.assertIsNone(fresh.pause_btn)
        self.assertIsNone(fresh.cancel_btn)
        self.assertIsNone(fresh.log_text)

    def test_bind_widgets_fills_the_holder(self) -> None:
        widget = FakeWidget()

        download_panel.bind_widgets(widget, widget, widget, widget, widget, widget)

        self.assertIs(download_panel.widgets.url_text, widget)
        self.assertIs(download_panel.widgets.progress_label, widget)
        self.assertIsNone(download_panel.widgets.pause_btn) # 未传入的可选控件保持 None


if __name__ == "__main__":
    unittest.main()
