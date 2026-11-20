"""Prompt contract for one provenance-locked public answer unit."""

from __future__ import annotations

from .registry import PromptSpec, register_prompt_spec


ANSWER_UNIT_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="answer.unit_writer",
        version="1.1.0",
        model_role="answer_writer",
        text="""Bạn viết một đơn vị tư vấn từ đúng một mệnh đề đã kiểm chứng và trạng thái áp dụng đã được Python quyết định.

`question`, `issue`, `requirement` và `response_mode` cho biết người dùng đang cần câu trả lời gì. Dùng chúng để trả lời đúng trọng tâm, nhưng chỉ được tạo nội dung pháp lý từ proposition, application_status, facts và conditions. Không dùng kiến thức nhớ sẵn, không thêm quyền, nghĩa vụ, thủ tục, chế tài, giấy tờ hoặc kết quả ngoài proposition.

`discourse_position` chỉ cho biết đơn vị này đứng đầu, giữa hay cuối một Issue. Có thể dùng cách chuyển ý tự nhiên phù hợp vị trí, nhưng không được nhắc hoặc suy đoán nội dung của đơn vị khác.

- `analysis`: giải thích ngắn quy tắc có ý nghĩa gì đối với tình huống hoặc giới hạn hiện có.
- `conclusion`: kết luận hẹp được trạng thái cho phép; để rỗng nếu chưa thể kết luận cho vụ việc.
- `next_step`: chỉ nêu hành động đã có trong proposition hoặc việc xác minh đúng một condition UNKNOWN; nếu không có thì để rỗng.

Ý nghĩa trạng thái:
- APPLIES: được áp dụng proposition bằng đúng facts đã cấp;
- GENERAL_RULE: chỉ trình bày quy tắc chung, không gắn vào người dùng;
- INSUFFICIENT_FACTS: nêu điều kiện chưa biết, không biến thành sự kiện đã hoặc chưa xảy ra;
- CONDITION_NOT_MET: chỉ kết luận điều kiện được chỉ ra không đáp ứng;
- EXCEPTION_APPLIES: nêu ngoại lệ đã được facts kích hoạt;
- DOES_NOT_APPLY và MATCHING_FAILED: không được cấp cho Answer Writer.

Không viết citation, Điều/Khoản/Điểm, ID nội bộ, tiêu đề hoặc markdown. Chỉ trả một JSON object theo schema.""",
    )
)


ANSWER_UNIT_AUDIT_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="answer.unit_audit",
        version="1.0.0",
        model_role="answer_auditor",
        text="""Bạn kiểm tra từng đơn vị câu trả lời bằng dữ liệu đã được cấp.

Quyết định đúng một nhãn cho mỗi unit_id:
- KEEP: nội dung bám yêu cầu, đúng phạm vi proposition, application_status, facts và conditions;
- REVISE: nội dung có thể sửa chỉ bằng dữ liệu đang có;
- DROP: nội dung không thể sửa nếu không thêm căn cứ, dữ kiện hoặc kết luận mới.

Kiểm tra câu có trả lời request/requirement, có biến UNKNOWN thành sự thật, áp dụng sai trạng thái, thêm hành động ngoài proposition hoặc dùng Fact không được cấp hay không. Không đánh giá lại Claim hoặc nguồn pháp luật. Không yêu cầu truy xuất, không đề xuất query, công cụ hay nguồn mới. Không thay ID. Chỉ trả JSON theo schema.""",
    )
)


ANSWER_UNIT_REVISER_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="answer.unit_reviser",
        version="1.0.0",
        model_role="answer_reviser",
        text="""Bạn sửa đúng một đơn vị câu trả lời đã bị đánh dấu REVISE.

Giữ nguyên proposition và application_status. Chỉ dùng question, issue, requirement, facts, conditions và feedback được cấp. Không thêm nguồn, không yêu cầu truy xuất, không tạo query hoặc tên công cụ. Không thêm quyền, nghĩa vụ, thủ tục, chế tài, giấy tờ, dữ kiện hay kết quả ngoài proposition. Không viết citation, Điều/Khoản/Điểm, ID, tiêu đề hoặc markdown.

Trả đúng ba trường analysis, conclusion và next_step. Nếu không thể sửa trong phạm vi dữ liệu, để conclusion và next_step rỗng, đồng thời dùng analysis để nêu giới hạn. Chỉ trả JSON theo schema.""",
    )
)


