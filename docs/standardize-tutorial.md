# Hướng dẫn triển khai Phase S — Standardize

> **Tài liệu này dành cho BẠN, không dành cho agent.** Nó trả lời: làm bước nào trước, dán chữ gì vào
> Claude Design, nhìn cái gì để biết bản vẽ đã đạt, và nói gì với Claude Code để nó làm từng task.
>
> Nguồn: `tasks.md` §7b (task, DoD, bảng nút chờ), KE-HOACH §24.2b (cái gì và tại sao),
> `docs/design-tutorials.md` (cách làm T-HD của Phase 3 — tài liệu này là phần tiếp theo của nó).
> Viết ngày 2026-09-23.

---

## 0. Trước khi bắt đầu — 15 phút

1. **Commit những thay đổi đang dở của bạn.** Working tree ngày 2026-09-23 có `design/README.md`,
   `frontend/package.json` (thêm `morphicons`), `frontend/pnpm-lock.yaml` chưa commit. T-S.0 và T-S.1
   cần một cây sạch — T-S.1 đổi tên hàng trăm chỗ, trộn nó với thay đổi dở là một conflict không ai gỡ nổi.
2. **Xoá `frontend/package-lock.json`** — file lock của npm, trong khi repo dùng pnpm (B-269).
3. **Chắc rằng P3 đã xong hết** (T-3.12 ✅). Phase S bắt đầu từ đó.
4. **Ghim sẵn hai link:** Scarlet Design System (`https://claude.ai/artifact/91nTKKUNZdW7VdSrSVGv6E`) và
   project Claude Design chứa các bản v1 (`https://claude.ai/design/p/367a3a52-8862-45dd-af4e-cfbce7ae3b56`).

---

## 1. Bức tranh toàn cảnh

Phase S có hai dòng việc chạy **song song**: agent làm backend (không cần bản vẽ nào), bạn vẽ trên
Claude Design. Khi đủ bản vẽ, agent làm phần giao diện, mỗi task đúng một bản vẽ.

```
   CLAUDE CODE (agent)                                  BẠN (Claude Design)
   ───────────────────                                  ───────────────────
   T-S.0  mở phase (mục v2 trong design/README.md)  ──▶ T-HD1-v2  token bổ sung
   T-S.1  🔒 đổi tên định danh                           T-HD2-v2  khung chính
   T-S.2  🔒 đo mức suy luận   ◀── bạn bật 9Router       T-HD9     trang Cài đặt
                                  + Sub2API              T-HD8     sáu màn auth
   T-S.3  catalog v4 ──── dữ liệu thật ────────────────▶ T-HD3-v2  bong bóng
   T-S.4  picker tự nạp                                  T-HD4-v2  Model Picker
   T-S.5  hồ sơ + tuỳ chọn                               T-HD7-v2  quản trị
   T-S.6  mức suy luận đầu-cuối                          T-HD5-v2  chuyển động  (vẽ CUỐI)
   T-S.7  🔒 đặt tên hội thoại
   T-S.8  backend mở đường
             ─────────────── đủ tám bản vẽ ───────────────
   T-S.9  theme v2 + ComingSoon + Icon       ← T-HD1-v2 + T-HD5-v2
   T-S.10 🔒 ô nhập + hội thoại nháp          ← T-HD2-v2
   T-S.11 trang Cài đặt                       ← T-HD9
   T-S.12 header + khối tài khoản             ← T-HD2-v2
   T-S.13 sidebar                             ← T-HD2-v2
   T-S.14 Model Picker                        ← T-HD4-v2
   T-S.15 bong bóng                           ← T-HD3-v2
   T-S.16 sáu màn auth                        ← T-HD8
   T-S.17 quản trị                            ← T-HD7-v2
   T-S.18 đối chiếu toàn bộ v2 ↔ code
   T-S.19 phần còn sót — BẠN giao nội dung
```

**Vì sao thứ tự này:**

- **T-S.1 (đổi tên) đi trước mọi thứ**, để không task nào viết thêm vào một file sắp bị đổi tên.
- **T-HD3-v2 và T-HD4-v2 chờ T-S.3** vì chúng vẽ dữ liệu thật: tên hãng hiển thị và các mức suy luận
  chỉ chắc chắn sau khi T-S.2 đã đo và T-S.3 đã ghi vào catalog. Vẽ trước là vẽ cho dữ liệu đoán.
- **T-HD5-v2 vẽ cuối** vì nó định nghĩa chuyển động cho những thứ các bản khác vẽ ra (ô nhập trượt,
  menu con của picker, thanh quota trong Cài đặt).
- **T-S.9 chờ cả T-HD1-v2 lẫn T-HD5-v2**, và mọi task giao diện chờ T-S.9. Nên giao diện chỉ bắt đầu khi
  đủ tám bản vẽ — backend (T-S.0 … T-S.8, khoảng 29 giờ) đủ dài để bạn vẽ xong trong lúc ấy.

---

## 2. Lộ trình từng bước

Làm từ trên xuống. Cột "Ai" cho biết bạn đang giao việc cho agent hay tự làm trên Claude Design.
Hai dòng việc chen nhau là bình thường: agent làm một task thì bạn vẽ một bản.

| # | Ai | Việc | Cần có trước | Xong thì |
|---|---|---|---|---|
| 1 | Agent | **T-S.0** — mục v2 trong `design/README.md` | §0 của tài liệu này | Có bảng v2 trống để bạn ghi link |
| 2 | Bạn | **T-HD1-v2** (§5) | — | Ghi link vào bảng v2; ghi đè `design/theme.css` + `design/contrast.md` |
| 3 | Agent | **T-S.1** 🔒 — đổi tên định danh | cây sạch | — |
| 4 | Bạn | **T-HD2-v2** (§6) | T-HD1-v2 | Ghi link |
| 5 | Agent | **T-S.2** 🔒 — đo mức suy luận | **bạn bật 9Router + Sub2API** | Bảng đo trong "Ghi nhận" của T-S.2 |
| 6 | Bạn | **T-HD9** (§7) | T-HD1-v2 | Ghi link |
| 7 | Agent | **T-S.3** — catalog v4 | T-S.2 | Bảng dữ liệu thật cho T-HD3-v2/T-HD4-v2 |
| 8 | Bạn | **T-HD8** (§8) | T-HD1-v2 | Ghi link |
| 9 | Agent | **T-S.4** — Model Picker tự nạp | — | — |
| 10 | Bạn | **T-HD3-v2** (§9) | **T-S.3** | Ghi link |
| 11 | Agent | **T-S.5** — hồ sơ + tuỳ chọn | — | — |
| 12 | Bạn | **T-HD4-v2** (§10) | **T-S.3** | Ghi link |
| 13 | Agent | **T-S.6** — mức suy luận đầu-cuối | — | — |
| 14 | Bạn | **T-HD7-v2** (§11) | T-HD1-v2 | Ghi link |
| 15 | Agent | **T-S.7** 🔒 — đặt tên hội thoại | — | — |
| 16 | Bạn | **T-HD5-v2** (§12) — vẽ cuối | T-HD2-v2, T-HD4-v2, T-HD9 | Ghi link; ghi đè `design/theme.css`; tạo `design/motion-springs.ts` |
| 17 | Agent | **T-S.8** — backend mở đường | — | Hết phần backend |
| 18 | Agent | **T-S.9** — theme v2 + `ComingSoon` + `Icon` | T-HD1-v2, T-HD5-v2 | — |
| 19 | Agent | **T-S.10** 🔒 — ô nhập + hội thoại nháp | T-HD2-v2 | — |
| 20 | Agent | **T-S.11** — trang Cài đặt | T-HD9 | — |
| 21 | Agent | **T-S.12** — header + khối tài khoản | T-HD2-v2 | — |
| 22 | Agent | **T-S.13** — sidebar | T-HD2-v2 | — |
| 23 | Agent | **T-S.14** — Model Picker | T-HD4-v2 | — |
| 24 | Agent | **T-S.15** — bong bóng | T-HD3-v2 | — |
| 25 | Agent | **T-S.16** — sáu màn auth | T-HD8 | — |
| 26 | Agent | **T-S.17** — quản trị | T-HD7-v2 | — |
| 27 | Agent | **T-S.18** — đối chiếu toàn bộ v2 ↔ code | 19–26 | M5b |
| 28 | Agent | **T-S.19** — phần còn sót, **bạn giao nội dung** | T-S.18 | Phase S xong |

