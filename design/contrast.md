# Scarlet — Bảng tương phản

Mọi số dưới đây tính theo công thức tương phản WCAG 2.1 (relative luminance, sRGB)
từ chính giá trị hex trong `theme.css`. Sửa một biến màu thì phải tính lại dòng tương ứng.

**Ngưỡng áp dụng**

| Loại | Ngưỡng |
|---|---|
| Chữ thường (< 18.66px thường / < 24px đậm) | ≥ 4.5:1 |
| Chữ lớn (≥ 24px, hoặc ≥ 18.66px đậm) | ≥ 3:1 |
| Thành phần đồ hoạ, viền ô nhập, vòng focus, thanh, cột biểu đồ | ≥ 3:1 |
| Chữ vô hiệu hoá | miễn trừ (WCAG 1.4.3) — hệ vẫn giữ ≥ 3:1 |

Cả hai cột Sáng / Tối đều phải đạt thì dòng đó mới ✅.

---

## 1. Chữ chính và chữ phụ trên từng bề mặt

| Chữ / thành phần | Nền | Sáng | Tối | Ngưỡng | Đạt |
|---|---|---:|---:|---:|:--:|
| `--color-foreground` | `--color-background` | 16.23 | 15.89 | 4.5:1 | ✅ |
| `--color-foreground` | `--color-surface-sidebar` | 14.99 | 16.95 | 4.5:1 | ✅ |
| `--color-foreground` | `--color-surface-panel` | 17.53 | 13.63 | 4.5:1 | ✅ |
| `--color-foreground` | `--color-surface-assistant` | 17.53 | 14.51 | 4.5:1 | ✅ |
| `--color-foreground` | `--color-surface-user` | 15.35 | 13.07 | 4.5:1 | ✅ |
| `--color-foreground` | `--color-surface-code` | 13.85 | 17.26 | 4.5:1 | ✅ |
| `--color-muted` | `--color-background` | 6.69 | 7.07 | 4.5:1 | ✅ |
| `--color-muted` | `--color-surface-sidebar` | 6.18 | 7.54 | 4.5:1 | ✅ |
| `--color-muted` | `--color-surface-panel` | 7.23 | 6.06 | 4.5:1 | ✅ |
| `--color-muted` | `--color-surface-assistant` | 7.23 | 6.45 | 4.5:1 | ✅ |
| `--color-muted` | `--color-surface-user` | 6.33 | 5.81 | 4.5:1 | ✅ |
| `--color-muted` | `--color-surface-code` | 5.71 | 7.68 | 4.5:1 | ✅ |

## 2. Chữ trên nền đặc (accent / danger)

| Chữ / thành phần | Nền | Sáng | Tối | Ngưỡng | Đạt |
|---|---|---:|---:|---:|:--:|
| `--color-accent-foreground` | `--color-accent` | 6.54 | 4.68 | 4.5:1 | ✅ |
| `--color-accent-foreground` | `--color-accent-hover` | 8.10 | 5.42 | 4.5:1 | ✅ |
| `--color-accent-foreground` | `--color-accent-active` | 9.91 | 6.84 | 4.5:1 | ✅ |
| `--color-danger-foreground` | `--color-danger` | 8.02 | 5.63 | 4.5:1 | ✅ |
| `--color-danger-foreground` | `--color-danger-hover` | 9.88 | 4.61 | 4.5:1 | ✅ |

## 3. Màu trạng thái dùng làm CHỮ

Accent và danger mỗi thứ có hai biến: `--color-accent` là nền nút (đồ hoạ, ngưỡng 3:1),
`--color-accent-text` là bản đủ tương phản để làm chữ hoặc icon trên bề mặt (4.5:1).
Không dùng lẫn.

| Chữ / thành phần | Nền | Sáng | Tối | Ngưỡng | Đạt |
|---|---|---:|---:|---:|:--:|
| `--color-accent-text` | `--color-background` | 6.80 | 8.00 | 4.5:1 | ✅ |
| `--color-accent-text` | `--color-surface-panel` | 7.34 | 6.86 | 4.5:1 | ✅ |
| `--color-accent-text` | `--color-surface-sidebar` | 6.28 | 8.53 | 4.5:1 | ✅ |
| `--color-accent-text` | `--color-accent-subtle` | 6.30 | 7.15 | 4.5:1 | ✅ |
| `--color-danger-text` | `--color-background` | 8.02 | 8.42 | 4.5:1 | ✅ |
| `--color-danger-text` | `--color-danger-subtle` | 7.44 | 7.41 | 4.5:1 | ✅ |
| `--color-warning-text` | `--color-background` | 5.91 | 8.44 | 4.5:1 | ✅ |
| `--color-warning-text` | `--color-warning-subtle` | 5.71 | 6.94 | 4.5:1 | ✅ |
| `--color-success-text` | `--color-background` | 6.57 | 8.22 | 4.5:1 | ✅ |
| `--color-success-text` | `--color-success-subtle` | 6.18 | 7.05 | 4.5:1 | ✅ |

## 4. Chữ vô hiệu hoá (model không dùng được)

| Chữ / thành phần | Nền | Sáng | Tối | Ngưỡng | Đạt |
|---|---|---:|---:|---:|:--:|
| `--color-disabled-foreground` | `--color-background` | 3.46 | 4.01 | 3:1 | ✅ |
| `--color-disabled-foreground` | `--color-surface-panel` | 3.74 | 3.44 | 3:1 | ✅ |
| `--color-disabled-foreground` | `--color-surface-sidebar` | 3.20 | 4.28 | 3:1 | ✅ |

