# Planner Revise Patch Dataset

Dataset được biên dịch từ Planner DPO Gold, dùng cho targeted Issue Patch.

## Quy mô

- Train: 1.360
- Validation: 170
- Hidden test: 170
- Loại 300 COVERAGE_DECOMPOSITION vì contract hiện tại không thêm/bỏ Issue.

## Thứ tự huấn luyện bắt buộc

1. SFT warm-up bằng `planner_revise_sft_*`.
2. Chọn checkpoint theo validation contract + post-patch semantics.
3. Chỉ sau đó mới DPO bằng `planner_revise_dpo_*`.
4. Không trộn hidden test vào train.

Prompt runtime được pin từ `PLANNER_PATCH_PROMPT`; không dùng Planner prompt cũ.
