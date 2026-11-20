"""Prompt contract for source-bound atomic claim extraction."""

from __future__ import annotations

from .registry import PromptSpec, register_prompt_spec


CLAIM_EXTRACTOR_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="claim_extractor",
        version="1.0.0",
        model_role="claim_extractor",
        training_required=True,
        text="""Bạn tách các mệnh đề pháp lý nguyên tử từ đúng một nguồn cho đúng một Requirement.

Mỗi mệnh đề phải:
- trực tiếp phục vụ toàn bộ hoặc một thành phần của Requirement;
- diễn đạt đúng nội dung được nguồn nêu, giữ chủ thể, hành vi, đối tượng, điều kiện, ngoại lệ, chiều khẳng định/phủ định, thời hạn, ngưỡng và hệ quả;
- chỉ chứa một quy tắc hoặc kết quả có thể kiểm tra độc lập;
- kèm `source_quote` là đoạn liên tục có thật trong nguồn và đủ để kiểm chứng proposition.

Không áp dụng quy phạm vào Facts, không viết câu trả lời, không thêm điều kiện hoặc hệ quả từ kiến thức ngoài nguồn, không đổi quan hệ pháp lý để giống Requirement. Không tạo ID hoặc citation. Nếu nguồn không có mệnh đề trực tiếp hoặc thành phần cần thiết cho Requirement, trả mảng rỗng.

Chỉ trả một JSON object theo schema được cung cấp.""",
    )
)


CLAIM_EXTRACTOR_RETRY_INSTRUCTION = """Kết quả trước không đạt output contract. Chỉ trả các proposition có source_quote thật trong nguồn; không tạo ID, không thêm kiến thức và không đổi Requirement."""


def claim_extractor_schema(max_claims: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "maxItems": max_claims,
                "items": {
                    "type": "object",
                    "properties": {
                        "proposition": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 600,
                        },
                        "source_quote": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1200,
                        },
                    },
                    "required": ["proposition", "source_quote"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["claims"],
        "additionalProperties": False,
    }


__all__ = [
    "CLAIM_EXTRACTOR_RETRY_INSTRUCTION",
    "CLAIM_EXTRACTOR_SPEC",
    "claim_extractor_schema",
]
