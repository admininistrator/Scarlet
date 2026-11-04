# Chuẩn bị Phase 10 — tổng hợp ý tưởng cải thiện

> File gom **ý tưởng** cho Phase 10. Chưa phải task: mỗi mục ghi vấn đề, hướng làm, ràng buộc
> đã biết. Lúc mở Phase 10 mới tách thành task trong `tasks.md` (kèm DoD, ước lượng).

---

## 0. Ý tưởng thô: chưa có kế hoạch rõ ràng

- Ở bước đăng ký, khi người dùng nhập tài khoản hay mật khẩu chưa thoả mãn yêu cầu tối thiểu, phải nói rõ yêu cầu của tài khoản, mật khẩu. Không để trừu tượng như 'Mật khẩu quá ngắn. Hãy chọn một mật khẩu dài hơn.'
- Thêm một bộ đếm thời gian ở UI, khi user gửi prompt đến khi model trả kết quả xong, có cả thời gian suy luận
- Khi search web xong, những trang web nào đọc bị lỗi với báo lỗi dạng: 'Không đọc được loại nội dung này', 'Công cụ gặp lỗi', ... thì không phải hiển thị lên UI
- Ở câu trả lời của Scarlet trên UI, thay vì hiển thị toàn bộ các website mà agent đã đọc, hãy đưa chúng vào ...
- Sử dụng latex để biểu diễn những phép toán, khi render câu trả lời, những phép toán/biểu thức vẫn chưa được render đúng cách
- Triển khai tính năng mới: gửi prompt đến một loạt model - user có thể chọn nhiều model trong một phiên, khi bấm nút gửi thì prompt sẽ được gửi đồng thời đến các model đã chọn, trên màn hình sẽ chia ra thành các ô song song dọc. Sau đó người dùng có thể lựa chọn 1 model tổng kết (hoặc user cũng có thể tự chọn/không chọn-nhận cả 3 kết quả), đánh giá các kết quả và đưa ra phương án duy nhất cuối cùng. LƯU Ý QUAN TRỌNG: prompt được gửi độc lập đến các model được chọn, model này không biết hoạt động của model còn lại ...
---

## 1. Web search: cải thiện search hiện tại + thêm jev làm tool thứ 3

