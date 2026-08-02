"""Nạp cấu hình. Config là code — review qua git, không sửa lúc chạy."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .manifest import DEFAULT_ORDER, ORDER_KEYS, DocTypeRule

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def load_doctype_rules(path: str | Path | None = None) -> list[DocTypeRule]:
    """Nạp luật gán docType từ doctypes.yaml, kiểm tra hợp lệ ngay khi nạp.

    Sai config phải nổ lúc khởi động chứ không phải lúc đang chạy giữa chừng —
    một order_by gõ nhầm mà im lặng bỏ qua sẽ khiến agent chọn sai bản tài liệu
    mà không ai biết.
    """
    config_path = Path(path) if path else CONFIG_DIR / "doctypes.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    rules: list[DocTypeRule] = []
    seen: set[str] = set()
    for raw in data.get("rules", []):
        doc_type = raw.get("doc_type")
        if not doc_type:
            raise ValueError(f"{config_path}: có luật thiếu trường 'doc_type'.")
        if doc_type in seen:
            raise ValueError(f"{config_path}: docType {doc_type!r} bị khai báo trùng.")
        seen.add(doc_type)

        order = tuple(raw.get("order_by") or DEFAULT_ORDER)
        invalid = [k for k in order if k not in ORDER_KEYS]
        if invalid:
            raise ValueError(
                f"{config_path}: docType {doc_type!r} có khoá sắp xếp không hợp lệ {invalid}. "
                f"Chỉ chấp nhận: {', '.join(ORDER_KEYS)}."
            )

        rules.append(
            DocTypeRule(
                doc_type=doc_type,
                label=raw.get("label", ""),
                path_contains=list(raw.get("path_contains") or []),
                name_matches=list(raw.get("name_matches") or []),
                order_by=order,
            )
        )

    if not rules:
        raise ValueError(f"{config_path}: không có luật nào.")
    return rules


@dataclass
class FolderConfig:
    """Phạm vi Drive mà agent được chạm tới."""

    read_roots: list[str] = field(default_factory=list)
    write_root_path: str = ""
    write_root_id: str = ""
    recipient_allowlist: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "FolderConfig":
        config_path = Path(path) if path else CONFIG_DIR / "folders.yaml"
        data: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        cfg = cls(
            read_roots=[str(f["id"]) for f in data.get("read_roots") or []],
            write_root_path=str(data.get("write_root", {}).get("path", "")),
            write_root_id=str(data.get("write_root", {}).get("id", "")),
            recipient_allowlist=list(data.get("recipient_allowlist") or []),
        )
        if not cfg.read_roots:
            raise ValueError(f"{config_path}: chưa khai báo read_roots — agent sẽ không đọc được gì.")
        if not cfg.write_root_path:
            raise ValueError(f"{config_path}: chưa khai báo write_root — mọi thao tác ghi sẽ bị chặn.")
        return cfg
