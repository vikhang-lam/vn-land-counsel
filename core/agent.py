"""Public entry points for the clean submission pipeline."""

from __future__ import annotations

from typing import Any


def answer_question(
    question: str,
    client: Any = None,
    history: str = "",
    pipeline: str = "clean",
    **_: Any,
):
    """Run the only pipeline shipped in this submission."""

    del history, pipeline
    from core.pipeline import Pipeline

    query = str(question or "").strip()
    if not query:
        raise ValueError("Câu hỏi không được để trống.")
    if client is None:
        from core.config import get_active_settings
        from core.llm import create_llm_client

        settings = get_active_settings()
        client = create_llm_client(settings.provider, model=settings.base_model)
        client.ensure_available()
    state = Pipeline().run(client, query)
    return state.answer, list(state.retrieved_contexts)


def run_agent(client: Any = None) -> None:
    from core.terminal_chat import run_terminal_chat

    run_terminal_chat(client)


__all__ = ["answer_question", "run_agent"]