> Bạn đổi được thứ tự các bước vẽ (2, 4, 6, 8, 10, 12, 14, 16) với nhau, miễn giữ ba điều: T-HD1-v2 đầu
> tiên, T-HD3-v2/T-HD4-v2 sau T-S.3, T-HD5-v2 cuối cùng. Thứ tự các task của agent thì **không** đổi.

---

## 3. Giao task cho Claude Code

Mỗi phiên Claude Code làm **đúng một task** (luật G1). Xong một task: đọc báo cáo bốn phần, kiểm output
DoD, rồi mới giao task tiếp theo.

### 3.1 Prompt cho task backend (T-S.0, T-S.1, T-S.3 … T-S.8)

```text
Làm task T-S.<n> trong docs/tasks.md.
Đọc mục "KH tham chiếu" của task (KE-HOACH §24.2b và các mục nó trỏ tới) trước khi viết dòng code đầu tiên.
```

Lời dặn thêm cho vài task:

| Task | Thêm vào prompt |
|---|---|
| **T-S.0** | `Tôi đã commit các thay đổi của tôi trong design/README.md.` |
| **T-S.1** | `Cây đã sạch. Đây là commit đổi tên thuần tuý — thấy bug thì ghi Backlog, không sửa.` |
| **T-S.2** | `9Router và Sub2API đang chạy trên máy Windows. Ngân sách thí nghiệm tối đa 0.10 USD.` |
| **T-S.3** | Nếu muốn tên hãng hiển thị khác đề xuất (DeepSeek · Anthropic · Google AI · xAI · Alibaba Qwen), ghi luôn: `Dùng display_provider: <model> = <tên>, …` |

### 3.2 Prompt cho task giao diện (T-S.9 … T-S.17)

Mỗi task FE cần đúng một bản vẽ (cột "Cần có trước" ở §2). Khi Claude Design xuất bản vẽ để giao cho
Claude Code, nó cho một đoạn chữ bắt đầu bằng `Use the claude_design MCP …` — đó chính là đoạn bạn đã ghi
vào `design/README.md`. Dán lại nguyên đoạn ấy:

```text
Làm task T-S.<n> trong docs/tasks.md.

Bản thiết kế: <T-HDx-v2> — đã ghi ở design/README.md, mục v2:
<dán nguyên đoạn "Use the claude_design MCP (…) to import this project: … Implement: …">

- Màu, spacing, bố cục đã chốt. Thấy sai thì BÁO LẠI, không sửa.
- Nếu một chỗ trong bản vẽ làm một dòng DoD không đạt được, dừng và hỏi — đừng chỉnh bản vẽ cho DoD xanh.
- Đọc mục "KH tham chiếu" của task trước khi viết dòng code đầu tiên.
```

Riêng **T-S.9** cần **hai** bản: T-HD1-v2 (token) và T-HD5-v2 (chuyển động). Dán cả hai đoạn, và nói
thêm: `Token đã ở design/theme.css, hằng lò xo ở design/motion-springs.ts.`

### 3.3 Prompt cho T-S.18 (đối chiếu) và T-S.19 (task cuối)

```text
Làm task T-S.18 trong docs/tasks.md. Tám bản v2 đã ghi đủ ở design/README.md, mục v2.
Lệch trình bày thì sửa; lệch hành vi thì dừng và hỏi tôi.
```

```text
Làm task T-S.19 trong docs/tasks.md. Nội dung tôi giao:
1. <chỗ còn sót thứ nhất>
2. <…>
Chép phần "Việc" và "Xong khi (DoD)" vào task trước khi viết dòng code đầu tiên, ghi ước lượng,
rồi đưa tôi xem trước khi làm.
```

### 3.4 Nghiệm thu một task

- Báo cáo có đúng **bốn phần** (`tasks.md` §0.4): đã làm gì · output thật của từng dòng DoD · lệch kế hoạch
  chỗ nào · cần ghi Backlog gì.
- Mỗi dòng DoD phải có **output dán nguyên văn**, không phải "đã test kỹ".
- Task 🔒 (T-S.1, T-S.2, T-S.7, T-S.10) phải là **một commit riêng**, không kèm gì khác.
- Commit dạng `feat(T-S.<n>): <mô tả>`.

---

## 4. Làm việc trên Claude Design

### 4.1 Mở đúng chỗ, đặt đúng tên

- **T-HD1-v2** sửa **Scarlet Design System** (artifact ở §0 bước 4). Yêu cầu nó đổi nhãn đầu trang thành
  `Design System · v2.0`; bản cũ vẫn còn trong lịch sử phiên bản của artifact.
- **T-HD2-v2, T-HD3-v2, T-HD4-v2, T-HD5-v2, T-HD7-v2**: mở **cùng project** chứa bản v1, yêu cầu Claude Design
  tạo **file mới** dựa trên file v1, tên có đuôi ` v2`:

  | Bản | File v1 (giữ nguyên, không sửa) | File v2 (tạo mới) |
  |---|---|---|
  | T-HD2-v2 | `Scarlet Khung chính.dc.html` | `Scarlet Khung chính v2.dc.html` |
  | T-HD3-v2 | `Scarlet Bong bóng tin nhắn.dc.html` | `Scarlet Bong bóng tin nhắn v2.dc.html` |
  | T-HD4-v2 | `Scarlet Model Picker.dc.html` | `Scarlet Model Picker v2.dc.html` |
  | T-HD5-v2 | `Scarlet Chuyển động.dc.html` | `Scarlet Chuyển động v2.dc.html` |
  | T-HD7-v2 | `Scarlet Quản trị.dc.html` | `Scarlet Quản trị v2.dc.html` |

- **T-HD8** và **T-HD9** là màn mới: tạo file `Scarlet Xác thực.dc.html` và `Scarlet Cài đặt.dc.html` trong
  cùng project.

> **Đừng sửa file v1.** T-S.18 đọc v1 cạnh v2 để biết cái gì đã đổi. Sửa đè v1 là mất chuẩn để so.

### 4.2 Bản giao kèo v2 — dán vào ĐẦU mọi cuộc trò chuyện

Giống bản giao kèo của Phase 3 (`design-tutorials.md` §2), thêm năm ràng buộc mới (10–14) đến từ các quyết
định NQ-117 … NQ-121:

