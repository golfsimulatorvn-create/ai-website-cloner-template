"""Giải nghĩa phiên bản tài liệu từ tên file.

Đây là phần thay thế cho việc hỏi LLM "file nào mới nhất". Toàn bộ logic ở đây
là xác định: cùng đầu vào luôn cho cùng kết quả, và sai thì test bắt được.

Hai khái niệm tách biệt:
  - version : số hiệu bản do người đặt, ví dụ "v3.2"
  - period  : kỳ áp dụng của tài liệu, ví dụ "2026-07", "T7/2026", "28-07-2026"

Chúng không phải một thứ, và cái nào ưu tiên hơn phụ thuộc loại tài liệu:
bảng giá thì kỳ áp dụng quan trọng hơn số bản, còn mẫu văn bản thì ngược lại.
Vì vậy thứ tự ưu tiên nằm trong config theo từng docType, không hardcode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Bỏ phần mở rộng file trước khi parse, tránh ".docx" gây nhiễu.
# Bắt buộc bắt đầu bằng chữ cái: file Google Docs gốc không có đuôi mở rộng, nên
# tên "Bảng giá v3.2" là có thật — cắt ".2" ở đây sẽ làm mất số bản phụ.
_EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,4}$")

# "v3.2", "V 3", "ver3.1", "phiên bản 2", "phien ban 2.0"
_VERSION_RE = re.compile(
    r"(?:^|[\s_\-(\[.])"
    r"(?:v|ver|version|phiên\s*bản|phien\s*ban)"
    r"\s*\.?\s*"
    r"(\d{1,3})(?:\.(\d{1,3}))?"
    r"(?![\d.])",
    re.IGNORECASE,
)

# Thứ tự thử rất quan trọng: mẫu cụ thể trước, mẫu chung sau.
# Mỗi mẫu trả về (year, month) — month = 0 nghĩa là chỉ biết năm.
_PERIOD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 2026-07-28 hoặc 2026/07
    (re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?(?!\d)"), "ymd"),
    # 28-07-2026
    (re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})(?!\d)"), "dmy"),
    # T7/2026, T7.2026, tháng 7/2026
    (
        re.compile(r"(?:^|[\s_\-(\[])(?:t|tháng|thang)\s*(\d{1,2})[-/. ]\s*(20\d{2})(?!\d)", re.IGNORECASE),
        "my",
    ),
    # 07-2026 (tháng-năm, không có ngày)
    (re.compile(r"(?<!\d)(\d{1,2})[-/.](20\d{2})(?!\d)"), "my"),
    # 2026 đứng một mình
    (re.compile(r"(?<!\d)(20\d{2})(?!\d)"), "y"),
]


@dataclass(frozen=True)
class Version:
    """Số hiệu bản đọc được từ tên file. Mọi trường None nghĩa là không có."""

    raw: str | None = None
    major: int | None = None
    minor: int | None = None

    @property
    def known(self) -> bool:
        return self.major is not None

    def sort_key(self) -> tuple[int, int]:
        # Không có version xếp dưới mọi version có thật
        return (self.major if self.major is not None else -1,
                self.minor if self.minor is not None else -1)

    def __str__(self) -> str:
        if not self.known:
            return "—"
        return f"v{self.major}" + (f".{self.minor}" if self.minor is not None else "")


@dataclass(frozen=True)
class Period:
    """Kỳ áp dụng đọc được từ tên file."""

    raw: str | None = None
    year: int | None = None
    month: int | None = None

    @property
    def known(self) -> bool:
        return self.year is not None

    def sort_key(self) -> tuple[int, int]:
        return (self.year or -1, self.month or 0)

    def __str__(self) -> str:
        if not self.known:
            return "—"
        return f"{self.year}-{self.month:02d}" if self.month else str(self.year)


def strip_extension(name: str) -> str:
    return _EXT_RE.sub("", name)


def parse_version(name: str) -> Version:
    """Đọc số hiệu bản từ tên file.

    Chỉ nhận khi có tiền tố rõ ràng (v/ver/phiên bản). Một con số trần trong tên
    file gần như luôn là ngày tháng hoặc công suất, không phải số bản — đoán bừa
    ở đây gây sai lệch âm thầm, nên ta cố tình không đoán.
    """
    stem = strip_extension(name)
    match = None
    for match in _VERSION_RE.finditer(stem):  # lấy lần khớp cuối cùng
        pass
    if match is None:
        return Version()
    major = int(match.group(1))
    minor = int(match.group(2)) if match.group(2) is not None else None
    return Version(raw=match.group(0).strip(" _-([."), major=major, minor=minor)


def parse_period(name: str) -> Period:
    """Đọc kỳ áp dụng từ tên file.

    Bỏ qua đoạn đã được nhận là số hiệu bản, để "v3.2 - 2026" không bị hiểu
    nhầm thành tháng 3 năm 2026.
    """
    stem = strip_extension(name)

    version = parse_version(name)
    if version.raw:
        stem = stem.replace(version.raw, " ", 1)

    for pattern, kind in _PERIOD_PATTERNS:
        m = pattern.search(stem)
        if not m:
            continue
        if kind == "ymd":
            year, month = int(m.group(1)), int(m.group(2))
        elif kind == "dmy":
            year, month = int(m.group(3)), int(m.group(2))
        elif kind == "my":
            month, year = int(m.group(1)), int(m.group(2))
        else:  # "y"
            year, month = int(m.group(1)), 0

        if month and not 1 <= month <= 12:
            continue  # ví dụ "15-20-2026" — không phải tháng hợp lệ, thử mẫu sau
        return Period(raw=m.group(0).strip(), year=year, month=month or None)

    return Period()
