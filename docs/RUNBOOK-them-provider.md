# RUNBOOK — thêm một provider mới

> Checklist copy-paste cho provider **mức 1** (OpenAI-compatible) và **mức 2**
> (LiteLLM hỗ trợ sẵn, protocol riêng) theo KE-HOACH §9.8.
> Mức 3 (API tự chế, không có bản dịch OpenAI) **không** dùng file này: phải
> viết ADR mới trước khi code, vì nó đang phá vỡ A9.
>
> Tiêu chí nghiệm thu: **S15** — model của provider mới hiện trong Model Picker
> và chat được trong **≤ 15 phút**, **0 dòng `.py`/`.tsx` sửa**.
> Ba file được phép sửa, không có file thứ tư:
> `.env.providers` · `config/litellm.config.yaml` · `config/model_catalog.json`

Điền trước rồi copy-paste — cả runbook dùng lại đúng bốn giá trị này:

```bash
export P=foo                                  # khoá provider trong catalog, chữ thường
export M=foo-large                            # id model, cũng là model_name trong litellm
export BASE=https://api.foo.com/v1            # GỐC API, phải có /v1 — xem C43
export UPSTREAM=openai/foo-large-v2           # chuỗi LiteLLM dùng để gọi upstream
```

---

## 6 bước (KE-HOACH §9.9)

### ☐ Bước 1 — `.env.providers`

```bash
cat >> .env.providers <<EOF
FOO_API_KEY=sk-...
FOO_BASE_URL=$BASE
EOF
```

- `.env.providers` bị gitignore. Thêm **cùng lúc** hai dòng tương ứng (giá trị
  rỗng) vào `.env.providers.example` — file đó mới là thứ người sau đọc được.
- **Không** đụng `.env` và **không** đụng `backend/app/config/settings.py`:
  backend không gọi provider trực tiếp (A9), key provider không phải việc của
  nó (NQ-15). Thêm biến vào `Settings` sẽ làm `make test` đỏ và là dấu hiệu
  bạn đang đi sai đường.
- Provider self-host không có key thì vẫn đặt một chuỗi khác rỗng
  (`FOO_API_KEY=ollama`): SDK OpenAI từ chối key rỗng trước khi gửi request.

### ☐ Bước 2 — `config/litellm.config.yaml`

```yaml
  - model_name: foo-large              # = $M, cũng là tên backend gọi
    litellm_params:
      model: openai/foo-large-v2       # = $UPSTREAM. Mức 2 đổi tiền tố:
                                       #   gemini/…, bedrock/…, vertex_ai/…
      api_base: os.environ/FOO_BASE_URL
      api_key:  os.environ/FOO_API_KEY
```

- `model_name` ở đây **phải trùng** `models[].id` trong catalog. Lệch một ký tự
  thì FE hiện model nhưng gọi ra `400 model not found`.
- Mức 2 (Gemini/Bedrock/Vertex/Azure/Cohere) thường **không** cần `api_base`.

### ☐ Bước 3 — `config/model_catalog.json`, **`"enabled": false`**

File đang là **catalog v4** (`"version": 4`, T-S.3). Backend chỉ đọc đúng v4:
khai số khác thì app không boot và in rõ phiên bản nào cần backend nào.

```jsonc
"foo": {
  "label": "Foo AI",
  "base_url": "https://api.foo.com/v1",  // C43: có /v1, không có / cuối
  "availability": "always",              // "host-dependent" nếu chạy ngoài Docker
  "byok_supported": false,
  "cost_reporting": "exact",             // "unreliable" nếu là gateway (§9.5)
  "auth_style": "bearer",                // bearer | x-api-key | query — C44
  "verify_path": "/models",              // null nếu không có endpoint rẻ — C42
  "user_visible": true                   // false nếu là ĐƯỜNG TRUNG GIAN — xem mục dưới
}
```

```jsonc
{
  "id": "foo-large",                     // = model_name ở bước 2
  "display_name": "Foo Large",           // KHÔNG ghi tên đường trung gian ("qua …")
  "provider": "foo",
  "display_provider": "Foo AI",          // hãng gốc; BẮT BUỘC nếu provider user_visible=false
  "upstream_model": "openai/foo-large-v2",
  "capabilities": [],                    // để RỖNG cho tới khi eval chứng minh — C41
  "context_window": 32768,               // trần VÀO — xem mục "Trần vào / trần ra"
  "max_output": 4096,                    // trần RA  — xem mục "Trần vào / trần ra"
  "pricing": { "input_per_1m": 0.10, "output_per_1m": 0.30 },
  "pricing_mode": "metered",             // "unmetered" nếu cost_reporting unreliable
  "enabled": false,                      // ⬅ LUẬT. Chỉ bật ở bước 6
  "default": false,                      // đúng MỘT model trong cả file được true
  "order": 40
  // "reasoning": KHÔNG khai ở bước này — chỉ sau khi đo (mục "Thêm một mức suy luận")
}
```

