# T-HD12 — Chia sẻ, trang công khai, giọng nói, bộ icon PWA

Prompt cho Claude Design, viết ở T-8.1 (2026-10-13) theo khuôn `design/T-HD11-prompt.md` (Q-P8-1, NQ-149).
Chỗ gắn của từng nút lấy từ **code** đang chạy (`Sidebar.tsx`, `AnswerActions.tsx`, `Composer.tsx`, token
`theme.css`); JSON ở ② là **response thật** của `GET /api/v1/s/{token}` trên stack (`https://localhost`,
2026-10-13), chỉ rút gọn phần chữ ký của URL.

## 1. Làm khi / Chặn / Mở / Đầu ra

- **Làm khi:** sau T-8.1 (`POST /conversations/{id}/share`, `GET /api/v1/s/{token}` đã chạy trên stack). Vẽ được
  ngay — song song với T-8.5 → T-8.7.
- **Chặn:** T-8.2 (hộp thoại + trang công khai), T-8.3 (nút "Chat tiếp"), T-8.4 (mic, Đọc to), T-8.8 (bộ icon PWA,
  `theme_color`). **Không** chặn T-8.5 / T-8.6 / T-8.7 — menu con "Xuất ›" chỉ đối chiếu.
- **Mở:** cùng project Claude Design của bản v3. Tạo **file mới** `Scarlet Chia sẻ & giọng nói.dc.html` dựa trên
  `Scarlet Khung chính v3.dc.html` (sidebar, ô nhập) + `Scarlet Tin nhắn v3.dc.html` (bong bóng, hàng nút dưới
  câu trả lời). **Không sửa** hai file v3 (tutorial §4.1).
- **Đầu ra:** mã component (`.tsx`) + phần `theme.css` bổ sung nếu có (chỉ THÊM biến, không đổi biến cũ) + bộ icon
  (PNG đúng kích thước, SVG nguồn) + hai cặp màu `theme_color` / `background_color`.

## 2. Dán gì vào

Dán theo thứ tự, trong **một** cuộc trò chuyện:

1. Bản giao kèo §4.2 của `docs/standardize-tutorial.md` (mười bốn ràng buộc) — nguyên văn.
2. Toàn bộ `design/theme.css` hiện tại.
3. Prompt riêng dưới đây.

