"""Terminal interface for the clean submission pipeline."""

from __future__ import annotations

import os
from typing import Any

from core.config import AgentSettings
from core.debug_trace import debug_enabled


def _print_banner(client: Any, settings: AgentSettings) -> None:
    print("=" * 72)
    print("HỆ THỐNG HỖ TRỢ TƯ VẤN PHÁP LUẬT ĐẤT ĐAI VÀ TRANH CHẤP")
    print("DỰA TRÊN AGENTIC RAG (VN LAND COUNSEL)")
    print(
        f"LLM provider: {getattr(client, 'provider', settings.provider)} "
        f"| Endpoint: {client.base_url} | Profile: {settings.profile}"
    )
    print(
        f"Router: {settings.router_model}\n"
        f"Fact: {settings.fact_model}\n"
        f"Planner: {settings.planner_model}\n"
        f"Planner Full Revise: {settings.planner_full_revise_model}\n"
        f"Temporal: {settings.decomposer_model}\n"
        f"Evidence/Answer: {settings.adjudicator_model}\n"
        f"Claim Verifier: {os.getenv('CLAIM_VERIFIER_MODEL', settings.adjudicator_model)}"
    )
    print("Pipeline: clean")
    print(f"Pipeline debug: {'BẬT' if debug_enabled() else 'TẮT'}")
    print("Gõ 'thoát', 'exit' hoặc 'q' để kết thúc.")
    print("=" * 72, flush=True)


def run_terminal_chat(client: Any = None) -> None:
    settings = AgentSettings.from_env()
    if client is None:
        from core.llm import create_llm_client

        client = create_llm_client(settings.provider, model=settings.base_model)
        client.ensure_available()

    _print_banner(client, settings)
    from core.conversation import (
        canonicalize_legal_context,
        depends_on_previous,
        update_conversation_context,
    )
    from core.pipeline import PipelineExecutionError, Pipeline
    from core.question_normalizer import normalize_question_text

    pipeline = Pipeline()
    previous_context = ""
    while True:
        try:
            raw_query = input("\nBạn: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nĐã kết thúc phiên tư vấn.")
            return
        if raw_query.casefold() in {"thoat", "thoát", "exit", "quit", "q"}:
            print("Đã kết thúc phiên tư vấn.")
            return
        if not raw_query:
            continue

        normalized = normalize_question_text(raw_query)
        question = canonicalize_legal_context(normalized, previous_context)
        print("  [Đang xử lý] Đang phân tích yêu cầu...", flush=True)
        try:
            state = pipeline.run(client, question)
            final_text = state.answer or "Chưa tạo được nội dung có căn cứ cho yêu cầu này."
            stages = " → ".join(state.diagnostics.get("completed_stages", []))
        except PipelineExecutionError as error:
            final_text = f"Hệ thống dừng an toàn tại bước {error.stage}: {error.detail}"
            stages = f"FAILED: {error.stage}"
        except Exception as error:
            final_text = f"Hệ thống gặp lỗi trước khi hoàn tất: {error}"
            stages = "FAILED"

        previous_context = (
            update_conversation_context(normalized, previous_context)
            if depends_on_previous(normalized, previous_context)
            else normalized
        )
        print("\n" + "=" * 72)
        print("KẾT QUẢ TƯ VẤN")
        if debug_enabled() and stages:
            print(f"Luồng: {stages}")
        print("=" * 72)
        print(final_text)
        print("=" * 72)


__all__ = ["run_terminal_chat"]
