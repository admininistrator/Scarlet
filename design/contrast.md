# Scarlet — Bảng tương phản

Kiểm chứng accessibility cho `theme.css`. Tính theo công thức tương phản WCAG 2.x
(relative luminance sRGB). Nguồn giá trị: các token trong `@theme` (theme sáng) và
`[data-theme="dark"]` (theme tối).

**Đích:** chữ thường ≥ 4.5:1 · chữ lớn và thành phần đồ hoạ ≥ 3:1 · trong CẢ HAI theme.

**Kết quả:** không có cặp nào không đạt. 87 cặp đã tính, 0 fail.

---

## 1. Chữ — ngưỡng 4.5:1

| Chữ | Trên nền | Sáng | Tối |
|---|---|---|---|
| foreground | background / sidebar / raised | 16.51 / 14.90 / 17.49 | 16.00 / 16.81 / 13.23 |
| foreground | bubble-assistant / bubble-user / codeblock | 17.49 / 14.91 / 14.93 | 14.62 / 12.34 / 17.47 |
| foreground | field / hover | 17.49 / 14.13 | 14.62 / 12.90 |
| foreground | accent-subtle / danger-subtle | 14.39 / 14.41 | 13.50 / 14.24 |
| foreground | warning-subtle / success-subtle | 15.35 / 15.18 | 12.88 / 13.43 |
| muted | background / sidebar / raised | 6.75 / 6.09 / 7.15 | 8.20 / 8.61 / 6.78 |
| muted | bubble-user / codeblock / field / hover | 6.10 / 6.11 / 7.15 / 5.78 | 6.32 / 8.95 / 7.49 / 6.61 |
| disabled-foreground | background / sidebar / raised / field | 4.99 / **4.51** / 5.29 / 5.29 | 5.86 / 6.15 / **4.84** / 5.35 |
| accent-foreground | accent / accent-hover / accent-active | 5.49 / 7.14 / 9.52 | 5.69 / **4.72** / 6.97 |
| danger-foreground | danger / danger-hover | 6.42 / 8.18 | 6.33 / 5.11 |
| warning-foreground | warning | 7.66 | 7.45 |
| success-foreground | success | 5.02 | 5.35 |
| accent-emphasis | background / raised / sidebar / accent-subtle | 6.74 / 7.14 / 6.08 / 5.87 | 8.44 / 6.98 / 8.87 / 7.13 |
| danger-emphasis | background / raised / danger-subtle | 7.32 / 7.76 / 6.39 | 8.51 / 7.03 / 7.57 |
| warning-emphasis | background / raised / warning-subtle | 5.97 / 6.33 / **5.56** | 10.30 / 8.52 / 8.29 |
| success-emphasis | background / raised / success-subtle | 6.33 / 6.70 / 5.82 | 9.84 / 8.13 / 8.26 |

### Ba cặp sát ngưỡng nhất

| Cặp | Theme | Tỷ lệ | Biên |
|---|---|---|---|
| disabled-foreground trên sidebar | sáng | 4.51 | +0.01 |
| accent-foreground trên accent-hover | tối | 4.72 | +0.22 |
| disabled-foreground trên raised | tối | 4.84 | +0.34 |

Đổi bất kỳ token nào trong ba cặp trên là phải tính lại trước khi commit.

---

## 2. Phi văn bản — ngưỡng 3:1

Áp WCAG 1.4.11 (Non-text Contrast): viền ô nhập, vòng focus, thanh quota và cột
biểu đồ đều là thành phần đồ hoạ cần thiết để hiểu nội dung.

| Cặp | Sáng | Tối |
|---|---|---|
| border-strong / field | 3.75 | 3.45 |
| border-strong / background | 3.54 | 3.77 |
| border-strong / raised | 3.75 | **3.12** |
| border-strong / sidebar | 3.19 | 3.96 |
| ring / background | 5.18 | 7.98 |
| ring / sidebar | 4.67 | 8.38 |
| ring / raised | 5.49 | 6.60 |
| ring / bubble-user | 4.68 | 6.16 |
| ring / codeblock | 4.68 | 8.71 |
| accent / background | 5.18 | **3.22** |
| quota-normal / quota-track | 5.32 | 3.63 |
| quota-warning / quota-track | **3.30** | 6.31 |
| quota-depleted / quota-track | 4.88 | 3.84 |
| chart-metered / background | 12.57 | 3.71 |
| chart-metered / raised | 13.31 | **3.07** |
| chart-unmetered / background | 3.33 | 12.57 |
| chart-unmetered / raised | 3.52 | 10.40 |
| **chart-metered / chart-unmetered** | **3.78** | **3.39** |

### Biểu đồ và in trắng đen

Hai màu chuỗi đạt cả ba điều kiện cùng lúc: ≥3:1 với nền, ≥3:1 với nhau, và
metered luôn là màu **tối** còn unmetered luôn là màu **sáng** ở cả hai theme
(12.57 so với 3.33 trong theme sáng) — nên thứ tự độ sáng không đảo, in trắng đen
vẫn phân biệt được.

Giá phải trả: metered trong theme sáng là đỏ huyết `#5c1610`, không phải đỏ son
tươi. Một màu đỏ tươi không thể đồng thời ≥3:1 với nền trắng và ≥3:1 với một màu
thứ hai cũng ≥3:1 với nền trắng.

---

## 3. Hai chỗ tương phản thấp — có chủ ý

