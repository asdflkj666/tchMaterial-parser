# -*- coding: utf-8 -*-
# 获取平台上的资源目录树，并提供按分类路径筛选与计数的辅助函数

from .network import session

def descend_hierarchy(hier: dict, tag_paths: list[str]) -> dict: # 按分类 id 顺序在层级树里逐级下钻
    """平台给出的 tag_paths 与树中的排列顺序不一定一致，因此每一层都从头尝试所有 id，
    命中就进入下一层；无法继续下钻时返回当前所在的层级。"""
    for tag_id in tag_paths:
        children = hier.get("children")
        if children and children.get(tag_id):
            return descend_hierarchy(children[tag_id], tag_paths)
    return hier

class ResourceHelper: # 获取网站上资源的数据
    def parse_hierarchy(self, hierarchy: list) -> dict: # 解析层级数据
        if not hierarchy: # 如果没有层级数据，返回空字典
            return {}

        parsed = {}
        for h in hierarchy:
            for ch in h["children"]:
                parsed[ch["tag_id"]] = { "display_name": ch["tag_name"], "children": self.parse_hierarchy(ch["hierarchies"]) }
        return parsed

    def fetch_book_list(self) -> dict: # 获取课本列表
        # 获取电子课本层级数据
        tags_resp = session.get("https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/tags/tch_material_tag.json")
        tags_data: dict = tags_resp.json()
        parsed_hier = self.parse_hierarchy(tags_data["hierarchies"])

        # 获取电子课本 URL 列表
        list_resp = session.get("https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/version/data_version.json")
        list_data: list[str] = list_resp.json()["urls"].split(",")

        # 获取电子课本列表
        for url in list_data:
            book_resp = session.get(url)
            book_data: list[dict] = book_resp.json()
            for book in book_data:
                if book.get("tag_paths"): # 某些非课本资料的 tag_paths 属性为空数组
                    # 解析课本层级数据
                    tag_paths: list[str] = book["tag_paths"][0].split("/")

                    # 分别解析课本层级；平台偶尔会给出分类树里没有的 tag，
                    # 直接索引会抛 KeyError 并导致整份课本列表加载失败，因此跳过这类记录
                    if len(tag_paths) < 2 or tag_paths[1] not in parsed_hier:
                        continue
                    temp_hier = parsed_hier[tag_paths[1]]

                    for p in tag_paths[2:]: # 电子课本 tag_paths 的前两项为 “教材”、“电子教材”
                        if temp_hier.get("children") and temp_hier["children"].get(p):
                            temp_hier = temp_hier["children"][p]
                    if not temp_hier.get("children"):
                        temp_hier["children"] = {}

                    book["display_name"] = book.get("title") or book.get("name") or f"(未知电子课本 {book['id']})"

                    temp_hier["children"][book["id"]] = book

        return parsed_hier

    def fetch_national_lesson_list(self) -> dict: # 获取自学课件列表
        return self._fetch_lesson_list(
            tags_url="https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/tags/national_lesson_tag.json",
            list_url="https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/national_lesson/teachingmaterials/version/data_version.json",
            internal_tag_id="__internal_national_lesson",
            group_name="学生自主学习课件",
        )

    def fetch_prepare_lesson_list(self) -> dict: # 获取备课课件列表
        return self._fetch_lesson_list(
            tags_url="https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/tags/k12.json",
            list_url="https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/prepare_lesson/teachingmaterials/parts.json",
            internal_tag_id="__internal_prepare_lesson",
            group_name="教师备课授课课件",
        )

    def _fetch_lesson_list(self, tags_url: str, list_url: str, internal_tag_id: str, group_name: str) -> dict: # 拉取某类课件并挂到分类树上
        # 自学课件与备课课件的流程完全一致，只是数据源不同，因此共用这一份实现
        tags_data: dict = session.get(tags_url).json()
        parsed_hier = self.parse_hierarchy([{ "children": [{ "tag_id": internal_tag_id, "hierarchies": tags_data["hierarchies"], "tag_name": group_name }] }])

        list_data = session.get(list_url).json()
        if isinstance(list_data, dict): # 自学课件的接口把分片地址放在 urls 字段里
            list_data = list_data["urls"]

        for url in list_data:
            lesson_data: list[dict] = session.get(url).json()
            for lesson in lesson_data:
                if not lesson.get("tag_list"):
                    continue

                # tag_paths 是乱序的，按 order_num 还原顺序后再下钻层级
                tag_paths: list[str] = [tag["tag_id"] for tag in sorted(lesson["tag_list"], key=lambda tag: tag["order_num"])]
                hier = descend_hierarchy(parsed_hier[internal_tag_id], tag_paths)
                if not hier.get("children"):
                    hier["children"] = {}

                lesson["display_name"] = lesson.get("title") or lesson.get("name") or f"(未知课件 {lesson['id']})"

                hier["children"][lesson["id"]] = lesson

        return parsed_hier

    def fetch_resource_list(self) -> dict: # 获取资源列表
        book_hier = self.fetch_book_list()
        # national_lesson_hier = self.fetch_national_lesson_list()
        # prepare_lesson_hier = self.fetch_prepare_lesson_list()
        return { **book_hier }

def filter_resource_items(items: dict[str, dict], query: str) -> dict[str, dict]: # 按完整分类路径筛选资源树
    keywords = query.casefold().split()
    if not keywords:
        return items

    def filter_branch(branch: dict[str, dict], parent_names: tuple[str, ...]) -> dict[str, dict]:
        matches: dict[str, dict] = {}
        for option_id, option_data in branch.items():
            path_names = (*parent_names, option_data["display_name"])
            children = option_data.get("children", {})
            if children:
                filtered_children = filter_branch(children, path_names)
                if filtered_children:
                    matches[option_id] = { **option_data, "children": filtered_children }
            elif all(keyword in " ".join(path_names).casefold() for keyword in keywords):
                matches[option_id] = option_data
        return matches

    return filter_branch(items, ())

def count_resource_items(items: dict[str, dict]) -> int: # 统计资源树中的末级资源数量
    return sum(
        count_resource_items(children) if (children := option_data.get("children", {})) else 1
        for option_data in items.values()
    )
