"""S8 — cổng phê duyệt của con người.

Mọi thứ rời khỏi hệ thống đều đi qua đây. Không có đường vòng, không có cờ
"khẩn cấp" để bỏ qua: nếu một hành động cần duyệt, nó chỉ chạy sau khi có người
trong danh sách bấm duyệt.

Về kênh phê duyệt, MVP dùng `ConsoleChannel` vì agent chạy theo lệnh thủ công —
người ra lệnh đang ngồi trước màn hình, hỏi ngay tại chỗ là nhanh nhất và không
cần hạ tầng gì. `TelegramNotifier` là kênh MỘT CHIỀU để gửi cảnh báo và thông
báo, không dùng để thu quyết định: thu quyết định qua chat cần vòng lặp polling
và cơ chế chống bấm trùng, thuộc phạm vi bản STABLE.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Sequence

from ..core.guards import GuardError, check_approver, redact_secrets

APPROVED = "approved"
REJECTED = "rejected"
EDITED = "edited"
TIMEOUT = "timeout"
BLOCKED = "blocked"


@dataclass
class ApprovalRequest:
    """Thứ trình cho người duyệt.

    Bốn phần cố định, để người quyết định được trong 30 giây: làm gì, dựa trên
    nguồn nào, có gì cần chú ý, và nội dung cụ thể.
    """

    run_id: str
    flow: str
    title: str
    body: str = ""
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    action: str = ""  # hành động sẽ thực hiện nếu duyệt, ví dụ "Ghi vào /Agent Output/"


@dataclass
class Decision:
    run_id: str
    status: str
    approver: str = ""
    reason: str = ""
    edited_body: str = ""
    decided_at: str = ""
    flow: str = ""

    def __post_init__(self) -> None:
        if not self.decided_at:
            self.decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    @property
    def allowed(self) -> bool:
        return self.status in (APPROVED, EDITED)


def render_request(request: ApprovalRequest) -> str:
    """Dựng tin nhắn xin duyệt.

    Phần cảnh báo là bắt buộc phải hiển thị kể cả khi rỗng: một agent luôn báo
    cáo trơn tru là một agent đang giấu rủi ro.
    """
    lines = [f"📋 [{request.flow}] {request.title}", ""]

    if request.action:
        lines += [f"Hành động nếu duyệt: {request.action}", ""]

    lines.append("Nguồn đã dùng:")
    lines += [f"  • {s}" for s in request.sources] or ["  (không có nguồn nào)"]

    lines.append("")
    if request.warnings:
        lines.append("⚠️ Cần chú ý:")
        lines += [f"  • {w}" for w in request.warnings]
    else:
        lines.append("✓ Không có cảnh báo nào từ bước tự kiểm tra.")

    if request.body:
        lines += ["", "─" * 50, request.body, "─" * 50]

    return "\n".join(lines)


class ApprovalChannel(Protocol):
    def request_decision(self, request: ApprovalRequest) -> Decision:
        ...


class ConsoleChannel:
    """Hỏi duyệt ngay tại terminal — kênh chính của bản MVP chạy thủ công."""

    def __init__(self, approver: str = "cli", input_fn=input, output_fn=print) -> None:
        self.approver = approver
        self._input = input_fn
        self._output = output_fn

    def request_decision(self, request: ApprovalRequest) -> Decision:
        self._output(render_request(request))
        self._output("\n[d] Duyệt   [s] Sửa   [t] Từ chối")

        while True:
            choice = str(self._input("Lựa chọn: ")).strip().lower()
            if choice in ("d", "duyet", "duyệt", "y"):
                return Decision(request.run_id, APPROVED, self.approver, flow=request.flow)
            if choice in ("t", "tu choi", "từ chối", "n"):
                reason = str(self._input("Lý do từ chối: ")).strip()
                return Decision(request.run_id, REJECTED, self.approver, reason=reason,
                                flow=request.flow)
            if choice in ("s", "sua", "sửa", "e"):
                self._output("Dán nội dung đã sửa, kết thúc bằng một dòng chỉ có 'EOF':")
                edited: list[str] = []
                while True:
                    line = str(self._input(""))
                    if line.strip() == "EOF":
                        break
                    edited.append(line)
                return Decision(request.run_id, EDITED, self.approver,
                                edited_body="\n".join(edited), flow=request.flow)
            self._output("Không hiểu. Nhập d, s hoặc t.")


class TelegramNotifier:
    """Gửi thông báo một chiều. KHÔNG dùng để thu quyết định phê duyệt."""

    API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: str, chat_ids: Sequence[str], timeout: int = 10) -> None:
        self.token = token
        self.chat_ids = list(chat_ids)
        self.timeout = timeout

    def send(self, text: str) -> list[str]:
        """Gửi tới mọi chat trong danh sách. Trả về danh sách chat gửi lỗi.

        Không bao giờ ném lỗi ra ngoài: gửi thông báo hỏng không được phép làm
        hỏng luồng công việc chính, nhưng cũng không được im lặng.
        """
        failures: list[str] = []
        payload_text = redact_secrets(text)[:4000]  # Telegram giới hạn 4096 ký tự

        for chat_id in self.chat_ids:
            data = urllib.parse.urlencode(
                {"chat_id": chat_id, "text": payload_text, "disable_web_page_preview": "true"}
            ).encode()
            try:
                req = urllib.request.Request(self.API.format(token=self.token), data=data)
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    if response.status != 200:
                        failures.append(chat_id)
            except (urllib.error.URLError, OSError):
                failures.append(chat_id)
        return failures


def log_decision(decision: Decision, path: str | Path = "state/decisions.jsonl") -> None:
    """Ghi phán quyết vào sổ.

    Đây là dữ liệu quý nhất của hệ thống: nó cho biết agent sai ở đâu theo đánh
    giá của người thật, và là nguyên liệu duy nhất cho vòng tự cải tiến.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(decision), ensure_ascii=False)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(redact_secrets(line) + "\n")


def is_disabled() -> bool:
    return os.environ.get("AGENT_DISABLED", "0").strip() in ("1", "true", "yes")


def require_approval(
    request: ApprovalRequest,
    channel: ApprovalChannel,
    approvers: Sequence[str],
    approver_id: str | None = None,
    log_path: str | Path = "state/decisions.jsonl",
) -> Decision:
    """Cổng bắt buộc trước mọi hành động ra ngoài.

    Ba lớp kiểm tra, theo thứ tự: tắt khẩn cấp → quyền người duyệt → quyết định.
    Mọi kết quả đều được ghi sổ, kể cả khi bị chặn — nhất là khi bị chặn.
    """
    if is_disabled():
        decision = Decision(request.run_id, BLOCKED, reason="AGENT_DISABLED=1",
                            flow=request.flow)
        log_decision(decision, log_path)
        raise GuardError("Agent đang bị tắt khẩn cấp (AGENT_DISABLED=1) — mọi hành động "
                         "ra ngoài bị chặn.")

    if approver_id is not None:
        check_approver(approver_id, approvers)

    decision = channel.request_decision(request)

    # Kênh phê duyệt cũng không được tự phong quyền: người trả lời phải nằm
    # trong danh sách, kể cả khi kênh khẳng định là đã duyệt.
    if decision.allowed and approvers:
        check_approver(decision.approver, approvers)

    log_decision(decision, log_path)
    return decision
