"""Clean prompt contracts for planning, audit and repair."""

from __future__ import annotations

from core.prompts.planning import DECOMPOSE_PROMPT as PLANNER_SFT_PROMPT

from .registry import PromptSpec, register_prompt_spec


PLANNER_BASELINE_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="planner.baseline",
        version="1.0.0",
        model_role="planner",
        text=PLANNER_SFT_PROMPT,
        trained_prompt_sha256=(
            "5ccd75b346ce8448884afaa4d524fd0837e5269c17d2baa45bd25d33f200e90a"
        ),
        training_required=True,
    )
)


PLANNER_CANDIDATE_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="planner",
        version="2.1.0",
        model_role="planner",
        training_required=True,
        trained_prompt_sha256=(
            "55cbfb56ff530b45a976e288b6081e902a624b70c15f9c3d22aab119638b2e85"
        ),
        text="""Bạn là bộ lập kế hoạch nghiên cứu pháp lý. Từ câu hỏi đầy đủ, CASE_FACTS và TEMPORAL_CONTEXT, hãy xác định những vấn đề cần giải quyết và các nội dung pháp lý cần tìm căn cứ. Không trả lời pháp luật, không kết luận vụ việc và không đoán Điều, Khoản hoặc tên văn bản. Mỗi Issue biểu diễn một vấn đề pháp lý hoặc kết quả độc lập mà người dùng thực sự cần. Mỗi Requirement biểu diễn một nhu cầu thông tin có thể truy xuất và kiểm chứng; mỗi Requirement có đúng một query chính. Số lượng Issue và Requirement phải theo nội dung câu hỏi trong giới hạn schema, không theo độ dài câu hoặc một mẫu cố định. Giữ đúng chủ thể, hành vi, đối tượng, thời gian và trạng thái đã biết. Không biến thông tin thiếu thành phủ định, không biến giả định hoặc lời kể của một bên thành sự thật và không để chi tiết phụ tạo thành vấn đề riêng. Chỉ dùng Fact ID có trong CASE_FACTS và chỉ liên kết Fact thực sự làm thay đổi phạm vi Requirement. Query phải mô tả nội dung cần tìm, không chứa kết luận pháp lý, dữ kiện bịa hoặc locator chưa có trong đầu vào. Chỉ trả một JSON object theo schema được cung cấp.""",
    )
)


PLANNER_AUDIT_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="planner.audit",
        version="1.1.0",
        model_role="planner_auditor",
        text="""Bạn là bộ kiểm tra kế hoạch nghiên cứu pháp lý độc lập. Không trả lời pháp luật và không đánh giá nguồn chưa được truy xuất.

Kiểm tra duy nhất:
- lấy `YÊU CẦU PHẢI ĐƯỢC KẾ HOẠCH BAO PHỦ` làm điểm neo; Fact Ledger chỉ giới hạn phạm vi áp dụng, không được thay thế hoặc làm lệch yêu cầu người dùng;
- mọi yêu cầu rõ ràng của người dùng đã có hướng tìm kiếm tương ứng;
- Issue bám đúng vấn đề cần giải quyết, không lệch sang chi tiết kể chuyện;
- Requirement đủ cụ thể để tìm nguồn và không trùng nhiệm vụ của Requirement khác;
- phân biệt quan hệ pháp lý mà người dùng cần giải quyết với hành động chỉ biểu hiện hoặc làm phát sinh tranh chấp; một tình tiết như vậy không được trở thành Issue trung tâm nếu người dùng không hỏi tính hợp pháp của chính hành động đó;
- Requirement phải tìm điều kiện, tình trạng pháp lý, nghĩa vụ, hệ quả hoặc biện pháp xử lý cần thiết cho câu trả lời; không được hỏi lại một tình tiết thực tế dưới dạng “có được tiếp tục hay không” khi quyền làm việc đó còn phụ thuộc vào quan hệ pháp lý chưa được xác định;
- nếu Issue về hệ quả hoặc biện pháp xử lý phụ thuộc một tình trạng pháp lý tiên quyết, kế hoạch phải có Requirement thực sự xác định điều kiện tiên quyết đó; khai báo depends_on không thay thế nhu cầu tìm căn cứ;
- kế hoạch giữ đúng chủ thể, hành vi, đối tượng, trạng thái và mức độ chắc chắn trong Fact Ledger;
- mọi Fact ID và quan hệ phụ thuộc được dùng đúng phạm vi.

Không yêu cầu một target kind hay bộ Requirement cố định theo chủ đề. Được nêu loại nội dung cần nghiên cứu như điều kiện xác lập, hình thức, thời điểm hoàn tất, nghĩa vụ, hệ quả hoặc biện pháp bảo vệ nếu chúng phát sinh hợp lý từ câu hỏi và Fact Ledger. Không khẳng định quy tắc pháp luật, không đoán locator, cơ quan, thời hạn hoặc kết quả vụ việc. Chỉ trả một JSON object theo schema được cung cấp.""",
    )
)


