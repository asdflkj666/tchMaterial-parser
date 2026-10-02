import platform
import unittest

from src.tchmaterial_parser import platform_utils


class PlatformUtilsTest(unittest.TestCase):
    def test_stdlib_modules_survive_missing_pywin32(self) -> None:
        """pywin32 缺失不应连累标准库。

        winreg 用于配置读写、ctypes 用于高 DPI 适配，二者都是标准库，
        以前和 win32* 放在同一个 try 里，一旦 pywin32 装不上就会被一起置空，
        导致配置静默读不到（用户会以为 Token 丢了）。
        """
        if platform.system() != "Windows":
            self.skipTest("仅在 Windows 上检查")

        self.assertIsNotNone(platform_utils.winreg)
        self.assertIsNotNone(platform_utils.ctypes)


if __name__ == "__main__":
    unittest.main()
