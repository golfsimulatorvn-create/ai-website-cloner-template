"""Test phân loại, tìm kiếm và chọn bản mới nhất trong chỉ mục."""

import unittest

from src.core.config import load_doctype_rules
from src.core.manifest import (
    DocTypeRule,
    FileEntry,
    Manifest,
    classify,
    normalize,
    resolve_latest,
)

RULES = [
    DocTypeRule(
        doc_type="bang_gia",
        path_contains=["bang gia"],
        name_matches=["bang ?gia"],
        order_by=("period", "version", "modified"),
    ),
    DocTypeRule(
        doc_type="mau_van_ban",
        path_contains=["mau"],
        name_matches=["^mau "],
        order_by=("version", "period", "modified"),
    ),
]


def entry(name, path="/Kinh doanh/Bang gia", modified="2026-01-01T00:00:00Z",
          doc_type="bang_gia", file_id=None):
    return FileEntry(
        id=file_id or name,
        name=name,
        path=path,
        modified_time=modified,
        doc_type=doc_type,
    )


class TestNormalize(unittest.TestCase):
    def test_strips_accents_and_lowercases(self):
        self.assertEqual(normalize("Bảng Giá"), "bang gia")
        self.assertEqual(normalize("Công văn Đi"), "cong van di")
        self.assertEqual(normalize("PHÒNG CHÁY"), "phong chay")


class TestClassify(unittest.TestCase):
    def test_matches_by_path_and_name(self):
        self.assertEqual(classify("/Kinh doanh/Bảng giá", "Bảng giá pin.xlsx", RULES),
                         "bang_gia")

    def test_unmatched_falls_back_to_khac(self):
        self.assertEqual(classify("/Linh tinh", "Ghi chú.docx", RULES), "khac")

    def test_requires_both_path_and_name_when_both_declared(self):
        # Tên khớp nhưng nằm sai thư mục → không nhận
        self.assertEqual(classify("/Nhân sự", "Bảng giá pin.xlsx", RULES), "khac")

    def test_first_matching_rule_wins(self):
        rules = [
            DocTypeRule(doc_type="cu_the", name_matches=["bang gia pin"]),
            DocTypeRule(doc_type="chung", name_matches=["bang gia"]),
        ]
        self.assertEqual(classify("/x", "Bảng giá pin.xlsx", rules), "cu_the")

    def test_empty_rule_never_matches_everything(self):
        self.assertEqual(classify("/bat ky", "bat ky.docx", [DocTypeRule(doc_type="rong")]),
                         "khac")


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.manifest = Manifest(
            [
                entry("Bảng giá pin LiFePO4 2026-07.xlsx"),
                entry("Bảng giá pin LiFePO4 2026-06.xlsx"),
                entry("Bảng giá inverter 2026-07.xlsx"),
                entry("Mẫu công văn v3.docx", path="/Hành chính/Mẫu",
                      doc_type="mau_van_ban"),
            ],
            rules=RULES,
        )

    def test_filters_by_doc_type(self):
        self.assertEqual(len(self.manifest.search(doc_type="bang_gia")), 3)

    def test_keywords_are_accent_insensitive(self):
        found = self.manifest.search(keywords=["bang gia", "inverter"])
        self.assertEqual([f.name for f in found], ["Bảng giá inverter 2026-07.xlsx"])

    def test_keywords_use_and_not_or(self):
        """AND giữ kết quả đủ hẹp để LLM chọn lọc hiệu quả; OR trả về quá nhiều nhiễu."""
        self.assertEqual(self.manifest.search(keywords=["inverter", "khong ton tai"]), [])

    def test_results_sorted_newest_first(self):
        found = self.manifest.search(doc_type="bang_gia", keywords=["lifepo4"])
        self.assertEqual(found[0].name, "Bảng giá pin LiFePO4 2026-07.xlsx")

    def test_limit(self):
        self.assertEqual(len(self.manifest.search(doc_type="bang_gia", limit=2)), 2)


