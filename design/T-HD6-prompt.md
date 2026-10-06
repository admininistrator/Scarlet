# T-HD6 — Panel artifact

Prompt cho Claude Design, viết ở T-5.4 (2026-10-07) theo khuôn một mục của `docs/standardize-tutorial.md` §5–§11.
Mọi con số dưới đây là **số đo thật** của khung T-5.4 trên Chromium qua Nginx (`https://localhost`, 2026-10-07),
không phải ước lượng.

## 1. Làm khi / Chặn / Mở / Đầu ra

- **Làm khi:** sau T-5.4 (khung panel đã chạy trên app thật).
- **Chặn:** T-5.5 (hiển thị theo loại, nút Tải), T-5.9 (tab phiên bản, so sánh, sửa trong panel).
- **Mở:** cùng project Claude Design của bản v3. Tạo **file mới** `Scarlet Panel artifact.dc.html` dựa trên
  `Scarlet Khung chính v3.dc.html` + `Scarlet Tin nhắn v3.dc.html`. **Không sửa** hai file v3 (tutorial §4.1).
- **Đầu ra:** mã component (`.tsx`) + phần `theme.css` bổ sung nếu có (chỉ THÊM biến, không đổi biến cũ).

## 2. Dán gì vào

Dán theo thứ tự, trong **một** cuộc trò chuyện:

1. Bản giao kèo §4.2 của `docs/standardize-tutorial.md` (mười bốn ràng buộc) — nguyên văn.
2. Toàn bộ `design/theme.css` hiện tại.
3. Prompt riêng dưới đây.

