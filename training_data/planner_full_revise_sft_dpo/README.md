# Planner Full-Plan Revision Dataset

Bộ dữ liệu huấn luyện Planner sửa lại toàn bộ kế hoạch sau khi Audit phát hiện
sai lệch. Đầu vào gồm Request Anchor, câu hỏi, Fact Ledger, Temporal Context,
kế hoạch ban đầu và kết quả Audit. Đầu ra là toàn bộ `issues`; Python cấp lại ID
sau khi kiểm tra.

- 2.000 mẫu được chuyển từ Planner DPO Gold sang nhiệm vụ sửa toàn bộ kế hoạch.
- 200 mẫu mới: 50 tình huống do tác giả soạn, mỗi tình huống có 4 hard-negative.
- Split mục tiêu: train 1.760, validation 220, hidden test 220.
- Các biến thể của cùng một tình huống luôn nằm trong cùng split.

Chạy `build_planner_full_revise_dataset.py` để tạo JSONL SFT/DPO, manifest và
bundle huấn luyện từ Qwen3-8B base.

Ví dụ huấn luyện sau khi giải nén bundle:

```bash
python train_planner_full_revise_sft.py \
  --task planner \
  --model-id Qwen/Qwen3-8B \
  --train-file planner_full_revise_sft_train_1760.jsonl \
  --val-file planner_full_revise_sft_validation_220.jsonl \
  --output-dir planner_full_revise_qwen3_8b \
  --epochs 3 \
  --max-seq-length 6144 \
  --learning-rate 1e-4 \
  --gradient-accumulation-steps 16
```

`planner_full_revise_sft_test_220.jsonl` là hidden test. Không truyền file này
vào Trainer hoặc dùng để chọn checkpoint.
