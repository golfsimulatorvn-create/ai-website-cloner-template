"""Test bản demo.

Demo là thứ người mới chạm vào đầu tiên. Nếu nó hỏng thì ấn tượng đầu tiên là
một stack trace — nên nó cần test như mọi phần khác, và nhất là ba tình huống
mà hướng dẫn chạy thử hứa là sẽ thấy.
"""

import contextlib
import io
import unittest

from src.demo import CONTENTS, DRIVE_TREE, DemoDownloader, build_demo_manifest, main
from src.main import run_lookup


class TestDemoData(unittest.TestCase):
    def test_every_document_has_content(self):
        """Thiếu nội dung cho một file là lỗi KeyError giữa lúc đang demo."""
        ids = {f["id"] for children in DRIVE_TREE.values() for f in children
               if f["mimeType"] != "application/vnd.google-apps.folder"}
        self.assertEqual(ids - set(CONTENTS), set())

    def test_manifest_classifies_everything(self):
        manifest = build_demo_manifest()
        unclassified = [f.name for f in manifest.files if f.doc_type == "khac"]
        self.assertEqual(unclassified, [])

    def test_manifest_is_not_stale(self):
        """Demo không được hiện cảnh báo 'chỉ mục đã cũ' — gây hiểu nhầm."""
        self.assertFalse(build_demo_manifest().stale)


class TestDemoScenarios(unittest.TestCase):
    """Ba tình huống mà HUONG-DAN-CHAY-THU.md hứa người dùng sẽ thấy."""

    def setUp(self):
        self.manifest = build_demo_manifest()
        self.downloader = DemoDownloader()

    def test_template_returns_v3_not_v2(self):
        code, output = run_lookup("mẫu công văn hành chính", self.manifest, self.downloader)
        self.assertEqual(code, 0)
        self.assertIn("v3", output)
        self.assertNotIn("bản v2", output)

    def test_solar_panel_price_list_is_a_conflict(self):
        code, output = run_lookup("bảng giá tấm pin", self.manifest, self.downloader)
        self.assertEqual(code, 3)
        self.assertIn("bản nào?", output)

    def test_pccc_document_is_flagged_but_still_answered(self):
        code, output = run_lookup("giấy phép PCCC", self.manifest, self.downloader)
        self.assertEqual(code, 0)
        self.assertIn("chỉ dẫn lạ", output)
        self.assertIn("1234/PCCC", output)

    def test_unknown_document_reports_not_found(self):
        code, _ = run_lookup("bảng giá ắc quy chì", self.manifest, self.downloader)
        self.assertEqual(code, 4)


class TestDemoCli(unittest.TestCase):
    """Chạy CLI thật nhưng nuốt đầu ra, để kết quả test không lẫn với demo."""

    @staticmethod
    def _run(argv) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_list_mode_shows_catalog(self):
        code, output = self._run(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("bang_gia", output)

    def test_single_question_mode(self):
        code, output = self._run(["bảng giá inverter"])
        self.assertEqual(code, 0)
        self.assertIn("18.500.000", output)

    def test_all_mode_covers_every_exit_code(self):
        """Bộ câu gợi ý phải chạm được cả bốn kiểu kết quả — đó là điểm của nó."""
        _, output = self._run(["--all"])
        for code in (0, 3, 4):
            self.assertIn(f"mã thoát {code}", output)


if __name__ == "__main__":
    unittest.main()
