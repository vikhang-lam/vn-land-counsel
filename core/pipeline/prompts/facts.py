"""Versioned prompt contracts for Fact extraction."""

from __future__ import annotations

from core.prompts.planning import CASE_FACT_EXTRACTOR_PROMPT as FACT_SFT_PROMPT

from .registry import PromptSpec, register_prompt_spec


FACT_EXTRACTOR_BASELINE_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="fact_extractor.baseline",
        version="1.0.0",
        model_role="fact_extractor",
        text=FACT_SFT_PROMPT,
        trained_prompt_sha256=(
            "b24639ea8ad11a23e177f453ad36c431f22b98ca1a38441dcc72b9bd5eaccd37"
        ),
        training_required=True,
    )
)


FACT_EXTRACTOR_CANDIDATE_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="fact_extractor",
        version="2.0.0",
        model_role="fact_extractor",
        training_required=True,
        text="""Bạn là bộ trích xuất dữ kiện của vụ việc.

Chỉ ghi nhận thông tin được người dùng khẳng định hoặc đặt làm tiền đề của tình huống. Không phân tích pháp luật, không đánh giá đúng sai, không tạo vấn đề pháp lý và không trả lời yêu cầu của người dùng.

Với mỗi dữ kiện:
- tách thành một sự kiện hoặc trạng thái có thể hiểu độc lập;
- chép một `quote` liên tục, nguyên văn từ đầu vào;
- giữ đủ chủ thể, hành vi hoặc trạng thái và đối tượng để quote không trở thành mảnh câu mất nghĩa;
- giữ thông tin vật chất có thể phân biệt phạm vi vụ việc như vai trò chủ thể, hành vi, loại đất hoặc tài sản, diện tích, vị trí, giấy tờ, trạng thái thủ tục, thời điểm và số liệu;
- không lặp cùng một dữ kiện bằng nhiều quote gần giống nhau.

Đọc toàn bộ đầu vào. Từ “Hỏi” hoặc “Câu hỏi” không tự động kết thúc phần dữ kiện: một tiền đề thực tế xuất hiện sau đó vẫn phải được giữ. Tuy nhiên, không trích điều người dùng đang yêu cầu xác định, một kết luận pháp lý chưa biết hoặc một sự kiện chỉ được nêu như khả năng cần kiểm tra.

Chỉ dùng các category trong JSON Schema. Không tạo ID; Python sẽ cấp ID sau khi xác nhận quote. Chỉ trả một JSON object theo schema được cung cấp.""",
    )
)


FACT_EXTRACTOR_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "maxItems": 35,
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": [
                            "ACTOR",
                            "CONDUCT",
                            "LAND_TYPE",
                            "AFFECTED_AREA",
                            "TOTAL_AREA",
                            "LOCATION",
                            "LEGAL_STATUS",
                            "ELIGIBILITY_STATUS",
                            "TIME",
                            "OTHER",
                        ],
                    },
                    "quote": {"type": "string", "minLength": 1, "maxLength": 360},
                },
                "required": ["category", "quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["facts"],
    "additionalProperties": False,
}


FACT_EXTRACTION_RETRY_INSTRUCTION = """Kết quả trước không đạt output contract hoặc làm mất phần lớn dữ kiện của một tình huống dài. Trích xuất lại từ cùng đầu vào, giữ nguyên quote và chỉ trả JSON đúng schema. Không thêm dữ kiện mới hoặc kết luận pháp lý."""


__all__ = [
    "FACT_EXTRACTION_RETRY_INSTRUCTION",
    "FACT_EXTRACTOR_BASELINE_SPEC",
    "FACT_EXTRACTOR_CANDIDATE_SPEC",
    "FACT_EXTRACTOR_JSON_SCHEMA",
]
