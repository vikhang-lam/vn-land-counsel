# Adapter mô hình

Thư mục này chứa các adapter do nhóm huấn luyện cho chương trình chạy cục bộ.

## Mô hình được dùng trong cấu hình mặc định

| Thành phần | Model ID | Adapter |
|---|---|---|
| Trích xuất dữ kiện | `Fact-Qwen3-8B-LoRA` | `models/fact_qwen3_8b_lora/` |
| Lập kế hoạch | `Planner-Qwen3-8B-SFT-3000` | `models/planner_qwen3_8b_sft_3000_candidate/` |
| Sửa kế hoạch | `Planner-Full-Revise-Qwen3-8B-LoRA` | `models/planner_full_revise_qwen3_8b_lora/` |
| Kiểm chứng nhận định | `Claim-Verifier-Qwen3-8B-LoRA` | `models/claim_verifier_qwen3_8b_lora/` |

Các adapter Planner còn lại phục vụ những cấu hình so sánh có sẵn trong
launcher; chúng không được chọn trong cấu hình mặc định.

Mỗi thư mục mô hình có thể gồm adapter Hugging Face, adapter GGUF và tệp mô tả
quá trình huấn luyện. Khi chạy, llama.cpp ghép adapter tương ứng với mô hình nền
được khai báo trong `runtime/llama-models.ini`.

## Kho truy xuất

Kho chunk và cơ sở dữ liệu ChromaDB được đặt riêng tại `data/retrieval_store/`.
