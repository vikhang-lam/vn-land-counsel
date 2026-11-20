# Tài nguyên AI chạy cục bộ

Các tài nguyên lớn được tải riêng để repository GitHub tập trung vào mã nguồn, dữ liệu và tài liệu. Tất cả đường dẫn dưới đây tính từ thư mục chứa `main.py`.

## Liên kết tải

Các liên kết dưới đây dẫn tới nguồn phát hành của từng thành phần. Adapter SFT và kho truy xuất của nhóm đã được mở **Public** trên Hugging Face và có thể tải trực tiếp. Mã nguồn hiện chưa có bước tải tự động.

| Thành phần | File hoặc nội dung cần tải | Liên kết |
| --- | --- | --- |
| Qwen3-8B | `Qwen3-8B-Q5_K_M.gguf` | [Tải GGUF từ Qwen](https://huggingface.co/Qwen/Qwen3-8B-GGUF/blob/main/Qwen3-8B-Q5_K_M.gguf) |
| Qwen3-4B | `Qwen3-4B-Q4_K_M.gguf` | [Tải GGUF từ Qwen](https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/main/Qwen3-4B-Q4_K_M.gguf) |
| Embedding | Toàn bộ model BGE-M3 | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) |
| Reranker | Toàn bộ model BGE-Reranker-v2-M3 | [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) |
| Bộ chạy | Bản llama.cpp Windows x64 có CUDA, gồm server và DLL | [Releases chính thức](https://github.com/ggml-org/llama.cpp/releases) |
| Adapter SFT của nhóm | `models/adapters/`, giữ đúng các thư mục con | [vikhanglam625/vn-land-counsel-adapters](https://huggingface.co/vikhanglam625/vn-land-counsel-adapters) — Public |
| Dataset Luật Đất Đai và Tranh Chấp | Toàn bộ `data/retrieval_store/` | [vikhanglam625/dataset-luat-dat-dai-tranh-chap](https://huggingface.co/datasets/vikhanglam625/dataset-luat-dat-dai-tranh-chap) — Public |

### Bản upload đã đối chiếu

Ngày 18/11/2026, đã đối chiếu kích thước và mã kiểm tra của từng file trên Hugging Face với bản local:

| Kho | Revision | Kết quả |
| --- | --- | --- |
| Adapter | `7c01f531e3708c59df94e3fb403db127afe2992f` | Khớp đủ 102 file, gồm 7 GGUF và 7 bộ trọng số Hugging Face; có thêm model card ở gốc kho |
| Truy xuất | `3b57dc1f7c6680a0f7d26bf13e7cdfdbd6ade477` | Khớp đủ 14 file |

Kiểm tra này xác nhận tính toàn vẹn của bản upload; chưa thay cho thử nghiệm chạy lại hệ thống sau khi tải về. Có thể thêm `--revision` cùng mã revision tương ứng vào lệnh `hf download` để lấy đúng bản này.

Tên và kiểu lượng tử hóa của hai file GGUF trên khớp cấu hình launcher. Chưa đối chiếu SHA-256 với các file cục bộ, nên các link này chưa xác nhận là đúng từng byte của bản đã dùng trong thí nghiệm. Trước khi công bố bản chạy có thể tái lập, cần ghi revision/hash của model và phiên bản llama.cpp đã kiểm thử. Trang Releases cung cấp các phiên bản bộ chạy; không mặc định mọi phiên bản mới đều tương thích với launcher hiện tại.

### Tải model công khai bằng PowerShell

Thực hiện tại thư mục gốc dự án, trong môi trường Python đã kích hoạt:

```powershell
python -m pip install -U huggingface_hub
hf download Qwen/Qwen3-8B-GGUF Qwen3-8B-Q5_K_M.gguf --local-dir "vendor/local-ai/models"
hf download Qwen/Qwen3-4B-GGUF Qwen3-4B-Q4_K_M.gguf --local-dir "vendor/local-ai/models"
hf download BAAI/bge-m3 --local-dir "vendor/huggingface/models/bge-m3"
hf download BAAI/bge-reranker-v2-m3 --local-dir "vendor/huggingface/models/bge-reranker-v2-m3"
```

Các lệnh tải toàn bộ repository BGE có thể lấy thêm các định dạng trọng số khác nên cần thêm dung lượng. Với llama.cpp, tải bộ Windows x64 CUDA và thư viện CUDA đi kèm nếu bản phát hành tách riêng; giải nén để `llama-server.exe` cùng DLL nằm trong `vendor/local-ai/llama.cpp/`. Giữ bản đang chạy ổn định để kiểm thử trước khi đổi phiên bản.

Có thể cung cấp các gói qua Google Drive hoặc kho model riêng. Giữ thông tin nguồn và tuân thủ điều kiện phân phối của từng mô hình/phần mềm. Bản GGUF và bản llama.cpp cần tương thích với adapter và định dạng preset của launcher.

## Cấu trúc sau khi giải nén

```text
vendor/
├── local-ai/
│   ├── llama.cpp/
│   │   ├── llama-server.exe
│   │   └── ... DLL đi kèm cùng bản build
│   └── models/
│       ├── Qwen3-4B-Q4_K_M.gguf
│       └── Qwen3-8B-Q5_K_M.gguf
└── huggingface/models/
    ├── bge-m3/
    └── bge-reranker-v2-m3/

models/adapters/
├── fact_qwen3_8b_lora/gguf/fact-qwen3-8b-lora-f16.gguf
├── planner_qwen3_4b_lora/gguf/planner-qwen3-4b-lora-f16.gguf
├── planner_qwen3_8b_lora/gguf/planner-qwen3-8b-lora-f16.gguf
├── planner_qwen3_8b_sft_3000_candidate/gguf/planner-qwen3-8b-sft-3000-f16.gguf
├── planner_revise_qwen3_8b_lora/gguf/planner-revise-qwen3-8b-lora-f16.gguf
├── planner_full_revise_qwen3_8b_lora/gguf/planner-full-revise-qwen3-8b-lora-f16.gguf
└── claim_verifier_qwen3_8b_lora/gguf/claim-verifier-qwen3-8b-lora-f16.gguf

data/retrieval_store/
├── README.md
├── chroma_audit.json
├── chunks/
│   ├── legal_chunks.json
│   ├── judgment_chunks.json
│   ├── precedent_chunks.json
│   └── production_chunks_manifest.json
└── chroma_db/
    ├── chroma.sqlite3
    └── ... chỉ mục vector và cache đi kèm
```

Hai thư mục embedding/reranker cần đủ trọng số, cấu hình, tokenizer và file phụ trợ. Kho ChromaDB cũng cần toàn bộ thư mục chỉ mục, không chỉ `chroma.sqlite3`.

## Những tài nguyên bắt buộc

`scripts/run_local.ps1` hiện kiểm tra hai model nền và cả bảy adapter ở trên trước khi khởi động, dù một số chỉ phục vụ cấu hình so sánh. Bộ tải dành cho bản mã nguồn hiện tại cần cung cấp đủ các file này.

Trong cấu hình mặc định `answer_8b` với `lora_8b_sft_3000`, các adapter chuyên biệt gồm Fact, Planner SFT 3000, Planner Full Revise và Claim Verifier. Không đổi tên file hoặc thay adapter bằng model nền.

Các bản Hugging Face của adapter trong `hf_adapter/` phục vụ nghiên cứu và chuyển đổi; launcher hiện trỏ tới file trong `gguf/`. Có thể cung cấp cả hai dạng, nhưng chỉ tải `adapter_model.safetensors` sẽ chưa đủ cho launcher.

## Tải adapter và kho truy xuất

Chạy tại thư mục gốc dự án sau khi cài công cụ Hugging Face:

```powershell
hf download vikhanglam625/vn-land-counsel-adapters --local-dir "models/adapters"
hf download vikhanglam625/dataset-luat-dat-dai-tranh-chap --repo-type dataset --local-dir "data/retrieval_store"
```

Hai kho công khai nên người dùng không cần được cấp quyền riêng để tải. Giữ đúng cấu trúc thư mục để launcher tìm được các file.

## Cấu hình trên máy

Launcher tạo `runtime/llama-models.ini` theo đường dẫn hiện tại mỗi lần khởi động. File này được Git bỏ qua vì chứa đường dẫn tuyệt đối. Dùng launcher thay vì gọi máy chủ trực tiếp bằng preset sao chép từ máy khác.

Các file AI và kho truy xuất đã có trên máy không bị xóa khi thêm `.gitignore`. Bản clone mới cần tải lại chúng theo hướng dẫn này.