class TestResolveLatest(unittest.TestCase):
    def test_picks_newest_period(self):
        result = resolve_latest(
            [entry("Bảng giá 2026-06.xlsx"), entry("Bảng giá 2026-07.xlsx")],
            order=("period", "version", "modified"),
        )
        self.assertFalse(result.needs_human)
        self.assertEqual(result.winner.name, "Bảng giá 2026-07.xlsx")

    def test_picks_newest_version_for_templates(self):
        result = resolve_latest(
            [entry("Mau cong van v3.1.docx"), entry("Mau cong van v3.2.docx")],
            order=("version", "period", "modified"),
        )
        self.assertEqual(result.winner.name, "Mau cong van v3.2.docx")

    def test_order_by_changes_the_answer(self):
        """Cùng dữ liệu, order_by khác nhau cho kết quả khác nhau — nên nó phải
        nằm trong config theo docType, không hardcode."""
        files = [
            entry("Bảng giá v3.2 - 2026-06.xlsx"),
            entry("Bảng giá v3.1 - 2026-07.xlsx"),
        ]
        by_period = resolve_latest(files, order=("period", "version", "modified"))
        by_version = resolve_latest(files, order=("version", "period", "modified"))
        self.assertEqual(by_period.winner.name, "Bảng giá v3.1 - 2026-07.xlsx")
        self.assertEqual(by_version.winner.name, "Bảng giá v3.2 - 2026-06.xlsx")

    def test_falls_back_to_modified_time(self):
        result = resolve_latest(
            [
                entry("Ghi chú họp.docx", modified="2026-05-01T00:00:00Z"),
                entry("Ghi chú họp (bản sao).docx", modified="2026-06-01T00:00:00Z"),
            ]
        )
        self.assertEqual(result.winner.name, "Ghi chú họp (bản sao).docx")

    def test_empty_input(self):
        result = resolve_latest([])
        self.assertIsNone(result.winner)
        self.assertFalse(result.needs_human)

    # ---- các trường hợp BẮT BUỘC hỏi người ----

    def test_exact_tie_is_a_conflict(self):
        """Hai file cùng kỳ, cùng bản, cùng giờ sửa — không có cơ sở để chọn."""
        result = resolve_latest(
            [
                entry("Bảng giá 2026-07.xlsx", file_id="a"),
                entry("Bảng giá pin 2026-07.xlsx", file_id="b"),
            ],
            order=("period", "version", "modified"),
        )
        self.assertTrue(result.needs_human)
        self.assertIsNone(result.winner)
        self.assertEqual({f.id for f in result.conflicts}, {"a", "b"})

    def test_undated_file_modified_later_is_a_conflict(self):
        """'Bảng giá v3.2' và 'Bảng giá mới nhất' sửa hôm qua — chọn bừa là sai.

        Đây là trường hợp thật hay gặp nhất và cũng là chỗ LLM luôn chọn bừa,
        vì nó không bao giờ trả lời 'không đủ cơ sở'.
        """
        result = resolve_latest(
            [
                entry("Bảng giá v3.2 - 2026-06.xlsx", modified="2026-06-01T00:00:00Z"),
                entry("Bảng giá mới nhất.xlsx", modified="2026-07-30T00:00:00Z"),
            ],
            order=("period", "version", "modified"),
        )
        self.assertTrue(result.needs_human)
        self.assertIn("sửa muộn hơn", result.reason)

    def test_undated_file_modified_earlier_is_not_a_conflict(self):
        result = resolve_latest(
            [
                entry("Bảng giá v3.2 - 2026-06.xlsx", modified="2026-06-01T00:00:00Z"),
                entry("Bảng giá cũ.xlsx", modified="2026-01-01T00:00:00Z"),
            ],
            order=("period", "version", "modified"),
        )
        self.assertFalse(result.needs_human)
        self.assertEqual(result.winner.name, "Bảng giá v3.2 - 2026-06.xlsx")


class TestManifestRoundTrip(unittest.TestCase):
    def test_save_and_load(self):
        import tempfile
        from pathlib import Path

        original = Manifest(
            [entry("Bảng giá 2026-07.xlsx")],
            generated_at="2026-08-01T00:00:00+00:00",
            rules=RULES,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            original.save(path)
            loaded = Manifest.load(path, rules=RULES)

        self.assertEqual(len(loaded.files), 1)
        self.assertEqual(loaded.files[0].name, "Bảng giá 2026-07.xlsx")
        self.assertEqual(loaded.files[0].period.month, 7)
        self.assertEqual(loaded.generated_at, "2026-08-01T00:00:00+00:00")

    def test_age_hours_infinite_when_missing_timestamp(self):
        self.assertEqual(Manifest([]).age_hours, float("inf"))


class TestShippedConfig(unittest.TestCase):
    """Config đi kèm phải nạp được và phân loại đúng các tên file thật.

    Test này bắt lỗi gõ nhầm trong doctypes.yaml trước khi nó âm thầm khiến
    mọi tài liệu rơi vào nhóm 'khac'.
    """

    def setUp(self):
        self.rules = load_doctype_rules()

    def test_config_loads(self):
        self.assertGreater(len(self.rules), 5)

    def test_real_world_names(self):
        cases = [
            ("/HOA HUY GREEN/Kinh doanh/Bảng giá", "Bảng giá pin LiFePO4 v3.2 - 2026-07.xlsx",
             "bang_gia"),
            ("/HOA HUY GREEN/Hành chính/Biểu mẫu", "Mẫu công văn hành chính v2.docx",
             "mau_van_ban"),
            ("/HOA HUY GREEN/Pháp lý/Giấy phép", "Giấy chứng nhận đăng ký kinh doanh 2024.pdf",
             "phap_ly"),
            ("/HOA HUY GREEN/Kinh doanh/Hợp đồng", "Hợp đồng thi công 28-07-2026.pdf",
             "hop_dong"),
        ]
        for path, name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(classify(path, name, self.rules), expected)

    def test_price_list_prefers_period_over_version(self):
        from src.core.manifest import order_for

        self.assertEqual(order_for("bang_gia", self.rules)[0], "period")
        self.assertEqual(order_for("mau_van_ban", self.rules)[0], "version")


if __name__ == "__main__":
    unittest.main()
