"""Các contract dữ liệu chuẩn của pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from copy import deepcopy
import json
import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .answer_contract import AnswerDraftResult, PublishedAnswer
    from .claim_contract import ClaimExtractionResult
    from .condition_contract import ConditionApplicationResult
    from .evidence_contract import EvidenceSelectionResult
    from .verification_contract import ClaimVerificationResult

from core.evidence import (
    retrieval_query_facet,
    retrieval_rerank_score,
    retrieval_requirement_id,
    source_citation,
    strip_retrieval_metadata,
)

ALLOWED_RETRIEVAL_TOOLS = {
    "search_law",
    "search_by_article",
    "search_judgment",
    "search_precedent",
}


_RETRIEVAL_REQUIREMENT_METADATA_RE = re.compile(
    r"(?mi)^[ \t]*\[RETRIEVAL_REQUIREMENT_ID:\s*"
    r"[A-Z][A-Z0-9_]{1,63}\s*\][ \t]*\r?\n?"
)


class Route(str, Enum):
    """Năm nhánh xử lý công khai của Router."""

    INTAKE = "INTAKE"
    ARTICLE = "ARTICLE"
    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"

    @classmethod
    def parse(cls, value: str) -> "Route":
        try:
            return cls(str(value or "").strip().upper())
        except ValueError as error:
            raise ValueError(f"Route không hợp lệ: {value!r}") from error


@dataclass(frozen=True, slots=True)
class FactRecord:
    """Một dữ kiện đã được Python xác nhận bằng trích dẫn nguyên văn."""

    fact_id: str
    category: str
    value: str
    source_quote: str

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "FactRecord":
        fact_id = str(payload.get("fact_id", "")).strip().upper()
        category = str(payload.get("category", "OTHER")).strip().upper()
        value = str(payload.get("value", "")).strip()
        source_quote = str(payload.get("source_quote", "")).strip()
        if not fact_id or not value or not source_quote:
            raise ValueError("Fact thiếu ID, value hoặc source_quote.")
        return cls(
            fact_id=fact_id,
            category=category,
            value=value,
            source_quote=source_quote,
        )

    def to_dict(self) -> dict[str, str]:
        """Giữ đúng shape mà các stage previous đang sử dụng."""

        return {
            "fact_id": self.fact_id,
            "category": self.category,
            "value": self.value,
            "source_quote": self.source_quote,
        }


@dataclass(frozen=True, slots=True)
class RequirementRecord:
    """Requirement do Planner tạo, giữ nguyên payload để bảo toàn tương thích."""

    requirement_id: str
    target_kind: str
    objective: str
    fact_ids: tuple[str, ...]
    query: str
    raw: dict[str, Any]

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "RequirementRecord":
        requirement_id = str(payload.get("requirement_id", "")).strip().upper()
        target_kind = str(payload.get("target_kind", "OTHER_CONCRETE")).strip().upper()
        objective = str(payload.get("objective", "")).strip()
        query = str(payload.get("query", "")).strip()
        fact_ids = tuple(
            str(fact_id).strip().upper()
            for fact_id in payload.get("fact_ids", [])
            if str(fact_id).strip()
        )
        if not requirement_id or not objective or not query:
            raise ValueError("Requirement thiếu ID, objective hoặc query.")
        if not fact_ids:
            raise ValueError(f"Requirement {requirement_id} không liên kết Fact.")
        return cls(
            requirement_id=requirement_id,
            target_kind=target_kind,
            objective=objective,
            fact_ids=fact_ids,
            query=query,
            raw=deepcopy(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.raw)


@dataclass(frozen=True, slots=True)
class IssueRecord:
    """Một vấn đề pháp lý cùng các Requirement thuộc vấn đề đó."""

    issue_id: str
    display_text: str
    issue_type: str
    time_basis: str
    requirements: tuple[RequirementRecord, ...]
    depends_on: tuple[str, ...]
    raw: dict[str, Any]

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any],
        display_text: str,
    ) -> "IssueRecord":
        issue_id = str(payload.get("issue_id", "")).strip().upper()
        issue_type = str(payload.get("issue_type", "OTHER")).strip().upper()
        time_basis = str(payload.get("time_basis", "hien_hanh")).strip()
        requirements = tuple(
            RequirementRecord.from_mapping(requirement)
            for requirement in payload.get("required_evidence", [])
            if isinstance(requirement, dict)
        )
        depends_on = tuple(
            str(parent).strip().upper()
            for parent in payload.get("depends_on", [])
            if str(parent).strip()
        )
        if not issue_id or not display_text.strip() or not requirements:
            raise ValueError("Issue thiếu ID, nội dung hoặc Requirement.")
        return cls(
            issue_id=issue_id,
            display_text=display_text,
            issue_type=issue_type,
            time_basis=time_basis,
            requirements=requirements,
            depends_on=depends_on,
            raw=deepcopy(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.raw)


@dataclass(frozen=True, slots=True)
class PlanningResult:
    """Kết quả Planner đã được đóng contract nhưng chưa đổi nội dung."""

    issue_texts: tuple[str, ...]
    issues: tuple[IssueRecord, ...]
    temporal_context: str
    temporal_payload: dict[str, Any]

    @classmethod
    def from_payload(
        cls,
        issue_texts: list[str],
        temporal_context: str,
    ) -> "PlanningResult":
        try:
            payload = json.loads(temporal_context)
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError("Temporal Context của Planner không phải JSON hợp lệ.") from error
        specs = payload.get("issue_specs", []) if isinstance(payload, dict) else []
        if not isinstance(specs, list) or len(specs) != len(issue_texts):
            raise ValueError("Số Issue và issue_specs của Planner không khớp.")
        issues = tuple(
            IssueRecord.from_mapping(spec, issue_texts[index])
            for index, spec in enumerate(specs)
            if isinstance(spec, dict)
        )
        if len(issues) != len(issue_texts):
            raise ValueError("Planner có issue_spec không hợp lệ.")
        return cls(
            issue_texts=tuple(issue_texts),
            issues=issues,
            temporal_context=temporal_context,
            temporal_payload=deepcopy(payload),
        )

    @property
    def requirements(self) -> tuple[RequirementRecord, ...]:
        return tuple(
            requirement
            for issue in self.issues
            for requirement in issue.requirements
        )

    def issue_text_list(self) -> list[str]:
        return list(self.issue_texts)

    def issue_spec_payloads(self) -> list[dict[str, Any]]:
        return [issue.to_dict() for issue in self.issues]


@dataclass(frozen=True, slots=True)
class RetrievalActionRecord:
    """Một lần gọi công cụ truy xuất đã được Python kiểm tra."""

    action_id: str
    issue_id: str
    tool: str
    requirement_id: str
    reported_requirement_id: str
    id_reconciled: bool
    query_facet: str
    query_text: str
    raw: dict[str, Any]

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any],
        *,
        action_id: str,
        issue_id: str,
        requirement_id: str,
    ) -> "RetrievalActionRecord":
        """Đóng action vào Requirement của lượt gọi, không tin ID do model trả."""

        tool = str(payload.get("tool", "")).strip()
        if tool not in ALLOWED_RETRIEVAL_TOOLS:
            raise ValueError(f"Retrieval action dùng tool không hợp lệ: {tool!r}")
        canonical_requirement_id = str(requirement_id or "").strip().upper()
        if not re.fullmatch(r"R\d{3}_\d{2}", canonical_requirement_id):
            raise ValueError(
                f"Retrieval action thiếu Requirement do Python cấp: "
                f"{canonical_requirement_id or '<trống>'}"
            )
        reported_requirement_id = str(
            payload.get("requirement_id", "")
        ).strip().upper()
        query_text = str(
            payload.get("query") or payload.get("so_dieu") or ""
        ).strip()
        if not query_text:
            raise ValueError("Retrieval action thiếu query hoặc số Điều.")
        canonical_raw = deepcopy(payload)
        canonical_raw["requirement_id"] = canonical_requirement_id
        return cls(
            action_id=action_id,
            issue_id=issue_id,
            tool=tool,
            requirement_id=canonical_requirement_id,
            reported_requirement_id=reported_requirement_id,
            id_reconciled=reported_requirement_id != canonical_requirement_id,
            query_facet=str(payload.get("query_facet", "")).strip().upper(),
            query_text=query_text,
            raw=canonical_raw,
        )

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.raw)


@dataclass(frozen=True, slots=True)
class RetrievedContextRecord:
    """Một context truy xuất cùng metadata được tách từ phần đầu bản ghi."""

    context_id: str
    issue_id: str
    requirement_id: str
    reported_requirement_id: str
    id_reconciled: bool
    group_id: str
    action_id: str
    origin: str
    parent_context_id: str
    scope_document: str
    scope_article: str
    query_facet: str
    rerank_score: float | None
    citation: str
    raw_text: str

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        context_id: str,
        issue_id: str,
        requirement_id: str,
        group_id: str = "",
        action_id: str = "",
        origin: str = "PRIMARY",
        parent_context_id: str = "",
        scope_document: str = "",
        scope_article: str = "",
    ) -> "RetrievedContextRecord":
        source_text = str(text or "").strip()
        if not source_text:
            raise ValueError("Context truy xuất rỗng.")
        canonical_requirement_id = str(requirement_id or "").strip().upper()
        if not re.fullmatch(r"R\d{3}_\d{2}", canonical_requirement_id):
            raise ValueError(
                f"Context thiếu Requirement do Python cấp: "
                f"{canonical_requirement_id or '<trống>'}"
            )
        canonical_group_id = str(group_id or "").strip().upper()
        if canonical_group_id and not re.fullmatch(r"G\d{4}", canonical_group_id):
            raise ValueError(f"Context có group_id không hợp lệ: {canonical_group_id}")
        canonical_action_id = str(action_id or "").strip().upper()
        if canonical_action_id and not re.fullmatch(r"A\d{3}", canonical_action_id):
            raise ValueError(f"Context có action_id không hợp lệ: {canonical_action_id}")
        canonical_origin = str(origin or "PRIMARY").strip().upper()
        if canonical_origin not in {
            "PRIMARY", "QUERY_EXPANSION", "CROSS_REFERENCE", "RECOVERY"
        }:
            raise ValueError(f"Context có origin không hợp lệ: {canonical_origin}")
        canonical_parent_id = str(parent_context_id or "").strip().upper()
        if canonical_parent_id and not re.fullmatch(r"RC\d{4}", canonical_parent_id):
            raise ValueError(
                f"Context có parent_context_id không hợp lệ: {canonical_parent_id}"
            )
        reported_requirement_id = retrieval_requirement_id(source_text)
        source_without_reported_id = _RETRIEVAL_REQUIREMENT_METADATA_RE.sub(
            "",
            source_text,
        ).strip()
        raw_text = (
            f"[RETRIEVAL_REQUIREMENT_ID: {canonical_requirement_id}]\n"
            f"{source_without_reported_id}"
        ).strip()
        return cls(
            context_id=context_id,
            issue_id=issue_id,
            requirement_id=canonical_requirement_id,
            reported_requirement_id=reported_requirement_id,
            id_reconciled=reported_requirement_id != canonical_requirement_id,
            group_id=canonical_group_id,
            action_id=canonical_action_id,
            origin=canonical_origin,
            parent_context_id=canonical_parent_id,
            scope_document=str(scope_document or "").strip(),
            scope_article=str(scope_article or "").strip(),
            query_facet=retrieval_query_facet(raw_text),
            rerank_score=retrieval_rerank_score(raw_text),
            citation=source_citation(strip_retrieval_metadata(raw_text)),
            raw_text=raw_text,
        )


@dataclass(frozen=True, slots=True)
class IssueRetrievalResult:
    """Kết quả truy xuất riêng của một Issue."""

    issue_id: str
    contexts: tuple[RetrievedContextRecord, ...]
    actions: tuple[RetrievalActionRecord, ...]

    def context_texts(self) -> list[str]:
        return [context.raw_text for context in self.contexts]

    def action_payloads(self) -> list[dict[str, Any]]:
        return [action.to_dict() for action in self.actions]


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Toàn bộ ứng viên truy xuất trước bước chọn và kiểm chứng chứng cứ."""

    issues: tuple[IssueRetrievalResult, ...]

    @property
    def actions(self) -> tuple[RetrievalActionRecord, ...]:
        return tuple(action for issue in self.issues for action in issue.actions)

    @property
    def contexts(self) -> tuple[RetrievedContextRecord, ...]:
        return tuple(context for issue in self.issues for context in issue.contexts)

    def action_payloads(self) -> list[dict[str, Any]]:
        return [action.to_dict() for action in self.actions]

    def context_texts(self) -> list[str]:
        # Previous raw_contexts loại trùng nhưng giữ thứ tự xuất hiện đầu tiên.
        return list(dict.fromkeys(context.raw_text for context in self.contexts))

    def issue_context_texts(self) -> dict[int, list[str]]:
        return {
            index: issue.context_texts()
            for index, issue in enumerate(self.issues, 1)
        }


@dataclass(slots=True)
class PipelineState:
    """Trạng thái duy nhất được truyền giữa các stage của pipeline."""

    question: str
    route: Route | None = None
    facts: list[FactRecord] = field(default_factory=list)
    planning: PlanningResult | None = None
    retrieval: RetrievalResult | None = None
    evidence_selection: EvidenceSelectionResult | None = None
    claim_extraction: ClaimExtractionResult | None = None
    claim_verification: ClaimVerificationResult | None = None
    condition_application: ConditionApplicationResult | None = None
    answer_draft: AnswerDraftResult | None = None
    publication: PublishedAnswer | None = None
    verified_claims: list[dict[str, Any]] = field(default_factory=list)
    condition_results: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    retrieved_contexts: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def fact_payloads(self) -> list[dict[str, str]]:
        return [fact.to_dict() for fact in self.facts]

    def issue_spec_payloads(self) -> list[dict[str, Any]]:
        return self.planning.issue_spec_payloads() if self.planning else []

    def retrieval_action_payloads(self) -> list[dict[str, Any]]:
        return self.retrieval.action_payloads() if self.retrieval else []

    def context_texts(self) -> list[str]:
        return self.retrieval.context_texts() if self.retrieval else []
