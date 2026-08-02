"""CLI của trợ lý điều hành.

    python -m src.main index                       # S0: quét Drive dựng chỉ mục
    python -m src.main lookup "bảng giá pin mới nhất"   # S1→S5: tra cứu

Luồng LOOKUP chạy trọn vẹn mà không cần LLM. Nó cũng là mốc đối chứng: trước khi
thêm model vào bất kỳ bước nào, hãy đo xem bản thuần luật này trả lời đúng bao
nhiêu phần trăm câu hỏi thật. Model chỉ đáng thêm vào chỗ nó thắng được con số đó.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .core.config import FolderConfig, load_doctype_rules
from .core.intake import parse as parse_question
from .core.manifest import Manifest
from .stages.s4_retrieve import DocNeed, format_conflicts, format_not_found, retrieve
from .tools.extract import GoogleDriveDownloader, TextCache

DEFAULT_MANIFEST = "state/manifest.json"


def cmd_index(args: argparse.Namespace) -> int:
    from .stages.s0_index import main as index_main

    return index_main(["--out", args.manifest] + (["--credentials", args.credentials]
                                                  if args.credentials else []))


def run_lookup(question: str, manifest: Manifest, downloader, cache=None,
               max_docs: int = 1) -> tuple[int, str]:
    """Luồng LOOKUP thuần tuý: câu hỏi vào, (mã thoát, câu trả lời) ra.

    Tách khỏi phần nối dây Drive để kiểm thử được đầu-cuối bằng Drive giả lập.
    Mã thoát mang ý nghĩa riêng, không gộp chung thành "lỗi":
      0 = trả lời được   2 = câu hỏi không dùng được
      3 = xung đột, cần người chọn   4 = không tìm thấy
    """
    rules = manifest.rules or load_doctype_rules()
    intake = parse_question(question, rules)
    if intake.is_empty:
        return 2, "✖ Không rút được từ khoá nào từ câu hỏi. Hãy nêu rõ tên tài liệu cần tìm."

    need = DocNeed(
        label=intake.doc_type or "Tài liệu liên quan",
        doc_type=intake.doc_type,
        keywords=intake.keywords,
        must_have=True,
        max_docs=max_docs,
    )
    evidence, report = retrieve(manifest, [need], downloader, cache=cache)

    if report.needs_human:
        return 3, format_conflicts(report)
    if not report.can_proceed:
        return 4, format_not_found(report)

    lines = [f"Từ khoá: {', '.join(intake.keywords)}"
             + (f"  ·  loại: {intake.doc_type}" if intake.doc_type else "")]
    if report.stale:
        lines.append("⚠️ Chỉ mục đã cũ — nên chạy lại `index` để chắc chắn.")
    lines.append("")

    for item in evidence:
        lines.append(f"📄 {item.describe()}")
        lines.append(f"   {item.drive_url or '(không có link)'}")
        lines += [f"   ⚠️ {w}" for w in item.warnings]
        for excerpt in item.excerpts:
            lines.append(f"   … {' '.join(excerpt.split())[:400]}")
        lines.append("")

    return 0, "\n".join(lines)


def cmd_lookup(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"✖ Chưa có chỉ mục tại {manifest_path}. Chạy trước: python -m src.main index",
              file=sys.stderr)
        return 2

    credentials = args.credentials or os.environ.get("GOOGLE_SA_READ_JSON")
    if not credentials:
        print("✖ Thiếu credential đọc Drive (GOOGLE_SA_READ_JSON).", file=sys.stderr)
        return 2

    manifest = Manifest.load(manifest_path, rules=load_doctype_rules())
    code, output = run_lookup(
        question=args.question,
        manifest=manifest,
        downloader=GoogleDriveDownloader(credentials),
        cache=TextCache(args.cache),
        max_docs=args.max_docs,
    )
    print(output, file=sys.stderr if code == 2 else sys.stdout)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tro-ly-dieu-hanh",
                                     description="Trợ lý điều hành Hoa Huy")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--credentials", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    index = sub.add_parser("index", help="Quét Drive và dựng chỉ mục (S0)")
    index.set_defaults(func=cmd_index)

    lookup = sub.add_parser("lookup", help="Tra cứu tài liệu (S1→S5)")
    lookup.add_argument("question")
    lookup.add_argument("--max-docs", type=int, default=1)
    lookup.add_argument("--cache", default="state/cache")
    lookup.set_defaults(func=cmd_lookup)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Cấu hình phải hợp lệ trước khi làm bất cứ việc gì — sai config phải nổ
    # lúc khởi động, không phải giữa chừng.
    if args.command == "index":
        FolderConfig.load()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
