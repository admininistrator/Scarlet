"""Tiến trình worker: nơi DUY NHẤT được phép đợi model (§5.2, A1).

Bảng ranh giới §5.2 chia đôi hệ thống ở đúng chỗ này. `api` tạo record rồi
`enqueue` và trả `202` trong dưới 100 ms; mọi thứ kéo dài hơn hai giây — gọi
LLM, gọi tool, ghi Redis Stream — sống trong các module ở đây (A1).

`main.py` là điểm vào của lệnh `arq app.workers.main.WorkerSettings` (Phụ lục
C); mỗi job một file riêng — hôm nay có `generate.py`, §23 xếp sẵn chỗ cho
`title.py`, `extract.py` và `reaper.py`.
"""
