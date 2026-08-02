"""Test bóc tách câu hỏi bằng luật (S1 rút gọn)."""

import unittest

from src.core.config import load_doctype_rules
from src.core.intake import derive_keywords, guess_doc_type, parse, wants_latest


class TestDeriveKeywords(unittest.TestCase):
    def test_strips_stopwords(self):
        keywords = derive_keywords("Cho tôi xem bảng giá pin")
        self.assertIn("bang", keywords)
        self.assertIn("gia", keywords)
        self.assertIn("pin", keywords)
        self.assertNotIn("cho", keywords)
        self.assertNotIn("toi", keywords)

    def test_removes_latest_hints(self):
        """'mới nhất' không bao giờ có trong tên file — giữ lại chỉ làm trượt hết."""
        self.assertNotIn("moi", derive_keywords("bảng giá pin mới nhất"))
        self.assertNotIn("nhat", derive_keywords("bảng giá pin mới nhất"))

    def test_keeps_alphanumeric_tokens(self):
        keywords = derive_keywords("Hồ sơ kỹ thuật dự án 5kwp Bình Dương")
        self.assertIn("5kwp", keywords)
        self.assertIn("duong", keywords)

    def test_normalizes_like_the_index(self):
        """Hai bên phải chuẩn hoá giống nhau, nếu không sẽ trượt hết."""
        self.assertEqual(derive_keywords("Bảng Giá"), derive_keywords("bang gia"))

    def test_deduplicates(self):
        self.assertEqual(derive_keywords("pin pin pin").count("pin"), 1)

    def test_respects_limit(self):
        question = "bảng giá pin inverter lifepo4 hybrid solar dự án bình dương"
        self.assertLessEqual(len(derive_keywords(question, max_keywords=3)), 3)

    def test_truncation_keeps_distinctive_tokens(self):
        """Cắt theo độ đặc trưng, không theo thứ tự xuất hiện.

        Câu hỏi tiếng Việt mở đầu bằng loại tài liệu và kết thúc bằng thứ thật
        sự phân biệt — cắt từ cuối lên sẽ giữ lại đúng phần vô dụng.
        """
        keywords = derive_keywords("hồ sơ kỹ thuật dự án 5kwp Bình Dương", max_keywords=3)
        self.assertIn("5kwp", keywords)
        self.assertNotIn("ho", keywords)

    def test_short_questions_keep_original_order(self):
        self.assertEqual(derive_keywords("bảng giá pin"), ["bang", "gia", "pin"])

    def test_empty_question(self):
        self.assertEqual(derive_keywords("cho tôi"), [])


class TestWantsLatest(unittest.TestCase):
    def test_detects_hints(self):
        for question in ("bảng giá mới nhất", "bản gần nhất", "giá hiện tại"):
            with self.subTest(question=question):
                self.assertTrue(wants_latest(question))

    def test_absent_when_not_asked(self):
        self.assertFalse(wants_latest("bảng giá tháng 6"))


class TestGuessDocType(unittest.TestCase):
    def setUp(self):
        self.rules = load_doctype_rules()

    def test_recognises_common_questions(self):
        cases = [
            ("bảng giá pin mới nhất", "bang_gia"),
            ("mẫu công văn hành chính", "mau_van_ban"),
            ("giấy chứng nhận đăng ký kinh doanh", "phap_ly"),
            ("hợp đồng thi công với khách", "hop_dong"),
            ("quy trình bảo trì hệ thống", "quy_trinh"),
        ]
        for question, expected in cases:
            with self.subTest(question=question):
                self.assertEqual(guess_doc_type(question, self.rules), expected)

    def test_returns_none_when_unclear(self):
        self.assertIsNone(guess_doc_type("cho tôi xem cái đó", self.rules))


class TestParse(unittest.TestCase):
    def setUp(self):
        self.rules = load_doctype_rules()

    def test_full_parse(self):
        intake = parse("Bảng giá pin LiFePO4 mới nhất", self.rules)
        self.assertEqual(intake.doc_type, "bang_gia")
        self.assertIn("lifepo4", intake.keywords)
        self.assertTrue(intake.explicit_latest)
        self.assertFalse(intake.is_empty)

    def test_explicit_latest_is_false_when_not_stated(self):
        self.assertFalse(parse("bảng giá tháng 6", self.rules).explicit_latest)

    def test_empty_intake_is_detected(self):
        self.assertTrue(parse("cho tôi", self.rules).is_empty)


if __name__ == "__main__":
    unittest.main()
