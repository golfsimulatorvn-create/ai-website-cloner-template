"""Test S0 — duyệt cây Drive và dựng chỉ mục, dùng Drive giả lập.

Không cần credential và không chạm mạng: build_manifest và walk_drive được tách
khỏi lớp gọi API chính là để kiểm thử được như thế này.
"""

import unittest

from src.core.manifest import DocTypeRule
from src.stages.s0_index import FOLDER_MIME, build_manifest, walk_drive

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

RULES = [
    DocTypeRule(doc_type="bang_gia", path_contains=["bang gia"], name_matches=["bang ?gia"]),
]


class FakeDrive:
    """Drive giả lập: ánh xạ folder_id → danh sách con."""

    def __init__(self, tree):
        self.tree = tree
        self.calls = []

    def list_children(self, folder_id):
        self.calls.append(folder_id)
        return list(self.tree.get(folder_id, []))


def folder(fid, name):
    return {"id": fid, "name": name, "mimeType": FOLDER_MIME}


def doc(fid, name, mime=XLSX, modified="2026-07-01T00:00:00Z"):
    return {"id": fid, "name": name, "mimeType": mime, "modifiedTime": modified,
            "size": "1024", "webViewLink": f"https://drive.google.com/file/d/{fid}"}


class TestWalkDrive(unittest.TestCase):
    def test_builds_full_paths(self):
        drive = FakeDrive({
            "root": [folder("f1", "Kinh doanh")],
            "f1": [folder("f2", "Bang gia")],
            "f2": [doc("d1", "Bang gia pin 2026-07.xlsx")],
        })
        files = walk_drive(drive, ["root"])
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["path"], "/Kinh doanh/Bang gia")

    def test_visits_each_folder_once(self):
        """Shortcut trỏ vòng là chuyện có thật trên Drive dùng chung —
        không chống vòng lặp thì việc quét không bao giờ kết thúc."""
        drive = FakeDrive({
            "root": [folder("f1", "A")],
            "f1": [folder("root", "Quay lại gốc"), doc("d1", "x.xlsx")],
        })
        files = walk_drive(drive, ["root"])
        self.assertEqual(len(files), 1)
        self.assertEqual(drive.calls.count("root"), 1)

    def test_respects_max_files(self):
        drive = FakeDrive({"root": [doc(f"d{i}", f"file{i}.xlsx") for i in range(50)]})
        self.assertEqual(len(walk_drive(drive, ["root"], max_files=10)), 10)

    def test_multiple_roots(self):
        drive = FakeDrive({
            "r1": [doc("d1", "a.xlsx")],
            "r2": [doc("d2", "b.xlsx")],
        })
        self.assertEqual(len(walk_drive(drive, ["r1", "r2"])), 2)

    def test_files_at_root_get_placeholder_path(self):
        drive = FakeDrive({"root": [doc("d1", "a.xlsx")]})
        self.assertEqual(walk_drive(drive, ["root"])[0]["path"], "/")


class TestBuildManifest(unittest.TestCase):
    def test_classifies_entries(self):
        raw = [{"id": "d1", "name": "Bảng giá pin 2026-07.xlsx", "path": "/Kinh doanh/Bang gia",
                "mimeType": XLSX, "modifiedTime": "2026-07-01T00:00:00Z"}]
        manifest = build_manifest(raw, RULES)
        self.assertEqual(manifest.files[0].doc_type, "bang_gia")
        self.assertEqual(manifest.files[0].period.month, 7)

    def test_skips_folders(self):
        raw = [{"id": "f1", "name": "Thư mục", "path": "/", "mimeType": FOLDER_MIME}]
        self.assertEqual(build_manifest(raw, RULES).files, [])

    def test_skips_non_indexable_media(self):
        """Ảnh và video vào chỉ mục chỉ làm nhiễu kết quả tìm kiếm —
        chúng không bao giờ dùng làm nguồn trích dẫn."""
        raw = [
            {"id": "i1", "name": "anh cong trinh.jpg", "path": "/", "mimeType": "image/jpeg"},
            {"id": "v1", "name": "video.mp4", "path": "/", "mimeType": "video/mp4"},
            {"id": "d1", "name": "Bao cao.docx", "path": "/", "mimeType": DOCX},
        ]
        manifest = build_manifest(raw, RULES)
        self.assertEqual([f.name for f in manifest.files], ["Bao cao.docx"])

    def test_records_generation_time(self):
        manifest = build_manifest([], RULES)
        self.assertTrue(manifest.generated_at)
        self.assertLess(manifest.age_hours, 1)

    def test_stale_flag_is_preserved(self):
        """Chỉ mục dựng từ cache phải mang cờ stale để cảnh báo được cho người dùng."""
        self.assertTrue(build_manifest([], RULES, stale=True).stale)

    def test_handles_missing_size(self):
        raw = [{"id": "d1", "name": "a.docx", "path": "/", "mimeType": DOCX}]
        self.assertEqual(build_manifest(raw, RULES).files[0].size_bytes, 0)


class TestEndToEndIndexing(unittest.TestCase):
    def test_scan_then_resolve_latest(self):
        """Đường đi đầy đủ: quét Drive giả → dựng chỉ mục → hỏi 'bản mới nhất'."""
        drive = FakeDrive({
            "root": [folder("f1", "Bang gia")],
            "f1": [
                doc("d1", "Bảng giá pin 2026-06.xlsx", modified="2026-06-01T00:00:00Z"),
                doc("d2", "Bảng giá pin 2026-07.xlsx", modified="2026-07-01T00:00:00Z"),
                doc("d3", "Bảng giá inverter 2026-07.xlsx", modified="2026-07-01T00:00:00Z"),
            ],
        })
        rules = [DocTypeRule(doc_type="bang_gia", path_contains=["bang gia"],
                             name_matches=["bang ?gia"],
                             order_by=("period", "version", "modified"))]
        manifest = build_manifest(walk_drive(drive, ["root"]), rules)

        result = manifest.resolve_latest(doc_type="bang_gia", keywords=["pin"])
        self.assertFalse(result.needs_human)
        self.assertEqual(result.winner.id, "d2")


if __name__ == "__main__":
    unittest.main()