## 5. Thành phần đồ hoạ

| Chữ / thành phần | Nền | Sáng | Tối | Ngưỡng | Đạt |
|---|---|---:|---:|---:|:--:|
| `--color-border-strong` | `--color-background` | 3.37 | 4.18 | 3:1 | ✅ |
| `--color-border-strong` | `--color-surface-panel` | 3.64 | 3.59 | 3:1 | ✅ |
| `--color-ring` | `--color-background` | 6.80 | 8.00 | 3:1 | ✅ |
| `--color-ring` | `--color-surface-panel` | 7.34 | 6.86 | 3:1 | ✅ |
| `--color-ring` | `--color-surface-sidebar` | 6.28 | 8.53 | 3:1 | ✅ |
| `--color-ring` | `--color-surface-user` | 6.43 | 6.58 | 3:1 | ✅ |
| `--color-accent` (nền nút) | `--color-background` | 6.05 | 3.89 | 3:1 | ✅ |
| `--color-quota-normal` | `--color-quota-track` | 4.96 | 5.57 | 3:1 | ✅ |
| `--color-quota-warning` | `--color-quota-track` | 3.75 | 6.59 | 3:1 | ✅ |
| `--color-quota-empty` | `--color-quota-track` | 5.98 | 5.05 | 3:1 | ✅ |
| `--color-chart-1` | `--color-background` | 8.24 | 4.91 | 3:1 | ✅ |
| `--color-chart-2` | `--color-background` | 3.46 | 10.91 | 3:1 | ✅ |
| `--color-chart-1` | `--color-surface-panel` | 8.90 | 4.21 | 3:1 | ✅ |
| `--color-chart-2` | `--color-surface-panel` | 3.74 | 9.36 | 3:1 | ✅ |

## 6. Hai màu chuỗi dữ liệu của biểu đồ

Yêu cầu: tách bạch với nhau, tách bạch với nền, và tách bạch **khi in trắng đen**.
Điều kiện in trắng đen = chênh lệch độ sáng giữa hai màu; hệ đặt ngưỡng ≥ 2:1.

| Cặp | Sáng | Tối | Ngưỡng | Đạt |
|---|---:|---:|---:|:--:|
| `--color-chart-1` (metered) ↔ `--color-chart-2` (unmetered) | 2.38 | 2.22 | 2:1 | ✅ |

Hai màu còn khác tông (đỏ ↔ lam) nên phân biệt được với cả deuteranopia và
protanopia. Vẫn nên gắn nhãn trực tiếp lên cột, không chỉ dựa vào chú giải màu.

## 7. Phân tầng bề mặt

Không phải ngưỡng WCAG (hai bề mặt kề nhau không cần 3:1). Ngưỡng thực dụng
là ≥ 1.05 cộng với viền hoặc shadow.

| Cặp bề mặt | Sáng | Tối | Ngưỡng | Đạt |
|---|---:|---:|---:|:--:|
| sidebar ↔ nền app | 1.083 | 1.067 | 1.05 | ✅ |
| panel nổi ↔ nền app | 1.080 | 1.166 | 1.05 | ✅ |
| bong bóng assistant ↔ nền app | 1.080 | 1.095 | 1.05 | ✅ |
| bong bóng user ↔ nền app | 1.057 | 1.215 | 1.05 | ✅ |
| bong bóng assistant ↔ bong bóng user | 1.142 | 1.110 | 1.05 | ✅ |
| khối code ↔ bong bóng assistant | 1.266 | 1.190 | 1.05 | ✅ |
| khối code ↔ bong bóng user | 1.108 | 1.320 | 1.05 | ✅ |
| hover hàng ↔ nền app | 1.110 | 1.111 | 1.02 | ✅ |

Ở theme sáng, `surface-panel` và `surface-assistant` cùng là `#ffffff`: panel phân biệt
bằng `--shadow-popover`, bong bóng assistant phân biệt bằng `--color-border`. Đây là
lựa chọn có chủ đích — thêm một sắc trắng thứ hai chỉ tạo bẩn, không tạo thông tin.

## 8. Những chỗ đã cân nhắc và loại bỏ

- **Dùng thẳng đỏ son làm chữ.** `--color-accent` ở theme tối chỉ đạt
  3.89:1 trên nền app — dưới ngưỡng chữ.
  Vì vậy mới có `--color-accent-text` (8.00:1).
- **Danger trùng accent.** Cả hai đều đỏ thì người dùng không đọc được ý nghĩa.
  Danger dịch về đỏ thẫm lạnh (hue ~345°), accent giữ đỏ son ấm (hue ~8°), và danger
  hầu như chỉ xuất hiện dưới dạng chữ hoặc viền, hiếm khi là nền đặc.
- **Warning nền đặc + chữ trắng.** `#b45309` với chữ trắng chỉ đạt
  5.02:1. Warning vì thế là màu đồ hoạ (thanh quota, chấm, icon);
  phần chữ dùng `--color-warning-text` trên `--color-warning-subtle`.
- **Hover sáng lên ở theme tối.** `#de4e3b` với chữ trắng chỉ đạt 3.99:1. Ở theme tối
  trạng thái hover của nút nhấn vì thế đậm xuống chứ không sáng lên.
- **Sidebar sáng hơn nền app ở theme tối.** Đã thử, nhưng sidebar là tầng lùi về sau;
  hệ để sidebar tối hơn nền app (1.067)
  và dùng `--color-border` để cắt cạnh.
