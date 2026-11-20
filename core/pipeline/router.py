"""Stage 1 - phân loại yêu cầu người dùng."""

from __future__ import annotations

from dataclasses import dataclass

from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.llm import LocalLLMClient

from .contracts import Route
from .prompts import (
    ROUTER_JSON_SCHEMA,
    ROUTER_PROMPT_SPEC,
    SCOPE_REVIEW_JSON_SCHEMA,
    SCOPE_REVIEW_PROMPT_SPEC,
)
from .routing_validation import (
    parse_scope_review,
    syntax_proven_route,
    validate_router_decision,
)


@dataclass(frozen=True, slots=True)
class RouterResult:
    route: Route
    source: str
    raw_output: str = ""
    scope_review_output: str = ""


class RouterStage:
    """Ưu tiên rule chắc chắn; chỉ gọi model khi rule chưa kết luận được."""

    def run(self, client: LocalLLMClient, question: str) -> RouterResult:
        query = str(question or "").strip()
        if not query:
            raise ValueError("Router không nhận câu hỏi rỗng.")

        deterministic = syntax_proven_route(query)
        if deterministic:
            result = RouterResult(
                route=deterministic,
                source="DETERMINISTIC_POLICY",
            )
            debug_dump(
                "PIPELINE :: ROUTER :: DETERMINISTIC",
                {"query": query, "route": result.route.value},
            )
            return result

        settings = get_active_settings()
        response = client.complete(
            query,
            model=settings.router_model,
            system_prompt=ROUTER_PROMPT_SPEC.text,
            temperature=0.0,
            max_tokens=64,
            json_mode=True,
            json_schema=ROUTER_JSON_SCHEMA,
        )
        route = validate_router_decision(query, response.text)
        if route is not Route.OUT_OF_SCOPE:
            result = RouterResult(
                route=route,
                source="ROUTER_MODEL",
                raw_output=response.text,
            )
            debug_dump(
                "PIPELINE :: ROUTER :: MODEL",
                {
                    "query": query,
                    "raw_output": response.text,
                    "route": result.route.value,
                },
            )
            return result

        # OUT_OF_SCOPE là quyết định có rủi ro từ chối người dùng. Stage thực
        # hiện một lượt review độc lập giống contract production hiện hành.
        scope_response = client.complete(
            query,
            model=settings.router_model,
            system_prompt=SCOPE_REVIEW_PROMPT_SPEC.text,
            temperature=0.0,
            max_tokens=32,
            json_mode=True,
            json_schema=SCOPE_REVIEW_JSON_SCHEMA,
        )
        in_scope = parse_scope_review(scope_response.text)
        final_route = (
            Route.OUT_OF_SCOPE
            if in_scope is False
            else Route.SIMPLE
        )
        result = RouterResult(
            route=final_route,
            source="SCOPE_REVIEW",
            raw_output=response.text,
            scope_review_output=scope_response.text,
        )
        debug_dump(
            "PIPELINE :: ROUTER :: SCOPE REVIEW",
            {
                "query": query,
                "router_output": response.text,
                "scope_output": scope_response.text,
                "route": final_route.value,
            },
        )
        return result


__all__ = ["RouterResult", "RouterStage"]