```text
Dự án: Scarlet — chatbot self-host cho 15–20 người dùng nội bộ. Giao diện tiếng Việt.
Đây là vòng CHUẨN HOÁ: tôi vẽ lại một số màn đã có (bản v1) thành bản v2, trên Scarlet
Design System có sẵn. Giữ nguyên mọi thứ của v1 mà tôi không nói đổi.

Stack đã chốt, KHÔNG đổi được:
React 19 + TypeScript + Vite + TailwindCSS v4. Không UI-kit lớn (MUI, AntD, Chakra).
Primitive chọn lọc từ Radix (dialog, popover, tooltip, dropdown-menu).
Icon: bộ Lucide (nét, lưới 24×24), render qua thư viện morphicons để icon biến hình được.

MƯỜI BỐN RÀNG BUỘC — mọi thứ bạn xuất ra phải thoả cả mười bốn:

1. Màu chỉ tồn tại dưới dạng CSS variable trong MỘT file theme.css.
   Trong mã component tuyệt đối không có #rrggbb, rgb(), hsl(), oklch().
2. Sáng/tối KHÔNG dùng biến thể `dark:` của Tailwind. Một bộ tên class, hai bộ giá trị:
     @theme { ... }              ← giá trị theme sáng
     [data-theme="dark"] { ... } ← ghi đè cho theme tối, nằm NGOÀI @theme
3. KHÔNG đổi tên, KHÔNG đổi giá trị bất kỳ biến nào đã có trong theme.css. Chỉ THÊM.
4. Thời lượng và easing là token trong theme.css. Mã component không chứa `transition:`,
   `animation:`, `150ms`, hay `duration-[200ms]`; component chỉ gắn class .motion-*.
5. Mọi chuỗi tiếng Việt tách khỏi component (vi.json, khoá phẳng dạng "chat.gui").
   Không interpolation: đừng viết câu có biến ở giữa; tách thành hai mảnh.
6. 375 px là bề rộng nhỏ nhất phải chạy đúng. Không cuộn ngang ở bất kỳ màn nào.
7. Vùng chạm tối thiểu 44 × 44 px.
8. Lighthouse Accessibility ≥ 90, axe-core 0 lỗi serious/critical. Tương phản chữ ≥ 4.5:1,
   chữ lớn và thành phần đồ hoạ ≥ 3:1 — trong CẢ HAI theme. Mọi thành phần tương tác có
   trạng thái focus nhìn thấy được.
9. Định danh trong mã (biến, hàm, prop, tên file) viết bằng tiếng Anh.
   Chỉ chuỗi hiển thị mới là tiếng Việt.
10. Mọi phần tử bấm được có con trỏ bàn tay; phần tử bị khoá có con trỏ not-allowed.
11. NÚT CHỜ — nút của tính năng chưa có: trông như nút thật đang bị khoá (mờ, con trỏ
    not-allowed, tooltip "Sắp có"), không có hành vi nào. Tooltip KHÔNG ghi phase hay ngày.
12. KHÔNG BAO GIỜ hiện tên đường trung gian "9Router" hay "Sub2API" ở màn của người dùng —
    chỉ tên hãng gốc (DeepSeek, Anthropic, Google AI, xAI, Alibaba Qwen). Riêng màn Quản trị
    được thấy đường đi thật.
13. Mức suy luận viết bằng tiếng Anh: Off · Low · Medium · High · Extra High · Max.
14. Chỉ dùng icon loại NÉT (stroke) của Lucide — morphicons không biến hình được icon đặc (fill).

Khi xuất mã, luôn xuất HAI thứ tách rời:
  (a) phần theme.css — chỉ CSS variable (và class .motion-* nếu có);
  (b) phần component .tsx — chỉ dùng class tiện ích Tailwind sinh ra từ các biến đó.
```

### 4.3 Ghi link vào `design/README.md`

Sau mỗi bản vẽ: bảng **v2** (T-S.0 dựng) → cột Link: dán nguyên đoạn `Use the claude_design MCP … Implement: …`
mà Claude Design xuất khi bạn chọn giao cho Claude Code — giống hệt cách bạn đã ghi các dòng v1. Cột Ngày chốt:
ngày bạn chốt bản vẽ.

---

## 5. T-HD1-v2 — Token bổ sung

**Làm khi:** ngay sau T-S.0. **Chặn:** T-S.9 (và gián tiếp mọi task giao diện).
**Mở:** Scarlet Design System. **Đầu ra:** phần `theme.css` bổ sung + bảng tương phản bổ sung.

### 5.1 Dán gì vào

Thứ tự: **(1) bản giao kèo §4.2** → **(2) nội dung `design/theme.css` hiện tại** → **(3) prompt dưới đây**.

```text
Đây là bản v2 của hệ thống thiết kế Scarlet. KHÔNG vẽ lại từ đầu: giữ nguyên mọi token đã có
(tên lẫn giá trị), chỉ THÊM bốn thứ dưới đây. Đổi nhãn đầu trang thành "Design System · v2.0".

1. BẢNG MÀU AVATAR — 8 màu nền cho avatar tròn chứa MỘT chữ cái đầu của tên người dùng.
   Tên biến: --color-avatar-1 … --color-avatar-8, cộng --color-avatar-foreground cho chữ.
   Chữ trên mọi màu nền phải ≥ 4.5:1 ở CẢ HAI theme — in bảng tương phản 16 ô (8 màu × 2 theme).
   Tám màu phải phân biệt được với nhau, và KHÔNG màu nào gần accent hay danger
   (một avatar đỏ son trông như một nút bấm, một avatar đỏ thẫm trông như một lỗi).
   Cho tôi xem 8 avatar mẫu với 8 chữ cái khác nhau, cả hai theme.

2. TRẠNG THÁI "NÚT CHỜ" — nút của tính năng chưa có. Nó trông như nút thật đang bị khoá:
   mờ đi, con trỏ not-allowed, tooltip "Sắp có". Vẽ cho ba loại: nút icon (trong ô nhập),
   mục trong menu (có icon + chữ), nút chữ. Đặt cạnh nút "đang tắt vì điều kiện" (ví dụ nút Gửi
   khi ô nhập rỗng) và nói rõ hai thứ đó nên trông giống hay khác nhau, vì sao.

3. LUẬT CON TRỎ — viết trong @layer base của theme.css:
   cursor: pointer cho button, a[href], [role=button], [role=menuitem], [role=tab],
   [role=option], summary, và label bọc checkbox/radio;
   cursor: not-allowed cho :disabled và [aria-disabled="true"].

4. ĐƯỜNG KẺ NGĂN MỤC TRONG MENU (menu tài khoản, Model Picker). Nếu --color-border hiện có
   đủ dùng thì nói vậy; nếu không, thêm một token riêng và in tương phản của nó trên
   --color-surface-panel.

Xuất: phần theme.css BỔ SUNG (đúng khuôn: thêm vào @theme, thêm vào [data-theme="dark"],
thêm vào @layer base) và bảng tương phản bổ sung. Không đụng tới biến nào đã có.
```

### 5.2 Nhìn gì để biết đạt

- [ ] Đủ 8 màu avatar + `--color-avatar-foreground`, có mặt ở **cả hai** khối sáng/tối
- [ ] Bảng tương phản 16 ô, mọi ô ≥ 4.5:1
- [ ] Không màu avatar nào trông gần đỏ son (`--color-accent`) hay đỏ thẫm (`--color-danger`)
- [ ] Nút chờ của ba loại đều có tooltip "Sắp có", đều có con trỏ not-allowed
- [ ] `@layer base` có đúng hai luật con trỏ
- [ ] **Đếm lại các biến cũ:** không biến nào đổi tên hay đổi giá trị (so với `design/theme.css` bạn đã dán)

### 5.3 Giao gì

