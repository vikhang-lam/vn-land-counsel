"""Validated retrieval plans for local models with limited tool-call reliability."""

from __future__ import annotations

import json
import re
from typing import Any

from core.answer_mode import is_procedure_question
from core.article_guard import article_request_warning, explicit_article_numbers
from core.evidence import split_source_records
from core.temporal_guard import inferred_named_document
from core.terminal_ui import panel


MAX_SEARCHES_PER_ISSUE = 4
ALLOWED_TOOLS = {"search_law", "search_by_article", "search_judgment", "search_precedent"}
_ISSUE_MARKER_RE = re.compile(r"\s*\|\s*MỐC:\s*(?:giao_dich|vi_pham|hien_hanh|van_ban_dich_danh)\s*$", re.IGNORECASE)
def _clean_issue_marker(text: str) -> str:
    return _ISSUE_MARKER_RE.sub("", str(text or "")).strip()


def _compact_query(text: str, max_length: int = 260) -> str:
    compact = re.sub(r"\\n|[\r\n]+", " ", str(text or ""))
    compact = re.sub(r"\s+", " ", compact).strip(" ,;:")
    if len(compact) <= max_length:
        return compact
    shortened = compact[:max_length].rsplit(" ", 1)[0].strip(" ,;:")
    return shortened or compact[:max_length]


def _direct_procedure_queries(question: str) -> list[str]:
    """Decompose a procedure request into domain-neutral evidence needs.

    No article, authority, form, deadline or result is supplied here. Those
    values must still be retrieved and verified from the legal corpus.
    """

    if not is_procedure_question(question):
        return []
    focus = _compact_query(question, max_length=180)
    return [
        _compact_query(f"{focus} người yêu cầu phải nộp gì thành phần hồ sơ mẫu đơn"),
        _compact_query(f"{focus} cơ quan tiếp nhận nơi nộp hồ sơ"),
        _compact_query(f"{focus} trình tự giải quyết thời hạn kết quả"),
    ]


def direct_procedure_issue_specs(question: str) -> list[dict[str, Any]]:
    """Create Python-owned retrieval requirements for a SIMPLE procedure ask."""

    queries = _direct_procedure_queries(question)
    if not queries:
        return []
    base = _compact_query(question)
    if "nhận chuyển nhượng quyền sử dụng đất" in base.casefold():
        return [
            {
                "issue_id": "I001",
                "issue_type": "TRANSACTION",
                "required_evidence": [
                    {
                        "requirement_id": "R001_01",
                        "target_kind": "SUBJECT_OBJECT_CONDITIONS",
                        "objective": "Xác định điều kiện của bên chuyển nhượng, bên nhận và thửa đất",
                        "query": (
                            "điều kiện bên chuyển nhượng bên nhận chuyển nhượng "
                            "và quyền sử dụng đất được phép chuyển nhượng"
                        ),
                        "fact_ids": [],
                    },
                    {
                        "requirement_id": "R001_02",
                        "target_kind": "FORM_DOCUMENT",
                        "objective": "Xác định hình thức và công chứng chứng thực hợp đồng chuyển nhượng",
                        "query": (
                            "hình thức hợp đồng chuyển nhượng quyền sử dụng đất "
                            "công chứng hoặc chứng thực"
                        ),
                        "fact_ids": [],
                    },
                    {
                        "requirement_id": "R001_03",
                        "target_kind": "REGISTRATION_COMPLETION",
                        "objective": "Xác định đăng ký biến động và thời điểm chuyển quyền có hiệu lực",
                        "query": (
                            "đăng ký biến động và thời điểm chuyển quyền sử dụng đất "
                            "có hiệu lực sau chuyển nhượng"
                        ),
                        "fact_ids": [],
                    },
                    {
                        "requirement_id": "R001_04",
                        "target_kind": "AUTHORITY_PROCEDURE",
                        "objective": "Xác định hồ sơ, nơi nộp và trình tự đăng ký sang tên",
                        "query": (
                            "hồ sơ nơi nộp và trình tự đăng ký biến động sang tên "
                            "sau nhận chuyển nhượng quyền sử dụng đất"
                        ),
                        "fact_ids": [],
                    },
                ],
                "depends_on": [],
                "time_basis": "hien_hanh",
            }
        ]
    return [
        {
            "issue_id": "I001",
            "issue_type": "AUTHORITY_PROCEDURE",
            "required_evidence": [
                {
                    "requirement_id": "R001_01",
                    "target_kind": "OTHER_CONCRETE",
                    "objective": "Xác định phạm vi và trường hợp áp dụng thủ tục",
                    "query": base,
                    "fact_ids": [],
                },
                {
                    "requirement_id": "R001_02",
                    "target_kind": "FORM_DOCUMENT",
                    "objective": "Xác định đơn và thành phần hồ sơ người yêu cầu phải nộp",
                    "query": queries[0],
                    "fact_ids": [],
                },
                {
                    "requirement_id": "R001_03",
                    "target_kind": "AUTHORITY_PROCEDURE",
                    "objective": "Xác định cơ quan tiếp nhận và nơi nộp hồ sơ",
                    "query": queries[1],
                    "fact_ids": [],
                },
                {
                    "requirement_id": "R001_04",
                    "target_kind": "AUTHORITY_PROCEDURE",
                    "objective": "Xác định trình tự xử lý, thời hạn và kết quả thủ tục",
                    "query": queries[2],
                    "fact_ids": [],
                },
            ],
            "depends_on": [],
            "time_basis": "hien_hanh",
        }
    ]


