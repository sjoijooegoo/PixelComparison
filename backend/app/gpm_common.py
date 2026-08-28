"""GPMHeatmap 各 API 共享的标识、资源 URL 与错误约定。"""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

from fastapi import HTTPException


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
QUALITY_LABELS = {0: "节能", 1: "流畅", 2: "均衡", 3: "精美", 4: "极致", 5: "电影"}
SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")
SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9._-]{1,200}")


def http_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def safe_segment(value: str, fallback: str) -> str:
    source = str(value or "").strip()
    normalized = SAFE_SEGMENT.sub("_", source).strip("._") or fallback
    if normalized != source or len(normalized) > 120:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:10]
        normalized = f"{normalized[:109]}-{digest}"
    return normalized


def require_identifier(value: str, label: str, *, maximum: int = 200) -> str:
    normalized = str(value or "").strip()
    if len(normalized) > maximum or not SAFE_IDENTIFIER.fullmatch(normalized):
        raise http_error(
            422, "INVALID_IDENTIFIER",
            f"{label} 仅允许字母、数字、点、下划线和连字符",
        )
    return normalized


def require_platform(value: object, label: str = "platform", *, maximum: int = 120) -> str:
    """Validate a display-name platform consistently across upload and configuration APIs."""

    normalized = str(value or "").strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(ord(character) < 32 for character in normalized)
    ):
        raise http_error(
            422, "INVALID_GPM_PLATFORM",
            f"{label} 不能为空、不能包含控制字符且不能超过 {maximum} 个字符",
        )
    return normalized


def asset_url(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    return "/gpm-assets/" + "/".join(
        safe_segment(part, "asset") for part in PurePosixPath(relative_path).parts
    )
