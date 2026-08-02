"""Test luật đọc số bản và kỳ áp dụng từ tên file.

Đây là bộ test quan trọng nhất trong dự án: nếu logic này sai, agent sẽ trích
dẫn nhầm bảng giá cũ vào báo giá gửi khách mà không có dấu hiệu gì bất thường.
"""

import unittest

from src.core.version import parse_period, parse_version, strip_extension


class TestStripExtension(unittest.TestCase):
    def test_removes_common_extensions(self):
        self.assertEqual(strip_extension("Bảng giá.xlsx"), "Bảng giá")
        self.assertEqual(strip_extension("Công văn.docx"), "Công văn")
        self.assertEqual(strip_extension("Hồ sơ.pdf"), "Hồ sơ")

    def test_keeps_name_without_extension(self):
        self.assertEqual(strip_extension("Bảng giá v3.2"), "Bảng giá v3.2")


class TestParseVersion(unittest.TestCase):
    def test_major_and_minor(self):
        v = parse_version("Bảng giá pin LiFePO4 v3.2 - 2026-07.xlsx")
        self.assertEqual((v.major, v.minor), (3, 2))

    def test_major_only(self):
        v = parse_version("Bảng giá v3.xlsx")
        self.assertEqual((v.major, v.minor), (3, None))

    def test_vietnamese_prefix(self):
        v = parse_version("Quy trình ISO phiên bản 2.1.docx")
        self.assertEqual((v.major, v.minor), (2, 1))

    def test_uppercase_and_spacing(self):
        self.assertEqual(parse_version("Mẫu công văn V 4.docx").major, 4)
        self.assertEqual(parse_version("Mau_cong_van_ver2.docx").major, 2)

    def test_no_version_when_absent(self):
        self.assertFalse(parse_version("Bảng giá mới nhất.xlsx").known)
        self.assertFalse(parse_version("Bảng giá 2026-07.xlsx").known)

    def test_bare_numbers_are_not_versions(self):
        """Con số trần trong tên file gần như luôn là ngày tháng hoặc công suất.

        Đoán bừa ở đây là nguồn sai lệch âm thầm nguy hiểm nhất — "hệ 5kWp"
        không được hiểu thành bản 5.
        """
        self.assertFalse(parse_version("Báo giá hệ 5kWp cho khách Minh.docx").known)
        self.assertFalse(parse_version("Hợp đồng 28-07-2026.pdf").known)
        self.assertFalse(parse_version("Bảng giá 2026.xlsx").known)

    def test_last_version_wins(self):
        v = parse_version("Mau v1 - cap nhat tu ban v2.docx")
        self.assertEqual(v.major, 2)

    def test_str_representation(self):
        self.assertEqual(str(parse_version("Mẫu v4.2.docx")), "v4.2")
        self.assertEqual(str(parse_version("Mẫu v4.docx")), "v4")
        self.assertEqual(str(parse_version("Mẫu.docx")), "—")

    def test_ordering(self):
        older = parse_version("Mau v3.1.docx").sort_key()
        newer = parse_version("Mau v3.2.docx").sort_key()
        none_ = parse_version("Mau.docx").sort_key()
        self.assertLess(older, newer)
        self.assertLess(none_, older)  # không có bản xếp dưới mọi bản có thật


class TestParsePeriod(unittest.TestCase):
    def test_iso_year_month_day(self):
        p = parse_period("Bảng giá 2026-07-28.xlsx")
        self.assertEqual((p.year, p.month), (2026, 7))

    def test_iso_year_month(self):
        p = parse_period("Bảng giá 2026-07.xlsx")
        self.assertEqual((p.year, p.month), (2026, 7))

    def test_vietnamese_day_month_year(self):
        p = parse_period("Hợp đồng 28-07-2026.pdf")
        self.assertEqual((p.year, p.month), (2026, 7))

    def test_month_year(self):
        p = parse_period("Bảng giá 07-2026.xlsx")
        self.assertEqual((p.year, p.month), (2026, 7))

    def test_t_prefix(self):
        for name in ("Báo cáo T7/2026.docx", "Báo cáo T7.2026.docx",
                     "Báo cáo tháng 7 2026.docx"):
            with self.subTest(name=name):
                p = parse_period(name)
                self.assertEqual((p.year, p.month), (2026, 7))

    def test_year_only(self):
        p = parse_period("Bảng giá 2026.xlsx")
        self.assertEqual((p.year, p.month), (2026, None))

    def test_no_period(self):
        self.assertFalse(parse_period("Bảng giá mới nhất.xlsx").known)

    def test_version_is_not_mistaken_for_period(self):
        """'v3.2 - 2026' phải ra kỳ 2026, không phải tháng 3 năm 2026."""
        p = parse_period("Bảng giá v3.2 - 2026.xlsx")
        self.assertEqual((p.year, p.month), (2026, None))

    def test_invalid_month_falls_through(self):
        """'15-20-2026' không có tháng hợp lệ — phải lùi về chỉ nhận năm."""
        p = parse_period("Ho so 15-20-2026.pdf")
        self.assertEqual((p.year, p.month), (2026, None))

    def test_ordering(self):
        self.assertLess(
            parse_period("Bang gia 2026-06.xlsx").sort_key(),
            parse_period("Bang gia 2026-07.xlsx").sort_key(),
        )
        self.assertLess(
            parse_period("Bang gia 2025-12.xlsx").sort_key(),
            parse_period("Bang gia 2026-01.xlsx").sort_key(),
        )
        self.assertLess(
            parse_period("Bang gia.xlsx").sort_key(),
            parse_period("Bang gia 2020.xlsx").sort_key(),
        )

    def test_str_representation(self):
        self.assertEqual(str(parse_period("Bang gia 2026-07.xlsx")), "2026-07")
        self.assertEqual(str(parse_period("Bang gia 2026.xlsx")), "2026")
        self.assertEqual(str(parse_period("Bang gia.xlsx")), "—")


if __name__ == "__main__":
    unittest.main()
