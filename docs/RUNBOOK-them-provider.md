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

```jsonc
"foo": {
  "label": "Foo AI",
  "base_url": "https://api.foo.com/v1",  // C43: có /v1, không có / cuối
  "availability": "always",              // "host-dependent" nếu chạy ngoài Docker
  "byok_supported": false,
  "cost_reporting": "exact",             // "unreliable" nếu là gateway (§9.5)
  "auth_style": "bearer",                // bearer | x-api-key | query — C44
  "verify_path": "/models"               // null nếu không có endpoint rẻ — C42
}
```

```jsonc
{
  "id": "foo-large",                     // = model_name ở bước 2
  "display_name": "Foo Large",
  "provider": "foo",
  "upstream_model": "openai/foo-large-v2",
  "capabilities": [],                    // để RỖNG cho tới khi eval chứng minh — C41
  "context_window": 32768,
  "max_output": 4096,
  "pricing": { "input_per_1m": 0.10, "output_per_1m": 0.30 },
  "pricing_mode": "metered",             // "unmetered" nếu cost_reporting unreliable
  "enabled": false,                      // ⬅ LUẬT. Chỉ bật ở bước 6
  "default": false,                      // đúng MỘT model trong cả file được true
  "order": 40
}
```

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
