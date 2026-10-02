import unittest

from src.tchmaterial_parser.api import combine_resource_title, resolve_title


class ResolveTitleTest(unittest.TestCase):
    def test_reads_localized_title(self) -> None:
        self.assertEqual(resolve_title({"zh-CN": "语文", "en": "Chinese"}), "语文")

    def test_falls_back_to_english(self) -> None:
        self.assertEqual(resolve_title({"en": "Chinese"}), "Chinese")

    def test_falls_back_to_any_language_then_extra_fields(self) -> None:
        # 平台数据不保证有 zh-CN/en，字典里只有别的语言键时也要能取出标题
        self.assertEqual(resolve_title({"ja": "国語"}), "国語")
        self.assertEqual(resolve_title({}, "资源标题"), "资源标题")
        self.assertEqual(resolve_title(None, None, "abc-123"), "abc-123")

    def test_uses_plain_string_title(self) -> None:
        self.assertEqual(resolve_title("直接是字符串"), "直接是字符串")

    def test_returns_empty_string_when_nothing_usable(self) -> None:
        # 以前这里会返回 None，进而在拼接标题时抛 AttributeError，被吞成「无法解析」
        self.assertEqual(resolve_title(None), "")
        self.assertEqual(resolve_title({"zh-CN": "   "}), "")
        self.assertEqual(resolve_title({"en": None}, None, 123), "")


class CombineTitleTest(unittest.TestCase):
    def test_keeps_resource_title_when_no_root(self) -> None:
        self.assertEqual(combine_resource_title(None, "语文"), "语文")

    def test_falls_back_to_root_when_resource_title_empty(self) -> None:
        # 缺标题的子资源只保留专题标题，避免生成 “标题 - ”
        self.assertEqual(combine_resource_title("专题", ""), "专题")

    def test_joins_distinct_titles(self) -> None:
        self.assertEqual(combine_resource_title("专题", "子资源"), "专题 - 子资源")

    def test_collapses_duplicate_title(self) -> None:
        self.assertEqual(combine_resource_title("语文 上册", " 语文  上册 "), " 语文  上册 ")


if __name__ == "__main__":
    unittest.main()
