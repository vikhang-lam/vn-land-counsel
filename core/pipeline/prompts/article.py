"""One-pass grounded summarizer for an exact Article lookup."""

from __future__ import annotations

from .registry import PromptSpec, register_prompt_spec


ARTICLE_SUMMARIZER_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="article.summarizer",
        version="1.1.0",
        model_role="article_summarizer",
        text="""Giải thích ngắn nội dung của đúng một Điều luật từ các đoạn nguồn được cung cấp.

Mỗi ý phải dùng đúng một source_index và có source_quote là đoạn liên tục có thật trong nguồn đó. source_quote phải là cụm ngắn hoàn chỉnh, không dùng "...", "…" hoặc ký hiệu rút gọn. Diễn đạt dễ hiểu nhưng không thêm điều kiện, ngoại lệ, con số hoặc hệ quả ngoài source_quote. Giữ các nhánh, trường hợp hoặc ngoại lệ quan trọng; không biến việc tóm tắt thành tư vấn áp dụng cho một vụ việc cụ thể.

Không viết citation, locator, ID nội bộ, tiêu đề hoặc markdown. Nếu nhiều đoạn lặp cùng nội dung, chỉ giữ một ý. Nếu input có trường repair, lượt trước không vượt qua kiểm tra đoạn trích; hãy chép source_quote nguyên văn và sửa lại JSON, không tuyên bố thiếu nguồn khi các đoạn của Điều đã được cung cấp. Chỉ trả JSON theo schema.""",
    )
)


def article_summarizer_schema(max_units: int, source_count: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "units": {
                "type": "array",
                "maxItems": max_units,
                "items": {
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
                            "maxLength": 1200,
                        },
                        "text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1200,
                        },
                    },
                    "required": ["source_index", "source_quote", "text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["units"],
        "additionalProperties": False,
    }


__all__ = ["ARTICLE_SUMMARIZER_SPEC", "article_summarizer_schema"]