- Ghi đè `design/theme.css` bằng bản v2 đầy đủ, và `design/contrast.md` bằng bảng đã bổ sung. Bản v1 vẫn còn
  trong lịch sử git (mốc ghi ở T-S.0).
- Ghi link vào `design/README.md`, hàng T-HD1-v2.

---

## 6. T-HD2-v2 — Khung chính

**Làm khi:** sau T-HD1-v2. **Chặn:** T-S.10, T-S.12, T-S.13 — bản vẽ nặng nhất của phase.
**Mở:** file `Scarlet Khung chính.dc.html`, tạo `Scarlet Khung chính v2.dc.html`.

### 6.1 Dán gì vào

Bản giao kèo §4.2, rồi:

```text
Đây là bản v2 của "Scarlet Khung chính". Mở file v1 làm nền, tạo file mới
"Scarlet Khung chính v2". Giữ mọi con số của v1 (bề rộng sidebar, header 56 px, bề rộng tối đa
của cột chat, breakpoint 1024 px, gutter) trừ chỗ tôi nói đổi.

MƯỜI THAY ĐỔI:

1. MÀN NHÁP — lúc mở app hoặc bấm "Hội thoại mới": chưa có tin nhắn nào. Ô nhập nằm GIỮA
   vùng chat (giữa cả ngang lẫn dọc), phía trên có một câu chào ngắn.
2. SAU CÂU ĐẦU TIÊN: ô nhập nằm ở đáy vùng chat như v1. Vẽ cả hai vị trí; chuyển động giữa
   hai vị trí làm ở bản "Chuyển động v2", ở đây chỉ cần hai trạng thái đầu và cuối.
3. Ô NHẬP LÀ MỘT KHỐI ĐỨNG RIÊNG: bỏ dải nền full-width và đường viền trên đang bao quanh nó.
   Ô nhập (textarea + nút Gửi) là một khối bo góc nằm thẳng trên nền vùng chat.
   Vẽ trạng thái focus: viền ô nhập hiện rõ.
4. BÊN DƯỚI Ô NHẬP:
   - bỏ dòng "Enter để gửi · Shift+Enter để xuống dòng";
   - bỏ bộ đếm "0/24000"; chỉ khi gõ VƯỢT trần ký tự mới hiện một dòng báo nhỏ — vẽ trạng thái đó;
   - góc dưới bên phải: tên model đang dùng, chữ trơn, KHÔNG khung, bấm vào mở Model Picker
     (picker vẽ ở bản "Model Picker v2").
5. BÊN TRÊN Ô NHẬP — dòng cảnh báo hạn mức: MỘT hàng, nhỏ, chỉ hiện khi hạn mức còn ≤ 20%.
   Ví dụ: "Hạn mức 5 giờ còn 14%" + link "Xem mức sử dụng" (sang trang Cài đặt).
   Vẽ thêm trạng thái HẾT hạn mức: báo đã hết, nói thời điểm hoàn lại chính xác
   ("Hoàn lại lúc 15:42"), nút Gửi bị khoá.
   Hai thanh hạn mức đầy đủ KHÔNG còn ở màn chat — chúng sang trang Cài đặt.
6. NÚT CHỜ TRONG Ô NHẬP (tính năng sắp có — trạng thái "nút chờ" của Design System v2):
   đính kèm ảnh/tệp · công tắc "Tìm web" · micro (nhập bằng giọng nói) · chọn skill.
   Vẽ thêm, không cần bấm được:
   - khay xem trước tệp đính kèm phía trên ô nhập: ảnh thumbnail và chip PDF (tên + dung lượng),
     mỗi cái có nút xoá;
   - trạng thái của nút đính kèm khi model đang chọn không đọc được ảnh: mờ + tooltip
     "Model này không đọc được ảnh".
7. BỎ DẢI TRẠNG THÁI phía trên vùng chat (mã hội thoại dạng b463bb6e-…, "đang nhận chữ",
   "in=… out=…"). Chỉ giữ một thông báo nhỏ khi mất kết nối: "Mất kết nối, đang nối lại…".
8. HEADER: bỏ email và nút "Đăng xuất". Còn: nút mở/đóng sidebar, tên app, lối vào "Quản trị"
   (chỉ admin thấy), công tắc sáng/tối, và một nút chờ "Mở panel artifact" (chỉ nút — panel
   chưa vẽ ở vòng này).
9. SIDEBAR:
   - nhóm hội thoại theo ngày hoạt động gần nhất, mới nhất ở trên: "Đã ghim" (đầu, luôn đầy đủ)
     · "Hôm nay" · "Hôm qua" · rồi ngày viết thẳng "21/9/2026", "20/9/2026"…;
   - BỎ dòng "Ghim nổi lên đầu trong phần đã tải; hội thoại ghim ở trang sau chỉ hiện sau khi
     bấm Tải thêm";
   - hàng hội thoại vừa tạo: tiêu đề hiện dần từng mảnh — vẽ ba khung liên tiếp
     (trống → "Cách đọc hạn" → "Cách đọc hạn mức từ Redis"), và trạng thái
     "Hội thoại chưa đặt tên" khi không đặt được tên;
   - menu của hàng hội thoại (đổi tên / ghim / xoá) thêm hai nút chờ: "Chia sẻ", "Xuất".
10. KHỐI TÀI KHOẢN Ở CHÂN SIDEBAR: avatar tròn (một chữ cái, màu --color-avatar-*) · tên hiển thị
    · tier (ví dụ "Miễn phí"). Đây là gợi ý bố cục, hãy thiết kế cho đẹp chứ không cần giữ đúng
    thứ tự tôi viết. Tên dài phải bị cắt; tên trống thì hiện nguyên email.
    Bấm vào khối mở menu, ĐÚNG thứ tự này:
        [icon] Cài đặt
        [icon] Mức sử dụng
        [icon] Ngôn ngữ        (nút chờ)
        [icon] Trợ giúp        (nút chờ)
        ─────────────
        [icon] Nâng cấp gói    (nút chờ)
        ─────────────
        [icon] Đăng xuất
    Icon lấy từ Lucide (nét, 24×24) — đề xuất tên icon cho từng mục. Trên desktop menu mở LÊN từ
    khối tài khoản; ở 375 px chọn sheet từ đáy hay popover, và nói lý do.

ARTBOARD CẦN CÓ:
  A. Desktop 1440×900 — màn nháp, sidebar mở, đủ bốn nhóm: Đã ghim · Hôm nay · Hôm qua · 21/9/2026
  B. Desktop 1440×900 — đang trong hội thoại, ô nhập ở đáy, dòng cảnh báo hạn mức đang hiện
  C. Desktop — sidebar đóng
  D. Desktop — menu tài khoản đang mở
  E. Mobile 375×812 — màn nháp
  F. Mobile 375×812 — drawer mở, thấy khối tài khoản ở chân
  G. Ô nhập, năm trạng thái: thường · focus · vượt trần ký tự · sắp hết hạn mức · hết hạn mức
  H. Hàng hội thoại: thường · đang chọn · đang hiện tên · chưa đặt tên · đã ghim · menu đang mở

Cho tôi CON SỐ, không chỉ hình: vị trí dọc của ô nhập ở màn nháp, bề rộng tối đa của ô nhập,
khoảng cách từ ô nhập tới đáy ở trạng thái thường, chiều cao khối tài khoản.
```

### 6.2 Nhìn gì để biết đạt

