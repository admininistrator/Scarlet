# META — QUY TRÌNH LẬP KẾ HOẠCH PHẦN MỀM

> **File này không phải kế hoạch của một dự án cụ thể.** Nó mô tả *cách viết ra* bộ
> tài liệu kế hoạch, để bạn đưa cho AGENT và bảo: "làm y như thế này cho app mới của tôi".
>
> Rút ra từ bộ tài liệu dự án LifeLog (`KE-HOACH-v3.md` + `tasks.md` + `HUONG-DAN-AGENT.md`).
> Version 1.0 · 2026-08-16

---

## MỤC LỤC

- [1. Bộ ba tài liệu và vai trò](#1-bộ-ba-tài-liệu-và-vai-trò)
- [2. Chín nguyên tắc viết ⭐](#2-chín-nguyên-tắc-viết-)
- [3. Khung chuẩn: `KE-HOACH.md`](#3-khung-chuẩn-ke-hoachmd)
- [4. Khung chuẩn: `tasks.md`](#4-khung-chuẩn-tasksmd)
- [5. Khung chuẩn: `HUONG-DAN-AGENT.md`](#5-khung-chuẩn-huong-dan-agentmd)
- [6. Quy trình 4 giai đoạn](#6-quy-trình-4-giai-đoạn)
- [7. Prompt copy-paste ⭐](#7-prompt-copy-paste-)
- [8. Bộ câu hỏi phỏng vấn chuẩn](#8-bộ-câu-hỏi-phỏng-vấn-chuẩn)
- [9. Checklist nghiệm thu bản kế hoạch](#9-checklist-nghiệm-thu-bản-kế-hoạch)
- [10. Mười hai dấu hiệu kế hoạch kém](#10-mười-hai-dấu-hiệu-kế-hoạch-kém)

---

## 1. Bộ ba tài liệu và vai trò

Ba file, ba câu hỏi khác nhau. **Không gộp.**

| File | Trả lời | Ai đọc | Nhịp cập nhật |
|---|---|---|---|
| `docs/KE-HOACH.md` | **Cái gì** và **tại sao** — thiết kế, quyết định, đánh đổi | Người + agent (đọc theo mục) | Hiếm; đổi = viết ADR |
| `docs/tasks.md` | **Thứ tự nào** và **xong khi nào** | Agent (mỗi task) | Mỗi commit |
| `docs/HUONG-DAN-AGENT.md` | **Giao việc thế nào** | Chỉ người | Khi rút ra bài học mới |
| `CLAUDE.md` (gốc repo) | Luật rút gọn agent đọc tự động mỗi phiên | Agent | Hiếm |

**Vì sao tách:** kế hoạch dài 2000+ dòng không dùng làm hàng đợi công việc được — agent nạp hết vào context sẽ loãng và bỏ sót. Ngược lại, `tasks.md` không giải thích được *tại sao* chọn kiến trúc này, nên agent sẽ tự ý "đơn giản hoá" khi gặp khó.

---

## 2. Chín nguyên tắc viết ⭐

Đây là phần cốt lõi của file này. Nếu chỉ đọc một mục, đọc mục này.

### N1 — Mở đầu bằng ràng buộc và phi-mục-tiêu, không bằng tính năng

Danh sách tính năng ai cũng viết được. Thứ quyết định kiến trúc là **ràng buộc**: ngân sách, thiết bị đang có, kỹ năng, thời gian, dữ liệu sẵn có, nơi triển khai.

```
❌ "App sẽ có: đăng nhập, dashboard, báo cáo, thông báo..."
✅ "Ràng buộc: dev trên Windows không có Mac → loại nhánh native iOS.
    Không chi tiền Apple → PWA, chốt.
    Không có dữ liệu quá khứ → đảo thứ tự roadmap (§3)."
```

**Phi-mục-tiêu quan trọng ngang mục tiêu.** Viết rõ "v1 KHÔNG làm: X, Y, Z" chặn được scope creep hiệu quả hơn mọi lời nhắc nhở.

### N2 — Mỗi quyết định công nghệ phải có cột "đã cân nhắc"

Bảng ADR ba cột: **Quyết định · Lý do · Đã cân nhắc (và vì sao loại)**.

Cột thứ ba là cột giá trị nhất. Không có nó, sáu tháng sau bạn (hoặc agent) sẽ đề xuất lại đúng phương án đã bị loại, và không ai nhớ vì sao đã loại.

```
❌ | Postgres + pgvector | Phù hợp, dễ dùng |
✅ | Postgres + pgvector làm DB duy nhất | Filter thời gian/entity JOIN trực
     tiếp trong cùng câu truy vấn vector; quy mô cá nhân < 500k chunk thừa sức
   | Qdrant (thêm hạ tầng, thêm bug đồng bộ 2 nguồn); Pinecone (phụ thuộc cloud) |
```

### N3 — Phản biện yêu cầu của người dùng khi cần

Kế hoạch tốt không phải kế hoạch chép lại yêu cầu. Khi một yêu cầu sẽ gây hại, **nói rõ, giải thích tại sao, đề xuất phương án thay thế** — rồi vẫn để người dùng quyết.

```
✅ Mẫu:
   "Ý tưởng lưu API kèm metadata vào DB: ĐÚNG hướng, giữ nguyên.
    Nhưng khâu 'LLM format dữ liệu gửi tới UI' NÊN SỬA, vì:
    ① chậm và tốn tiền ② không tất định ③ không unit-test được
    ④ mở thêm bề mặt prompt injection.
    Thay bằng: transform tất định bằng JMESPath; LLM chỉ chọn tool và viết lời văn."
```

Đánh dấu rõ: `✅ giữ nguyên` / `⚠️ nên sửa` / `⛔ nên bỏ` + lý do cụ thể, không chung chung.

### N4 — Ràng buộc quyết định thứ tự phase, không phải "logic kỹ thuật đẹp"

Thứ tự mặc định (hạ tầng → backend → frontend → tính năng) thường sai. Hỏi hai câu:

1. **Cái gì hữu ích sớm nhất?** — để không mất động lực.
2. **Cái gì cần dữ liệu/thông tin mà bây giờ chưa có?** — đẩy về sau.

```
✅ Ví dụ thật: "Không có dữ liệu quá khứ → tính năng tìm kiếm vô giá trị trong
   4-8 tuần đầu. Vì vậy đảo thứ tự: chat + nhắc hẹn + kênh nhập liệu trước
   (hữu ích ngay cả khi kho rỗng); retrieval xây ở Phase 3 khi đã có gì để tìm."
```

Và ngược lại: một số task **phải kéo lên sớm** dù không cấp bách, nếu phát hiện muộn thì đắt. Ví dụ kiểm tra build ARM ở Phase 0 thay vì Phase 7 — vì phát hiện thư viện không chạy ARM khi đã viết xong nửa app đồng nghĩa phải đổi thư viện.

### N5 — Tiêu chí thành công phải có số

```
❌ "Tìm kiếm chính xác, phản hồi nhanh, dễ mở rộng"
✅ | recall@10 ≥ 0.80 và không nhóm nào < 0.60 | đo ở Phase 3 |
   | p95 prompt → token đầu ≤ 4 s                | đo ở Phase 3 |
   | thêm 1 API ngoài ≤ 30 phút, không sửa code core | đo ở Phase 5 |
```

Mỗi tiêu chí ghi rõ **đo khi nào**. Tiêu chí không có mốc đo là tiêu chí không bao giờ được đo.

### N6 — Nêu cạm bẫy cụ thể, không phải lời khuyên chung

```
❌ "Cần chú ý cấu hình proxy cho phù hợp"
✅ "SSE qua Nginx: thiếu `proxy_buffering off` thì streaming sẽ IM LẶNG rồi trả
    nguyên khối khi xong. Đây là lỗi hay gặp nhất khi đặt Nginx trước FastAPI.
    Test bằng: curl -N ... → phải thấy dòng chảy ra TỪNG CÁI."
```

Cạm bẫy tốt luôn có ba phần: **hiện tượng** · **nguyên nhân** · **cách kiểm chứng**.

### N7 — Phụ lục chứa thứ copy-paste được, không phải lý thuyết

Phụ lục là nơi đặt: DDL đầy đủ, JSON Schema, `.env` mẫu, file config tham chiếu (nginx.conf, docker-compose.yml), prompt template. Người đọc phải **dán được vào repo và chạy**, không phải đọc rồi tự viết lại.

### N8 — Rủi ro có mức độ và ứng phó cụ thể

```
❌ | Có thể gặp lỗi kỹ thuật | Trung bình | Cần kiểm tra kỹ |
✅ | Máy chủ tắt/mất điện → nhắc hẹn không bắn | Cao | Scheduler polling đã
     idempotent nên bật lại bắn bù (cờ fire_missed_within_minutes, mặc định 120).
     Cân nhắc UPS. Chấp nhận: đây là đánh đổi của self-host. |
```

Ứng phó phải là **hành động**, và được nhắc lại trong task tương ứng.

### N9 — Kết thúc bằng câu hỏi mở

Mục cuối luôn là **"Câu hỏi cần bạn quyết"** — liệt kê những gì agent không quyết được: ngân sách, nhà cung cấp, đánh đổi, phạm vi. Mỗi câu ghi rõ **nó chặn task nào**.

Kế hoạch không có mục này là kế hoạch đã đoán thay người dùng ở đâu đó.

---

## 3. Khung chuẩn: `KE-HOACH.md`

Mục lục cố định. Bỏ mục nào phải nói rõ vì sao.

| # | Mục | Bắt buộc chứa |
|---|---|---|
| 0 | **Đọc trước khi thực thi (dành cho AGENT)** | 8–10 nguyên tắc kiến trúc, đánh số, mỗi cái 1–2 dòng. Đây là thứ sẽ chép vào `CLAUDE.md`. |
| 1 | **Bối cảnh & tầm nhìn** | Vấn đề (mô tả bằng tình huống thật, không trừu tượng) · giải pháp · 5–6 nguyên tắc sản phẩm kèm **hệ quả kỹ thuật** của từng cái |
| 2 | **Ràng buộc, phi-mục-tiêu, tiêu chí thành công** | Bảng ràng buộc → ảnh hưởng thiết kế · danh sách "v1 KHÔNG làm" · bảng tiêu chí có số và mốc đo |
| 3 | **Chiến lược cho ràng buộc chi phối nhất** ⭐ | Chỉ có khi tồn tại một ràng buộc định hình cả roadmap (kho rỗng, deadline cứng, không có dữ liệu, phải tương thích hệ cũ). Nếu có → viết hẳn một mục, vì nó quyết định thứ tự phase |
| 4 | **Use cases + acceptance criteria** | Mỗi UC: actor, kênh, luồng, **AC dạng checkbox kiểm chứng được** |
| 5 | **Kiến trúc tổng thể** | Sơ đồ ASCII (không phải mermaid — agent đọc ASCII ổn định hơn) · bảng ranh giới trách nhiệm "được phép / không được phép" từng lớp |
| 6 | **ADR** | Bảng 3 cột theo [N2](#n2--mỗi-quyết-định-công-nghệ-phải-có-cột-đã-cân-nhắc). 10–15 dòng |
| 7…N | **Các subsystem cốt lõi** | Mỗi subsystem một mục. Bắt đầu bằng *vì sao subsystem này khó/khác thường*, rồi mới đến thiết kế. Đánh ⭐ cho phần cốt lõi |
| — | **Mô hình dữ liệu & schema** | DDL đầy đủ chạy được + mục "ghi chú thiết kế" giải thích các trường không hiển nhiên |
| — | **Triển khai** | Kiến trúc hạ tầng · **bảng chi phí ước tính** · **bảng bẫy tiền/bẫy vận hành cần tránh** · bảo mật · quy trình deploy |
| — | **API surface** | Danh sách endpoint đầy đủ — đây là hợp đồng cho frontend |
| — | **Chống hardcode & cấu hình** | Bảng "thứ gì sống ở đâu, thêm mới thế nào" + 3–4 luật |
| — | **Bảo mật & quyền riêng tư** | Bảng hạng mục → yêu cầu |
| — | **Observability, Eval & chi phí** | Cách đo chất lượng bằng số; nếu sản phẩm có thành phần ML/AI thì mục này bắt buộc |
| — | **Cấu trúc repo** | Cây thư mục có chú thích |
| — | **Roadmap** | Phase có DoD riêng, ước lượng, và **lý do thứ tự** |
| — | **Rủi ro & câu hỏi mở** | Theo [N8](#n8--rủi-ro-có-mức-độ-và-ứng-phó-cụ-thể) và [N9](#n9--kết-thúc-bằng-câu-hỏi-mở) |
| — | **Phụ lục** | Theo [N7](#n7--phụ-lục-chứa-thứ-copy-paste-được-không-phải-lý-thuyết) |

**Đầu file:** nếu là bản v2 trở lên, thêm bảng **"Thay đổi so với bản trước"** — thay đổi gì, ảnh hưởng mục nào.

**Độ dài tham chiếu:** app cỡ vừa (~6 tháng làm một mình) → 1500–2500 dòng. Ngắn hơn 800 dòng thường là thiếu chi tiết thực thi được; dài hơn 3500 dòng thường là đã lẫn nội dung của `tasks.md` vào.

---

## 4. Khung chuẩn: `tasks.md`

### 4.1 Mục lục

```
0. Cách dùng file này    — giao thức cho agent, 5-6 luật, ký hiệu trạng thái, quy ước
1. Vì sao có file này    — ghi lại lý do tồn tại để sau không ai xoá nhầm
2. Tiến độ tổng quan     — bảng phase × số task × ước lượng × trạng thái + mốc quan trọng
3. Việc của NGƯỜI (T-H)  — thứ agent không làm được, ghi rõ chặn task nào
4..N. Task theo phase
N+1. Backlog             — ý tưởng nảy ra giữa chừng, KHÔNG code ngay
N+2. DoD chung           — áp dụng cho mọi task
N+3. Nhật ký quyết định
```

### 4.2 Mẫu một task — copy chính xác cấu trúc này

```markdown
### T-1.6 — TemporalResolver tiếng Việt
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.4 · **Ước lượng:** 4h
- **KH:** §10, §8.9 · **Rủi ro:** nguồn bug lớn nhất của dự án
- **Việc:**
  - [ ] `app/rag/temporal.py`: `resolve(text, ref_time, tz) -> (start, end, precision)`
  - [ ] Rule-based trước cho: <liệt kê cụ thể, không "các trường hợp phổ biến">
  - [ ] Không khớp rule → trả `precision='unknown'`, để tầng trên xử lý
- **Xong khi (DoD):**
  - [ ] `tests/rag/test_temporal.py` có ≥ 50 case, tất cả xanh
  - [ ] "hè năm ngoái" (ref = 2026-08) → `(2025-06-01, 2025-08-31, season)`
  - [ ] Case mơ hồ trả `unknown`, **không đoán bừa một ngày**
- **Cạm bẫy:** mốc so sánh là `captured_at` của event, KHÔNG phải thời điểm chạy model.
```

**Bảy trường, không thiếu trường nào:**

| Trường | Quy tắc |
|---|---|
| Trạng thái | ☐ chưa · 🔄 đang · 🚧 BLOCKED (kèm lý do + cần quyết định gì) · ✅ xong · ⏭️ bỏ qua (kèm ADR) |
| Phụ thuộc | ID task, không phải mô tả |
| Ước lượng | 1–4 giờ. **Task > 1 buổi phải tách nhỏ** |
| KH tham chiếu | 1–3 mục. Nhiều hơn 3 = task quá lớn |
| Việc cần làm | Checkbox, cụ thể tới mức tên file/hàm |
| **Xong khi (DoD)** | ⭐ **Lệnh chạy được hoặc hành vi quan sát được.** Không bao giờ là mô tả |
| Cạm bẫy | Chỉ khi có thật. Không bịa cho đủ trường |

### 4.3 Luật vàng của DoD

```
❌ "Hoạt động đúng"  /  "Đã test kỹ"  /  "Xử lý được các trường hợp lỗi"
✅ "curl -N http://localhost/api/v1/_debug/sse → dòng chảy ra TỪNG CÁI,
    KHÔNG phải một cục sau 5 giây"
✅ "Chạy 2 worker song song → chỉ bắn 1 lần"
✅ "Reprocess event không đổi nội dung → 0 lời gọi API embedding (kiểm bằng log)"
✅ "Xoá 1 biến bắt buộc trong .env → app KHÔNG boot, in đúng tên biến thiếu"
```

Cách kiểm nhanh: **DoD này có thể sai không?** Nếu không thể sai thì nó vô dụng.

### 4.4 Chi tiết đến đâu

| Phase | Mức chi tiết |
|---|---|
| Phase đầu (0 → ~1/3 roadmap) | **Đầy đủ 7 trường** |
| Phase giữa | Bảng: ID · task · phụ thuộc · KH · ước lượng |
| Phase cuối | Danh sách gạch đầu dòng |

**Vì sao:** sau vài phase bạn sẽ biết những điều hôm nay chưa biết. Task chi tiết viết sẵn cho phase cuối gần như chắc chắn phải viết lại — viết bây giờ là lãng phí. Có prompt riêng để mở rộng khi tới nơi ([§7.4](#74-prompt-mở-rộng-phase-chưa-chi-tiết)).

---

## 5. Khung chuẩn: `HUONG-DAN-AGENT.md`

Ngắn hơn hai file kia. Mục lục:

```
1. Nguyên tắc nền tảng      — agent viết code, người sở hữu quyết định; 3 vai trò
2. Đơn vị giao việc         — từng task; bảng task nào gộp được / phải làm riêng
3. Chuẩn bị repo
4. Nội dung CLAUDE.md       — copy nguyên văn
5. Vòng lặp một phiên       — sơ đồ 13 bước
6. Bộ prompt mẫu ⭐          — 8-9 prompt copy-paste
7. Việc người phải tự làm
8. Cách review              — checklist 5 phút + lệnh grep kiểm rò rỉ kiến trúc
9. Quản lý context          — dấu hiệu hỏng, khi nào /clear
10. Git & rollback
11. Khi agent đi lạc        — bảng dấu hiệu → chẩn đoán → xử lý
12. Nhịp độ thực tế         — lịch theo tuần
13. Kịch bản 3 phiên đầu
14. Cạm bẫy phổ biến
```

**Bộ prompt tối thiểu phải có:** bootstrap · giao task · nghiệm thu · DoD không đạt · test đỏ · agent đi lạc · kết thúc phase · mở rộng phase · task thí nghiệm.

---

## 6. Quy trình 4 giai đoạn

```
GĐ1  PHỎNG VẤN          bạn ↔ agent      1 lượt trao đổi
     Agent hỏi, KHÔNG viết gì. Bạn trả lời. Agent tóm tắt lại để bạn xác nhận.
        │
GĐ2  VIẾT KE-HOACH.md   agent            1-2 lượt
     Agent viết. Bạn đọc, phản biện, yêu cầu sửa. Lặp tới khi ưng.
        │
GĐ3  VIẾT tasks.md      agent            1 lượt
     Chỉ sau khi kế hoạch đã chốt. Task phải trỏ ngược về mục KH cụ thể.
        │
GĐ4  VIẾT HUONG-DAN + CLAUDE.md          1 lượt
     Phần lớn tái dùng được từ dự án trước; chỉ đổi phần đặc thù.
```

**Không nhảy GĐ1.** Agent viết kế hoạch mà chưa hỏi gì sẽ đoán ràng buộc — và ràng buộc đoán sai làm hỏng toàn bộ kiến trúc. Ở dự án LifeLog, ba lần chỉnh lớn (v1→v2→v3) đều vì ràng buộc chỉ lộ ra dần: có sẵn RAG-core, deploy ở đâu, dùng API hay self-host. Hỏi trước tiết kiệm được cả ba lần đó.

---

## 7. Prompt copy-paste ⭐

### 7.1 Prompt giai đoạn 1 — phỏng vấn

```
Tôi muốn xây dựng một phần mềm mới. Trước khi viết kế hoạch, hãy PHỎNG VẤN tôi.

Bối cảnh sơ bộ:
<mô tả 5-10 dòng: app làm gì, cho ai, vì sao cần>

Nhiệm vụ của bạn LÚC NÀY:
1. KHÔNG viết kế hoạch, KHÔNG đề xuất công nghệ, KHÔNG viết code.
2. Hỏi tôi tối đa 12 câu, ưu tiên những câu mà câu trả lời sẽ THAY ĐỔI
   KIẾN TRÚC — không hỏi những thứ có thể suy ra hoặc quyết sau.
   Bắt buộc phủ: ràng buộc cứng · phi-mục-tiêu · dữ liệu hiện có ·
   nơi triển khai · ngân sách · thiết bị/kỹ năng của tôi · thời gian ·
   tài sản sẵn có (code, service, tài khoản).
3. Nhóm câu hỏi theo chủ đề, đánh số.
4. Với mỗi câu, ghi ngắn: "ảnh hưởng gì nếu trả lời khác nhau".

Sau khi tôi trả lời, hãy tóm tắt lại toàn bộ ràng buộc bạn hiểu được
thành một bảng, và chỉ ra CHỖ NÀO BẠN VẪN ĐANG PHẢI ĐOÁN.
Chờ tôi xác nhận rồi mới sang bước viết kế hoạch.
```

### 7.2 Prompt giai đoạn 2 — viết kế hoạch

```
Ràng buộc đã chốt ở bước phỏng vấn. Bây giờ viết docs/KE-HOACH.md.

Đọc docs/META-LAP-KE-HOACH.md và làm ĐÚNG theo:
- §2 (9 nguyên tắc viết) — áp dụng từng nguyên tắc một
- §3 (khung mục lục chuẩn)

Yêu cầu bắt buộc:
1. Mở đầu bằng ràng buộc và phi-mục-tiêu, KHÔNG bằng danh sách tính năng.
2. Mỗi quyết định công nghệ phải có cột "đã cân nhắc và vì sao loại".
3. NẾU yêu cầu nào của tôi sẽ gây hại — NÓI THẲNG, giải thích tại sao,
   đề xuất phương án thay thế. Đừng chép lại yêu cầu của tôi.
   Đánh dấu rõ: ✅ giữ nguyên / ⚠️ nên sửa / ⛔ nên bỏ.
4. Thứ tự phase phải xuất phát từ ràng buộc, không phải từ
   "hạ tầng → backend → frontend". Nêu rõ lý do thứ tự.
   Xác định rõ: cái gì hữu ích sớm nhất? cái gì cần dữ liệu chưa có?
   task nào tuy không cấp bách nhưng phát hiện muộn thì rất đắt?
5. Tiêu chí thành công phải CÓ SỐ và có mốc đo.
6. Cạm bẫy phải cụ thể: hiện tượng + nguyên nhân + cách kiểm chứng.
7. Rủi ro phải có mức độ + ứng phó là HÀNH ĐỘNG.
8. Phụ lục chứa thứ dán vào repo là chạy: DDL, schema, .env mẫu,
   file config, prompt template.
9. Kết thúc bằng "Câu hỏi cần bạn quyết", mỗi câu ghi rõ chặn task nào.

Viết bằng tiếng Việt, thuật ngữ kỹ thuật giữ tiếng Anh.
Dùng bảng nhiều hơn văn xuôi. Đánh ⭐ cho phần cốt lõi.
Độ dài mục tiêu: 1500-2500 dòng.

CHƯA viết tasks.md. CHƯA viết code.
```

### 7.3 Prompt giai đoạn 3 — viết tasks.md

```
Kế hoạch đã chốt. Bây giờ viết docs/tasks.md.

Đọc docs/META-LAP-KE-HOACH.md §4 và làm đúng khung + mẫu task ở đó.

Yêu cầu bắt buộc:
1. Mỗi task 1-4 giờ. Task lớn hơn PHẢI tách nhỏ.
2. Đủ 7 trường: Trạng thái · Phụ thuộc · Ước lượng · KH tham chiếu ·
   Việc cần làm · Xong khi (DoD) · Cạm bẫy.
3. ⭐ DoD phải là LỆNH CHẠY ĐƯỢC hoặc HÀNH VI QUAN SÁT ĐƯỢC.
   Tự kiểm mỗi DoD bằng câu hỏi: "DoD này có thể SAI không?"
   Không thể sai = vô dụng = viết lại.
   Cấm: "hoạt động đúng", "đã test kỹ", "xử lý được lỗi".
4. Mức chi tiết: phase đầu (đến ~1/3 roadmap) đầy đủ 7 trường;
   phase giữa dạng bảng; phase cuối gạch đầu dòng.
5. Có mục "Việc của NGƯỜI" (T-H) — thứ agent không làm được,
   ghi rõ mỗi cái chặn task nào.
6. Có mục Backlog để chứa ý tưởng nảy ra giữa chừng.
7. Có mục "Cách dùng file này" với 5-6 luật cho agent thực thi.
8. Mỗi task trỏ ngược về mục cụ thể trong KE-HOACH.md.

Task nào rủi ro cao (dễ sai, phát hiện muộn thì đắt, hoặc quyết định
chất lượng sản phẩm) → ghi rõ và đánh dấu KHÔNG ĐƯỢC GỘP với task khác.
```

### 7.4 Prompt mở rộng phase chưa chi tiết

```
Sắp bắt đầu Phase <N>. Trong docs/tasks.md, phase này mới chỉ có bảng tóm tắt.

Mở rộng T-<N>.1 … T-<N>.<k> thành task đầy đủ theo ĐÚNG mẫu của các phase đầu.

Yêu cầu:
- DoD phải là lệnh chạy được, không phải mô tả.
- Cạm bẫy phải dựa trên những gì THỰC TẾ đã vấp ở các phase trước,
  không phải lý thuyết.
- Ước lượng điều chỉnh theo tốc độ thực tế đã đo được, không dùng lại con số cũ.
- Giữ nguyên ID task.

Ghi đè vào docs/tasks.md. CHƯA viết code.
```

### 7.5 Prompt rà soát kế hoạch (dùng trước khi chốt)

```
Rà soát lại docs/KE-HOACH.md và docs/tasks.md như một người phản biện,
không phải người viết.

Trả lời từng câu, thẳng thắn:
1. Chỗ nào trong kế hoạch là "lời khuyên chung chung" có thể áp cho bất kỳ
   dự án nào? Liệt kê và đề xuất thay bằng nội dung đặc thù.
2. DoD nào KHÔNG THỂ SAI (tức là vô dụng)? Liệt kê và viết lại.
3. Quyết định công nghệ nào chưa có phương án thay thế được cân nhắc?
4. Ràng buộc nào tôi nêu mà kế hoạch chưa phản ánh vào kiến trúc?
5. Task nào ước lượng phi thực tế?
6. Thứ tự phase có chỗ nào sai không — cái gì đang làm quá sớm hoặc quá muộn?
7. Chỗ nào bạn ĐANG ĐOÁN mà chưa hỏi tôi?
8. Nếu chỉ được giữ 60% phạm vi v1, cắt gì?

Chỉ trả lời, chưa sửa file.
```

---

## 8. Bộ câu hỏi phỏng vấn chuẩn

Đưa agent bộ này nếu muốn nó hỏi đúng trọng tâm ngay lượt đầu.

| Nhóm | Câu hỏi | Ảnh hưởng |
|---|---|---|
| **Ràng buộc cứng** | Ngân sách hằng tháng? Deadline? Làm một mình hay có đội? | Chọn hạ tầng, chọn phạm vi |
| | Máy dev là gì? Có giới hạn gì về hệ điều hành/thiết bị? | Loại bỏ nhánh công nghệ |
| | Ngôn ngữ/framework bạn đã mạnh? | Chọn stack theo người, không theo mốt |
| **Người dùng** | Bao nhiêu người dùng ở v1? Có phải chỉ mình bạn? | Quyết định auth, multi-tenant, HA |
| **Dữ liệu** | Có dữ liệu sẵn không? Bao nhiêu? Ở đâu? | **Quyết định thứ tự roadmap** |
| | Dữ liệu có nhạy cảm không? Có được gửi ra API bên ngoài không? | Phân tầng riêng tư, chọn self-host hay API |
| **Triển khai** | Deploy ở đâu? Có tên miền chưa? Có cần truy cập từ ngoài mạng không? | Kiến trúc hạ tầng, HTTPS, chi phí |
| **Tài sản sẵn có** | Có code/service/tài khoản nào tái dùng được không? | Có thể tiết kiệm cả phase — hoặc tạo bẫy tích hợp |
| **Phi-mục-tiêu** | Cái gì bạn CHẮC CHẮN không cần ở v1? | Chặn scope creep |
| **Thành công** | Sau 3 tháng, dấu hiệu nào cho thấy dự án này thành công? | Suy ra tiêu chí đo được |
| **Rủi ro** | Điều gì làm bạn lo nhất ở dự án này? | Ưu tiên xử lý sớm |
| **Nhịp độ** | Mỗi tuần bỏ ra được bao nhiêu giờ? | Ước lượng roadmap thực tế |

---

## 9. Checklist nghiệm thu bản kế hoạch

Chạy trước khi cho agent bắt đầu code.

**`KE-HOACH.md`:**
- [ ] Có mục phi-mục-tiêu, liệt kê cụ thể
- [ ] Mỗi ràng buộc tôi nêu đều xuất hiện trong bảng "ảnh hưởng thiết kế"
- [ ] Mọi ADR đều có cột "đã cân nhắc"
- [ ] Có ít nhất một chỗ agent **phản biện** yêu cầu của tôi (nếu không có, hoặc yêu cầu của tôi hoàn hảo, hoặc agent đang chiều tôi)
- [ ] Tiêu chí thành công có số và có mốc đo
- [ ] Thứ tự phase có giải thích lý do, không phải mặc định
- [ ] Rủi ro có mức độ + ứng phó là hành động
- [ ] Phụ lục dán vào repo là chạy được
- [ ] Có mục "Câu hỏi cần bạn quyết", mỗi câu ghi rõ chặn task nào

**`tasks.md`:**
- [ ] Mọi task ≤ 4 giờ
- [ ] Mọi DoD là lệnh chạy được hoặc hành vi quan sát được
- [ ] Không DoD nào chứa "hoạt động đúng" / "đã test kỹ"
- [ ] Mọi task trỏ về mục KH cụ thể
- [ ] Có mục việc của người (T-H), ghi rõ chặn task nào
- [ ] Có Backlog
- [ ] Task rủi ro cao được đánh dấu "không được gộp"
- [ ] Phase cuối **chưa** chi tiết (nếu chi tiết hết = lãng phí)

**Chạy prompt §7.5** rồi đọc câu trả lời. Nếu agent tự tìm ra ≥ 3 điểm yếu thật, kế hoạch đang lành mạnh. Nếu nó trả lời "mọi thứ đều ổn", đó là dấu hiệu xấu.

---

## 10. Mười hai dấu hiệu kế hoạch kém

| # | Dấu hiệu | Vì sao tệ |
|---|---|---|
| 1 | Mở đầu bằng danh sách tính năng | Chưa hiểu ràng buộc thì kiến trúc chỉ là phỏng đoán |
| 2 | Không có mục phi-mục-tiêu | Scope sẽ phình, không có gì chặn |
| 3 | ADR không có "đã cân nhắc" | Sáu tháng sau sẽ tranh luận lại từ đầu |
| 4 | Chép lại nguyên yêu cầu người dùng, không phản biện chỗ nào | Agent đang chiều, không phải đang giúp |
| 5 | Phase chia kiểu "backend / frontend / testing" | Không có phase nào giao được giá trị dùng được |
| 6 | DoD kiểu "hoạt động đúng" | Không kiểm chứng được = agent tự chấm điểm chính nó |
| 7 | Tiêu chí thành công không có số | Không bao giờ biết đã xong hay chưa |
| 8 | Rủi ro chung chung ("có thể gặp lỗi") | Không dẫn tới hành động nào |
| 9 | Cạm bẫy là lời khuyên chung ("cần cẩn thận") | Không giúp tránh được gì |
| 10 | Chi tiết đều nhau cho mọi phase | Phase cuối chắc chắn viết lại — lãng phí |
| 11 | Không có mục "việc của người" | Sẽ tắc ở giữa vì thiếu API key / tài khoản / quyết định |
| 12 | Không có câu hỏi mở ở cuối | Agent đã đoán thay bạn ở đâu đó mà không nói |

---

## 11. Tái dùng cho dự án mới — 4 bước

```
1. Chép META-LAP-KE-HOACH.md (file này) vào docs/ của repo mới.
2. Chạy prompt §7.1 → trả lời phỏng vấn → xác nhận bảng ràng buộc.
3. Chạy §7.2 → §7.5 (rà soát) → sửa → §7.3 → §7.4 khi cần.
4. Chép HUONG-DAN-AGENT.md của dự án cũ, chỉ đổi:
   §2.3 (task nào phải làm riêng) · §4 (CLAUDE.md) · §13 (kịch bản 3 phiên đầu).
   Phần còn lại dùng lại gần như nguyên vẹn.
```

---

*Hết. Bổ sung nguyên tắc mới vào §2 và dấu hiệu mới vào §10 sau mỗi dự án.*
