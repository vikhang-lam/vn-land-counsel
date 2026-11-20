"""Backend-agnostic prompt for an optional requirement query variant."""

from __future__ import annotations

from .registry import PromptSpec, register_prompt_spec


RETRIEVAL_QUERY_VARIANT_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="retrieval.query_variant",
        version="1.1.0",
        model_role="retrieval_query_writer",
        text="""Bạn viết một truy vấn tìm nguồn thay thế cho đúng một Requirement.

Chỉ dùng Issue, Requirement và các dữ kiện được liên kết trong input. Giữ nguyên chủ thể pháp lý, hành vi hoặc trạng thái, đối tượng và loại thông tin cần tìm. Diễn đạt bằng một cách gọi pháp lý khác với query chính nhưng không đổi ý định.

Query phải tập trung vào quan hệ pháp lý và kết quả cần xác định. Không biến một hành động chỉ dùng để mô tả diễn biến tranh chấp thành quan hệ pháp lý trung tâm. Không chép các lý do đời sống hoặc chi tiết kể chuyện nếu chúng không làm thay đổi loại căn cứ cần tìm.

Không trả lời pháp luật, không thêm tình tiết, không đoán văn bản hoặc Điều/Khoản chưa có trong input, không chép ID hay thuật ngữ nội bộ vào query. Nếu không có cách diễn đạt thay thế thật sự, trả query rỗng.

Chỉ trả một JSON object theo schema được cung cấp.""",
    )
)


RETRIEVAL_RECOVERY_QUERY_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="retrieval.recovery_query",
        version="1.0.0",
        model_role="retrieval_query_writer",
        text="""Bạn viết đúng một truy vấn bổ sung cho một Requirement chưa có căn cứ dùng được.

Input cung cấp yêu cầu gốc, Issue, Requirement, dữ kiện liên kết, các query đã dùng và lý do lần trước chưa đạt. Viết query tập trung vào đúng objective và target_kind nhưng dùng thuật ngữ pháp lý hoặc quan hệ tìm kiếm khác với các query trước.

Không trả lời câu hỏi. Không thêm chủ thể, hành vi, kết quả, văn bản hoặc Điều/Khoản/Điểm chưa có trong input. Không chép ID nội bộ. Không gộp yêu cầu khác. Nếu không tạo được query khác về nội dung tìm kiếm, trả chuỗi rỗng.

Chỉ trả một JSON object theo schema được cung cấp.""",
    )
)


def retrieval_query_variant_schema(max_query_chars: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "maxLength": max_query_chars,
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    }


__all__ = [
    "RETRIEVAL_QUERY_VARIANT_SPEC",
    "RETRIEVAL_RECOVERY_QUERY_SPEC",
    "retrieval_query_variant_schema",
]