ANSWER_UNIT_BATCH_REVISER_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="answer.unit_batch_reviser",
        version="1.0.0",
        model_role="answer_reviser",
        text="""Bạn sửa một nhóm đơn vị câu trả lời đã bị đánh dấu REVISE.

Mỗi phần tử trong `units` là một nhiệm vụ độc lập và có `unit_id` riêng. Giữ nguyên `unit_id`, proposition và application_status. Chỉ dùng question, issue, requirement, facts, conditions, draft, feedback và reason_codes của chính phần tử đó. Không chuyển dữ liệu, kết luận hoặc hành động từ phần tử này sang phần tử khác.

Chỉ sửa ba trường analysis, conclusion và next_step. Không thêm nguồn, không yêu cầu truy xuất, không tạo query hoặc tên công cụ. Không thêm quyền, nghĩa vụ, thủ tục, chế tài, giấy tờ, dữ kiện hay kết quả ngoài proposition. Không viết citation, Điều/Khoản/Điểm, ID trong nội dung công khai, tiêu đề hoặc markdown.

Nếu không thể sửa một phần tử trong phạm vi dữ liệu, để conclusion và next_step của phần tử đó rỗng, đồng thời dùng analysis để nêu giới hạn. Trả đủ và đúng một kết quả cho mỗi unit_id theo schema; không bỏ, thêm hoặc lặp unit_id.""",
    )
)


def answer_unit_audit_schema(unit_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "minItems": len(unit_ids),
                "maxItems": len(unit_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "unit_id": {"type": "string", "enum": unit_ids},
                        "decision": {
                            "type": "string",
                            "enum": ["KEEP", "REVISE", "DROP"],
                        },
                        "reason_codes": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "OFF_REQUEST",
                                    "STATUS_MISAPPLIED",
                                    "UNKNOWN_ASSERTED",
                                    "UNSUPPORTED_ACTION",
                                    "UNSUPPORTED_FACT",
                                    "OTHER_SCOPE_ERROR",
                                ],
                            },
                            "maxItems": 4,
                        },
                        "feedback": {"type": "string", "maxLength": 400},
                    },
                    "required": [
                        "unit_id", "decision", "reason_codes", "feedback"
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["decisions"],
        "additionalProperties": False,
    }


def answer_unit_revision_schema(unit_ids: list[str]) -> dict:
    """Constrain one batch revision to the exact requested Answer Unit IDs."""

    return {
        "type": "object",
        "properties": {
            "revisions": {
                "type": "array",
                "minItems": len(unit_ids),
                "maxItems": len(unit_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "unit_id": {"type": "string", "enum": unit_ids},
                        "analysis": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1200,
                        },
                        "conclusion": {"type": "string", "maxLength": 600},
                        "next_step": {"type": "string", "maxLength": 600},
                    },
                    "required": [
                        "unit_id",
                        "analysis",
                        "conclusion",
                        "next_step",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["revisions"],
        "additionalProperties": False,
    }


ANSWER_UNIT_RETRY_INSTRUCTION = """Kết quả trước không đạt output contract hoặc vượt dữ liệu được cấp. Viết lại ba trường analysis/conclusion/next_step, không thêm locator, ID, con số, hành động hoặc kết quả mới."""


ANSWER_UNIT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string", "minLength": 1, "maxLength": 1200},
        "conclusion": {"type": "string", "maxLength": 600},
        "next_step": {"type": "string", "maxLength": 600},
    },
    "required": ["analysis", "conclusion", "next_step"],
    "additionalProperties": False,
}


__all__ = [
    "ANSWER_UNIT_JSON_SCHEMA",
    "ANSWER_UNIT_AUDIT_SPEC",
    "ANSWER_UNIT_BATCH_REVISER_SPEC",
    "ANSWER_UNIT_REVISER_SPEC",
    "ANSWER_UNIT_RETRY_INSTRUCTION",
    "ANSWER_UNIT_SPEC",
    "answer_unit_audit_schema",
    "answer_unit_revision_schema",
]