- [ ] Có đủ tám artboard A–H, xem được ở **cả hai** theme
- [ ] Màn nháp (A, E): ô nhập nằm giữa; trạng thái trong hội thoại (B): ô nhập ở đáy, **không** còn dải nền
      full-width nào bao quanh
- [ ] Không còn dòng "Enter để gửi…", không còn bộ đếm `0/24000` ở trạng thái thường
- [ ] Tên model dưới ô nhập là chữ trơn, không khung
- [ ] Dòng cảnh báo hạn mức đúng **một hàng**, có link; trạng thái hết hạn mức có **giờ** hoàn lại
- [ ] Header không còn email, không còn "Đăng xuất"
- [ ] Sidebar có bốn nhóm, không còn dòng ghi chú về ghim
- [ ] Menu tài khoản đúng **bảy mục, đúng thứ tự, hai đường kẻ**, ba mục chờ có tooltip "Sắp có"
- [ ] Không chữ "9Router" / "Sub2API" nào trên màn hình
- [ ] 375 px: mọi nút ≥ 44 px, không tràn ngang; drawer có khối tài khoản ở chân

### 6.3 Giao gì

Ghi link vào `design/README.md`, hàng T-HD2-v2. Ba task dùng bản này: T-S.10, T-S.12, T-S.13.

---

## 7. T-HD9 — Trang Cài đặt

**Làm khi:** sau T-HD1-v2. **Chặn:** T-S.11.
**Mở:** project Claude Design, tạo file mới `Scarlet Cài đặt.dc.html`.

### 7.1 Dán gì vào

Bản giao kèo §4.2, rồi:

```text
Vẽ trang Cài đặt của Scarlet. Hôm nay nó là một trang dài không có bản vẽ; bản mới chia TAB,
mỗi tab một đường dẫn riêng (menu tài khoản trỏ thẳng vào tab "Mức sử dụng"):

  Tài khoản · Giao diện · Model · Khoá API · Mức sử dụng

TÀI KHOẢN
  - Avatar tròn (một chữ cái đầu của tên hiển thị) + bảng chọn màu 8 ô (--color-avatar-1…8).
  - Nút "Tải ảnh lên" — NÚT CHỜ.
  - Ô "Tên hiển thị"; để trống thì nơi khác hiện nguyên email. Có giới hạn độ dài.
  - Email (chỉ đọc) · tier của tài khoản (ví dụ "Miễn phí").
  - Nút "Đăng xuất" ở cuối tab.
GIAO DIỆN
  - Theo hệ thống / Sáng / Tối.
MODEL
  - Model mặc định của tài khoản: danh sách chọn, hiện tên model + tên hãng; model đang không
    dùng được thì xám và không chọn được.
KHOÁ API (khoá riêng của người dùng)
  - Danh sách provider nhận khoá riêng. Mỗi hàng: "sk-...4f2a" (chỉ 4 ký tự cuối) + thời điểm thêm
    + nút Xoá. Ô thêm khoá. Không bao giờ hiện lại khoá đầy đủ.
MỨC SỬ DỤNG
  - Hai thanh hạn mức "5 giờ" và "7 ngày". Ba mức màu có sẵn trong hệ: bình thường / còn ≤ 20% /
    đã hết. Luôn kèm phần trăm còn lại (màu một mình không phải thông tin).
  - Thời điểm hoàn lại chính xác của từng cửa sổ.
  - Ghi chú: "Khi hết hạn mức, bạn vẫn gửi được bằng khoá API riêng."
  - Thanh sẽ chạy từ 0 tới giá trị thật khi mở tab lần đầu (chuyển động làm ở bản
    "Chuyển động v2") — ở đây vẽ trạng thái cuối.

Desktop: cột tab bên trái, nội dung bên phải. 375 px: chọn một cách (tab cuộn ngang ở đầu, hoặc
danh sách tab → màn con có nút quay lại) và nói lý do.
Mỗi thay đổi có nút Lưu và thông báo "Đã lưu". Thay đổi hạn mức do quản trị viên làm có hiệu lực
trong vòng 60 giây — đừng viết chữ "đã áp dụng" ở đâu cả.

Artboard: desktop mỗi tab một artboard (5), mobile 375 px cho tab Tài khoản và tab Mức sử dụng,
cả hai theme.
```

### 7.2 Nhìn gì để biết đạt

- [ ] Năm tab, đúng thứ tự
- [ ] Tab Tài khoản có đủ: avatar + 8 màu, "Tải ảnh lên" là nút chờ, tên hiển thị, email, tier, Đăng xuất
- [ ] Tab Khoá API không có chỗ nào hiện được khoá đầy đủ
- [ ] Tab Mức sử dụng có **phần trăm** cạnh mỗi thanh, và có **giờ** hoàn lại
- [ ] Không có chữ "đã áp dụng"
- [ ] 375 px không tràn ngang

### 7.3 Giao gì

Ghi link vào `design/README.md`, hàng T-HD9. Task dùng bản này: T-S.11.

---

## 8. T-HD8 — Sáu màn xác thực

**Làm khi:** sau T-HD1-v2. **Chặn:** T-S.16.
**Mở:** project Claude Design, tạo file mới `Scarlet Xác thực.dc.html`.

### 8.1 Dán gì vào

Bản giao kèo §4.2, dán thêm các khoá `auth.*` trong `frontend/src/locales/vi.json` (để bản vẽ dùng đúng chữ
thật), rồi:

```text
Vẽ các màn xác thực của Scarlet, dùng CHUNG một bố cục (một khung, nhiều nội dung). Đây là màn
đầu tiên người dùng thấy; giữ tinh thần của hệ: nền trung tính, đỏ son chỉ cho hành động chính.

1. /dang-nhap — email, mật khẩu, "Quên mật khẩu?", nút "Đăng nhập", link "Đăng ký".
   Lỗi sai thông tin: MỘT câu cho cả hai trường hợp ("Email hoặc mật khẩu không đúng") — không
   được nói cái nào sai. Tài khoản bị khoá: "Tài khoản này không đăng nhập được. Liên hệ quản trị viên."
2. /dang-ky — email, mật khẩu, widget Cloudflare Turnstile, nút "Đăng ký". Sau khi gửi: MỘT màn duy
   nhất "Kiểm tra hộp thư của bạn…" — kể cả khi email ĐÃ tồn tại (không được lộ email nào đã đăng ký).
3. /quen-mat-khau — nhập email → màn "Nếu email này có tài khoản, thư đặt lại đã được gửi."
4. /dat-lai-mat-khau — mật khẩu mới + nhập lại. Xong: "Mọi phiên đăng nhập cũ đã bị thu hồi."
5. /verify-email — ba trạng thái: đang xác thực · thành công (tự chuyển sang màn chờ duyệt) · link
   hết hạn (nút "Gửi lại thư"). Nút gửi lại giới hạn 3 lần mỗi giờ — vẽ cả trạng thái bị từ chối vì
   quá giới hạn, nói rõ khi nào thử lại được.
6. /cho-duyet — "Tài khoản đang chờ quản trị viên duyệt."
+ Màn tài khoản bị khoá, cùng khung.

RÀNG BUỘC RIÊNG:
  - Turnstile là loại "invisible": trước khi hiện huy hiệu nó chiếm một khoảng khoảng 336×71 px.
    Chừa đúng chỗ ấy; bố cục không được nhảy khi huy hiệu hiện.
  - Không viết cứng số ký tự tối thiểu của mật khẩu vào giao diện (con số đến từ máy chủ).
  - 375 px: không cuộn ngang; khi bàn phím ảo mở, nút chính vẫn thấy được.
  - Có trạng thái đang gửi (nút bị khoá + "Đang xử lý…") cho mọi form.
```

