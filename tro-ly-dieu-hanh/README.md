# Trợ lý điều hành Hoa Huy — scaffold MVP

Phần lõi đã chạy được của agent mô tả trong
[`docs/agent-design/TRO-LY-DIEU-HANH-AGENT.md`](../docs/agent-design/TRO-LY-DIEU-HANH-AGENT.md).

Hiện thực **Ngày 1–3 của lộ trình MVP**: chỉ mục Drive, luật giải nghĩa phiên
bản, rào chắn an ninh, trích xuất text có cache, truy xuất có kiểm chứng nguồn,
và cổng phê duyệt. Luồng `LOOKUP` đã chạy được đầu-cuối.

Toàn bộ phần này **không cần LLM** — và đó là chủ đích. Nó rẻ, chạy nhanh, test
được đầy đủ, và nó quyết định chất lượng của mọi thứ phía sau: một agent truy
xuất sai tài liệu thì model có giỏi đến đâu cũng chỉ soạn ra văn bản sai một
cách trôi chảy. Nó cũng là **mốc đối chứng** — trước khi thêm model vào bước
nào, hãy đo xem bản thuần luật này trả lời đúng bao nhiêu phần trăm câu hỏi
thật. Model chỉ đáng thêm vào chỗ nó thắng được con số đó.

## Chạy thử ngay (không cần Drive)

```bash
cd tro-ly-dieu-hanh
python3 -m src.demo --all
```

Chạy 8 câu hỏi trên kho tài liệu giả và cho thấy cả bốn kiểu kết quả — kể cả
lúc agent từ chối trả lời. Xem [`HUONG-DAN-CHAY-THU.md`](HUONG-DAN-CHAY-THU.md)
để biết cách đọc kết quả và cách nối vào Drive thật.

## Đã có gì

| Thành phần | File | Trạng thái |
|------------|------|------------|
| Đọc số bản / kỳ áp dụng từ tên file | `src/core/version.py` | ✅ có test |
| Chỉ mục: phân loại, tìm kiếm, chọn bản mới nhất | `src/core/manifest.py` | ✅ có test |
| Rào chắn an ninh | `src/core/guards.py` | ✅ có test |
| Nạp và kiểm tra config | `src/core/config.py` | ✅ có test |
| S0 — quét Drive dựng chỉ mục | `src/stages/s0_index.py` | ✅ có test (Drive giả lập) |
| S1 rút gọn — bóc từ khoá theo luật | `src/core/intake.py` | ✅ có test |
| Trích xuất text + cache | `src/tools/extract.py` | ✅ có test |
| S4+S5 — truy xuất và kiểm chứng nguồn | `src/stages/s4_retrieve.py` | ✅ có test |
| S8 — cổng phê duyệt | `src/stages/s8_approve.py` | ✅ có test |
| CLI (`index`, `lookup`) | `src/main.py` | ✅ có test đầu-cuối |
| Demo với Drive giả lập | `src/demo.py` | ✅ có test |
| Luật gán docType | `config/doctypes.yaml` | ✅ có test |
| Sổ dữ kiện công ty | `state/facts.md` | 📝 cần điền |

**Chưa có (các bước tiếp theo):** S2 định tuyến 5 luồng, S3 lập kế hoạch,
S6 soạn thảo, S7 tự kiểm tra, S9 bàn giao — tức là toàn bộ phần cần LLM.

## Chạy test

Không cần cài gì thêm — test dùng `unittest` của stdlib và Drive giả lập.

```bash
cd tro-ly-dieu-hanh
python3 -m unittest discover -s tests -t .
```

184 test, chạy dưới 0,3 giây. Chạy lại sau **mọi** thay đổi config hoặc prompt —
nhóm `test_guards.py` là thứ duy nhất đảm bảo các ràng buộc an ninh còn nguyên
sau khi ai đó dọn dẹp code.

## Thiết lập để quét Drive thật

```bash
pip install -r requirements.txt
cp .env.example .env                          # điền credential
cp config/folders.example.yaml config/folders.yaml   # điền folder ID

python3 -m src.main index                            # S0: dựng chỉ mục
python3 -m src.main lookup "bảng giá pin LiFePO4 mới nhất"
```

Bước `index` in ra số tài liệu theo từng nhóm. Nếu hơn 40% rơi vào `khac`, hãy
bổ sung luật trong `config/doctypes.yaml` — chỉ mục kém phân loại thì việc tìm
kiếm sẽ kém chính xác theo.

Mã thoát của `lookup` mang ý nghĩa riêng, tiện khi gọi từ script:

| Mã | Nghĩa |
|----|-------|
| 0 | Trả lời được, kèm nguồn và link Drive |
| 2 | Câu hỏi không rút được từ khoá nào |
| 3 | Có xung đột phiên bản — cần người chọn |
| 4 | Không tìm thấy tài liệu |

Không gộp 3 và 4 thành "lỗi" là có chủ đích: "cần bạn chọn bản nào" và "không
có tài liệu này" là hai tình huống khác hẳn nhau về cách xử lý tiếp.

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
