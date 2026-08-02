"""Test S8 — cổng phê duyệt.

Nhóm test này là chốt chặn cuối: nếu nó hỏng mà không ai biết, agent có thể gửi
văn bản ra ngoài khi chưa có người duyệt.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.core.guards import GuardError
from src.stages.s8_approve import (
    APPROVED,
    BLOCKED,
    EDITED,
    REJECTED,
    ApprovalRequest,
    ConsoleChannel,
    Decision,
    log_decision,
    render_request,
    require_approval,
)

APPROVERS = ["12345"]


def make_request(**kwargs):
    defaults = dict(
        run_id="2026-08-02-a1",
        flow="DRAFT_DOC",
        title="Công văn gửi Sở Công Thương",
        body="Kính gửi Sở Công Thương...",
        sources=["Giấy phép kinh doanh 2024 (v2)", "Mẫu công văn HH-2025"],
        warnings=["Số hiệu công văn để trống — chưa có trong nguồn nào."],
        action="Ghi vào /HOA HUY GREEN/Agent Output/",
    )
    defaults.update(kwargs)
    return ApprovalRequest(**defaults)


class ScriptedChannel:
    """Kênh giả, trả về quyết định đã định sẵn."""

    def __init__(self, decision: Decision):
        self.decision = decision
        self.seen: ApprovalRequest | None = None

    def request_decision(self, request):
        self.seen = request
        return self.decision


class TestRenderRequest(unittest.TestCase):
    def test_shows_action_sources_and_warnings(self):
        text = render_request(make_request())
        self.assertIn("DRAFT_DOC", text)
        self.assertIn("Ghi vào /HOA HUY GREEN/Agent Output/", text)
        self.assertIn("Giấy phép kinh doanh 2024", text)
        self.assertIn("Số hiệu công văn để trống", text)
        self.assertIn("Kính gửi Sở Công Thương", text)

    def test_warning_section_always_present(self):
        """Không có cảnh báo cũng phải nói rõ là không có.

        Một agent luôn báo cáo trơn tru là một agent đang giấu rủi ro — người
        duyệt cần phân biệt được 'đã kiểm tra, sạch' với 'quên không kiểm tra'.
        """
        text = render_request(make_request(warnings=[]))
        self.assertIn("Không có cảnh báo", text)

    def test_empty_sources_are_called_out(self):
        self.assertIn("không có nguồn nào", render_request(make_request(sources=[])))


class TestConsoleChannel(unittest.TestCase):
    def _channel(self, answers):
        outputs = []
        answers = list(answers)
        channel = ConsoleChannel(
            approver="12345",
            input_fn=lambda *_: answers.pop(0),
            output_fn=outputs.append,
        )
        return channel, outputs

    def test_approve(self):
        channel, _ = self._channel(["d"])
        decision = channel.request_decision(make_request())
        self.assertEqual(decision.status, APPROVED)
        self.assertTrue(decision.allowed)

    def test_reject_captures_reason(self):
        channel, _ = self._channel(["t", "Sai số hiệu"])
        decision = channel.request_decision(make_request())
        self.assertEqual(decision.status, REJECTED)
        self.assertEqual(decision.reason, "Sai số hiệu")
        self.assertFalse(decision.allowed)

    def test_edit_captures_body(self):
        channel, _ = self._channel(["s", "Dòng 1", "Dòng 2", "EOF"])
        decision = channel.request_decision(make_request())
        self.assertEqual(decision.status, EDITED)
        self.assertEqual(decision.edited_body, "Dòng 1\nDòng 2")
        self.assertTrue(decision.allowed)

    def test_reprompts_on_invalid_input(self):
        channel, outputs = self._channel(["x", "d"])
        self.assertEqual(channel.request_decision(make_request()).status, APPROVED)
        self.assertTrue(any("Không hiểu" in o for o in outputs))


class TestRequireApproval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "decisions.jsonl"
        self.addCleanup(self.tmp.cleanup)

    def test_approved_decision_passes_through_and_is_logged(self):
        channel = ScriptedChannel(Decision("r1", APPROVED, approver="12345"))
        decision = require_approval(make_request(), channel, APPROVERS, log_path=self.log)

        self.assertTrue(decision.allowed)
        self.assertEqual(len(self.log.read_text(encoding="utf-8").strip().splitlines()), 1)

    def test_kill_switch_blocks_and_logs(self):
        """AGENT_DISABLED=1 phải chặn cứng, và vẫn ghi sổ — nhất là khi bị chặn."""
        channel = ScriptedChannel(Decision("r1", APPROVED, approver="12345"))
        with mock.patch.dict(os.environ, {"AGENT_DISABLED": "1"}):
            with self.assertRaises(GuardError):
                require_approval(make_request(), channel, APPROVERS, log_path=self.log)

        self.assertIsNone(channel.seen)  # chưa từng hỏi ai
        logged = json.loads(self.log.read_text(encoding="utf-8").strip())
        self.assertEqual(logged["status"], BLOCKED)

    def test_channel_cannot_self_authorise(self):
        """Kênh phê duyệt khẳng định 'đã duyệt' nhưng người duyệt không có quyền
        thì vẫn phải bị chặn — không tin kênh, chỉ tin danh sách."""
        channel = ScriptedChannel(Decision("r1", APPROVED, approver="99999"))
        with self.assertRaises(GuardError):
            require_approval(make_request(), channel, APPROVERS, log_path=self.log)

    def test_rejection_by_unlisted_user_is_allowed(self):
        """Từ chối thì ai cũng có quyền — chỉ việc CHO PHÉP mới cần thẩm quyền."""
        channel = ScriptedChannel(Decision("r1", REJECTED, approver="99999"))
        decision = require_approval(make_request(), channel, APPROVERS, log_path=self.log)
        self.assertEqual(decision.status, REJECTED)

    def test_caller_identity_is_checked_before_asking(self):
        channel = ScriptedChannel(Decision("r1", APPROVED, approver="12345"))
        with self.assertRaises(GuardError):
            require_approval(make_request(), channel, APPROVERS,
                             approver_id="99999", log_path=self.log)
        self.assertIsNone(channel.seen)


class TestLogDecision(unittest.TestCase):
    def test_appends_one_line_per_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "decisions.jsonl"
            log_decision(Decision("r1", APPROVED, approver="a"), path)
            log_decision(Decision("r2", REJECTED, approver="b", reason="sai"), path)

            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[1])["reason"], "sai")

    def test_redacts_secrets_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions.jsonl"
            log_decision(Decision("r1", REJECTED, reason="lộ key sk-ant-api03-AbCdEf123456"),
                         path)
            content = path.read_text(encoding="utf-8")

        self.assertNotIn("sk-ant-api03", content)
        self.assertIn("ĐÃ CHE", content)

    def test_decided_at_is_filled_automatically(self):
        self.assertTrue(Decision("r1", APPROVED).decided_at)


if __name__ == "__main__":
    unittest.main()