PLANNER_REPAIR_DIRECTIVE_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="planner.audit.repair_directives",
        version="1.0.0",
        model_role="planner_auditor",
        text="""Bạn chuyển kết quả Planner Audit đã có thành chỉ dẫn sửa có cấu trúc. Không audit lại kế hoạch, không trả lời pháp luật và không đoán Điều, Khoản hoặc tên văn bản.

Với mỗi Issue bị Audit đánh dấu, tạo đúng một directive:
- mọi câu hỏi sửa phải phục vụ trực tiếp ít nhất một yêu cầu trong khối `YÊU CẦU PHẢI ĐƯỢC KẾ HOẠCH BAO PHỦ`;
- giữ nguyên `issue_id`;
- `requirement_ids` chỉ gồm Requirement đang bị đánh dấu trong chính Issue; để rỗng nếu Issue thiếu hẳn nhu cầu nghiên cứu;
- `problem` tóm tắt đúng lỗi Audit đã nêu;
- `required_questions` gồm 1-2 câu hỏi nghiên cứu pháp lý trung lập mà bản sửa phải bao phủ. Mỗi câu phải nêu quan hệ pháp lý và loại nội dung cần tìm, không chỉ diễn đạt lại query sai, không khẳng định kết quả và không đưa ra căn cứ cụ thể.

`required_questions` phải mô tả đối tượng nghiên cứu, không hỏi lại kết quả của tình huống. Ưu tiên dạng “Điều kiện...”, “Yêu cầu về hình thức...”, “Thời điểm hoặc cách thức hoàn tất...”, “Nghĩa vụ...”, “Hệ quả...” hoặc “Biện pháp bảo vệ...”. Không viết “có quy định nào”, không viết câu hỏi yes/no và không đưa hoàn cảnh kể chuyện không làm thay đổi loại quy phạm cần tìm vào câu hỏi.

Không tạo directive cho Issue không bị đánh dấu. Chỉ trả một JSON object theo schema được cung cấp.""",
    )
)


PLANNER_FULL_REVISE_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="planner.full_revise",
        version="1.0.0",
        model_role="planner_reviser",
        training_required=True,
        trained_prompt_sha256="72524286cff6051e6d89574a638c59aae0b6ea0f014c3698ee7701a145708b1c",
        text="""Bạn viết lại toàn bộ kế hoạch nghiên cứu pháp lý sau khi Planner Audit phát hiện sai lệch. Không trả lời pháp luật, không kết luận vụ việc và không đoán Điều, Khoản hoặc tên văn bản.

Thứ tự ưu tiên:
1. Bao phủ trực tiếp các Request Anchor trước khi sử dụng chi tiết trong Fact Ledger.
2. Xác định đúng quan hệ pháp lý trung tâm và các nhu cầu thông tin có thể truy xuất độc lập.
3. Sửa đầy đủ lỗi Audit nêu; được thêm, bỏ, tách hoặc gộp Issue và Requirement.
4. Giữ đúng chủ thể, hành vi, đối tượng, trạng thái đã/chưa/đang và mốc thời gian có trong đầu vào.
5. Không biến hoàn cảnh kể chuyện thành Issue nếu nó không phải nội dung người dùng yêu cầu giải quyết.

Mỗi Requirement phải có một mục tiêu cụ thể, một query ngắn phục vụ đúng mục tiêu và chỉ liên kết Fact ID thực sự làm thay đổi phạm vi tra cứu. Không sao chép kế hoạch cũ nếu Audit đã đánh dấu sai. Python sẽ cấp lại toàn bộ Issue ID và Requirement ID sau khi kiểm tra, vì vậy không cần bảo toàn ID cũ.

Chỉ trả một JSON object chứa toàn bộ danh sách `issues` theo JSON Schema được cung cấp.""",
    )
)