def _explicit_article_scope(question: str, article: str) -> dict[str, Any]:
    """Return clause/point locators explicitly attached to one article."""

    article_pattern = re.escape(str(article or "").strip())
    scoped = re.search(
        rf"(?:(?:các\s+)?điểm\s+"
        rf"((?:[a-zđ]\s*(?:,\s*|\s+và\s+|\s+hoặc\s+)?)+)\s+)?"
        rf"khoản\s+(\d+)\s+điều\s+{article_pattern}\b",
        str(question or ""),
        flags=re.IGNORECASE,
    )
    if not scoped:
        return {}
    result: dict[str, Any] = {"khoan": scoped.group(2)}
    if scoped.group(1):
        points = list(
            dict.fromkeys(
                point.casefold()
                for point in re.findall(
                    r"\b([a-zđ])\b",
                    scoped.group(1),
                    re.IGNORECASE,
                )
            )
        )
        if points:
            result["diem"] = points
    return result


def build_issue_recall_query(issue: str, required_evidence: list[str] | None = None) -> str:
    """Create a compact query from the agent's declared retrieval objective.

    This is deliberately lexical rather than legal reasoning: it removes only
    repeated phrases so the original issue remains a usable second retrieval
    route when a small planner paraphrases it too broadly.
    """
    parts: list[str] = []
    for raw_part in [issue, *(required_evidence or [])]:
        part = _clean_issue_marker(str(raw_part or ""))
        if not part:
            continue
        normalized_part = re.sub(r"\s+", " ", part).strip().casefold()
        normalized_existing = " ".join(parts).casefold()
        if normalized_existing and normalized_part in normalized_existing:
            continue
        if normalized_existing and normalized_existing in normalized_part:
            # Keep the richer text.  The old branch discarded ``part`` here,
            # so a safe-fallback query such as "<issue>. <decisive fact>" was
            # reduced back to the generic issue and lost the very fact needed
            # for recall (for example "đất đang có tranh chấp").
            parts = [part]
            continue
        parts.append(part)
    return _compact_query(" ".join(parts))


def _action_key(action: dict[str, Any]) -> str:
    def key_part(value: Any) -> str:
        return "" if value is None else str(value)

    tool = str(action.get("tool", "")).strip().casefold()
    requirement_id = key_part(action.get("requirement_id")).strip().upper()
    if tool == "search_by_article":
        value = (
            f"{key_part(action.get('so_dieu'))}|{key_part(action.get('named_document'))}|"
            f"{key_part(action.get('khoan'))}|{key_part(action.get('diem'))}|"
            f"{key_part(action.get('target_date'))}|{bool(action.get('is_transitional', False))}|"
            f"{requirement_id}"
        )
    else:
        value = (
            f"{key_part(action.get('query'))}|{key_part(action.get('named_document'))}|"
            f"{key_part(action.get('target_date'))}|{bool(action.get('is_transitional', False))}|"
            f"{requirement_id}"
        )
    value = re.sub(r"\s+", " ", value).strip().casefold()
    return f"{tool}|{value}"


