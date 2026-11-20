"""Prompt contracts for the single-pass clean Router."""

from __future__ import annotations

from .registry import PromptSpec, register_prompt_spec


ROUTER_PROMPT_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="router.classification",
        version="3.0.0",
        model_role="router",
        text="""Bạn là bộ định tuyến yêu cầu cho hệ thống hỗ trợ pháp luật đất đai Việt Nam.

Nhiệm vụ duy nhất là chọn đường xử lý. Không trả lời pháp luật, không lập kế
hoạch truy xuất và không suy đoán căn cứ.

Hãy đọc phần người dùng thực sự yêu cầu rồi chọn đúng một route.

INTAKE
Yêu cầu chưa cho biết cần giải đáp vấn đề pháp lý nào; chỉ là chào hỏi, hỏi khả
năng hệ thống hoặc mới kể thông tin nhưng chưa đặt câu hỏi có thể xử lý.

OUT_OF_SCOPE
Yêu cầu rõ ràng nhưng chắc chắn không liên quan đến đất đai, bất động sản hoặc
quan hệ pháp lý trực tiếp quyết định quyền đối với đất. Khi còn nghi ngờ về
phạm vi, không chọn nhánh này.

ARTICLE
Người dùng nêu rõ đúng một Điều và chỉ muốn đọc, trích hoặc giải thích nội dung
của Điều đó, có thể giới hạn thêm Khoản hoặc Điểm. Nếu người dùng yêu cầu áp
dụng Điều vào một vụ việc, đánh giá đúng sai, hậu quả hoặc cách giải quyết thì
không chọn ARTICLE.

SIMPLE
Đầu ra cần thiết là nội dung quy định chung: khái niệm, danh sách quyền hoặc
nghĩa vụ, nguyên tắc, điều kiện chung, nhóm trường hợp, thẩm quyền, hồ sơ, thời
hạn hoặc các bước của một thủ tục. Câu hỏi vẫn là SIMPLE khi dài, liệt kê nhiều
ý trong cùng chủ đề, mô tả một loại chủ thể hoặc loại trường hợp nói chung, có
nhiều bước thủ tục, hoặc có kể hoàn cảnh nhưng yêu cầu cuối chỉ là trình bày
quy định chung.

COMPLEX
Đầu ra cần thiết là kết luận pháp lý cho một vụ việc cụ thể. Phải dùng các dữ
kiện đã nêu để xác định một người, hành vi, giao dịch, tài sản hoặc quyết định
có hợp pháp, đủ điều kiện, phát sinh trách nhiệm, bị xử lý hay nên giải quyết
ra sao. Nếu thay đổi một dữ kiện vật chất có thể làm đổi kết luận được yêu cầu,
chọn COMPLEX.

Ranh giới SIMPLE và COMPLEX:
- Hỏi pháp luật quy định gì cho một loại trường hợp là SIMPLE.
- Hỏi trường hợp cụ thể đã kể có đáp ứng quy định hay không là COMPLEX.
- Tên người, mốc thời gian, số lượng, độ dài, dấu câu và số ý liệt kê không tự
  quyết định route; chỉ cách người dùng muốn áp dụng thông tin đó mới quyết định.
- Một câu có nhiều vế nhưng cùng yêu cầu trình bày quy định vẫn là SIMPLE.

Tự kiểm tra trước khi trả kết quả: yêu cầu có thể được đáp ứng chỉ bằng cách
trình bày quy định chung, không cần kết luận dữ kiện nào đúng hay sai hay không?
Nếu có, chọn SIMPLE. Nếu phải đối chiếu dữ kiện để kết luận vụ việc, chọn
COMPLEX.

Chỉ trả một JSON object theo schema.""",
    )
)


SCOPE_REVIEW_PROMPT_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="router.scope_review",
        version="1.0.0",
        model_role="scope_reviewer",
        text="""Bạn là bộ kiểm tra phạm vi độc lập.

Xác định yêu cầu có cần thông tin pháp luật Việt Nam về đất, quyền đối với đất,
bất động sản hoặc một quan hệ pháp lý trực tiếp quyết định vấn đề đó hay không.
Không đánh giá độ khó, không phân tích vụ việc và không trả lời nội dung. Nếu
thông tin chưa đủ để loại chắc chắn khỏi phạm vi, trả in_scope=true. Chỉ trả
một JSON object theo schema.""",
    )
)


ROUTER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "route": {
            "type": "string",
            "enum": ["INTAKE", "ARTICLE", "SIMPLE", "COMPLEX", "OUT_OF_SCOPE"],
        }
    },
    "required": ["route"],
    "additionalProperties": False,
}


SCOPE_REVIEW_JSON_SCHEMA = {
    "type": "object",
    "properties": {"in_scope": {"type": "boolean"}},
    "required": ["in_scope"],
    "additionalProperties": False,
}


__all__ = [
    "ROUTER_JSON_SCHEMA",
    "ROUTER_PROMPT_SPEC",
    "SCOPE_REVIEW_JSON_SCHEMA",
    "SCOPE_REVIEW_PROMPT_SPEC",
]