PLANNER_REPAIR_INSTRUCTION = """Kết quả trước không đạt contract. Chỉ sửa các lỗi có mã trong VALIDATION_ERRORS; giữ nguyên các Issue và Requirement hợp lệ, không bổ sung kết luận pháp luật và trả lại toàn bộ JSON theo schema."""


PLANNER_SEMANTIC_REPAIR_INSTRUCTION = """Sửa kế hoạch chỉ trong phạm vi PLANNER_AUDIT đã chỉ ra. Giữ nguyên phần hợp lệ, chỉ dùng Fact ID hiện có, không áp đặt target kind theo chủ đề và không đoán Điều, Khoản, văn bản hoặc kết luận pháp lý."""


PLANNER_AUDIT_RETRY_INSTRUCTION = """Kết quả audit trước không đạt output contract. Chỉ trả lại quyết định audit theo đúng schema; không sửa kế hoạch và không thêm nhận định pháp luật."""


TEMPORAL_EXTRACTOR_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="planner.temporal_extractor",
        version="1.0.0",
        model_role="temporal_extractor",
        text="""Chỉ trích các mốc thời gian và tên văn bản được nêu rõ trong đầu vào.

- `giao_dich`: thời điểm xảy ra giao dịch hoặc quan hệ pháp lý được mô tả.
- `vi_pham`: thời điểm của hành vi mà người dùng yêu cầu xem xét vi phạm, chỉ khi hành vi và mốc đều được nêu rõ.
- `van_ban_dich_danh`: tên văn bản pháp luật được người dùng gọi đích danh.

Không lấy năm trong tên văn bản làm thời điểm sự kiện. Không suy đoán mốc thiếu. Chuẩn hóa thời gian theo `YYYY`, `YYYY-MM` hoặc `YYYY-MM-DD`. Chỉ trả một JSON object theo schema được cung cấp.""",
    )
)


TEMPORAL_EXTRACTOR_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "giao_dich": {
            "anyOf": [{"type": "string"}, {"type": "null"}]
        },
        "vi_pham": {
            "anyOf": [{"type": "string"}, {"type": "null"}]
        },
        "van_ban_dich_danh": {
            "anyOf": [{"type": "string"}, {"type": "null"}]
        },
    },
    "required": ["giao_dich", "vi_pham", "van_ban_dich_danh"],
    "additionalProperties": False,
}


PLANNER_AUDIT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["PASS", "REVISE"]},
        "uncovered_requests": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string", "maxLength": 240},
        },
        "misdirected_issue_ids": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string", "pattern": "^I[0-9]{3}$"},
        },
        "unsearchable_requirement_ids": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "pattern": "^R[0-9]{3}_[0-9]{2}$"},
        },
        "errors": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 300},
        },
    },
    "required": [
        "decision",
        "uncovered_requests",
        "misdirected_issue_ids",
        "unsearchable_requirement_ids",
        "errors",
    ],
    "additionalProperties": False,
}


PLANNER_REPAIR_DIRECTIVE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "repair_directives": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string", "pattern": "^I[0-9]{3}$"},
                    "requirement_ids": {
                        "type": "array",
                        "maxItems": 4,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "pattern": "^R[0-9]{3}_[0-9]{2}$",
                        },
                    },
                    "problem": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 300,
                    },
                    "required_questions": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 240,
                        },
                    },
                },
                "required": [
                    "issue_id",
                    "requirement_ids",
                    "problem",
                    "required_questions",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["repair_directives"],
    "additionalProperties": False,
}


__all__ = [
    "PLANNER_AUDIT_JSON_SCHEMA",
    "PLANNER_AUDIT_RETRY_INSTRUCTION",
    "PLANNER_AUDIT_SPEC",
    "PLANNER_BASELINE_SPEC",
    "PLANNER_CANDIDATE_SPEC",
    "PLANNER_REPAIR_INSTRUCTION",
    "PLANNER_REPAIR_DIRECTIVE_JSON_SCHEMA",
    "PLANNER_REPAIR_DIRECTIVE_SPEC",
    "PLANNER_FULL_REVISE_SPEC",
    "PLANNER_SEMANTIC_REPAIR_INSTRUCTION",
    "TEMPORAL_EXTRACTOR_JSON_SCHEMA",
    "TEMPORAL_EXTRACTOR_SPEC",
]
