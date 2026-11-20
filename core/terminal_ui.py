"""Small, dependency-free terminal panels for the interactive runtime."""

from __future__ import annotations

import textwrap
from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

from core.debug_trace import debug_enabled


PANEL_WIDTH = 78
StatusListener = Callable[[str], None]
_status_listener: ContextVar[StatusListener | None] = ContextVar("status_listener", default=None)


_WEB_STATUS_BY_PANEL = {
    "CHUẨN HÓA CÂU HỎI": "Đang làm rõ nội dung cần hỗ trợ.",
    "NGỮ CẢNH HỘI THOẠI": "Đang đối chiếu với nội dung trao đổi trước đó.",
    "LUỒNG XỬ LÝ": "Đang phân tích tình huống pháp lý.",
    "CASE FACTS": "Đang giữ lại các dữ kiện pháp lý quan trọng của tình huống.",
    "PHÂN TÍCH THỜI GIAN": "Đang xác định mốc thời gian và văn bản áp dụng.",
    "PHÂN RÃ CÂU HỎI": "Đang xác định các vấn đề pháp lý cần tra cứu.",
    "SUB-AGENT": "Đang tra cứu độc lập từng vấn đề pháp lý.",
    "RETRIEVAL PLAN": "Đang lập kế hoạch tra cứu căn cứ phù hợp.",
    "EVIDENCE SELECTOR": "Đang chọn các căn cứ trực tiếp cho từng vấn đề.",
    "CLAIM EXTRACTOR": "Đang trích xuất các quy định pháp luật liên quan.",
    "CLAIM VERIFIER": "Đang kiểm tra căn cứ và điều kiện áp dụng.",
    "EVIDENCE PACK": "Đang tổng hợp các căn cứ đã xác minh.",
    "TRA CỨU BỔ SUNG": "Đang tra cứu thêm căn cứ cho nội dung còn thiếu.",
    "REFINE": "Đang hoàn thiện câu trả lời theo các căn cứ đã kiểm tra.",
    "CRITIQUE": "Đang rà soát lần cuối trước khi trả lời.",
}


@contextmanager
def capture_status(listener: StatusListener) -> Iterator[None]:
    """Forward concise pipeline progress to a web request without changing terminal output."""
    token = _status_listener.set(listener)
    try:
        yield
    finally:
        _status_listener.reset(token)


def _notify_status(message: str) -> None:
    listener = _status_listener.get()
    text = " ".join(str(message or "").split())
    if not listener or not text:
        return
    try:
        listener(text)
    except Exception:
        # A disconnected browser must never interrupt the legal pipeline.
        return


def progress(message: str, detail: str = "") -> None:
    """Show concise progress and an optional terminal-only detail line."""
    if debug_enabled():
        _notify_status(message)
        return
    text = " ".join(str(message or "").split())
    detail_text = " ".join(str(detail or "").split())
    if text:
        _notify_status(text)
        print(f"  [Đang xử lý] {text}", flush=True)
    if detail_text:
        print(f"    └─ {detail_text}", flush=True)


def panel(title: str, lines: str | Iterable[str] = ()) -> None:
    """Print internal pipeline status only in the explicit debug runtime."""
    title_key = str(title or "").strip().upper()
    status = _WEB_STATUS_BY_PANEL.get(title_key)
    if not status and title_key.startswith("CITATION GUARDRAIL"):
        status = "Đang kiểm tra trích dẫn và độ phù hợp của câu trả lời."
    if status:
        _notify_status(status)
    if not debug_enabled():
        return
    if isinstance(lines, str):
        lines = [lines]

    inner_width = PANEL_WIDTH - 2
    title_text = str(title).strip()[: inner_width - 2]
    top = f"┌─ {title_text} "
    print("\n" + top + "─" * max(0, PANEL_WIDTH - len(top) - 1) + "┐")

    rendered_lines: list[str] = []
    for line in lines:
        text = str(line).strip()
        if not text:
            rendered_lines.append("")
            continue
        rendered_lines.extend(
            textwrap.wrap(
                text,
                width=inner_width - 2,
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [""]
        )

    for line in rendered_lines:
        print(f"│ {line:<{inner_width - 2}} │")
    print("└" + "─" * inner_width + "┘")