```text
Đây là bản vẽ MỚI "Scarlet Chia sẻ & giọng nói" — bốn mảnh nhỏ, một file: ① hộp thoại Chia sẻ,
② trang công khai người lạ mở từ link chia sẻ, ③ mic + Đọc to, ④ bộ icon cài app (PWA). Mở
"Scarlet Khung chính v3" và "Scarlet Tin nhắn v3" làm nền; tạo file mới, không sửa hai file đó.

① HỘP THOẠI CHIA SẺ — MỞ TỪ MENU HÀNG HỘI THOẠI (ĐÃ CÓ)

  Menu "…" của một hàng trong sidebar (DropdownMenu, rộng w-50, nền surface-panel, shadow-popover),
  trên → dưới: [Đổi tên ✎] [Ghim 📌] [Chia sẻ ↗ — Lucide share-2] [Xuất ⬇] ── [Xoá 🗑 — màu nguy hiểm].
  "Chia sẻ" hôm nay là mục "Sắp có" (mờ + tooltip). Giữ đúng chỗ, icon 18 px; bấm ⇒ hộp thoại.

  Điều phải hiểu trước khi vẽ (sản phẩm đã chốt — ADR-14, R15):
    - Chia sẻ = ẢNH CHỤP của nhánh đang xem TẠI LÚC BẤM. Chat tiếp sau đó KHÔNG hiện ra ở link.
    - Mỗi lần mở hộp thoại là một ảnh chụp MỚI, một link MỚI; link cũ vẫn sống với nội dung cũ.
    - Ai có link cũng xem được, không cần đăng nhập. KHÔNG thu hồi được link (v1 không có nút xoá link).
    - Server trả: 201 {"token": "j56J1I-pZJnwoISgv9JTiA",
                       "url": "https://localhost/s/j56J1I-pZJnwoISgv9JTiA"}
      URL thật dài ~45 ký tự trên localhost, sau này là https://<domain>/s/<22 ký tự>.

  Vẽ:
    - Đang tạo link (ngay khi mở — request chạy, thường < 1 s; có ảnh/tệp thì lâu hơn vài giây).
    - Có link: ô link chỉ đọc (cắt giữa hoặc cuộn ngang trong ô, KHÔNG làm vỡ bề rộng hộp thoại) +
      nút "Sao chép" ⇒ trạng thái "Đã chép" ~2 s. Hai câu bắt buộc, chữ do bạn trau chuốt:
        "Đây là ảnh chụp cuộc trò chuyện tại thời điểm này — tin nhắn sau đó sẽ không hiện ra."
        "Ai có link đều xem được và link không thu hồi được."
    - Lỗi theo mã, mỗi mã một câu + nút "Thử lại":
        409 GENERATION_IN_PROGRESS  — câu trả lời còn đang chạy; chia sẻ sau khi xong.
        422 CONVERSATION_EMPTY      — hội thoại chưa có tin nhắn.
        503 SHARE_STORAGE_UNAVAILABLE — không chép được ảnh/tệp, thử lại sau.
        khác / mất mạng             — câu chung.
    - Nút đóng 44 × 44; Esc đóng; mobile 375: hộp thoại thành sheet đáy hoặc toàn màn hình.

② TRANG CÔNG KHAI /s/{token} — NGƯỜI LẠ, KHÔNG ĐĂNG NHẬP

  Người xem có thể KHÔNG có tài khoản. Không sidebar, không ô nhập, không hàng nút dưới câu trả
  lời (không Thích / Thử lại / Đọc to), không Model Picker, không khối tài khoản. Chỉ đọc.

  Dữ liệu thật (GET /api/v1/s/{token}, 2026-10-13 — URL ký rút gọn):
    { "version": 1,
      "title": "Tạo file Word báo cáo DoD T-7.9",          ← có thể null (chưa đặt tên)
      "shared_at": "2026-10-13T16:46:13.269603+00:00",
      "messages": [
        { "role": "user", "content": "Tạo giúp mình file Word dod-t79.docx: …",
          "model_display_name": null, "created_at": "2026-10-13T12:43:24…",
          "attachments": [], "artifacts": [] },
        { "role": "assistant", "content": "Tạo file Word giúp bạn:File **dod-t79.docx** đã sẵn sàng…",
          "model_display_name": "Claude Haiku 4.5", "created_at": "…", "attachments": [],
          "artifacts": [ { "kind": "file", "title": "dod-t79.docx",
                           "key": "share/…/9d6c….docx", "url": "https://localhost/scarlet/share/…?X-Amz-…" } ] },
        { "role": "user", "content": "Ảnh này màu gì? Trả lời đúng một câu ngắn.",
          "model_display_name": null, "created_at": "…", "artifacts": [],
          "attachments": [ { "kind": "image", "name": "dod-t81.png", "width": 64, "height": 48,
                             "key": "share/…/5806….png", "url": "https://localhost/scarlet/share/…?X-Amz-…" } ] },
        { "role": "assistant", "content": "Ảnh màu đỏ.", "model_display_name": "Claude Haiku 4.5", … } ] }

  Luật của dữ liệu:
    content là markdown (cùng renderer đã sanitize của màn chat): đoạn, danh sách, bảng, khối mã.
    attachments: kind "image" (có url, width, height — hiện ảnh như trong bong bóng chat) hoặc
      kind "document" {name, mime_type} — CHỈ tên: chip tên tệp, KHÔNG link, không tải được.
    artifacts: kind "file" {title, url} ⇒ thẻ tệp + nút Tải (lối thẻ file của T-HD6);
      kind html / react / svg / mermaid / code / markdown {title, language, content} ⇒ thẻ +
      MÃ TĨNH (khối code) + nút Tải. KHÔNG chạy, KHÔNG iframe, KHÔNG xem trước — người lạ không
      chạy code model sinh (Q-P8-6). Một câu nhỏ giải thích là được.
    model_display_name: chip tên model dưới câu trả lời (lối chip "model · mức" của bong bóng v2,
      nhưng chỉ có tên); null ⇒ không chip.
    Không có: tên/email chủ, chi phí, mức suy luận, nhánh ‹ 2/3 ›, nút sửa.

  Vẽ:
    - Đầu trang: tiêu đề hội thoại (null ⇒ "Cuộc trò chuyện"), ngày chia sẻ, nhãn "Bản chia sẻ —
      chỉ đọc", logo/tên Scarlet nhỏ (dẫn về trang chủ).
    - Danh sách bong bóng đủ các loại trên (ảnh, chip tài liệu, thẻ file + Tải, thẻ artifact mã tĩnh,
      bảng rộng cuộn ngang trong vùng của nó, khối mã dài).
    - Nút "Chat tiếp" (T-8.3): đưa người xem vào app — chưa đăng nhập ⇒ sang Đăng nhập rồi quay lại
      tự tạo bản sao hội thoại của CHÍNH họ; đã đăng nhập ⇒ tạo luôn. Chỗ đặt (đầu trang / dính đáy /
      cuối danh sách) bạn chọn, ghi lý do. Trạng thái: thường · đang tạo bản sao · lỗi + Thử lại.
    - Đang nạp (skeleton) · "Link không tồn tại" (404 SHARE_NOT_FOUND — link sai hoặc đã gỡ; một màn,
      không phân biệt hai ca, có đường về trang chủ) · lỗi mạng + Thử lại.
    - Desktop 1440 (cột đọc rộng như màn chat, giữa) và mobile 375 × 812 — không cuộn ngang trang.

③ MIC VÀ ĐỌC TO (Web Speech API của trình duyệt — miễn phí, không lên server)

  Mic — ô nhập, hàng nút dưới (ĐÃ CÓ chỗ), trái → phải:
    [Đính kèm 📎] [Tìm web 🌐] [Chọn skill ⚡] ……… [Mic 🎤 — Lucide mic 20 px] [Gửi]
  Mic hôm nay là nút "Sắp có", vùng chạm 44 × 44. Vẽ: chờ · đang nghe (rõ ràng là ĐANG THU — người
    dùng phải biết mic mở) · chữ tạm (chữ đang nhận dạng hiện ngay trong ô nhập, kiểu khác chữ đã
    chốt) · lỗi (bị từ chối quyền mic / không nghe thấy gì / mất mạng — một câu ngắn).
    Bấm lần hai hoặc Esc ⇒ dừng; chữ đã chốt nằm lại trong ô, KHÔNG tự gửi.
    Firefox không có nhận dạng giọng nói ⇒ nút mic BIẾN MẤT hẳn (không mờ, không nút chết — ADR-13).

  Đọc to — hàng nút dưới câu trả lời (ĐÃ CÓ chỗ): [Copy] [👍] [👎] [Thử lại] [Đọc to 🔊 — Lucide
    volume-2 18 px]; dưới 640 px nó nằm trong menu "…". Vẽ: chờ · đang đọc (bấm lần nữa = dừng; chỉ
    một câu trả lời được đọc một lúc) · lỗi (trình duyệt không có giọng tiếng Việt / đọc hỏng).
    Firefox GIỮ Đọc to.

④ BỘ ICON CÀI APP (PWA)

  App chưa có logo/favicon nào. Vẽ một dấu nhận diện đơn giản cho Scarlet, xuất:
    icon 192 × 192 · icon 512 × 512 · icon 512 × 512 maskable (nội dung trong vùng an toàn — vòng
    tròn đường kính 80 %) · apple-touch-icon 180 × 180 (nền đặc, không trong suốt) · favicon (SVG
    + 32 × 32 PNG).
  Kèm theme_color và background_color cho theme sáng VÀ theme tối (màn khởi động khi mở app đã cài,
    thanh trạng thái điện thoại) — chọn từ token có sẵn của theme.css, ghi tên token.

⑤ ĐỐI CHIẾU (KHÔNG CHẶN) — MENU CON "XUẤT ›"

  T-8.7 làm trước bản vẽ này, theo đúng ngôn ngữ menu đang có: "Xuất ›" trong menu hàng mở menu con
  ba mục: Markdown (.md) · JSON — nhánh đang xem · JSON — cả cây. Nếu bạn thấy cần khác, vẽ một
  khung đối chiếu; không bắt buộc.

⑥ RÀNG BUỘC RIÊNG CỦA BẢN NÀY

  - Không vẽ lại thẻ artifact / thẻ file / bong bóng — dùng lại bản v3 + T-HD6; trang công khai chỉ
    bỏ bớt nút và thêm phần đầu trang + "Chat tiếp".
  - Không có ô mật khẩu, không ngày hết hạn, không nút "Thu hồi link" — v1 không có (R15).
  - Mọi chuỗi mới là khoá vi.json phẳng ("share.…", "voice.…", "publicShare.…"), không interpolation
    trừ ngày / số đếm.
  - Không đổi tên / đổi giá trị biến nào của theme.css; token mới chỉ THÊM, kèm giá trị cho cả theme tối.
  - Không chữ "9Router" / "Sub2API" ở bất cứ đâu. Không hiện id model nội bộ — chỉ model_display_name.

Artboard: desktop 1440 (menu hàng mở · hộp thoại đang tạo · có link · đã chép · ba lỗi) ; trang công
khai desktop 1440 (đủ loại nội dung · đang nạp · link không tồn tại) và 375 × 812 ; "Chat tiếp" ba
trạng thái ; ô nhập với mic bốn trạng thái + bản Firefox không mic ; hàng nút câu trả lời với Đọc to
ba trạng thái (desktop + menu "…" 375) ; bộ icon trên nền sáng và tối ; cả hai theme.
```

