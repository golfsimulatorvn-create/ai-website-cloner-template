"""S1 rút gọn — bóc từ khoá và đoán loại tài liệu từ câu hỏi, bằng luật.

Bản thiết kế dành S1/S2 cho LLM, và đúng là LLM làm việc này tốt hơn khi câu hỏi
diễn đạt vòng vo. Nhưng bản rút gọn bằng luật ở đây đủ dùng cho phần lớn câu hỏi
tra cứu thật, chạy không cần API key, và quan trọng hơn: nó là mốc đối chứng để
sau này đo xem thêm LLM vào có thật sự tốt hơn không.

Khi cắm LLM vào, giữ nguyên chữ ký hàm — phần còn lại của S4 không cần biết
từ khoá đến từ đâu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .manifest import DocTypeRule, normalize

# Từ chức năng không mang thông tin tra cứu. Giữ danh sách ngắn có chủ đích:
# lọc quá tay sẽ mất cả những từ thật sự phân biệt được tài liệu.
STOPWORDS = {
    "cho", "cua", "la", "va", "o", "dau", "nao", "gi", "toi", "can", "tim",
    "xem", "cai", "mot", "cac", "ve", "hay", "giup", "file", "tai", "lieu",
    "co", "khong", "the", "nay", "do", "voi", "tu", "den", "trong", "ra",
    "duoc", "bi", "se", "da", "dang", "thi", "ma", "nhu", "hon", "rat",
    "ban", "minh", "anh", "chi", "em", "a", "oi", "nhe", "nhi", "vay",
    "lay", "dua", "gui", "coi", "kiem", "tra", "bao", "nhieu",
}

# Cụm báo hiệu muốn bản mới nhất — bỏ khỏi từ khoá vì chúng không có trong tên file
LATEST_HINTS = ("moi nhat", "gan nhat", "hien tai", "hien hanh", "cap nhat nhat",
                "latest", "moi ra")


@dataclass
class Intake:
    """Kết quả bóc tách câu hỏi.

    `explicit_latest` ghi lại việc người hỏi có nói rõ "mới nhất" hay không.
    Nó không đổi hành vi — bộ chọn mặc định luôn lấy bản mới nhất — nhưng có ích
    khi rà log: câu hỏi nói rõ mà vẫn trả sai bản là lỗi nặng hơn.
    """

    raw: str
    keywords: list[str] = field(default_factory=list)
    doc_type: str | None = None
    explicit_latest: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.keywords and self.doc_type is None


def _distinctiveness(token: str) -> tuple[int, int]:
    """Điểm ưu tiên khi phải cắt bớt từ khoá.

    Từ có chữ số ("5kwp", "2026") gần như luôn là thứ phân biệt tài liệu này với
    tài liệu khác. Từ dài cũng đặc trưng hơn từ ngắn — tiếng Việt bỏ dấu sinh ra
    rất nhiều âm tiết hai chữ ("ho", "so", "ky") gần như không mang thông tin.
    """
    return (1 if any(c.isdigit() for c in token) else 0, len(token))


def derive_keywords(question: str, max_keywords: int = 6) -> list[str]:
    """Rút từ khoá tra cứu từ câu hỏi.

    Chuẩn hoá bỏ dấu giống hệt chỉ mục — hai bên lệch nhau là trượt hết.

    Khi vượt trần, cắt theo độ đặc trưng chứ không theo thứ tự xuất hiện. Câu
    hỏi tiếng Việt hay mở đầu bằng loại tài liệu ("hồ sơ kỹ thuật…") và kết thúc
    bằng thứ thật sự phân biệt ("…5kWp Bình Dương"). Cắt từ cuối lên sẽ giữ lại
    đúng phần vô dụng — mà tìm kiếm lại dùng AND, nên vừa mất từ phân biệt vừa
    không thu hẹp được kết quả. Loại tài liệu đã được `guess_doc_type` lo riêng.
    """
    text = normalize(question)
    for hint in LATEST_HINTS:
        text = text.replace(hint, " ")

    tokens = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*", text)
    keywords: list[str] = []
    for token in tokens:
        if token in STOPWORDS or len(token) < 2:
            continue
        if token not in keywords:
            keywords.append(token)

    if len(keywords) <= max_keywords:
        return keywords
    return sorted(keywords, key=_distinctiveness, reverse=True)[:max_keywords]


def guess_doc_type(question: str, rules: Sequence[DocTypeRule]) -> str | None:
    """Đoán loại tài liệu bằng chính luật đã dùng để phân loại file.

    Dùng lại một bộ luật cho cả hai phía là có chủ đích: câu hỏi và tên file được
    đối chiếu bằng cùng một tiêu chuẩn, nên không có chuyện phân loại file kiểu
    này mà hiểu câu hỏi kiểu khác.
    """
    text = normalize(question)
    for rule in rules:
        if rule.label and normalize(rule.label) in text:
            return rule.doc_type
        for pattern in rule.name_matches:
            if re.search(normalize(pattern).lstrip("^"), text):
                return rule.doc_type
    return None


def wants_latest(question: str) -> bool:
    return any(hint in normalize(question) for hint in LATEST_HINTS)


def parse(question: str, rules: Sequence[DocTypeRule]) -> Intake:
    return Intake(
        raw=question,
        keywords=derive_keywords(question),
        doc_type=guess_doc_type(question, rules),
        explicit_latest=wants_latest(question),
    )
