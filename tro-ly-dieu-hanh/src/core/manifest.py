"""Chỉ mục Drive: phân loại tài liệu, tìm kiếm và chọn bản mới nhất.

Toàn bộ module này chạy trên metadata đã quét sẵn (manifest.json), không gọi
mạng. Nhờ vậy câu hỏi "bảng giá mới nhất" trở thành phép lọc-và-sắp-xếp tốn 0
token và cho kết quả giống hệt nhau mỗi lần hỏi.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .version import Period, Version, parse_period, parse_version

# Thứ tự ưu tiên khi so hai tài liệu cùng loại. Đặt trong config theo docType
# vì không có đáp án chung: bảng giá nhìn kỳ áp dụng, mẫu văn bản nhìn số bản.
ORDER_KEYS = ("version", "period", "modified")
DEFAULT_ORDER = ("version", "period", "modified")


def normalize(text: str) -> str:
    """Bỏ dấu và hạ chữ thường, để 'Bảng giá' khớp được với 'bang gia'."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.replace("đ", "d")


@dataclass
class DocTypeRule:
    """Luật gán docType từ đường dẫn và tên file."""

    doc_type: str
    label: str = ""
    path_contains: list[str] = field(default_factory=list)
    name_matches: list[str] = field(default_factory=list)
    order_by: tuple[str, ...] = DEFAULT_ORDER

    def matches_name(self, name: str) -> bool:
        norm_name = normalize(name)
        return any(re.search(normalize(p), norm_name) for p in self.name_matches)

    def matches_path(self, path: str) -> bool:
        norm_path = normalize(path)
        return any(normalize(p) in norm_path for p in self.path_contains)

    def matches(self, path: str, name: str) -> bool:
        """Khớp nếu tên HOẶC đường dẫn khớp. Xem `classify` về thứ tự ưu tiên."""
        return self.matches_name(name) or self.matches_path(path)


@dataclass
class FileEntry:
    """Một tài liệu trong chỉ mục."""

    id: str
    name: str
    path: str
    mime: str = ""
    modified_time: str = ""  # ISO 8601
    doc_type: str = "khac"
    size_bytes: int = 0
    web_url: str = ""

    def __post_init__(self) -> None:
        self._version = parse_version(self.name)
        self._period = parse_period(self.name)

    @property
    def version(self) -> Version:
        return self._version

    @property
    def period(self) -> Period:
        return self._period

    @property
    def modified_dt(self) -> datetime:
        if not self.modified_time:
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            return datetime.fromisoformat(self.modified_time.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)

    def sort_key(self, order_by: Sequence[str] = DEFAULT_ORDER) -> tuple:
        parts: list[Any] = []
        for key in order_by:
            if key == "version":
                parts.append(self.version.sort_key())
            elif key == "period":
                parts.append(self.period.sort_key())
            elif key == "modified":
                parts.append(self.modified_dt.timestamp())
            else:
                raise ValueError(f"Khoá sắp xếp không hợp lệ: {key!r}")
        return tuple(parts)

    def describe(self) -> str:
        return f"{self.name} (bản {self.version}, kỳ {self.period}, sửa {self.modified_time or '—'})"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["version"] = {"raw": self.version.raw, "major": self.version.major,
                           "minor": self.version.minor}
        data["period"] = {"raw": self.period.raw, "year": self.period.year,
                          "month": self.period.month}
        return data


@dataclass
class Resolution:
    """Kết quả chọn bản mới nhất.

    `conflicts` không rỗng nghĩa là không thể tự quyết — S5 phải hỏi người dùng
    thay vì đoán. Đây là điểm khác biệt so với việc để LLM chọn: nó luôn chọn
    một cái gì đó, kể cả khi dữ liệu không đủ để chọn.
    """

    winner: FileEntry | None
    conflicts: list[FileEntry] = field(default_factory=list)
    reason: str = ""

    @property
    def needs_human(self) -> bool:
        return bool(self.conflicts)


def classify(path: str, name: str, rules: Sequence[DocTypeRule]) -> str:
    """Gán docType. Tên file thắng đường dẫn; trong mỗi vòng, luật đầu tiên thắng.

    Hai vòng chứ không phải một, vì tên file là tín hiệu mạnh hơn nhiều so với
    thư mục chứa nó:

      - Đòi hỏi cả hai cùng khớp thì "Mẫu công văn.docx" nằm trong /Hành chính
        sẽ rơi vào nhóm 'khac' — tài liệu có thật mà agent tìm không ra.
      - Khớp một trong hai theo cùng một vòng thì "Biên bản nghiệm thu.docx"
        nằm trong /Hợp đồng lại bị gán nhầm thành hợp đồng, vì luật hợp đồng
        đứng trước và đường dẫn khớp.

    Ưu tiên tên trước, đường dẫn sau, giải quyết được cả hai. Đường dẫn vẫn có
    ích cho những file đặt tên chung chung nằm trong thư mục rõ ràng.
    """
    for rule in rules:
        if rule.matches_name(name):
            return rule.doc_type
    for rule in rules:
        if rule.matches_path(path):
            return rule.doc_type
    return "khac"


