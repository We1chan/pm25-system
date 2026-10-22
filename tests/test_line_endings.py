"""验证系统的既有约定，使用测试样本或只读产物执行断言。
输入接口、特征或模型结果，输出可重复的自动化验证结论。"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ShellLineEndingTests(unittest.TestCase):
    def test_shell_scripts_use_lf(self):
        """验证shell scripts use lf 对应的约定。"""
        invalid = [
            path.name
            for path in sorted((ROOT / "scripts").glob("*.sh"))
            if b"\r" in path.read_bytes()
        ]
        self.assertFalse(invalid, "以下脚本含 CR/CRLF：" + ", ".join(invalid))
