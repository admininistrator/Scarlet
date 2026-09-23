# Hướng dẫn thao tác Claude Design cho T-HD1 → T-HD7

> **Tài liệu này dành cho BẠN, không dành cho agent.** Nó không chứa một dòng code nào phải chạy.
> Nó chứa: mở cái gì, dán chữ gì vào, nhìn cái gì để biết đã đạt, và giao cái gì cho agent.
>
> Nguồn: `tasks.md` §3 (T-H-DESIGN), `tasks.md` §7 (Phase 3), `KE-HOACH.md` §19.1, §16.3, §23,
> ADR-16, R20, P5. Mọi con số trong tài liệu này đo được trên chính repo ngày 2026-09-21.

---

## 0. Bạn đang đứng ở đâu

| Xong | Đang chờ bạn | Bị chặn vì nó |
|---|---|---|
| T-3.0, T-3.1a, T-3.1b, T-3.1c ✅ | **T-HD1** | T-3.2 → rồi T-3.3, T-3.5, T-3.9, T-3.10 |

Bốn task đường-vào của Phase 3 đã xong. Từ đây **mọi task giao diện còn lại đều chờ một bước T-HD**,
trừ T-3.4 (ô nhập), T-3.7a (backend feedback), T-3.8 (điều hướng nhánh) và T-3.11 (thanh quota) —
bốn task ấy agent làm được ngay, nhưng chúng sẽ mang giao diện tạm cho tới khi T-HD1 về.

**Thứ tự làm, và lý do:**

```
T-HD1 ──┬── T-HD2 ──┬── T-HD3 ──── T-HD5
        │           └── T-HD4
        └── T-HD7                          (T-HD7 chỉ cần T-2.19, đã xong — làm song song được)

T-HD6 ── chờ T-5.4 (Phase 5). KHÔNG làm bây giờ.
```

T-HD1 phải đi trước **tất cả** vì nó là cái duy nhất định nghĩa token. Làm T-HD2 trước T-HD1
nghĩa là màn hình khung sẽ bịa ra màu của riêng nó, rồi T-HD1 về và bạn phải vẽ lại T-HD2.

**T-HD6 đừng làm sớm.** Nó thuộc Phase 5 và nó có một ràng buộc mà hôm nay chưa tồn tại:
artifact render trong `<iframe>` ở **origin khác** (`artifacts.localhost`, ADR-10) — tức nội dung
bên trong iframe **không** thừa kế `theme.css`. Thiết kế nó trước khi T-5.6 dựng xong origin ấy là
thiết kế cho một thứ chưa có hình dạng.

---

## 1. Claude Design là gì, và bạn sẽ mở hai thứ khác nhau

Trên claude.ai có hai loại artifact bạn cần, và chúng **không** thay thế nhau:

| Loại | Dùng cho | Trả về cái gì |
|---|---|---|
| **Design System** | T-HD1 | Một trang tham chiếu: bảng màu hai theme, thang chữ, spacing, radius, shadow, component kèm xem trước và hướng dẫn |
| **Design** | T-HD2…T-HD7 | Một canvas chứa nhiều artboard — từng màn hình vẽ sống, xem được ở 375 px lẫn desktop |

Cách bắt đầu: mở một cuộc trò chuyện mới trên claude.ai và **nói ra loại bạn muốn**
("tạo cho tôi một design system", "vẽ cho tôi các màn hình…"). Sau khi có Design System,
các cuộc trò chuyện Design sau sẽ lấy nó làm chuẩn — đó chính là lý do T-HD1 đi trước.

Tìm lại artifact đã tạo: thư viện artifact trên claude.ai (`claude.ai/code/artifacts`), hoặc gõ
`/artifacts` trong Claude Code. Ghim (pin) Design System của Scarlet để sáu bước sau khỏi phải đi tìm.

> **Lưu ý về nút bấm:** giao diện claude.ai đổi theo thời gian. Thứ có giá trị lâu dài trong tài liệu
> này là **nội dung prompt** và **danh sách kiểm**, không phải vị trí nút. Nếu một nút không nằm ở
> chỗ tài liệu nói, cứ nói thẳng điều bạn muốn bằng chữ.

---

## 2. Bản giao kèo kỹ thuật — dán vào **mọi** cuộc trò chuyện Claude Design

Đây là phần quan trọng nhất của tài liệu. Không có nó, Claude Design sẽ trả về một giao diện đẹp mà
**không lắp được vào Scarlet**, và bạn sẽ phát hiện ra điều đó ở bước T-3.2 chứ không phải ở bước T-HD1.

Mở đầu mỗi cuộc trò chuyện bằng nguyên khối này:

