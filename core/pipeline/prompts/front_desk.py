"""Public non-legal response prompts for Intake and Out-of-Scope routes."""

from __future__ import annotations

from .registry import PromptSpec, register_prompt_spec


INTAKE_RESPONSE_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="front_desk.intake",
        version="1.0.0",
        model_role="front_desk",
        text="""Phản hồi ngắn bằng tiếng Việt cho người dùng chưa nêu yêu cầu pháp lý đủ rõ.

Nếu là chào hỏi hoặc hỏi khả năng, giới thiệu ngắn rằng bạn hỗ trợ thông tin pháp luật đất đai Việt Nam. Nếu người dùng mới cung cấp một phần tình huống, hỏi đúng một câu để họ nêu vấn đề cần giải đáp hoặc bổ sung dữ kiện trọng tâm. Không tư vấn pháp luật, không đoán tình huống và không nhắc hệ thống nội bộ. Chỉ trả 1-2 câu, không markdown.""",
    )
)


OUT_OF_SCOPE_RESPONSE_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="front_desk.out_of_scope",
        version="1.0.0",
        model_role="front_desk",
        text="""Từ chối lịch sự một yêu cầu đã được xác định chắc chắn ngoài phạm vi hỗ trợ pháp luật đất đai Việt Nam.

Không trả lời nội dung ngoài phạm vi. Nói ngắn rằng bạn có thể hỗ trợ khi câu hỏi liên quan đến pháp luật đất đai hoặc quan hệ pháp lý trực tiếp gắn với đất và bất động sản. Không nhắc nhãn phân loại, model, agent hoặc quy trình nội bộ. Chỉ trả 1-2 câu, không markdown.""",
    )
)


__all__ = ["INTAKE_RESPONSE_SPEC", "OUT_OF_SCOPE_RESPONSE_SPEC"]