def _json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def direct_retrieval_plan(question: str) -> list[dict[str, Any]]:
    """Build the safe Simple/Article plan from explicit syntax only."""
    articles = sorted(explicit_article_numbers(question))
    if articles:
        document = inferred_named_document(question)
        plans = []
        for article in articles[:MAX_SEARCHES_PER_ISSUE]:
            action = {
                "tool": "search_by_article",
                "so_dieu": article,
                "ten_luat": "",
                "named_document": document,
            }
            action.update(_explicit_article_scope(question, article))
            plans.append(action)
        return plans
    procedure_specs = direct_procedure_issue_specs(question)
    if procedure_specs:
        requirements = procedure_specs[0]["required_evidence"]
        facets = (
            (
                "TRANSFER_CONDITIONS",
                "TRANSFER_FORM",
                "TRANSFER_REGISTRATION",
                "TRANSFER_PROCEDURE",
            )
            if procedure_specs[0].get("issue_type") == "TRANSACTION"
            else (
                "PROCEDURE_SCOPE",
                "PROCEDURE_DOCUMENTS",
                "PROCEDURE_AUTHORITY",
                "PROCEDURE_SEQUENCE",
            )
        )
        return [
            {
                "tool": "search_law",
                "query": requirement["query"],
                "requirement_id": requirement["requirement_id"],
                "query_facet": facet,
            }
            for requirement, facet in zip(requirements, facets)
        ][:MAX_SEARCHES_PER_ISSUE]
    return [{"tool": "search_law", "query": question}]