```text
Dự án: Scarlet — chatbot self-host cho 15–20 người dùng nội bộ. Giao diện tiếng Việt.

Stack đã chốt, KHÔNG đổi được:
React 19 + TypeScript + Vite + TailwindCSS v4. Không dùng UI-kit lớn (MUI, AntD, Chakra).
shadcn/ui chỉ dùng chọn lọc cho primitive (dialog, dropdown, tooltip).

CHÍN RÀNG BUỘC — mọi thứ bạn xuất ra phải thoả cả chín:

1. Màu chỉ tồn tại dưới dạng CSS variable trong MỘT file theme.css.
   Trong mã component tuyệt đối không có #rrggbb, rgb(), hsl(), oklch().

2. Sáng/tối KHÔNG dùng biến thể `dark:` của Tailwind.
   Một bộ tên class, hai bộ giá trị:
     @theme { ... }              ← giá trị theme sáng
     [data-theme="dark"] { ... } ← ghi đè cho theme tối, nằm NGOÀI @theme
   Thuộc tính data-theme nằm trên thẻ <html>.

3. Bảy tên biến màu này đã có mã đang dùng. GIỮ NGUYÊN TÊN, chỉ đổi giá trị:
     --color-background  --color-foreground  --color-muted  --color-border
     --color-accent  --color-accent-foreground  --color-danger
   Thêm biến mới thì cứ thêm. Đổi tên biến cũ là phải sửa className trong 9 component.

4. Thời lượng và easing của hoạt ảnh cũng là token trong theme.css.
   Mã component không được chứa `transition:`, `animation:`, `150ms`, hay `duration-[200ms]`.
   Nếu cần chuyển động, hãy định nghĩa một class tiện ích trong theme.css
   (ví dụ .motion-panel) rồi component chỉ gắn tên class đó.

5. Mọi chuỗi tiếng Việt phải tách khỏi component (file vi.json, khoá phẳng dạng "chat.gui").
   Hàm dịch KHÔNG có interpolation — đừng viết câu có biến ở giữa
   ("Còn {n}% hạn mức" là sai; hãy tách thành hai mảnh hoặc đặt số ở đầu/cuối).

6. Chiều rộng nhỏ nhất phải chạy đúng là 375 px. Không cuộn ngang ở bất kỳ màn hình nào.

7. Vùng chạm tối thiểu 44 × 44 px.

8. Đích tiếp cận: Lighthouse Accessibility ≥ 90 và axe-core 0 lỗi mức serious/critical.
   Tương phản: chữ thường ≥ 4.5:1, chữ lớn và thành phần đồ hoạ ≥ 3:1 — trong CẢ HAI theme.
   Mọi thành phần tương tác phải có trạng thái focus nhìn thấy được.

9. Định danh trong mã (biến, hàm, prop, tên file) viết bằng tiếng Anh.
   Chỉ chuỗi hiển thị mới là tiếng Việt.

Khi xuất mã, luôn xuất HAI thứ tách rời:
  (a) phần theme.css — chỉ CSS variable;
  (b) phần component .tsx — chỉ dùng class tiện ích Tailwind sinh ra từ các biến đó
      (--color-background → bg-background, --radius-md → rounded-md, v.v.).
```

**Vì sao chín ràng buộc này, không phải chín ràng buộc khác:** tám trong chín đến thẳng từ một dòng
DoD có thật trong `tasks.md`. Ví dụ ràng buộc 1 và 2 là dòng DoD `grep -rnE "#[0-9a-fA-F]{6}|rgb\(|hsl\("`
của T-3.2; ràng buộc 4 là dòng `grep -rnE "transition:|animation:|[0-9]+ms|duration-\["` của T-3.9.
Một thiết kế vi phạm chúng không phải là "thiết kế hơi khác" — nó là **một task DoD đỏ**.

---

## 3. T-HD1 — Hệ thống thiết kế

**Làm khi:** ngay bây giờ. **Chặn:** T-3.2 (và gián tiếp cả T-3.3, T-3.5, T-3.9, T-3.10, T-3.12).
**Đầu ra phải giao cho agent:** `theme.css` đầy đủ, đã kiểm tương phản.

### 3.1 Mở cái gì

Một cuộc trò chuyện mới → yêu cầu tạo **Design System** tên `Scarlet`.

### 3.2 Dán gì vào

Thứ tự: **(1) bản giao kèo §2** → **(2) nội dung `theme.css` hiện tại** → **(3) prompt dưới đây**.

Nội dung `theme.css` hiện tại (mở `frontend/src/styles/theme.css` và dán nguyên văn) là thứ nói cho
Claude Design biết bảy cái tên bất di bất dịch và hình dạng hai khối. Đừng mô tả bằng lời, hãy dán file.

```text
Hãy làm hệ thống thiết kế cho Scarlet.

Tinh thần: "scarlet" là đỏ son. Màu nhấn xoay quanh sắc đỏ ấy, nhưng đây là một công cụ
người ta ngồi trong đó hàng giờ — nền phải trung tính, đỏ chỉ dùng cho hành động chính
và tiêu điểm. Không phải một trang bán hàng.

Tôi cần ĐỦ các vai trò ngữ nghĩa sau, vì màn hình của tôi thật sự có từng cái một.
Thiếu một vai trò ở bước này thì bước sau tôi sẽ phải bịa ra màu, và bịa ở bước sau
nghĩa là làm lại bước này.

BỀ MẶT (ít nhất 4 tầng, phân biệt được ở cả hai theme):
  - nền app
  - sidebar
  - panel nổi / dropdown / tooltip (có shadow)
  - bong bóng tin nhắn của assistant, và bong bóng của user (hai cái phải khác nhau)
  - nền khối code (khác cả hai loại bong bóng)

CHỮ: foreground, muted (chữ phụ), chữ trên nền nhấn, chữ trên nền nguy hiểm,
     chữ trạng thái vô hiệu hoá (model không dùng được).

ĐƯỜNG VIỀN: viền thường, viền đậm (dùng cho ô nhập — xem mục "bẫy" bên dưới),
     vòng focus (focus ring).

TRẠNG THÁI: accent (+ hover, + active), danger, warning, success.
     - warning dùng cho "hạn mức còn ≤ 20%"
     - success dùng cho "đã xác thực email", "provider khoẻ"

THANH QUOTA: ba mức — bình thường, cảnh báo (≤ 20%), đã hết.

BIỂU ĐỒ: đúng 2 màu chuỗi dữ liệu, dùng cho biểu đồ chi phí của admin
     (hai cột tách riêng: "metered" và "unmetered"). Hai màu này phải phân biệt được
     cả với nhau lẫn với nền, ở cả hai theme, và phải phân biệt được khi in trắng đen.

CHỮ: thang cỡ chữ, font chữ thường + font mono cho khối code.
     BẮT BUỘC: font phải có bộ ký tự tiếng Việt đầy đủ (subset "vietnamese").
     Số tiền hiển thị trong bảng admin phải dùng tabular-nums.

CÒN LẠI: thang spacing, thang radius, thang shadow.

Với MỖI cặp màu chữ/nền, in ra tỷ lệ tương phản đã tính. Tôi sẽ đọc bảng đó.

Xuất kết quả cuối cùng dưới dạng MỘT file theme.css theo đúng khuôn Tailwind v4:
đúng hai khối @theme { } và [data-theme="dark"] { }, không có khối thứ ba.
```

