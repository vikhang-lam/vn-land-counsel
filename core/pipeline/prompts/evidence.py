"""Prompt contracts for semantic evidence classification."""

from __future__ import annotations

from .registry import PromptSpec, register_prompt_spec


EVIDENCE_CLASSIFIER_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="evidence.classifier",
        version="1.1.0",
        model_role="evidence_classifier",
        training_required=True,
        text="""Bạn phân loại mức hỗ trợ của từng nguồn đối với đúng một Requirement.

Chỉ so sánh nội dung Requirement với nội dung nguồn. Không áp dụng quy phạm vào dữ kiện vụ việc, không viết Claim, không trả lời người dùng và không sử dụng kiến thức ngoài nguồn.

Nhãn:
- DIRECT: nguồn trực tiếp quy định đúng quan hệ pháp lý trung tâm, vai trò chủ thể, đối tượng và kết quả mà Requirement cần xác định.
- COMPONENT: nguồn trực tiếp quy định một tiền đề thật sự cần thiết của Requirement nhưng chưa tự giải quyết toàn bộ Requirement.
- ADJACENT: nguồn cùng lĩnh vực nhưng điều chỉnh một quan hệ, bước, chủ thể hoặc hệ quả kế cận.
- IRRELEVANT: nguồn không hỗ trợ Requirement hoặc sai phạm vi pháp lý.

Không đánh giá theo từ khóa chung. Việc cùng nhắc một hành động vật lý, một loại tài sản hoặc từ “chuyển nhượng” không đủ để gắn DIRECT nếu các bên đang ở quan hệ pháp lý khác nhau. Quy định về dự án, hoạt động kinh doanh, quan hệ liền kề hoặc một loại hợp đồng chuyên biệt không trực tiếp hỗ trợ giao dịch dân sự thông thường nếu Requirement không yêu cầu đúng phạm vi đó. COMPONENT phải là tiền đề cần dùng để lập luận, không phải một quy định chỉ có chủ đề gần nhau.

Không yêu cầu nguồn phải chứa dữ kiện của người dùng; việc đối chiếu điều kiện với Facts thuộc stage khác. Chỉ dùng context_id có trong input và trả đúng một decision cho mỗi context_id theo schema.""",
    )
)


EVIDENCE_CLASSIFIER_RETRY_INSTRUCTION = """Kết quả trước không đạt output contract. Trả đúng một decision cho mỗi context_id đã được cấp, không thêm hoặc bỏ ID và không thay đổi nhiệm vụ phân loại."""


def evidence_classifier_schema(max_candidates: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "minItems": 1,
                "maxItems": max_candidates,
                "items": {
                    "type": "object",
                    "properties": {
                        "context_id": {
                            "type": "string",
                            "pattern": "^RC[0-9]{4}$",
                        },
                        "relevance": {
                            "type": "string",
                            "enum": ["DIRECT", "COMPONENT", "ADJACENT", "IRRELEVANT"],
                        },
                        "reason": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 300,
                        },
                    },
                    "required": ["context_id", "relevance", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["decisions"],
        "additionalProperties": False,
    }


__all__ = [
    "EVIDENCE_CLASSIFIER_RETRY_INSTRUCTION",
    "EVIDENCE_CLASSIFIER_SPEC",
    "evidence_classifier_schema",
]