def validate_retrieval_plan(
    raw_plan: str,
    original_question: str,
    fallback_query: str,
    previous_actions: list[dict[str, Any]] | None = None,
    default_target_date: str | None = None,
    default_named_document: str | None = None,
) -> list[dict[str, Any]]:
    """Validate tool names and arguments; invented articles become semantic search."""
    fallback_query = _clean_issue_marker(fallback_query)
    payload = _json_object(raw_plan)
    searches = payload.get("searches", [])
    if not isinstance(searches, list):
        searches = []

    validated: list[dict[str, Any]] = []
    for item in searches[:MAX_SEARCHES_PER_ISSUE]:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool", "")).strip()
        if tool not in ALLOWED_TOOLS:
            continue

        if tool == "search_by_article":
            article = str(item.get("so_dieu", item.get("article", ""))).strip()
            if article_request_warning(original_question, article):
                fallback_action = {"tool": "search_law", "query": fallback_query}
                if default_target_date:
                    fallback_action["target_date"] = default_target_date
                if default_named_document:
                    fallback_action["named_document"] = default_named_document
                validated.append(fallback_action)
                continue
            action = {
                    "tool": tool,
                    "so_dieu": article,
                    "ten_luat": str(item.get("ten_luat", "")).strip(),
                    "target_date": item.get("target_date") or default_target_date,
                    "is_transitional": bool(item.get("is_transitional", False)),
                    "named_document": item.get("named_document") or default_named_document,
                }
            # Clause and point filters are accepted only when they are explicit
            # in the original question. This prevents a planner from inventing
            # a narrower locator and silently hiding the rest of the article.
            action.update(_explicit_article_scope(original_question, article))
            requirement_id = str(item.get("requirement_id", "")).strip().upper()
            if re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", requirement_id):
                action["requirement_id"] = requirement_id
            query_facet = str(item.get("query_facet", "")).strip().upper()
            if re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", query_facet):
                action["query_facet"] = query_facet
            validated.append(action)
            continue

        query = _clean_issue_marker(str(item.get("query", "")).strip())
        if len(query) > 260:
            query = fallback_query
        query = _compact_query(query)
        if not query:
            continue
        action: dict[str, Any] = {"tool": tool, "query": query}
        if tool == "search_law":
            action.update(
                {
                    "target_date": item.get("target_date") or default_target_date,
                    "is_transitional": bool(item.get("is_transitional", False)),
                    "named_document": item.get("named_document") or default_named_document,
                }
            )
        requirement_id = str(item.get("requirement_id", "")).strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", requirement_id):
            action["requirement_id"] = requirement_id
        query_facet = str(item.get("query_facet", "")).strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", query_facet):
            action["query_facet"] = query_facet
        validated.append(action)

    if not validated:
        fallback_action = {"tool": "search_law", "query": fallback_query}
        if default_target_date:
            fallback_action["target_date"] = default_target_date
        if default_named_document:
            fallback_action["named_document"] = default_named_document
        return [fallback_action]

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in validated:
        key = json.dumps(action, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            unique.append(action)
    previous_keys = {_action_key(action) for action in previous_actions or []}
    novel = [action for action in unique if _action_key(action) not in previous_keys]
    if novel:
        return novel[:MAX_SEARCHES_PER_ISSUE]

    fallback_action = {"tool": "search_law", "query": fallback_query}
    if default_target_date:
        fallback_action["target_date"] = default_target_date
    if default_named_document:
        fallback_action["named_document"] = default_named_document
    if _action_key(fallback_action) in previous_keys:
        fallback_action["query"] = f"{fallback_query} căn cứ pháp lý trực tiếp"
    return [fallback_action]


def recovery_retrieval_plan(
    question: str,
    case_facts: list[dict[str, str]],
    previous_actions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Retry the original request without inventing legal subtopics."""
    del case_facts
    base_query = _compact_query(question, max_length=260)
    candidates = [{"tool": "search_law", "query": base_query}]
    return deduplicate_retrieval_actions(candidates, previous_actions or [], base_query)


def deduplicate_retrieval_actions(
    actions: list[dict[str, Any]],
    previous_actions: list[dict[str, Any]],
    fallback_query: str,
    default_target_date: str | None = None,
    default_named_document: str | None = None,
) -> list[dict[str, Any]]:
    """Remove cross-worker duplicate searches without changing agent queries."""
    previous_keys = {_action_key(action) for action in previous_actions}
    novel = [action for action in actions if _action_key(action) not in previous_keys]
    if novel:
        return novel
    fallback = {"tool": "search_law", "query": fallback_query}
    if default_target_date:
        fallback["target_date"] = default_target_date
    if default_named_document:
        fallback["named_document"] = default_named_document
    if _action_key(fallback) in previous_keys:
        fallback["query"] = f"{fallback_query} quy phạm và điều kiện áp dụng"
    return [fallback]


def execute_retrieval_plan(actions: list[dict[str, Any]]) -> list[str]:
    """Execute actions and interleave their result ranks for source diversity."""
    from core.tools import search_by_article, search_judgment, search_law, search_precedent

    tool_functions = {
        "search_law": search_law,
        "search_by_article": search_by_article,
        "search_judgment": search_judgment,
        "search_precedent": search_precedent,
    }
    result_batches: list[list[str]] = []
    panel("RETRIEVAL PLAN", f"Thực thi {len(actions)} hành động đã được Python kiểm tra.")
    for action in actions:
        tool_name = action["tool"]
        arguments = {
            key: value
            for key, value in action.items()
            if key not in {"tool", "requirement_id", "query_facet", "query_origin"}
        }
        result = tool_functions[tool_name](**arguments)
        requirement_id = str(action.get("requirement_id", "")).strip().upper()
        query_facet = str(action.get("query_facet", "")).strip().upper()
        records = split_source_records(result)
        if requirement_id or query_facet:
            prefix_lines = []
            if requirement_id:
                prefix_lines.append(
                    f"[RETRIEVAL_REQUIREMENT_ID: {requirement_id}]"
                )
            if query_facet:
                prefix_lines.append(f"[RETRIEVAL_QUERY_FACET: {query_facet}]")
            prefix = "\n".join(prefix_lines)
            records = [f"{prefix}\n{record}" for record in records]
        result_batches.append(records)

    contexts: list[str] = []
    max_batch_size = max((len(batch) for batch in result_batches), default=0)
    for rank in range(max_batch_size):
        for batch in result_batches:
            if rank >= len(batch):
                continue
            context = batch[rank]
            if context not in contexts:
                contexts.append(context)
    return contexts