### 3.3 Nhìn cái gì để biết đã đạt

Bốn con số dưới đây đo từ **giá trị tạm đang có trong repo**. Bản T-HD1 giao phải **bằng hoặc hơn**:

| Cặp | Sáng | Tối | Ngưỡng |
|---|---|---|---|
| `foreground` / `background` | 17.85:1 | 15.56:1 | ≥ 4.5 |
| `muted` / `background` | **4.76:1** | 7.48:1 | ≥ 4.5 — và xem bẫy ① |
| `accent-foreground` / `accent` | 6.29:1 | 6.43:1 | ≥ 4.5 |
| `danger` / `background` | 4.83:1 | 6.93:1 | ≥ 4.5 |

**Bẫy ① — `muted` phải có biên an toàn, không chỉ "đạt".** Giá trị tạm hôm nay là **4.76:1**,
tức cách ngưỡng 4.5 đúng 0.26. Bản T-HD1 nên nhắm **≥ 5.5:1** cho `muted`. Lý do rất cụ thể: DoD của
T-3.2 có một **ca âm bắt buộc** — tạm đặt `--color-muted: var(--color-background)` thì `make audit`
phải **ĐỎ**. Ca âm ấy chỉ có nghĩa khi `muted` thật sự đang được dùng làm màu chữ trên nền, và một
giá trị chỉ vừa đủ 4.5 sẽ làm cả hai phía của phép thử đều mong manh.

**Bẫy ② — viền là chỗ `make audit` KHÔNG bắt được.** Giá trị tạm hôm nay: viền trên nền là
**1.23:1** (sáng) và **1.31:1** (tối). WCAG 1.4.11 đòi 3:1 cho biên của thành phần giao diện có
nghĩa — nhưng axe-core không có luật tự động cho tương phản phi-văn-bản, và Lighthouse cũng không
chấm nó. Nghĩa là: **một ô nhập có viền vô hình vẫn cho `Accessibility 100`.** Đây là quyết định
phải chốt ở T-HD1, không phải ở lúc chạy DoD. Hãy yêu cầu một `--color-border-strong` riêng cho
biên ô nhập, nhắm ≥ 3:1.

**Bẫy ③ — font tiếng Việt.** Rất nhiều font hiển thị đẹp không có dấu tiếng Việt đầy đủ
(ế, ộ, ữ, ẳ). Trước khi chốt, gõ thử đúng chuỗi này vào bản xem trước:
`Hội thoại mới · Đổi giao diện sáng/tối · Mật khẩu · Hạn mức đã dùng · Suy luận`.
Nếu một chữ nào rơi về font dự phòng (nhìn lệch nét), font đó không dùng được.
Và nếu font đến từ Google Fonts thì phải chốt luôn: tải về tự host, hay để app gọi ra ngoài
mỗi lần tải trang — Scarlet là app self-host, đừng để một nét chữ thành một request ra Internet.

**Bẫy ④ — đừng nhận một bảng màu chỉ có 7 biến.** Nếu bản trả về chỉ đúng bảy cái tên cũ thì T-HD2
sẽ phải bịa. Đếm lại theo danh sách vai trò ở prompt trên; thiếu vai trò nào thì hỏi thêm ngay
trong cùng cuộc trò chuyện chứ đừng mở cuộc mới.

### 3.4 Giao gì cho agent

Một file `theme.css` duy nhất, đúng hai khối. Kèm bảng tương phản (dán vào phần mô tả khi giao task).
Xem §10 để biết đặt file ở đâu.

---

## 4. T-HD2 — Khung chính

**Làm khi:** sau T-HD1. **Chặn:** T-3.3 (sidebar), và là nền của T-3.10 (responsive).
**Đầu ra:** ảnh/mã ba trạng thái — sidebar mở · sidebar đóng · mobile.

### 4.1 Mở cái gì

Một cuộc trò chuyện mới → yêu cầu tạo **Design** (canvas artboard), dùng design system Scarlet đã có.

### 4.2 Dán gì vào

Bản giao kèo §2, rồi:

```text
Vẽ khung chính của Scarlet — ba artboard trên cùng một canvas:

  A. Desktop 1440×900, sidebar MỞ
  B. Desktop 1440×900, sidebar ĐÓNG
  C. Mobile 375×812, sidebar là drawer (vẽ cả trạng thái drawer đang mở, có overlay)

Bốn vùng:
  - Sidebar: nút "Hội thoại mới", ô tìm kiếm, danh sách hội thoại.
    Mỗi hàng hội thoại có: tiêu đề (có thể dài, phải cắt), dấu ghim, và menu
    (đổi tên / ghim / xoá). Phải vẽ cả trạng thái hàng đang được chọn.
    Cuối danh sách có chỗ cho "tải thêm".
  - Header: tên app, nút mở/đóng sidebar, email người dùng, nút Đăng xuất,
    công tắc sáng/tối, và một lối vào /admin chỉ hiện với admin.
  - Vùng chat: danh sách bong bóng (T-HD3 sẽ vẽ chi tiết — ở đây chỉ cần khối xám),
    và ô nhập neo ở đáy.
  - Panel phải: hôm nay đóng. Vẽ trạng thái đóng và chừa chỗ cho nó
    (nó sẽ là panel artifact ở Phase 5, kéo rộng được).

Cho tôi CON SỐ, không chỉ hình:
  - bề rộng sidebar (mở), bề rộng khi đóng (nếu là dải icon) hay ẩn hẳn
  - chiều cao header
  - bề rộng tối đa của một dòng chữ trong vùng chat
  - bề rộng mặc định của panel phải, và khoảng kéo được (min/max)
  - điểm ngắt (breakpoint) nào sidebar chuyển thành drawer

Ở artboard C, chỉ ra rõ: đóng drawer bằng Esc và bằng chạm ra ngoài; tiêu điểm
quay về đúng nút đã mở nó; nội dung phía sau KHÔNG cuộn được khi drawer mở.
```

### 4.3 Một quyết định T-HD2 buộc bạn phải chốt

Sidebar có nút Ghim. **Backend không sắp xếp theo `pinned`** — đọc được ở
`app/db/repositories/conversations.py`: `ORDER BY updated_at DESC, id DESC`, không một chữ `pinned` nào.
Nếu FE tự đẩy ghim lên đầu thì nó chỉ đúng **trong phần đã tải**: một hội thoại ghim từ tháng trước
nằm ở trang 3 sẽ vắng mặt ở đầu danh sách.

Hai ngả, chốt **tại T-HD2** chứ không để agent gặp ở T-3.3:

- **(a)** Thiết kế một khu "Đã ghim" tách riêng ở đầu sidebar, kèm một dòng chữ nói rõ nó chỉ gồm
  phần đã tải. Không đụng backend.
- **(b)** Đổi `ORDER BY` của backend thành `pinned DESC, updated_at DESC, id DESC` và sửa con trỏ
  phân trang cho khớp. Đắt hơn, nhưng đúng hơn.

Cạm bẫy ① của T-3.3 ghi đúng hai ngả này và yêu cầu **"chốt trước khi viết dòng đầu"**.
Chốt ở đây là chốt sớm nhất có thể.

Tương tự, nút "Xoá" trong sidebar **không xoá gì trong DB** (soft delete). Chữ trên nút phải nói
đúng thứ nó làm — quyết định ở T-HD2: dùng chữ "Xoá" kèm một dòng giải thích, hay dùng chữ khác.

### 4.4 Nhìn cái gì để biết đã đạt

- Artboard C rộng đúng **375**, và không có gì tràn ra ngoài mép.
- Mọi nút trong artboard C đo được **≥ 44 px** mỗi chiều.
- Tiêu đề hội thoại dài **bị cắt**, không đẩy giãn sidebar. Thử một tiêu đề 80 ký tự.
- Sidebar đóng ở B: bạn phải trả lời được "nút mở lại nằm ở đâu" chỉ bằng cách nhìn ảnh.
- Cả ba artboard xem được ở **cả hai theme**.

---

## 5. T-HD3 — Bong bóng tin nhắn + khối code

**Làm khi:** sau T-HD2. **Chặn:** T-3.5 (bong bóng + markdown), và cung cấp hình cho T-3.7, T-3.8.
**Đầu ra:** mã component.

### 5.1 Dán gì vào

Bản giao kèo §2, rồi:

```text
Vẽ bong bóng tin nhắn của Scarlet. Đây là màn hình người ta nhìn lâu nhất, nên
tôi cần đủ trạng thái chứ không chỉ trạng thái đẹp.

BỐN TRẠNG THÁI của một câu trả lời:
  1. đang chờ  — chưa có chữ nào. Phải nói ra rằng đang chờ, không để bong bóng rỗng.
  2. đang stream — chữ đang chảy, có con trỏ. Xem ràng buộc hiệu năng bên dưới.
  3. xong
  4. lỗi — hiện mã lỗi và một nút thử lại

HAI LOẠI bong bóng: của người dùng, và của assistant. Phải phân biệt được ngay.

TRONG bong bóng assistant còn có:
  - khối "Suy luận" gập/mở được (mặc định gập)
  - một hàng chip ghi chú nhỏ (tên model, số token, ghi chú hệ thống)
  - điều hướng nhánh dạng ‹ 2/3 › — hai nút mũi tên và một con số ở giữa.
    Nút sẽ bị vô hiệu hoá ở đầu và cuối dãy; vẽ cả trạng thái đó.
  - một hàng NĂM nút dưới câu trả lời: Copy · Thích · Không thích · Thử lại ·
    Đổi model & thử lại. Nút Thích/Không thích có trạng thái đã chọn và bấm lại
    thì bỏ chọn.

TRONG bong bóng người dùng: nút Sửa, và trạng thái "đang sửa tại chỗ"
(ô textarea + nút Lưu + nút Thôi).

KHỐI CODE:
  - nhãn ngôn ngữ ở góc
  - số dòng
  - nút Copy
  - RẤT QUAN TRỌNG: số dòng phải vẽ bằng CSS counter hoặc ::before, KHÔNG phải
    một cột <span> chứa chữ số. Lý do: nút Copy phải trả về nội dung code KHÔNG
    kèm số dòng, và cách rẻ nhất để bảo đảm điều đó là số dòng không nằm trong DOM text.
  - phải chịu được dòng rất dài (cuộn ngang TRONG khối code, không làm trang cuộn ngang)

RÀNG BUỘC HIỆU NĂNG — đọc kỹ, đây là chỗ dễ hỏng nhất:
  Chữ được stream về theo từng mảnh nhỏ. Đo thật trên hệ thống này: 309 mảnh trong
  3,768 giây, khoảng cách lớn nhất giữa hai mảnh là 22 ms. Nghĩa là component này
  re-render 300+ lần trong 4 giây.
    - KHÔNG đặt transition/animation lên phần tử chứa chữ đang chảy.
    - Thiết kế phải chịu được markdown CHƯA ĐÓNG: một khối ``` mới mở một nửa,
      một bảng đang dở. Nó không được làm vỡ bố cục giữa lúc chữ đang chảy.
    - Nếu bạn đề xuất thư viện tô màu cú pháp, nói rõ nó nặng bao nhiêu KB và nó
      tô lại toàn khối hay chỉ phần mới ở mỗi lần cập nhật.
