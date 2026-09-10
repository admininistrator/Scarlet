# SCARLET — HƯỚNG DẪN GIAO VIỆC CHO AGENT

> **File này chỉ dành cho BẠN đọc, agent không cần.**
> Nó trả lời: *giao việc thế nào để agent không đi lạc, và làm sao biết nó đã đi lạc.*
>
> Version 1.0 · 2026-09-10 · Cập nhật khi rút ra bài học mới.

---

## MỤC LỤC

| # | Mục |
|---|---|
| 1 | [Nguyên tắc nền tảng](#1-nguyên-tắc-nền-tảng) |
| 2 | [Đơn vị giao việc](#2-đơn-vị-giao-việc) |
| 3 | [Chuẩn bị repo](#3-chuẩn-bị-repo) |
| 4 | [Nội dung `CLAUDE.md`](#4-nội-dung-claudemd) |
| 5 | [Vòng lặp một phiên](#5-vòng-lặp-một-phiên) |
| 6 | [Bộ prompt mẫu](#6-bộ-prompt-mẫu-) ⭐ |
| 7 | [Việc bạn phải tự làm](#7-việc-bạn-phải-tự-làm) |
| 8 | [Cách review](#8-cách-review) ⭐ |
| 9 | [Quản lý context](#9-quản-lý-context) |
| 10 | [Git & rollback](#10-git--rollback) |
| 11 | [Khi agent đi lạc](#11-khi-agent-đi-lạc) |
| 12 | [Nhịp độ thực tế](#12-nhịp-độ-thực-tế) |
| 13 | [Kịch bản ba phiên đầu](#13-kịch-bản-ba-phiên-đầu) |
| 14 | [Cạm bẫy phổ biến](#14-cạm-bẫy-phổ-biến) |

---

## 1. Nguyên tắc nền tảng

### 1.1 Ba vai trò, không lẫn lộn

| Vai | Ai | Làm gì | KHÔNG làm gì |
|---|---|---|---|
| **Chủ quyết định** | Bạn | Chốt ràng buộc, duyệt ADR, quyết đánh đổi, thiết kế giao diện bằng Claude Design | Viết code từng dòng |
| **Người thực thi** | Agent | Viết code, viết test, chạy DoD, báo cáo | Đổi kiến trúc, đổi phạm vi, tự quyết đánh đổi |
| **Trọng tài** | `docs/KE-HOACH.md` + `docs/tasks.md` | Nguồn sự thật khi hai bên bất đồng | — |

Khi bạn và agent bất đồng: mở kế hoạch ra. Nếu kế hoạch nói rõ → làm theo kế hoạch. Nếu kế hoạch không nói → **bạn** quyết, rồi **ghi vào Nhật ký quyết định** của `tasks.md`. Đừng để một quyết định chỉ tồn tại trong lịch sử chat — ba tuần sau không ai tìm lại được.

### 1.2 Luật một chiều

> **Agent được phép hỏi bất cứ lúc nào. Agent không được phép tự quyết bất cứ lúc nào.**

Nếu agent viết "tôi thấy cách này đơn giản hơn nên tôi đã làm theo cách đó", đó là lý do hợp lệ để bỏ toàn bộ phiên làm việc và làm lại. Không phải vì cách của nó sai — có thể đúng — mà vì lần sau nó sẽ tự quyết một chỗ mà bạn không kịp nhận ra.

### 1.3 Ba chỗ agent hay tự ý "đơn giản hoá" trong dự án này

Biết trước để nhận ra ngay:

| Chỗ | Dấu hiệu | Vì sao nó cám dỗ |
|---|---|---|
| **§7 stream resume** | Thấy `StreamingResponse` gọi thẳng LLM trong `app/api/` | Đơn giản hơn thật, và chạy được trong mọi test thủ công thông thường |
| **§8 cây message** | Thấy `ORDER BY created_at` khi dựng context | Ai cũng viết chatbot kiểu mảng; cây là ngoại lệ |
| **§12 cách ly network** | Thấy `fetcher` hoặc `sandbox` được thêm vào network `internal` | "Cho nó gọi được API nội bộ cho tiện" |

Ba chỗ này có lệnh grep ở §8.3. Chạy chúng sau mỗi phase.

---

## 2. Đơn vị giao việc

### 2.1 Mặc định: một task, một phiên, một commit

Không giao "làm hết P0 đi". Agent sẽ làm 11 task với chất lượng của task thứ 11.

### 2.2 Khi nào gộp được

| Gộp được | Điều kiện |
|---|---|
| 2–3 task nhỏ (≤ 1.5 h) cùng một tầng, không đánh 🔒 | Ví dụ: T-0.1 + T-0.9 (đều là hạ tầng repo) |
| Task và test của chính nó | Vốn đã nằm chung DoD |
| Sửa lỗi phát sinh từ task vừa xong | Cùng commit |

### 2.3 Task PHẢI làm riêng — không có ngoại lệ

| Task | Vì sao |
|---|---|
| **T-0.6** LiteLLM ↔ 9Router | Nếu hỏng thì ADR-03 phải viết lại. Cần biết chính xác nó hỏng vì cái gì |
| **T-0.8** Nginx + SSE | C1/C2 là hai lỗi im lặng. Gộp với việc khác thì không biết cái nào gây ra |
| **T-1.6** Stream producer | Một nửa cơ chế resume |
| **T-1.7** Stream consumer | Nửa còn lại. **Gộp T-1.6 và T-1.7 là sai lầm tệ nhất có thể mắc trong dự án này** — khi test đỏ, bạn không biết lỗi ở đầu ghi hay đầu đọc |
| **T-1.11** `test_resume.py` | Đây là tiêu chí nghiệm thu của cả P1 |
| **T-2.18** Test IDOR | Test bảo mật phải độc lập với code nó kiểm |
| **T-5.6** Origin phụ artifact | Sai một thuộc tính là mất toàn bộ cách ly |
| **T-6.2/6.3/6.4** SSRF | Ba lớp phòng thủ, mỗi lớp phải kiểm riêng |
| **T-7.1** Thí nghiệm Unix socket | Chặn cả P7. Có thể phải viết lại ADR-09 |
| **T-7.4** Test cách ly sandbox | Như T-2.18 |

### 2.4 Task thí nghiệm

Một số task không phải "viết code" mà là "trả lời một câu hỏi kỹ thuật". T-0.6, T-7.1 thuộc loại này. Prompt riêng ở §6.9.

Đặc điểm: **kết quả có thể là "không làm được"**, và đó là kết quả hợp lệ, không phải thất bại. Nếu agent luôn báo "làm được" cho mọi task thí nghiệm, hoặc bạn may mắn, hoặc nó đang chiều bạn.

---

## 3. Chuẩn bị repo

```bash
# 1. TRONG WSL, KHÔNG phải /mnt/c  (C35 — chậm 10-20× nếu sai)
cd ~ && mkdir scarlet && cd scarlet && git init

# 2. Tài liệu vào trước, code sau
mkdir -p docs
cp META-LAP-KE-HOACH.md KE-HOACH.md tasks.md HUONG-DAN-AGENT.md docs/
cp CLAUDE.md .                      # §4 của file này

# 3. Chứng chỉ local (T-H1)
mkcert -install
mkdir certs && cd certs
mkcert localhost "*.localhost" 127.0.0.1
mv localhost+2.pem localhost.pem
mv localhost+2-key.pem localhost-key.pem
cd ..

# 4. .wslconfig ở phía Windows: C:\Users\<ban>\.wslconfig
#    [wsl2]
#    memory=8GB
#    swap=2GB
#    → rồi chạy `wsl --shutdown` từ PowerShell

git add . && git commit -m "docs: kế hoạch, tasks, hướng dẫn agent"
```

**Commit tài liệu trước khi có dòng code nào.** Nếu sau này agent sửa kế hoạch (nó không được phép, nhưng), `git diff` sẽ chỉ ra ngay.

---

## 4. Nội dung `CLAUDE.md`

Chép nguyên văn vào `CLAUDE.md` ở gốc repo. Agent đọc file này **tự động mỗi phiên** — đây là thứ duy nhất bạn chắc chắn nó đã đọc.

Bản đầy đủ nằm ở file `CLAUDE.md` kèm theo. Nguyên tắc khi sửa nó:

| Luật | Lý do |
|---|---|
| **Giữ dưới 100 dòng** | Dài hơn thì nó loãng cùng phần còn lại của context |
| **Chỉ chứa luật, không chứa giải thích** | Giải thích ở `KE-HOACH.md`; `CLAUDE.md` trỏ tới đó bằng số mục |
| **Mỗi dòng phải kiểm chứng được** | "Viết code sạch" là vô nghĩa; "không `os.getenv` ngoài `app/config/`" thì grep được |
| **Thêm luật mới khi agent mắc lỗi lần thứ hai** | Lần thứ nhất là tai nạn, lần thứ hai là mẫu hình |

---

## 5. Vòng lặp một phiên

```
 ①  Mở phiên mới (/clear nếu phiên trước dài)
 ②  Dán prompt giao task (§6.2), kèm ID task
 ③  Agent đọc CLAUDE.md + mục KH tham chiếu + task
 ④  Agent HỎI nếu có chỗ chưa rõ  ← nếu nó không hỏi gì ở task khó, đó là dấu hiệu xấu
 ⑤  Bạn trả lời
 ⑥  Agent viết code
 ⑦  Agent tự chạy DoD
 ⑧  DoD đỏ → agent sửa → về ⑦   (tối đa 3 vòng, quá thì sang §11)
 ⑨  Agent báo cáo theo 4 phần (tasks.md §0.4)
 ⑩  BẠN review 5 phút (§8)
 ⑪  Không đạt → prompt §6.4, về ⑥
 ⑫  Đạt → bạn commit, đánh ✅ trong tasks.md
 ⑬  Sang task tiếp theo, hoặc kết thúc phiên
```

**Bước ⑩ không được bỏ.** Agent tự chấm điểm chính nó là cách nhanh nhất để tích luỹ nợ kỹ thuật vô hình. Năm phút review một task rẻ hơn ba giờ gỡ rối ở phase sau.

**Bước ④ là chỉ báo sức khoẻ.** Task T-1.7 mà agent không hỏi gì thì hoặc nó thật sự đã hiểu §7.3, hoặc nó chưa đọc. Hỏi lại nó một câu kiểm tra: *"vì sao phải XRANGE trước XREAD?"* — trả lời sai thì cho đọc lại, đừng cho viết code.

---

## 6. Bộ prompt mẫu ⭐

Chín prompt copy-paste. Điền chỗ `<...>`.

### 6.1 Bootstrap — phiên đầu tiên tuyệt đối

```
Đây là dự án Scarlet — chatbot self-host cho 15-20 người.

Đọc theo đúng thứ tự này, KHÔNG viết code:
1. CLAUDE.md
2. docs/KE-HOACH.md — đọc §0, §2, §3, §5, §6. Các §7+ đọc khi task cần.
3. docs/tasks.md — đọc §0, §2, §3.

Sau đó trả lời bốn câu, ngắn gọn:
a) Ràng buộc chi phối cả dự án là gì, và nó đổi kiến trúc ở chỗ nào?
b) Vì sao message là cây chứ không phải danh sách?
c) Ba việc mà tầng `api` KHÔNG được phép làm?
d) Task đầu tiên là gì, và nó phụ thuộc vào việc gì của tôi?

CHƯA viết code. CHƯA tạo file.
```

Nếu câu (a) trả lời sai hoặc chung chung, cho đọc lại §3 rồi hỏi lại. **Đừng bắt đầu code với một agent chưa nắm §3** — nó sẽ viết `StreamingResponse` gọi thẳng LLM ở task đầu tiên có cơ hội.

### 6.2 Giao một task

```
Task: T-<id>

Trước khi viết dòng code đầu tiên:
1. Đọc mục KH tham chiếu ghi trong task.
2. Đọc lại các luật A1-A10 trong CLAUDE.md.
3. Nếu có chỗ chưa rõ hoặc mâu thuẫn — HỎI TÔI, đừng đoán.

Rồi làm đúng phần "Việc cần làm".
Rồi chạy đúng từng dòng DoD và DÁN OUTPUT THẬT.

Báo cáo theo 4 phần ở tasks.md §0.4.
Chỉ làm task này. Không làm task khác dù thấy dễ.
```

### 6.3 Nghiệm thu

```
Tôi đang review T-<id>. Trả lời thẳng, không bào chữa:

1. Dòng DoD nào bạn CHƯA thực sự chạy? (chạy trong đầu không tính)
2. Bạn có lệch khỏi kế hoạch chỗ nào không? Lệch ở đâu, vì sao?
3. Chỗ nào trong code này bạn KHÔNG chắc chắn?
4. Nếu tôi xoá một dòng bất kỳ trong code bạn vừa viết, test nào sẽ đỏ?
   Nếu câu trả lời là "không test nào" — chỉ ra dòng đó.
```

Câu 4 là câu hữu ích nhất. Nó phát hiện code không được test che phủ mà không cần chạy công cụ coverage.

### 6.4 DoD không đạt

```
DoD của T-<id> chưa đạt:
- <dòng DoD cụ thể> → tôi chạy được kết quả: <dán output>

Đừng sửa test cho khớp code. Sửa code cho khớp DoD.
Nếu bạn cho rằng DoD viết sai — nói rõ vì sao, tôi sẽ quyết định sửa DoD hay sửa code.
```

Câu thứ hai quan trọng. Không có nó, agent sẽ nới lỏng test và báo xanh.

### 6.5 Test đỏ

```
Test <tên> đang đỏ.

Trước khi sửa:
1. Test này kiểm điều gì? Điều đó có ĐÚNG với kế hoạch không?
2. Đỏ vì code sai hay vì test sai?
3. Nếu code sai — nó sai từ task nào?

Trả lời ba câu trên trước, rồi mới sửa.
```

### 6.6 Agent đi lạc

```
Dừng lại.

Bạn đang làm <X>. Nhưng task T-<id> chỉ yêu cầu <Y>.

Trả lời:
1. Bạn đang giải quyết vấn đề gì?
2. Vấn đề đó nằm trong task này hay task khác?
3. Nếu là task khác — ghi vào Backlog của tasks.md và quay lại.

Không sửa thêm file nào cho tới khi trả lời xong.
```

### 6.7 Kết thúc phase

```
Phase <N> đã xong hết task. Trước khi sang phase sau:

1. Chạy DoD của cả phase (tasks.md, phần "DoD của phase").
   Dán output từng dòng.
2. Chạy: make test && make lint && make check-hardcode && docker compose ps
3. Chạy ba lệnh grep ở HUONG-DAN-AGENT.md §8.3. Dán output.
4. Trả lời:
   - Chỗ nào trong phase này bạn làm khác kế hoạch? Đã ghi vào Nhật ký quyết định chưa?
   - Ước lượng thực tế so với ước lượng trong tasks.md chênh bao nhiêu %?
   - Có cạm bẫy nào THỰC TẾ vấp phải mà kế hoạch chưa ghi? Đề xuất bổ sung.
   - Task nào của phase sau nên đổi ước lượng dựa trên tốc độ thật vừa đo được?

CHƯA bắt đầu phase sau.
```

Câu cuối cùng của mục 4 là cách bạn giữ cho ước lượng của các phase sau không phải con số bịa.

### 6.8 Mở rộng phase chưa chi tiết

```
S��p bắt đầu Phase <N>. Trong docs/tasks.md phase này mới chỉ có bảng/gạch đầu dòng.

Mở rộng T-<N>.1 … T-<N>.<k> thành task đầy đủ 7 trường, theo ĐÚNG mẫu của P0-P2.

Yêu cầu:
- DoD phải là lệnh chạy được, không phải mô tả. Tự kiểm mỗi DoD:
  "DoD này có thể SAI không?" Không thể sai = vô dụng = viết lại.
- Cạm bẫy phải dựa trên những gì THỰC TẾ đã vấp ở P0-P<N-1>,
  không phải lý thuyết chép từ kế hoạch.
- Ước lượng theo tốc độ thật đã đo được ở các phase trước, KHÔNG dùng lại
  con số trong bảng §2 — con số đó viết khi chưa biết gì.
- Giữ nguyên ID task.
- Đánh dấu 🔒 cho task rủi ro cao.

Ghi đè vào docs/tasks.md. CHƯA viết code.
```

### 6.9 Task thí nghiệm

```
Đây là TASK THÍ NGHIỆM: T-<id>.

Mục tiêu không phải viết code sản phẩm, mà trả lời một câu hỏi:
<câu hỏi, ví dụ: "worker có gọi được sandbox qua Unix socket khi
 network_mode: none không?">

Yêu cầu:
1. Viết mã tối thiểu để trả lời câu hỏi. Vứt đi sau cũng được.
2. Dán output thật chứng minh câu trả lời.
3. "KHÔNG LÀM ĐƯỢC" là câu trả lời hợp lệ và hữu ích. Đừng cố cho ra
   kết quả tôi muốn nghe.
4. Nếu không làm được: liệt kê phương án thay thế kèm đánh đổi,
   và ghi rõ ADR nào phải viết lại.

Chưa đụng vào code sản phẩm.
```

---

## 7. Việc bạn phải tự làm

Đã liệt kê đầy đủ ở `tasks.md` §3 (T-H1…T-H12 và T-HD1…T-HD7). Ba điều bổ sung:

| Việc | Vì sao agent không làm được |
|---|---|
| **Quyết định đánh đổi** | Nó không biết bạn chịu được rủi ro tới đâu |
| **Thiết kế giao diện** | Bạn đã chọn Claude Design; agent chỉ nối dây |
| **Đọc báo cáo và nói "không đạt"** | Đây là việc duy nhất không uỷ quyền được |

**Nhắc riêng về T-H8 (SMTP thật):** cho tới khi có, đặt `REGISTRATION_MODE=invite`. Mailpit không gửi thư ra ngoài — người thật sẽ không nhận được mail xác thực và bạn sẽ tưởng tính năng hỏng.

---

## 8. Cách review

### 8.1 Checklist 5 phút

Chạy sau mỗi task. Nếu bất kỳ dòng nào sai → không nghiệm thu.

- [ ] Báo cáo có **output thật** của lệnh DoD, không phải mô tả ("đã test kỹ" = không đạt)
- [ ] `git diff --stat` — số file sửa có **hợp lý** với phạm vi task không? Sửa 18 file cho một task 2 giờ là dấu hiệu xấu
- [ ] Có file nào trong `docs/` bị sửa không? Agent **không được** sửa kế hoạch
- [ ] Có biến `.env` mới không? Có trong `Settings` **và** `.env.example` không?
- [ ] Test mới có thể **đỏ** không? Xoá thử một dòng code chính → test phải đỏ
- [ ] Có `TODO` / `FIXME` / `pass  # tạm` nào không?
- [ ] Task có 🔒 mà commit chứa cả việc khác không?

### 8.2 Đọc code ở đâu

Không đọc hết. Đọc ba chỗ:

1. **Đường đi chính** của tính năng — từ endpoint tới DB
2. **Xử lý lỗi** — `except` nào nuốt lỗi im lặng?
3. **Test** — nó khẳng định điều gì, và điều đó có đúng ý task không?

### 8.3 Ba lệnh grep chống rò rỉ kiến trúc

Chạy sau mỗi phase, không phải sau mỗi task.

```bash
# ① API không được gọi model/tool trực tiếp (A1, §5.3)
grep -rnE "litellm|openai|AsyncOpenAI|anthropic" backend/app/api/
# → PHẢI rỗng

# ② Không dựng context bằng danh sách phẳng (A2, C11)
grep -rn "ORDER BY created_at" backend/app/llm/ backend/app/db/repositories/messages.py
# → chỉ được xuất hiện trong recursive CTE của get_path, không nơi nào khác

# ③ Cách ly network còn nguyên (§12.2, ADR-09)
grep -A15 -E "^  (fetcher|sandbox):" docker-compose.yml | grep -E "internal|network_mode"
# → fetcher: chỉ thấy `egress`.  sandbox: chỉ thấy `network_mode: "none"`
```

Thêm hai lệnh nữa từ `make check-hardcode` (§19.4 của kế hoạch) là đủ bộ.

### 8.4 Dấu hiệu agent đang chiều bạn

| Dấu hiệu | Nghĩa là |
|---|---|
| Không hỏi gì ở task khó | Chưa đọc kế hoạch, hoặc đang đoán |
| Mọi DoD đều xanh ngay lần đầu, kể cả task 4 giờ | Có thể đã nới test |
| Báo cáo dài, nhiều tính từ, ít output | Đang lấp chỗ trống |
| "Tôi đã cải tiến thêm..." | Đã làm ngoài phạm vi, và bạn chưa review phần đó |
| Trả lời prompt §6.3 câu 3 là "tôi chắc chắn về mọi thứ" | Dấu hiệu xấu rõ ràng nhất |

---

## 9. Quản lý context

### 9.1 Dấu hiệu context đã hỏng

| Dấu hiệu | Xử lý |
|---|---|
| Quên luật đã nhắc 20 lượt trước | `/clear`, bootstrap lại bằng §6.1 rút gọn |
| Đề xuất lại phương án đã bị loại trong ADR | `/clear` + trỏ đúng số ADR |
| Viết lại code đã viết ở task trước | `/clear`, nhắc đọc file hiện có trước |
| Trả lời chung chung, "về cơ bản là..." | `/clear` |
| Bịa tên hàm không tồn tại trong repo | `/clear` ngay |

### 9.2 Khi nào `/clear`

- **Luôn luôn** giữa hai task khác tầng (backend → frontend)
- **Luôn luôn** sau khi kết thúc một phase
- Sau 3 vòng sửa DoD không xong
- Khi thấy bất kỳ dấu hiệu ở §9.1

### 9.3 Giữ phiên gọn

- Một task một phiên là mặc định
- Không dán cả `KE-HOACH.md` vào chat — bảo nó đọc mục cụ thể
- Không dán log dài; dán 20 dòng quanh chỗ lỗi
- Không thảo luận thiết kế trong phiên đang code; tách phiên riêng

---

## 10. Git & rollback

### 10.1 Quy ước

```
<loại>(T-<id>): <mô tả ngắn>

feat(T-1.7): SSE consumer đọc Redis Stream theo cursor
fix(T-1.7): XRANGE dùng dấu ( thay vì [ để không lặp bản ghi
test(T-1.11): script kiểm resume 6 kịch bản
docs(NQ-04): ghi quyết định về Unix socket cho sandbox
```

Một task = một commit. Task 🔒 = một commit **chỉ** chứa task đó.

### 10.2 Nhánh

Với dự án một người, làm thẳng trên `main` là hợp lý — trừ ba trường hợp cần nhánh riêng:

- Task thí nghiệm (T-0.6, T-7.1) — có thể phải vứt đi
- Task 🔒 rủi ro cao ở P1
- Bất cứ lúc nào bạn muốn thử một hướng mà chưa chắc

### 10.3 Rollback

```bash
git log --oneline | head -20             # tìm commit tốt cuối cùng
git revert <sha>                         # đã push / muốn giữ lịch sử
git reset --hard <sha>                   # chưa push, muốn xoá hẳn
git diff <sha> HEAD -- backend/app/streaming/   # xem đã đổi gì ở một tầng
```

**Tag ở mỗi mốc**, để lùi về một điểm đã biết là chạy được:

```bash
git tag -a M3 -m "Chat lõi + resume chạy được"
```

---

## 11. Khi agent đi lạc

| Dấu hiệu | Chẩn đoán | Xử lý |
|---|---|---|
| Sửa nhiều file hơn hẳn phạm vi task | Đang refactor không được yêu cầu | §6.6 → `git checkout .` → giao lại |
| "Tôi đã đơn giản hoá X cho dễ hiểu" | Vi phạm A10 | Reject cả phiên. Hỏi X là gì, ghi Backlog nếu hợp lý |
| Test xanh nhưng thao tác tay hỏng | Test đang mock chính thứ cần kiểm | Yêu cầu test đi qua đường thật; xem lại DoD |
| Sửa test thay vì sửa code | Đang tối ưu cho "xanh" | §6.4, nhấn mạnh câu thứ hai |
| Ba vòng sửa DoD chưa xong | Task quá lớn hoặc kế hoạch mơ hồ | `/clear`, tách task nhỏ hơn, cập nhật `tasks.md` |
| Đề xuất thêm thư viện không có trong kế hoạch | Có thể hợp lý, nhưng phải qua bạn | Hỏi: giải quyết vấn đề gì? đã cân nhắc gì? → nếu nhận, viết ADR |
| Code chạy nhưng bạn không hiểu | Quá phức tạp so với vấn đề | Yêu cầu giải thích 5 dòng; không giải thích được → viết lại |
| Nói "không thể làm được" cho một task trong kế hoạch | Có thể đúng, có thể lười | Yêu cầu: đã thử gì, lỗi cụ thể là gì, phương án thay thế nào |

---

## 12. Nhịp độ thực tế

Không có deadline (R19). Nhưng nhịp độ đều quan trọng hơn tốc độ cao — dự án một người chết vì mất động lực, không vì chậm.

### 12.1 Một tuần điển hình

| Buổi | Việc | Vì sao |
|---|---|---|
| 2 buổi × 2–3 h | Giao task, review, commit | Buổi ngắn hơn 90 phút thì phần lớn thời gian là khởi động lại context |
| 1 buổi × 1 h | Đọc lại `tasks.md`, cập nhật trạng thái, dọn Backlog | Không làm thì `tasks.md` lệch khỏi thực tế sau 2 tuần và thành vô dụng |

### 12.2 Ba quy tắc giữ nhịp

1. **Kết thúc mỗi buổi ở trạng thái xanh.** Không để `make test` đỏ qua đêm — mở lại máy hôm sau với test đỏ là cách nhanh nhất để bỏ dở.
2. **Sau mỗi phase, dùng thật một tuần trước khi sang phase sau.** Bạn sẽ tìm ra 3–5 thứ mà không test nào bắt được.
3. **Nếu chán một phase, đổi sang phase độc lập.** P5 và P6 hoán vị được. P8 làm sớm cũng được nếu nó vui hơn.

---

## 13. Kịch bản ba phiên đầu

### Phiên 1 (~2 h) — Bootstrap + T-0.1 → T-0.3

```
1. Dán §6.1. Đọc bốn câu trả lời. Câu (a) sai → cho đọc lại §3, hỏi lại.
2. §6.2 với T-0.1. Review.
3. §6.2 với T-0.2. Kiểm `which python` trỏ vào .venv.
4. §6.2 với T-0.3. ⭐ DoD quan trọng: unset một biến → app không boot.
5. Commit từng task. Kết thúc phiên.
```

**Xong phiên này bạn có:** repo có cấu trúc, backend chạy, cấu hình fail-fast.
**Cần chuẩn bị trước:** T-H4 (`.wslconfig`, repo trong WSL).

### Phiên 2 (~2.5 h) — T-0.4 → T-0.6 (mốc M1)

```
1. /clear. §6.2 với T-0.4.
2. §6.2 với T-0.5. Kiểm `\d messages` — parent_id phải nullable.
3. /clear (đổi tầng).
4. §6.9 (task thí nghiệm) với T-0.6.  ← đây là mốc M1
   Nếu 9Router không gọi được từ container: DỪNG, xử lý cho xong.
   Đừng đi tiếp với M1 đỏ.
```

**Xong phiên này bạn có:** M1 — biết chắc kiến trúc provider chạy được.
**Cần chuẩn bị trước:** T-H2 (9Router chạy), T-H3 (API key).

### Phiên 3 (~2 h) — T-0.8 (mốc M2) + T-0.7

```
1. /clear. §6.2 với T-0.8.
2. ⭐ Tự tay chạy `curl -kN https://localhost/api/v1/_debug/sse`.
   PHẢI thấy chữ ra từng dòng. Nếu ra một cục → C1 chưa được xử lý,
   không nghiệm thu dù agent nói đã xong.
3. §6.2 với T-0.7.
4. Tag: git tag -a M2 -m "SSE chảy qua Nginx"
```

**Xong phiên này bạn có:** M2 — đường ống streaming đã thông. Từ đây P1 xây trên nền chắc.
**Cần chuẩn bị trước:** T-H1 (mkcert).

> Sau ba phiên này, nhịp đã ổn định: mở phiên → §6.2 → review → commit. Từ P1 trở đi, mỗi task 🔒 nên là một phiên riêng.

---

## 14. Cạm bẫy phổ biến khi làm việc với agent

| # | Cạm bẫy | Cách tránh |
|---|---|---|
| 1 | Giao nhiều task một lúc "cho nhanh" | Một task một phiên. Chất lượng tụt theo cấp số nhân từ task thứ ba |
| 2 | Tin "đã test kỹ" thay vì đọc output | §8.1 dòng đầu tiên |
| 3 | Để agent tự sửa `tasks.md` hoặc `KE-HOACH.md` | Chỉ bạn sửa, trừ mục Backlog và Nhật ký quyết định |
| 4 | Không `/clear` giữa các tầng | §9.2 |
| 5 | Chấp nhận "tôi đã cải tiến thêm" | Ngoài phạm vi = chưa review = nợ kỹ thuật |
| 6 | Bỏ qua task nhàm chán (test, backup, eval) | Đó thường là task cứu bạn ở P9 |
| 7 | Sửa DoD cho khớp code | §6.4 |
| 8 | Để test đỏ qua đêm | §12.2 |
| 9 | Bắt đầu P1 khi M1 hoặc M2 còn đỏ | Cả P1 sẽ xây trên nền hỏng |
| 10 | Mời người thật vào trước M4 | Chưa có quota = ai cũng tiêu tiền của bạn |
| 11 | Thiết kế giao diện ở P1 "cho đẹp luôn" | Làm hai lần. Giao diện là P3, và là việc của bạn với Claude Design |
| 12 | Quên cập nhật trạng thái trong `tasks.md` | Sau 2 tuần file lệch khỏi thực tế và bạn sẽ bỏ dùng nó |

---

*Hết `HUONG-DAN-AGENT.md` v1.0. Bổ sung cạm bẫy mới vào §14 và luật mới vào `CLAUDE.md` sau mỗi phase.*
