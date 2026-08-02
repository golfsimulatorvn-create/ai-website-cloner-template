"""Test nạp và kiểm tra config.

Sai config phải nổ ngay lúc khởi động. Một order_by gõ nhầm mà bị im lặng bỏ qua
sẽ khiến agent chọn sai bản tài liệu suốt nhiều tháng mà không ai biết.
"""

import tempfile
import unittest
from pathlib import Path

from src.core.config import FolderConfig, load_doctype_rules


def write_yaml(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


class TestLoadDocTypeRules(unittest.TestCase):
    def test_loads_shipped_config(self):
        rules = load_doctype_rules()
        self.assertTrue(any(r.doc_type == "bang_gia" for r in rules))

    def test_rejects_invalid_order_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(Path(tmp), "doctypes.yaml", """
rules:
  - doc_type: bang_gia
    name_matches: ["bang gia"]
    order_by: [periode, version]
""")
            with self.assertRaises(ValueError) as ctx:
                load_doctype_rules(path)
            self.assertIn("periode", str(ctx.exception))

    def test_rejects_duplicate_doc_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(Path(tmp), "doctypes.yaml", """
rules:
  - doc_type: bang_gia
    name_matches: ["bang gia"]
  - doc_type: bang_gia
    name_matches: ["price list"]
""")
            with self.assertRaises(ValueError) as ctx:
                load_doctype_rules(path)
            self.assertIn("trùng", str(ctx.exception))

    def test_rejects_rule_without_doc_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(Path(tmp), "doctypes.yaml", """
rules:
  - name_matches: ["bang gia"]
""")
            with self.assertRaises(ValueError):
                load_doctype_rules(path)

    def test_rejects_empty_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(Path(tmp), "doctypes.yaml", "rules: []\n")
            with self.assertRaises(ValueError):
                load_doctype_rules(path)

    def test_defaults_order_when_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(Path(tmp), "doctypes.yaml", """
rules:
  - doc_type: bang_gia
    name_matches: ["bang gia"]
""")
            self.assertEqual(load_doctype_rules(path)[0].order_by,
                             ("version", "period", "modified"))


class TestFolderConfig(unittest.TestCase):
    VALID = """
read_roots:
  - id: "1AbC"
    label: "Kinh doanh"
write_root:
  id: "1Out"
  path: "/HOA HUY GREEN/Agent Output"
recipient_allowlist:
  - "@hoahuy.com"
"""

    def test_loads_valid_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = FolderConfig.load(write_yaml(Path(tmp), "folders.yaml", self.VALID))
        self.assertEqual(cfg.read_roots, ["1AbC"])
        self.assertEqual(cfg.write_root_path, "/HOA HUY GREEN/Agent Output")
        self.assertEqual(cfg.recipient_allowlist, ["@hoahuy.com"])

    def test_rejects_missing_read_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(Path(tmp), "folders.yaml",
                              'write_root:\n  path: "/Out"\n')
            with self.assertRaises(ValueError) as ctx:
                FolderConfig.load(path)
            self.assertIn("read_roots", str(ctx.exception))

    def test_rejects_missing_write_root(self):
        """Không khai báo phạm vi ghi thì mọi thao tác ghi phải bị chặn,
        chứ không phải được ghi tự do."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_yaml(Path(tmp), "folders.yaml",
                              'read_roots:\n  - id: "1AbC"\n')
            with self.assertRaises(ValueError) as ctx:
                FolderConfig.load(path)
            self.assertIn("write_root", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
