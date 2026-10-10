# T-HD11 — Panel chọn skill

Prompt cho Claude Design, viết ở T-7.5 (2026-10-10) theo khuôn `design/T-HD6-prompt.md` (Q-P7-4, NQ-147).
Số đo của nút ở ô nhập lấy từ **code** đang chạy (`Composer.tsx`, token `theme.css`), không đo lại trên Chromium;
JSON ở ② là **response thật** của `GET /skills` trên stack (`https://localhost`, 2026-10-10).

## 1. Làm khi / Chặn / Mở / Đầu ra

- **Làm khi:** sau T-7.5 (`GET /skills`, `PUT /skills/{name}/toggle` đã chạy trên stack). Vẽ được ngay — không
  chờ T-7.6 … T-7.8.
- **Chặn:** phần panel của T-7.9. **Không** chặn task backend nào, không chặn nút mount trong ô nhập (đã có từ
  T-S.10) hay chip "Đang chạy code…" (đã có từ T-S.15).
- **Mở:** cùng project Claude Design của bản v3. Tạo **file mới** `Scarlet Panel skill.dc.html` dựa trên
  `Scarlet Khung chính v3.dc.html` (ô nhập) + `Scarlet Tin nhắn v3.dc.html`. **Không sửa** hai file v3
  (tutorial §4.1).
- **Đầu ra:** mã component (`.tsx`) + phần `theme.css` bổ sung nếu có (chỉ THÊM biến, không đổi biến cũ).

## 2. Dán gì vào

Dán theo thứ tự, trong **một** cuộc trò chuyện:

1. Bản giao kèo §4.2 của `docs/standardize-tutorial.md` (mười bốn ràng buộc) — nguyên văn.
2. Toàn bộ `design/theme.css` hiện tại.
3. Prompt riêng dưới đây.

