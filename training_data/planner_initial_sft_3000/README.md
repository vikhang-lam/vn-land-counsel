# Planner Qwen3-8B SFT 3000

Dataset locked at 2,400 train / 300 validation / 300 hidden test.
Use `train_planner_qlora.py --task planner --train-file planner_sft_train.jsonl --val-file planner_sft_validation.jsonl --output-dir output`.
The test split is held out and must not be used for checkpoint selection. No Gold target is truncated.
