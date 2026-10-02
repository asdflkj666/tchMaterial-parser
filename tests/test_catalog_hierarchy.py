import unittest

from src.tchmaterial_parser.catalog import descend_hierarchy


def make_tree() -> dict:
    return {
        "display_name": "教材",
        "children": {
            "xiaoxue": {
                "display_name": "小学",
                "children": {
                    "yuwen": {
                        "display_name": "语文",
                        "children": {},
                    },
                },
            },
        },
    }


class DescendHierarchyTest(unittest.TestCase):
    def test_walks_down_in_order(self) -> None:
        node = descend_hierarchy(make_tree(), ["xiaoxue", "yuwen"])

        self.assertEqual(node["display_name"], "语文")

    def test_stops_at_last_reachable_level(self) -> None:
        # 末级还没有子节点，下钻到“语文”即停止
        node = descend_hierarchy(make_tree(), ["xiaoxue", "yuwen", "unknown"])

        self.assertEqual(node["display_name"], "语文")

    def test_returns_root_when_path_does_not_match(self) -> None:
        node = descend_hierarchy(make_tree(), ["unknown"])

        self.assertEqual(node["display_name"], "教材")

    def test_tolerates_out_of_order_ids(self) -> None:
        # 平台给出的 tag_paths 与树中顺序不一致时，仍应能逐级下钻
        node = descend_hierarchy(make_tree(), ["yuwen", "xiaoxue"])

        self.assertEqual(node["display_name"], "语文")


if __name__ == "__main__":
    unittest.main()