```text
Đây là bản vẽ MỚI "Scarlet Panel artifact": panel bên phải màn chat, nơi hiện một artifact
(khối code / trang HTML / SVG / sơ đồ… mà model sinh ra trong câu trả lời). Mở
"Scarlet Khung chính v3" và "Scarlet Tin nhắn v3" làm nền; tạo file mới, không sửa hai file đó.
Khung panel ĐÃ CÓ trong app (T-5.4) — vẽ trên đúng số đo thật dưới đây, không đổi chúng
trừ khi bạn ghi rõ lý do và giá trị mới thành token mới.

① SỐ ĐO THẬT CỦA KHUNG ĐANG CHẠY (Chromium, 2026-10-07)

  Token đang dùng (đã có trong theme.css, KHÔNG đổi tên/giá trị):
    --spacing-panel-right 23.75rem = 380 px   bề rộng mặc định
    --spacing-panel-min   20rem    = 320 px   kéo hẹp nhất
    --spacing-panel-max   35rem    = 560 px   kéo rộng nhất
    --shadow-panel                             bóng của panel
    .motion-panel                              hoạt ảnh vào (scarlet-panel-in, normal · enter)
    nền bg-surface-panel, viền trái border-border 1 px

  Desktop, cửa sổ 1440 × 900, đảo neo trên:
    panel mở ⇒ rect 1060, 0, 380 × 900 (cao hết màn hình, sát mép phải); cột chat co lại
    kéo tay nắm 300 px sang trái ⇒ 560 (kẹp ở max); 300 px sang phải ⇒ 320 (kẹp ở min)
    bề rộng nhớ theo người xem (localStorage); tải lại ⇒ vẫn bề rộng đã kéo
    không cuộn ngang ở cả ba bề rộng (scrollWidth = innerWidth = 1440)

  Tay nắm kéo: dải dọc 12 px × cao hết panel, tâm nằm đúng trên viền trái
    (x 1055 → 1067 khi panel ở 1060), con trỏ col-resize, nền hover surface-hover.
    Bàn phím: role="separator", mũi tên trái = rộng thêm 16 px, mũi tên phải = hẹp đi 16 px.
    Hôm nay tay nắm không có vạch nhìn thấy khi không hover — cần bạn vẽ.

  Ngưỡng toàn màn hình: < 640 px (cùng ngưỡng đảo thu gọn).
    375 × 812 ⇒ panel là dialog phủ kín 0, 0, 375 × 812, không tay nắm, có nút đóng (X, 44 × 44,
    phần tử tabbable duy nhất hôm nay); nội dung phía sau không cuộn; đóng ⇒ luồng tin giữ
    nguyên vị trí cuộn.

  Hai chế độ neo của đảo:
    neo trên    — nút panel nằm ở hàng cuối của thanh đảo khi mở, cạnh khối tài khoản và
                  công tắc sáng/tối (icon panel-right ⇄ panel-right-close, 44 × 44)
    neo hai bên — sidebar dọc 256 px + lề 16 px LUÔN mở và đẩy nội dung 272 px (NQ-136).
                  Sidebar dọc không có chỗ cho nút panel ⇒ CHỖ TẠM của T-5.4: nút 44 × 44 ở
                  chân sidebar, bên phải khối tài khoản (neo trái: 228, 826; neo phải: 1380, 826).
                  1440 px, neo trái, panel 320: cột chat 272 → 1120 (848), panel 1120 → 1440.
                  1440 px, neo phải, panel 320: cột chat 0 → 848, panel 848 → 1168, sidebar bên phải.
    Chưa có quy tắc cho 640–1279 px khi neo hai bên + panel rộng: 1024 px, neo hai bên,
    panel 560 ⇒ cột chat còn 192 px. Hãy chọn và vẽ cách xử lý (ví dụ panel phủ lên, hoặc
    kẹp max theo bề rộng còn lại).

② DỮ LIỆU THẬT PANEL PHẢI HIỆN

  GET /artifacts/{id} (một phiên bản, có nội dung):
    { "id": "8a8c0f4b-…", "lineage_id": "d24c285e-…", "version": 3, "kind": "html",
      "language": "html", "title": "Trang hiển thị mã 949133",
      "content": "<!DOCTYPE html>\n<html lang=\"vi\">…", "message_id": "…",
      "conversation_id": "…", "created_at": "2026-10-06T18:33:12Z" }

  GET /artifacts/{id}/versions (mọi phiên bản của dòng, KHÔNG có nội dung):
    { "items": [
      { "version": 1, "kind": "html", "title": "Trang hiển thị mã 949133", "origin": "model", … },
      { "version": 2, "kind": "html", "title": "Trang hiển thị mã 949133", "origin": "model", … },
      { "version": 3, "kind": "html", "title": "Trang hiển thị mã 949133", "origin": "user",  … } ] }

  Luật của dữ liệu:
    kind có BẢY giá trị: html · react · svg · mermaid · code · markdown · file
    title có thể RỖNG ⇒ app hiện nhãn suy ra (ngôn ngữ · số dòng), ví dụ "Python · 42 dòng"
    version đánh số theo dòng, mọi nhánh hội thoại ⇒ một nhánh có thể thấy "v1 v4" (hở số)
    origin = model | user — "user" là bản người dùng tự sửa, tab mang nhãn "bạn sửa"
    content có thể rất dài (200 dòng × 300 ký tự là ca thử của T-5.5) — cuộn trong khối

③ CHÍN THỨ PHẢI VẼ

  ① Khung panel: tiêu đề (title hoặc nhãn suy ra), nút đóng, tay nắm kéo có vạch nhìn thấy,
     trạng thái trống ("Chưa mở artifact nào")
  ② Tab phiên bản v1 v2 v3 — kể cả dãy hở số (v1 v4) và dòng nhiều phiên bản phải cuộn
  ③ Nút Tải (tải đúng đuôi tệp theo kind)
  ④ Toàn màn hình trên mobile (< 640 px, 375 × 812): đầu panel, nút đóng, tab, nút Tải
  ⑤ Hai chế độ "Xem trước / Mã" cho html, react, svg, mermaid
  ⑥ Chế độ sửa: ô sửa, "Lưu thành phiên bản mới", "Huỷ"; nhãn "bạn sửa" trên tab của bản
     origin = user
  ⑦ Khung so sánh hai phiên bản (khác biệt theo dòng)
  ⑧ Trạng thái của khung render: đang nạp, lỗi (thông báo từ khung), treo ⇒ nút "Chạy lại"
  ⑨ Nút mở panel khi đảo neo hai bên — thay chỗ tạm ở chân sidebar dọc (xem ①)

④ RÀNG BUỘC RIÊNG CỦA BẢN NÀY

  - Vùng nội dung của html / react / mermaid là IFRAME Ở ORIGIN KHÁC (artifacts.localhost,
    ADR-10). Chỉ vẽ khung, nền, viền và trạng thái QUANH nó; không vẽ gì đè lên hay bên trong
    iframe, không giả định đọc được chiều cao nội dung của nó.
  - SVG hiện bằng <img> (không chèn SVG vào trang). Markdown không hiện ảnh (cố ý).
  - Thẻ artifact trong tin nhắn (bản Bong bóng v2, mục 3e) ĐÃ CÓ — không vẽ lại.
  - Ô sửa là <textarea> thường: không trình soạn code có tô màu cú pháp, không số dòng.
  - Mọi chuỗi mới là khoá vi.json phẳng ("artifact.panel.…"), không interpolation.
  - Không đổi tên / đổi giá trị biến nào của theme.css; token mới chỉ THÊM, kèm giá trị
    cho cả theme tối.
  - Không chữ "9Router" / "Sub2API" ở bất cứ đâu.

Artboard: desktop 1440 neo trên (panel trống · có artifact html · đang kéo tay nắm · chế độ sửa ·
so sánh · đang nạp · lỗi · treo); desktop 1440 neo trái và neo phải với nút ⑨; desktop 1024 neo
hai bên + panel (cách xử lý của bạn ở ①); mobile 375 × 812 (panel trống · có artifact · chế độ
Mã · chế độ sửa); cả hai theme.
```