| Cặp | Sáng | Tối | Bù bằng gì |
|---|---|---|---|
| quota-track / background | 1.27 | 1.31 | thanh quota **bắt buộc** có `border border-border-strong` (3.19–3.96:1) |
| các tầng bề mặt kề nhau | 1.06–1.17 | 1.05–1.24 | mọi ranh giới tầng phải có `border-border`; panel nổi thêm shadow |

Chi tiết phân tầng bề mặt (không có ngưỡng WCAG, chỉ để kiểm tra "phân biệt được"):

| Cặp tầng | Sáng | Tối |
|---|---|---|
| background / sidebar | 1.11 | 1.05 |
| background / raised | 1.06 | 1.21 |
| background / bubble-assistant | 1.06 | 1.09 |
| bubble-assistant / bubble-user | 1.17 | 1.18 |
| bubble-assistant / codeblock | 1.17 | 1.19 |
| border / background | 1.27 | 1.31 |

Trong theme sáng, `raised` và `bubble-assistant` cùng là `#ffffff`: panel nổi phân
biệt bằng shadow chứ không bằng nền. Hai token vẫn tách nhau nên điều chỉnh được
độc lập.

---

## 4. Giá trị token dùng để tính

Để kiểm tra lại độc lập (WebAIM Contrast Checker, axe DevTools, v.v.).

| Token | Sáng | Tối |
|---|---|---|
| `--color-background` | `#faf8f6` | `#171413` |
| `--color-sidebar` | `#f1ece7` | `#100e0d` |
| `--color-raised` | `#ffffff` | `#292525` |
| `--color-bubble-assistant` | `#ffffff` | `#201d1c` |
| `--color-bubble-user` | `#fbe9e6` | `#3f2421` |
| `--color-codeblock` | `#f2ece7` | `#090807` |
| `--color-field` | `#ffffff` | `#201d1c` |
| `--color-hover` | `#ece6e0` | `#2b2726` |
| `--color-foreground` | `#1c1917` | `#f2efec` |
| `--color-muted` | `#5f5651` | `#b4aca6` |
| `--color-disabled-foreground` | `#736a63` | `#99908a` |
| `--color-border` | `#e4ddd6` | `#302b28` |
| `--color-border-strong` | `#8d8279` | `#787069` |
| `--color-ring` | `#c3341c` | `#ff8a75` |
| `--color-accent` | `#c3341c` | `#bf3220` |
| `--color-accent-hover` | `#a6281d` | `#d43b26` |
| `--color-accent-active` | `#851f16` | `#a82a1a` |
| `--color-accent-foreground` | `#ffffff` | `#ffffff` |
| `--color-accent-subtle` | `#ffe3dd` | `#3a1c16` |
| `--color-accent-emphasis` | `#a6281d` | `#ff9280` |
| `--color-danger` | `#b81a45` | `#b81f45` |
| `--color-danger-hover` | `#9c1339` | `#cf2a52` |
| `--color-danger-foreground` | `#ffffff` | `#ffffff` |
| `--color-danger-subtle` | `#ffe2e9` | `#3a1220` |
| `--color-danger-emphasis` | `#a3123b` | `#ff8fa8` |
| `--color-warning` | `#e8a33d` | `#e0a33a` |
| `--color-warning-foreground` | `#2b1c05` | `#2b1c05` |
| `--color-warning-subtle` | `#fdefd0` | `#33260d` |
| `--color-warning-emphasis` | `#8a5300` | `#f0b95c` |
| `--color-success` | `#15803d` | `#1a7a4a` |
| `--color-success-foreground` | `#ffffff` | `#ffffff` |
| `--color-success-subtle` | `#dcf5e4` | `#0d2a1c` |
| `--color-success-emphasis` | `#0f6a35` | `#5fd39a` |
| `--color-quota-track` | `#e4ddd6` | `#302b28` |
| `--color-quota-normal` | `#5f5651` | `#8a8079` |
| `--color-quota-warning` | `#a86a08` | `#e0a33a` |
| `--color-quota-depleted` | `#b3251b` | `#e8543c` |
| `--color-chart-metered` | `#5c1610` | `#c9402c` |
| `--color-chart-unmetered` | `#728c9e` | `#c9d8e2` |

---

## 5. Những gì bảng này KHÔNG bao phủ

Tương phản chỉ là một phần của đích "Lighthouse Accessibility ≥ 90 và axe-core 0
lỗi serious/critical". Còn phải kiểm bằng tay:

- Mọi thành phần tương tác có `focus-visible` nhìn thấy được:
  `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2
  focus-visible:ring-offset-background` (ring-offset tách vòng focus khỏi nền nút đỏ).
- Vùng chạm ≥ 44 × 44 px: `size-touch` hoặc `min-h-touch min-w-touch`.
- Không cuộn ngang ở 375 px.
- Model không dùng được: `--color-disabled-foreground` đạt 4.51:1 nên không còn
  "trông mờ" → phải kèm `aria-disabled` và nhãn chữ "không dùng được". Item
  disabled không nhận `hover:bg-hover`.
- Trạng thái quota và provider không được chỉ báo bằng màu: kèm nhãn chữ và số.
- Nút xoá: hue của danger chỉ lệch accent ~30°, không đủ để phân biệt đáng tin →
  phải khác cả về hình thức (viền thay vì tô đặc, có icon, có bước xác nhận).
- Biểu đồ: hai cột tách riêng + nhãn trực tiếp; thêm hoạ tiết gạch chéo cho
  unmetered nếu in trắng đen là yêu cầu thật.
