"""检查脚本的换行格式，避免 Windows 编辑引入 CRLF 后中断实时流水线。"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ShellLineEndingTests(unittest.TestCase):
    def test_shell_scripts_use_lf(self):
        """列出含回车字节的脚本，让故障在执行 Bash 前就能被定位。"""
        invalid = [
            path.name
            for path in sorted((ROOT / "scripts").glob("*.sh"))
            if b"\r" in path.read_bytes()
        ]
        self.assertFalse(invalid, "以下脚本含 CR/CRLF：" + ", ".join(invalid))