```

### 5.2 Nhìn cái gì để biết đã đạt

- Vẽ đủ **bốn** trạng thái, không phải ba. Trạng thái "đang chờ" hay bị bỏ quên nhất.
- Hàng năm nút ở **375 px** vẫn đủ 44 px mỗi nút — nếu không, thiết kế phải gập bớt vào một menu "…".
- Con số `‹ 2/3 ›` có đủ hai trạng thái nút vô hiệu hoá.
- Khối code có dòng dài 200 ký tự: trang **không** cuộn ngang.
- Bong bóng lỗi hiện được một mã lỗi dạng `CONTEXT_TOO_LARGE` mà không vỡ chữ.

---

## 6. T-HD4 — Model Picker

**Làm khi:** sau T-HD2. **Chặn:** T-3.6.
**Đầu ra:** mã component.

### 6.1 Dữ liệu thật mà picker phải hiện

Đây là toàn bộ catalog hôm nay (`config/model_catalog.json`). Dán nguyên bảng này vào prompt —
thiết kế bịa dữ liệu sẽ không chịu được dữ liệu thật:

| id | Tên hiển thị | Provider | Capabilities | Badge |
|---|---|---|---|---|
| `deepseek-flash` | DeepSeek Flash | deepseek | tools, vision, reasoning | `Mặc định · Rẻ` |
| `claude-haiku` | Claude Haiku 4.5 | anthropic | tools, vision | *(không có)* |
| `nr-gemini-flash` | Gemini Flash (qua 9Router) | ninerouter | tools | `9Router` |
| `ol-qwen-small` | Qwen2.5 0.5B (Ollama) | ollama | *(không có)* | `Self-host` |

Bốn hàng này đã đủ để phá một thiết kế cẩu thả: một hàng **0** capability, một hàng **3**;
một hàng không badge, ba hàng có; tên hiển thị dài nhất có ngoặc đơn.

### 6.2 Dán gì vào

Bản giao kèo §2, bảng trên, rồi:

```text
Vẽ Model Picker của Scarlet.

Mỗi hàng model hiện: tên hiển thị, provider, các badge capability (0 đến 3 cái),
một badge chữ tuỳ chọn, và dấu cho biết model nào đang là mặc định.

TRẠNG THÁI KHÔNG DÙNG ĐƯỢC — đây là trạng thái THƯỜNG, không phải ca lạ:
máy chủ model local (9Router) tắt là chuyện hằng ngày. Khi đó model đó phải:
  - xám đi, KHÔNG chọn được (không chỉ là mờ đi mà vẫn bấm được)
  - có tooltip hiện nguyên văn lý do, là một câu tiếng Việt do server gửi về,
    độ dài không đoán trước được. Tooltip phải xuống dòng được, không tràn màn hình.
Vẽ ít nhất một hàng ở trạng thái này.

HAI TẦNG MẶC ĐỊNH, phải phân biệt được bằng mắt:
  - mặc định của hội thoại này
  - mặc định của tài khoản bạn
  - (và nếu cả hai đều trống thì rơi về mặc định của catalog)
Thứ tự thắng: hội thoại > tài khoản > catalog. Tôi cần biết nhìn vào đâu để biết
model đang dùng đến từ tầng nào.

CHỪA CHỖ, nhưng ĐỪNG vẽ nội dung: sau này sẽ có cảnh báo "model này không có
khả năng vision mà hội thoại đã có ảnh". Chỉ cần chừa chỗ.

Vẽ ở cả desktop và 375 px. Ở 375 px picker nên là gì — dropdown hay sheet từ đáy lên?
Chọn một và nói lý do.
```

### 6.3 Bẫy

- **Đừng để tên model thật lọt vào mã component.** DoD của T-3.6 có dòng
  `grep -rnE '"(deepseek|claude|gpt|gemini|ol)-[a-z0-9.-]+"' frontend/src/` → phải **rỗng**.
  Nếu Claude Design trả về mã có `"deepseek-flash"` viết cứng, hãy yêu cầu nó chuyển bốn hàng đó
  sang một file fixture riêng và component chỉ nhận qua props. Nói thẳng câu đó trong cuộc trò chuyện.
- **Đừng thiết kế một picker gọi API mỗi lần mở.** Đo được ở màn Hệ thống: một lượt kiểm 9Router mất
  **854 / 806 / 941 ms**. Picker mở nhiều hơn màn Hệ thống rất nhiều lần. Nếu thiết kế cần một chỉ
  báo "đang làm mới danh sách", hãy vẽ nó ngay ở bước này.

---

## 7. T-HD5 — Hoạt ảnh

**Làm khi:** sau T-HD3. **Chặn:** T-3.9.
**Đầu ra:** bảng token thời lượng + easing, đặt trong `theme.css`.

Đây là bước **ngắn nhất** và dễ làm hỏng nhất, vì nó là bước duy nhất mà đầu ra không phải hình ảnh.

### 7.1 Dán gì vào

```text
Cho Scarlet một bộ token chuyển động, không phải một bộ hiệu ứng.

