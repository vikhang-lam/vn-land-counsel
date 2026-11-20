"""Canonical, self-contained contract for the Claim Verifier."""

from __future__ import annotations

import hashlib
import json
from typing import Any


SOURCE_ENTAILMENT_VALUES = ("YES", "NO")
REQUIREMENT_RELEVANCE_VALUES = (
    "DIRECT",
    "COMPONENT_SUPPORT",
    "ADJACENT",
    "WRONG_RELATION",
    "IRRELEVANT",
)

CLAIM_VERIFIER_PROMPT = """Bạn là bộ kiểm chứng mệnh đề cho hệ thống hỗ trợ tư vấn pháp luật.

Chỉ thực hiện hai phép kiểm tra độc lập:
1. SOURCE ENTAILMENT: SOURCE có hỗ trợ toàn bộ CLAIM, đúng chủ thể, hành vi,
   đối tượng, điều kiện, ngoại lệ, chiều khẳng định và phạm vi hay không.
2. REQUIREMENT RELEVANCE: CLAIM có trực tiếp trả lời REQUIREMENT, chỉ hỗ trợ một
   thành phần, chỉ liên quan kế cận, sai quan hệ hay hoàn toàn không liên quan.

Không áp dụng claim vào facts của vụ việc. Không quyết định điều kiện đã xảy ra.
Không dùng kiến thức ngoài SOURCE. Không tự tạo hoặc sửa issue_id,
requirement_id, claim_id hay evidence_id. Chỉ dùng ID có trong input.

source_entailment là YES hoặc NO.
requirement_relevance là DIRECT, COMPONENT_SUPPORT, ADJACENT,
WRONG_RELATION hoặc IRRELEVANT.

DIRECT đòi hỏi đúng hành vi hoặc kết quả pháp lý trung tâm của requirement, không
chỉ trùng chủ thể, tài sản hay từ khóa. COMPONENT_SUPPORT chỉ dùng khi claim
chứng minh một thành phần thật sự cần thiết của requirement rộng hơn. ADJACENT
là quy phạm cùng miền nhưng điều chỉnh bước, thủ tục hoặc hệ quả kế bên.
WRONG_RELATION là sai chủ thể, đối tượng, hành vi hoặc quan hệ pháp lý.

OUTPUT BẮT BUỘC — chỉ trả đúng một JSON object, không Markdown và không có
văn bản ngoài JSON:
{
  "decisions": [
    {
      "claim_id": "<chép nguyên claim_id từ input>",
      "source_entailment": "<YES hoặc NO>",
      "requirement_relevance": "<DIRECT, COMPONENT_SUPPORT, ADJACENT, WRONG_RELATION hoặc IRRELEVANT>",
      "grounding_evidence_ids": ["<chép evidence_id gắn với claim từ input>"],
      "reason_codes": ["<mã lý do chữ hoa và dấu gạch dưới>"],
      "reason": "<lý do ngắn gọn dựa trên SOURCE, CLAIM và REQUIREMENT>"
    }
  ]
}

Trả đúng một decision cho mỗi claim, theo đúng thứ tự claim trong input. Không
thêm khóa ngoài cấu trúc trên. Không bỏ claim_id hoặc evidence_id. Không chép
các dấu ngoặc nhọn dạng mẫu; phải thay bằng giá trị grounded từ input."""


