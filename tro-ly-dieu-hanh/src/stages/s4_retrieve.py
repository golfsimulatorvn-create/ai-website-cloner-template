"""S4 + S5 — truy xuất tài liệu và kiểm chứng nguồn.

Toàn bộ bước này chạy được **không cần LLM**: chỉ mục lọc theo docType và từ
khoá, luật phiên bản chọn bản mới nhất, rồi trích đoạn quanh từ khoá. Chỗ dành
cho LLM là giao diện `Picker` — khi cần chọn lọc tinh hơn giữa nhiều ứng viên
thì cắm bộ chọn bằng model vào, phần còn lại không đổi.

Kiểm chứng nguồn (S5) trả về báo cáo chứ không tự quyết. Thiếu tài liệu bắt buộc
thì dừng và nói "không tìm thấy"; xung đột phiên bản thì hỏi người. Đây là điểm
khác biệt căn bản so với việc đưa thẳng câu hỏi cho model — model luôn trả lời
một cái gì đó, kể cả khi dữ liệu không đủ để trả lời.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, Sequence

from ..core.guards import wrap_untrusted
from ..core.manifest import FileEntry, Manifest, Resolution
from ..tools.extract import (
    Downloader,
    ExtractionError,
    TextCache,
    extract_file,
    find_excerpts,
)

STALE_AFTER_HOURS = 24


@dataclass
class DocNeed:
    """Một loại tài liệu mà kế hoạch cần."""

    label: str
    doc_type: str | None = None
    keywords: list[str] = field(default_factory=list)
    must_have: bool = False
    max_docs: int = 1


@dataclass
class Evidence:
    """Một tài liệu đã lấy được, kèm trích đoạn liên quan."""

    file_id: str
    name: str
    path: str
    drive_url: str = ""
    version: str = "—"
    period: str = "—"
    modified_time: str = ""
    excerpts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    injection_hits: list[str] = field(default_factory=list)
    need_label: str = ""
    retrieved_at: str = ""

    @property
    def suspicious(self) -> bool:
        return bool(self.injection_hits)

    def cite(self) -> str:
        return f"[[ref:{self.file_id}]]"

    def describe(self) -> str:
        return f"{self.name} (bản {self.version}, kỳ {self.period})"


@dataclass
class EvidenceReport:
    """Kết quả kiểm chứng nguồn — S5."""

    covered: list[str] = field(default_factory=list)
    missing: list[DocNeed] = field(default_factory=list)
    conflicts: list[Resolution] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    stale: bool = False
    suspicious_files: list[str] = field(default_factory=list)

    @property
    def missing_required(self) -> list[DocNeed]:
        return [need for need in self.missing if need.must_have]

    @property
    def needs_human(self) -> bool:
        """Có xung đột phiên bản thì bắt buộc hỏi người, không được đoán."""
        return bool(self.conflicts)

    @property
    def can_proceed(self) -> bool:
        return not self.needs_human and not self.missing_required


class Picker(Protocol):
    """Chọn tài liệu nào trong số ứng viên sẽ được lấy.

    Bộ chọn mặc định là thuần luật. Khi cần chọn lọc theo ngữ nghĩa, cắm bộ chọn
    bằng LLM vào đây — S4 không cần biết bên trong là gì.
    """

    def pick(self, candidates: Sequence[FileEntry], need: DocNeed) -> list[FileEntry]:
        ...


class LatestPicker:
    """Bộ chọn mặc định: lấy bản mới nhất theo luật phiên bản của docType.

    Trả về rỗng khi có xung đột — để S5 phát hiện và hỏi người, thay vì lặng lẽ
    chọn bừa một bản.
    """

    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest
        self.last_conflict: Resolution | None = None

    def pick(self, candidates: Sequence[FileEntry], need: DocNeed) -> list[FileEntry]:
        self.last_conflict = None
        if not candidates:
            return []

        if need.max_docs > 1:
            return list(candidates[: need.max_docs])

        from ..core.manifest import order_for, resolve_latest

        order = order_for(need.doc_type or candidates[0].doc_type, self.manifest.rules)
        result = resolve_latest(candidates, order)
        if result.needs_human:
            self.last_conflict = result
            return []
        return [result.winner] if result.winner else []


def retrieve(
    manifest: Manifest,
    needs: Sequence[DocNeed],
    downloader: Downloader,
    cache: TextCache | None = None,
    picker: Picker | None = None,
) -> tuple[list[Evidence], EvidenceReport]:
    """Lấy tài liệu cho từng nhu cầu và kiểm chứng kết quả."""
    picker = picker or LatestPicker(manifest)
    report = EvidenceReport(stale=manifest.stale or manifest.age_hours > STALE_AFTER_HOURS)
    evidence: list[Evidence] = []

    for need in needs:
        candidates = manifest.search(doc_type=need.doc_type, keywords=need.keywords)
        picked = picker.pick(candidates, need)

        conflict = getattr(picker, "last_conflict", None)
        if conflict is not None:
            report.conflicts.append(conflict)
            continue

        if not picked:
            report.missing.append(need)
            continue

        got_any = False
        for entry in picked:
            try:
                extracted = extract_file(
                    file_id=entry.id,
                    mime=entry.mime,
                    modified_time=entry.modified_time,
                    downloader=downloader,
                    cache=cache,
                    name=entry.name,
                )
            except ExtractionError as exc:
                report.failed.append(f"{entry.name}: {exc}")
                continue

            warnings: list[str] = []
            if extracted.truncated:
                warnings.append(f"Tài liệu bị cắt ở {extracted.char_count} ký tự.")
            if extracted.injection_hits:
                warnings.append(
                    f"Phát hiện {len(extracted.injection_hits)} dấu hiệu chỉ dẫn lạ "
                    "trong nội dung — đã xử lý như dữ liệu, không thi hành."
                )
                report.suspicious_files.append(entry.id)

            evidence.append(
                Evidence(
                    file_id=entry.id,
                    name=entry.name,
                    path=entry.path,
                    drive_url=entry.web_url,
                    version=str(entry.version),
                    period=str(entry.period),
                    modified_time=entry.modified_time,
                    excerpts=find_excerpts(extracted.text, need.keywords),
                    warnings=warnings,
                    injection_hits=list(extracted.injection_hits),
                    need_label=need.label,
                    retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
            )
            got_any = True

        if got_any:
            report.covered.append(need.label)
        else:
            report.missing.append(need)

    return evidence, report


def to_prompt_context(evidence: Sequence[Evidence]) -> str:
    """Ghép trích đoạn thành khối đưa vào prompt.

    Mọi nội dung đi qua wrap_untrusted — không có đường nào khác để nội dung
    Drive lọt vào prompt. Đây là chỗ ràng buộc đó được thực thi.
    """
    blocks = []
    for item in evidence:
        body = "\n\n---\n\n".join(item.excerpts) if item.excerpts else "(không có trích đoạn)"
        header = f"Nguồn: {item.describe()}\nMã trích dẫn: {item.cite()}\n\n"
        blocks.append(wrap_untrusted(header + body, item.file_id, item.name))
    return "\n\n".join(blocks)


def format_not_found(report: EvidenceReport) -> str:
    """Câu trả lời khi không đủ nguồn. Nói rõ thiếu gì, không vòng vo."""
    lines = ["Không tìm thấy đủ tài liệu để trả lời."]
    if report.missing:
        lines.append("\nThiếu:")
        lines += [f"  • {need.label}"
                  + (f" (từ khoá: {', '.join(need.keywords)})" if need.keywords else "")
                  for need in report.missing]
    if report.failed:
        lines.append("\nĐọc được nhưng trích xuất lỗi:")
        lines += [f"  • {item}" for item in report.failed]
    if report.stale:
        lines.append("\n⚠️ Chỉ mục Drive đã cũ — nên chạy lại S0 rồi thử lại.")
    return "\n".join(lines)


def format_conflicts(report: EvidenceReport) -> str:
    """Câu hỏi khi có xung đột phiên bản. Người chọn, agent không đoán."""
    lines = ["Có nhiều bản tài liệu và không đủ cơ sở để tự chọn:"]
    for conflict in report.conflicts:
        lines.append(f"\n{conflict.reason}")
        for entry in conflict.conflicts:
            lines.append(f"  • {entry.describe()}")
    lines.append("\nBạn muốn dùng bản nào?")
    return "\n".join(lines)