Tôi cần:
  - một thang thời lượng (đặt tên theo vai trò, không theo con số:
    ví dụ tức thì / nhanh / thường / chậm)
  - một bộ đường cong easing, cũng đặt tên theo vai trò
    (ví dụ: vào màn hình, ra khỏi màn hình, di chuyển trong màn hình)
  - một bảng "chỗ nào dùng token nào", phủ đúng bốn chỗ:
      · nút bấm (nhấn xuống, nhả ra)
      · icon khi hover
      · sidebar mở/đóng (và drawer trên mobile)
      · chữ xuất hiện khi stream

HAI ĐIỀU BẮT BUỘC:

(1) prefers-reduced-motion: reduce  ⇒  TẮT HẲN hoạt ảnh.
    Không phải "giảm còn một nửa". Viết cho tôi khối @media ấy.

(2) Chữ đang stream: hoạt ảnh đặt ở mức VÙNG (bong bóng xuất hiện),
    TUYỆT ĐỐI không ở mức từng chữ hay từng mảnh.
    Lý do đo được: 309 mảnh trong 3,768 giây. Một transition đặt trên phần tử
    chứa chữ nghĩa là trình duyệt vẽ lại 300+ lần trong 4 giây.

CÁCH GIAO: component của tôi không được chứa `transition:`, `animation:`,
`150ms`, hay `duration-[200ms]`. Nên hãy giao:
  (a) các biến --... trong theme.css, và
  (b) một nhúm class tiện ích cũng định nghĩa trong theme.css
      (ví dụ .motion-press, .motion-panel, .motion-enter)
  để component chỉ việc gắn tên class.
```

### 7.2 Bẫy

- **`make audit` không bắt được `prefers-reduced-motion` sai.** Cả Lighthouse lẫn axe đều không chấm nó.
  Nếu bạn nhận một bản không có khối `@media`, không có phép đo tự động nào báo cho bạn biết —
  người chịu hậu quả là đúng người không chịu được chuyển động. Đếm bằng mắt: khối `@media` phải có mặt.
- **Đừng nhận token chuyển động dưới dạng lớp tiện ích Tailwind có sẵn** (`transition-all duration-200`).
  Con số `200` ấy chính là thứ dòng DoD `grep` đang tìm.

---

## 8. T-HD6 — Panel artifact *(Phase 5 — chưa làm)*

**Làm khi:** sau **T-5.4**, không sớm hơn. **Chặn:** T-5.5.

Ghi lại ở đây để khi tới nơi bạn không phải đọc lại từ đầu. Ba điều riêng của bước này:

1. **Nội dung iframe KHÔNG thừa kế `theme.css`.** Artifact render live chạy ở origin phụ
   `artifacts.localhost` với `sandbox` **không có** `allow-same-origin` (ADR-10, §14.3). Nghĩa là:
   thiết kế của bạn chỉ vẽ được **cái khung** quanh iframe. Bên trong là một trang khác, được nạp
   nội dung qua `postMessage`. Đừng thiết kế một panel giả định rằng nền bên trong khớp nền bên ngoài.
2. **Tab phiên bản `v1 v2 v3`** — artifact không sửa tại chỗ, mỗi lần cập nhật là một dòng mới
   (§14.2). Thiết kế phải chịu được 10+ phiên bản, không chỉ 3.
3. **Toàn màn hình trên mobile**, cộng nút Tải. Ở 375 px panel phải không chia đôi màn hình.

---

## 9. T-HD7 — Admin panel

**Làm khi:** ngay được — nó chỉ phụ thuộc T-2.19 (đã xong). **Chặn:** T-3.12.
**Ghi chú của `tasks.md`:** *"Có thể để đơn giản, ưu tiên thấp."* Đừng đầu tư quá tay ở đây.

### 9.1 Sáu màn hình (§16.3)

| Màn | Nội dung |
|---|---|
| Duyệt user | Danh sách chờ duyệt, nút Duyệt/Từ chối, email + thời điểm đăng ký |
| Người dùng | Bảng: trạng thái, tier, chi tiêu 7 ngày, số hội thoại; hành động: đổi tier, ghi đè hạn mức, bật `can_execute_skills`, khoá |
| Chi phí | Biểu đồ theo ngày + bảng theo user và theo model. **Hai cột tách riêng** `metered` / `unmetered` |
| Model | Health từng provider, nút reload catalog, bật/tắt từng model |
| Hệ thống | Độ dài hàng đợi, số stream đang chạy, phiên bản, kết quả healthcheck |
| Audit log | Ai · lúc nào · làm gì · với ai |

### 9.2 Dán gì vào

Bản giao kèo §2, bảng trên, rồi:

```text
Vẽ admin panel của Scarlet — sáu màn theo bảng trên. Giữ đơn giản: đây là màn
cho một người quản trị duy nhất, không phải một sản phẩm SaaS.

BỐN ĐIỀU KHÔNG ĐƯỢC BỎ QUA:

