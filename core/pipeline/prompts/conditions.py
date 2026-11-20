"""Prompt contracts for condition extraction and fact matching."""

from __future__ import annotations

from .registry import PromptSpec, register_prompt_spec


CONDITION_EXTRACTOR_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="condition_extractor",
        version="1.0.0",
        model_role="condition_extractor",
        training_required=True,
        text="""Bạn trích cấu trúc điều kiện chi phối đúng một mệnh đề pháp lý từ đoạn nguồn đã được khóa.

Chỉ dùng chữ có trong SOURCE QUOTE. Không xem Facts và không quyết định điều kiện đã xảy ra.

Phân loại cấu trúc:
- `all_of`: các điều kiện cùng phải được thỏa mãn để mệnh đề áp dụng;
- `any_of`: các nhóm phương án thay thế, trong mỗi nhóm chỉ cần một alternative;
- `exceptions`: trường hợp loại trừ hoặc làm quy tắc chính không áp dụng.

Mỗi điều kiện có role:
- SCOPE: giới hạn về chủ thể, đối tượng, loại quan hệ, loại tài sản, địa điểm hoặc thời gian;
- TRIGGER: sự kiện hoặc trạng thái kích hoạt quy tắc;
- REMEDY_PRECONDITION: tiền đề riêng để sử dụng biện pháp xử lý.

Mỗi item phải kèm `source_quote` là đoạn liên tục có thật trong SOURCE QUOTE. Không chép kết luận của proposition thành điều kiện, không bổ sung điều kiện chung từ kiến thức ngoài nguồn và không đưa nhánh anh em không chi phối proposition đang xét. Không tạo ID. Nếu proposition không có điều kiện cần đối chiếu với vụ việc, trả các mảng rỗng.

Chỉ trả một JSON object theo schema được cung cấp.""",
    )
)


CONDITION_MATCHER_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="condition_matcher",
        version="1.0.0",
        model_role="condition_matcher",
        training_required=True,
        text="""Bạn đối chiếu từng điều kiện đã được cấp với Fact Ledger.

Với mỗi condition_id, chọn đúng một trạng thái:
- SATISFIED: ít nhất một Fact trực tiếp xác nhận điều kiện;
- CONTRADICTED: ít nhất một Fact trực tiếp xác nhận trạng thái đối lập;
- UNKNOWN: Fact Ledger không đủ để xác định.

Chỉ dùng Fact ID có trong input. SATISFIED và CONTRADICTED phải có fact_ids; UNKNOWN phải để fact_ids rỗng. Không dùng kiến thức ngoài điều kiện và Facts, không suy từ việc không được nêu thành phủ định, không tự bỏ/gộp điều kiện và không quyết định trạng thái áp dụng chung của Claim. Trả đúng một match cho mọi condition_id theo schema.""",
    )
)


CONDITION_EXTRACTOR_RETRY_INSTRUCTION = """Kết quả trước không đạt output contract hoặc có source_quote không nằm trong đoạn nguồn. Trả lại đúng cấu trúc all_of/any_of/exceptions, không tạo ID và không thêm điều kiện ngoài nguồn."""


CONDITION_MATCHER_RETRY_INSTRUCTION = """Kết quả trước không đạt output contract. Trả đúng một match cho mỗi condition_id; chỉ dùng Fact ID đã cấp và không quyết định trạng thái chung của Claim."""


_CONDITION_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "condition": {"type": "string", "minLength": 1, "maxLength": 600},
        "source_quote": {"type": "string", "minLength": 1, "maxLength": 900},
        "role": {
            "type": "string",
            "enum": ["SCOPE", "TRIGGER", "REMEDY_PRECONDITION"],
        },
    },
    "required": ["condition", "source_quote", "role"],
    "additionalProperties": False,
}


CONDITION_EXTRACTOR_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "all_of": {
            "type": "array",
            "items": _CONDITION_ITEM_SCHEMA,
        },
        "any_of": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "alternatives": {
                        "type": "array",
                        "minItems": 2,
                        "items": _CONDITION_ITEM_SCHEMA,
                    }
                },
                "required": ["alternatives"],
                "additionalProperties": False,
            },
        },
        "exceptions": {
            "type": "array",
            "items": _CONDITION_ITEM_SCHEMA,
        },
    },
    "required": ["all_of", "any_of", "exceptions"],
    "additionalProperties": False,
}


def condition_matcher_schema(condition_count: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "minItems": condition_count,
                "maxItems": condition_count,
                "items": {
                    "type": "object",
                    "properties": {
                        "condition_id": {
                            "type": "string",
                            "pattern": "^K[0-9]{3}$",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["SATISFIED", "CONTRADICTED", "UNKNOWN"],
                        },
                        "fact_ids": {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"type": "string", "pattern": "^F[0-9]{3}$"},
                        },
                        "reason": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 300,
                        },
                    },
                    "required": ["condition_id", "status", "fact_ids", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["matches"],
        "additionalProperties": False,
    }


__all__ = [
    "CONDITION_EXTRACTOR_JSON_SCHEMA",
    "CONDITION_EXTRACTOR_RETRY_INSTRUCTION",
    "CONDITION_EXTRACTOR_SPEC",
    "CONDITION_MATCHER_RETRY_INSTRUCTION",
    "CONDITION_MATCHER_SPEC",
    "condition_matcher_schema",
]
