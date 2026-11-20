"""Grounded one-pass answer contract for the SIMPLE branch."""

from __future__ import annotations

from .registry import PromptSpec, register_prompt_spec


SIMPLE_SOURCE_GATE_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="simple.source_gate",
        version="1.1.0",
        model_role="simple_source_gate",
        text="""Đánh dấu từng nguồn YES hoặc NO đối với nguyên văn câu hỏi người dùng.

YES chỉ khi ít nhất một quy định thực chất trong nguồn khớp đúng hành vi pháp
lý, đối tượng và trường hợp mà câu hỏi yêu cầu; nguồn có thể trả lời trực tiếp
hoặc quy định một bước, điều kiện, ngoại lệ, thời hạn hay hệ quả thật sự thuộc
đúng quy trình hoặc quan hệ đó.

NO khi nguồn chỉ trùng từ khóa hoặc cùng lĩnh vực nhưng điều chỉnh sai quan hệ,
sai thủ tục, sai đối tượng, trường hợp hẹp không được hỏi, biểu mẫu rời rạc hoặc
thao tác không giúp trả lời câu hỏi.

Không đánh dấu YES chỉ vì tiêu đề hoặc một dòng cuối nhắc tới chủ đề nếu phần
quy phạm chính đang nói việc khác. Một bước xử lý của cơ quan có thể là YES nếu
nó thực sự thuộc đúng thủ tục được hỏi. Một trường hợp đặc biệt là NO khi câu
hỏi không nêu điều kiện làm phát sinh trường hợp đó.

Đọc toàn bộ câu hỏi và toàn bộ nội dung từng nguồn. Không trả lời người dùng,
không chọn Điều mới, không sửa nguồn và không dùng kiến thức ngoài input. Trả
đúng một decision cho mỗi source_index trong input. Đánh giá các nguồn trong
tương quan với nhau để phân biệt quy định trực tiếp với nguồn chỉ gần chủ đề.
Reason chỉ nêu một lý do ngắn dựa trên nội dung nguồn.""",
    )
)


def simple_source_gate_schema(source_count: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "minItems": source_count,
                "maxItems": source_count,
                "items": {
                    "type": "object",
                    "properties": {
                        "source_index": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": max(0, source_count - 1),
                        },
                        "verdict": {"type": "string", "enum": ["YES", "NO"]},
                        "reason": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 140,
                        },
                    },
                    "required": ["source_index", "verdict", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["decisions"],
        "additionalProperties": False,
    }


SIMPLE_GROUNDED_WRITER_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="simple.grounded_writer",
        version="2.1.0",
        model_role="simple_answer_writer",
        text="""Trả lời trực tiếp một câu hỏi pháp luật đơn giản chỉ từ các nguồn được cung cấp.

Đầu vào gồm câu hỏi, kiểu trả lời và các nguồn có chỉ mục. Tiêu đề Điều ở đầu nguồn là một phần của ngữ cảnh pháp lý: phải phân biệt đúng quyền, giao dịch, thủ tục và trường hợp áp dụng; không dùng một nguồn chỉ gần chủ đề nhưng điều chỉnh trường hợp khác.

Nếu câu hỏi chỉ yêu cầu nêu khái niệm, quyền, nghĩa vụ, nguyên tắc, điều kiện hoặc thủ tục chung, hãy trình bày quy định có trong nguồn. Không giả định đây là một vụ việc đang thiếu hồ sơ và không viết "chưa đủ thông tin" chỉ vì câu hỏi không cung cấp dữ kiện áp dụng. Khi câu hỏi có nhiều vế trong cùng chủ đề, direct_answer trả lời vế chính và units lần lượt trả lời các vế còn lại.

direct_answer là câu trả lời mở đầu:
- trả lời ngay điều người dùng hỏi, không kể lại quá trình tìm kiếm;
- viết một hoặc hai câu hoàn chỉnh, tối đa 500 ký tự; không chép cả danh sách dài và không dùng dấu ba chấm;
- dùng đúng một source_index và một source_quote liên tục có thật;
- source_quote là cụm ngắn nhất đủ chứng minh, tối đa 160 ký tự;
- source_quote phải kết thúc tại ranh giới một cụm hoặc câu có thật; tuyệt đối không dùng "...", "…" hoặc ký hiệu rút gọn;
- direct_answer chỉ nêu nội dung mà quote ngắn trực tiếp chứng minh; đưa từng điều kiện hoặc bước chi tiết xuống units với quote riêng;
- không bỏ điều kiện làm thay đổi phạm vi của nguồn;
- nếu không có nguồn trực tiếp, dùng source_index=-1 và để text, source_quote rỗng.

units chỉ bổ sung tối đa ba ý cần thiết. Với thủ tục, ưu tiên theo thứ tự: hành động của người yêu cầu, bước xử lý tiếp theo, thời hạn hoặc lưu ý. Không biến thao tác nội bộ của cơ quan thành việc người dùng phải làm và không lặp direct_answer.

Mỗi câu phải bám đúng source_quote, không thêm con số, điều kiện, ngoại lệ hoặc kết luận ngoài nguồn. Không viết citation, locator, ID nội bộ, tiêu đề hay Markdown; Python sẽ gắn trích dẫn.

Coverage:
- COMPLETE: đã trả lời trực tiếp toàn bộ nội dung được hỏi rõ;
- PARTIAL: trả lời được một phần, ghi cụ thể phần còn thiếu;
- NO_SUPPORT: không có nguồn trực tiếp.

Nếu input có trường repair, lượt trước đã không vượt qua kiểm tra kỹ thuật. Hãy sửa đúng lỗi được nêu, chọn lại source_index và chép source_quote nguyên văn. Không lặp lại kết luận NO_SUPPORT khi nguồn đang chứa trực tiếp nội dung câu hỏi.

Chỉ trả một JSON object theo schema.""",
    )
)


def simple_grounded_writer_schema(max_units: int, source_count: int) -> dict:
    grounded_unit = {
        "type": "object",
        "properties": {
            "source_index": {
                "type": "integer",
                "minimum": 0,
                "maximum": max(0, source_count - 1),
            },
            "source_quote": {
                "type": "string",
                "minLength": 1,
                "maxLength": 180,
            },
            "text": {"type": "string", "minLength": 1, "maxLength": 600},
        },
        "required": ["source_index", "source_quote", "text"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "coverage": {
                "type": "string",
                "enum": ["COMPLETE", "PARTIAL", "NO_SUPPORT"],
            },
            "missing_aspects": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string", "maxLength": 220},
            },
            "direct_answer": {
                "type": "object",
                "properties": {
                    "source_index": {
                        "type": "integer",
                        "minimum": -1,
                        "maximum": max(0, source_count - 1),
                    },
                    "source_quote": {"type": "string", "maxLength": 180},
                    "text": {"type": "string", "maxLength": 500},
                },
                "required": ["source_index", "source_quote", "text"],
                "additionalProperties": False,
            },
            "units": {
                "type": "array",
                "maxItems": max_units,
                "items": grounded_unit,
            },
        },
        "required": ["coverage", "missing_aspects", "direct_answer", "units"],
        "additionalProperties": False,
    }


__all__ = [
    "SIMPLE_GROUNDED_WRITER_SPEC",
    "SIMPLE_SOURCE_GATE_SPEC",
    "simple_grounded_writer_schema",
    "simple_source_gate_schema",
]
