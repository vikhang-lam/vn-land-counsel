# Kho dữ liệu truy xuất

Thư mục này chứa dữ liệu đã được chuẩn bị cho bước tìm kiếm căn cứ pháp luật. Chương trình sử dụng kho ở chế độ chỉ đọc trong quá trình trả lời câu hỏi.

## Thành phần

- `chunks/`: các đoạn văn bản pháp luật được phân chia theo cấu trúc điều, khoản và điểm; kèm dữ liệu bản án, án lệ đã chuẩn bị.
- `chunks/legal_chunks.json`: nội dung và siêu dữ liệu của các đoạn văn bản pháp luật.
- `chunks/production_chunks_manifest.json`: số lượng bản ghi, mã kiểm tra tệp nguồn và kết quả kiểm tra cấu trúc dữ liệu.
- `chroma_db/`: cơ sở dữ liệu vector dùng cho tìm kiếm ngữ nghĩa.
- `chroma_audit.json`: kết quả đối chiếu mã định danh, văn bản và siêu dữ liệu sau khi xây dựng cơ sở dữ liệu.

## Thông tin dữ liệu

- 10.125 đoạn dữ liệu pháp luật được tạo từ 40 văn bản.
- Mỗi bản ghi pháp luật sử dụng cùng một cấu trúc gồm 23 trường dữ liệu.
- Thông tin nhận diện văn bản và thời gian hiệu lực được đối chiếu với dữ liệu trong `chunks/legal_chunks.json`.
- Kho tìm kiếm có 13.697 bản ghi sau bước loại trùng và loại nội dung không hợp lệ.
- Trường số điều không gộp nhiều điều luật vào cùng một nhãn.

Không chỉnh sửa trực tiếp các tệp trong thư mục này. Khi cần xây dựng lại kho truy xuất, phải thực hiện từ dữ liệu nguồn và kiểm tra lại số lượng, mã định danh cùng siêu dữ liệu trước khi sử dụng.
