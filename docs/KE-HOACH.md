# SCARLET — KẾ HOẠCH THIẾT KẾ PHẦN MỀM

> Chatbot đa-provider self-host cho một nhóm nhỏ (15–20 người).
> Version 1.0 · 2026-09-10 · Viết theo `docs/META-LAP-KE-HOACH.md`
>
> **File này trả lời CÁI GÌ và TẠI SAO.** Thứ tự thực thi nằm ở `docs/tasks.md`.
> Cách giao việc cho agent nằm ở `docs/HUONG-DAN-AGENT.md`.

---

## MỤC LỤC

| # | Mục |
|---|---|
| 0 | [Đọc trước khi thực thi (dành cho AGENT)](#0-đọc-trước-khi-thực-thi-dành-cho-agent) ⭐ |
| 1 | [Bối cảnh & tầm nhìn](#1-bối-cảnh--tầm-nhìn) |
| 2 | [Ràng buộc, phi-mục-tiêu, tiêu chí thành công](#2-ràng-buộc-phi-mục-tiêu-tiêu-chí-thành-công) |
| 3 | [Ràng buộc chi phối: câu trả lời phải sống độc lập với kết nối](#3-ràng-buộc-chi-phối-câu-trả-lời-phải-sống-độc-lập-với-kết-nối-http-) ⭐ |
| 4 | [Use cases & acceptance criteria](#4-use-cases--acceptance-criteria) |
| 5 | [Kiến trúc tổng thể](#5-kiến-trúc-tổng-thể) |
| 6 | [ADR — quyết định kiến trúc](#6-adr--quyết-định-kiến-trúc) ⭐ |
| 7 | [Subsystem: Streaming & Resume](#7-subsystem-streaming--resume-) ⭐ |
| 8 | [Subsystem: Cây hội thoại & branching](#8-subsystem-cây-hội-thoại--branching-) ⭐ |
| 9 | [Subsystem: Provider layer & Model Catalog](#9-subsystem-provider-layer--model-catalog) |
| 10 | [Subsystem: Metering, Quota, BYOK](#10-subsystem-metering-quota-byok) |
| 11 | [Subsystem: Auth & vòng đời tài khoản](#11-subsystem-auth--vòng-đời-tài-khoản) |
| 12 | [Subsystem: Web tools & chống SSRF](#12-subsystem-web-tools--chống-ssrf-) |
| 13 | [Subsystem: Skills & Sandbox](#13-subsystem-skills--sandbox-) ⭐ |
| 14 | [Subsystem: Artifacts & render sandbox](#14-subsystem-artifacts--render-sandbox) |
| 15 | [Subsystem: File, ảnh, Vision](#15-subsystem-file-ảnh-vision) |
| 16 | [Subsystem: Share, Voice, Admin panel](#16-subsystem-share-voice-admin-panel) |
| 17 | [Mô hình dữ liệu](#17-mô-hình-dữ-liệu) |
| 18 | [API surface](#18-api-surface) |
| 19 | [Chống hardcode & cấu hình](#19-chống-hardcode--cấu-hình) ⭐ |
| 20 | [Bảo mật & quyền riêng tư](#20-bảo-mật--quyền-riêng-tư) |
| 21 | [Observability, Eval & chi phí](#21-observability-eval--chi-phí) |
| 22 | [Triển khai](#22-triển-khai) |
| 23 | [Cấu trúc repo](#23-cấu-trúc-repo) |
| 24 | [Roadmap](#24-roadmap) ⭐ |
| 25 | [Rủi ro](#25-rủi-ro) |
| 26 | [Câu hỏi cần bạn quyết](#26-câu-hỏi-cần-bạn-quyết) |
| A–H | [Phụ lục](#phụ-lục-a--ddl-đầy-đủ) |

---

## 0. Đọc trước khi thực thi (dành cho AGENT)

Mười nguyên tắc dưới đây là bản rút gọn của cả kế hoạch. Chúng được chép nguyên văn vào `CLAUDE.md`. Nếu một task có vẻ mâu thuẫn với chúng, **dừng lại và hỏi**, đừng tự hoà giải.

| # | Nguyên tắc | Vì sao |
|---|---|---|
| **A1** | **Sinh câu trả lời KHÔNG BAO GIỜ chạy trong HTTP request handler.** Handler chỉ tạo record và đẩy job. Worker sinh chữ, ghi vào Redis Stream. Client đọc stream qua SSE. | §3, §7. Đây là ràng buộc chi phối cả dự án |
| **A2** | **Message là cây, không phải danh sách.** Mọi truy vấn dựng hội thoại đều đi theo `parent_id` từ leaf lên root. Không có API nào trả "tất cả message của conversation" theo thứ tự thời gian. | §8. Retrofit branching = viết lại cả FE lẫn BE |
| **A3** | **Không viết literal của: tên model, giá, giới hạn, URL provider, danh sách capability** trong `.py`/`.tsx`. Chúng sống ở `model_catalog.json`, `.env`, hoặc bảng `settings`/`tiers`. | §19 |
| **A4** | **Thiếu biến `.env` bắt buộc → app KHÔNG boot** và in đúng tên biến thiếu. Không có giá trị mặc định ngầm cho secret. | §19 |
| **A5** | **Mọi URL do người dùng cung cấp đều đi qua `app/tools/ssrf.py::validate_url()` trước khi fetch.** Không có ngoại lệ, kể cả redirect. | §12 |
| **A6** | **Backend không bao giờ tự chạy code do LLM/skill sinh ra.** Luôn gửi sang service `sandbox` qua HTTP. | §13 |
| **A7** | **Chi phí được snapshot vào `usage_events` tại thời điểm gọi**, không tính lại từ catalog sau này. Đổi giá trong catalog không được làm thay đổi lịch sử. | §10 |
| **A8** | **Mọi endpoint POST tạo tài nguyên đều đọc header `Idempotency-Key`.** Thiếu key → 400 với chat, cho qua với các endpoint khác. | §11.4 |
| **A9** | **Backend chỉ nói một protocol duy nhất với model: OpenAI Chat Completions (streaming).** Khác biệt provider được xử lý ở LiteLLM hoặc ở adapter, không rò lên tầng service. | §9 |
| **A10** | **Không tự "đơn giản hoá" kiến trúc khi gặp khó.** Nếu thấy một thiết kế trong file này là thừa, ghi vào `tasks.md` mục Backlog và hỏi — không tự bỏ. | §10 dấu hiệu 4 của META |

**Ba lệnh phải chạy được sau mỗi phiên làm việc:**

```bash
docker compose ps          # tất cả service healthy
make test                  # pytest xanh
make check-hardcode        # grep không tìm thấy literal bị cấm (§19.4)
```

---

## 1. Bối cảnh & tầm nhìn

### 1.1 Vấn đề — mô tả bằng tình huống thật

Bạn đang trả tiền cho nhiều nhà cung cấp LLM và có một gateway 9Router chạy trên máy cá nhân đã gom sẵn nhiều model. Nhóm bạn bè/đồng nghiệp của bạn (15–20 người) thì mỗi người một tài khoản ChatGPT/Claude riêng, hoặc không có gì. Ba tình huống cụ thể lặp lại:

1. **Một người cần hỏi một model cụ thể một lần duy nhất** — không đáng để họ mua gói tháng, nhưng cũng không có cách nào để bạn "cho mượn" quyền dùng model đó một cách có kiểm soát.
2. **Bạn hỏi một câu dài, model trả lời 3 phút, bạn lỡ tay F5** — mất trắng, phải hỏi lại và trả tiền lần hai. Với model reasoning giá cao, đây là mất tiền thật.
3. **Bạn muốn dùng bộ skills chuẩn của Anthropic** (`docx`, `xlsx`, `pptx`…) nhưng chúng chỉ chạy được bên trong sản phẩm của Anthropic, không dùng được với model rẻ hơn hoặc model local.

### 1.2 Giải pháp

Scarlet là một chatbot self-host: một cửa vào duy nhất (HTTPS + đăng nhập), phía sau là nhiều model từ nhiều nguồn, có hạn mức chi phí theo người, và có ba thứ mà các chatbot self-host phổ biến (Open WebUI, LibreChat, Lobe Chat) đều **không** làm hoặc làm nửa vời: **stream sống sót qua F5**, **skills chạy được code trong sandbox**, và **artifact render live**.

### 1.3 Năm nguyên tắc sản phẩm và hệ quả kỹ thuật

| # | Nguyên tắc sản phẩm | Hệ quả kỹ thuật bắt buộc |
|---|---|---|
| **P1** | **Không mất chữ.** Đã bấm gửi là câu trả lời sẽ được sinh xong, bất kể trình duyệt còn hay mất. | Generation chạy ở worker; token ghi vào Redis Stream có cursor; SSE là *đầu đọc*, không phải *nguồn sinh*. Kéo theo toàn bộ §7 |
| **P2** | **Không mất tiền oan.** Người dùng không tiêu được nhiều hơn hạn mức; chủ app luôn biết ai tiêu bao nhiêu. | Kiểm quota **trước** khi gọi model (dự toán theo max_tokens), ghi thực tế **sau**. Kéo theo §10 |
| **P3** | **Thêm model mới là sửa file cấu hình, không phải sửa code.** | Model catalog dạng data; capability là cờ dữ liệu; UI đọc capability để bật/tắt nút. Kéo theo §9, §19 |
| **P4** | **Mọi thứ người dùng gửi lên đều là dữ liệu thù địch** cho tới khi được kiểm. URL, file, code trong skill, HTML trong artifact. | SSRF guard (§12), sandbox không mạng (§13), origin phụ cho artifact (§14) |
| **P5** | **Giao diện phải có cá tính riêng, không phải bản sao.** | Theme token hoá (`theme.json`), không màu literal trong component; toàn bộ visual do bạn thiết kế bằng Claude Design ở Phase 3, backend không giả định gì về màu sắc/layout |

### 1.4 Cái này KHÔNG phải là gì

Không phải sản phẩm thương mại. Không multi-tenant. Không có SLA. Không tối ưu cho 1000 user. **Mọi quyết định trong file này đều được cân theo trục "20 người dùng, một người vận hành"** — nếu một thiết kế chỉ có ý nghĩa ở quy mô lớn hơn, nó bị loại và có ghi lý do.

---

## 2. Ràng buộc, phi-mục-tiêu, tiêu chí thành công

### 2.1 Bảng ràng buộc → ảnh hưởng thiết kế

| # | Ràng buộc | Ảnh hưởng thiết kế cụ thể |
|---|---|---|
| **R1** | Máy deploy x86, RAM/disk dư dả. Giai đoạn đầu chạy **local**, có domain trỏ sau. | Được phép chạy 10+ container. Nhưng **HTTPS phải có ngay từ Phase 0** bằng `mkcert`, không đợi tới lúc có domain — xem cạm bẫy §22.4 |
| **R2** | Bắt buộc HTTPS khi vào Scarlet. | Nginx terminate TLS. Cookie `Secure`+`HttpOnly`+`SameSite=Lax`. Web Speech API (§16.2) **chỉ chạy trên secure context** — đây là lý do kỹ thuật thứ hai buộc phải có TLS từ sớm |
| **R3** | Có **system key** (chủ app trả tiền) **và** BYOK tuỳ chọn. | Hai đường gọi model song song, cùng protocol nhưng khác nguồn credential và khác luật quota (§10.5) |
| **R4** | Quota: rolling **5 giờ** + rolling **7 ngày**, tính theo **USD quy đổi từ token**. | Cần bảng giá per-model trong catalog, snapshot giá vào từng usage event, và hai cửa sổ trượt trong Redis (§10.3) |
| **R5** | Đăng ký **mở**, nhưng tài khoản mới phải được **admin duyệt** mới dùng được system key. | Trạng thái tài khoản là máy trạng thái 5 bước (§11.1), không phải cờ boolean `is_active` |
| **R6** | Verify email + quên mật khẩu. SMTP giai đoạn này là **Mailpit**. | Email đi qua interface `Mailer`, cấu hình bằng `.env`. **Mailpit không gửi thư ra ngoài** — xem Q-02 §26 |
| **R7** | Admin chỉ có một người (bạn). | Không cần RBAC phức tạp. `users.role ∈ {user, admin}`. Nhưng vẫn phải có audit log cho hành động admin (§20.5) |
| **R8** | **Stream resume mức (b):** F5/đóng tab/mất mạng rồi quay lại vẫn thấy chữ chảy tiếp, không mất không lặp. | **Ràng buộc chi phối — xem §3.** Đổi toàn bộ tầng chat |
| **R9** | **Skills mức (b):** chạy được script Python kèm theo skill, tương thích format Anthropic. | Service `sandbox` riêng, `network_mode: none`, gated bằng quyền per-user (§13) |
| **R10** | **Artifact render live** HTML/React như Claude. | Origin phụ `artifacts.<domain>` + iframe `sandbox` + CSP riêng (§14.3) |
| **R11** | Upstream: **9Router** (`:20128`, OpenAI-compatible, chạy trên Windows host), **DeepSeek**, **Anthropic**. Đi qua **LiteLLM self-host**. | ADR-03. 9Router nằm **ngoài** Docker và **ngoài** vòng đời compose ⇒ model của nó phải được đánh dấu `availability: host-dependent` và Model Picker phải hiện trạng thái, không để lỗi lộ ra giữa lúc stream (§9.5) |
| **R22** | **Sẽ thêm provider khác trong tương lai**, gồm cả những nơi có **endpoint tuỳ chỉnh** (self-host, gateway khác, API nội bộ) | Tầng provider phải mở theo **dữ liệu**, không theo code. Thêm nhà cung cấp OpenAI-compatible = sửa 3 file cấu hình, 0 dòng code. Xem §9.8 và tiêu chí S15 |
| **R12** | Bỏ OCR engine, dùng **vision model**. | Không có container OCR. Ảnh và PDF-scan đi qua pipeline resize → base64 → vision (§15.3). Tiết kiệm ~4 GB image và một worker |
| **R13** | Web search Tavily + **fetch được link user gửi**, có Playwright cho trang JS-heavy. Không lưu mật khẩu bên thứ ba. | Service `fetcher` ở network Docker riêng, không thấy được service nội bộ (§12.4) |
| **R14** | v1 **có** branching/edit lại câu hỏi cũ. | Schema message phải là cây **ngay từ Phase 1** (§8) |
| **R15** | v1 **có** share hội thoại: ai có link cũng xem được, muốn chat tiếp phải đăng nhập, không cần thu hồi link. | Share = **snapshot bất biến**, không phải link tới hội thoại sống (§16.1) |
| **R16** | v1 **có** voice input/TTS bằng **Web Speech API của trình duyệt**. | Không tốn chi phí server, không vào quota, không có biến `.env` cho provider giọng nói. Nhưng **chất lượng tiếng Việt phụ thuộc trình duyệt** và Firefox không hỗ trợ nhận dạng — phải degrade êm (§16.2) |
| **R17** | Redis bắt buộc. | Redis chết = app chết. Phải có healthcheck, `appendonly yes`, và degrade path rõ ràng (§7.7) |
| **R18** | Dev trên **Windows + WSL2 + Docker Desktop**. | Code **phải** nằm trong WSL filesystem, không phải `/mnt/c` (chậm 10–20×). `.venv` tạo trong WSL. `localhost` trong container **không** phải Windows host (§22.5) |
| **R19** | Không deadline, làm một mình, không phải app kiếm tiền. | Mỗi phase phải dùng được ngay khi xong. Không có phase "chỉ hạ tầng, chưa dùng được" |
| **R20** | Người thiết kế FE bằng **Claude Design** là bạn, không phải agent. | API phải ổn định **trước** Phase 3. Backend không được giả định gì về DOM/component. Các task FE-visual đánh dấu `T-H` (việc của người) trong `tasks.md` |
| **R21** | MCP và RAG: **chỉ thiết kế interface, chưa code**. | §13.5 và §21.4 định nghĩa điểm cắm; không có container, không có bảng DB cho hai thứ này ở v1 |

### 2.2 Phi-mục-tiêu — v1 KHÔNG làm

Danh sách này là hợp đồng. Muốn thêm gì vào đây phải viết ADR.

| Không làm | Vì sao |
|---|---|
| **Mobile app native (iOS/Android)** | Bạn đã chốt. PWA responsive là đủ. Không có Mac (R18) nên nhánh iOS native bị loại từ gốc |
| **Multi-tenant / organization / workspace** | 20 người, một chủ. Thêm tenant_id vào mọi bảng là chi phí vĩnh viễn cho một tính năng không ai dùng |
| **High availability, multi-node, k8s** | Một máy. Downtime chấp nhận được. Docker Compose là đúng công cụ |
| **Tự train/fine-tune/host model trong Scarlet** | 9Router đã lo phần model. Scarlet là tầng ứng dụng |
| **RAG (upload tài liệu → hỏi đáp trên tài liệu)** | Bạn đã chốt hoãn. Nhưng §17.3 chừa sẵn chỗ cắm |
| **MCP client** | Bạn đã chốt hoãn. §13.5 định nghĩa interface tool để sau này MCP chỉ là một nguồn tool khác |
| **i18n / đa ngôn ngữ giao diện** | Người dùng đều nói tiếng Việt. Nhưng **không hardcode chuỗi tiếng Việt trong component** — dùng `t('key')` với một file `vi.json` duy nhất, để sau thêm ngôn ngữ là thêm file |
| **Thanh toán, gói cước, hoá đơn** | Không phải app kiếm tiền (R19) |
| **Thu hồi link đã share** | Bạn đã chốt (R15). Nhưng cột `revoked_at` vẫn có trong schema — thêm cột rẻ, thêm bảng đắt |
| **Đăng nhập thay user vào trang bên thứ ba** (Playwright login) | Đã chuyển sang Backlog theo quyết định GĐ1. Lưu mật khẩu bên thứ ba là rủi ro không tương xứng với lợi ích |
| **Realtime collaboration** (2 người cùng sửa một hội thoại) | Không có nhu cầu. Kéo theo CRDT/OT — chi phí khổng lồ |
| **Tự động chọn model theo nội dung câu hỏi (auto-routing)** | 9Router đã làm việc này ở tầng dưới. Làm lần nữa ở Scarlet là trùng lặp và làm chi phí không dự đoán được |

### 2.3 Tiêu chí thành công — có số, có mốc đo

| # | Tiêu chí | Cách đo | Đo ở |
|---|---|---|---|
| **S1** | Xoá 1 biến `.env` bắt buộc → app **không boot**, log in đúng tên biến thiếu | `docker compose up` → exit code ≠ 0, grep tên biến trong log | P0 |
| **S2** | p95 từ lúc bấm gửi → **token đầu tiên** ≤ 2.0 s (model qua 9Router local) và ≤ 4.0 s (model qua API) | Script `scripts/bench_ttft.py` chạy 30 lượt, in p50/p95 | P1 |
| **S3** | **F5 giữa lúc đang stream** → quay lại thấy chữ chảy tiếp: **0 ký tự mất, 0 ký tự lặp** | `scripts/test_resume.py`: bắt đầu stream, ngắt ở token thứ 50, reconnect, so chuỗi nối được với chuỗi tham chiếu → phải khớp byte-by-byte | P1 |
| **S4** | Kill container `worker` giữa lúc stream → sau khi bật lại, message không kẹt trạng thái `streaming` quá **120 s** | `docker compose kill worker` rồi query DB sau **150 s**: `status ∈ {failed, completed}` | P1 |
| **S5** | Bấm nút gửi **2 lần trong 300 ms** → đúng **1** message trong DB, lần thứ hai trả về cùng `message_id` | `scripts/test_idempotency.sh` | P2 |
| **S6** | User hết quota → request bị chặn **trước** khi gọi model, trả `429` với `retry_after` chính xác; **0 USD phát sinh** | Đặt `limit_5h_usd = 0.001`, gửi request, kiểm bảng `usage_events` không có dòng mới | P2 |
| **S7** | Thêm 1 model mới vào catalog: hiện trong Model Picker sau ≤ 5 phút, **0 dòng code sửa, 0 lần rebuild image** | Sửa `config/model_catalog.json` → `curl -X POST /api/v1/admin/catalog/reload` → `GET /api/v1/models` có model mới | P3 |
| **S8** | Giao diện dùng được ở **375 px**; Lighthouse mobile: Accessibility ≥ 90, Performance ≥ 80 | `npx lighthouse https://localhost --preset=mobile` | P3 |
| **S9** | Gửi model **không có** capability `vision` một ảnh → FE chặn ở nút upload (icon cấm khi hover), BE trả `422` nếu bị bypass | Test thủ công + `pytest tests/api/test_vision_guard.py` | P4 |
| **S10** | Fetch `http://169.254.169.254/latest/meta-data/` và `http://litellm:4000/` → **bị từ chối**, không có request nào rời khỏi container `fetcher` | `pytest tests/tools/test_ssrf.py` ≥ 25 case, gồm cả redirect chain và DNS rebinding | P6 |
| **S11** | Skill chạy `import socket; socket.create_connection(('1.1.1.1',53))` trong sandbox → **thất bại**; chạy `while True: pass` → bị kill sau `SANDBOX_TIMEOUT_S` | `pytest tests/sandbox/test_isolation.py` | P7 |
| **S12** | Artifact HTML chứa `fetch('/api/v1/conversations')` → **không** lấy được dữ liệu (khác origin, không có cookie) | Test thủ công có ghi lại + `tests/e2e/test_artifact_origin.spec.ts` | P5 |
| **S13** | Chi phí thực tế 30 ngày ≤ `MONTHLY_BUDGET_USD` cấu hình sẵn; admin panel hiển thị đúng ±2% so với dashboard của provider | So bảng `usage_events` với báo cáo của DeepSeek/Anthropic cuối tháng | P2 → theo dõi liên tục |
| **S15** ⭐ | Thêm **một provider hoàn toàn mới** có endpoint tuỳ chỉnh (base URL + key riêng): model của nó hiện trong Model Picker và chat được, trong **≤ 15 phút**, **0 dòng code sửa**, chỉ sửa `model_catalog.json` + `litellm.config.yaml` + `.env` | Diễn tập thật với một provider thứ tư ở T-0.12, ghi lại thời gian | P0, lặp lại mỗi phase |
| **S14** | Toàn bộ test suite chạy < 3 phút trên máy dev | `time make test` | Liên tục |

**Ghi chú về S13:** với model đi qua 9Router, con số này **sẽ không khớp** — xem §9.5 và ADR-03. Tiêu chí S13 chỉ áp cho model gọi trực tiếp qua LiteLLM tới DeepSeek/Anthropic.

**Ghi chú về S4 — hai con số 120 s và 150 s ở đâu ra** *(sửa 2026-09-16, NQ-38; trước đó là 90 s và 120 s)*. Cửa sổ phát hiện suy ra được từ chính ba tham số của §7.6, không phải chọn cho đẹp:

```
cửa sổ = [REAPER_STALE_S − WORKER_HEARTBEAT_S,  REAPER_STALE_S + nhịp cron]
       = [90 − 15, 90 + 30] = [75 s, 120 s]
```

Cận trên là `REAPER_STALE_S + nhịp cron`. Vì `REAPER_STALE_S` đã bằng 90, **mọi** nhịp cron > 0 đều đẩy cận trên vượt 90 — tức "≤ 90 s" là điều §7.6 không bao giờ thoả được, và hạ nhịp quét một mình không cứu được. Ba phép đo thật rơi đúng trong khoảng: **82.31 s**, **95.72 s** (T-1.10) và **121.2 s** (rà phase 1, chạm trần).

Cách kiểm đo ở **150 s** chứ không 120 s vì 120 s là **đúng** cận trên: hỏi ngay tại biên là một phép thử 50/50 tự đỏ. 30 s dôi ra là biên an toàn cho hạt của phép đo, không phải nới tiêu chí.

**Không hạ `REAPER_STALE_S` để ép cửa sổ xuống dưới 90 s.** Nhịp tim chỉ được ghi **bên trong** vòng `async for chunk in stream` (`workers/generate.py`), nên giữa `mark_streaming` và chunk đầu tiên không có nhịp nào — `REAPER_STALE_S` vì thế đồng thời là **TTFT tối đa trước khi reaper giết một lượt sinh còn sống**. `nr-gemini-flash` đo được TTFT p95 **43.7 s** ngày xấu (B-103) nên 90 s chỉ còn ~2× biên; hạ xuống 60 s là đổi một phiền toái (dọn chậm) lấy một mất mát (giết nhầm câu trả lời người dùng đã trả tiền). Muốn hạ thì phải tách nhịp tim khỏi vòng chunk trước — xem B-122.

---

## 3. Ràng buộc chi phối: câu trả lời phải sống độc lập với kết nối HTTP ⭐

Đây là mục quan trọng nhất của kế hoạch. Nó quyết định thứ tự phase, quyết định schema, và quyết định vì sao Redis là bắt buộc chứ không phải "cho nhanh".

### 3.1 Cách làm mặc định và vì sao nó sai ở đây

Gần như mọi hướng dẫn "FastAPI + SSE + LLM" trên mạng đều viết thế này:

```python
@router.post("/chat")
async def chat(req: ChatRequest):
    async def gen():
        async for chunk in llm.stream(req.messages):   # ← generation sống bên trong request
            yield f"data: {chunk}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
```

Kiến trúc này có bốn chỗ chết, và cả bốn đều nằm đúng vào yêu cầu R8 của bạn:

| Hiện tượng | Nguyên nhân |
|---|---|
| F5 → mất toàn bộ câu trả lời đang sinh dở | Generator bị GC khi client disconnect; không có bản sao nào của các token đã sinh |
| Mất mạng 3 giây → mất cả câu trả lời | Như trên. `EventSource` sẽ tự reconnect nhưng server không có gì để phát lại |
| Đóng laptop, mở lại sau 10 phút → không có gì | Không có ai đang sinh nữa |
| `docker compose restart api` khi deploy → mọi câu trả lời đang chạy bốc hơi | Generation gắn với vòng đời của process API |

Thêm một chỗ chết ít ai nghĩ tới: **user đã trả tiền cho những token đó rồi.** Provider vẫn tính tiền phần đã sinh dù bạn có nhận được hay không. Mất chữ ở đây là mất tiền thật.

### 3.2 Đảo ngược: tách *nguồn sinh* khỏi *đầu đọc*

```
CÁCH SAI                          CÁCH CỦA SCARLET

[browser] ←──SSE──→ [api]         [browser] ──POST──→ [api] ──job──→ [redis queue]
                      │                                                    │
                      ↓                                                    ↓
                    [LLM]                                              [worker] ──→ [LLM]
                                                                           │
   một sợi dây duy nhất                                                    ↓ XADD
   đứt là mất hết                                              [redis stream:msg_id]
                                                                           │
                                  [browser] ←──SSE (đọc từ cursor)──── [api]
```

Ba tính chất có được:

| Tính chất | Vì sao có |
|---|---|
| **Đứt kết nối không dừng generation** | Worker không biết và không quan tâm client còn hay mất |
| **Reconnect không mất chữ** | Redis Stream có ID tăng dần; client gửi `Last-Event-ID`, server `XRANGE` từ đó |
| **Reconnect không lặp chữ** | Cùng lý do — cursor là chính xác, không phải "đọc lại từ đầu rồi cắt" |

### 3.3 Vì sao điều này đảo thứ tự roadmap

Theo N4 của META, thứ tự phase phải đến từ ràng buộc. Hai câu hỏi:

**Cái gì hữu ích sớm nhất?** Chat được với một model, ngay cả khi chưa có đăng ký, chưa có quota, chưa có giao diện đẹp. Bạn tự dùng được từ Phase 1.

**Cái gì phát hiện muộn thì rất đắt?** Chính là §3 này và §8 (cây message). Cả hai đều là **hình dạng của dữ liệu và của luồng điều khiển**, không phải tính năng bổ sung. Retrofit chúng vào một hệ đã chạy nghĩa là:

- Viết lại toàn bộ endpoint chat và mọi thứ gọi nó
- Viết lại state management của frontend (từ "mảng message" sang "cây + con trỏ leaf")
- Migration dữ liệu cũ với `parent_id` phải suy ngược từ thứ tự thời gian
- Viết lại phần lớn test

Ước lượng: làm đúng từ đầu ở Phase 1 tốn khoảng 12–16 giờ. Retrofit ở Phase 5 tốn 35–50 giờ và gần như chắc chắn để lại bug ở các trường hợp biên.

**Vì vậy Phase 1 = chat core với đầy đủ streaming resume + cây message, trước cả auth đầy đủ, trước cả giao diện.** Đây là lý do thứ tự phase của Scarlet không phải "hạ tầng → backend → frontend".

### 3.4 Cái giá phải trả — nói thẳng

| Cái giá | Mức độ | Có chấp nhận không |
|---|---|---|
| Bắt buộc có Redis với `appendonly yes` | Trung bình | Có — Redis vốn đã cần cho rate limit, idempotency, blacklist (R17) |
| Bắt buộc có worker process riêng | Trung bình | Có — vốn đã cần cho xử lý file, sinh tiêu đề hội thoại |
| Chat không còn là một request đơn giản → khó debug hơn | Cao | Bù bằng `/api/v1/_debug/stream/{message_id}` (§21.2) trả về toàn bộ nội dung stream và metadata |
| Độ trễ tăng thêm ~10–30 ms do qua hàng đợi | Thấp | Không đáng kể so với 500–3000 ms TTFT của model |
| Phải tự xử lý message "mồ côi" khi worker chết | Trung bình | Có reaper task, tiêu chí S4 |

---

## 4. Use cases & acceptance criteria

Mỗi UC có actor, luồng, và AC dạng checkbox kiểm chứng được. AC ở đây là nguồn để viết DoD trong `tasks.md`.

### UC-01 — Đăng ký và được duyệt

**Actor:** người dùng mới · **Kênh:** web

Luồng: điền email + mật khẩu + Turnstile → nhận mail xác thực → bấm link → trạng thái `pending_approval` → admin thấy trong panel → duyệt → trạng thái `active`, nhận mail thông báo.

- [ ] Đăng ký với email đã tồn tại → phản hồi **giống hệt** trường hợp thành công (không lộ email nào đã đăng ký), nhưng không tạo user mới
- [ ] Chưa verify email → gọi `POST /conversations/*/messages` trả `403` với `code=EMAIL_NOT_VERIFIED`
- [ ] Đã verify, chưa duyệt → đăng nhập được, thấy giao diện, chọn model được, nhưng gửi tin nhắn bằng system key trả `403 PENDING_APPROVAL`; **nếu đã cấu hình BYOK thì gửi được**
- [ ] Link verify hết hạn sau `EMAIL_TOKEN_TTL_MIN` → trả trang "gửi lại", không phải lỗi 500
- [ ] Link verify dùng lần thứ hai → không lỗi, chuyển thẳng tới trang đăng nhập (idempotent)

### UC-02 — Chat cơ bản có stream

**Actor:** user đã active

- [ ] Gửi tin nhắn → thấy chữ đầu tiên trong ≤ 2 s (model local), ≤ 4 s (API)
- [ ] Trong lúc stream, nút gửi biến thành nút **Dừng**; bấm Dừng → chữ ngừng trong ≤ 500 ms, phần đã sinh **được lưu** với `finish_reason='cancelled'`
- [ ] Trong lúc stream, `usage_events` chưa có dòng; sau khi xong hoặc bị huỷ, có đúng **1** dòng
- [ ] Model trả về code → hiện trong code block có nút Copy, có nhãn ngôn ngữ, có số dòng
- [ ] Dưới mỗi câu trả lời của AI có: Copy · Like · Dislike · Retry · (Đổi model & retry)

### UC-03 — F5 giữa lúc đang stream ⭐

**Actor:** user · **Đây là UC quan trọng nhất, mọi thiết kế ở §7 tồn tại vì nó**

- [ ] Đang stream, bấm F5 → sau khi tải lại, chữ **tiếp tục chảy** từ đúng chỗ đang dở
- [ ] Nội dung nối được sau reconnect **khớp byte-by-byte** với nội dung nếu không ngắt (S3)
- [ ] Đóng hẳn tab, mở lại sau 30 s → hội thoại hiện câu trả lời **đầy đủ** (đã sinh xong trong lúc tab đóng)
- [ ] Rút mạng 5 s rồi cắm lại → tự reconnect, không cần thao tác tay
- [ ] Mở **hai** tab cùng một hội thoại → cả hai cùng thấy chữ chảy, không tab nào bị đói
- [ ] Stream đã xong quá `STREAM_TTL_S` → mở lại vẫn thấy nội dung đầy đủ (đọc từ Postgres thay vì Redis)

### UC-04 — Sửa câu hỏi cũ và chuyển nhánh

**Actor:** user

- [ ] Bấm sửa một tin nhắn ở giữa hội thoại → tạo **nhánh mới**, không xoá nhánh cũ
- [ ] Dưới tin nhắn có nhánh, hiện điều hướng `‹ 2/3 ›`; bấm chuyển nhánh → phần hội thoại phía dưới đổi theo
- [ ] Bấm Retry trên câu trả lời AI → sinh câu trả lời anh em cùng cha, không ghi đè
- [ ] Retry bằng model khác → nhánh mới ghi lại `model_id` khác; nhánh cũ giữ nguyên model cũ
- [ ] Context gửi lên model chỉ gồm các message **trên đường đi hiện tại**, không gồm nhánh khác

### UC-05 — Đổi model giữa hội thoại

- [ ] Model Picker hiện: tên hiển thị, nhà cung cấp, badge capability (vision/tools/reasoning), và **trạng thái khả dụng**
- [ ] Model thuộc 9Router mà host đang tắt → hiện xám, tooltip "nguồn local đang không chạy", **không cho chọn**
- [ ] Chọn model không có `vision` khi hội thoại đã có ảnh → cảnh báo trước, không âm thầm bỏ ảnh
- [ ] Model mặc định lấy từ `default: true` trong catalog, user đổi được và được nhớ theo user

### UC-06 — Upload ảnh và hỏi về ảnh

- [ ] Model có `vision` → nút upload sáng, kéo-thả được, dán từ clipboard được
- [ ] Model **không** có `vision` → nút vẫn hiện nhưng mờ; hover hiện icon cấm + tooltip "model này không đọc được ảnh" (yêu cầu rõ ràng của bạn)
- [ ] Ảnh > `MAX_IMAGE_MB` → báo lỗi **trước khi** upload, không phải sau
- [ ] Ảnh được resize xuống cạnh dài ≤ `VISION_MAX_EDGE_PX` trước khi gửi model
- [ ] Ảnh lưu ở MinIO, hiện lại được khi tải lại trang, **không** kèm trong context của các lượt sau nếu model không có vision

### UC-07 — Hết quota

- [ ] Còn ≤ 20% quota → hiện thanh cảnh báo, không chặn
- [ ] Hết quota 5h → nút gửi vô hiệu hoá, hiện **thời điểm chính xác** quota được hoàn lại
- [ ] Cố gửi bằng API trực tiếp → `429` kèm `Retry-After` và body có `limit_type ∈ {5h, weekly}`
- [ ] Hết quota system key nhưng có BYOK → **vẫn gửi được** bằng key riêng
- [ ] Admin nâng hạn mức cho user → có hiệu lực trong ≤ 60 s, không cần user đăng nhập lại

### UC-08 — Tìm kiếm web

- [ ] Bật công tắc "Tìm web" → model gọi tool `web_search`, UI hiện chip nguồn kèm favicon và tiêu đề
- [ ] User dán link vào prompt → app fetch được nội dung link đó và dùng làm context
- [ ] Link trỏ vào IP nội bộ hoặc `169.254.169.254` → từ chối, hiện thông báo rõ, **không** treo
- [ ] Trang JS-heavy (nội dung rỗng khi fetch thường) → tự leo thang sang Playwright, người dùng không phải làm gì
- [ ] Tavily hỏng/hết quota → chat vẫn chạy, chỉ mất tính năng search, hiện cảnh báo

### UC-09 — Dùng skill

- [ ] User bật một skill trong panel → chỉ `name` + `description` được nạp vào system prompt, không phải toàn bộ nội dung
- [ ] Model quyết định dùng skill → gọi tool `load_skill` để lấy nội dung đầy đủ
- [ ] Skill cần chạy code, user **có** quyền → code chạy trong sandbox, output quay lại hội thoại
- [ ] Skill cần chạy code, user **không** có quyền → model được báo rõ và trả lời bằng cách khác, không im lặng thất bại
- [ ] Skill sinh file `.docx` → file lên MinIO, hiện trong panel artifact với nút tải

### UC-10 — Artifact

- [ ] Model sinh HTML/React → mở panel bên phải, render live trong iframe
- [ ] Artifact có nhiều phiên bản → chuyển qua lại được giữa các phiên bản
- [ ] Artifact HTML cố gọi API của Scarlet → thất bại (khác origin, không cookie) — S12
- [ ] Panel artifact đóng/mở được, kéo rộng được, trên mobile thì chiếm toàn màn hình
- [ ] Tải artifact về dưới dạng file đúng đuôi

### UC-11 — Share hội thoại

- [ ] Bấm Share → tạo **snapshot**, trả link
- [ ] Người lạ mở link → xem được nội dung tại thời điểm share, **không** thấy tin nhắn phát sinh sau đó
- [ ] Người lạ bấm "Chat tiếp" → bị đẩy sang đăng nhập/đăng ký; sau khi đăng nhập, snapshot được **fork** thành hội thoại mới của họ
- [ ] Trang share không lộ: email chủ hội thoại, model id nội bộ, chi phí

### UC-12 — Admin

- [ ] Thấy danh sách user chờ duyệt, duyệt/từ chối bằng một nút
- [ ] Thấy bảng chi phí: theo ngày, theo user, theo model
- [ ] Đổi hạn mức của một tier, hoặc override cho một user
- [ ] Bật/tắt `can_execute_skills` cho từng user
- [ ] Reload model catalog không cần restart container
- [ ] Mọi hành động admin ghi vào `audit_logs`

---

## 5. Kiến trúc tổng thể

### 5.1 Sơ đồ

```
                          ┌──────────────────────────────┐
   Trình duyệt            │  WINDOWS HOST (ngoài Docker) │
   (React PWA)            │   9Router  :20128            │
        │                 │   (OpenAI-compatible)        │
        │ HTTPS           └───────────▲──────────────────┘
        ▼                             │ host.docker.internal
┌───────────────┐                     │
│    NGINX      │  TLS · gzip · rate-limit lớp 1
│               │  ⚠ proxy_buffering off cho /api/v1/*/stream
└───┬───────┬───┘
    │       │
    │       └────────────────────────────────┐
    ▼                                        ▼
┌────────────────┐                  ┌──────────────────┐
│  web (React)   │                  │  artifacts       │  ← ORIGIN PHỤ
│  origin chính  │                  │  origin riêng    │    iframe sandbox
└────────────────┘                  └──────────────────┘    KHÔNG cookie chung
    │ /api/v1
    ▼
┌─────────────────────────────────────────────────────────┐
│  api  (FastAPI)                                          │
│   • auth · quota check · CRUD · SSE READER               │
│   • KHÔNG gọi LLM. KHÔNG chạy code. KHÔNG fetch URL.     │
└───┬────────────┬──────────────┬─────────────┬───────────┘
    │            │              │             │
    ▼            ▼              ▼             ▼
┌────────┐  ┌─────────┐   ┌──────────┐  ┌──────────┐
│postgres│  │  redis  │   │  minio   │  │ mailpit  │
│ nguồn  │  │ stream  │   │ file/ảnh │  │  SMTP    │
│ sự thật│  │ queue   │   │          │  │  (dev)   │
│        │  │ cache   │   │          │  │          │
└────────┘  └────┬────┘   └──────────┘  └──────────┘
                 │ job
                 ▼
┌─────────────────────────────────────────────────────────┐
│  worker  (arq)                                           │
│   • generation loop → XADD từng delta vào stream         │
│   • gọi tool · sinh tiêu đề · trích text file            │
└───┬──────────────┬───────────────┬──────────────────────┘
    │              │               │
    ▼              ▼               ▼
┌─────────┐  ┌───────────┐  ┌──────────────┐
│ litellm │  │  fetcher  │  │   sandbox    │
│ :4000   │  │ Playwright│  │ network:none │
│         │  │ net riêng │  │ read-only fs │
└────┬────┘  └─────┬─────┘  └──────────────┘
     │             │
     ▼             ▼
  DeepSeek      Internet
  Anthropic     (chỉ 80/443,
  9Router        đã lọc SSRF)
```

### 5.2 Bảng ranh giới trách nhiệm

Bảng này là công cụ review. Khi đọc một PR, câu hỏi đầu tiên là "lớp này có đang làm việc của lớp khác không".

| Lớp | ĐƯỢC PHÉP | KHÔNG ĐƯỢC PHÉP |
|---|---|---|
| **nginx** | TLS, nén, rate limit theo IP, định tuyến, phục vụ static | Biết gì về user, JWT, hay logic nghiệp vụ |
| **web (React)** | Render, state UI, gọi `/api/v1`, đọc `GET /models` | Gọi thẳng LiteLLM/provider; đọc file catalog từ đĩa; giữ API key trong localStorage |
| **artifacts origin** | Render nội dung do model sinh, trong iframe | Đọc cookie của origin chính; gọi `/api/v1` có xác thực |
| **api** | Auth, phân quyền, **kiểm quota trước**, CRUD, đẩy job, **đọc** Redis Stream và phát SSE | **Gọi LLM**, **chạy code**, **fetch URL bên ngoài**, chạy tác vụ > 2 s |
| **worker** | Gọi LLM, gọi tool, ghi Redis Stream, ghi Postgres, **ghi** usage | Nhận request HTTP từ ngoài; giữ state trong RAM giữa các job |
| **litellm** | Chuẩn hoá protocol, giữ system key, retry/fallback, timeout | Chứa logic nghiệp vụ của Scarlet; quyết định quota |
| **fetcher** | Fetch HTTP(S) ra Internet, chạy Playwright | Thấy được `postgres`/`redis`/`api` (khác network) |
| **sandbox** | Chạy code Python trong thư mục tạm | Có mạng; ghi ra volume dùng chung; sống lâu hơn một lần gọi |
| **postgres** | Nguồn sự thật duy nhất | — |
| **redis** | Stream, queue, cache, rate limit, idempotency, blacklist | Là nơi lưu dữ liệu **duy nhất** của bất cứ thứ gì quan trọng |

### 5.3 Luật vàng của lớp

> **API không bao giờ đợi model.** Nếu một hàm trong `app/api/` có `await` một lời gọi có thể kéo dài hơn 2 giây, nó đang ở sai chỗ.

Kiểm bằng: `grep -rn "litellm\|openai\|anthropic\|httpx.*http" backend/app/api/` phải **không** ra kết quả nào (§19.4).

---

## 6. ADR — quyết định kiến trúc

| # | Quyết định | Lý do | Đã cân nhắc (và vì sao loại) |
|---|---|---|---|
| **ADR-01** | **Redis Stream** làm bộ đệm token, mỗi message một key `stream:{message_id}`, TTL `STREAM_TTL_S=3600` | Có ID tăng dần dùng làm cursor ⇒ resume chính xác. `XADD` O(1). `XREAD BLOCK` cho độ trễ gần 0. Redis vốn đã bắt buộc (R17) | **Redis Pub/Sub**: không có lịch sử, reconnect là mất chữ — trượt thẳng R8. **Postgres LISTEN/NOTIFY**: payload ≤ 8 kB, không có cursor, tạo tải ghi rất lớn (mỗi token một row). **Kafka/NATS**: hạ tầng thừa cho 20 user. **Ghi thẳng vào cột Postgres mỗi token**: ~2000 UPDATE cho một câu trả lời dài, table bloat nặng |
| **ADR-02** | **arq** làm task queue | Async-native (khớp FastAPI), chỉ cần Redis, ~1000 dòng đọc hết được, hỗ trợ job timeout + retry + cron | **Celery**: nặng, mô hình sync, cấu hình async khó chịu, thêm nhiều khái niệm không dùng tới. **Dramatiq**: tốt nhưng cộng đồng nhỏ hơn, vẫn thiên sync. **FastAPI BackgroundTasks**: chết theo process ⇒ trượt R8 và S4. **RQ**: không async |
| **ADR-03** ⭐ | **LiteLLM đứng trước, 9Router là một upstream phía sau nó.** Không dùng 9Router làm gateway trực tiếp của Scarlet | ① Backend chỉ nói **một** protocol với **một** base URL (A9). ② Anthropic native API được LiteLLM chuẩn hoá sang OpenAI format ⇒ một parser duy nhất. ③ LiteLLM nằm **trong** compose ⇒ vòng đời do Scarlet kiểm soát, còn 9Router chạy bằng npm trên Windows host, có thể tắt bất kỳ lúc nào. ④ Retry/timeout/fallback là **dữ liệu** trong `litellm.config.yaml`, không phải code | **Chỉ dùng 9Router**: nó đã OpenAI-compatible và có 60+ provider, nhưng nó sống ngoài Docker, tắt máy là chết, và tính năng auto-fallback theo tier khiến **model thực tế trả lời có thể khác model đã yêu cầu** ⇒ đo chi phí sai (xem §9.5). **Chỉ dùng SDK gốc từng provider**: 3 code path streaming khác nhau, mỗi provider một kiểu tool-call, chính là thứ A9 muốn tránh. **Cả hai gateway song song, không chồng nhau**: phải viết logic chọn gateway ⇒ lại hardcode |
| **ADR-04** | **Loại LangChain khỏi đường chat chính** ⚠️ *(phản biện yêu cầu ban đầu của bạn)* | LangChain chuẩn hoá tốt phần non-streaming, nhưng ở streaming + tool-call + reasoning token, sự khác biệt provider vẫn rò qua abstraction, và bạn sẽ debug ở tầng bạn không viết. Sau ADR-03 thì **LiteLLM đã làm đúng việc bạn cần LangChain làm**. Bỏ nó tiết kiệm ~40 MB deps và một tầng phiên bản hay vỡ | **Giữ LangChain**: vẫn dùng được, nhưng thành hai tầng abstraction chồng nhau cho cùng một mục đích. **LlamaIndex**: định hướng RAG, chưa cần ở v1. **Chỉ dùng `openai` SDK trỏ vào LiteLLM**: ← **đây là lựa chọn**, đơn giản nhất và đủ. *Nếu sau này làm RAG (§21.4) mà thấy cần orchestration, mở lại quyết định này bằng ADR mới* |
| **ADR-05** | **Postgres 17**, không thêm vector DB ở v1 | Nguồn sự thật duy nhất. Khi làm RAG, `pgvector` cắm thẳng vào cùng DB, JOIN được với `messages`/`users` trong một câu truy vấn | **SQLite**: một writer, không chịu được worker + api ghi song song. **MongoDB**: cây message và quota cần transaction + constraint. **Qdrant ngay từ đầu**: chưa có RAG (R21) — thêm hạ tầng cho tính năng chưa tồn tại |
| **ADR-06** | **Message là cây** (`parent_id`), `conversations.active_leaf_id` trỏ nhánh đang xem | R14 yêu cầu branching. Chi phí thêm ở Phase 1 là nhỏ; retrofit sau là 3–4× (§3.3) | **Danh sách phẳng + bảng `branches` riêng**: nhân đôi nguồn sự thật, đồng bộ hai nơi. **Lưu cả hội thoại thành JSONB một cột**: không query được, không index được, ghi đồng thời là mất dữ liệu |
| **ADR-07** | **Access JWT ngắn (15 phút) + refresh token xoay vòng lưu DB, có phát hiện tái sử dụng** | Blacklist chỉ cần giữ `jti` tối đa 15 phút ⇒ Redis nhẹ. Refresh bị đánh cắp và dùng lại → cả family bị thu hồi | **Session trong DB thuần**: một query DB mỗi request. **JWT dài hạn không refresh**: không thu hồi được — trượt R5/R7. **Chỉ refresh không xoay vòng**: token đánh cắp dùng được vĩnh viễn |
| **ADR-08** | **Ước tính chi phí trước khi gọi, ghi thực tế sau khi xong**, giá snapshot vào từng dòng usage | Chặn được vượt quota **trước khi tốn tiền** (S6). Snapshot giá giữ lịch sử đúng khi catalog đổi giá (A7) | **Chỉ ghi sau**: user vượt hạn mức rồi mới biết. **Tính lại từ catalog khi hiển thị**: đổi giá làm sai lệch toàn bộ lịch sử. **Dùng số liệu của LiteLLM**: đúng cho DeepSeek/Anthropic, nhưng sai cho 9Router (§9.5), và tạo phụ thuộc vào DB nội bộ của LiteLLM |
| **ADR-09** | **Sandbox là service HTTP riêng**, `network_mode: none`, rootfs read-only, tmpfs cho workdir, ephemeral từng lần gọi | A6. Code do LLM sinh phải bị coi là mã độc. Tách service ⇒ giới hạn tài nguyên bằng cgroup của Docker, không phải bằng code Python | **`exec()` trong process API**: thoát ra là chiếm cả app — không bàn. **Docker-out-of-Docker (mount `docker.sock`)**: mount socket = trao quyền root máy chủ cho service đó. **gVisor/Firecracker**: an toàn hơn thật, nhưng phức tạp vận hành cao cho 20 user; ghi vào Backlog nếu mở đăng ký rộng hơn |
| **ADR-10** | **Artifact render ở origin riêng** `artifacts.<domain>` (local: `artifacts.localhost`), iframe `sandbox="allow-scripts"` **không** kèm `allow-same-origin` | Cùng lúc hai lớp: khác origin ⇒ không đọc được cookie/localStorage của app; `sandbox` không có `allow-same-origin` ⇒ script coi như origin `null` | **Cùng origin + CSP**: một lỗ XSS trong artifact là chiếm session. **`srcdoc` cùng origin**: y hệt, không cách ly. **Chỉ hiện code không render**: trượt R10 |
| **ADR-11** | **Vision model thay OCR engine** | R12. Chất lượng tiếng Việt có dấu tốt hơn Tesseract rõ rệt; bỏ được ~4 GB image, một worker và một hàng đợi | **Tesseract**: tiếng Việt có dấu kém, gần như vô dụng với ảnh chụp nghiêng. **PaddleOCR/VietOCR**: chất lượng tốt nhưng kéo theo torch, ~4 GB, và cần GPU mới đủ nhanh. *Đánh đổi đã chấp nhận:* mỗi lần đọc ảnh đều tốn tiền token và cần mạng |
| **ADR-12** | **Model catalog là JSON mounted, phục vụ qua `GET /api/v1/models`** ⚠️ *(sửa nhẹ yêu cầu của bạn: FE không đọc thẳng file)* | Server lọc theo quyền/tier/BYOK của từng user, ẩn `base_url` và giá vốn, và báo trạng thái khả dụng của 9Router. File tĩnh không làm được ba việc đó | **FE fetch thẳng `/config/model_catalog.json`**: lộ base URL nội bộ + giá; không lọc được theo user; không biết model nào đang chết. **Catalog trong DB**: sửa phải qua UI, mất khả năng diff/commit bằng git — *ghi vào Backlog, có thể đổi sau* |
| **ADR-13** | **Web Speech API của trình duyệt** cho voice/TTS | R16. Không tốn tiền, không vào quota, không thêm container, không thêm biến `.env` | **Whisper API + TTS API**: chất lượng tiếng Việt tốt hơn nhiều nhưng tốn tiền và phải vào quota. **whisper.cpp self-host**: thêm ~2 GB và CPU. *Đánh đổi:* Firefox không hỗ trợ nhận dạng giọng nói ⇒ phải ẩn nút, không được để nút chết (§16.2) |
| **ADR-14** | **Share = snapshot bất biến**, không phải link tới hội thoại sống | R15. Chủ hội thoại chat tiếp sau khi share thì nội dung mới **không** rò ra link công khai. Đây là chế độ an toàn mặc định | **Link tới hội thoại sống**: mỗi tin nhắn mới đều tự động công khai — gần như chắc chắn có ngày lộ nhầm. **Share có mật khẩu**: bạn đã chốt là không cần |
| **ADR-15** | **Idempotency bằng header `Idempotency-Key`** (client sinh UUID v4), Redis `SET NX` TTL 24h, lưu cả response | Chống double-click (S5) và chống retry của trình duyệt. Xử lý được cả trường hợp request thứ hai đến khi request thứ nhất **chưa xong** (trả `409 IN_PROGRESS`) | **Dedupe bằng hash nội dung**: gửi cùng câu hỏi hai lần một cách cố ý là hợp lệ, không được chặn. **Debounce chỉ ở FE**: không chống được retry tầng mạng hay user mở hai tab |
| **ADR-16** | **`pnpm` + Vite + React 19 + TypeScript**, TailwindCSS v4, không dùng UI-kit lớn | Bạn sẽ thiết kế bằng Claude Design (R20); UI-kit lớn sẽ chống lại thiết kế riêng. Tailwind v4 dùng CSS variable ⇒ đổi theme không cần build lại | **Next.js**: SSR không đem lại gì cho một app sau đăng nhập; thêm một runtime Node để vận hành. **MUI/AntD**: áp đặt ngôn ngữ thiết kế, chống lại P5. **shadcn/ui**: ← chấp nhận được vì là code copy vào repo, sửa tự do; dùng chọn lọc cho primitive (dialog, dropdown, tooltip) |

---

## 7. Subsystem: Streaming & Resume ⭐

### 7.1 Vì sao subsystem này khó

Nó khó không phải vì SSE khó, mà vì **ba thứ phải cùng đúng một lúc**: (1) generation không được gắn với kết nối, (2) cursor phải chính xác tuyệt đối để không lặp/không mất, (3) phải có đường thoát khi worker chết giữa chừng. Bỏ sót bất kỳ cái nào thì hai cái kia trở nên vô nghĩa.

Thêm nữa, nó là subsystem **duy nhất** mà bug chỉ lộ ra khi có sự cố — chạy êm trong 100% test thủ công thông thường. Vì vậy nó bắt buộc phải có test tự động mô phỏng đứt kết nối (S3), không được nghiệm thu bằng mắt.

### 7.2 Vòng đời một câu trả lời

```
① POST /conversations/{cid}/messages          (Idempotency-Key: <uuid>)
   api:
     - kiểm auth, kiểm trạng thái tài khoản
     - kiểm idempotency key            → trùng? trả lại response cũ
     - kiểm quota (ước tính)           → không đủ? 429, DỪNG, chưa tốn xu nào
     - INSERT message(role=user, parent_id=<leaf hiện tại>)
     - INSERT message(role=assistant, parent_id=<user msg>, status='queued')
     - UPDATE conversations.active_leaf_id
     - arq.enqueue('generate', assistant_message_id)
     - RETURN 202 {user_message_id, assistant_message_id, stream_url}
   → tổng thời gian: < 100 ms. KHÔNG có await nào tới model.

② GET /messages/{amid}/stream            (SSE, header Last-Event-ID nếu reconnect)
   api:
     - kiểm quyền sở hữu message
     - cursor = Last-Event-ID hoặc query ?cursor=, mặc định '0'
     - XRANGE stream:{amid} (cursor, +]    → phát lại phần đã có (tức thì)
     - XREAD BLOCK 15000 STREAMS ...       → phát tiếp khi có delta mới
     - hết BLOCK mà chưa done → gửi comment ": ping" giữ kết nối
     - gặp event type=done → đóng stream

③ worker: generate(assistant_message_id)
     - load đường đi từ leaf lên root → dựng messages[]
     - UPDATE status='streaming'
     - XADD stream:{amid} type=start model=...
     - async for chunk in openai_client.stream(...):
          XADD stream:{amid} type=delta text=<chunk>
          mỗi N chunk: kiểm cờ huỷ cancel:{amid}
     - (nếu có tool call → XADD type=tool_call, chạy tool, XADD type=tool_result, lặp lại)
     - UPDATE messages SET content=<toàn bộ>, status='completed', usage=...
     - INSERT usage_events (chi phí thực)
     - XADD stream:{amid} type=done
     - EXPIRE stream:{amid} STREAM_TTL_S
```

### 7.3 Vì sao có bước "XRANGE trước rồi mới XREAD"

Đây là chỗ dễ viết sai nhất. Nếu chỉ `XREAD BLOCK` từ `$` (nghĩa là "chỉ những cái mới"), client reconnect sẽ **mất toàn bộ phần đã sinh trong lúc đứt**. Nếu chỉ `XRANGE` rồi thôi, client không nhận được phần sinh tiếp.

Phải làm đúng thứ tự: **`XRANGE (cursor, +]` để đuổi kịp, rồi `XREAD BLOCK` từ ID cuối cùng vừa đọc được.** Và ID dùng cho `XREAD` phải là ID của bản ghi cuối cùng **thực sự đã gửi cho client**, không phải ID lúc bắt đầu.

### 7.4 Định dạng event SSE

Mỗi event SSE mang `id:` chính là Redis Stream ID (`1725984000123-0`). Nhờ vậy `EventSource` của trình duyệt **tự động** gửi `Last-Event-ID` khi reconnect — không cần code phía client cho việc này.

```
id: 1725984000123-0
event: delta
data: {"t":"Xin ch"}

id: 1725984000456-0
event: tool_call
data: {"name":"web_search","args":{"query":"..."},"call_id":"c_1"}

id: 1725984002100-0
event: done
data: {"finish_reason":"stop","usage":{"in":1204,"out":389,"cost_usd":0.00231}}
```

| `event` | Ý nghĩa | FE làm gì |
|---|---|---|
| `start` | Bắt đầu sinh, kèm `model_id`, `message_id` | Hiện con trỏ nhấp nháy |
| `delta` | Một mẩu văn bản | Nối vào cuối |
| `reasoning` | Mẩu reasoning/thinking (model hỗ trợ) | Hiện trong khối gấp được, tách khỏi nội dung chính |
| `tool_call` | Model gọi tool | Hiện chip "đang tìm web…" |
| `tool_result` | Tool trả kết quả | Cập nhật chip, hiện nguồn |
| `artifact` | Có artifact mới/cập nhật | Mở panel phải |
| `usage` | Số token tạm tính | Cập nhật thanh quota |
| `done` | Kết thúc | Đóng `EventSource`, bật lại nút gửi |
| `error` | Lỗi có mã | Hiện lỗi + nút Retry |

**Luật:** FE **không được** suy ra "đã xong" bằng cách thấy stream im lặng. Chỉ `done` hoặc `error` mới kết thúc. Im lặng = đang chờ, hiện trạng thái chờ.

### 7.5 Huỷ giữa chừng

```
POST /messages/{amid}/cancel → SET cancel:{amid} 1 EX 300
worker: mỗi 8 chunk kiểm EXISTS cancel:{amid}
        → có: dừng vòng lặp, UPDATE finish_reason='cancelled',
               VẪN ghi usage_events cho phần đã sinh, XADD type=done
```

Ghi usage cho phần đã huỷ là bắt buộc: **provider vẫn tính tiền phần đã sinh.** Không ghi = quota bị rò.

### 7.6 Worker chết giữa chừng — reaper

Nếu container `worker` bị kill lúc đang sinh, message sẽ kẹt ở `status='streaming'` mãi mãi và client sẽ treo vô hạn.

```
Cron arq mỗi 30 s:
  UPDATE messages SET status='failed', error_code='WORKER_LOST'
  WHERE status='streaming' AND heartbeat_at < now() - interval '90 seconds'
  → với mỗi message: XADD stream:{id} type=error data={"code":"WORKER_LOST"}
```

Worker cập nhật `heartbeat_at` mỗi 15 giây trong lúc sinh. Tiêu chí nghiệm thu là S4.

### 7.7 Cạm bẫy — hiện tượng · nguyên nhân · cách kiểm chứng

| # | Cạm bẫy |
|---|---|
| **C1** | **Hiện tượng:** stream im lặng hoàn toàn rồi trả một cục khi xong. **Nguyên nhân:** Nginx buffer response. **Kiểm:** `curl -N https://localhost/api/v1/_debug/sse` — chữ phải ra **từng cái**, không phải một cục sau 5 s. **Sửa:** `proxy_buffering off; proxy_cache off; chunked_transfer_encoding on;` trong location đó, **và** backend gửi header `X-Accel-Buffering: no` |
| **C2** | **Hiện tượng:** stream chết đúng sau 60 giây. **Nguyên nhân:** `proxy_read_timeout` mặc định 60 s của Nginx. **Kiểm:** hỏi một câu khiến model trả lời > 60 s. **Sửa:** `proxy_read_timeout 3600s;` **và** heartbeat `: ping` mỗi 15 s từ backend |
| **C3** | **Hiện tượng:** reconnect thấy chữ bị **lặp** một đoạn. **Nguyên nhân:** dùng lại cursor cũ thay vì ID cuối cùng đã gửi, hoặc `XRANGE` dùng `[cursor` (bao gồm) thay vì `(cursor` (loại trừ). **Kiểm:** S3 — so byte-by-byte |
| **C4** | **Hiện tượng:** reconnect **mất** một đoạn giữa. **Nguyên nhân:** `XREAD` từ `$` thay vì từ ID cuối của `XRANGE` (§7.3). **Kiểm:** S3 |
| **C5** | **Hiện tượng:** `docker compose restart redis` → mọi hội thoại mất sạch lịch sử. **Nguyên nhân:** coi Redis là nơi lưu trữ. **Kiểm:** restart redis rồi tải lại trang — hội thoại cũ **phải** còn (đọc từ Postgres). **Luật:** Redis chỉ giữ dữ liệu đang bay; Postgres là sự thật |
| **C6** | **Hiện tượng:** trên mobile, khoá màn hình 30 s rồi mở lại thì stream đứng. **Nguyên nhân:** iOS Safari đóng kết nối nền. **Kiểm:** test thật trên điện thoại. **Sửa:** lắng `visibilitychange`, khi `visible` thì đóng và mở lại `EventSource` — `Last-Event-ID` lo phần còn lại |
| **C7** | **Hiện tượng:** mở 2 tab, một tab không nhận chữ. **Nguyên nhân:** dùng consumer group của Redis Stream (mỗi bản ghi giao cho **một** consumer). **Sửa:** **không** dùng consumer group ở đây; mỗi client `XREAD` độc lập với cursor riêng. **Kiểm:** UC-03, mở hai tab |
| **C8** | **Hiện tượng:** hết RAM Redis sau vài tuần. **Nguyên nhân:** quên `EXPIRE` stream key. **Kiểm:** `redis-cli --scan --pattern 'stream:*' \| wc -l` phải ổn định, không tăng đơn điệu. **Sửa:** `EXPIRE` ngay sau `done`, cộng thêm `maxmemory-policy volatile-lru` |
| **C9** | **Hiện tượng:** message dài bị cắt ngang ở ký tự tiếng Việt thành `?` hoặc `\ufffd`. **Nguyên nhân:** cắt chuỗi theo byte thay vì theo ký tự khi chia delta. **Kiểm:** hỏi model trả lời dài bằng tiếng Việt có dấu, so chuỗi cuối với `content` trong DB |
| **C10** | **Hiện tượng:** JSON trong `data:` vỡ khi nội dung có xuống dòng. **Nguyên nhân:** SSE dùng `\n` làm dấu phân cách trường. **Sửa:** luôn `json.dumps()` toàn bộ payload (escape `\n` thành `\\n`), không bao giờ nội suy chuỗi thô vào `data:` |

---

## 8. Subsystem: Cây hội thoại & branching ⭐

### 8.1 Vì sao subsystem này khác thường

Hầu hết chatbot lưu hội thoại thành mảng. ChatGPT/Claude thì không — vì "sửa câu hỏi cũ" và "retry" tạo ra **cây**, không phải mảng. Bạn đã yêu cầu tính năng này ở v1 (R14), nên schema phải là cây từ dòng migration đầu tiên.

### 8.2 Mô hình

```
conversation (active_leaf_id ──────────────┐)
                                           │
  m1 user "viết hàm sort"                  │
   └── m2 assistant (bubble sort)          │
        └── m3 user "nhanh hơn đi"         │
             ├── m4 assistant (quicksort)  │
             └── m5 assistant (mergesort) ←┘   ← retry tạo anh em của m4
  m1' user "viết hàm sort bằng Rust"           ← sửa m1 tạo anh em của m1 (parent_id = NULL)
   └── m6 assistant (...)
```

| Thao tác | Nghĩa trên cây |
|---|---|
| Gửi tin nhắn mới | Thêm con của `active_leaf_id` |
| **Retry** câu trả lời | Thêm **anh em** của message assistant đó (cùng `parent_id`) |
| **Sửa** câu hỏi | Thêm **anh em** của message user đó; nhánh con cũ vẫn còn |
| Chuyển nhánh `‹ 2/3 ›` | Chỉ đổi `active_leaf_id` — **không** xoá gì |
| Dựng context gửi model | Đi từ `active_leaf_id` ngược lên `parent_id = NULL`, rồi đảo ngược |

### 8.3 Truy vấn đường đi — recursive CTE

```sql
WITH RECURSIVE path AS (
    SELECT m.*, 0 AS depth FROM messages m WHERE m.id = :leaf_id
    UNION ALL
    SELECT m.*, p.depth + 1 FROM messages m JOIN path p ON m.id = p.parent_id
)
SELECT * FROM path ORDER BY depth DESC;   -- gốc trước, lá sau
```

**Sắp theo `depth`, không sắp theo `created_at`.** Thứ tự của một đường đi do *cấu trúc cây* quyết định chứ không do đồng hồ: mỗi tầng có đúng một message, nên `depth` là khoá sắp xếp chính xác và không bao giờ hoà. Thời gian thì hoà được — xem NQ-18 trong `tasks.md`. (CTE vẫn phải lọc `deleted_at IS NULL` ở **cả hai** nhánh — C12.)

Với hội thoại < 500 message, chi phí không đáng kể nếu có index trên `(parent_id)` và `(conversation_id, parent_id)`.

Đếm anh em cho điều hướng `‹ n/m ›`:

```sql
SELECT id, created_at FROM messages
WHERE conversation_id = :cid
  AND parent_id IS NOT DISTINCT FROM :parent_id
ORDER BY created_at, id;
```

Khoá phụ `id` để kết quả **xác định** khi hai anh em trùng `created_at`. `clock_timestamp()` chỉ phân giải tới micro-giây, nên một câu `INSERT ... SELECT generate_series` ghi hàng loạt vẫn tạo ra giá trị trùng (đo được: 500 dòng → 88 giá trị). Ứng dụng không bao giờ ghi message kiểu đó, nhưng script seed thì có — và `sibling_index` sai là C13.

`IS NOT DISTINCT FROM` là bắt buộc: `parent_id = NULL` không bao giờ đúng trong SQL, mà message gốc thì `parent_id` **là** NULL.

### 8.4 Cạm bẫy

| # | Cạm bẫy |
|---|---|
| **C11** | **Hiện tượng:** hoá đơn tăng bất thường, model "nhớ" những thứ user chưa hỏi ở nhánh này. **Nguyên nhân:** dựng context bằng `SELECT * FROM messages WHERE conversation_id=... ORDER BY created_at` — gom cả nhánh bị bỏ. **Kiểm:** tạo 3 nhánh, gửi ở nhánh 1, log số message gửi lên model — phải bằng độ dài đường đi, không phải tổng số message |
| **C12** | **Hiện tượng:** xoá một message làm mất cả một mảng hội thoại. **Nguyên nhân:** `ON DELETE CASCADE` trên `parent_id`. **Sửa:** dùng **soft delete** (`deleted_at`), không xoá cứng; truy vấn đường đi lọc `deleted_at IS NULL` |
| **C13** | **Hiện tượng:** FE hiện sai số nhánh sau khi retry. **Nguyên nhân:** FE tự đếm cục bộ thay vì đọc `sibling_index`/`sibling_count` do API trả. **Sửa:** API trả sẵn hai trường này trong mỗi message |
| **C14** | **Hiện tượng:** hai tab cùng gửi tin nhắn → cây tách đôi ngoài ý muốn. **Nguyên nhân:** cả hai đọc `active_leaf_id` cũ. **Sửa:** client gửi kèm `parent_id` mình đang thấy; nếu khác `active_leaf_id` hiện tại thì vẫn chấp nhận (đó **là** một nhánh hợp lệ) nhưng trả cờ `branched: true` để FE thông báo |
| **C15** | **Hiện tượng:** hội thoại dài làm request chậm dần rồi vỡ context window. **Nguyên nhân:** gửi toàn bộ đường đi. **Sửa:** cắt theo ngân sách token (§9.6) — giữ system prompt + N message gần nhất vừa trong `context_window - max_output`, và **luôn giữ nguyên vẹn cặp tool_call/tool_result**, không được cắt lẻ một nửa |

---

## 9. Subsystem: Provider layer & Model Catalog

### 9.1 Một protocol duy nhất

```python
# app/llm/client.py — cả hệ thống chỉ có MỘT interface này
class LLMClient(Protocol):
    async def stream(
        self, *, model: str, messages: list[dict], tools: list[dict] | None,
        max_tokens: int, temperature: float, extra: dict,
    ) -> AsyncIterator[Chunk]: ...
```

Hai cài đặt, cùng dùng SDK `openai`:

| Adapter | base_url | Credential | Dùng khi |
|---|---|---|---|
| `SystemAdapter` | `http://litellm:4000/v1` | `LITELLM_MASTER_KEY` | Mặc định, tính vào quota |
| `ByokAdapter` | lấy từ `provider.base_url` trong catalog | key của user, giải mã từ vault | User đã cấu hình BYOK cho provider đó |

Hai adapter dùng **chung** code parse stream vì cả hai đều là OpenAI-compatible. Đây là toàn bộ giá trị của ADR-03 + ADR-04.

### 9.2 Cấu trúc catalog

```jsonc
{
  "version": 3,
  "providers": {
    "ninerouter": {
      "label": "9Router (local)",
      "base_url": "http://host.docker.internal:20128/v1",
      "availability": "host-dependent",   // ⚠ ngoài Docker, có thể tắt
      "health_path": "/models",
      "byok_supported": false,
      "cost_reporting": "unreliable"      // xem §9.5
    },
    "deepseek":  { "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
                   "availability": "always", "byok_supported": true, "cost_reporting": "exact",
                   "auth_style": "bearer",        // bearer | x-api-key | query  (C44)
                   "verify_path": "/models" },    // endpoint rẻ nhất để kiểm key BYOK (C42)
    "anthropic": { "label": "Anthropic", "base_url": "https://api.anthropic.com",
                   "availability": "always", "byok_supported": true, "cost_reporting": "exact" }
  },
  "models": [
    {
      "id": "deepseek-chat",
      "display_name": "DeepSeek V3",
      "provider": "deepseek",
      "upstream_model": "deepseek/deepseek-chat",
      "capabilities": ["tools", "vision"],
      "context_window": 128000,
      "max_output": 8192,
      "pricing": { "input_per_1m": 0.27, "output_per_1m": 1.10, "cached_input_per_1m": 0.07 },
      "pricing_mode": "metered",
      "enabled": true, "default": true, "order": 10,
      "badge": "Nhanh · Rẻ"
    }
  ]
}
```

**Luật:** thêm model = thêm một object vào mảng này + `POST /admin/catalog/reload`. Không sửa code, không rebuild (S7).

### 9.3 Endpoint `GET /api/v1/models` — vì sao không để FE đọc file ⚠️

Yêu cầu ban đầu của bạn là FE đọc thẳng `model_catalog.json`. Tôi đề nghị **sửa**: giữ file làm nguồn sự thật, nhưng phục vụ qua API. Lý do cụ thể, không phải nguyên tắc chung:

| Việc | File tĩnh | Qua API |
|---|---|---|
| Ẩn `base_url` nội bộ và giá vốn | ✗ lộ hết cho mọi khách | ✓ |
| Ẩn model chỉ dành cho admin, hoặc tier cao | ✗ | ✓ |
| Báo "9Router đang tắt" để làm xám model | ✗ file không biết | ✓ health check định kỳ |
| Ẩn model provider mà user chưa có BYOK, khi hết quota system | ✗ | ✓ |
| Cache | như nhau | như nhau (ETag) |

Chi phí của việc sửa: khoảng 40 dòng code. Đổi lại bốn khả năng trên. Nếu bạn vẫn muốn FE đọc file, ghi lại thành ADR mới, tôi làm theo.

### 9.4 Cờ capability điều khiển UI

| Capability | Hệ quả UI | Hệ quả BE |
|---|---|---|
| `vision` | Không có → nút upload ảnh mờ, hover hiện icon cấm (yêu cầu của bạn) | Không có → `422` nếu payload chứa ảnh |
| `tools` | Không có → công tắc "Tìm web" và panel Skills bị vô hiệu hoá kèm giải thích | Không có → không gửi mảng `tools` |
| `reasoning` | Có → hiện khối "Đang suy nghĩ…" gấp được | Có → map `reasoning` delta sang event riêng |
| `attachments` | Không có → chỉ cho upload ảnh, không cho pdf/docx | Không có → trích text ở worker rồi chèn dưới dạng văn bản |

### 9.5 ⚠️ Vấn đề riêng của 9Router — phải xử lý, không được bỏ qua

9Router là AI gateway tự động fallback qua nhiều tier provider để phiên làm việc không chết vì lỗi 429, và có nén token RTK. Hai tính năng đó rất hữu ích cho coding agent, nhưng chúng tạo hai hệ quả cho Scarlet:

1. **Model thực tế trả lời có thể không phải model đã yêu cầu.** Nếu tier 1 hết quota, request rơi xuống tier 2/3. Nghĩa là giá tính theo `pricing` trong catalog **sai**.
2. **Số token báo về có thể đã bị RTK nén**, không phản ánh chi phí thật ở provider gốc.

**Cách xử lý — ba lớp:**

| Lớp | Việc |
|---|---|
| Catalog | Model qua 9Router đặt `pricing_mode: "unmetered"` (hoặc `"flat"` nếu bạn muốn tính một giá ước lượng cố định) |
| Metering | `usage_events.cost_usd` cho các model này ghi giá trị ước lượng và cột `cost_confidence='low'`; quota **vẫn trừ** để chống lạm dụng, nhưng admin panel hiển thị tách riêng khỏi chi phí thật |
| Ghi nhận | Nếu 9Router trả header cho biết upstream thật, worker ghi vào `usage_events.upstream_model_reported` để đối chiếu sau |

**Cạm bẫy C16:** *Hiện tượng:* bảng chi phí không khớp hoá đơn provider. *Nguyên nhân:* trộn chung model `metered` và `unmetered` vào một con số. *Kiểm:* admin panel phải có hai cột riêng; tiêu chí S13 chỉ áp cho cột `metered`.

### 9.6 Ngân sách token khi dựng context

```
budget = min(model.context_window, CONTEXT_WINDOW_CAP) - model.max_output - RESERVE_TOKENS
```

Thứ tự ưu tiên khi cắt: system prompt (không bao giờ cắt) → skill descriptions → message mới nhất → lùi dần về quá khứ. **Cặp `tool_call` + `tool_result` là một đơn vị nguyên tử** — cắt lẻ một nửa khiến nhiều provider trả `400 invalid request` (C15).

### 9.7 Cạm bẫy khác

| # | Cạm bẫy |
|---|---|
| **C17** | **Hiện tượng:** `Connection refused` tới `localhost:20128` từ trong container. **Nguyên nhân:** `localhost` trong container là chính container đó, không phải Windows host. **Sửa:** `host.docker.internal`; trên Docker Desktop/WSL2 cần `extra_hosts: ["host.docker.internal:host-gateway"]`. **Kiểm:** `docker compose exec litellm curl -s http://host.docker.internal:20128/v1/models` phải ra JSON |
| **C18** | **Hiện tượng:** thêm provider mới thì tool-call vỡ. **Nguyên nhân:** không phải OpenAI-compatible endpoint nào cũng hỗ trợ `tools`. **Sửa:** capability là dữ liệu trong catalog, và có eval golden-set (§21.3) chạy khi thêm model mới |
| **C19** | **Hiện tượng:** stream dừng giữa chừng không có `done`. **Nguyên nhân:** upstream đứt mà không gửi `[DONE]`. **Sửa:** worker luôn `finally: XADD done/error` — không có đường thoát nào không ghi event kết thúc |

### 9.8 Thêm provider mới sau này ⭐

Ràng buộc R22. Toàn bộ tầng provider được thiết kế để mở rộng bằng **dữ liệu**. Ba mức tương thích, và chỉ mức 3 mới phải đụng vào code:

| Mức | Provider kiểu gì | Phải làm gì | Sửa code? | Rebuild image? |
|---|---|---|---|---|
| **1 — OpenAI-compatible** | Có `/v1/chat/completions` chuẩn: vLLM, Ollama, LM Studio, llama.cpp, Together, Groq, Fireworks, OpenRouter, xAI, Mistral, một gateway khác, hay API nội bộ của bạn | ① 1 entry vào `providers` + n entry vào `models` của catalog · ② 1 entry `openai/<model>` kèm `api_base` vào `litellm.config.yaml` · ③ 1 biến key vào `.env` | **Không** | **Không** (chỉ restart container `litellm`) |
| **2 — LiteLLM hỗ trợ sẵn, protocol riêng** | Google Gemini, AWS Bedrock, Vertex AI, Cohere, Azure OpenAI | Như mức 1, chỉ khác: `model:` trong litellm dùng tiền tố nhà cung cấp (`gemini/gemini-2.5-pro`, `bedrock/...`) thay vì `openai/` | **Không** | **Không** |
| **3 — Không thuộc hai loại trên** | API tự chế, giao thức lạ, không có bản dịch OpenAI | Viết adapter mới trong `app/llm/adapters/` cài đúng protocol `LLMClient` (§9.1) | **Có** | Có |

**Mức 3 rất hiếm** — nếu gặp, viết ADR mới trước khi code, vì nó đang phá vỡ A9.

### 9.9 Quy trình chuẩn thêm provider (mức 1 và 2)

```
1. .env                    thêm  FOO_API_KEY=...        (và FOO_BASE_URL nếu self-host)
2. litellm.config.yaml     thêm  - model_name: foo-large
                                   litellm_params:
                                     model: openai/foo-large-v2
                                     api_base: os.environ/FOO_BASE_URL
                                     api_key:  os.environ/FOO_API_KEY
3. model_catalog.json      thêm  providers.foo  +  models[] cho từng model
                                 → ĐẶT "enabled": false
4. docker compose up -d litellm
5. make eval MODEL=foo-large           ← bộ 12 case §21.3
6. eval xanh  →  đổi "enabled": true  →  POST /admin/catalog/reload
```

**Luật:** model của provider mới **luôn** vào với `enabled: false` và chỉ được bật sau khi eval xanh (§21.3). Đây không phải thủ tục hình thức — năm cạm bẫy dưới đây đều chỉ lộ ra khi chạy thật, và cả năm đều âm thầm.

### 9.10 Cạm bẫy khi thêm provider

| # | Cạm bẫy |
|---|---|
| **C40** | **Hiện tượng:** chat được nhưng `usage_events.cost_usd = 0` và quota không bao giờ trừ. **Nguyên nhân:** provider không hỗ trợ `stream_options: {include_usage: true}`, nên chunk cuối không có `usage`. **Kiểm:** sau khi thêm, `SELECT prompt_tokens, completion_tokens FROM usage_events ORDER BY created_at DESC LIMIT 1` — cả hai phải > 0. **Sửa:** đường lùi ước tính bằng tiktoken, và đặt `cost_confidence='low'` cho provider đó |
| **C41** | **Hiện tượng:** provider khai có `tools` nhưng tool call vỡ hoặc bị bỏ qua. **Nguyên nhân:** nhiều endpoint "OpenAI-compatible" chỉ compatible ở phần text. **Kiểm:** case 4–6 của eval golden-set. **Sửa:** bỏ `tools` khỏi `capabilities` trong catalog — FE sẽ tự vô hiệu hoá công tắc Tìm web và panel Skills (§9.4) |
| **C42** | **Hiện tượng:** thêm BYOK cho provider mới thì luôn báo "key không hợp lệ". **Nguyên nhân:** không phải provider nào cũng có `GET /models` để kiểm key. **Sửa:** trường `verify_path` trong catalog (§9.2); nếu provider không có endpoint rẻ nào, đặt `verify_path: null` → lưu key mà không kiểm, và báo cho user biết là chưa xác thực |
| **C43** | **Hiện tượng:** `404 Not Found` từ upstream, dù URL dán vào trình duyệt thì chạy. **Nguyên nhân:** `base_url` có/không có hậu tố `/v1` và dấu `/` cuối — SDK `openai` và LiteLLM ghép đường dẫn khác nhau. **Sửa:** chuẩn hoá trong catalog loader (bỏ `/` cuối, yêu cầu `base_url` **đã bao gồm** `/v1`), và validate lúc boot |
| **C44** | **Hiện tượng:** `401` dù key đúng. **Nguyên nhân:** provider dùng header khác — `x-api-key` thay vì `Authorization: Bearer`. **Sửa:** trường `auth_style` trong catalog; LiteLLM xử lý phần lớn trường hợp, nhưng `ByokAdapter` (§9.1) gọi thẳng thì phải tự áp dụng |
| **C45** | **Hiện tượng:** thêm provider self-host xong, chạy được trên máy dev nhưng chết trong container. **Nguyên nhân:** cùng loại với C17 — `localhost` trong container. **Sửa:** self-host trên máy host thì dùng `host.docker.internal`; self-host trong compose thì dùng tên service |

---

## 10. Subsystem: Metering, Quota, BYOK

### 10.1 Vì sao khó

Vì phải chặn **trước** khi tốn tiền, mà lúc đó chưa biết model sẽ sinh bao nhiêu token. Và vì có hai nguồn credential với hai luật khác nhau chạy song song trong cùng một luồng code.

### 10.2 Hai cửa: ước tính trước, ghi thực sau

```
TRƯỚC (trong api, đồng bộ, < 5 ms):
  est_in   = đếm token của context đã dựng (tiktoken, xấp xỉ là đủ)
  est_max  = est_in * in_price + max_output * out_price     ← trường hợp xấu nhất
  spent_5h, spent_7d = đọc từ Redis
  nếu spent_5h + est_max > limit_5h  → 429 {limit_type:"5h", retry_after: <giây>}
  nếu spent_7d + est_max > limit_7d  → 429 {limit_type:"weekly", ...}

SAU (trong worker, khi có usage thật):
  cost = in*in_price + out*out_price + cached*cached_price
  INSERT usage_events (... , price_snapshot = {…}, cost_confidence)
  ZADD quota:5h:{uid}  <ts> <cost>   ;  ZADD quota:7d:{uid} <ts> <cost>
```

**Vì sao dùng trường hợp xấu nhất để chặn:** nếu ước tính lạc quan, user sát hạn mức có thể vượt hàng chục lần bằng một câu hỏi sinh 8000 token. Chặn theo tình huống xấu nhất khiến người dùng thấy quota "chặt hơn thực tế" — chấp nhận được, và có thể bù bằng cách hiển thị "còn lại ~X USD" theo chi tiêu thật, không theo dự toán.

### 10.3 Hai cửa sổ trượt

| Cửa sổ | Cấu trúc | Đọc | Dọn |
|---|---|---|---|
| 5 giờ | Redis ZSET `quota:5h:{uid}`, score = epoch, member = `{usage_id}` | `ZRANGEBYSCORE now-18000 +inf` rồi cộng | `ZREMRANGEBYSCORE -inf now-18000` trước mỗi lần đọc |
| 7 ngày | ZSET `quota:7d:{uid}` | tương tự với 604800 | tương tự |

**Redis là cache, Postgres là sự thật.** Khi Redis mất dữ liệu, quota được dựng lại bằng một truy vấn `SUM(cost_usd)` trên `usage_events` (có index `(user_id, created_at)`), rồi nạp lại ZSET. Hàm `rebuild_quota(user_id)` phải tồn tại và có test — không phải để phòng xa, mà vì `docker compose down -v` khi dev sẽ xảy ra thường xuyên.

`retry_after` tính chính xác bằng: thời điểm mà tổng trong cửa sổ tụt xuống dưới hạn mức = `score` của phần tử cũ nhất cần rơi ra + độ dài cửa sổ − now.

### 10.4 Tier là dữ liệu, không phải code

```
tiers(name PK, limit_5h_usd, limit_7d_usd, can_execute_skills, can_use_web,
      max_upload_mb, max_attachments, allowed_model_tags[], is_default)
users.tier_name → tiers.name
users.limit_override_json → ghi đè từng trường cho một user cụ thể
```

Đổi hạn mức trong admin panel có hiệu lực ≤ 60 s (cache tier trong Redis TTL 60). Đây là AC của UC-07.

### 10.5 BYOK

| Khía cạnh | Quyết định |
|---|---|
| Lưu ở đâu | Bảng `user_provider_keys`, giá trị mã hoá **AES-256-GCM** bằng khoá dẫn xuất từ `MASTER_ENCRYPTION_KEY` trong `.env`, mỗi bản ghi một nonce riêng |
| Hiển thị lại | **Không bao giờ.** UI chỉ hiện `sk-...4f2a` (4 ký tự cuối) + thời điểm thêm. Muốn đổi thì nhập lại |
| Kiểm tra khi thêm | Gọi `GET {base_url}/models` (hoặc endpoint rẻ nhất) để xác nhận key sống, trước khi lưu |
| Quota | Request dùng BYOK **không** trừ quota, nhưng **vẫn** ghi `usage_events` với `key_source='byok'` để user tự xem chi tiêu |
| Rate limit | Vẫn áp dụng (chống hành vi lạm dụng hạ tầng, dù không tốn tiền của bạn) |
| Khi tài khoản `pending_approval` | BYOK **dùng được ngay** — đây là lý do phân tách trạng thái ở §11.1 |
| Xoá tài khoản | Xoá cứng bản ghi key, không soft-delete |

**Cạm bẫy C20:** *Hiện tượng:* key của user hiện trong log hoặc trong thông báo lỗi. *Nguyên nhân:* log cả object request hoặc để exception của SDK nổi lên nguyên văn. *Kiểm:* `grep -rE "sk-[a-zA-Z0-9]{20,}" logs/` phải rỗng; có một middleware redact chạy trên mọi log record. Thêm test: cố tình dùng key sai → thông điệp lỗi trả về user **không** chứa chuỗi key.

### 10.6 Rate limit (khác quota)

Hai thứ khác nhau: **quota** giới hạn tiền, **rate limit** giới hạn tần suất.

| Lớp | Phạm vi | Giá trị mặc định | Cài đặt |
|---|---|---|---|
| Nginx | theo IP | 30 req/s burst 60 | `limit_req_zone` |
| API | theo user + nhóm route | chat: 20/phút · auth: 5/phút · upload: 10/phút | Token bucket trong Redis (Lua script để atomic) |
| API | theo IP cho route chưa đăng nhập | đăng ký: 3/giờ · quên mật khẩu: 3/giờ | chống dò email |
| Đồng thời | theo user | tối đa `MAX_CONCURRENT_STREAMS=3` message đang `streaming` | đếm trong Redis |

---

## 11. Subsystem: Auth & vòng đời tài khoản

### 11.1 Máy trạng thái tài khoản

Yêu cầu R5 (đăng ký mở + admin duyệt) không biểu diễn được bằng một cờ boolean. Năm trạng thái:

```
  đăng ký
     ↓
 pending_email ──(bấm link)──→ pending_approval ──(admin duyệt)──→ active
     │                              │                                 │
     │                              └──(admin từ chối)──→ rejected     │
     │                                                                ↓
     └──(quá hạn 7 ngày, cron dọn)──→ xoá                          suspended
```

| Trạng thái | Đăng nhập | Xem UI | Chat bằng system key | Chat bằng BYOK |
|---|---|---|---|---|
| `pending_email` | ✓ | ✓ (banner nhắc verify) | ✗ | ✗ |
| `pending_approval` | ✓ | ✓ (banner chờ duyệt) | ✗ | **✓** |
| `active` | ✓ | ✓ | ✓ | ✓ |
| `rejected` | ✗ | — | — | — |
| `suspended` | ✗ | — | — | — |

Cho phép BYOK ở `pending_approval` là có chủ ý: người đó không tiêu tiền của bạn, nên không có lý do gì chặn họ.

### 11.2 Token

| Token | Dạng | TTL | Lưu ở |
|---|---|---|---|
| Access | JWT (HS256), claim: `sub`, `jti`, `role`, `tier`, `status`, `exp` | 15 phút | Bộ nhớ JS (**không** localStorage) |
| Refresh | chuỗi ngẫu nhiên 256-bit | 30 ngày | Cookie `HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth` |

Refresh **xoay vòng**: mỗi lần dùng sinh token mới, token cũ đánh dấu `used_at`. Nếu một token đã `used_at` bị dùng lại → **thu hồi toàn bộ family** và bắt đăng nhập lại (dấu hiệu bị đánh cắp).

**Vì sao access token không nằm trong localStorage:** một lỗ XSS đọc được localStorage. Giữ trong biến JS thì XSS vẫn nguy hiểm nhưng không tồn tại qua reload. Refresh cookie `HttpOnly` thì JS không đọc được.

### 11.3 Blacklist (R: bạn yêu cầu revoke khi logout/đổi mật khẩu)

```
Logout        → SET bl:jti:{jti} 1 EX <thời gian còn lại của access token>
                + đánh dấu refresh family revoked trong DB
Đổi mật khẩu  → revoke TẤT CẢ refresh family của user
                + SET bl:user:{uid} <now> EX 900
                  (middleware từ chối mọi access token có iat < giá trị này)
Admin suspend → như đổi mật khẩu
```

Vì access token chỉ sống 15 phút, blacklist trong Redis không bao giờ lớn. Đây là lợi ích trực tiếp của ADR-07.

**Cạm bẫy C21:** *Hiện tượng:* logout xong vẫn gọi API được vài phút. *Nguyên nhân:* chỉ xoá token ở client, không blacklist ở server. *Kiểm:* lưu access token, gọi logout, dùng lại token cũ → phải `401`.

### 11.4 Idempotency

```
POST bất kỳ có header Idempotency-Key:
  key = idem:{user_id}:{route}:{idempotency_key}
  SET key '{"state":"in_progress"}' NX EX 86400
    → NX thất bại:
        state == in_progress → 409 {code:"IN_PROGRESS"}
        state == done        → trả lại nguyên response đã lưu, status 200
    → NX thành công: xử lý, rồi SET key '{"state":"done","response":{...}}' EX 86400
```

**Cạm bẫy C22:** *Hiện tượng:* double-click vẫn tạo 2 message. *Nguyên nhân:* FE sinh `Idempotency-Key` mới cho mỗi lần bấm. *Sửa:* key gắn với **lần soạn thảo**, sinh khi ô nhập chuyển từ rỗng sang có chữ, chỉ đổi sau khi gửi thành công. *Kiểm:* S5.

### 11.5 Email

| Việc | Chi tiết |
|---|---|
| Interface | `app/core/mailer.py::Mailer` với `send(template, to, ctx)`; cài đặt `SMTPMailer` cấu hình hoàn toàn bằng `.env` |
| Dev | Mailpit — bắt mọi thư, xem ở `http://localhost:8025`, **không gửi ra ngoài** |
| Template | Jinja2, `backend/app/templates/email/*.html`, có bản text kèm |
| Token | Chuỗi ngẫu nhiên, lưu **hash** trong DB (không lưu bản rõ), TTL cấu hình được, dùng một lần nhưng idempotent (UC-01) |
| Chống dò | Đăng ký với email đã có và quên-mật-khẩu với email không tồn tại đều trả **cùng một** phản hồi thành công |

> ⚠️ **Mailpit chỉ dùng được khi dev.** Khi mời người thật vào (Phase 2 trở đi), phải có SMTP thật, nếu không không ai verify được email. Xem Q-02 §26.

### 11.6 Mật khẩu và Turnstile

- Argon2id (`argon2-cffi`), tham số trong `.env` (`ARGON2_TIME_COST`…)
- Độ dài tối thiểu 12 ký tự; kiểm tra với danh sách mật khẩu phổ biến (`zxcvbn` hoặc danh sách 10k top) thay vì bắt ký tự đặc biệt
- Cloudflare Turnstile ở form đăng ký và quên mật khẩu; `TURNSTILE_SECRET` rỗng → bỏ qua kiểm tra (cho dev), nhưng **log cảnh báo mỗi lần boot**

---

## 12. Subsystem: Web tools & chống SSRF ⭐

### 12.1 Vì sao đây là chỗ nguy hiểm nhất của cả app

Bạn yêu cầu: *"cần xử lí được trường hợp user gửi link và app truy cập được link đó"*. Câu đó, viết ra thành code, nghĩa là: **server của bạn sẽ gửi HTTP request tới bất kỳ địa chỉ nào một người lạ trên Internet bảo nó gửi, và trả kết quả về cho người lạ đó.**

Đó là định nghĩa của SSRF. Với kiến trúc Docker Compose, hậu quả cụ thể:

| Người dùng gửi | Nếu không chặn |
|---|---|
| `http://litellm:4000/v1/models` | Lộ cấu hình gateway, có thể lộ tên model nội bộ |
| `http://minio:9000/` | Truy cập object storage nội bộ |
| `http://api:8000/api/v1/admin/users` | Gọi API nội bộ (dù vẫn cần token, đây là bước dò đầu tiên) |
| `http://169.254.169.254/latest/meta-data/` | Trên cloud: **lấy credential của instance** |
| `http://127.0.0.1:6379/` | Redis không mật khẩu = toàn quyền |
| `file:///etc/passwd` | Đọc file hệ thống |

### 12.2 Bốn lớp phòng thủ

| Lớp | Cơ chế |
|---|---|
| **1. Cách ly mạng** | Service `fetcher` nằm ở Docker network **riêng**, chỉ có route ra ngoài, **không** join network nội bộ. Kể cả khi lớp 2–4 vỡ, `http://redis:6379` cũng không resolve được |
| **2. Kiểm URL** | Chỉ scheme `http`/`https`; chỉ cổng 80/443; từ chối userinfo (`http://user@evil`); chuẩn hoá trước khi so sánh |
| **3. Kiểm IP sau khi resolve DNS** | Resolve tên miền → với **mọi** địa chỉ trả về, từ chối nếu thuộc private/loopback/link-local/multicast/reserved (IPv4 **và** IPv6, gồm cả `::ffff:127.0.0.1`) |
| **4. Kiểm lại mỗi redirect** | `follow_redirects=False`, tự đi từng hop, chạy lại lớp 2–3 cho từng hop, tối đa `MAX_REDIRECTS=5` |

**DNS rebinding:** kẻ tấn công trả IP hợp lệ khi kiểm, rồi trả IP nội bộ khi fetch. Cách chặn: sau khi resolve và validate, **kết nối thẳng tới IP đã kiểm** và đặt header `Host` thủ công, thay vì để thư viện resolve lại. Với `httpx` dùng transport tuỳ chỉnh.

### 12.3 Leo thang sang Playwright

```
fetch(url):
  1. httpx GET, timeout 10 s, giới hạn 5 MB
  2. content-type không phải html/text → xử lý theo loại hoặc từ chối
  3. Trích text (trafilatura / readability)
  4. Nếu len(text) < JS_ESCALATE_MIN_CHARS (mặc định 200) VÀ HTML có > 3 thẻ <script>
       → coi là trang JS-heavy, chuyển sang Playwright
  5. Playwright: chromium headless, block ảnh/font/media, wait networkidle
     timeout 20 s, chụp text, đóng context (KHÔNG dùng lại)
```

Người dùng không cần biết đường nào được chọn — nhưng response có trường `fetch_method` để debug.

### 12.4 Tavily

- Chỉ dùng `search` và `extract`; endpoint và key trong `.env`
- Interface `SearchProvider` để sau này thêm nguồn khác không phải sửa call site
- Tavily lỗi hoặc hết quota → tool trả kết quả có `error`, model được báo và trả lời bằng kiến thức sẵn có; **chat không được chết** (AC của UC-08)
- Số lượt search mỗi ngày mỗi user: giới hạn bằng `tiers` (`can_use_web`, cộng một bộ đếm ngày)

### 12.5 Cạm bẫy

| # | Cạm bẫy |
|---|---|
| **C23** | **Hiện tượng:** SSRF guard viết đúng nhưng vẫn lọt. **Nguyên nhân:** validate URL rồi mới truyền URL đó cho `httpx`, và `httpx` **resolve DNS lần nữa**. **Kiểm:** test với DNS server giả trả IP khác nhau ở hai lần query |
| **C24** | **Hiện tượng:** Playwright container ăn hết RAM sau vài chục lần fetch. **Nguyên nhân:** browser context không đóng. **Kiểm:** chạy 50 fetch liên tiếp, `docker stats` phải trở về mức nền. **Sửa:** context per-request + `--single-process` + `mem_limit` trong compose |
| **C25** | **Hiện tượng:** fetch một link tải file 2 GB làm đầy đĩa. **Nguyên nhân:** không giới hạn kích thước response. **Sửa:** đọc theo stream, huỷ khi vượt `MAX_FETCH_MB`; **không** tin `Content-Length` do server đối phương khai |
| **C26** | **Hiện tượng:** trang tiếng Việt về bị lỗi font/ký tự. **Nguyên nhân:** đoán sai encoding khi header thiếu charset. **Sửa:** dùng `charset-normalizer`, ưu tiên thẻ `<meta charset>` trong HTML hơn header |

---

## 13. Subsystem: Skills & Sandbox ⭐

### 13.1 Vì sao khó, và vì sao chia hai mức

Bạn chọn mức (b): chạy được script kèm theo skill, tương thích format Anthropic. Điều đó có nghĩa **chạy mã tuỳ ý trên máy chủ của bạn, cho những người bạn chưa từng gặp mặt**. Đây là bề mặt tấn công lớn nhất của toàn bộ dự án.

Theo thoả thuận ở GĐ1, chia làm hai bước triển khai, **không gộp**:

| Mức | Nội dung | Phase |
|---|---|---|
| **(a)** Nạp tri thức | Đọc thư mục skill, inject `name` + `description` vào system prompt; model gọi tool `load_skill(name)` để lấy nội dung đầy đủ khi cần | P7.1 |
| **(b)** Chạy code | Tool `run_code` gửi sang service `sandbox`; kết quả (stdout/stderr/file sinh ra) quay lại hội thoại | P7.2 |

Mức (a) đã hữu ích một mình: rất nhiều skill là hướng dẫn thuần, không cần chạy gì.

### 13.2 Format skill (tương thích Anthropic)

```
skills/
  docx/
    SKILL.md            ← frontmatter: name, description, (license, allowed-tools)
    scripts/*.py
    references/*.md
```

Progressive disclosure ba tầng — điều này không phải để "cho giống Anthropic" mà vì lý do chi phí cụ thể: nạp toàn bộ 10 skill vào mỗi request có thể tốn 30–60k token mỗi lượt, tức là nhân đôi hoá đơn cho một tính năng dùng 5% thời gian.

| Tầng | Nạp khi nào | Kích thước điển hình |
|---|---|---|
| 1 | Luôn luôn (mọi request có skill được bật) | `name` + `description`, ~30 token/skill |
| 2 | Model gọi `load_skill(name)` | Toàn bộ `SKILL.md`, ~1–5k token |
| 3 | Model đọc file cụ thể hoặc chạy script | Theo nhu cầu |

### 13.3 Sandbox — cấu hình cụ thể

```yaml
sandbox:
  build: ./sandbox
  network_mode: "none"            # ← không có mạng, không đàm phán
  read_only: true                 # rootfs chỉ đọc
  tmpfs:
    - /work:size=256m,mode=1777   # nơi duy nhất ghi được
  mem_limit: 512m
  pids_limit: 128
  cpus: 1.0
  cap_drop: [ALL]
  security_opt:
    - no-new-privileges:true
  user: "65534:65534"             # nobody
```

Giao thức: `POST /exec {files: {...}, cmd: [...], timeout_s: N}` → `{exit_code, stdout, stderr, files_out: {...}}`. Mỗi lần gọi dùng thư mục tạm riêng và **xoá sạch sau khi xong**.

Nhưng `network_mode: none` có một hệ quả: **skill không thể `pip install`**. Vì vậy image sandbox phải cài sẵn bộ thư viện cho các skill chuẩn (`python-docx`, `openpyxl`, `python-pptx`, `pypdf`, `pillow`, `pandas`, `matplotlib`). Danh sách này nằm trong `sandbox/requirements.txt` — thêm skill cần thư viện mới = sửa file này + rebuild sandbox image. Đây là đánh đổi có ý thức: an toàn đổi lấy sự bất tiện khi mở rộng.

### 13.4 Phân quyền

`tiers.can_execute_skills` mặc định `false`. Admin bật cho từng user (UC-12). Model được cho biết rõ khả năng này qua system prompt để nó không cố dùng tool không có — nếu bị chặn, model nhận `tool_result` báo lỗi rõ ràng và tự chuyển hướng, chứ không im lặng thất bại (AC của UC-09).

### 13.5 Điểm cắm cho MCP sau này

MCP chưa làm ở v1 (R21), nhưng interface tool phải được thiết kế để MCP chỉ là **một nguồn tool khác**:

```python
class ToolProvider(Protocol):
    def list_tools(self, ctx: UserContext) -> list[ToolSpec]: ...
    async def call(self, name: str, args: dict, ctx: UserContext) -> ToolResult: ...

# v1:  BuiltinTools (web_search, fetch_url, load_skill, run_code)
# sau: MCPToolProvider(server_url)  — không sửa dòng nào ở call site
```

Registry gom tool từ mọi provider, tiền tố tên để tránh trùng (`mcp__{server}__{tool}`). **Đây là toàn bộ công việc "chuẩn bị cho MCP" ở v1** — không thêm container, không thêm bảng DB.

### 13.6 Cạm bẫy

| # | Cạm bẫy |
|---|---|
| **C27** | **Hiện tượng:** sandbox "an toàn" nhưng đọc được biến môi trường chứa secret. **Nguyên nhân:** compose kế thừa `env_file` chung. **Sửa:** service sandbox **không** khai báo `env_file`; kiểm bằng skill test chạy `os.environ` và assert không thấy key nào của Scarlet |
| **C28** | **Hiện tượng:** một skill treo làm chết cả worker. **Nguyên nhân:** không có timeout ở phía gọi. **Sửa:** timeout hai lớp — `SANDBOX_TIMEOUT_S` trong sandbox và timeout HTTP ngắn hơn 5 s ở worker. **Kiểm:** S11 |
| **C29** | **Hiện tượng:** file do skill sinh ra biến mất. **Nguyên nhân:** `/work` là tmpfs, mất khi container kết thúc. **Sửa:** sandbox trả file trong response (base64) và worker đẩy lên MinIO ngay; giới hạn `MAX_SKILL_OUTPUT_MB` |
| **C30** | **Hiện tượng:** hoá đơn tăng vọt khi bật nhiều skill. **Nguyên nhân:** nạp toàn bộ nội dung skill vào mỗi request thay vì progressive disclosure. **Kiểm:** log `prompt_tokens` với 0 skill và với 10 skill bật — chênh lệch phải < 500 token |

---

## 14. Subsystem: Artifacts & render sandbox

### 14.1 Artifact là gì trong Scarlet

Một khối nội dung độc lập, có phiên bản, hiện ở panel bên phải thay vì trong dòng chat. Bốn nguồn sinh ra artifact:

| Nguồn | Ví dụ |
|---|---|
| Model gọi tool `create_artifact` | HTML, React, SVG, Mermaid, Markdown |
| Model trả code block đủ lớn theo ngưỡng cấu hình | `ARTIFACT_MIN_CODE_LINES=20` |
| Skill sinh file | `.docx`, `.xlsx`, `.pptx` → lưu MinIO, artifact là con trỏ |
| User sửa artifact trong panel | Tạo phiên bản mới |

### 14.2 Phiên bản

`artifacts(id, message_id, kind, title, language, content, storage_key, version, parent_artifact_id, created_at)`

Mỗi lần cập nhật tạo **dòng mới** với `version = version + 1` và `parent_artifact_id` trỏ về gốc. Panel có điều hướng `v1 v2 v3`. Không sửa tại chỗ — vì user hay muốn quay lại bản trước, và vì artifact gắn với message cụ thể trong cây (§8).

### 14.3 Cách ly khi render live ⭐

Đây là phần bảo mật của subsystem này. Ba lớp chồng nhau:

| Lớp | Cơ chế | Chặn được gì |
|---|---|---|
| **1. Origin riêng** | Render ở `https://artifacts.<domain>` (local: `https://artifacts.localhost`), không phải origin chính | Cookie phiên không được gửi kèm; `localStorage` khác kho |
| **2. Thuộc tính sandbox** | `<iframe sandbox="allow-scripts allow-popups allow-forms">` — **cố tình không có** `allow-same-origin` | Script chạy với origin `null` ⇒ không đọc được kể cả storage của chính origin phụ |
| **3. CSP ở origin phụ** | `default-src 'none'; script-src 'unsafe-inline' https://cdn...; style-src 'unsafe-inline'; img-src data: https:; connect-src 'none'` | Chặn artifact gọi ra ngoài, gồm cả gọi ngược về API Scarlet |

> **Cảnh báo:** `sandbox="allow-scripts allow-same-origin"` cùng lúc là **vô hiệu hoá toàn bộ sandbox** — script có thể tự gỡ thuộc tính sandbox của chính iframe cha. Đây là lỗi phổ biến nhất khi làm tính năng này. Tiêu chí nghiệm thu là S12.

Nội dung được nạp vào iframe qua `postMessage` từ frame cha, không qua URL query (tránh giới hạn độ dài và tránh lộ nội dung trong log truy cập).

### 14.4 Render React

Artifact React cần: React + ReactDOM UMD, Babel standalone để biên dịch JSX trong trình duyệt, Tailwind CDN. Danh sách thư viện cho phép nằm trong `config/artifact_runtime.json` — thêm thư viện = sửa file, không sửa code (A3).

**Cạm bẫy C31:** *Hiện tượng:* artifact React trắng trang, console báo lỗi cú pháp ở dòng 1. *Nguyên nhân:* quên `type="text/babel"` hoặc dùng `import` ES module trong khi chỉ nạp UMD. *Sửa:* template render cung cấp sẵn `React`, `ReactDOM` ở global scope và tài liệu hoá điều này trong system prompt để model sinh code đúng dạng.

**Cạm bẫy C32:** *Hiện tượng:* artifact chạy vòng lặp vô hạn làm treo tab. *Nguyên nhân:* code do model sinh có bug. *Sửa:* iframe có watchdog — frame cha gửi ping mỗi 2 s, không có pong sau 6 s thì huỷ iframe và hiện nút "chạy lại".

---

## 15. Subsystem: File, ảnh, Vision

### 15.1 Luồng upload

```
FE chọn file
  → POST /api/v1/attachments (multipart)
  → api: kiểm size, kiểm MIME bằng MAGIC BYTES (không tin phần mở rộng, không tin Content-Type)
  → lưu MinIO: {user_id}/{yyyy}/{mm}/{uuid}{ext}
  → INSERT attachments(status='uploaded')
  → nếu là pdf/docx/xlsx → enqueue job trích text
  → trả {attachment_id, kind, preview_url}
```

### 15.2 Luật kiểm file

| Luật | Chi tiết |
|---|---|
| Kích thước | `tiers.max_upload_mb`, kiểm ở **cả** Nginx (`client_max_body_size`) và app |
| Loại | Allowlist trong `.env`: `image/png,image/jpeg,image/webp,application/pdf,...`. Blocklist là sai hướng |
| Nhận dạng | `python-magic` đọc magic bytes; file `.png` mà thực ra là `.exe` → từ chối |
| SVG | **Từ chối** upload SVG hoặc sanitize triệt để — SVG chứa được `<script>` |
| Tên file | Không bao giờ dùng tên gốc làm key lưu trữ; giữ tên gốc chỉ để hiển thị, escape khi render |
| Phục vụ lại | Qua presigned URL của MinIO, TTL ngắn (`PRESIGN_TTL_S=300`); **không** để bucket public |

### 15.3 Pipeline vision (thay OCR)

```
Ảnh:
  MinIO → resize cạnh dài ≤ VISION_MAX_EDGE_PX (mặc định 1568)
        → nén JPEG q=85 nếu > VISION_MAX_BYTES
        → base64 → content block image_url

PDF:
  Có text layer  → trích text bằng pymupdf (rẻ, chính xác, KHÔNG tốn token vision)
  Không có text  → render từng trang thành PNG → gửi vision
                   giới hạn MAX_PDF_PAGES_VISION (mặc định 10), quá thì báo user
```

**Vì sao resize là bắt buộc:** ảnh 4000×3000 gửi thẳng sẽ tốn hàng nghìn token vision và có provider trả `400`. Ảnh chụp màn hình điện thoại thường 1170×2532 — vẫn nên resize.

**Cạm bẫy C33:** *Hiện tượng:* hoá đơn tăng đột biến sau khi bật vision. *Nguyên nhân:* ảnh được gửi lại trong **mọi** lượt sau của hội thoại. *Sửa:* chỉ đính ảnh vào đúng message chứa nó; các lượt sau chỉ giữ mô tả text nếu có, và có cờ `RESEND_IMAGES_IN_HISTORY=false` mặc định tắt. *Kiểm:* log `prompt_tokens` ở lượt 2 và lượt 3 sau khi gửi ảnh — không được tăng theo số ảnh.

**Cạm bẫy C34:** *Hiện tượng:* ảnh xoay 90° khi gửi model dù hiển thị đúng trên web. *Nguyên nhân:* EXIF Orientation bị bỏ khi resize bằng Pillow. *Sửa:* `ImageOps.exif_transpose()` trước khi resize.

---

## 16. Subsystem: Share, Voice, Admin panel

### 16.1 Share hội thoại

Theo ADR-14, share tạo **snapshot bất biến**:

```
POST /conversations/{cid}/share
  → dựng đường đi hiện tại (§8.3)
  → serialize thành JSONB: [{role, content, model_display_name, created_at, artifacts:[...]}]
  → INSERT shared_conversations(token, snapshot_json, owner_id, created_at, revoked_at NULL)
  → trả https://<domain>/s/{token}
```

| Yêu cầu | Cách làm |
|---|---|
| Ai có link cũng xem được | `GET /s/{token}` không cần auth; server render từ `snapshot_json` |
| Chat tiếp phải đăng nhập | Nút "Chat tiếp" → nếu chưa đăng nhập thì chuyển sang login kèm `?next=/s/{token}/fork` |
| Fork | `POST /s/{token}/fork` tạo hội thoại **mới** thuộc về người bấm, nội dung copy từ snapshot; chủ cũ không bị ảnh hưởng |
| Không lộ | Snapshot **không** chứa: email chủ, `model_id` nội bộ, chi phí, `user_id`, attachment key gốc |
| Ảnh trong snapshot | Copy sang prefix `public/` của MinIO với key ngẫu nhiên mới, hoặc phục vụ qua endpoint proxy có kiểm token — **không** presign key gốc |
| SEO | `<meta name="robots" content="noindex">` — link công khai không có nghĩa là muốn Google đánh chỉ mục |

Cột `revoked_at` có sẵn dù v1 không dùng (R15) — thêm cột rẻ, thêm bảng đắt.

### 16.2 Voice input & TTS

Theo ADR-13, dùng Web Speech API. Ba điều phải xử lý đúng:

| Vấn đề | Cách xử lý |
|---|---|
| Chỉ chạy trên **secure context** | Đã có HTTPS từ P0 (R2) — đây là lý do kỹ thuật thứ hai buộc phải có TLS sớm |
| Firefox **không** hỗ trợ `SpeechRecognition` | Feature-detect; không hỗ trợ thì **ẩn nút**, không để nút bấm không phản ứng |
| Chất lượng tiếng Việt phụ thuộc trình duyệt/OS | Chấp nhận. Ghi rõ trong tooltip là tính năng của trình duyệt. Interface `VoiceProvider` ở FE để sau này thay bằng Whisper API mà không sửa component |

TTS (`speechSynthesis`) chọn giọng `vi-VN` nếu có, không thì giọng mặc định; nút đọc đặt cùng hàng với Copy/Like/Dislike/Retry.

### 16.3 Admin panel

Không phải app riêng — là các route `/admin/*` trong cùng FE, chỉ hiện khi `role=admin`, và **mọi** endpoint `/api/v1/admin/*` kiểm lại quyền phía server (không tin FE).

| Màn hình | Nội dung |
|---|---|
| Duyệt user | Danh sách `pending_approval`, nút Duyệt/Từ chối, xem email + thời điểm đăng ký |
| Người dùng | Bảng user: trạng thái, tier, chi tiêu 7 ngày, số hội thoại; hành động: đổi tier, override hạn mức, bật `can_execute_skills`, suspend |
| Chi phí | Biểu đồ theo ngày; bảng theo user và theo model; **hai cột tách riêng** `metered` và `unmetered` (§9.5) |
| Model | Trạng thái health từng provider, nút reload catalog, bật/tắt từng model |
| Hệ thống | Độ dài hàng đợi arq, số stream đang chạy, phiên bản, kết quả healthcheck |
| Audit log | Mọi hành động admin: ai, lúc nào, làm gì, với ai |

---

## 17. Mô hình dữ liệu

DDL đầy đủ ở [Phụ lục A](#phụ-lục-a--ddl-đầy-đủ). Mục này giải thích các quyết định **không hiển nhiên**.

### 17.1 Bảng

| Bảng | Vai trò |
|---|---|
| `users` | Tài khoản, trạng thái (§11.1), tier, role |
| `refresh_tokens` | Family, xoay vòng, phát hiện tái sử dụng |
| `email_tokens` | Verify + reset, lưu **hash** |
| `tiers` | Hạn mức và quyền — dữ liệu, không phải code |
| `user_provider_keys` | BYOK, mã hoá AES-GCM |
| `conversations` | Tiêu đề, model mặc định, `active_leaf_id`, `system_prompt_override` |
| `messages` | **Cây** (§8), nội dung, trạng thái stream, usage |
| `attachments` | File/ảnh, con trỏ MinIO, text đã trích |
| `artifacts` | Có phiên bản (§14.2) |
| `usage_events` | Một dòng mỗi lần gọi model, giá snapshot |
| `shared_conversations` | Snapshot JSONB |
| `skills` | Đăng ký skill, bật/tắt theo user |
| `user_settings` | Tuỳ chọn cá nhân (theme, model mặc định, bật/tắt tính năng) |
| `audit_logs` | Hành động admin |
| `feature_flags` | Bật/tắt tính năng không cần deploy |

### 17.2 Ghi chú thiết kế — các trường không hiển nhiên

| Trường | Vì sao tồn tại |
|---|---|
| `messages.parent_id` nullable | Message gốc của một nhánh có `parent_id = NULL`; một conversation có thể có **nhiều** gốc (khi sửa message đầu tiên) — §8.2 |
| `messages.status` | `queued / streaming / completed / failed / cancelled`. Client cần biết để hiển thị đúng; reaper cần để dọn (§7.6) |
| `messages.heartbeat_at` | Chỉ có ý nghĩa khi `status='streaming'`; reaper so với `now()` (§7.6) |
| `messages.content` | Ghi **một lần** khi xong. Trong lúc stream, nguồn sự thật là Redis. Đây là lý do C5 tồn tại |
| `messages.created_at` mặc định `clock_timestamp()` | Cột `created_at` **duy nhất** trong schema không dùng `now()`. `now()` là bí danh của `transaction_timestamp()` — hằng số suốt một giao dịch — nên mọi message ghi trong cùng một transaction sẽ mang `created_at` **bằng nhau**, và `ORDER BY created_at` của §8.3 không sắp được chúng (C13). Đo trên Postgres 17: 3 INSERT rời rạc trong một transaction cho 1 giá trị với `now()`, 3 giá trị với `clock_timestamp()`. Sửa ở migration 0002; lý do đầy đủ và các phương án đã loại nằm ở NQ-18 trong `tasks.md` |
| `messages.raw_response` JSONB | Giữ nguyên response cuối của provider để debug tool-call vỡ; TTL dọn sau `RAW_RESPONSE_KEEP_DAYS` |
| `usage_events.price_snapshot` JSONB | A7 — đổi giá catalog không được sửa lịch sử |
| `usage_events.cost_confidence` | `exact` / `low`. Model qua 9Router là `low` (§9.5) |
| `usage_events.key_source` | `system` / `byok`. Quyết định có trừ quota hay không (§10.5) |
| `conversations.active_leaf_id` | Con trỏ nhánh đang xem. Không phải khoá ngoại `NOT NULL` vì hội thoại rỗng chưa có message nào |
| `attachments.extracted_text` | Cache kết quả trích text để không trích lại mỗi lượt |
| `users.limit_override_json` | Ghi đè hạn mức cho **một** user mà không phải tạo tier mới |
| `shared_conversations.snapshot_json` | Cố tình phi chuẩn hoá (denormalize). Chuẩn hoá ở đây sẽ khiến snapshot thay đổi khi dữ liệu gốc đổi — đúng thứ ADR-14 muốn tránh |

### 17.3 Chừa chỗ cho RAG (chưa làm)

Khi làm RAG, thêm: `CREATE EXTENSION vector;` + bảng `documents`, `chunks(embedding vector(N))`, `collections`. **Không** thêm gì ở v1. Điều duy nhất phải làm ngay là: **không đặt tên bảng/cột trùng** với các tên trên, và giữ `attachments` đủ tổng quát để sau này một attachment có thể được index.

### 17.4 Index quan trọng

| Index | Vì sao |
|---|---|
| `messages(conversation_id, parent_id)` | Đếm anh em (§8.3) |
| `messages(parent_id)` | Recursive CTE đi ngược |
| `messages(status, heartbeat_at) WHERE status='streaming'` | Partial index cho reaper — quét rất rẻ |
| `usage_events(user_id, created_at DESC)` | Dựng lại quota (§10.3), báo cáo admin |
| `conversations(user_id, updated_at DESC)` | Sidebar |
| `users(email)` UNIQUE, lower-case | Chống trùng do khác hoa/thường |
| `refresh_tokens(family_id)` | Thu hồi cả family |

---

## 18. API surface

Hợp đồng với frontend. Tiền tố `/api/v1`. Mọi lỗi trả về theo một dạng duy nhất:

```json
{ "error": { "code": "QUOTA_EXCEEDED", "message": "…", "details": {...} } }
```

### 18.1 Auth

| Method | Path | Ghi chú |
|---|---|---|
| POST | `/auth/register` | Turnstile; luôn trả 200 dù email trùng |
| POST | `/auth/verify-email` | Idempotent |
| POST | `/auth/resend-verification` | Rate limit 3/giờ |
| POST | `/auth/login` | Trả access + set cookie refresh |
| POST | `/auth/refresh` | Xoay vòng; phát hiện tái sử dụng |
| POST | `/auth/logout` | Blacklist jti + revoke family |
| POST | `/auth/forgot-password` · `/auth/reset-password` | Rate limit |
| GET | `/auth/me` | User + tier + quota còn lại + trạng thái |

### 18.2 Chat ⭐

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/conversations` | Phân trang cursor, sắp theo `updated_at` |
| POST | `/conversations` | Tạo rỗng |
| GET | `/conversations/{id}` | Metadata + đường đi hiện tại + `sibling_index/count` mỗi message |
| PATCH | `/conversations/{id}` | Đổi tiêu đề, model mặc định, ghim, `active_leaf_id` |
| DELETE | `/conversations/{id}` | Soft delete |
| GET | `/conversations/{id}/export?format=json\|md` | Xuất **đường đi hiện tại** hoặc `?full=true` để xuất cả cây. Streaming response, không dựng cả file trong RAM |
| **POST** | **`/conversations/{id}/messages`** | ⭐ `Idempotency-Key` bắt buộc. Trả **202** + `stream_url`. Body có `parent_id` client đang thấy (C14) |
| **GET** | **`/messages/{id}/stream`** | ⭐ SSE. `Last-Event-ID` hoặc `?cursor=` |
| POST | `/messages/{id}/cancel` | |
| POST | `/messages/{id}/retry` | Tạo anh em, cho phép đổi `model_id` |
| PATCH | `/messages/{id}` | Sửa nội dung message user → tạo nhánh mới |
| POST | `/messages/{id}/feedback` | `like` / `dislike` + lý do tuỳ chọn |
| GET | `/messages/{id}/siblings` | Điều hướng nhánh |

### 18.3 Model, file, tool

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/models` | Đã lọc theo user (ADR-12), có `available: bool` và `unavailable_reason` |
| POST | `/attachments` | multipart |
| GET | `/attachments/{id}` | Presigned URL, TTL ngắn |
| GET | `/artifacts/{id}` · `/artifacts/{id}/versions` | |
| GET | `/skills` · PUT `/skills/{name}/toggle` | Bật/tắt cho user hiện tại |

### 18.4 Cài đặt cá nhân

| Method | Path |
|---|---|
| GET/PUT | `/settings` (theme, model mặc định, bật/tắt tính năng) |
| GET | `/settings/keys` (chỉ 4 ký tự cuối) |
| PUT/DELETE | `/settings/keys/{provider}` |
| GET | `/settings/usage` (chi tiêu của chính mình) |

### 18.5 Share & admin

| Method | Path |
|---|---|
| POST | `/conversations/{id}/share` |
| GET | `/s/{token}` (công khai, không auth) |
| POST | `/s/{token}/fork` (cần auth) |
| GET | `/admin/users` · POST `/admin/users/{id}/approve` · `/reject` · `/suspend` |
| PATCH | `/admin/users/{id}` (tier, override, quyền skill) |
| GET | `/admin/usage` (theo ngày/user/model, tách `metered`/`unmetered`) |
| GET/PATCH | `/admin/tiers` |
| POST | `/admin/catalog/reload` |
| GET | `/admin/system` · `/admin/audit-logs` |

### 18.6 Debug & health

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/health` | Rỗng, nhanh, cho Docker healthcheck |
| GET | `/health/deep` | Postgres, Redis, MinIO, LiteLLM, 9Router — mỗi cái có `ok` + `latency_ms` |
| GET | `/_debug/sse` | Phát 1 dòng mỗi 200 ms trong 10 s. **Dùng để kiểm C1**, chỉ bật khi `DEBUG=true` |
| GET | `/_debug/stream/{message_id}` | Dump toàn bộ Redis Stream của một message |

---

## 19. Chống hardcode & cấu hình ⭐

Yêu cầu rõ ràng của bạn: *"Hạn chế hardcode nhất có thể, app phải linh hoạt và dễ dàng sửa đổi, update, add features sau này."* Mục này biến câu đó thành luật kiểm chứng được.

### 19.1 Thứ gì sống ở đâu

| Loại | Sống ở | Đổi bằng cách | Cần restart? |
|---|---|---|---|
| Secret (key, mật khẩu DB, JWT secret) | `.env` | Sửa file | Có |
| Endpoint hạ tầng (`DATABASE_URL`, `REDIS_URL`, `LITELLM_BASE_URL`) | `.env` | Sửa file | Có |
| Danh sách model, giá, capability, provider | `config/model_catalog.json` | Sửa file + `POST /admin/catalog/reload` | **Không** |
| Định tuyến/fallback của LiteLLM | `config/litellm.config.yaml` | Sửa file | Chỉ container litellm |
| Hạn mức, quyền theo tier | Bảng `tiers` | Admin panel | Không (cache 60 s) |
| Bật/tắt tính năng | Bảng `feature_flags` | Admin panel | Không |
| Thư viện cho artifact React | `config/artifact_runtime.json` | Sửa file | Không |
| Thư viện cho sandbox | `sandbox/requirements.txt` | Sửa + rebuild image sandbox | Có (riêng sandbox) |
| System prompt | `config/prompts/*.jinja` | Sửa file | Không (đọc lại có cache 60 s) |
| Màu sắc, radius, spacing của UI | `frontend/src/styles/theme.css` (CSS variables) | Sửa file | Không (Tailwind v4) |
| Chuỗi hiển thị tiếng Việt | `frontend/src/locales/vi.json` | Sửa file | Không |

### 19.2 Bốn luật

| # | Luật |
|---|---|
| **L1** | **Không literal bị cấm trong code.** Danh sách cấm: tên model, giá tiền, URL provider, con số hạn mức, tên capability dạng chuỗi rời rạc. Chúng phải đến từ config layer |
| **L2** | **Fail-fast khi boot.** `Settings` dùng `pydantic-settings` với validator. Thiếu biến bắt buộc → raise, in **đúng tên biến**, exit ≠ 0 (S1). Không có `os.getenv("X", "default-cua-toi")` cho bất cứ thứ gì quan trọng |
| **L3** | **Thêm một tính năng mới không được sửa file cũ ở nhiều chỗ.** Tool mới = thêm một file trong `app/tools/` + đăng ký vào registry. Provider mới = thêm vào catalog. Skill mới = thêm thư mục |
| **L4** | **Mọi con số ma đều phải có tên.** `if len(text) < 200` là sai; `if len(text) < settings.JS_ESCALATE_MIN_CHARS` là đúng |

### 19.3 Cấu trúc Settings

```python
class Settings(BaseSettings):
    # Bắt buộc — không có default
    DATABASE_URL: PostgresDsn
    REDIS_URL: RedisDsn
    JWT_SECRET: SecretStr
    MASTER_ENCRYPTION_KEY: SecretStr
    LITELLM_MASTER_KEY: SecretStr

    # Có default hợp lý — nhưng vẫn ghi trong .env.example
    STREAM_TTL_S: int = 3600
    MAX_CONCURRENT_STREAMS: int = 3
    VISION_MAX_EDGE_PX: int = 1568
    JS_ESCALATE_MIN_CHARS: int = 200

    @field_validator("JWT_SECRET")
    def _strong(cls, v):
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET phải dài ≥ 32 ký tự")
        return v
```

### 19.4 Lệnh kiểm rò rỉ — chạy trong `make check-hardcode`

```bash
# API không được gọi model/tool trực tiếp (§5.3)
grep -rnE "litellm|openai|anthropic|AsyncClient\(" backend/app/api/ && exit 1

# Không tên model literal ngoài config layer
grep -rnE "\"(deepseek|claude|gpt|gemini)-[a-z0-9.-]+\"" backend/app/ --include=*.py \
  | grep -v "app/config/" | grep -v "tests/" && exit 1

# Không màu literal trong component React
grep -rnE "#[0-9a-fA-F]{6}|rgb\(" frontend/src/components/ && exit 1

# Không secret lọt vào repo
grep -rnE "sk-[a-zA-Z0-9]{20,}" --exclude-dir=node_modules . && exit 1
```

Lệnh này chạy trong pre-commit hook và là một phần của DoD chung trong `tasks.md`.

---

## 20. Bảo mật & quyền riêng tư

| Hạng mục | Yêu cầu |
|---|---|
| **Truyền tải** | HTTPS bắt buộc mọi nơi (R2). HSTS khi đã có domain thật. Không HSTS khi còn dùng `mkcert` cho localhost |
| **Mật khẩu** | Argon2id, tham số trong `.env`, tối thiểu 12 ký tự, đối chiếu danh sách phổ biến |
| **Token** | §11.2. Access trong bộ nhớ JS, refresh trong cookie `HttpOnly` |
| **BYOK** | AES-256-GCM, nonce riêng mỗi bản ghi, không bao giờ hiển thị lại, redact khỏi mọi log (C20) |
| **Phân quyền** | Mọi truy vấn tài nguyên đều lọc `user_id` **trong câu SQL**, không lọc ở tầng Python sau khi đã lấy về |
| **IDOR** | Test bắt buộc: user A gọi `/conversations/{id-của-B}` → **404** (không phải 403 — 403 xác nhận tài nguyên tồn tại) |
| **SSRF** | §12, tiêu chí S10 |
| **Chạy code** | §13.3, tiêu chí S11 |
| **XSS** | Markdown render qua sanitizer allowlist; artifact ở origin phụ (§14.3); không `dangerouslySetInnerHTML` ngoài renderer đã sanitize |
| **CSRF** | API dùng Bearer token (không phải cookie) ⇒ miễn nhiễm phần lớn. Riêng `/auth/refresh` dùng cookie → thêm kiểm `Origin` header |
| **Upload** | §15.2 |
| **Prompt injection** | Nội dung web fetch và file được bọc trong khối `<untrusted_content>` với chỉ dẫn rõ trong system prompt là không được coi đó là chỉ thị. **Không coi đây là biện pháp đủ** — vì vậy tool có tác dụng phụ (run_code) phải có quyền riêng, không bật mặc định |
| **Log** | Không log: mật khẩu, token, key BYOK, nội dung message đầy đủ (chỉ log độ dài + hash). Có middleware redact |
| **Audit** | Mọi hành động admin ghi `audit_logs` |
| **Backup** | `pg_dump` hằng ngày + mirror MinIO; **phải có một lần diễn tập khôi phục** trước khi mời người thật vào (task riêng trong `tasks.md`) |
| **Quyền riêng tư** | Người dùng xoá được hội thoại và tài khoản của mình; xoá tài khoản → xoá cứng key BYOK, soft-delete phần còn lại rồi purge sau `PURGE_AFTER_DAYS` |
| **Điều cần nói rõ với người dùng** | Nội dung chat **được gửi tới nhà cung cấp LLM bên ngoài** (DeepSeek/Anthropic), và **admin về mặt kỹ thuật đọc được** dữ liệu trong DB. Ghi trong trang đăng ký, không giấu |

---

## 21. Observability, Eval & chi phí

### 21.1 Log

JSON có cấu trúc, mỗi dòng có `request_id`, `user_id`, `route`, `latency_ms`. `request_id` sinh ở Nginx (`$request_id`), truyền qua header, và **theo job vào worker** — nếu không, không thể lần dấu một câu trả lời từ lúc bấm gửi tới lúc ghi usage.

### 21.2 Chỉ số phải đo

| Chỉ số | Vì sao |
|---|---|
| TTFT p50/p95 theo model | Tiêu chí S2; cũng là cách phát hiện 9Router đang fallback xuống tier chậm |
| Tỉ lệ stream kết thúc bằng `error` | Sức khoẻ tổng thể |
| Số lần reconnect SSE trên mỗi message | Tăng đột biến = có vấn đề mạng hoặc proxy (C2) |
| Độ dài hàng đợi arq | Worker không theo kịp |
| Chi phí/ngày, chi phí/user, chi phí/model | S13 |
| Số lần chạm quota | Hạn mức đặt sai (quá chặt hoặc quá lỏng) |
| Số lần SSRF bị chặn | Có ai đang dò không |

Với 20 user, không cần Prometheus + Grafana ngay. Một bảng trong admin panel đọc từ `usage_events` và Redis là đủ. **Ghi vào Backlog:** nếu sau này cần, thêm `prometheus_client` và một container Grafana.

### 21.3 Eval — golden set khi thêm model

Đây là thứ hay bị bỏ qua và luôn phải trả giá. Mỗi khi thêm một model vào catalog, chạy:

```bash
make eval MODEL=deepseek-chat
```

Bộ 12 case cố định, mỗi case kiểm một khả năng cụ thể của **tầng tích hợp**, không phải chất lượng model:

| Case | Kiểm |
|---|---|
| Trả lời ngắn tiếng Việt có dấu | Encoding end-to-end, không lỗi C9 |
| Trả lời dài > 2000 token | Chunking, không timeout |
| Sinh code block | Parse fence đúng ngôn ngữ |
| Gọi 1 tool | Tool-call parsing |
| Gọi 2 tool liên tiếp | Vòng lặp tool |
| Tool trả lỗi | Model xử lý được lỗi tool |
| Có ảnh (nếu `vision`) | Pipeline §15.3 |
| Reasoning (nếu có) | Event `reasoning` tách đúng |
| Bị huỷ giữa chừng | §7.5 |
| Context gần đầy | Cắt ngân sách §9.6 |
| Ký tự đặc biệt và emoji | JSON escape (C10) |
| Hai lượt liên tiếp | Lịch sử được gửi đúng |

Kết quả ghi vào `evals/results/{model}-{date}.json`. **Model chưa qua eval không được đặt `enabled: true` trong catalog.**

### 21.4 Điểm cắm cho RAG (chưa làm)

Khi làm, RAG sẽ là một `ToolProvider` (§13.5) tên `search_knowledge`, một mục riêng trên sidebar để quản lý collection, và dùng **chung** model từ catalog cho phần sinh câu trả lời. Ba việc phải làm đúng **ngay bây giờ** để sau này không phải sửa:

1. `attachments` đủ tổng quát để một file có thể vừa là đính kèm chat vừa là nguồn cho RAG
2. Tool registry cho phép thêm provider mà không sửa call site
3. Không dùng trước các tên bảng `documents`, `chunks`, `collections`

### 21.5 Bảng chi phí ước tính

Hạ tầng: **0 đồng** (self-host trên máy có sẵn). Chi phí duy nhất là token.

| Hạng mục | Ước tính | Ghi chú |
|---|---|---|
| 20 user × 30 tin nhắn/tháng × ~3k token, model rẻ (DeepSeek) | ~2–5 USD/tháng | Kịch bản thực tế nhất |
| Nếu ai đó dùng nhiều model đắt | có thể ×10–50 | ← chính là lý do có quota (§10) |
| Tavily | 1000 lượt/tháng miễn phí | Vượt thì tính phí |
| Model qua 9Router | không đo được chính xác | §9.5 |
| Domain | ~10 USD/năm | Khi trỏ tên miền thật |

**Bẫy tiền — bốn cái cụ thể:**

| Bẫy | Cách chặn |
|---|---|
| Một user tò mò gửi 200 tin nhắn với model đắt trong một buổi tối | Quota 5h (§10.3) |
| Ảnh gửi lại trong mọi lượt sau | `RESEND_IMAGES_IN_HISTORY=false` (C33) |
| Skill được nạp toàn bộ vào mỗi request | Progressive disclosure (C30) |
| Hội thoại dài gửi nguyên lịch sử mỗi lượt | Ngân sách token §9.6 |

---

## 22. Triển khai

### 22.1 Compose profiles

| Profile | Service |
|---|---|
| `core` | nginx · web · api · worker · postgres · redis · minio · litellm |
| `tools` | fetcher (Playwright) · sandbox |
| `dev` | mailpit · adminer |

`docker compose --profile core --profile tools up -d`. Chia profile để lúc phát triển phần chat không phải chờ build Playwright.

### 22.2 Thứ tự khởi động

`depends_on` với `condition: service_healthy` cho postgres, redis, minio, litellm. Migration chạy bằng **một service `migrate` riêng** chạy `alembic upgrade head` rồi thoát — **không** chạy migration trong entrypoint của api, vì nếu scale api lên 2 replica thì hai tiến trình sẽ migrate đồng thời.

### 22.3 Nginx — cấu hình cốt lõi

Toàn văn ở [Phụ lục D](#phụ-lục-d--nginxconf-phần-cốt-lõi). Ba điều quan trọng nhất:

```nginx
location ~ ^/api/v1/(messages/[^/]+/stream|_debug/sse) {
    proxy_pass http://api:8000;
    proxy_buffering off;          # ← C1: thiếu dòng này là streaming chết
    proxy_cache off;
    proxy_read_timeout 3600s;     # ← C2: mặc định 60s sẽ cắt câu trả lời dài
    proxy_set_header Connection '';
    proxy_http_version 1.1;
}
```

### 22.4 HTTPS local ngay từ Phase 0

```bash
mkcert -install
mkcert localhost "*.localhost" 127.0.0.1
```

**Vì sao không đợi tới lúc có domain:** ba tính năng chỉ chạy trên secure context — Web Speech API (R16), clipboard API (nút Copy), service worker (PWA). Nếu dev suốt trên `http://localhost` rồi mới bật HTTPS ở Phase 8, sẽ phát hiện một loạt thứ hỏng cùng lúc và không biết cái nào gây ra cái nào. Chi phí làm sớm: khoảng 30 phút.

### 22.5 Cạm bẫy WSL2 — cụ thể cho máy của bạn

| # | Cạm bẫy |
|---|---|
| **C35** | **Hiện tượng:** hot-reload chậm 10–20×, `npm install` mất nhiều phút. **Nguyên nhân:** code nằm ở `/mnt/c/...` (đi qua 9P filesystem). **Sửa:** repo phải nằm trong `~/` của WSL. **Kiểm:** `pwd` bắt đầu bằng `/home/`, không phải `/mnt/c/` |
| **C36** | **Hiện tượng:** `Connection refused` tới 9Router. **Nguyên nhân:** C17. **Kiểm:** lệnh ở C17 |
| **C37** | **Hiện tượng:** file watcher không nhận thay đổi. **Nguyên nhân:** inotify không xuyên qua ranh giới Windows↔WSL. **Sửa:** hệ quả của C35; hoặc bật polling (chậm, chỉ là biện pháp cuối) |
| **C38** | **Hiện tượng:** `vmmem` ăn hết RAM Windows. **Nguyên nhân:** WSL2 không tự trả RAM. **Sửa:** `.wslconfig` với `memory=8GB` và `swap=2GB` |
| **C39** | **Hiện tượng:** script `.sh` báo `bad interpreter: ^M`. **Nguyên nhân:** Git trên Windows đổi line ending. **Sửa:** `.gitattributes` với `*.sh text eol=lf` |

### 22.6 Từ local lên domain — thay đổi tối thiểu

| Việc | Thay đổi |
|---|---|
| Trỏ DNS | Bản ghi A cho `<domain>` **và** `artifacts.<domain>` |
| Chứng chỉ | Đổi `mkcert` sang Let's Encrypt (certbot hoặc Caddy) |
| `.env` | `PUBLIC_BASE_URL`, `ARTIFACTS_BASE_URL`, `CORS_ORIGINS` |
| SMTP | Từ Mailpit sang provider thật (Q-02) |
| Bật HSTS | Chỉ sau khi chắc chắn chứng chỉ ổn |
| 9Router | Nếu máy deploy khác máy chạy 9Router → cần đường mạng riêng, **không** mở `:20128` ra Internet |

### 22.7 Backup

```
Hằng ngày 03:00:  pg_dump -Fc → /backup/db-{date}.dump   (giữ 14 bản)
                  mc mirror minio/scarlet /backup/minio/  (giữ 7 bản)
Hằng tuần:        copy ra ổ ngoài / máy khác
```

**Backup chưa từng khôi phục thử không phải là backup.** `tasks.md` có một task riêng: xoá volume, khôi phục từ dump, xác nhận đăng nhập được và hội thoại cũ còn nguyên.

---

## 23. Cấu trúc repo

```
scarlet/
├── CLAUDE.md                    # luật rút gọn, agent đọc mỗi phiên (§0)
├── Makefile                     # test, lint, check-hardcode, eval, migrate
├── docker-compose.yml
├── docker-compose.override.yml  # chỉ cho dev: mount code, mailpit, adminer
├── .env.example                 # MỌI biến, có chú thích  (Phụ lục B)
├── .gitattributes               # C39
│
├── config/                      # ← mounted, không nằm trong image
│   ├── model_catalog.json       # §9.2
│   ├── litellm.config.yaml      # §22
│   ├── artifact_runtime.json    # §14.4
│   ├── prompts/*.jinja
│   └── nginx/nginx.conf
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic/versions/
│   └── app/
│       ├── main.py
│       ├── config/settings.py catalog.py     # §19.3 — nơi DUY NHẤT đọc env
│       ├── api/v1/  auth.py conversations.py messages.py stream.py
│       │            models.py attachments.py artifacts.py settings.py
│       │            share.py admin.py health.py
│       ├── core/    security.py jwt.py crypto.py mailer.py deps.py errors.py
│       ├── db/      models/  repositories/  session.py
│       ├── llm/     client.py adapters/ parser.py context.py tokens.py
│       ├── streaming/  producer.py  consumer.py  events.py   # §7
│       ├── quota/   estimator.py meter.py windows.py         # §10
│       ├── tools/   registry.py web_search.py fetch_url.py ssrf.py
│       │            run_code.py load_skill.py                # §12, §13
│       ├── skills/  loader.py registry.py
│       ├── workers/ main.py generate.py title.py extract.py reaper.py
│       └── templates/email/
│
├── frontend/
│   └── src/
│       ├── components/  chat/ sidebar/ artifacts/ settings/ admin/ ui/
│       ├── features/    auth/ chat/ models/ quota/
│       ├── lib/         api.ts sse.ts tree.ts                # sse.ts = §7 phía client
│       ├── locales/vi.json
│       └── styles/theme.css                                  # ← Claude Design sửa ở đây
│
├── sandbox/     Dockerfile  requirements.txt  server.py      # §13.3
├── fetcher/     Dockerfile  server.py                        # §12
├── skills/      docx/ xlsx/ ...                              # format Anthropic
├── evals/       cases/  runner.py  results/                  # §21.3
├── scripts/     bench_ttft.py  test_resume.py  test_idempotency.sh
└── docs/        KE-HOACH.md  tasks.md  HUONG-DAN-AGENT.md  META-LAP-KE-HOACH.md
```

---

## 24. Roadmap

### 24.1 Nguyên tắc xếp thứ tự

Không theo "hạ tầng → backend → frontend". Ba quy tắc:

1. **Hữu ích sớm nhất trước.** Bạn phải tự dùng được Scarlet từ cuối Phase 1.
2. **Phát hiện muộn thì đắt → kéo lên sớm.** Cây message và stream-resume ở Phase 1 (§3.3). Kết nối tới 9Router và HTTPS ở Phase 0.
3. **Mở cửa cho người lạ là việc CUỐI của nửa đầu.** Auth đầy đủ ở Phase 2, sau khi lõi đã chạy — không mời ai vào trước khi có quota và duyệt.

### 24.2 Bảng phase

| Phase | Tên | Giao được gì | Ước lượng | Lý do ở vị trí này |
|---|---|---|---|---|
| **P0** | Nền móng | `docker compose up` chạy, HTTPS local, migration, health, fail-fast config | 12–18 h | Xác minh **ngay** hai thứ có thể làm hỏng cả kiến trúc nếu phát hiện muộn: đường mạng tới 9Router (C17) và HTTPS (§22.4) |
| **P1** ⭐ | Chat lõi + resume | Chat được với 1 model qua CLI/HTTP; F5 không mất chữ; cây message | 24–32 h | §3.3. Đây là phase quyết định. **Không gộp task nào trong phase này** |
| **P2** | Auth, quota, admin | Mời người thật vào được an toàn | 20–28 h | Phải xong trước khi có người dùng thứ hai |
| **P3** | Giao diện | UI hoàn chỉnh: sidebar, model picker, code block, sáng/tối, responsive, animation | 30–40 h | Cần API ổn định trước. **Phần lớn là việc của NGƯỜI (Claude Design)** — R20 |
| **PS** | Standardize *(chèn 2026-09-23)* | Giao diện chuẩn hoá theo bản vẽ v2; nút chờ cho P4–P9; đặt tên hội thoại tự động; chọn mức suy luận; hồ sơ người dùng | 55–70 h | Sau P3 vì cần một giao diện đã dùng thật mới biết chuẩn hoá chỗ nào; trước P4 vì P4 là phase đầu tiên đặt nút mới vào ô nhập — §24.2b |
| **P4** | Ảnh & vision | Upload ảnh, hỏi về ảnh, PDF | 12–16 h | Sau khi UI có chỗ để đặt nút |
| **P5** | Artifacts | Panel phải, hiển thị + tải, rồi render live | 20–28 h | Phụ thuộc P3 |
| **P6** | Web tools | Tavily + fetch link + Playwright + SSRF | 16–22 h | Độc lập, có thể đổi chỗ với P5 |
| **P7** | Skills | (a) nạp tri thức → (b) sandbox chạy code | 24–32 h | Rủi ro cao nhất, làm khi mọi thứ khác đã ổn định |
| **P8** | Share, voice, export, PWA | Chia sẻ hội thoại, xuất JSON/Markdown, voice/TTS, cài như app | 16–22 h | Ít rủi ro, hoãn được |
| **P9** | Hoàn thiện | Eval đầy đủ, backup + diễn tập khôi phục, lên domain, tài liệu | 12–16 h | |

**Tổng: khoảng 180–250 giờ.** Không có deadline (R19), nên con số này chỉ để so sánh tương đối giữa các phase.

### 24.2b Phase S — Standardize *(chèn giữa P3 và P4, 2026-09-23)*

> **Mục này được thêm sau khi P3 xong.** Người dùng cho phép sửa file này **chỉ** bằng cách chèn Phase S vào giữa P3 và P4; mọi mục khác giữ nguyên từng chữ. Vì vậy những gì Phase S thêm vào hợp đồng chung (endpoint, cột DB, biến `.env`, khoá Redis, trường catalog) được liệt kê **ở đây** — S14 — chứ không ở §7.4, §17, §18, Phụ lục A/B. Agent làm P4 trở đi đọc S14 như phần mở rộng của các mục ấy (NQ-107).
>
> Thứ tự thực thi và DoD từng task: `tasks.md` §7b. Hướng dẫn thao tác cho người thiết kế (dán prompt gì vào Claude Design, giao gì cho agent): `docs/standardize-tutorial.md`.

#### S0 — Vì sao có phase này, và vì sao nó đứng trước P4

P3 giao một giao diện dùng được (M5). Dùng thật vài ngày thì lộ ra ba loại việc mà không phase nào phía sau sở hữu:

1. **Giao diện cần chuẩn hoá lại:** ô nhập, sidebar, header, Model Picker, trang Cài đặt, sáu màn auth. Người dùng vẽ lại bằng Claude Design (bản **v2**), vẫn trên Scarlet Design System.
2. **P4–P9 đều cần một chỗ trên màn hình:** nút đính kèm, công tắc Tìm web, mic, Chia sẻ, Xuất, thẻ artifact… Để mỗi phase tự chen nút của mình vào là vẽ lại bố cục sáu lần. Phase S vẽ và dựng **tất cả** những nút ấy một lần, ở trạng thái chưa bấm được (S12); phase sau chỉ còn việc gắn.
3. **Ba tính năng nhỏ đã có chỗ trong kiến trúc mà chưa ai xếp lịch:** đặt tên hội thoại tự động (`workers/title.py` đã nằm trong cây §23), hồ sơ người dùng (`users.display_name` đã có từ Phụ lục A), và chọn mức suy luận của model (đường `extra` của §9.1 đã có).

Đứng **trước** P4 vì P4 là phase đầu tiên đặt nút mới vào ô nhập (T-4.5, T-4.7). Chuẩn hoá sau P4 nghĩa là vẽ lại ô nhập hai lần.

#### S1 — Luật riêng của phase

- **A1–A10 giữ nguyên.** Không mục nào dưới đây nới một luật kiến trúc; chỗ nào chạm vào kiến trúc thì ghi rõ nó **thêm** gì.
- **Bản vẽ v1 và v2.** Bản Claude Design đã giao ở P3 (T-HD1…T-HD5, T-HD7) là **v1**. Bản vẽ lại trong phase này mang hậu tố **`-v2`** (T-HD1-v2 …). Hai màn chưa từng có bản vẽ nhận số mới: **T-HD8** (sáu màn auth) và **T-HD9** (trang Cài đặt). T-HD6 vẫn dành cho panel artifact của P5. Link của mọi bản v2 ghi ở `design/README.md`, mục v2 (NQ-108).
- **Quy tắc phân vai của `tasks.md` §3 không đổi:** Claude Design ra hình dạng và mã component; agent nối vào state/API/test và **không tự đổi màu, spacing, bố cục**.
- **Nút của phase tương lai không có hành vi:** không gọi API, không mở dialog. S12 định nghĩa đúng một component cho chúng.

#### S2 — Đổi tên định danh tiếng Việt không dấu

`CLAUDE.md` bản hiện hành đòi sửa mọi định danh dạng tiếng Việt không dấu còn tồn tại; NQ-87 trước đó chỉ áp luật tiếng Anh cho code mới. Phase S làm việc này **một lần, ở đầu phase** (T-S.1 🔒), trước khi các task sau viết thêm vào đúng những file ấy (NQ-109 thay NQ-87).

- **Phạm vi:** biến, hàm, lớp, prop, tên file, tên test — trong `backend/`, `frontend/src/`, `scripts/`.
- **Ngoài phạm vi, có chủ ý:** tên trường trên dây (JSON của API, ví dụ `streams_dang_chay`), khoá `vi.json`, tên bảng/cột Postgres, khoá Redis. Đó là hợp đồng với client, là dữ liệu đã lưu, hoặc cả hai — đổi chúng là một migration, không phải một lần đổi tên.
- Một phép kiểm tự động (`scripts/check_identifiers.py`, chạy trong `make lint`) canh để định danh loại này không quay lại.
- **Hành vi không đổi một dòng:** đây là commit đổi tên thuần tuý.

#### S3 — Catalog v4: provider hiển thị, ẩn đường trung gian, mức suy luận, giá

**(a) Provider hiển thị.** Hôm nay tên provider người dùng thấy là `providers[].label` — tức tên **đường đi** (9Router, Sub2API), không phải hãng làm ra model. Catalog v4 thêm (NQ-119):

- `providers[].user_visible: bool` — `false` cho đường trung gian (`ninerouter`, `sub2api`). Tên của chúng **không bao giờ** tới giao diện người dùng: không trong `GET /models`, không trong `unavailable_reason`, không trong badge, không trong `display_name`. Badge "9Router" bị gỡ khỏi catalog.
- `models[].display_provider` — hãng gốc ("Google AI", "xAI"…). **Bắt buộc** khi provider có `user_visible: false`; thiếu thì app không boot và in đúng `id` của model thiếu (cùng khuôn A4).
- Màn quản trị vẫn thấy đường đi thật — health đo theo đường đi (§9.5) — qua `GET /admin/models` (S14).

**(b) Mức suy luận (thinking effort).** Mỗi model có thể khai một khối `reasoning` (NQ-118):

```json
"reasoning": {
  "default": "high",
  "options": [
    { "id": "off",  "params": { "thinking": { "type": "disabled" } } },
    { "id": "low",  "params": { "thinking": { "type": "enabled" }, "reasoning_effort": "low" } },
    { "id": "high", "params": { "thinking": { "type": "enabled" }, "reasoning_effort": "high" } },
    { "id": "max",  "params": { "thinking": { "type": "enabled" }, "reasoning_effort": "max" } }
  ]
}
```

- `id` thuộc một bộ từ vựng cố định: `off · low · medium · high · xhigh · max`. **Nhãn hiển thị bằng tiếng Anh** — Off · Low · Medium · High · Extra High · Max — đặt trong `vi.json`, không trong catalog.
- `params` được **trộn nguyên văn** vào body request qua đường `extra` đã có của `LLMClient.stream` (§9.1). Code không biết tên provider nào (A3); backend vẫn chỉ nói Chat Completions (A9). `params` **không** bao giờ rời backend — FE chỉ nhận `id`.
- Ba trường tuỳ chọn cho những ca provider khác nhau, chỉ dùng khi T-S.2 đo ra là cần: `byok_params` (đường BYOK gọi thẳng provider có thể cần tham số khác đường LiteLLM), `alias` (9Router chọn mức bằng **tên model khác**, nên mỗi mức là một alias LiteLLM riêng), `omit_temperature` (Anthropic không nhận `temperature` tuỳ ý khi bật thinking).
- Model không khai `reasoning` ⇒ không có tuỳ chọn; picker hiện hàng Thinking Effort ở trạng thái mờ.
- **Không mức nào được vào catalog nếu chưa đo.** `litellm_settings.drop_params: true` (Phụ lục E) nghĩa là một tham số sai **không báo lỗi** — nó bị bỏ đi im lặng, và `200 OK` không chứng minh được gì. T-S.2 đo từng mức trên đường thật; mức nào không làm `reasoning_tokens` thay đổi thì bị loại.

Hiện trạng tra cứu ngày 2026-09-23 — là giả thuyết để T-S.2 đo, không phải kết luận:

| Model | Cơ chế | Các mức | Mặc định | Tắt được | Rủi ro đã biết |
|---|---|---|---|---|---|
| `deepseek-flash` | `thinking.type` + `reasoning_effort` | low · high · max | high | có | LiteLLM gộp low/medium thành high (issue BerriAI/litellm#27439) |
| `claude-haiku` (Haiku 4.5) | `thinking.budget_tokens` — Haiku 4.5 không có `effort` | ngân sách 1024 · 4096 · 6144 | off | có | đường BYOK (lớp tương thích OpenAI) bỏ qua `reasoning_effort` và không trả chữ suy luận |
| `nr-gemini-flash` (Gemini 3.8 Flash qua 9Router) | alias theo hậu tố `-low` / `-medium` / `-high` | low · medium · high | medium | không | `minimal` báo lỗi trên 3.8 Flash |
| `grok-4.6` (qua Sub2API) | `reasoning_effort` | low · medium · high · xhigh | high | không | chưa biết Sub2API có chuyển tham số đi không (B-250: nó đã bỏ qua `max_tokens`) |
| `ol-qwen-small` | — | — | — | — | không có suy luận |

**(c) Giá trong `GET /models`.** Picker hiện giá của model đang chọn (S11), nên `GET /models` trả thêm: giá niêm yết USD / 1M token vào và ra **dạng chuỗi** (cùng luật tiền của T-2.16), khung giá đang áp dụng và khung còn lại nếu model có `pricing_schedules` (DeepSeek cao/thấp điểm — backend tính theo múi giờ của catalog, FE không tự so giờ), cờ `estimated` cho giá lấy từ `manual_pricing`, và `pricing_mode`. Đơn vị là USD; không có tỷ giá nào trong hệ thống (NQ-120).

**(d) Model đặt tên hội thoại.** Khoá cấp cao `title_model` trong catalog: `{ "model": "deepseek-flash", "reasoning": "off", "max_output": <n> }`. Model phải tồn tại và `enabled`; kiểm lúc nạp catalog. Đổi model đặt tên là sửa một dòng dữ liệu, không sửa code (A3).

**(e) Tài liệu.** `docs/RUNBOOK-them-provider.md` được bổ sung — người dùng cho phép đích danh (NQ-118): cách khai `display_provider` / `user_visible`, cách thêm một mức suy luận (đo trước bằng `scripts/probe_reasoning.py`, rồi mới khai), cách chỉnh trần vào (`context_window`) và trần ra (`max_output`) cùng các ràng buộc giữa chúng.

#### S4 — Chọn mức suy luận, đầu-cuối

- `POST /conversations/{id}/messages` và `POST /messages/{id}/retry` nhận thêm `reasoning_effort` (một `id` của S3b). Mức không có ở model đó ⇒ `400 REASONING_UNSUPPORTED` **ở biên vào**, không tạo message nào.
- **Thứ tự thắng:** body › mức đã nhớ của user **cho model đó** › `reasoning.default` của catalog. Mức đã nhớ lưu **theo user × model** ở server, trong `user_settings.prefs_json` (bảng đã có từ migration 0001 và chưa dùng), ghi bằng `PUT /settings`.
- Worker trộn `params` của mức đã chọn vào request; ghi mức ấy vào cột mới `messages.reasoning_effort` và vào event `start` (§7.4 — thêm một trường, không thêm event).
- **Một nút Thử lại, không hai.** "Thử lại" và "Đổi model & thử lại" gộp làm một: nút duy nhất gửi model **và** mức đang chọn trên picker. UC-02 dòng 5 và UC-04 dòng 4 vẫn đạt — retry bằng model khác là chọn model khác trên picker rồi bấm Thử lại.
- **Quota:** `est_max` giữ nguyên công thức §10.2. Token suy luận nằm **trong** `max_tokens` ở mọi provider đã tra, nên trường hợp xấu nhất không đổi.
- **Va chạm đã biết với P6, ghi trước để P6 không phải phát hiện lại:** DeepSeek và Anthropic đều đòi gửi lại phần suy luận của lượt trước **khi có tool call**. B-33 hôm nay cố ý không bao giờ gửi lại suy luận. Ngày P6 bật tool, hai điều ấy va nhau (Backlog B-266).

#### S5 — Model Picker tự nạp; request không bao giờ chờ một lượt đo

Đo ngày 2026-09-23 trên stack thật, 9Router im lặng (không từ chối TCP): `GET /models` lần đầu **5.09 s**, lần sau 0.22 s, 31 s sau lại **5.06 s** — đúng `PROBE_TIMEOUT_S` mỗi khi bộ nhớ 30 s của `core/provider_health.py` hết hạn. Trong khoảng ấy picker hiện "Chưa có mô hình nào", và người dùng phải bấm làm mới.

Sửa ở gốc (NQ-113): trạng thái provider được **đo ngầm** — một lần lúc `api` khởi động, rồi làm tươi theo chu kỳ trong một tác vụ nền. Request **không bao giờ** `await` một lượt đo; nó đọc kết quả gần nhất, kèm `checked_at` (thời điểm backend đo, không phải lúc FE đọc). TTL và trần chờ chuyển từ hằng số trong `.py` sang `Settings` (A3). FE hiện trạng thái đang tải thay cho danh sách rỗng, và khi mở picker mà `checked_at` đã cũ hơn TTL thì tự hỏi lại. Đây là một lần nới **có điều kiện** Cạm bẫy ② của T-3.6 ("đừng gọi `GET /models` mỗi lần mở dropdown"): lần gọi thêm chỉ xảy ra khi dữ liệu đã cũ, và nó chỉ đọc bộ nhớ, không chờ đo.

#### S6 — Đặt tên hội thoại tự động

- **Khi nào:** handler của `POST .../messages` enqueue job `title` **ngay** khi nhận câu hỏi đầu tiên của một hội thoại chưa có tiêu đề, song song với `generate`. A1 giữ nguyên: handler chỉ tạo record và enqueue. Job id `title:{conversation_id}` nên một hội thoại không bao giờ được đặt tên hai lần (NQ-110).
- **Model:** `title_model` của catalog (S3d), suy luận tắt, trần token nhỏ. Prompt ở `config/prompts/title.jinja` (A3).
- **Tiền:** luôn dùng **system key**. Ghi `usage_events` với cột mới `purpose = 'title'` (mặc định `'chat'`); A7 áp như mọi dòng khác. Lượt đặt tên **không** trừ vào hai cửa sổ quota của user: `record_usage` không `ZADD`, **và** `rebuild_quota` chỉ đọc `purpose = 'chat'` — thiếu vế thứ hai thì lần dựng lại quota đầu tiên (§10.3) sẽ trừ oan mọi lượt đặt tên.
- **Chữ chảy — SSE thật:** worker ghi vào một Redis Stream riêng `stream:title:{conversation_id}`, dùng bốn event của §7.4 (`start` · `delta` · `done` · `error`); `done` mang tiêu đề cuối. Endpoint mới `GET /conversations/{id}/title/stream` dùng lại **đúng** consumer của §7.3 (XRANGE rồi XREAD, `Last-Event-ID`), lọc `user_id` trong SQL (IDOR ⇒ `404`). Nginx: location SSE phải phủ cả đường mới, với `proxy_buffering off` (C1).
- **Không ghi đè tay người:** `UPDATE conversations SET title = … WHERE id = … AND title IS NULL`. Người dùng đổi tên trước khi job xong thì tên của họ thắng.
- **Hỏng:** job lỗi ⇒ event `error`, tiêu đề vẫn `NULL`, sidebar hiện "Hội thoại chưa đặt tên" như hôm nay. Không thử lại vô hạn.
- **Trần tự nhiên:** không trừ quota không có nghĩa là không giới hạn — mỗi hội thoại một lượt, và hội thoại chỉ ra đời khi câu đầu đã qua cửa quota và rate limit.
- **Admin:** `/admin/usage` tách thêm theo `purpose`; màn Chi phí có khoản "Đặt tên". Biểu đồ giữ đúng hai chuỗi `metered` / `unmetered` — hệ thiết kế chỉ có hai màu biểu đồ.

#### S7 — Mở app là vào một hội thoại nháp

- Mở `/` hoặc bấm "Hội thoại mới" ⇒ màn **nháp**: chưa có bản ghi nào trong DB, nên không có hội thoại rỗng nào tích lại (NQ-111).
- Câu đầu gửi đi ⇒ FE gọi `POST /conversations` rồi `POST /conversations/{id}/messages`. **Hai khoá `Idempotency-Key` sinh cùng lúc khi lần soạn thảo bắt đầu** và giữ qua mọi lần thử lại (C22). Khoá Redis của §11.4 có chứa route nên hai khoá không đụng nhau; bước 1 xong mà bước 2 hỏng thì lần thử lại dùng lại hội thoại đã tạo chứ không tạo cái thứ hai.

#### S8 — Sidebar: nhóm theo ngày, mục ghim đầy đủ, tiêu đề chảy

- Nhóm theo **`updated_at`** — lần hoạt động gần nhất, đúng thứ tự `ORDER BY` và con trỏ phân trang hôm nay, nên không đổi backend — theo giờ máy người dùng: **Hôm nay** · **Hôm qua** · rồi ngày viết thẳng `d/m/yyyy`, mới nhất ở trên (NQ-112).
- Mục **Đã ghim** ở đầu và **đầy đủ**: `GET /conversations?pinned=true` trả mọi hội thoại ghim trong một lần (có trần ở `Settings`), `?pinned=false` là danh sách phân trang còn lại. Vì thế dòng "Ghim nổi lên đầu trong phần đã tải…" bỏ đi được mà không nói sai — đóng hẳn Cạm bẫy ① của T-3.3.
- Hàng hội thoại vừa tạo nghe `…/title/stream` và hiện tiêu đề chảy từng mảnh.

#### S9 — Ô nhập và màn chat v2

- **Màn nháp:** ô nhập nằm **giữa** màn hình. Gửi câu đầu ⇒ ô nhập trượt xuống đáy (token chuyển động của T-HD5-v2; `prefers-reduced-motion` ⇒ nhảy tức thì). Chỉ **khung** ô nhập di chuyển; không phần tử chứa chữ nào có hoạt ảnh (T-3.9 ①).
- **Ô nhập là một khối đứng riêng:** bỏ dải nền full-width có viền trên. Viền của chính ô nhập **hiện dần** khi focus, không bật tức thì.
- Bỏ dòng "Enter để gửi · Shift+Enter để xuống dòng". Bỏ bộ đếm `0/24000`: trần ký tự vẫn chặn gửi, nhưng chỉ khi **vượt** trần mới hiện một dòng báo. Model Picker chiếm chỗ bộ đếm cũ (dưới, bên phải), dạng chữ trơn không khung (NQ-115).
- **Quota rời màn chat sang Cài đặt** (S10). Màn chat chỉ còn: một **dòng cảnh báo nhỏ, một hàng**, trên ô nhập khi còn ≤ `quota_warn_remaining_pct`, có link sang Cài đặt; và khi hết quota, thông báo kèm **thời điểm hoàn lại chính xác** cùng nút Gửi bị khoá. UC-07 dòng 1–2 vẫn đạt; ngoại lệ BYOK của T-3.11 ① giữ nguyên (NQ-114).
- Bỏ dải trạng thái trên vùng chat (mã hội thoại · "đang nhận chữ" · `in=… out=…`). Chỉ giữ một thông báo khi **đang nối lại** kết nối.
- Mọi phần tử bấm được dùng con trỏ bàn tay; phần tử bị khoá dùng `not-allowed`. Luật sống ở `@layer base` của `theme.css`, không rải trong component.

#### S10 — Header, khối tài khoản, trang Cài đặt

- **Header** bỏ email và nút Đăng xuất. Còn lại: nút sidebar, tên app, lối vào `/admin` (chỉ admin), công tắc sáng/tối, và nút chờ "mở panel artifact" (S12).
- **Khối tài khoản ở chân sidebar:** avatar tròn · tên hiển thị · tier. Bấm vào mở menu, theo thứ tự: Cài đặt · Mức sử dụng · Ngôn ngữ *(chờ)* · Trợ giúp *(chờ)* · ── · Nâng cấp gói *(chờ)* · ── · Đăng xuất.
- **Tên hiển thị** là cột `users.display_name` đã có, không bắt duy nhất; để trống thì hiện **nguyên email**. **Avatar** là chữ cái đầu trên nền tròn, màu người dùng chọn từ bảng màu token của T-HD1-v2 — lưu **tên** màu, không lưu mã màu (A3). Tải ảnh lên là nút chờ cho tới khi có đường ống ảnh của P4 (T-4.1–T-4.3). **Tier** hiện theo nhãn trong `vi.json`; tier chưa có nhãn thì hiện nguyên tên (NQ-116).
- **Icon** dùng `morphicons` với dữ liệu icon của gói `lucide`. Icon biến hình ở mọi chỗ đổi trạng thái (Gửi ↔ Dừng, mở/đóng sidebar, Sáng ↔ Tối, mũi tên `›` của menu con) và khi hover trong menu tài khoản. Mọi icon đặt `reducedMotion="user"` — mặc định của thư viện là **bỏ qua** cài đặt giảm chuyển động của hệ điều hành, trái T-3.9. Thông số lò xo khai một chỗ, `lib/motion.ts` (NQ-117).
- **Trang Cài đặt chia tab**, mỗi tab một đường dẫn: Tài khoản (tên, avatar, Đăng xuất) · Giao diện · Model · Khoá API · Mức sử dụng. "Mức sử dụng" chứa hai thanh quota; thanh chạy từ 0 **chỉ lần đầu mở trong một lần đăng nhập** — so theo `last_login_at` của `/auth/me`, nên F5 hay mở tab mới không chạy lại, đăng nhập lại thì có (NQ-114).
- `PUT /settings` nở thêm `display_name`, `avatar_color`, `reasoning_prefs`. Nó vẫn là PUT **thay cả tài nguyên** (§18.4, T-3.0), nên FE luôn gửi đủ mọi trường.

#### S11 — Model Picker v2

Nút mở là tên model đang dùng, chữ trơn, không khung. Bảng chọn có bốn khối, ngăn bằng đường kẻ (NQ-120):

1. **Model hiện tại** — tên, provider hiển thị, badge, capability, và tầng mặc định đang áp dụng (hội thoại › tài khoản › catalog, T-3.6). Mọi mô tả của v1 giữ nguyên.
2. **Thinking Effort ›** — các mức của model, nhãn tiếng Anh; model không có thì hàng mờ kèm tooltip.
3. **More models ›** — danh sách đủ; model không khả dụng xám, không chọn được, kèm lý do; giờ `checked_at` và nút kiểm lại.
4. **Giá model hiện tại** — USD / 1M token vào và ra, khung giá đang áp dụng, và một dòng "suy luận được tính như token ra".

Dưới 640 px là sheet; hai mục `›` mở thành màn trượt có nút quay lại. Chỗ cho cảnh báo vision của T-4.5 vẫn giữ.

#### S12 — Nút chờ cho P4–P9

Một component duy nhất, `ComingSoon`: trông như nút thật ở trạng thái khoá, `aria-disabled="true"` (không `disabled`, để tooltip tới được người dùng bàn phím), con trỏ `not-allowed`, tooltip "Sắp có" **không** ghi phase, không một handler nào. Mỗi nút mang `data-planned="<ID task sẽ gắn nó>"` để agent của phase sau `grep` ra đúng chỗ. Thành phần phụ thuộc dữ liệu (chip nguồn web, thẻ artifact, ảnh trong bong bóng…) được **dựng sẵn và có test render**, nhưng chưa mount — chưa có dữ liệu nào để chúng hiện (NQ-121).

Bảng đầy đủ (vị trí → bản vẽ → task dựng → task sẽ gắn) ở `tasks.md` §7b.2. Panel artifact **không** vẽ ở đây: nó vẫn là T-HD6, làm sau T-5.4, vì nội dung iframe ở origin khác (ADR-10). Mic hiện ở mọi trình duyệt cho tới P8; T-8.4 ẩn nó trên Firefox theo ADR-13.

#### S13 — Luồng thiết kế v1 → v2 và hai task khép phase

- Người dùng vẽ tám bản: T-HD1-v2, T-HD2-v2, T-HD3-v2, T-HD4-v2, T-HD5-v2, T-HD7-v2, T-HD8, T-HD9. Prompt dán vào Claude Design nằm ở `docs/standardize-tutorial.md`.
- Phần backend của phase (T-S.0 … T-S.8) **không chờ bản vẽ nào**, nên chạy trong lúc người dùng vẽ. Mỗi task FE (T-S.9 … T-S.17) chờ đúng bản vẽ của vùng nó dựng.
- **Task cận cuối (T-S.18)** đọc lại toàn bộ bản v2 cạnh bản v1 tương ứng, đối chiếu với code, sửa chỗ lệch thuần trình bày, báo lại chỗ lệch hành vi, và chốt `design/README.md`.
- **Task cuối (T-S.19)** để trống có chủ ý: người dùng giao những gì còn sót khi tới nơi.

#### S14 — Những gì Phase S thêm vào hợp đồng chung

§7.4, §17, §18 và Phụ lục A/B không được sửa, nên bảng dưới đây **là** phần mở rộng của chúng. Dòng DoD chung "Endpoint mới đã thêm vào KE-HOACH §18" (`tasks.md` §15) được thoả, với task của Phase S, bằng một dòng trong bảng này (NQ-107).

| Loại | Thêm | Task |
|---|---|---|
| Endpoint | `GET /conversations/{id}/title/stream` — SSE, cùng định dạng §7.4 | T-S.7 |
| Endpoint | `GET /admin/models` — từng model kèm đường đi thật, health, `enabled`; chỉ admin | T-S.8 |
| Tham số | `GET /conversations?pinned=true\|false` | T-S.8 |
| Mở rộng | `GET /models`: `provider` = provider hiển thị; thêm `reasoning` (chỉ `id` + `default`), `pricing`, `pricing_mode`, `checked_at` | T-S.3, T-S.4 |
| Mở rộng | `POST /conversations/{id}/messages`, `POST /messages/{id}/retry`: `reasoning_effort` | T-S.6 |
| Mở rộng | `GET /auth/me` + `PUT /settings`: `display_name`, `avatar_color`, `reasoning_prefs` (+ `display_name_max_chars` ở `/auth/me`) | T-S.5 |
| Mở rộng | `/admin/usage`: tách theo `purpose` | T-S.8 |
| Mã lỗi | `400 REASONING_UNSUPPORTED` | T-S.5, T-S.6 |
| SSE | event `start` có thêm `reasoning_effort` | T-S.6 |
| Cột | `usage_events.purpose TEXT NOT NULL DEFAULT 'chat' CHECK (purpose IN ('chat','title'))` | T-S.7 |
| Cột | `messages.reasoning_effort TEXT` (nullable) | T-S.6 |
| Dữ liệu | `user_settings.prefs_json`: `reasoning` (model → mức), `avatar_color` | T-S.5 |
| Khoá Redis | `stream:title:{conversation_id}` *(tên cuối chốt ở T-S.7, sau khi kiểm mọi chỗ quét `stream:*`)* | T-S.7 |
| Catalog | `version: 4`; `providers[].user_visible`; `models[].display_provider`; `models[].reasoning`; `title_model` | T-S.3 |
| `.env` | TTL và trần chờ của lượt đo provider · trần danh sách ghim · trần độ dài tên hiển thị · trần đầu vào của lượt đặt tên | T-S.4, T-S.5, T-S.7, T-S.8 |
| Config | `config/prompts/title.jinja` | T-S.7 |
| Phụ thuộc FE | `lucide` (dữ liệu icon cho `morphicons`); `@radix-ui/react-dropdown-menu` nếu bản T-HD2-v2 cần | T-S.9, T-S.12 |

#### S15 — Ảnh hưởng tới phase sau

Không task nào của P4–P9 bị sửa (vùng cấm). Những gì Phase S để lại cho chúng:

| Phase | Điều Phase S để lại |
|---|---|
| P4 | Nút đính kèm và khay xem trước đã có chỗ (`data-planned="T-4.7"`); trạng thái không-vision của nút (T-4.5) đã vẽ. Tải avatar lên chờ đường ống ảnh của T-4.1–T-4.3 — **chưa task nào của P4 nhắc tới avatar** (B-265) |
| P5 | Thẻ artifact trong bong bóng và nút mở panel đã có chỗ; panel vẫn là T-HD6 |
| P6 | Công tắc Tìm web, chip "đang tìm web…", chip nguồn đã dựng. **Va chạm đã biết:** suy luận phải được gửi lại khi có tool call (S4) — trái B-33 (B-266) |
| P7 | Nút chọn skill trong ô nhập đã có chỗ |
| P8 | Chia sẻ, Xuất (menu hội thoại), mic, Đọc to đã có chỗ. T-8.4 phải **ẩn** mic trên Firefox — nút chờ của Phase S hiện ở mọi trình duyệt |
| P9 | Eval (T-9.1) chạy ở mức suy luận mặc định của từng model; mức khác là một cấu hình khác và có thể cần golden set riêng |

### 24.3 DoD của từng phase

| Phase | Xong khi |
|---|---|
| P0 | `docker compose ps` tất cả healthy · `curl -k https://localhost/health/deep` trả ok cho cả 5 phụ thuộc · `docker compose exec litellm curl -s http://host.docker.internal:20128/v1/models` ra JSON · xoá 1 biến `.env` → không boot, in đúng tên biến (S1) |
| P1 | `scripts/test_resume.py` xanh (S3) · kill worker giữa chừng → message không kẹt quá 120 s (S4) · tạo 3 nhánh, kiểm context gửi lên chỉ chứa đường đi hiện tại (C11) · TTFT p95 đạt S2 |
| P2 | Đăng ký → verify (Mailpit) → duyệt → chat được, toàn bộ bằng UI · double-click tạo đúng 1 message (S5) · quota = 0 → chặn trước khi gọi model, 0 USD phát sinh (S6) · logout → token cũ trả 401 (C21) · user A không đọc được hội thoại của B (404) |
| P3 | Lighthouse mobile đạt S8 · thêm model vào catalog hiện trong picker ≤ 5 phút không sửa code (S7) · dùng được ở 375 px · sáng/tối không có chỗ nào chữ chìm vào nền |
| PS | `scripts/check_identifiers.py` 0 phát hiện · mở app không tạo hội thoại nào cho tới khi gửi câu đầu · tiêu đề chảy trong sidebar qua Nginx (`curl -N`), lượt đặt tên có đúng 1 dòng `usage_events` `purpose='title'` và không trừ quota, kể cả sau `rebuild_quota` · `GET /models` < 0.3 s kể cả khi 9Router im lặng, và không chứa tên đường trung gian nào · mọi mức suy luận trong catalog đã được đo (T-S.2) và được ghi vào `messages.reasoning_effort` · mọi nút chờ có `data-planned` khớp bảng `tasks.md` §7b.2 · `make audit` và 375 px đạt trên mọi đường, gồm năm tab `/cai-dat/*` |
| P4 | Model không vision → nút upload mờ + icon cấm khi hover; bypass API → 422 (S9) · gửi ảnh lượt 1, `prompt_tokens` lượt 3 không tăng theo số ảnh (C33) |
| P5 | Artifact HTML gọi `/api/v1/*` → thất bại (S12) · chuyển qua lại giữa các phiên bản · panel chiếm toàn màn hình trên mobile |
| P6 | `pytest tests/tools/test_ssrf.py` ≥ 25 case xanh (S10) · Tavily tắt → chat vẫn chạy · trang JS-heavy tự leo thang Playwright · 50 fetch liên tiếp, RAM trở về mức nền (C24) |
| P7 | Sandbox không ra mạng được, `while True` bị kill (S11) · `os.environ` trong sandbox không thấy secret của Scarlet (C27) · bật 10 skill làm `prompt_tokens` tăng < 500 (C30) |
| P8 | Export `.md` mở bằng trình đọc markdown ra đúng cấu trúc hội thoại; export `.json` nạp lại được bằng script kiểm tra · Link share hiện đúng snapshot, không lộ tin nhắn sau đó · fork tạo hội thoại mới của người fork · Firefox không hiện nút voice (không phải nút chết) |
| P9 | Xoá volume → khôi phục từ backup → đăng nhập được, hội thoại cũ nguyên vẹn · eval xanh cho mọi model `enabled: true` |

### 24.4 Mức chi tiết trong `tasks.md`

Theo §4.4 của META: **P0–P2 đủ 7 trường** · **P3–P5 dạng bảng** · **P6–P9 gạch đầu dòng**. Viết chi tiết cả 9 phase là lãng phí, vì sau P2 bạn sẽ biết những điều hôm nay chưa biết. Có prompt §7.4 để mở rộng khi tới nơi.

---

## 25. Rủi ro

| # | Rủi ro | Mức | Ứng phó (hành động cụ thể) |
|---|---|---|---|
| **RR-1** | **Đăng ký mở → người lạ tiêu tiền của bạn** | **Cao** | Bốn lớp: `REGISTRATION_MODE=approval` mặc định (R5) · verify email · Turnstile · quota chặn trước khi gọi (§10.2). Thêm: cảnh báo qua email khi chi tiêu ngày vượt `DAILY_ALERT_USD`. Nhắc lại trong task P2 |
| **RR-2** | **Thoát sandbox khi chạy skill** | **Cao** | ADR-09 + `can_execute_skills` mặc định tắt (§13.4) + tiêu chí S11. Nếu sau này mở đăng ký rộng hơn: chuyển sang gVisor (đã ghi Backlog). **Chấp nhận:** đây là rủi ro cố hữu của mức (b), không thể về 0 |
| **RR-3** | **SSRF qua tính năng fetch link** | **Cao** | Bốn lớp §12.2, quan trọng nhất là lớp 1 (cách ly network) vì nó vẫn giữ khi code có bug. Tiêu chí S10 với ≥ 25 case gồm DNS rebinding |
| **RR-4** | **Stream resume viết sai, phát hiện muộn** | **Cao** | Test tự động S3 ngay từ P1, không nghiệm thu bằng mắt. Task P1 đánh dấu **không được gộp** |
| **RR-5** | **9Router tắt/đổi hành vi → một phần model chết** | Trung bình | `availability: host-dependent` + health check + hiện xám trong picker (UC-05). Chat vẫn chạy với model khác. **Chấp nhận:** đây là đánh đổi của việc dùng gateway ngoài Docker |
| **RR-6** | **Chi phí không khớp thực tế do 9Router fallback** | Trung bình | §9.5: `cost_confidence`, hai cột tách riêng trong admin panel, S13 chỉ áp cho model `metered` |
| **RR-7** | **Redis mất dữ liệu → quota reset, stream đang chạy mất** | Trung bình | `appendonly yes` · `rebuild_quota(user_id)` từ Postgres có test · stream đang chạy thì mất (chấp nhận được, hiếm) · healthcheck + restart policy |
| **RR-8** | **Mailpit không gửi thư thật → không ai verify được email** | **Cao khi mời người thật** | Q-02 chặn task P2.7. Cho tới khi có SMTP thật, dùng `REGISTRATION_MODE=invite` và admin verify tay |
| **RR-9** | **Phạm vi v1 lớn (9–10 subsystem), mất động lực giữa chừng** | Trung bình | Mỗi phase giao được giá trị dùng ngay (§24.1). Bạn tự dùng được từ cuối P1. Nếu chán, dừng ở P4 vẫn có một app hoàn chỉnh |
| **RR-10** | **Prompt injection từ web/file khiến model gọi tool có hại** | Trung bình | Bọc `<untrusted_content>` + tool có tác dụng phụ phải có quyền riêng + không tool nào tự gọi tool khác mà không qua model. **Chấp nhận:** không có giải pháp triệt để hiện nay |
| **RR-11** | **Artifact render live bị dùng để XSS** | Trung bình | Ba lớp §14.3, tiêu chí S12. Lỗi hay gặp nhất là `allow-same-origin` — đã ghi cảnh báo tại chỗ |
| **RR-12** | **Agent tự "đơn giản hoá" §7 hoặc §8 khi gặp khó** | Trung bình | A1, A2, A10 trong `CLAUDE.md` · task P1 đánh dấu không được gộp · review bằng lệnh grep §19.4 |
| **RR-13** | **Chỉ có một người vận hành — bận/ốm thì không ai duyệt user, không ai xem chi phí** | Thấp | Email cảnh báo tự động khi vượt ngưỡng chi tiêu; quota là hàng rào tự động không cần người |
| **RR-14** | **Dữ liệu hội thoại của 20 người nằm trên một máy cá nhân** | Trung bình | Backup + diễn tập khôi phục (§22.7) · nói rõ với người dùng (§20) · mã hoá đĩa nếu là laptop |

---

## 26. Câu hỏi cần bạn quyết

Theo N9 của META — những gì tôi **không** quyết thay bạn được. Mỗi câu ghi rõ chặn task nào.

| # | Câu hỏi | Chặn | Nếu không trả lời, tôi sẽ mặc định |
|---|---|---|---|
| **Q-01** | 9Router chạy trên **Windows host** hay **trong WSL2**? Có bật xác thực (API key) không? | P0.4 (đường mạng), P0.6 (litellm config) | `host.docker.internal` + không cần key. Nếu sai thì P0 sẽ đỏ ngay, phát hiện sớm — chấp nhận được |
| **Q-02** ⚠️ | **SMTP thật** sẽ dùng gì khi mời người thật vào? (Resend / Brevo / SendGrid / Gmail SMTP) | P2.7 (verify email), P2.8 (quên mật khẩu) | Mailpit cho tới hết P2; **không mời ai vào cho tới khi có SMTP thật** (RR-8) |
| **Q-03** | Hạn mức mặc định là bao nhiêu USD cho **5 giờ** và cho **7 ngày**? | P2.11 (seed bảng `tiers`) | `limit_5h_usd = 0.50`, `limit_7d_usd = 3.00` — đủ cho ~150 tin nhắn model rẻ. Dễ đổi sau bằng admin panel |
| **Q-04** | Model **mặc định** cho user mới là model nào? Model nào được bật cho tier thấp nhất? | P0.7 (catalog đầu tiên), P3.5 (model picker) | Model rẻ nhất có `tools` làm mặc định |
| **Q-05** | Chi tiêu **một tháng** vượt bao nhiêu USD thì bạn muốn nhận email cảnh báo? | P2.14 (job cảnh báo) | `DAILY_ALERT_USD = 2.00`, `MONTHLY_BUDGET_USD = 30.00` |
| **Q-06** | Skill nào bạn muốn có sẵn ở P7? (bộ Anthropic `docx`/`xlsx`/`pptx`/`pdf`, hay skill tự viết?) | P7.1 (danh sách `sandbox/requirements.txt`) | Bộ Anthropic bốn cái trên |
| **Q-07** | Người dùng được **tự xoá tài khoản** không? Xoá thì dữ liệu purge sau bao lâu? | P2.16, §20 | Có, purge sau 30 ngày |
| **Q-08** | Hội thoại có **tự hết hạn** không (ví dụ xoá sau 1 năm không đụng tới)? | Schema `conversations`, job dọn | Không tự xoá. Chỉ dọn `raw_response` sau 30 ngày |
| **Q-09** | Bạn có muốn giữ **LangChain** không, sau khi đọc ADR-04? | P1.3 (tầng LLM client) | Bỏ LangChain, dùng `openai` SDK trỏ vào LiteLLM |
| **Q-10** | Bạn có đồng ý **FE gọi `GET /models`** thay vì đọc thẳng file catalog (ADR-12)? | P3.5 | Đi qua API |
| **Q-11** | Tên miền dự kiến là gì? (cần biết sớm để chuẩn bị `artifacts.<domain>`) | P9.3 | Dùng `localhost` + `artifacts.localhost` cho tới P9 |
| **Q-12** | ✅ **ĐÃ CHỐT: CÓ.** Export hội thoại JSON/Markdown vào v1 | P8.5–P8.6 | — (đã trả lời 2026-09-10) |

---

## Phụ lục A — DDL đầy đủ

> Dán vào `alembic/versions/0001_initial.py` (hoặc chạy trực tiếp để thử). Postgres 17.

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "citext";

-- ─────────────────────────── Người dùng & quyền ───────────────────────────
CREATE TYPE user_status AS ENUM
  ('pending_email','pending_approval','active','rejected','suspended');
CREATE TYPE user_role AS ENUM ('user','admin');

CREATE TABLE tiers (
    name                TEXT PRIMARY KEY,
    limit_5h_usd        NUMERIC(10,4) NOT NULL DEFAULT 0.50,
    limit_7d_usd        NUMERIC(10,4) NOT NULL DEFAULT 3.00,
    can_execute_skills  BOOLEAN NOT NULL DEFAULT FALSE,
    can_use_web         BOOLEAN NOT NULL DEFAULT TRUE,
    web_searches_per_day INT    NOT NULL DEFAULT 50,
    max_upload_mb       INT     NOT NULL DEFAULT 10,
    max_attachments     INT     NOT NULL DEFAULT 5,
    allowed_model_tags  TEXT[]  NOT NULL DEFAULT '{}',   -- rỗng = tất cả
    is_default          BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           CITEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT,
    status          user_status NOT NULL DEFAULT 'pending_email',
    role            user_role   NOT NULL DEFAULT 'user',
    tier_name       TEXT NOT NULL REFERENCES tiers(name) DEFAULT 'free',
    limit_override_json JSONB,          -- ghi đè từng trường của tier (§10.4)
    email_verified_at   TIMESTAMPTZ,
    approved_at         TIMESTAMPTZ,
    approved_by         UUID REFERENCES users(id),
    last_login_at       TIMESTAMPTZ,
    password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX ix_users_status ON users(status) WHERE deleted_at IS NULL;

CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id   UUID NOT NULL,                 -- xoay vòng: cùng family
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,                   -- dùng lại token đã used = bị đánh cắp
    revoked_at  TIMESTAMPTZ,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_refresh_family ON refresh_tokens(family_id);

CREATE TABLE email_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose     TEXT NOT NULL CHECK (purpose IN ('verify','reset')),
    token_hash  TEXT NOT NULL UNIQUE,          -- KHÔNG lưu bản rõ
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_provider_keys (             -- BYOK (§10.5)
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider     TEXT NOT NULL,                -- khớp key trong model_catalog.providers
    key_cipher   BYTEA NOT NULL,               -- AES-256-GCM
    key_nonce    BYTEA NOT NULL,
    key_last4    TEXT  NOT NULL,               -- chỉ để hiển thị
    verified_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider)
);

CREATE TABLE user_settings (
    user_id       UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    theme         TEXT NOT NULL DEFAULT 'system',
    default_model TEXT,
    prefs_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────── Hội thoại (CÂY) ───────────────────────────
CREATE TYPE message_role   AS ENUM ('system','user','assistant','tool');
CREATE TYPE message_status AS ENUM ('queued','streaming','completed','failed','cancelled');

CREATE TABLE conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title           TEXT,
    default_model   TEXT,
    system_prompt_override TEXT,
    active_leaf_id  UUID,                       -- §8, FK thêm sau khi có messages
    pinned          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX ix_conv_user ON conversations(user_id, updated_at DESC)
  WHERE deleted_at IS NULL;

CREATE TABLE messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    parent_id       UUID REFERENCES messages(id),   -- NULL = gốc nhánh (§8.2)
    role            message_role   NOT NULL,
    status          message_status NOT NULL DEFAULT 'completed',
    content         TEXT NOT NULL DEFAULT '',       -- ghi MỘT LẦN khi xong (§17.2)
    reasoning       TEXT,
    model_id        TEXT,
    tool_calls      JSONB,
    tool_call_id    TEXT,
    finish_reason   TEXT,
    error_code      TEXT,
    prompt_tokens     INT,
    completion_tokens INT,
    heartbeat_at    TIMESTAMPTZ,                    -- reaper (§7.6)
    raw_response    JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),  -- KHÔNG phải now(), §17.2
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX ix_msg_conv_parent ON messages(conversation_id, parent_id);
CREATE INDEX ix_msg_parent      ON messages(parent_id);
CREATE INDEX ix_msg_streaming   ON messages(heartbeat_at)
  WHERE status = 'streaming';                       -- partial index cho reaper

ALTER TABLE conversations
  ADD CONSTRAINT fk_active_leaf FOREIGN KEY (active_leaf_id)
  REFERENCES messages(id) ON DELETE SET NULL;

-- ─────────────────────────── File & artifact ───────────────────────────
CREATE TABLE attachments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id      UUID REFERENCES messages(id) ON DELETE SET NULL,
    kind            TEXT NOT NULL,               -- image | pdf | doc | sheet | other
    mime_type       TEXT NOT NULL,
    original_name   TEXT NOT NULL,
    size_bytes      BIGINT NOT NULL,
    storage_key     TEXT NOT NULL,               -- key trong MinIO
    width           INT,
    height          INT,
    extracted_text  TEXT,                        -- cache (§17.2)
    extract_status  TEXT NOT NULL DEFAULT 'none',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_att_user ON attachments(user_id, created_at DESC);

CREATE TABLE artifacts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id          UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    parent_artifact_id  UUID REFERENCES artifacts(id),
    version             INT  NOT NULL DEFAULT 1,
    kind                TEXT NOT NULL,           -- html | react | svg | mermaid | code | markdown | file
    language            TEXT,
    title               TEXT NOT NULL,
    content             TEXT,                    -- nội dung text
    storage_key         TEXT,                    -- hoặc file trong MinIO
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_art_msg ON artifacts(message_id);

-- ─────────────────────────── Chi phí & quota ───────────────────────────
CREATE TABLE usage_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id        UUID REFERENCES messages(id) ON DELETE SET NULL,
    model_id          TEXT NOT NULL,
    provider          TEXT NOT NULL,
    key_source        TEXT NOT NULL CHECK (key_source IN ('system','byok')),
    prompt_tokens     INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    cached_tokens     INT NOT NULL DEFAULT 0,
    cost_usd          NUMERIC(12,6) NOT NULL DEFAULT 0,
    cost_confidence   TEXT NOT NULL DEFAULT 'exact'
                      CHECK (cost_confidence IN ('exact','low')),   -- §9.5
    price_snapshot    JSONB NOT NULL,                               -- A7
    upstream_model_reported TEXT,                                   -- §9.5
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_usage_user_time ON usage_events(user_id, created_at DESC);
CREATE INDEX ix_usage_time      ON usage_events(created_at DESC);

-- ─────────────────────────── Share, skill, vận hành ───────────────────────
CREATE TABLE shared_conversations (
    token           TEXT PRIMARY KEY,            -- ngẫu nhiên ≥ 128 bit, url-safe
    owner_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    snapshot_json   JSONB NOT NULL,              -- ADR-14: bất biến
    view_count      INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ                  -- v1 không dùng, giữ chỗ (§16.1)
);

CREATE TABLE skills (
    name        TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    path        TEXT NOT NULL,
    requires_execution BOOLEAN NOT NULL DEFAULT FALSE,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_skills (
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL REFERENCES skills(name) ON DELETE CASCADE,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (user_id, skill_name)
);

CREATE TABLE feature_flags (
    key         TEXT PRIMARY KEY,
    enabled     BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    actor_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    target_type TEXT,
    target_id   TEXT,
    details     JSONB,
    ip          INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_time ON audit_logs(created_at DESC);

-- ─────────────────────────── Seed tối thiểu ───────────────────────────
INSERT INTO tiers (name, limit_5h_usd, limit_7d_usd, can_execute_skills, is_default)
VALUES ('free', 0.50, 3.00, FALSE, TRUE),
       ('trusted', 2.00, 12.00, TRUE, FALSE);
```

---

## Phụ lục B — `.env.example`

```bash
# ═══ BẮT BUỘC — thiếu bất kỳ dòng nào, app KHÔNG boot (S1) ═══
DATABASE_URL=postgresql+asyncpg://scarlet:CHANGE_ME@postgres:5432/scarlet
REDIS_URL=redis://redis:6379/0
JWT_SECRET=                       # openssl rand -hex 32
MASTER_ENCRYPTION_KEY=            # openssl rand -hex 32  — mã hoá BYOK
LITELLM_MASTER_KEY=               # cũng đặt trong litellm.config.yaml
LITELLM_BASE_URL=http://litellm:4000/v1
PUBLIC_BASE_URL=https://localhost
ARTIFACTS_BASE_URL=https://artifacts.localhost

MINIO_ENDPOINT=http://minio:9000
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
MINIO_BUCKET=scarlet

# ═══ Provider keys (dùng bởi LiteLLM, không phải bởi app) ═══
DEEPSEEK_API_KEY=
ANTHROPIC_API_KEY=
NINEROUTER_BASE_URL=http://host.docker.internal:20128/v1
NINEROUTER_API_KEY=               # để rỗng nếu 9Router không yêu cầu

# ═══ Email ═══
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_USER=
SMTP_PASSWORD=
SMTP_TLS=false
MAIL_FROM=Scarlet <no-reply@scarlet.local>

# ═══ Đăng ký & bảo mật ═══
REGISTRATION_MODE=approval        # open | approval | invite
TURNSTILE_SITE_KEY=
TURNSTILE_SECRET=                 # rỗng = bỏ qua (chỉ dev), log cảnh báo mỗi lần boot
EMAIL_TOKEN_TTL_MIN=60
ACCESS_TOKEN_TTL_MIN=15
REFRESH_TOKEN_TTL_DAYS=30
ARGON2_TIME_COST=3
ARGON2_MEMORY_KIB=65536

# ═══ Streaming (§7) ═══
STREAM_TTL_S=3600
STREAM_HEARTBEAT_S=15
WORKER_HEARTBEAT_S=15
REAPER_STALE_S=90
MAX_CONCURRENT_STREAMS=3

# ═══ Quota (§10) ═══
QUOTA_WINDOW_SHORT_S=18000        # 5 giờ
QUOTA_WINDOW_LONG_S=604800        # 7 ngày
DAILY_ALERT_USD=2.00
MONTHLY_BUDGET_USD=30.00

# ═══ Context & vision (§9.6, §15.3) ═══
CONTEXT_WINDOW_CAP=128000
RESERVE_TOKENS=1000
VISION_MAX_EDGE_PX=1568
VISION_MAX_BYTES=3500000
MAX_PDF_PAGES_VISION=10
RESEND_IMAGES_IN_HISTORY=false    # C33 — bật lên là hoá đơn tăng vọt

# ═══ Web tools (§12) ═══
TAVILY_API_KEY=
FETCHER_BASE_URL=http://fetcher:8080
MAX_FETCH_MB=5
MAX_REDIRECTS=5
JS_ESCALATE_MIN_CHARS=200
FETCH_TIMEOUT_S=10
PLAYWRIGHT_TIMEOUT_S=20

# ═══ Sandbox (§13) ═══
SANDBOX_BASE_URL=http://sandbox:8090
SANDBOX_TIMEOUT_S=30
MAX_SKILL_OUTPUT_MB=20

# ═══ Upload (§15.2) ═══
ALLOWED_UPLOAD_MIME=image/png,image/jpeg,image/webp,image/gif,application/pdf,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document
PRESIGN_TTL_S=300

# ═══ Vận hành ═══
LOG_LEVEL=INFO
DEBUG=false                       # true mới bật /_debug/*
RAW_RESPONSE_KEEP_DAYS=30
PURGE_AFTER_DAYS=30
```

---

## Phụ lục C — `docker-compose.yml` (rút gọn, phần cốt lõi)

```yaml
x-common: &common
  restart: unless-stopped
  env_file: [.env]
  networks: [internal]

services:
  nginx:
    <<: *common
    image: nginx:1.27-alpine
    ports: ["443:443", "80:80"]
    volumes:
      - ./config/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on: { api: { condition: service_healthy } }
    profiles: [core]

  api:
    <<: *common
    build: ./backend
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
      interval: 10s
      timeout: 3s
      retries: 5
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
      migrate:  { condition: service_completed_successfully }
    profiles: [core]

  worker:
    <<: *common
    build: ./backend
    command: arq app.workers.main.WorkerSettings
    depends_on:
      redis:   { condition: service_healthy }
      migrate: { condition: service_completed_successfully }
    profiles: [core]

  migrate:                       # §22.2 — chạy một lần rồi thoát
    <<: *common
    build: ./backend
    command: alembic upgrade head
    restart: "no"
    depends_on: { postgres: { condition: service_healthy } }
    profiles: [core]

  litellm:
    <<: *common
    image: ghcr.io/berriai/litellm:main-latest
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    volumes: ["./config/litellm.config.yaml:/app/config.yaml:ro"]
    extra_hosts: ["host.docker.internal:host-gateway"]   # ← C17
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:4000/health/liveliness"]
      interval: 15s
      retries: 5
    profiles: [core]

  postgres:
    <<: *common
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: scarlet
      POSTGRES_USER: scarlet
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U scarlet"]
      interval: 10s
      retries: 5
    profiles: [core]

  redis:
    <<: *common
    image: redis:7-alpine
    command: >
      redis-server --appendonly yes
      --maxmemory 512mb --maxmemory-policy volatile-lru
    volumes: ["redisdata:/data"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      retries: 5
    profiles: [core]

  minio:
    <<: *common
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    volumes: ["miniodata:/data"]
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 15s
      retries: 5
    profiles: [core]

  # ─────── network riêng, KHÔNG join internal (§12.2 lớp 1) ───────
  fetcher:
    build: ./fetcher
    restart: unless-stopped
    networks: [egress]
    mem_limit: 1g
    profiles: [tools]

  sandbox:
    build: ./sandbox
    restart: unless-stopped
    network_mode: "none"          # ← ADR-09
    read_only: true
    tmpfs: ["/work:size=256m,mode=1777"]
    mem_limit: 512m
    pids_limit: 128
    cpus: 1.0
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    user: "65534:65534"
    # KHÔNG có env_file — C27
    profiles: [tools]

  mailpit:
    image: axllent/mailpit:latest
    ports: ["8025:8025"]
    networks: [internal]
    profiles: [dev]

networks:
  internal: {}
  egress: {}

volumes: { pgdata: {}, redisdata: {}, miniodata: {} }
```

> ⚠️ `fetcher` và `sandbox` **không** join network `internal`. Đó là toàn bộ lớp phòng thủ số 1 của §12.2 và ADR-09. Nếu một task nào đó "sửa cho tiện" bằng cách thêm chúng vào `internal`, cả hai subsystem bảo mật sụp cùng lúc. Ghi rõ trong `CLAUDE.md`.
>
> `sandbox` với `network_mode: none` không gọi được từ `worker` qua HTTP. Có hai cách: (a) sandbox nghe trên Unix socket được mount, (b) worker gọi qua một shim nhỏ ở network riêng. **Chốt cách (a)** — đơn giản hơn và không mở cổng nào. Task P7.3 phải xử lý đúng điểm này; đây là chỗ dễ vô tình phá vỡ cách ly nhất.

---

## Phụ lục D — `nginx.conf` (phần cốt lõi)

```nginx
map $http_upgrade $connection_upgrade { default upgrade; '' close; }
limit_req_zone $binary_remote_addr zone=general:10m rate=30r/s;

server {
    listen 443 ssl;
    http2 on;
    server_name localhost;

    ssl_certificate     /etc/nginx/certs/localhost.pem;
    ssl_certificate_key /etc/nginx/certs/localhost-key.pem;

    client_max_body_size 25m;              # khớp tiers.max_upload_mb + đệm

    # ─── SSE: ba dòng dưới đây là sống còn (C1, C2) ───
    location ~ ^/api/v1/(messages/[^/]+/stream|_debug/sse)$ {
        proxy_pass http://api:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;               # C1
        proxy_cache off;
        proxy_read_timeout 3600s;          # C2
        chunked_transfer_encoding on;
        proxy_set_header X-Request-Id $request_id;
    }

    location /api/ {
        limit_req zone=general burst=60 nodelay;
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Request-Id $request_id;
    }

    location / {
        proxy_pass http://web:5173;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
    }
}

# ─── ORIGIN PHỤ cho artifact (ADR-10) ───
server {
    listen 443 ssl;
    http2 on;
    server_name artifacts.localhost;

    ssl_certificate     /etc/nginx/certs/localhost.pem;
    ssl_certificate_key /etc/nginx/certs/localhost-key.pem;

    add_header Content-Security-Policy
      "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; style-src 'unsafe-inline' https://cdn.jsdelivr.net; img-src data: https:; font-src data: https:; connect-src 'none'; frame-ancestors https://localhost" always;
    add_header X-Content-Type-Options nosniff always;

    location / { proxy_pass http://api:8000/artifacts-render/; }
}
```

---

## Phụ lục E — `litellm.config.yaml`

```yaml
model_list:
  - model_name: deepseek-chat
    litellm_params:
      model: deepseek/deepseek-chat
      api_key: os.environ/DEEPSEEK_API_KEY

  - model_name: claude-sonnet
    litellm_params:
      model: anthropic/claude-sonnet-4-5
      api_key: os.environ/ANTHROPIC_API_KEY

  # 9Router — OpenAI-compatible, chạy NGOÀI Docker (§9.5, C17)
  - model_name: nr-auto
    litellm_params:
      model: openai/auto
      api_base: os.environ/NINEROUTER_BASE_URL
      api_key: os.environ/NINEROUTER_API_KEY

litellm_settings:
  drop_params: true          # bỏ tham số provider không hỗ trợ thay vì lỗi 400
  request_timeout: 600
  num_retries: 2

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

---

## Phụ lục F — Hợp đồng SSE (dán cho FE)

```typescript
type StreamEvent =
  | { event: 'start';       data: { message_id: string; model_id: string } }
  | { event: 'delta';       data: { t: string } }
  | { event: 'reasoning';   data: { t: string } }
  | { event: 'tool_call';   data: { call_id: string; name: string; args: unknown } }
  | { event: 'tool_result'; data: { call_id: string; ok: boolean; summary: string } }
  | { event: 'artifact';    data: { artifact_id: string; kind: string; version: number } }
  | { event: 'usage';       data: { in: number; out: number; cost_usd: number } }
  | { event: 'done';        data: { finish_reason: string; usage: Usage } }
  | { event: 'error';       data: { code: string; message: string } };

// Client: EventSource TỰ gửi Last-Event-ID khi reconnect vì mỗi event có id:
const es = new EventSource(`/api/v1/messages/${id}/stream`, { withCredentials: true });

// Chỉ 'done' hoặc 'error' mới kết thúc. Im lặng = đang chờ (§7.4)
es.addEventListener('done',  () => es.close());
es.addEventListener('error', () => { /* KHÔNG đóng — để trình duyệt tự reconnect */ });

// C6 — mobile: khoá màn hình làm đứt kết nối lặng lẽ
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && streaming) reconnect();
});
```

---

## Phụ lục G — Nội dung `CLAUDE.md` (gốc repo)

> Đây là bản nháp. Bản chính thức viết ở GĐ4 cùng `HUONG-DAN-AGENT.md`.

```markdown
# Scarlet — luật cho agent

## Môi trường
- Repo PHẢI nằm trong WSL filesystem (`/home/...`), KHÔNG phải `/mnt/c/...` (C35)
- Python chạy trong `.venv` của backend: `cd backend && source .venv/bin/activate`
- Tạo venv: `python -m venv .venv && pip install -e ".[dev]"`
- KHÔNG cài package vào Python hệ thống. KHÔNG dùng conda.
- Frontend: `pnpm`, không `npm`/`yarn`

## Mười luật kiến trúc (§0 của docs/KE-HOACH.md)
A1  Generation KHÔNG chạy trong HTTP handler. Handler tạo record + enqueue.
A2  Message là CÂY. Không có query "tất cả message theo thời gian".
A3  Không literal: tên model, giá, giới hạn, URL provider trong .py/.tsx.
A4  Thiếu biến .env bắt buộc → app KHÔNG boot, in đúng tên biến.
A5  Mọi URL của user đi qua app/tools/ssrf.py::validate_url(). Kể cả redirect.
A6  Backend KHÔNG tự chạy code. Luôn gửi sang service sandbox.
A7  Chi phí snapshot vào usage_events lúc gọi. Đổi giá không sửa lịch sử.
A8  POST tạo tài nguyên đọc header Idempotency-Key.
A9  Backend chỉ nói OpenAI Chat Completions streaming. Không rò khác biệt provider.
A10 KHÔNG tự "đơn giản hoá" kiến trúc. Thấy thừa → ghi Backlog và HỎI.

## Không bao giờ
- Thêm `fetcher` hoặc `sandbox` vào network `internal` (phá vỡ §12.2 và ADR-09)
- Dùng `sandbox="allow-scripts allow-same-origin"` cho iframe artifact (§14.3)
- Bỏ `proxy_buffering off` khỏi location SSE (C1)
- Commit `.env`, chứng chỉ, hay bất cứ chuỗi nào khớp `sk-[A-Za-z0-9]{20,}`

## Trước khi báo xong task
make test && make check-hardcode && docker compose ps
```

---

## Phụ lục H — Bản ghi thay đổi so với yêu cầu ban đầu

Theo N3 của META, những chỗ kế hoạch **không** chép lại nguyên yêu cầu:

| Yêu cầu ban đầu | Trạng thái | Ở đâu | Lý do |
|---|---|---|---|
| "LangChain chuẩn hoá định dạng trả về của LLM" | ⚠️ **nên sửa** → bỏ LangChain | ADR-04, Q-09 | Sau khi có LiteLLM, LangChain thành tầng abstraction thứ hai cho cùng một việc |
| "Frontend sẽ đọc file model catalog" | ⚠️ **nên sửa** → qua `GET /models` | ADR-12, §9.3, Q-10 | File tĩnh không lọc được theo quyền, lộ base_url và giá, không biết 9Router đang tắt |
| "OCR" | ⚠️ **đã bỏ** → vision model | ADR-11 | Bạn đã đồng ý ở GĐ1. Tiết kiệm ~4 GB image và một worker |
| "Playwright tự đăng nhập" | ⛔ **chuyển Backlog** | §2.2, §12 | Lưu mật khẩu bên thứ ba; captcha/2FA khiến tỉ lệ hỏng cao |
| "Đăng ký mở" | ⚠️ **đã sửa** → mở + admin duyệt | §11.1, RR-1 | Đăng ký mở + bạn trả token = ai cũng tiêu được tiền của bạn |
| "Skills mức (b)" | ✅ **giữ**, nhưng chia hai bước + quyền riêng | §13.1, §13.4 | Giữ nguyên phạm vi, giảm rủi ro và cho ra tính năng dùng được sớm hơn |
| "Thành công = không có bug" | ⚠️ **đã sửa** → 14 tiêu chí có số | §2.3 | Tiêu chí không đo được là tiêu chí không bao giờ đạt |
| *(thiếu sót do tôi bỏ quên)* Mở rộng sang **provider khác có endpoint tuỳ chỉnh** | ➕ **đã bổ sung** | R22, §9.8–9.10, S15, T-0.12 | Kiến trúc vốn đã chịu được, nhưng không có yêu cầu và không có tiêu chí nghiệm thu nào bảo vệ nó. Không đo thì vài phase sau sẽ có ai đó hardcode và không ai biết |
| "Nginx, JWT, rate limit, blacklist, idempotency, Redis, Postgres, MinIO, FastAPI, SSE, React, Tailwind, Docker, alembic, workers, BYOK, model picker, .env đa provider, vision toggle, Copy/Like/Dislike/Retry, chạy ngầm khi chuyển tab, MCP/RAG để mở rộng" | ✅ **giữ nguyên toàn bộ** | khắp file | Đúng hướng, không có gì cần sửa |

---

*Hết `KE-HOACH.md` v1.0. Bước tiếp theo theo META §6: bạn phản biện và yêu cầu sửa, sau đó mới sang GĐ3 viết `tasks.md`.*