### 8.2 Nhìn gì để biết đạt

- [ ] Một bố cục chung cho cả bảy màn
- [ ] Lỗi đăng nhập **không** nói trường nào sai
- [ ] Đăng ký với email đã có ⇒ **cùng** màn "Kiểm tra hộp thư"
- [ ] Turnstile có chỗ 336×71 px cố định
- [ ] Không có con số "tối thiểu 8 ký tự" viết cứng
- [ ] 375 px, cả hai theme

### 8.3 Giao gì

Ghi link vào `design/README.md`, hàng T-HD8. Task dùng bản này: T-S.16.

---

## 9. T-HD3-v2 — Bong bóng tin nhắn

**Làm khi:** sau **T-S.3** — cần danh sách mức suy luận thật. **Chặn:** T-S.15.
**Mở:** `Scarlet Bong bóng tin nhắn.dc.html`, tạo `Scarlet Bong bóng tin nhắn v2.dc.html`.

### 9.1 Dán gì vào

Bản giao kèo §4.2, rồi:

```text
Đây là bản v2 của "Scarlet Bong bóng tin nhắn". Mở file v1 làm nền, tạo file mới
"Scarlet Bong bóng tin nhắn v2". Giữ nguyên: bốn trạng thái của câu trả lời (đang chờ · đang
stream · xong · lỗi), khối Suy luận gập/mở, điều hướng nhánh ‹ n/m ›, khối code, bong bóng
người dùng và trạng thái sửa tại chỗ. Ràng buộc hiệu năng của v1 vẫn giữ: không hoạt ảnh trên
phần tử chứa chữ đang chảy.

1. MỘT NÚT THỬ LẠI THAY CHO HAI: bỏ nút "Đổi model & thử lại". Nút "Thử lại" dùng model và mức
   suy luận đang chọn trên Model Picker; tooltip nói đúng điều đó: "Tạo lại bằng model đang chọn".
   Hàng nút mới: Sao chép · Thích · Không thích · Thử lại · Đọc to (NÚT CHỜ).
   Ở 375 px mỗi nút vẫn ≥ 44 px — không đủ chỗ thì gập bớt vào "…" như v1.

2. CHIP DƯỚI CÂU TRẢ LỜI: "<tên model> · <mức suy luận>", ví dụ "DeepSeek Flash · High",
   "Claude Haiku 4.5 · Off". Model không có mức suy luận thì chỉ tên model. Không bao giờ hiện
   tên đường trung gian.

3. KHỐI "SUY LUẬN" KHÔNG HIỆN khi câu trả lời không có suy luận — vẽ một câu trả lời như vậy
   (không có khối rỗng nào).

4. THÀNH PHẦN CHO TÍNH NĂNG SẮP CÓ — vẽ đủ, hôm nay chúng chưa xuất hiện:
   - chip trạng thái công cụ "Đang tìm web…" (có chỉ báo đang chạy), rồi hàng chip nguồn:
     favicon + tên trang, từ 3 tới 8 chip, xuống dòng được, tên trang dài bị cắt;
   - thẻ artifact nằm trong bong bóng: icon loại + tiêu đề + nhãn phiên bản "v3" + nút "Mở"
     (NÚT CHỜ). Chỉ vẽ thẻ — panel artifact chưa vẽ ở vòng này;
   - chip "Đang chạy code…";
   - trong bong bóng NGƯỜI DÙNG: ảnh đính kèm (thumbnail) và tệp (chip tên tệp + dung lượng).

Mức suy luận thật của từng model: <dán bảng "reasoning" trong Ghi nhận của T-S.3>.
```

> Ở dòng cuối, mở `docs/tasks.md` → T-S.3 → "Ghi nhận" và dán bảng mức của từng model. Không có bảng ấy thì
> dùng bảng ở §10.1 bên dưới, và ghi chú lại để T-S.18 kiểm.

### 9.2 Nhìn gì để biết đạt

- [ ] Hàng nút có **năm** nút, không còn "Đổi model & thử lại"
- [ ] Chip "model · mức" có mặt, nhãn mức tiếng Anh
- [ ] Có một câu trả lời **không** có khối Suy luận
- [ ] Đủ bốn thành phần chờ: chip tìm web + chip nguồn, thẻ artifact, chip chạy code, ảnh/tệp của người dùng
- [ ] 375 px: hàng nút ≥ 44 px mỗi nút, không tràn

### 9.3 Giao gì

Ghi link vào `design/README.md`, hàng T-HD3-v2. Task dùng bản này: T-S.15.

---

## 10. T-HD4-v2 — Model Picker

**Làm khi:** sau **T-S.3** — cần dữ liệu catalog v4. **Chặn:** T-S.14.
**Mở:** `Scarlet Model Picker.dc.html`, tạo `Scarlet Model Picker v2.dc.html`.

### 10.1 Dữ liệu thật mà picker phải hiện

Bảng dưới đây là **dự kiến** từ tra cứu ngày 2026-09-23. **Trước khi dán, mở T-S.3 → "Ghi nhận"** và sửa theo
kết quả đo thật (mức nào T-S.2 loại thì bỏ đi). Mức in đậm là mặc định.

| Tên hiển thị | Hãng | Capability | Badge | Mức suy luận | Giá / 1M token vào · ra |
|---|---|---|---|---|---|
| DeepSeek Flash | DeepSeek | tools, vision, reasoning | Mặc định · Rẻ | Off · Low · **High** · Max | $0.30 · $1.20 — thấp điểm $0.15 · $0.60 |
| Claude Haiku 4.5 | Anthropic | tools, vision | — | **Off** · Low · Medium · High | $1.00 · $5.00 |
| Gemini 3.8 Flash | Google AI | tools | — | Low · **Medium** · High | không tính phí theo token |
| Grok 4.6 | xAI | — | — | Low · Medium · **High** · Extra High | không tính phí theo token |
| Qwen2.5 0.5B | Alibaba Qwen | — | Self-host | *(không có)* | không tính phí theo token |

Gemini 3.8 Flash vẽ ở trạng thái **không dùng được**, lý do: *"Model này tạm thời không dùng được. Hãy thử lại
sau ít phút."* — câu này không nhắc tên đường trung gian nào.

### 10.2 Dán gì vào

Bản giao kèo §4.2, bảng §10.1 (đã sửa theo T-S.3), rồi:

```text
Đây là bản v2 của "Scarlet Model Picker". Mở file v1 làm nền, tạo file mới
"Scarlet Model Picker v2". Dùng đúng bảng dữ liệu tôi vừa dán — không bịa model, không bịa giá.

NÚT MỞ PICKER: chỉ là tên model đang dùng, chữ trơn, không khung, nằm dưới ô nhập ở góc phải
(một mũi tên nhỏ nếu cần để người dùng biết bấm được). Vẽ: thường · hover · focus · đang mở.

BẢNG CHỌN — bốn khối, ngăn bằng đường kẻ, ĐÚNG thứ tự:

  ① MODEL HIỆN TẠI — tên hiển thị, hãng, badge, các capability, và dấu cho biết model này đến
     từ tầng mặc định nào (mặc định hội thoại / mặc định tài khoản / mặc định catalog; thứ tự
     thắng: hội thoại › tài khoản › catalog). Giữ nguyên mọi mô tả của v1.
  ─────
  ② Thinking Effort ›  — mở menu con liệt kê các mức của model hiện tại, dấu ✓ ở mức đang chọn.
     Mức viết bằng tiếng Anh. Model không có tuỳ chọn suy luận: hàng này mờ + tooltip
     "Model này không có tuỳ chọn suy luận" — hàng vẫn ở đó, không ẩn đi.
  ─────
  ③ More models ›  — mở danh sách đầy đủ (như danh sách của v1): mỗi hàng tên, hãng, badge,
     capability; model không dùng được thì xám, không chọn được, tooltip lý do (xuống dòng được).
     Đầu danh sách: "Trạng thái kiểm lúc 14:32" + nút kiểm lại (giữ từ v1).
  ─────
  ④ GIÁ MODEL HIỆN TẠI — ví dụ "Vào $0.30 · Ra $1.20 / 1M token"; nếu model có giờ thấp điểm, thêm
     "Giờ thấp điểm: Vào $0.15 · Ra $0.60" và cho biết khung nào đang áp dụng. Model không tính theo
     token: "Không tính phí theo token". Giá ước lượng: thêm chữ "ước lượng". Một dòng phụ:
     "Suy luận được tính như token ra."

375 px: picker là sheet từ đáy; "Thinking Effort ›" và "More models ›" mở thành màn trượt có nút
quay lại ở đầu. Vẽ màn chính và cả hai màn con.

CHỪA CHỖ (không vẽ nội dung): cảnh báo "model này không đọc được ảnh mà hội thoại đã có ảnh".

Artboard: desktop picker đóng · mở · menu con Thinking Effort · menu con More models; mobile ba màn;
một artboard với model KHÔNG có mức suy luận (Qwen2.5 0.5B) đang được chọn; cả hai theme.
```

### 10.3 Nhìn gì để biết đạt

- [ ] Nút mở không có khung
- [ ] Bốn khối, đúng thứ tự, có đường kẻ
- [ ] Nhãn mức tiếng Anh, khớp bảng đã sửa theo T-S.3
- [ ] Qwen: hàng Thinking Effort **mờ nhưng vẫn còn**
- [ ] Giá DeepSeek có cả hai khung; giá ba model còn lại ghi "Không tính phí theo token"
- [ ] Không chữ "9Router" / "Sub2API" nào, kể cả trong tooltip lý do
- [ ] Mobile: có nút quay lại ở cả hai màn con

### 10.4 Giao gì

Ghi link vào `design/README.md`, hàng T-HD4-v2. Task dùng bản này: T-S.14.

---

## 11. T-HD7-v2 — Quản trị

**Làm khi:** sau T-HD1-v2. **Chặn:** T-S.17.
**Mở:** `Scarlet Quản trị.dc.html`, tạo `Scarlet Quản trị v2.dc.html`.

### 11.1 Dán gì vào

Bản giao kèo §4.2, rồi:

```text
Đây là bản v2 của "Scarlet Quản trị". Mở file v1 làm nền, tạo file mới "Scarlet Quản trị v2".
Giữ nguyên sáu màn; đổi hai chỗ và sửa năm chỗ lệch.

HAI CHỖ ĐỔI:

1. MÀN CHI PHÍ — thêm khoản "Đặt tên hội thoại": chi phí của các lượt tự đặt tên hội thoại. Khoản
   này luôn trả bằng khoá hệ thống và không trừ vào hạn mức của người dùng. Thêm một cột trong bảng
   theo người dùng và bảng theo model, và một thẻ số tổng. Biểu đồ GIỮ đúng hai chuỗi metered /
   unmetered (hệ màu chỉ có hai màu biểu đồ). Tiền là chuỗi từ máy chủ: căn phải, tabular-nums,
   không có ô "tổng" nào phải cộng ở giao diện.

2. MÀN MODEL — mỗi hàng hiện hãng gốc VÀ đường đi thật, ví dụ "Google AI · qua 9Router",
   "xAI · qua Sub2API", "DeepSeek" (gọi thẳng, không có vế "qua"). Health thuộc về ĐƯỜNG ĐI: khi
   9Router tắt, hàng báo hỏng phải nói rõ đường đi hỏng, không phải Google. Chỉ màn quản trị được
   thấy tên đường đi.

NĂM CHỖ LỆCH của bản v1, đã ghi ở Backlog B-262 — chốt từng chỗ:
  (1) file tự ghi nhãn "T-HD6 · ADMIN PANEL" — đúng là T-HD7;
  (2) dialog "Hạn mức tháng (USD)" chỉ có một ô — hệ thống có HAI cửa sổ 5 giờ / 7 ngày;
  (3) không có màn/khối cho hạn mức theo tier — hiện nó nằm cuối màn Người dùng; vẽ chỗ chính thức;
  (4) thẻ provider vẽ độ trễ, và cột "Bật" cho từng model không có endpoint nào — bỏ cột "Bật";
  (5) màn Chi phí bỏ mất bộ lọc nguồn tiền và bảng "theo nguồn" — vẽ lại chúng.
Thêm: lối vào "Cài đặt" nay là khối tài khoản ở chân sidebar (bản "Khung chính v2"), không còn ở
header — trang Quản trị không cần lối riêng.
```

### 11.2 Nhìn gì để biết đạt

- [ ] Màn Chi phí có cột + thẻ "Đặt tên hội thoại"; biểu đồ vẫn **hai** chuỗi
- [ ] Màn Model có dạng "Hãng · qua <đường đi>"
- [ ] Năm chỗ của B-262 đều đã xử lý (đối chiếu từng mục)
- [ ] Bảng số cuộn ngang **trong** khung ở 375 px (luật của v1)

### 11.3 Giao gì

Ghi link vào `design/README.md`, hàng T-HD7-v2. Task dùng bản này: T-S.17.

---

## 12. T-HD5-v2 — Chuyển động *(vẽ cuối cùng)*

**Làm khi:** sau T-HD2-v2, T-HD4-v2, T-HD9. **Chặn:** T-S.9.
**Mở:** `Scarlet Chuyển động.dc.html`, tạo `Scarlet Chuyển động v2.dc.html`.
**Đầu ra:** token + class `.motion-*` trong `theme.css`, cộng một đoạn TypeScript chứa hằng lò xo cho icon.

### 12.1 Dán gì vào

Bản giao kèo §4.2, nội dung `design/theme.css` hiện tại (đã là bản T-HD1-v2), rồi:

```text
Đây là bản v2 của "Scarlet Chuyển động". Mở file v1 làm nền, tạo file mới
"Scarlet Chuyển động v2". Giữ nguyên mọi token và class .motion-* của v1. THÊM cho bảy chuyển động:

1. Ô nhập trượt từ giữa màn xuống đáy sau câu đầu tiên của hội thoại (một lần mỗi hội thoại).
   Chỉ KHUNG ô nhập di chuyển (transform); không phần tử chứa chữ nào có hoạt ảnh.
2. Viền ô nhập hiện dần khi focus, mờ dần khi rời focus — thay cho việc bật tức thì.
3. Tiêu đề hội thoại hiện dần trong sidebar. Chữ đến theo 5–15 mảnh qua mạng. Hoạt ảnh ở mức
   con trỏ / đuôi chữ, KHÔNG ở từng ký tự; hàng không được đổi bề rộng khi chữ đến.
4. Thanh hạn mức chạy từ 0 tới giá trị thật khi mở tab "Mức sử dụng" (chỉ lần đầu trong mỗi lần
   đăng nhập — phần "khi nào chạy" là việc của code, bạn chỉ cần cho chuyển động).
5. Menu con trong Model Picker: desktop trượt ra bên cạnh; mobile trượt ngang như một màn con,
   có nút quay lại.
6. Menu tài khoản mở LÊN từ chân sidebar.
7. Icon biến hình (thư viện morphicons, mô hình lò xo). Cho tôi 2–3 cấu hình lò xo đặt tên theo
   vai trò — ví dụ "snappy" cho đổi trạng thái, "gentle" cho hover — dưới dạng
   { stiffness, damping }. Nói rõ chỗ nào dùng cấu hình nào: Gửi ↔ Dừng, mở/đóng sidebar,
   Sáng ↔ Tối, mũi tên › của menu con, hover trên từng mục của menu tài khoản.

HAI ĐIỀU BẮT BUỘC (giữ từ v1):
  - prefers-reduced-motion: reduce ⇒ TẮT HẲN cả bảy: ô nhập nhảy thẳng xuống đáy, viền hiện tức
    thì, tiêu đề hiện ngay, thanh hạn mức vẽ thẳng giá trị, menu hiện không trượt, icon đổi tức thì.
    Viết cho tôi khối @media ấy.
  - Component không chứa `transition:`, `animation:`, "150ms", `duration-[…]`. Giao token + class
    trong theme.css. Riêng lò xo của icon chạy bằng JavaScript: giao dưới dạng MỘT đoạn TypeScript
    export các hằng { stiffness, damping } — KHÔNG phải số mili-giây.
```

### 12.2 Nhìn gì để biết đạt

- [ ] Bảy chuyển động, mỗi cái có token + class riêng
- [ ] Khối `@media (prefers-reduced-motion: reduce)` có mặt và phủ **cả bảy**
- [ ] Không có con số ms nào nằm ngoài token
- [ ] Lò xo là một đoạn TypeScript chỉ gồm hằng số, đặt tên theo vai trò

### 12.3 Giao gì

- Ghi đè `design/theme.css` bằng bản có token chuyển động mới.
- Lưu đoạn TypeScript lò xo thành `design/motion-springs.ts`.
- Ghi link vào `design/README.md`, hàng T-HD5-v2. Task dùng bản này: T-S.9 (cùng T-HD1-v2).

---

## 13. Bảng nút chờ — bản nhanh cho người thiết kế

Mỗi nút chờ nằm trong bản v2 của vùng chứa nó. Bảng chuẩn (có cả task dựng và giá trị `data-planned`) là
`tasks.md` §7b.2.

| Vẽ ở | Nút / thành phần | Tính năng thật tới ở |
|---|---|---|
| T-HD2-v2 · ô nhập | Đính kèm ảnh/tệp · trạng thái "model không đọc được ảnh" · khay xem trước tệp | Phase 4 |
| T-HD2-v2 · ô nhập | Công tắc "Tìm web" | Phase 6 |
| T-HD2-v2 · ô nhập | Chọn skill | Phase 7 |
| T-HD2-v2 · ô nhập | Micro | Phase 8 (Firefox sẽ ẩn nút này) |
| T-HD2-v2 · header | Mở panel artifact | Phase 5 |
| T-HD2-v2 · menu hàng hội thoại | Chia sẻ · Xuất | Phase 8 |
| T-HD2-v2 · menu tài khoản | Ngôn ngữ · Trợ giúp · Nâng cấp gói | chưa có phase nào (Backlog B-264) |
| T-HD3-v2 · bong bóng | Đọc to | Phase 8 |
| T-HD3-v2 · bong bóng | Chip tìm web + chip nguồn · thẻ artifact · chip chạy code · ảnh/tệp của người dùng | Phase 6 · 5 · 7 · 4 |
| T-HD4-v2 · picker | Chỗ chừa cho cảnh báo vision | Phase 4 |
| T-HD9 · Cài đặt | Tải ảnh avatar lên | sau Phase 4 (Backlog B-265) |

Ba thứ **không** làm nút chờ (bạn đã chọn): công tắc bật/tắt model ở quản trị, "Chi tiêu của tôi", link trang
quyền riêng tư.

---

## 14. Danh sách kiểm — chạy sau MỖI bản vẽ, trước khi ghi link

- [ ] Mọi màu trong mã là `var(--…)` — không có `#`, `rgb(`, `hsl(`, `oklch(`
- [ ] Không có biến thể `dark:` trong mã component
- [ ] **Không biến cũ nào** trong `theme.css` bị đổi tên hay đổi giá trị
- [ ] Không có `transition:`, `animation:`, `150ms`, `duration-[…]` trong mã component
- [ ] Mọi chuỗi hiển thị tách riêng, không câu nào có biến ở giữa
- [ ] 375 px: không cuộn ngang, mọi vùng chạm ≥ 44 px
- [ ] Cả hai theme, không chỉ theme sáng
- [ ] Mọi thành phần tương tác có focus nhìn thấy được
- [ ] Trạng thái xấu đã vẽ: rỗng, đang tải, lỗi, bị khoá, chữ quá dài
- [ ] Nút chờ: mờ, con trỏ not-allowed, tooltip "Sắp có", **không** ghi phase
- [ ] Không chữ "9Router" / "Sub2API" ở màn người dùng
- [ ] Mức suy luận viết tiếng Anh
- [ ] Icon là Lucide loại nét
- [ ] Đã có **con số** (bề rộng, chiều cao, vị trí), không chỉ hình
- [ ] File v1 **không** bị sửa; file v2 có đuôi ` v2`
- [ ] Đã ghi link + ngày chốt vào `design/README.md`, mục v2

---

## 15. Khi bản vẽ và kế hoạch mâu thuẫn

Đừng tự hoà giải, và đừng để agent hoà giải (luật A10 của `CLAUDE.md`). Những chỗ có thể va, đã biết trước:

| Chỗ | Va chạm có thể gặp | Ai quyết |
|---|---|---|
| Model Picker | Bản vẽ có một mức suy luận mà T-S.2 đã loại | **T-S.2 thắng** — mức không đo được thì không có trong catalog, nên không vẽ |
| Màn chat | Bản vẽ đặt lại thanh quota đầy đủ ở màn chat | **Bạn** — NQ-114 đã chốt chỉ còn một dòng cảnh báo |
| Menu tài khoản | Bản vẽ đổi thứ tự bảy mục | **Bạn** — thứ tự ở KE-HOACH §24.2b·S10 là thứ tự bạn đã giao |
| Chuyển động | Bản vẽ đặt hoạt ảnh lên chữ đang chảy | **Không ai** — cấm (T-3.9 ①, C1). Yêu cầu vẽ lại |
| Quản trị | Bản vẽ giữ cột "Bật" cho từng model | **Bạn** — không có endpoint nào đổi `enabled` (B-258); bạn đã chọn không làm nút chờ cho nó |

Quyết xong thì bảo agent ghi một dòng vào **Nhật ký quyết định** của `tasks.md` §16 (số NQ tiếp theo còn trống
là **NQ-122**).

---

## 16. Xong phase

Phase S xong khi T-S.19 ✅ và mọi dòng PS của KE-HOACH §24.3 đạt. Khi ấy:

- `design/README.md` mục v2 có đủ tám link, đủ ngày chốt, đủ cột "Đã đối chiếu".
- Mở `tasks.md` §7b.2 và đếm: số `data-planned` trong code khớp số hàng "mount".
- Bắt đầu Phase 4 như kế hoạch cũ. Agent P4 tìm chỗ gắn nút bằng `grep -rn 'data-planned="T-4.' frontend/src`.