1. TIỀN LÀ CHUỖI, không phải số thực — nó đi nguyên chuỗi từ database ra tới
   màn hình để không bị làm tròn. Thiết kế phải căn phải và dùng tabular-nums.
   Đừng vẽ một ô hiện "tổng" mà tôi phải cộng ở tầng giao diện.

2. KHÔNG được có chữ "đã áp dụng" ở bất cứ đâu sau khi đổi hạn mức hay đổi tier.
   Thay đổi có hiệu lực trong ≤ 60 giây, không tức thì. Câu đúng là
   "có hiệu lực trong vòng 60 giây". Hãy vẽ chỗ cho câu ấy.

3. Ở 375 px, bốn bảng số này là màn hình tệ nhất của cả app. Chúng phải cuộn
   ngang được TRONG khung bảng, không làm trang cuộn ngang. Vẽ rõ cách bạn làm
   điều đó (khung cuộn có bóng mờ ở mép? cột đầu dính? đổi sang thẻ card?).

4. Màn Hệ thống phải hiện được LÝ DO một mục hỏng. Có trường hợp lý do trả về là
   CHUỖI RỖNG. Vẽ luôn trạng thái đó — nó phải nói được điều gì đó, không để trống.

BIỂU ĐỒ CHI PHÍ: dùng đúng hai màu chuỗi dữ liệu đã có trong design system
(metered / unmetered). Có chú giải. Phải đọc được khi in trắng đen.

AUDIT LOG: mỗi dòng phải nói được "ai" và "với ai" bằng chữ người đọc được,
không phải UUID. Vẽ cả trường hợp đối tượng là một tier (chuỗi) chứ không phải
một người (UUID) — hai loại đối tượng dùng chung một cột.
```

---

## 10. Bàn giao cho agent

### 10.1 Đặt file ở đâu

Tạo một thư mục `design/` ở gốc repo (bạn tạo, không phải agent):

```
design/
├── README.md                      # bảng: bước T-HD nào → link artifact nào → ngày chốt
├── theme.css                      # T-HD1 — bản agent sẽ chép vào frontend/src/styles/
├── contrast.md                    # T-HD1 — bảng tỷ lệ tương phản đã tính
├── T-HD2-khung-chinh/
│   ├── 01-sidebar-mo.png
│   ├── 02-sidebar-dong.png
│   ├── 03-mobile-375.png
│   ├── layout.md                  # CÁC CON SỐ: bề rộng, chiều cao, breakpoint
│   └── Shell.tsx                  # khung component
├── T-HD3-bong-bong/
├── T-HD4-model-picker/
├── T-HD5-hoat-anh/
│   └── motion.css                 # phần agent sẽ ghép vào theme.css
└── T-HD7-admin/
```

> **`design/` chưa có trong cây §23 của `KE-HOACH.md`.** Đây đúng là loại lệch mà repo này ghi Backlog
> thay vì lặng lẽ bỏ qua (tiền lệ B-210 với `src/app/`). Thêm một dòng vào §14 Backlog của `tasks.md`
> — số tiếp theo còn trống là **B-219**:
>
> ```
> | B-219 | Thư mục `design/` (bàn giao Claude Design, T-HD1…T-HD7) chưa có trong cây §23 | T-H-DESIGN, tiền lệ B-210 |
> ```
>
> (Bảng Backlog có đúng ba cột: `#` · `Ý tưởng` · `Nguồn`.)

### 10.2 Giao gì, và giao cái gì thì vô dụng

| Giao | Vì sao |
|---|---|
| ✅ `theme.css` hai khối | Agent chép thẳng, T-3.2 chỉ còn việc nối |
| ✅ Bảng con số (bề rộng, chiều cao, breakpoint) | Agent không đọc được số từ ảnh PNG |
| ✅ Mã `.tsx` dùng class Tailwind | Đúng thứ "Claude Design ra hình dạng và mã component" |
| ✅ Ảnh chụp từng trạng thái | Để bạn và agent nói về **cùng một** màn hình |
| ⚠️ Danh sách chuỗi tiếng Việt kèm khoá gợi ý | Agent phải chuyển chúng vào `vi.json` — đưa sẵn thì đỡ một vòng |
| ❌ Bản export HTML đầy đủ của artifact | Nó là HTML/CSS đứng riêng, không phải Tailwind v4 của repo. Agent sẽ phải viết lại và sẽ viết lại **sai chỗ bạn không nhìn** |
| ❌ "Cứ làm giống ảnh này" | Vi phạm đúng điều `tasks.md` §3 cấm: agent không được tự quyết màu/spacing/bố cục |

### 10.3 Prompt giao task cho agent

Sau khi đặt file vào `design/`, mở một phiên Claude Code mới và nói:

```text
Làm task T-3.2 trong docs/tasks.md.

Bản T-HD1 đã xong và nằm ở design/theme.css. Bảng tương phản ở design/contrast.md.

Ba điều về bàn giao này:
- Giữ nguyên bảy tên biến cũ; bản mới có thêm <N> biến, đó là chủ ý.
- Màu, spacing, bố cục đã chốt. Thấy sai thì BÁO LẠI, không sửa.
- Nếu một giá trị trong theme.css làm một dòng DoD không đạt được, dừng và hỏi
  chứ đừng tự chỉnh giá trị cho DoD xanh.

Đọc mục "KH tham chiếu" của task trước khi viết dòng code đầu tiên.
```

Câu thứ ba quan trọng hơn nó trông. Ca âm của T-3.2 (`--color-muted: var(--color-background)` phải
làm `make audit` đỏ) là một dòng DoD **cố ý làm hỏng** bảng màu của bạn rồi trả lại. Một agent không
được dặn trước có thể hiểu nhầm đó là lời mời chỉnh màu.