def order_for(doc_type: str, rules: Sequence[DocTypeRule]) -> tuple[str, ...]:
    for rule in rules:
        if rule.doc_type == doc_type:
            return rule.order_by
    return DEFAULT_ORDER


class Manifest:
    """Chỉ mục tra cứu được, dựng từ metadata Drive."""

    def __init__(self, files: Iterable[FileEntry], generated_at: str = "",
                 stale: bool = False, rules: Sequence[DocTypeRule] = ()) -> None:
        self.files = list(files)
        self.generated_at = generated_at
        self.stale = stale
        self.rules = list(rules)

    # ---------- tìm kiếm ----------

    def search(self, doc_type: str | None = None, keywords: Sequence[str] = (),
               limit: int | None = None) -> list[FileEntry]:
        """Lọc theo docType và từ khoá (bỏ dấu, khớp trên tên + đường dẫn).

        Mọi từ khoá đều phải xuất hiện — dùng AND chứ không OR, vì OR trên tập
        vài trăm file trả về quá nhiều nhiễu để LLM chọn lọc hiệu quả.
        """
        results = []
        norm_keywords = [normalize(k) for k in keywords if k.strip()]
        for entry in self.files:
            if doc_type and entry.doc_type != doc_type:
                continue
            haystack = normalize(f"{entry.path} {entry.name}")
            if all(kw in haystack for kw in norm_keywords):
                results.append(entry)

        results.sort(key=lambda e: e.sort_key(order_for(e.doc_type, self.rules)), reverse=True)
        return results[:limit] if limit else results

    # ---------- chọn bản mới nhất ----------

    def resolve_latest(self, doc_type: str | None = None,
                       keywords: Sequence[str] = ()) -> Resolution:
        candidates = self.search(doc_type=doc_type, keywords=keywords)
        if not candidates:
            return Resolution(winner=None, reason="Không có tài liệu nào khớp.")

        order = order_for(doc_type or candidates[0].doc_type, self.rules)
        return resolve_latest(candidates, order)

    # ---------- nạp / lưu ----------

    def to_json(self) -> str:
        return json.dumps(
            {
                "generatedAt": self.generated_at,
                "stale": self.stale,
                "files": [f.to_dict() for f in self.files],
            },
            ensure_ascii=False,
            indent=2,
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, rules: Sequence[DocTypeRule] = ()) -> "Manifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        files = [
            FileEntry(
                id=f["id"], name=f["name"], path=f["path"], mime=f.get("mime", ""),
                modified_time=f.get("modified_time", ""), doc_type=f.get("doc_type", "khac"),
                size_bytes=f.get("size_bytes", 0), web_url=f.get("web_url", ""),
            )
            for f in data.get("files", [])
        ]
        return cls(files, generated_at=data.get("generatedAt", ""),
                   stale=data.get("stale", False), rules=rules)

    @property
    def age_hours(self) -> float:
        if not self.generated_at:
            return float("inf")
        try:
            generated = datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
        except ValueError:
            return float("inf")
        return (datetime.now(timezone.utc) - generated).total_seconds() / 3600


def resolve_latest(candidates: Sequence[FileEntry],
                   order: Sequence[str] = DEFAULT_ORDER) -> Resolution:
    """Chọn bản mới nhất, hoặc báo xung đột nếu dữ liệu không đủ để quyết.

    Hai tình huống bắt buộc phải hỏi người:

    1. Hai file có khoá sắp xếp bằng nhau hoàn toàn — không có cơ sở để chọn.
    2. File thắng có thông tin bản/kỳ, nhưng một file khác *không* có thông tin đó
       lại được sửa muộn hơn. Đây là trường hợp thật hay gặp: "Bảng giá v3.2.xlsx"
       và "Bảng giá mới nhất.xlsx" sửa hôm qua. Chọn bừa cái nào cũng có thể sai.
    """
    if not candidates:
        return Resolution(winner=None, reason="Không có tài liệu nào khớp.")

    ranked = sorted(candidates, key=lambda e: e.sort_key(order), reverse=True)
    winner = ranked[0]

    ties = [e for e in ranked[1:] if e.sort_key(order) == winner.sort_key(order)]
    if ties:
        return Resolution(
            winner=None,
            conflicts=[winner, *ties],
            reason="Nhiều tài liệu có cùng số bản và kỳ áp dụng, không có cơ sở để chọn.",
        )

    if winner.version.known or winner.period.known:
        undated_newer = [
            e for e in ranked[1:]
            if not e.version.known and not e.period.known and e.modified_dt > winner.modified_dt
        ]
        if undated_newer:
            return Resolution(
                winner=None,
                conflicts=[winner, *undated_newer],
                reason=("Có tài liệu không ghi số bản/kỳ nhưng được sửa muộn hơn bản "
                        "được chọn — cần xác nhận đâu mới là bản đang dùng."),
            )

    return Resolution(winner=winner, reason=f"Chọn theo thứ tự {' → '.join(order)}.")
