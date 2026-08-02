# Trợ lý điều hành Hoa Huy — scaffold MVP

Phần lõi đã chạy được của agent mô tả trong
[`docs/agent-design/TRO-LY-DIEU-HANH-AGENT.md`](../docs/agent-design/TRO-LY-DIEU-HANH-AGENT.md).

Bước này hiện thực đúng phần **Ngày 1–2 của lộ trình MVP**: chỉ mục Drive, luật
giải nghĩa phiên bản, và rào chắn an ninh — tức là toàn bộ phần *không cần LLM*.
Làm xong phần này trước là có chủ đích: nó rẻ, chạy nhanh, test được đầy đủ, và
nó quyết định chất lượng của mọi thứ phía sau. Một agent truy xuất sai tài liệu
thì model có giỏi đến đâu cũng chỉ soạn ra văn bản sai một cách trôi chảy.

## Đã có gì

| Thành phần | File | Trạng thái |
|------------|------|------------|
| Đọc số bản / kỳ áp dụng từ tên file | `src/core/version.py` | ✅ có test |
| Chỉ mục: phân loại, tìm kiếm, chọn bản mới nhất | `src/core/manifest.py` | ✅ có test |
| Rào chắn an ninh | `src/core/guards.py` | ✅ có test |
| Nạp và kiểm tra config | `src/core/config.py` | ✅ có test |
| S0 — quét Drive dựng chỉ mục | `src/stages/s0_index.py` | ✅ có test (Drive giả lập) |
| Luật gán docType | `config/doctypes.yaml` | ✅ có test |
| Sổ dữ kiện công ty | `state/facts.md` | 📝 cần điền |

**Chưa có (các bước tiếp theo):** S1–S3 tiếp nhận/định tuyến/lập kế hoạch,
S4 trích xuất text, S6 soạn thảo, S7 tự kiểm tra, S8 cổng phê duyệt, S9 bàn giao.

## Chạy test

Không cần cài gì thêm — test dùng `unittest` của stdlib và Drive giả lập.

```bash
cd tro-ly-dieu-hanh
python3 -m unittest discover -s tests -t .
```

98 test, chạy dưới 0,1 giây. Chạy lại sau **mọi** thay đổi config hoặc prompt —
nhóm `test_guards.py` là thứ duy nhất đảm bảo các ràng buộc an ninh còn nguyên
sau khi ai đó dọn dẹp code.

## Thiết lập để quét Drive thật

```bash
pip install -r requirements.txt
cp .env.example .env                          # điền credential
cp config/folders.example.yaml config/folders.yaml   # điền folder ID
python3 -m src.stages.s0_index --out state/manifest.json
```

Kết quả in ra số tài liệu theo từng nhóm. Nếu hơn 40% rơi vào `khac`, hãy bổ
sung luật trong `config/doctypes.yaml` — chỉ mục kém phân loại thì việc tìm kiếm
sẽ kém chính xác theo.

### Hai service account, không dùng chung

Đây là ràng buộc bắt buộc, không phải khuyến nghị:

| Tài khoản | Scope | Được share vào |
|-----------|-------|----------------|
| `GOOGLE_SA_READ_JSON` | `drive.metadata.readonly`, `drive.readonly` | Các thư mục trong `read_roots`, quyền **Viewer** |
| `GOOGLE_SA_WRITE_JSON` | `drive.file` | **Duy nhất** thư mục `write_root`, quyền **Editor** |

Không cấp scope xoá cho tài khoản nào. Việc "agent không được xoá file" phải
được thực thi bằng phạm vi quyền OAuth, không phải bằng câu chữ trong prompt —
prompt có thể bị lách, scope thì không.

## Vì sao chỉ mục lại quan trọng đến vậy

Câu hỏi "bảng giá mới nhất đâu?" nếu đưa cho LLM cùng danh sách file sẽ đúng
phần lớn thời gian, và sai vào đúng lúc quan trọng theo cách không lặp lại được
nên không debug được.

`src/core/manifest.py` biến nó thành phép lọc-và-sắp-xếp xác định: tốn 0 token,
cho cùng kết quả mỗi lần hỏi, và **biết nói "không đủ cơ sở"**. Hai trường hợp
nó bắt buộc hỏi người thay vì đoán:

1. Hai tài liệu cùng số bản, cùng kỳ áp dụng, cùng giờ sửa.
2. Bản được chọn có ghi số bản/kỳ, nhưng một file *không* ghi gì lại được sửa
   muộn hơn — trường hợp `Bảng giá v3.2.xlsx` với `Bảng giá mới nhất.xlsx` sửa
   hôm qua. Chọn bừa cái nào cũng có thể sai.

Thứ tự ưu tiên khi so sánh nằm trong `config/doctypes.yaml` theo từng loại tài
liệu, vì không có đáp án chung: bảng giá nhìn **kỳ áp dụng** trước, mẫu văn bản
nhìn **số bản** trước. Test `test_order_by_changes_the_answer` chứng minh cùng
một tập dữ liệu cho hai kết quả khác nhau tuỳ cấu hình — nên đây là thứ phải
khai báo, không phải đoán.

## Ghi chú khi đọc code

- `src/core/` thuần tuý, không chạm mạng — vì thế mới test được đầy đủ như hiện tại.
- `GoogleDriveLister` là lớp duy nhất cần credential; nó import SDK Google bên
  trong hàm khởi tạo để phần còn lại chạy được mà không cần cài SDK.
- Mọi nội dung đọc từ Drive phải đi qua `wrap_untrusted()` trước khi vào prompt.
  Đây không phải tuỳ chọn: agent đọc tài liệu do nhiều người viết, gồm cả file
  khách và đối tác gửi tới.
- `scan_for_injection()` là lớp **phát hiện** để ghi cảnh báo, không phải lớp
  phòng thủ. Bộ mẫu nào rồi cũng có cách lách; phòng thủ thật nằm ở
  `wrap_untrusted()` và ở phạm vi quyền service account.
