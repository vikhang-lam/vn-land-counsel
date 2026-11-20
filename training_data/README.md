# Dữ liệu SFT và DPO

"
        "- `fact_extractor_sft/`: dữ liệu Fact Extractor.
"
        "- `planner_sft/`: dữ liệu Planner ban đầu.
"
        "- `planner_dpo/`: cặp chosen/rejected của Planner.
"
        "- `planner_revise_sft_dpo/`: SFT và DPO cho bước sửa Issue.
"
        "- `claim_verifier_authored_pool/`: pool Claim Verifier đã biên soạn.
"
        "- `claim_verifier_sft/`: split train/validation/hidden-test cố định.

"
        "Hidden test được giữ nguyên để tái lập kết quả và không được trộn vào train.
"
        "Các ZIP bundle chứa bản sao adapter không nằm trong bản nộp.
"

## Planner Full Revise

`planner_full_revise_sft_dpo/`: 2.200 mẫu, split cố định 1.760/220/220. Có bản SFT và cặp DPO; runtime hiện dùng adapter SFT, checkpoint epoch 2. Không trộn test vào train.

## Planner ban đầu SFT 3000

`planner_initial_sft_3000/`: 3.000 mẫu, split cố định 2.400/300/300. Runtime dùng checkpoint epoch 2 được chọn theo validation loss. Hidden test không được trộn vào train.