Giá viết thế nào thì Model Picker hiện đúng chữ số ấy (`0.30` ra `"0.30"`): tiền
đi dạng chuỗi từ catalog tới màn hình.

### ☐ Bước 4 — dựng lại LiteLLM

```bash
docker compose --profile core --profile tools up -d litellm
docker compose logs --tail=30 litellm          # không có traceback
```

### ☐ Bước 5 — gọi thử (bước **không được bỏ**)

```bash
# KHÔNG `source .env`: file đó không phải script shell (`MAIL_FROM=Scarlet
# <no-reply@…>` làm bash chết), và `cut -d= -f2-` thì nuốt luôn chú thích cuối
# dòng — key dài 86 ký tự thay vì 35 và LiteLLM trả "No connected db.".
KEY=$(sed -nE 's/^LITELLM_MASTER_KEY=([^#]*).*/\1/p' .env | sed -E 's/[[:space:]]+$//')

curl -s http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$M\",\"messages\":[{\"role\":\"user\",\"content\":\"Xin chào\"}],
       \"stream\":true,\"stream_options\":{\"include_usage\":true}}" | tail -5
```

Ba thứ phải thấy trong output, thiếu thứ nào thì quay lại bảng cạm bẫy:

1. các chunk `data: {...}` có `delta.content` — chat được
2. chunk áp chót có `"usage":{"prompt_tokens":N,"completion_tokens":M}`, **cả
   hai > 0** — C40. Không có ⇒ `pricing_mode: "unmetered"` +
   `cost_reporting: "unreliable"`, đừng để `metered` với usage rỗng
3. `data: [DONE]` — C19

Rồi chạy bộ 12 case golden-set (§21.3): `make eval MODEL=$M`.

### ☐ Bước 6 — bật

```bash
# sửa "enabled": false -> true trong config/model_catalog.json
curl -sk -X POST https://localhost/api/v1/admin/catalog/reload | jq
curl -sk https://localhost/api/v1/models | jq '.[] | select(.id=="'$M'")'
```

---

## Provider hiển thị: `display_provider` / `user_visible` (catalog v4, NQ-119)

Người dùng chỉ thấy **hãng làm ra model** (DeepSeek, Anthropic, Google AI, xAI,
Alibaba Qwen…), không bao giờ thấy **đường đi** (9Router, Sub2API, một gateway
tự dựng…).

| Provider là… | `user_visible` | `display_provider` của model |
|---|---|---|
| Hãng gốc, gọi thẳng API của họ | bỏ trống (mặc định `true`) | tuỳ chọn — vắng thì dùng `label` của provider |
| Đường trung gian (router, gateway, proxy chạy trên host) | `false` | **bắt buộc** — thiếu thì app **không boot** và log in đúng `id` model |

Khi `user_visible: false`:

- `GET /models` trả `provider` = `display_provider`, và `provider_id` = `null`
  (đường trung gian không có khoá BYOK nào để so — NQ-123).
- `unavailable_reason` là một câu chung, không chèn `label`.
- **Không** viết tên đường đi vào `display_name` hay `badge` — đó là hai chỗ
  loader không kiểm được. Kiểm bằng tay sau khi bật:

  ```bash
  curl -sk https://localhost/api/v1/models | grep -ciE "9router|sub2api|<tên đường mới>"   # phải ra 0
  ```

- Màn quản trị vẫn cần đường đi thật (health đo theo đường đi, §9.5) — nó đọc
  `GET /admin/models` (T-S.8), không đọc `GET /models`.

`display_provider` là dữ liệu: đổi tên hãng hiển thị = sửa một dòng + `POST
/admin/catalog/reload`, không sửa code.

---

## Thêm một mức suy luận — **đo trước, khai sau** (NQ-118)

`litellm_settings.drop_params: true` bỏ im lặng tham số provider không nhận: một
mức sai vẫn `200 OK` và chỉ đổi mỗi hoá đơn. Vì vậy **không mức nào vào catalog
khi chưa đo** — bằng chứng duy nhất là `reasoning_tokens` đổi rõ so với mức kề.

1. **Khai thang đo** trong `scripts/probe_reasoning.json` (dữ liệu, không phải
   code): thêm một phần tử vào `cases` của model trong `models[]` —
   `{ "level": "<id>", "ladder": "<tên thang>", "params": { … } }`, với đúng
   `params` bạn định khai và cùng `ladder` với các mức sẽ được so cạnh nó.
   Model chưa có trong file thì thêm một mục `{ "id", "paths", "max_tokens",
   "cases" }` theo mẫu các mục sẵn có. Mức chọn bằng **tên model khác** (kiểu
   9Router `…-high`) thì thêm `"alias"` và thêm tạm alias ấy vào
   `litellm.config.yaml`.
2. **Chạy thử khô, rồi đo thật** (tốn tiền thật — xem `budget_usd` trong file):

   ```bash
   source scripts/llm_env.sh
   backend/.venv/bin/python scripts/probe_reasoning.py --dry-run --model $M
   backend/.venv/bin/python scripts/probe_reasoning.py --ledger-user-id <uuid admin> --model $M
   backend/.venv/bin/python scripts/probe_reasoning.py --report
   ```

3. **Giữ mức** chỉ khi **cả hai** lượt đo "khác rõ" mức kề nó (ngưỡng `distinct`
   trong file kế hoạch: ≥ 32 token **và** ≥ 1.2 lần). Không khác rõ ⇒ bỏ mức ấy.
4. **Khai** vào `models[].reasoning` của catalog:

   ```jsonc
   "reasoning": {
     "default": "high",                                   // phải là một id trong options
     "options": [
       { "id": "off",  "params": { "thinking": { "type": "disabled" } } },
       { "id": "high", "params": { "thinking": { "type": "enabled" } } },
       { "id": "low",  "params": {}, "alias": "foo-large-low" },            // mức chọn bằng tên model
       { "id": "max",  "params": { … }, "byok_params": { … } },             // BYOK cần tham số khác
       { "id": "xhigh", "params": { … }, "omit_temperature": true }         // provider cấm temperature khi nghĩ
     ]
   }
   ```

   - `id` chỉ được lấy trong bộ `off · low · medium · high · xhigh · max`. Nhãn
     hiển thị (Off · Low · Medium · High · Extra High · Max) nằm ở `vi.json`.
   - `params` trộn **nguyên văn** vào body request; chúng không bao giờ rời
     backend (FE chỉ nhận `id`).
   - `alias` phải có `model_name` tương ứng trong `config/litellm.config.yaml`
     — `make test` đọc cả hai file và đỏ nếu thiếu. Rồi
     `docker compose up -d --force-recreate litellm` (B-40).
   - Chỉ khai `byok_params` / `omit_temperature` khi phép đo cho thấy cần.
5. `POST /admin/catalog/reload` → `GET /models` có `reasoning.options` mới.

Sai luật (`default` không thuộc `options`, `id` ngoài bộ từ vựng, `id` trùng)
⇒ app **không boot** và in đúng `id` model. Model không có khối `reasoning` ⇒
picker hiện hàng Thinking Effort mờ.

---

## Trần vào (`context_window`) và trần ra (`max_output`)

| Trường | Nghĩa | Ai đọc |
|---|---|---|
| `context_window` | số token tối đa model nhận (vào + ra) | dựng context (§9.6) |
| `max_output` | `max_tokens` gửi đi; trần của phần sinh **kể cả token suy luận** | dựng context, dự toán quota `est_max` (§10.2) |

Ngân sách ngữ cảnh của một model:

```
budget = min(context_window, CONTEXT_WINDOW_CAP) − max_output − RESERVE_TOKENS
```

(`CONTEXT_WINDOW_CAP` mặc định 128000, `RESERVE_TOKENS` mặc định 1000 — cả hai
ở `.env`). Hai ràng buộc phải giữ khi sửa một trong hai trường:

1. **`max_output` > ngân sách thinking lớn nhất của model.** Token suy luận
   nằm **trong** `max_tokens`; Anthropic còn từ chối request có `max_tokens` ≤
   `thinking.budget_tokens`. Ví dụ hôm nay: `claude-haiku` có mức `high` với
   `budget_tokens: 4096` ⇒ `max_output` (8192) phải > 4096. Hạ `max_output`
   xuống dưới đó là giết mức `high`. Loader **không** kiểm ràng buộc này (tên
   tham số ngân sách là của từng provider) — tự kiểm.
2. **`MESSAGE_MAX_CHARS` < `budget` nhỏ nhất của catalog** (B-208). Trần ký tự
   của một tin nhắn phải là cửa chặn **đầu tiên**; nếu một tin nhắn hợp lệ vẫn
   có thể vượt ngân sách của model nhỏ nhất thì nó qua được cửa API rồi mới nổ
   `CONTEXT_TOO_LARGE` trong worker. Hôm nay: `ol-qwen-small` =
   `min(32768, 128000) − 4096 − 1000 = 27672` > `MESSAGE_MAX_CHARS` 24000 (tính
   ở tỷ lệ bi quan 1 token / ký tự). Thêm model có `context_window` nhỏ, hoặc
   tăng `max_output`, thì tính lại dòng này; không có phép kiểm tự động nào
   canh nó.

Tăng `max_output` còn làm **tăng dự toán quota** mỗi lượt (`est_max` tính như
thể toàn bộ `max_output` là token ra) — người dùng sắp hết quota sẽ bị chặn sớm
hơn với model đó.

---

## 6 cạm bẫy (KE-HOACH §9.10)

| # | Triệu chứng | Nguyên nhân | Sửa |
|---|---|---|---|
| **C40** | Chat được nhưng `usage_events.cost_usd = 0`, quota không bao giờ trừ | Provider bỏ qua `stream_options: {include_usage: true}` nên chunk cuối không có `usage` | Kiểm bằng bước 5 mục 2, hoặc `SELECT prompt_tokens, completion_tokens FROM usage_events ORDER BY created_at DESC LIMIT 1` — cả hai phải > 0. Không có ⇒ ước tính bằng tiktoken + `cost_confidence='low'` |
| **C41** | Provider khai có `tools` nhưng tool call vỡ hoặc bị bỏ qua | Nhiều endpoint "OpenAI-compatible" chỉ compatible ở phần text | Case 4–6 của golden-set. Vỡ ⇒ bỏ `tools` khỏi `capabilities` — FE tự vô hiệu hoá công tắc Tìm web và panel Skills (§9.4) |
| **C42** | Thêm BYOK cho provider mới thì luôn báo "key không hợp lệ" | Không phải provider nào cũng có `GET /models` để kiểm key | `verify_path` trong catalog. Không có endpoint rẻ nào ⇒ `verify_path: null` → lưu key mà không kiểm, và **báo cho user biết là chưa xác thực** |
| **C43** | `404 Not Found` từ upstream, dù dán URL vào trình duyệt thì chạy | `base_url` thiếu `/v1`, hoặc có `/` cuối — SDK `openai` và LiteLLM ghép đường dẫn khác nhau | Loader `app/config/catalog.py` đã chặn: cắt `/` cuối và **bắt buộc** segment cuối là phiên bản (`/v1`, `/v2`, `/v1beta`). Sai thì app **không boot** và báo đúng tên provider |
| **C44** | `401` dù key đúng | Provider dùng `x-api-key` thay vì `Authorization: Bearer` | `auth_style` trong catalog. LiteLLM xử lý phần lớn trường hợp, nhưng `ByokAdapter` (§9.1) gọi thẳng thì phải tự áp dụng |
| **C45** | Chạy được trên máy dev nhưng chết trong container | `localhost` trong container là chính container đó | Self-host **trong compose** ⇒ dùng **tên service** (`http://ollama:11434/v1`). Self-host **trên máy host** ⇒ `host.docker.internal` + `extra_hosts` (C17) |

