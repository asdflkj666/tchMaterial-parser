import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.tchmaterial_parser import bookmarks


class AddBookmarksTest(unittest.TestCase):
    """回归 B4：写书签必须先落到 .bmk.tmp，成功后再替换回原文件。

    直接 open(pdf_path, "wb") 会先截断原文件，一旦中途失败（磁盘满、PDF 结构异常），
    留下的半截文件会被调用方当成「下载成功」的成品——文件在、大小像那么回事、日志说成功。
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.pdf_path = os.path.join(self.directory.name, "book.pdf")
        self.temp_path = f"{self.pdf_path}.bmk.tmp"
        with open(self.pdf_path, "wb") as file:
            file.write(b"original-pdf-bytes")

    def writer(self, write) -> Mock:
        writer = Mock()
        writer.pages = [object()]
        writer.add_outline_item.return_value = Mock()
        writer.write.side_effect = write
        return writer

    def read_pdf(self) -> bytes:
        with open(self.pdf_path, "rb") as file:
            return file.read()

    def test_write_failure_keeps_the_original_file_and_cleans_up(self) -> None:
        def failing_write(file):
            file.write(b"partial")  # 先写一点再失败，模拟磁盘写满
            raise OSError("disk full")

        with patch.object(bookmarks, "PdfReader"), \
             patch.object(bookmarks, "PdfWriter", return_value=self.writer(failing_write)), \
             patch.object(bookmarks, "print_error"):
            bookmarks.add_bookmarks(self.pdf_path, [{"title": "第一章", "page_index": 1}])

        self.assertEqual(self.read_pdf(), b"original-pdf-bytes")  # 原文件原样保留，未被截断
        self.assertFalse(os.path.exists(self.temp_path))  # 半成品被清掉

    def test_success_replaces_the_file_only_after_writing(self) -> None:
        def successful_write(file):
            file.write(b"with-bookmarks")

        with patch.object(bookmarks, "PdfReader"), \
             patch.object(bookmarks, "PdfWriter", return_value=self.writer(successful_write)):
            bookmarks.add_bookmarks(self.pdf_path, [{"title": "第一章", "page_index": 1}])

        self.assertEqual(self.read_pdf(), b"with-bookmarks")
        self.assertFalse(os.path.exists(self.temp_path))

    def test_no_chapters_leaves_the_file_untouched(self) -> None:
        with patch.object(bookmarks, "PdfReader"), \
             patch.object(bookmarks, "PdfWriter") as writer_class:
            bookmarks.add_bookmarks(self.pdf_path, [])

        writer_class.assert_not_called()
        self.assertEqual(self.read_pdf(), b"original-pdf-bytes")
        self.assertFalse(os.path.exists(self.temp_path))


if __name__ == "__main__":
    unittest.main()