CLAIM_VERIFIER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "pattern": "^C[0-9]{3}$",
                    },
                    "source_entailment": {
                        "type": "string",
                        "enum": list(SOURCE_ENTAILMENT_VALUES),
                    },
                    "requirement_relevance": {
                        "type": "string",
                        "enum": list(REQUIREMENT_RELEVANCE_VALUES),
                    },
                    "grounding_evidence_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 3,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "pattern": "^E[0-9]{3}$",
                        },
                    },
                    "reason_codes": {
                        "type": "array",
                        "maxItems": 4,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "pattern": "^[A-Z][A-Z0-9_]{1,63}$",
                        },
                    },
                    "reason": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 360,
                    },
                },
                "required": [
                    "claim_id",
                    "source_entailment",
                    "requirement_relevance",
                    "grounding_evidence_ids",
                    "reason_codes",
                    "reason",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


def contract_hashes() -> dict[str, str]:
    schema_text = json.dumps(
        CLAIM_VERIFIER_JSON_SCHEMA,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "system_prompt_sha256": hashlib.sha256(
            CLAIM_VERIFIER_PROMPT.encode("utf-8")
        ).hexdigest(),
        "json_schema_sha256": hashlib.sha256(
            schema_text.encode("utf-8")
        ).hexdigest(),
    }


def _validate_input_payload(payload: dict[str, Any]) -> None:
    issue_id = payload["issue"]["issue_id"]
    requirement_id = payload["requirement"]["requirement_id"]
    if not issue_id.startswith("I") or not issue_id[1:].isdigit():
        raise ValueError("Claim Verifier issue_id không hợp lệ")
    if not (
        requirement_id.startswith("R")
        and "_" in requirement_id
        and requirement_id[1:4].isdigit()
    ):
        raise ValueError("Claim Verifier requirement_id không hợp lệ")
    if not payload["question"] or not payload["issue"]["text"]:
        raise ValueError("Claim Verifier thiếu question/issue")
    if (
        not payload["requirement"]["objective"]
        or not payload["claims"]
        or not payload["sources"]
    ):
        raise ValueError("Claim Verifier thiếu requirement/claim/source")
    source_ids = {source["evidence_id"] for source in payload["sources"]}
    claim_ids: set[str] = set()
    for claim in payload["claims"]:
        claim_id = claim["claim_id"]
        if (
            not claim_id.startswith("C")
            or not claim_id[1:].isdigit()
            or claim_id in claim_ids
        ):
            raise ValueError("Claim Verifier claim_id không hợp lệ hoặc trùng")
        claim_ids.add(claim_id)
        if not claim["text"] or not claim["evidence_ids"]:
            raise ValueError("Claim Verifier claim thiếu text/evidence_ids")
        if len(claim["evidence_ids"]) > 3:
            raise ValueError("Claim Verifier claim vượt tối đa 3 evidence_ids")
        if not set(claim["evidence_ids"]) <= source_ids:
            raise ValueError("Claim Verifier claim tham chiếu evidence_id lạ")


def build_claim_verifier_input(
    *,
    question: str,
    issue: dict[str, Any],
    requirement: dict[str, Any],
    claims: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "question": str(question or "").strip(),
        "issue": {
            "issue_id": str(issue.get("issue_id", "")).strip().upper(),
            "issue_type": str(
                issue.get("issue_type", "OTHER")
            ).strip().upper(),
            "text": str(
                issue.get("text", issue.get("issue", ""))
            ).strip(),
            "time_basis": str(
                issue.get("time_basis", "hien_hanh")
            ).strip().lower(),
        },
        "requirement": {
            "requirement_id": str(
                requirement.get("requirement_id", "")
            ).strip().upper(),
            "target_kind": str(
                requirement.get("target_kind", "OTHER_CONCRETE")
            ).strip().upper(),
            "objective": str(requirement.get("objective", "")).strip(),
            "query": str(requirement.get("query", "")).strip(),
        },
        "claims": [
            {
                "claim_id": str(
                    claim.get("claim_id", "")
                ).strip().upper(),
                "text": str(
                    claim.get("text", claim.get("claim", ""))
                ).strip(),
                "evidence_ids": [
                    str(value).strip().upper()
                    for value in claim.get("evidence_ids", [])
                    if str(value).strip()
                ],
            }
            for claim in claims
        ],
        "sources": [
            {
                "evidence_id": str(
                    source.get("evidence_id", "")
                ).strip().upper(),
                "citation": str(source.get("citation", "")).strip(),
                "text": str(source.get("text", "")).strip(),
                "temporal_status": str(
                    source.get("temporal_status", "UNKNOWN")
                ).strip().upper(),
            }
            for source in sources
        ],
    }
    _validate_input_payload(payload)
    return payload


def render_claim_verifier_input(**kwargs: Any) -> str:
    return json.dumps(
        build_claim_verifier_input(**kwargs),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def validate_claim_verifier_output(
    raw: str | dict[str, Any],
    *,
    expected_claim_evidence: dict[str, list[str]],
) -> dict[str, Any]:
    payload = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict) or set(payload) != {"decisions"}:
        raise ValueError("Claim Verifier output phải chỉ có decisions")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("Claim Verifier decisions rỗng")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    required_keys = {
        "claim_id",
        "source_entailment",
        "requirement_relevance",
        "grounding_evidence_ids",
        "reason_codes",
        "reason",
    }
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != required_keys:
            raise ValueError("Claim Verifier decision sai keys")
        claim_id = str(decision["claim_id"]).strip().upper()
        if claim_id not in expected_claim_evidence or claim_id in seen:
            raise ValueError("Claim Verifier claim_id lạ hoặc trùng")
        seen.add(claim_id)
        entailment = str(decision["source_entailment"]).strip().upper()
        relevance = str(decision["requirement_relevance"]).strip().upper()
        if entailment not in SOURCE_ENTAILMENT_VALUES:
            raise ValueError("Claim Verifier source_entailment sai enum")
        if relevance not in REQUIREMENT_RELEVANCE_VALUES:
            raise ValueError("Claim Verifier requirement_relevance sai enum")
        evidence_ids = [
            str(value).strip().upper()
            for value in decision["grounding_evidence_ids"]
        ]
        if (
            not evidence_ids
            or not set(evidence_ids)
            <= set(expected_claim_evidence[claim_id])
        ):
            raise ValueError(
                "Claim Verifier grounding_evidence_ids vượt claim provenance"
            )
        reason_codes = [
            str(value).strip().upper()
            for value in decision["reason_codes"]
        ]
        if len(reason_codes) != len(set(reason_codes)):
            raise ValueError("Claim Verifier reason_codes trùng")
        reason = str(decision["reason"]).strip()
        if not reason:
            raise ValueError("Claim Verifier thiếu reason")
        validated.append(
            {
                "claim_id": claim_id,
                "source_entailment": entailment,
                "requirement_relevance": relevance,
                "grounding_evidence_ids": evidence_ids,
                "reason_codes": reason_codes,
                "reason": reason[:360],
            }
        )
    if seen != set(expected_claim_evidence):
        raise ValueError("Claim Verifier thiếu decision cho claim")
    return {"decisions": validated}


def complete_claim_verifier(
    client: Any,
    *,
    model: str,
    question: str,
    issue: dict[str, Any],
    requirement: dict[str, Any],
    claims: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = render_claim_verifier_input(
        question=question,
        issue=issue,
        requirement=requirement,
        claims=claims,
        sources=sources,
    )
    response = client.complete(
        prompt,
        model=model,
        system_prompt=CLAIM_VERIFIER_PROMPT,
        temperature=0.0,
        max_tokens=900,
        json_schema=CLAIM_VERIFIER_JSON_SCHEMA,
    )
    expected = {
        str(claim.get("claim_id", "")).strip().upper(): [
            str(value).strip().upper()
            for value in claim.get("evidence_ids", [])
            if str(value).strip()
        ]
        for claim in claims
    }
    return validate_claim_verifier_output(
        response.text,
        expected_claim_evidence=expected,
    )


__all__ = [
    "CLAIM_VERIFIER_JSON_SCHEMA",
    "CLAIM_VERIFIER_PROMPT",
    "REQUIREMENT_RELEVANCE_VALUES",
    "SOURCE_ENTAILMENT_VALUES",
    "build_claim_verifier_input",
    "complete_claim_verifier",
    "contract_hashes",
    "render_claim_verifier_input",
    "validate_claim_verifier_output",
]