### Cạm bẫy thứ 7 — của riêng repo này

`.env.providers` **không** có fail-fast. `.env` thiếu biến thì app không boot và
in đúng tên biến (A4), nhưng `.env.providers` chỉ được LiteLLM đọc: gõ sai tên
biến ở đây thì mọi thứ vẫn "xanh" cho tới lúc ai đó chọn model mới và nhận
`401`. Đây là cái giá đã biết trước của NQ-15 — và là lý do **bước 5 bắt buộc**.

### Cạm bẫy thứ 8 — chú thích cuối dòng trong file `.env*` (B-31, B-44)

Viết `FOO_API_KEY=abc123   # khoá của Foo` thì **giá trị thật vẫn là `abc123`**
(docker compose cắt chú thích khi giá trị khác rỗng), nhưng cùng cú pháp đó với
giá trị **rỗng** — `FOO_API_KEY=    # để trống nếu…` — làm compose lấy nguyên
chuỗi `# để trống nếu…` **làm giá trị**. Biến tưởng là rỗng hoá ra khác rỗng,
nên mọi nhánh `if not key:` đều đi sai đường (B-44).

Luật: trong `.env.providers`, **chú thích nằm trên dòng riêng**.
Và khi đọc `.env` bằng shell thì cắt chú thích như ở bước 5 — đừng `cut -d=`.

---

## Gỡ một provider

Xoá entry khỏi `models[]` và `providers{}` trong catalog, xoá entry trong
`litellm.config.yaml`, xoá dòng trong `.env.providers`, rồi
`docker compose up -d litellm` + `POST /admin/catalog/reload`.
Provider còn lại không bị ảnh hưởng — catalog validate độc lập từng provider.
Nếu model bị xoá đang là `"default": true` thì app **không boot** cho tới khi
có model khác nhận `default` (đúng một, không nhiều hơn).
