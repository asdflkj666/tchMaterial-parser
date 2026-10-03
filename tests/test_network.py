import json
import unittest
from unittest.mock import Mock, patch

from requests import ReadTimeout, Response
from requests.adapters import BaseAdapter

from src.tchmaterial_parser import api, config, network
from src.tchmaterial_parser.ui import download_panel


class MetadataAdapter(BaseAdapter):
    def __init__(self):
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append((request.url, kwargs.get("timeout")))
        if "bad.json" in request.url:
            raise ReadTimeout("模拟读取超时")
        if "mapping.json" in request.url:
            data = {"ebook_id": "book", "mappings": [{"node_id": "chapter", "page_number": 1}]}
        elif "/trees/" in request.url:
            data = [{"id": "chapter", "title": "第一章"}]
        elif "relation_audios.json" in request.url:
            data = []
        else:
            data = {"title": "教材", "ti_items": [
                {"ti_is_source_file": True, "ti_file_flag": "source", "ti_format": "pdf", "ti_storage": "https://example.com/book.pdf"},
                {"ti_file_flag": "ebook_mapping", "ti_storage": "https://example.com/mapping.json"},
            ]}
        response = Response()
        response.status_code = 200
        response.url = request.url
        response._content = json.dumps(data).encode("utf-8")
        return response

    def close(self):
        pass


class RequestTimeoutTest(unittest.TestCase):
    def setUp(self):
        self.session = network.TimeoutSession()
        self.session.trust_env = False
        self.adapter = MetadataAdapter()
        self.session.mount("https://", self.adapter)
        self.addCleanup(self.session.close)

    def test_defaults_cover_details_mapping_chapters_and_audio(self):
        with patch.object(api, "session", self.session):
            result = api.parse("https://basic.smartedu.cn/tchMaterial/detail?contentId=book", True)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].chapters, [{"title": "第一章", "page_index": 1}])
        self.assertEqual(len(self.adapter.calls), 4)
        self.assertTrue(all(timeout == network.REQUEST_TIMEOUT for _, timeout in self.adapter.calls))

    def test_explicit_timeout_is_preserved(self):
        self.session.get("https://example.com/details.json", timeout=(1, 2))
        self.assertEqual(self.adapter.calls[0][1], (1, 2))

    def test_timeout_does_not_block_remaining_urls_or_completion_callback(self):
        bad = "https://basic.smartedu.cn/tchMaterial/detail?contentId=bad"
        good = "https://basic.smartedu.cn/tchMaterial/detail?contentId=good"
        completed = Mock()
        with patch.object(api, "session", self.session), patch.object(api, "print_error"), patch.object(download_panel.widgets, "progress_label", Mock()), patch.object(download_panel, "download_states", []), patch.object(download_panel, "thread_it", lambda fn: fn()), patch.object(download_panel, "ui_call", lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            download_panel.parse_urls_in_background([bad, good], False, completed)

        completed.assert_called_once()
        resources, failed = completed.call_args.args
        self.assertEqual([resource.url for resource in resources], ["https://example.com/book.pdf"])
        self.assertEqual(failed, {bad})


class RelationsAdapter(BaseAdapter):
    """relations 里混进一个没有 ti_items 的子资源。"""

    def send(self, request, **kwargs):
        data = {"title": "课程包", "relations": {"ebook": [
            {"title": "坏条目"}, # 缺 ti_items
            {"title": "好条目", "ti_items": [
                {"ti_is_source_file": True, "ti_file_flag": "source", "ti_format": "pdf", "ti_storage": "https://example.com/good.pdf"},
            ]},
        ]}}
        response = Response()
        response.status_code = 200
        response.url = request.url
        response._content = json.dumps(data).encode("utf-8")
        return response

    def close(self):
        pass


class SessionHeadersTest(unittest.TestCase):
    """headers 定义了却从没装到 session 上：所有公开请求会顶着 requests 的默认身份发出，很容易被 WAF 拦。"""

    def test_global_headers_are_installed_on_the_session(self):
        for name, value in network.headers.items():
            with self.subTest(header=name):
                self.assertEqual(network.session.headers.get(name), value)
        self.assertNotIn("python-requests", network.session.headers.get("User-Agent", ""))

    def test_session_headers_follow_token_changes(self):
        """apply_static_headers 原地改的是 headers 字典，已建好的 session 必须跟着更新。"""
        token_before = config.access_token
        self.addCleanup(config.apply_static_headers) # 先注册的后执行：先把 token 还原，再重刷头部
        self.addCleanup(setattr, config, "access_token", token_before)

        config.access_token = "brand-new-token"
        config.apply_static_headers()

        self.assertEqual(network.session.headers["Authorization"], "Bearer brand-new-token")
        self.assertIn('id="brand-new-token"', network.session.headers["X-ND-AUTH"])


class BrokenSubResourceTest(unittest.TestCase):
    def test_one_broken_sub_resource_does_not_lose_the_whole_url(self):
        """专题课/课程包是一条 URL 对应 N 个子资源：其中一个缺 ti_items 不该让整条 URL 解析失败。"""
        session = network.TimeoutSession()
        session.trust_env = False
        session.mount("https://", RelationsAdapter())
        self.addCleanup(session.close)

        with patch.object(api, "session", session):
            result = api.parse("https://basic.smartedu.cn/tchMaterial/detail?contentId=course-pack", False)

        self.assertEqual([resource.url for resource in result], ["https://example.com/good.pdf"])

    def test_first_source_url_skips_items_without_storage_fields(self):
        items = [
            {"ti_file_flag": "source", "ti_format": "pdf"}, # 没有 ti_storage / ti_storages
            {"ti_file_flag": "source", "ti_format": "pdf", "ti_storage": "https://example.com/a.pdf"},
        ]

        self.assertEqual(
            api.first_source_url(items, lambda item: item.get("ti_file_flag") == "source"),
            ("https://example.com/a.pdf", "pdf"),
        )

    def test_first_source_url_skips_folders(self):
        items = [{"ti_file_flag": "source", "ti_format": "folder", "ti_storage": "https://example.com/dir"}]

        self.assertEqual(api.first_source_url(items, lambda item: True), (None, "pdf"))
