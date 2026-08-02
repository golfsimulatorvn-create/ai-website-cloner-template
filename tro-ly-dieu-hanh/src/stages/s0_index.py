"""S0 — quét Drive và dựng manifest.json.

Tách làm hai phần có chủ đích:

  build_manifest()  — thuần tuý, nhận metadata thô, không chạm mạng, test được
  GoogleDriveLister — lớp mỏng bọc Drive API, phần duy nhất cần credential

Nhờ tách vậy mà toàn bộ luật phân loại và sắp xếp kiểm thử được bằng dữ liệu giả,
không cần Drive thật và không cần mock nặng nề.

Chạy:  python -m src.stages.s0_index --out state/manifest.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from ..core.config import FolderConfig, load_doctype_rules
from ..core.manifest import DocTypeRule, FileEntry, Manifest, classify

# Thư mục Drive: dùng để duyệt cây, không đưa vào chỉ mục
FOLDER_MIME = "application/vnd.google-apps.folder"

# Chỉ lập chỉ mục những định dạng ta trích được text. Ảnh và video vào chỉ mục
# chỉ làm nhiễu kết quả tìm kiếm mà không bao giờ dùng làm nguồn trích dẫn.
INDEXABLE_MIMES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",
    "application/vnd.ms-excel",
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
}


class DriveLister(Protocol):
    """Giao diện tối thiểu mà S0 cần từ Drive.

    Chỉ có phép đọc — không có phương thức nào ghi hay xoá, nên nhánh lập chỉ mục
    không thể sửa dữ liệu kể cả khi có lỗi lập trình.
    """

    def list_children(self, folder_id: str) -> Iterable[dict[str, Any]]:
        ...


def build_manifest(
    raw_files: Sequence[dict[str, Any]],
    rules: Sequence[DocTypeRule],
    generated_at: str | None = None,
    stale: bool = False,
) -> Manifest:
    """Dựng chỉ mục từ metadata thô. Thuần tuý, không I/O."""
    entries: list[FileEntry] = []
    for raw in raw_files:
        mime = raw.get("mimeType", "")
        if mime == FOLDER_MIME or (INDEXABLE_MIMES and mime not in INDEXABLE_MIMES):
            continue
        path = raw.get("path", "")
        name = raw.get("name", "")
        entries.append(
            FileEntry(
                id=raw.get("id", ""),
                name=name,
                path=path,
                mime=mime,
                modified_time=raw.get("modifiedTime", ""),
                doc_type=classify(path, name, rules),
                size_bytes=int(raw.get("size") or 0),
                web_url=raw.get("webViewLink", ""),
            )
        )

    stamp = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return Manifest(entries, generated_at=stamp, stale=stale, rules=rules)


def walk_drive(lister: DriveLister, root_ids: Sequence[str],
               max_files: int = 5000) -> list[dict[str, Any]]:
    """Duyệt cây thư mục theo chiều rộng, gắn đường dẫn đầy đủ cho từng file.

    `max_files` là trần cứng: một shortcut trỏ vòng hoặc một thư mục chia sẻ khổng
    lồ có thể biến việc quét thành vòng lặp vô tận. Đã thăm thư mục nào thì không
    thăm lại.
    """
    collected: list[dict[str, Any]] = []
    visited: set[str] = set()
    queue: list[tuple[str, str]] = [(fid, "") for fid in root_ids]

    while queue:
        folder_id, prefix = queue.pop(0)
        if folder_id in visited:
            continue
        visited.add(folder_id)

        for child in lister.list_children(folder_id):
            name = child.get("name", "")
            if child.get("mimeType") == FOLDER_MIME:
                queue.append((child["id"], f"{prefix}/{name}"))
                continue
            collected.append({**child, "path": prefix or "/"})
            if len(collected) >= max_files:
                print(f"⚠️  Đã chạm trần {max_files} file — dừng quét.", file=sys.stderr)
                return collected

    return collected


class GoogleDriveLister:
    """Bọc Drive API bằng service account CHỈ ĐỌC.

    Import googleapiclient nằm trong hàm khởi tạo để phần logic thuần tuý ở trên
    chạy và test được mà không cần cài SDK Google.
    """

    SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
    FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink)"

    def __init__(self, credentials_path: str) -> None:
        from google.oauth2 import service_account  # noqa: PLC0415
        from googleapiclient.discovery import build  # noqa: PLC0415

        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=self.SCOPES
        )
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_children(self, folder_id: str) -> Iterable[dict[str, Any]]:
        page_token = None
        while True:
            response = (
                self._service.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields=self.FIELDS,
                    pageSize=200,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            yield from response.get("files", [])
            page_token = response.get("nextPageToken")
            if not page_token:
                return


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quét Drive và dựng manifest.json")
    parser.add_argument("--out", default="state/manifest.json", help="Nơi lưu chỉ mục")
    parser.add_argument("--credentials", default=None,
                        help="Đường dẫn service account đọc (mặc định lấy từ GOOGLE_SA_READ_JSON)")
    parser.add_argument("--max-files", type=int, default=5000)
    args = parser.parse_args(argv)

    import os

    credentials = args.credentials or os.environ.get("GOOGLE_SA_READ_JSON")
    if not credentials:
        print("✖ Thiếu credential đọc Drive. Đặt biến GOOGLE_SA_READ_JSON hoặc dùng --credentials.",
              file=sys.stderr)
        return 2

    rules = load_doctype_rules()
    folders = FolderConfig.load()

    lister = GoogleDriveLister(credentials)
    raw_files = walk_drive(lister, folders.read_roots, max_files=args.max_files)
    manifest = build_manifest(raw_files, rules)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest.save(out_path)

    by_type: dict[str, int] = {}
    for entry in manifest.files:
        by_type[entry.doc_type] = by_type.get(entry.doc_type, 0) + 1

    print(f"✓ Đã lập chỉ mục {len(manifest.files)} tài liệu → {out_path}")
    for doc_type, count in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"    {doc_type:<18} {count:>4}")
    if by_type.get("khac", 0) > len(manifest.files) * 0.4:
        print("⚠️  Hơn 40% tài liệu chưa phân loại được — nên bổ sung luật trong "
              "config/doctypes.yaml, nếu không việc tìm kiếm sẽ kém chính xác.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