## 3. Nhìn gì để biết đạt

- [ ] ① Khung: tiêu đề, nút đóng, tay nắm có vạch nhìn thấy, trạng thái trống
- [ ] ② Tab phiên bản, có ca hở số (v1 v4) và ca nhiều tab phải cuộn
- [ ] ③ Nút Tải
- [ ] ④ Toàn màn hình 375 × 812
- [ ] ⑤ Xem trước / Mã cho html, react, svg, mermaid
- [ ] ⑥ Chế độ sửa + nhãn "bạn sửa"
- [ ] ⑦ Khung so sánh hai phiên bản
- [ ] ⑧ Đang nạp · lỗi · treo + "Chạy lại"
- [ ] ⑨ Nút mở panel khi neo hai bên (thay chỗ tạm ở chân sidebar dọc)
- [ ] Bề rộng mặc định / min / max vẫn là 380 / 320 / 560, hoặc token mới có lý do ghi rõ
- [ ] 375 px không cuộn ngang ở mọi artboard mobile
- [ ] Cả hai theme; tương phản theo ràng buộc 8 (chữ ≥ 4.5:1, đồ hoạ ≥ 3:1)
- [ ] Mọi vùng chạm ≥ 44 × 44 (riêng tay nắm: dải dọc cao hết panel)
- [ ] Không biến cũ nào của `theme.css` bị đổi tên / đổi giá trị
- [ ] Không vẽ gì đè lên hay bên trong vùng iframe

## 4. Giao gì

- Link `Use the claude_design MCP … Implement: …` mà Claude Design xuất ⇒ thêm vào `design/README.md` một mục
  mới cho P5, cùng khuôn mục "v3 - Phase S - Task S.19" (bảng Design · Link · Ngày chốt).
- `theme.css` bổ sung (nếu có) ⇒ ghi đè `design/theme.css`, rồi `make sync-theme`.
- Task dùng bản này: T-5.5, T-5.9.