## 3. Nhìn gì để biết đạt

- [ ] ① Hộp thoại: đang tạo · có link + Sao chép/Đã chép · hai câu ADR-14 + R15 · ba lỗi theo mã + Thử lại · sheet 375
- [ ] ② Trang công khai: đầu trang (tiêu đề / null, ngày, "chỉ đọc") · ảnh · chip tài liệu không link · thẻ file + Tải ·
      artifact mã tĩnh, không xem trước · chip tên model · không nút nào của màn chat
- [ ] ② "Chat tiếp" ba trạng thái · đang nạp · "Link không tồn tại" · lỗi mạng · 1440 và 375 không cuộn ngang
- [ ] ③ Mic bốn trạng thái + bản Firefox **không có** nút mic; Đọc to ba trạng thái, cả trong menu "…" < 640
- [ ] ④ Năm icon đúng kích thước, maskable trong vùng an toàn, apple-touch nền đặc; `theme_color` / `background_color` hai theme
- [ ] Cả hai theme; tương phản theo ràng buộc 8 (chữ ≥ 4.5:1, đồ hoạ ≥ 3:1)
- [ ] Mọi vùng chạm ≥ 44 × 44
- [ ] Không biến cũ nào của `theme.css` bị đổi tên / đổi giá trị

## 4. Giao gì

- Link `Use the claude_design MCP … Implement: …` mà Claude Design xuất ⇒ thêm vào `design/README.md` một mục
  mới cho P8, cùng khuôn mục "Phase 5" (bảng Design · Link · Ngày chốt).
- `theme.css` bổ sung (nếu có) ⇒ ghi đè `design/theme.css`, rồi `make sync-theme`.
- Bộ icon ⇒ `design/icons/` (PNG + SVG nguồn); T-8.8 chép sang `frontend/public/`.
- Task dùng bản này: T-8.2 (①②), T-8.3 ("Chat tiếp"), T-8.4 (③), T-8.8 (④).