**Đã chốt (2026-10-29):** giữ Tavily, cải thiện tầng search hiện có (§1.2); thêm
[jev-ultrafast](https://github.com/browser-use/jev-ultrafast) làm **tool thứ 3** để thao tác
trên trang, không thay `web_search` (§1.3). **Không** dùng Playwright MCP (§1.4).

**Cập nhật (2026-11-03):** §1.2 viết lại thành search **hybrid** — Tavily + DeepSeek Search
(ra mắt 2026-10-21) + SearXNG tự host + Firecrawl free làm nguồn cuối, sau một
`HybridSearch`. Crawl4AI xét và **loại** (§1.2.5). Thay mục "Brave / Exa / Serper" cũ.

### 1.1 Hiện trạng (sau P6)

| Thành phần | Đang làm gì |
|---|---|
| `backend/app/tools/web_search.py` | `TavilySearch` gọi `POST /search`, chỉ gửi `query` + `max_results` (mặc định 5), trần 10 s. Trả `title · url · content` — **chỉ đoạn trích**. Hỏng ⇒ `SearchResult(error=<mã cố định>)`, chat không chết. Có interface `SearchProvider` |
| `backend/app/tools/fetch_url.py` + `fetcher/server.py` | httpx → leo thang Playwright khi trang JS-heavy (§12.3). SSRF bốn lớp; Playwright bị khoá: **mọi** request con qua `context.route` → GET bằng đường đã kiểm → `route.fulfill`; thứ lọt ra vào proxy chết; rào `iptables`. Mạng `egress` |
| `backend/app/tools/registry.py` | `ToolProvider` (chỗ cắm sẵn cho MCP, §13.5); `MAX_TOOL_CALLS_PER_TURN=5`; kết quả bọc `untrusted_block`. `web_search` kiểm quota (`quota/web_searches.py`, 24 h trượt) **trước** khi gọi `search_provider` |

Điểm yếu thấy được: model chỉ nhận đoạn trích, muốn đọc kỹ phải gọi thêm `fetch_url` (tốn lượt
trong 5 lời gọi); Tavily hỏng / hết quota là mất hẳn search; không làm được trang cần thao tác
(lọc, phân trang, form tra cứu).

### 1.2 A — Search hybrid (`HybridSearch`)

Mục tiêu: `web_search` không phụ thuộc một nguồn; nhận được chữ trang chứ không chỉ đoạn trích;
đổi thứ tự / bật tắt nguồn bằng `Settings`, không sửa code. `registry._web_search` và quota
không đổi chỗ gọi — `search_provider` (biến module trong `registry.py`) trỏ sang `HybridSearch`,
bản thân nó cũng là một `SearchProvider`.

#### 1.2.1 Vai trò từng nguồn

| Nguồn | Vai trò | Ghi chú |
|---|---|---|
| **Tavily** | Nguồn tìm (giữ) | Thêm tham số ở §1.2.4 |
| **DeepSeek Search** | Nguồn tìm, ứng viên nguồn chính | Rẻ; có `rerank_score`, `summary`, `content`. Dùng lại `DEEPSEEK_API_KEY` |
| **SearXNG** (tự host) | Nguồn tìm dự phòng / nguồn phụ, miễn phí | Service riêng ở `egress`. Chỉ đoạn trích |
| **Firecrawl** (gói free) | Nguồn **cuối** của chuỗi; dự phòng cho `fetch_url` khi trang chặn bot | Ngân sách Redis toàn cục |
| ~~Crawl4AI~~ | Loại | §1.2.5 |

#### 1.2.2 Hợp đồng API đã đọc (2026-11-03 — kiểm lại lúc mở phase)

- **DeepSeek** ([guide](https://api-docs.deepseek.com/guides/search/)):
  `POST https://api.deepseek.com/v1/tools/search` · `/v1/tools/fetch`, `Authorization: Bearer`.
  - Search: `query` 1–128 ký tự (hỗ trợ `site:`, `-từ`, `lang:`), `count` 1–50 (mặc định 10),
    `ori_question`, `localization`, `need_content` (mặc định `false`, khi đó `content` rỗng).
  - Kết quả: `title`, `url`, `snippet`, `summary` (viết cho model), `content`, `site_name`,
    `date`, `rerank_score` 0–3 (≥ 1.5 là tốt), `authority`.
  - Fetch: chỉ `url` (≤ 8192, không user:pass) ⇒ `title` + markdown.
  - Giá $0.75 / 1.000 lượt **thành công** mỗi loại (hỏng / rỗng / timeout không tính). Tính
    phí từ 2026-11-01. Search 100 QPS, Fetch 25 QPS + trần theo domain.
  - Mã lỗi: **402** hết số dư, **429** vượt QPS.
  - Chưa rõ: chất lượng câu hỏi tiếng Việt, độ dài tối đa của `content`, chính sách lưu dữ liệu.
- **SearXNG** ([search API](https://docs.searxng.org/dev/search_api.html),
  [limiter](https://docs.searxng.org/admin/searx.limiter.html)):
  `GET /search?q=&format=json&categories=&language=&time_range=day|month|year&pageno=&safesearch=`.
  - Phải bật `json` trong `search.formats` của `settings.yml`, không bật ⇒ 403.
  - Limiter cần Valkey. Hoặc tắt (`server.limiter: false`, service không lộ ra ngoài), hoặc
    thêm dải mạng của `worker` vào `pass_ip`.
- **Firecrawl** ([rate limits](https://docs.firecrawl.dev/rate-limits),
  [search](https://docs.firecrawl.dev/features/search)):
  - Endpoint `POST https://api.firecrawl.dev/v2/search`, `Authorization: Bearer fc-…`.
  - Tham số: `query`, `limit`, `sources`, `tbs`, `location`, `includeDomains`, `scrapeOptions`,
    `timeout` (ms). Kết quả ở `data.web[]` (`url`, `title`, `description`, `markdown` nếu scrape).
  - Gói Free: 1.000 credit (docs chưa rõ một lần hay theo tháng), 10 req/phút cho `/search` và
    `/scrape`, 2 trình duyệt song song.
  - Giá credit: search 2 credit / 10 kết quả, cộng 1 credit / trang nếu scrape.

#### 1.2.3 Luồng

```
web_search(query, time_range?, domains?)
  └─ registry._web_search          # quota: 1 lượt/user, dù gọi bao nhiêu nguồn
       └─ HybridSearch.search()
            ① chọn nguồn: thứ tự trong Settings, bỏ nguồn thiếu khoá / đang ngắt mạch
               mode=fallback : thử lần lượt, nguồn hỏng ⇒ nguồn kế
               mode=parallel : 2 nguồn đầu cùng lúc, gộp RRF, khử trùng theo URL đã chuẩn hoá
            ② đọc sẵn top-k (2–3): nguồn đã có chữ (DeepSeek need_content / Tavily
               include_raw_content / Firecrawl markdown) ⇒ dùng luôn; chưa có ⇒ fetcher song song
            ③ cắt bám câu hỏi (BM25 theo đoạn) cho vừa TOOL_RESULT_MAX_CHARS / token_budget()
```

1. **Mỗi nguồn một class** (`DeepSeekSearch`, `SearxngSearch`, `FirecrawlSearch`) theo đúng lối
   `TavilySearch`:
   - hỏng là dữ liệu (`SearchResult(error=…)`), không ném;
   - mã lỗi cố định, không chép thân response;
   - khoá chỉ ở header; thiếu khoá ⇒ `not_configured` ⇒ `HybridSearch` bỏ qua nguồn đó.
2. **Mã lỗi mới** `SearchError.PAYMENT` cho DeepSeek 402 và Firecrawl hết credit. Tavily 432/433
   giữ là `rate_limited`, hoặc chuyển sang mã mới — chốt lúc làm.
3. **Ngắt mạch:**
   - 401 / 402 / 403 / 429 / 432 / 433 ⇒ ghi `websearch:down:{provider}` vào Redis, TTL N giây;
     các lượt sau bỏ qua nguồn đó thay vì chờ timeout.
   - Học lối provider-health của LLM (`core/health_checks.py`, commit bf2db45).
4. **Trần thời gian:**
   - `WEB_SEARCH_TOTAL_TIMEOUT_S` là trần cho cả chuỗi (`asyncio.timeout`); mỗi nguồn vẫn có
     trần riêng của nó (lối hai timeout lồng nhau, B-71).
   - Mode `parallel`: hết trần thì trả những gì đã về.
5. **Gộp kết quả (mode `parallel`):**
   - Chuẩn hoá URL: bỏ `utm_*` / fragment, hạ chữ hoa host.
   - Reciprocal Rank Fusion; kết quả DeepSeek có `rerank_score` < ngưỡng thì xếp sau.
   - Giữ `sources` cho chip nguồn như hôm nay.
6. **Đọc sẵn top-k:**
   - Vẫn đi qua `fetcher` (A5, SSRF bốn lớp), chạy song song.
   - Một trang hỏng không làm hỏng lượt; trang hỏng **không** lên `sources` (khớp ý §0
     "trang đọc lỗi không hiển thị lên UI").
7. **Cắt bám câu hỏi:**
   - BM25 trên các đoạn văn của chữ trang (thư viện nhỏ như `rank_bm25`, hoặc tự viết), giữ
     đoạn liên quan nhất trong trần ký tự chia đều cho mỗi kết quả.
   - Lấy ý tưởng `BM25ContentFilter` / `fit_markdown` của Crawl4AI, không kéo Crawl4AI vào.

#### 1.2.4 Tham số tool + ánh xạ theo nguồn

| Tham số `web_search` | Tavily | DeepSeek | SearXNG | Firecrawl |
|---|---|---|---|---|
| `query` | `query` | `query` (> 128 ký tự ⇒ cắt, hoặc bỏ qua nguồn) | `q` | `query` |
| `time_range` (`day/week/month/year`) | `time_range` (+ `topic: "news"`) | không hỗ trợ — bỏ qua | `time_range` (không có `week` ⇒ `month`) | `tbs=qdr:d/w/m/y` |
| `domains` | `include_domains` | `site:` trong query | `site:` trong query | `includeDomains` |
| số kết quả | `max_results` | `count` | cắt phía mình | `limit` |
| lấy chữ trang | `include_raw_content` | `need_content: true` | — (dùng fetcher) | `scrapeOptions.formats=["markdown"]` (+1 credit/trang) |

Tavily `search_depth: "advanced"` để trong `Settings`, mặc định tắt cho tới khi eval thấy đáng
tiền. Mô tả tool phải nói rõ khi nào nên đặt `time_range` / `domains`.

#### 1.2.5 Đã loại: Crawl4AI

Xét [Crawl4AI](https://docs.crawl4ai.com/core/self-hosting/) (Docker `unclecode/crawl4ai`, cổng
11235, `/crawl`, `/md`…) làm tầng đọc trang. Loại vì:

- **Trùng việc với `fetcher`:** `fetcher` đã có httpx → trafilatura → leo thang Playwright.
- **Vượt rào SSRF:** trình duyệt của Crawl4AI tự resolve DNS và tự ra mạng, đi vòng qua khoá
  `context.route` + SSRF bốn lớp. Cùng lý do đã loại Playwright MCP ở §1.4.
- **Nặng:** tối thiểu 4 GB RAM, `shm` 1 GB.
- **Bề mặt chạy code:** có `/execute_js`; bản 0.9.0 vừa phải bỏ `hooks.code` vì là lỗ RCE.

Chỉ lấy **ý tưởng** cắt nội dung theo câu hỏi (§1.2.3 bước 7).

#### 1.2.6 Hạ tầng + ràng buộc

- **SearXNG — compose:**
  - Service mới, chỉ mạng `egress` (không `internal`, không `env_file`, không `ports`), lối
    `fetcher`; `worker` gọi `http://searxng:8080`.
  - Cập nhật `scripts/check_networks.py`.
  - `settings.yml` + `secret_key` mount `:ro`; image ghim phiên bản.
  - `mem_limit` nhỏ (SearXNG nhẹ, không trình duyệt).
- **SearXNG — rủi ro chính:** gọi Google / Bing từ IP EC2 rất dễ bị CAPTCHA / chặn ⇒ chất lượng
  dao động. Vì vậy **không** làm nguồn chính. Chọn engine ít chặn (DuckDuckGo, Brave, Mojeek,
  Wikipedia…) và đo trong eval.
- **SearXNG — giấy phép:** AGPL-3.0, không vấn đề khi chạy nguyên bản như service riêng.
- **Firecrawl — ngân sách:**
  - Bộ đếm Redis **toàn cục** (không theo user): `FIRECRAWL_MAX_PER_MIN` (< 10) và
    `FIRECRAWL_CREDIT_BUDGET`.
  - Chặn trước khi gọi, không đợi 429.
  - Hết ngân sách ⇒ coi như `not_configured`.
- **Firecrawl — dự phòng cho `fetch_url`:**
  - Chuỗi: `fetcher` → DeepSeek Fetch → Firecrawl scrape.
  - Chỉ leo thang khi trang bị chặn (403 / chữ quá ngắn sau Playwright).
  - **Không bao giờ** leo thang khi `ssrf` đã từ chối URL — URL nội bộ không được ra bên thứ ba.
- **Dữ liệu ra bên thứ ba:** câu hỏi đi tới Tavily / DeepSeek / Firecrawl, URL đi tới DeepSeek
  Fetch / Firecrawl. Ghi vào trang quyền riêng tư nếu có.
- **Bọc kết quả:** mọi kết quả vẫn bọc `untrusted_block`; `summary` của DeepSeek cũng là chữ của
  bên ngoài.
- **Quota:** `web_searches_per_day` vẫn tính **một** lượt cho người dùng dù gọi nhiều nguồn.
- **Chi phí:**
  - Bộ đếm theo nguồn mỗi ngày (`websearch:cost:{provider}:{date}`) để admin thấy chi phí
    DeepSeek ($), credit Tavily, credit Firecrawl.
  - Log mỗi lượt: nguồn đã dùng, độ trễ, số kết quả — không ghi câu hỏi (lối hiện tại: chỉ độ dài).
- **`Settings` (A3)** — mọi giá trị mặc định ở đây, không hằng trong code:
  - nguồn: `WEB_SEARCH_PROVIDERS="deepseek,tavily,searxng,firecrawl"`, `WEB_SEARCH_MODE`;
  - thời gian: `WEB_SEARCH_TOTAL_TIMEOUT_S`;
  - đọc sẵn: `WEB_SEARCH_PREFETCH_TOP_K`;
  - ngắt mạch: `WEB_SEARCH_CIRCUIT_TTL_S`;
  - từng nguồn: `DEEPSEEK_SEARCH_BASE_URL`, `SEARXNG_BASE_URL`, `FIRECRAWL_API_KEY` /
    `FIRECRAWL_BASE_URL`, ngân sách Firecrawl.

#### 1.2.7 Đo trước và sau

Bổ sung ca cần search vào golden-set eval (`make eval`):

- tiếng Việt, tiếng Anh;
- câu thời sự (cần `time_range`);
- câu chỉ định nguồn (cần `domains`).

So các cấu hình:

- Tavily đơn (hôm nay);
- DeepSeek đơn;
- fallback DeepSeek → Tavily;
- parallel DeepSeek + Tavily;
- có / không đọc sẵn top-k.

Thứ tự nguồn mặc định chốt **theo số đo**, không đoán. Thứ tự trong §1.2.6 mới là đề xuất ban đầu.

#### 1.2.8 Thứ tự làm trong A

1. `HybridSearch` mode `fallback` với **Tavily + DeepSeek**, ngắt mạch, `SearchError.PAYMENT`,
   tham số `time_range` / `domains`, eval. Rẻ, lợi ngay.
2. Đọc sẵn top-k + cắt BM25 (ưu tiên chữ nguồn đã trả).
3. Service SearXNG + mode `parallel` (RRF).
4. Firecrawl: nguồn cuối của search + dự phòng của `fetch_url`, có ngân sách.
5. Bảng chi phí theo nguồn trong admin.

### 1.3 B — jev-ultrafast làm tool thứ 3

**jev là gì:** browser agent (MIT, Python, tự host), không phải search API. Đầu vào
`URL + goal`; mỗi bước model Jev (TypeSafe) chọn thao tác (`CLICK`, `TYPE_TEXT`, `SCROLL`…) trên
bảng phần tử đã đánh số; model nhỏ chỉ chạy khi cần gõ chữ. Cần `TYPESAFE_API_KEY` (credit sẽ mua)
+ `TEXT_MODEL_API_KEY` (mặc định `inception/mercury` qua OpenRouter). Không có HTTP API — gọi qua
thư viện Python, tự điều khiển Chrome qua Browser Harness.

**Vai trò:** tool mới, tạm gọi `browse(url, goal)`, cho việc `fetch_url` không làm được —
lọc / phân trang / form tra cứu **chỉ đọc**. `web_search` và `fetch_url` giữ nguyên.

**Bước 0 — task thí nghiệm, có điều kiện dừng** (lối T-7.1). Trả lời trước khi viết tool:
- Chrome của jev có ép được **mọi** request (gồm request con, preconnect, WebSocket) đi qua
  `route` / proxy đã kiểm SSRF trong `fetcher` không? **Không được ⇒ DỪNG**, không làm tiếp B.
- Chạy được trong container `fetcher` (mạng `egress`, không `internal`, không `env_file`) không?
  Khoá TypeSafe / OpenRouter đi vào thế nào mà không phá "fetcher không đọc `.env`"?
- Đo thật: độ trễ và chi phí mỗi lượt trên vài trang mục tiêu (không dựa số 7,1 s trong README —
  chính README ghi đó không phải benchmark độ tin cậy).

**Ràng buộc nếu đi tiếp:**
- **Profile tạm mỗi request**, đóng sau lượt (jev mặc định dùng chung Chrome profile ⇒ cookie
  người này lọt sang người khác). Lối C24: không dùng lại context, `mem_limit`.
- **Chỉ đọc:** cấm đăng nhập, gửi thanh toán, submit form có tác dụng phụ (khớp quyết định đưa
  "Playwright đăng nhập thay user" vào Backlog).
- **Điều hướng do trang quyết định là injection:** mọi URL agent tự đi tới vẫn qua lớp 2–4; trần
  số bước và trần thời gian tổng của lượt (lối "hai timeout lồng nhau" B-71).
- **Hỏng là dữ liệu:** TypeSafe hết credit / lỗi / agent `BLOCKED` ⇒ `ToolResult(ok=False,
  reason=<mã cố định>)`, chat không chết. `DONE` của jev chưa chắc đúng (README tự ghi) — trả kèm
  chữ trích từ trang cuối để model tự kiểm.
- Kết quả bọc `untrusted_block` như `fetch_url`.
- **Quyền + quota riêng:** cờ tier mới (ví dụ `can_use_browser`) + bộ đếm ngày riêng, tách khỏi
  `web_searches_per_day` — chi phí một lượt `browse` khác hẳn một lượt search. Hiện chi phí trong
  admin như các khoản LLM khác.
- Vẫn chiếm một trong `MAX_TOOL_CALLS_PER_TURN`; mô tả tool phải nói rõ khi nào dùng `browse`
  thay vì `fetch_url` để model không gọi tràn lan.
- **Dữ liệu ra bên thứ ba:** nội dung trang đi tới TypeSafe và OpenRouter. Hỏi TypeSafe chính sách
  lưu dữ liệu / giá / rate limit **trước khi mua credit** (docs hiện không ghi).
- Giới hạn MVP đã biết của jev: không shadow DOM, iframe, canvas, upload, popup tab, cuộn lồng —
  trang dạng ấy phải trả `reason` rõ, không treo.

### 1.4 Đã loại: Playwright MCP

Cắm được qua `ToolProvider`, nhưng trùng việc với `fetcher` (đã có Playwright, khoá chặt hơn),
giao quyền lái trình duyệt cho chính model chat (injection, tốn token snapshot), và mặc định không
đi qua lớp SSRF.

### 1.5 Thứ tự đề xuất

A trước, theo §1.2.8 (bước 1–2 rẻ, hợp kiến trúc, đo được bằng eval) → Bước 0 của B → chỉ làm tool `browse` khi Bước 0
qua và có nhu cầu thật về thao tác trên trang.

---

## 2. MCP client + Connectors

**Chưa chốt.** Ý tưởng làm `B-05`: cắm MCP qua `ToolProvider` đã viết sẵn (§13.5), tách hai giai
đoạn — server MCP dùng bearer token trước (§2.2), connector OAuth sau (§2.3).

### 2.1 Hiện trạng (sau P9)

| Thành phần | Đang làm gì |
|---|---|
| `backend/app/tools/registry.py` | `ToolProvider` Protocol (`list_tools(ctx)` **đồng bộ**, `call(...)` async); `Registry([BuiltinTools()])` gom tool mọi provider; `Registry.call` tìm provider bằng cách duyệt `list_tools(ctx)` |
| KH §13.5, R21 | Quy ước tên `mcp__{server}__{tool}`; v1 **không** container, **không** bảng DB cho MCP |
| `llm/byok_endpoints.py`, `byok_verify.py`, `core/crypto.py` | Mẫu sẵn cho "user tự khai endpoint + khoá": lưu mã hoá, kiểm trước khi lưu, màn cài đặt |
| `tools/ssrf.py` | Kiểm SSRF cho URL do người dùng / trang quyết định |

Điểm yếu thấy được: tool chỉ có bốn tool dựng sẵn; muốn nối dịch vụ ngoài (Drive, Notion, GitHub,
DB nội bộ…) là phải viết tool mới trong code.

### 2.2 A — `MCPToolProvider`, server dùng bearer token

1. **Bảng `user_mcp_servers`:** `user_id`, `name` (slug, dùng làm tiền tố tên tool), `url`, token
   mã hoá bằng `core/crypto.py`, `enabled`, `updated_at`. Lối `user_byok_endpoints`: kiểm kết nối
   (`initialize` + `tools/list`) **trước khi lưu**, lỗi trả mã cố định, không lộ host / IP.
2. **Client:** SDK `mcp` Python, transport streamable HTTP. Không chạy server MCP dạng stdio trong
   stack (đó là chạy code tuỳ ý — việc của `sandbox`, không phải `worker`).
3. **`list_tools` đồng bộ mà MCP thì qua mạng** — điểm thiết kế chính. Hướng: lấy danh sách tool
   lúc lưu cài đặt + làm tươi theo TTL vào Redis; `list_tools(ctx)` chỉ **đọc** cache (lối
   `provider_statuses()` của T-3.12: request không bao giờ `await` một lượt đo). `Registry.call`
   tìm provider cũng đọc cache.
4. **Trần:** số server mỗi user, số tool mỗi server được đưa vào request (schema tool là token
   trên mỗi lượt), độ dài mô tả tool. Mọi trần vào `Settings` (A3).

**Ràng buộc:**
- **Mạng:** `worker` ở cả `internal` lẫn `egress` (T-6.5, chỉ để gọi `fetcher`), nhưng nguyên tắc
  A5 là không fetch ra ngoài từ `worker`. Chọn: (a) proxy lời gọi MCP qua `fetcher` / một service
  egress đã kiểm SSRF, hay (b) nới A5 cho riêng MCP có kiểm. `make lint`
  (`scripts/check_networks.py`) phải phản ánh lựa chọn — quyết định lúc mở phase, không lén sửa.
- **SSRF:** URL server do user khai ⇒ qua `tools/ssrf.py`, kể cả lúc kết nối lại / redirect.
- **Kết quả là dữ liệu:** bọc `untrusted_block`; mô tả tool do server MCP đặt cũng là chữ của bên
  thứ ba (tool poisoning) — cắt độ dài, không đặt vào system prompt.
- **Hỏng là dữ liệu:** server chết / timeout / trả sai schema ⇒ `ToolResult(ok=False,
  reason=<mã cố định>)`, chat không chết. Hai timeout lồng nhau (B-71).
- Vẫn chiếm một trong `MAX_TOOL_CALLS_PER_TURN`.
- **Quyền:** cờ tier mới (ví dụ `can_use_mcp`); log `audit_logs` khi thêm / xoá server.
- Tool có tác dụng phụ (ghi, xoá, gửi): v1 của mục này cân nhắc chỉ cho tool user đánh dấu tin
  cậy, hoặc hỏi xác nhận trên UI trước khi gọi.

### 2.3 B — Connector OAuth (giai đoạn 2)

Drive / Gmail / Calendar… cần luồng OAuth: đăng ký app với từng nhà cung cấp, callback, lưu và làm
tươi refresh token (mã hoá), thu hồi khi user ngắt. Nặng hơn A nhiều; chỉ làm khi A chạy ổn và có
nhu cầu thật về một connector cụ thể. Mỗi connector là một server MCP (tự host hoặc của nhà cung
cấp) — không viết tool riêng cho từng dịch vụ.

### 2.4 Thứ tự đề xuất

A (bảng + client + cache tool + màn cài đặt) → chốt câu hỏi mạng trước dòng code đầu → B khi có
connector cụ thể cần dùng.

---

## 3. Cross Session Memory

**Chưa chốt.** Ý tưởng: Scarlet nhớ được thông tin về người dùng giữa các hội thoại. Làm theo ba
bậc, bậc sau chỉ làm khi bậc trước đủ dùng không còn.

### 3.1 Hiện trạng (sau P9)

| Thành phần | Đang làm gì |
|---|---|
| `db/models/user_settings.py` + `core/user_prefs.py` | `prefs_json` chỉ có `avatar_color`, `reasoning` — không có custom instructions |
| `config/prompts/system.jinja` + `llm/context.py` | System prompt có `model_display_name`, `skills`; cache 60 s; **không bao giờ bị cắt** (§9.6) |
| Backlog | `B-09` FTS lịch sử hội thoại, `B-06` RAG — chưa làm |

Điểm yếu thấy được: mỗi hội thoại bắt đầu từ số 0; người dùng phải nhắc lại vai trò, sở thích,
bối cảnh dự án mỗi lần.

### 3.2 Bậc 1 — Custom instructions

Khoá mới trong `prefs_json` (ví dụ `custom_instructions`, trần ký tự trong `Settings`), một ô ở
trang cài đặt, một biến mới trong `system.jinja`. Người dùng tự viết, tự sửa — không có model ghi.
Rẻ nhất, giải phần lớn nhu cầu.

### 3.3 Bậc 2 — Memory do model ghi

1. **Bảng `user_memories`:** `user_id`, `content`, `source_conversation_id`, `created_at`.
2. **Tool `memory_save` / `memory_forget`** trong `BuiltinTools`; mỗi lượt đưa N mục mới nhất (hoặc
   trong trần token) vào system prompt.
3. **Màn quản lý:** người dùng xem, sửa, xoá từng mục; công tắc tắt hẳn memory.

**Ràng buộc:**
- **Token:** system prompt không bị cắt ⇒ phần memory phải có trần riêng, trừ vào
  `token_budget()` trước khi ghép lịch sử — không thì mọi lượt chat của user đó đều mất chỗ.
- **Injection lưu lâu dài:** model đọc trang web / tệp độc rồi tự ghi chỉ dẫn vào memory, chỉ dẫn
  sống mãi qua mọi hội thoại. Hướng: không cho `memory_save` trong lượt đã dùng `fetch_url` /
  `web_search` / tệp đính kèm, hoặc mục mới phải được user xác nhận trên UI; ghi rõ nguồn từng mục.
- Chữ memory đưa vào prompt vẫn là dữ liệu của người dùng, không phải chỉ dẫn hệ thống — ghi rõ
  trong `system.jinja`.
- Xoá tài khoản ⇒ `ON DELETE CASCADE`; xuất dữ liệu (`api/v1/export.py`) phải gồm memory.

### 3.4 Bậc 3 — Nhớ lại hội thoại cũ

Làm `B-09` (Postgres FTS trên `messages`, lọc theo `user_id`) rồi thêm tool `search_conversations`
cho model tự tìm khi người dùng nhắc "lần trước…". Kết quả bọc `untrusted_block`, cắt theo
`TOOL_RESULT_MAX_CHARS`. Nâng lên embedding sau, chung hạ tầng với RAG (`B-06`).

### 3.5 Thứ tự đề xuất

Bậc 1 (nửa ngày, không rủi ro) → đo xem còn nhu cầu không → Bậc 2 với chốt chống injection trước
dòng code đầu → Bậc 3 cùng lúc với `B-09`.