```text
Đây là bản vẽ MỚI "Scarlet Panel skill": nơi người dùng bật/tắt skill cho CHÍNH MÌNH. Skill là
một gói hướng dẫn (và có thể kèm script) mà model đọc khi cần — ví dụ "Word (.docx)": model biết
cách tạo file Word. Bật skill nghĩa là model được biết skill đó tồn tại trong mọi cuộc trò chuyện
của người này; tắt thì model không thấy nó. Mở "Scarlet Khung chính v3" và "Scarlet Tin nhắn v3"
làm nền; tạo file mới, không sửa hai file đó.

① CHỖ MỞ PANEL — ĐÃ CÓ TRONG APP

  Hàng nút dưới ô nhập (Composer), trái → phải:
    [Đính kèm 📎] [Tìm web 🌐 — công tắc có chữ] [Chọn skill ⚡] ……… [Mic] [Gửi]
  Nút "Chọn skill": icon Lucide `zap` 20 px, vùng chạm 44 × 44 (token size-touch), bo rounded-md,
    chữ muted, hover nền surface-hover. Hôm nay nó là nút "Sắp có" (ComingSoon, tooltip
    "Chọn skill"). Giữ đúng chỗ và kích thước này; bạn vẽ:
      - trạng thái của nút khi người dùng đã bật ≥ 1 skill (ví dụ chấm/số đếm — số skill đang bật);
      - panel mở ra từ nút này.
  Công tắc "Tìm web" bên cạnh là tiền lệ cho "một tính năng bật/tắt được": bật ⇒ viền accent +
    nền accent-subtle + chữ accent-text; bị chặn ⇒ mờ (control-disabled) + tooltip giải thích.

② DỮ LIỆU THẬT PANEL PHẢI HIỆN

  GET /api/v1/skills (response thật, 2026-10-10 — hôm nay mới có MỘT skill tối thiểu):
    { "items": [
      { "name": "docx",
        "display_name": "Word (.docx)",
        "description": "Create and edit Word documents (.docx) with python-docx — headings,
                        paragraphs, lists, tables and basic styling. Use when the user asks for a
                        Word file or a .docx report.",
        "requires_execution": false,
        "enabled": false } ] }

  PUT /api/v1/skills/{name}/toggle  body {"enabled": true|false}  ⇒ 200 + đúng một mục như trên
    (đã cập nhật). Skill bị gỡ khỏi server giữa chừng ⇒ 404 SKILL_NOT_FOUND.

  Luật của dữ liệu:
    Bộ skill sắp có (T-7.7b): docx · xlsx · pptx · pdf — bốn mục; thiết kế phải chịu được 10+ mục
      (cuộn trong panel), vì admin có thể thêm skill.
    display_name ngắn (≤ ~24 ký tự); name là slug a-z0-9- (≤ 64), có thể hiện phụ dạng mono.
    description là TIẾNG ANH, dài 30 → 1024 ký tự (skill công khai đo được tới ~290 token, chạm trần 1024) —
      không được để một mô tả dài đẩy cả danh sách: cắt 2 dòng + cách xem đủ (bạn chọn: mở rộng
      tại chỗ / tooltip / dòng chi tiết).
    enabled là công tắc CỦA NGƯỜI NÀY; người mới vào: mọi skill đều tắt.
    requires_execution = true ⇒ skill cần CHẠY CODE (trong sandbox của server). Người dùng chỉ
      chạy được khi tài khoản có quyền "chạy code" (admin bật cho từng người, mặc định TẮT).
      Không quyền ⇒ skill vẫn bật được (model vẫn đọc hướng dẫn), nhưng phải nói rõ "tài khoản
      của bạn chưa được chạy code — skill chỉ dùng được phần hướng dẫn". Lối của "Tìm web bị
      chặn": nhãn/biểu tượng + tooltip, không ẩn skill đi.

③ BẢY THỨ PHẢI VẼ

  ① Panel đóng/mở từ nút ⚡: kiểu popover neo trên nút (lối Model Picker) hoặc sheet — bạn chọn,
     ghi lý do. Đầu panel: tiêu đề "Skill", một dòng giải thích ngắn ("Bật skill để model biết
     cách làm việc chuyên biệt"), số đang bật.
  ② Một hàng skill: display_name, name phụ (tuỳ), description cắt 2 dòng + cách xem đủ, công tắc
     bật/tắt (role="switch", vùng chạm ≥ 44 × 44), nhãn "Chạy code" khi requires_execution.
  ③ Trạng thái hàng: tắt · bật · đang lưu (sau khi bấm, trước khi PUT trả) · lỗi lưu (công tắc
     quay về chỗ cũ + câu lỗi ngắn) · skill cần chạy code mà tài khoản không có quyền.
  ④ Danh sách 1 mục (hôm nay), 4 mục (sắp có), 12 mục (phải cuộn trong panel, đầu panel đứng yên).
  ⑤ Trạng thái panel: đang nạp · lỗi nạp (+ "Thử lại") · trống ("Chưa có skill nào" — server
     chưa cài skill).
  ⑥ Nút ⚡ khi ≥ 1 skill đang bật (lối công tắc Tìm web đang bật) và khi 0.
  ⑦ Mobile 375 × 812: panel thành sheet đáy hoặc toàn màn hình, có nút đóng 44 × 44; bàn phím
     ảo đang mở (375 × 420) không che công tắc.

④ RÀNG BUỘC RIÊNG CỦA BẢN NÀY

  - Chip "Đang chạy code…" / "Đã chạy code" dưới câu trả lời ĐÃ CÓ (T-S.15, lối chip "Đang tìm
    web…") — không vẽ lại. Thẻ file kèm nút Tải là màn T-HD6 (kind = file) — không vẽ lại.
  - Không có trang quản trị skill ở bản này (admin không bật/tắt skill toàn cục qua UI).
  - Bật/tắt có hiệu lực từ LƯỢT GỬI KẾ TIẾP, không đổi câu trả lời đang chạy — đừng vẽ gì gợi ý
    "áp dụng ngay cho câu đang trả lời".
  - description là dữ liệu của server, không dịch, không viết lại trong mock.
  - Mọi chuỗi mới là khoá vi.json phẳng ("composer.skill.…"), không interpolation trừ số đếm.
  - Không đổi tên / đổi giá trị biến nào của theme.css; token mới chỉ THÊM, kèm giá trị
    cho cả theme tối.
  - Không chữ "9Router" / "Sub2API" ở bất cứ đâu.

Artboard: desktop 1440 neo trên (nút ⚡ 0 skill · panel 1 mục · 4 mục có 1 bật · 12 mục cuộn ·
đang lưu · lỗi lưu · không quyền chạy code · đang nạp · lỗi nạp · trống); desktop 1440 neo trái;
mobile 375 × 812 (panel 4 mục · không quyền) và 375 × 420 (bàn phím mở); cả hai theme.
```

## 3. Nhìn gì để biết đạt

- [ ] ① Panel mở từ nút ⚡ đúng chỗ đang có, có tiêu đề + dòng giải thích + số đang bật
- [ ] ② Hàng skill: tên, mô tả cắt 2 dòng + cách xem đủ, công tắc `role="switch"`, nhãn "Chạy code"
- [ ] ③ Năm trạng thái hàng (tắt · bật · đang lưu · lỗi lưu · không quyền chạy code)
- [ ] ④ 1 / 4 / 12 mục, 12 mục cuộn trong panel
- [ ] ⑤ Đang nạp · lỗi nạp + "Thử lại" · trống
- [ ] ⑥ Nút ⚡ có trạng thái "đang bật ≥ 1"
- [ ] ⑦ Mobile 375 × 812 và 375 × 420, không cuộn ngang
- [ ] Cả hai theme; tương phản theo ràng buộc 8 (chữ ≥ 4.5:1, đồ hoạ ≥ 3:1)
- [ ] Mọi vùng chạm ≥ 44 × 44
- [ ] Không biến cũ nào của `theme.css` bị đổi tên / đổi giá trị

## 4. Giao gì

- Link `Use the claude_design MCP … Implement: …` mà Claude Design xuất ⇒ thêm vào `design/README.md` một mục
  mới cho P7, cùng khuôn mục "Phase 5" (bảng Design · Link · Ngày chốt).
- `theme.css` bổ sung (nếu có) ⇒ ghi đè `design/theme.css`, rồi `make sync-theme`.
- Task dùng bản này: T-7.9.
