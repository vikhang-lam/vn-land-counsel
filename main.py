"""Điểm khởi chạy giao diện terminal của hệ thống cục bộ."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Xây dựng hệ thống hỗ trợ tư vấn pháp luật đất đai và tranh chấp "
            "dựa trên Agentic RAG"
        )
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Tùy chọn ghi đè địa chỉ llama.cpp",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Tùy chọn ghi đè mô hình nền",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Thời gian chờ tính bằng giây; 0 dùng cấu hình mặc định",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Chỉ kiểm tra máy chủ mô hình rồi thoát",
    )
    args = parser.parse_args()

    from core.config import AgentSettings
    from core.llm import LocalLLMClient

    settings = AgentSettings.from_env()
    client = LocalLLMClient(
        base_url=args.base_url or None,
        model=args.model or settings.base_model,
        timeout=args.timeout or None,
    )
    try:
        client.ensure_available()
    except Exception as error:
        print(f"Lỗi: {error}")
        print("Hãy chạy llama-server trước, sau đó thử lại: python main.py --check")
        raise SystemExit(2) from error

    if args.check:
        print(f"Máy chủ mô hình sẵn sàng: {client.model} tại {client.base_url}")
        return

    from core.agent import run_agent

    run_agent(client)


if __name__ == "__main__":
    main()