---

## 11. Bảy cạm bẫy khi thao tác trên Claude Design

**① Không có Design System thì mỗi cuộc trò chuyện là một bảng màu.**
Đây là lý do duy nhất khiến T-HD1 phải đi trước, và là lỗi tốn thời gian nhất có thể mắc.

**② Artifact Design là một trang HTML đứng riêng — CSS của nó không phải cấu hình Tailwind của bạn.**
Luôn hỏi tách hai phần: "phần theme.css" và "phần component dùng class Tailwind". Nếu chỉ nhận một
bản xem trước đẹp, bạn đang nhận một bức ảnh có thể click được, không phải một bàn giao.

**③ Yêu cầu "cho đẹp" thì nhận lại giá trị tuỳ tiện.** `p-[13px]`, `duration-[240ms]`, `#c2183a`.
Mỗi cái là một dòng DoD đỏ. Hãy nói "token", đừng nói "đẹp".

**④ Đừng mở sáu artifact cho sáu lần sửa.** Sửa trong cùng một artifact — nó giữ lịch sử phiên bản,
và một link duy nhất trong `design/README.md` luôn trỏ tới bản mới nhất. Sáu link là sáu cơ hội để
agent lấy nhầm bản cũ.

**⑤ Đừng thiết kế cho dữ liệu chưa tồn tại.** Hai ví dụ có thật trong repo này: sắp xếp theo ghim
(backend chưa làm — §4.3), và trường `available` / `unavailable_reason` cho model (kiểu `ModelRa`
của FE hôm nay **chưa** có hai trường này, dù backend đã trả). Thiết kế cứ vẽ trạng thái ấy — nhưng
phải biết rằng nó kéo theo việc cho agent, và ghi lại điều đó khi giao task.

**⑥ Claude Design không biết chuỗi lỗi thật của backend.** Nó sẽ bịa
"Something went wrong". Chuỗi thật của Scarlet là những thứ như `CONTEXT_TOO_LARGE`,
`429 · Retry-After`, `ADMIN_REQUIRED`, và những câu tiếng Việt đã có trong
`frontend/src/locales/vi.json`. Dán file ấy vào khi thiết kế trạng thái lỗi.

**⑦ Kiểm tiếng Việt trước khi chốt, không sau.** Không chỉ font (§3.3 bẫy ③) mà cả **chiều dài chữ**:
tiếng Việt dài hơn tiếng Anh khoảng 20–30% cho cùng một ý. Một nút vừa khít chữ "Save" sẽ vỡ với
"Lưu thay đổi". Yêu cầu Claude Design vẽ bằng **chính chuỗi tiếng Việt thật**, đừng để nó vẽ bằng
tiếng Anh rồi dịch sau.

---

## 12. Danh sách kiểm — chạy sau mỗi bước T-HD, trước khi giao cho agent

- [ ] Mọi màu trong mã trả về là `var(--...)` — `grep` bằng mắt: không có `#`, `rgb(`, `hsl(`, `oklch(`
- [ ] Không có biến thể `dark:` nào trong mã component
- [ ] Bảy tên biến cũ còn nguyên tên
- [ ] Không có `transition:`, `animation:`, `150ms`, `duration-[...]` trong mã component
- [ ] Mọi chuỗi hiển thị đã tách ra một danh sách riêng, và không câu nào có biến ở giữa
- [ ] Xem ở **375 px**: không cuộn ngang, mọi vùng chạm ≥ 44 px
- [ ] Xem ở **cả hai theme**, không chỉ theme sáng
- [ ] Gõ thử `Hội thoại mới · Đổi giao diện sáng/tối · Mật khẩu · Hạn mức đã dùng · Suy luận` — dấu đủ, nét đều
- [ ] Mọi thành phần tương tác có trạng thái focus nhìn thấy được
- [ ] Trạng thái **xấu** đã được vẽ: rỗng, đang tải, lỗi, vô hiệu hoá, chữ quá dài
- [ ] Đã có **con số** (bề rộng, chiều cao, breakpoint), không chỉ có ảnh
- [ ] Đã cập nhật `design/README.md`: link artifact + ngày chốt

---

## 13. Nếu Claude Design và `tasks.md` mâu thuẫn

Đừng tự hoà giải, và đừng để agent hoà giải — đó là luật A10 của `CLAUDE.md`.

Ba chỗ có thật, đã biết trước, mà mâu thuẫn dễ xảy ra:

| Chỗ | Mâu thuẫn có thể gặp | Ai quyết |
|---|---|---|
| Sắp xếp ghim trong sidebar | Thiết kế đẩy ghim lên đầu; backend không sắp theo `pinned` | **Bạn**, tại T-HD2 (§4.3) |
| Tương phản viền | Thiết kế dùng viền rất nhạt; `make audit` không bắt, nhưng người dùng không thấy ô nhập | **Bạn**, tại T-HD1 (§3.3 bẫy ②) |
| Thư viện tô màu cú pháp | Thiết kế đòi highlight đẹp; không phép đo nào ở P3 bắt được giá của nó | **Bạn**, tại T-HD3 (§5.1) |

Quyết xong thì ghi một dòng vào **Nhật ký quyết định** của `tasks.md` (§16) — số NQ tiếp theo còn
trống là **NQ-91**. Đó là chỗ duy nhất trong `docs/` mà một quyết định thiết kế được phép sống, và
là thứ agent sẽ đọc khi nó gặp cùng câu hỏi ở task sau.
