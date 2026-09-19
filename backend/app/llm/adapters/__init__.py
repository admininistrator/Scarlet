"""Cài đặt cụ thể của `LLMClient` (§9.1).

`OpenAICompatAdapter` là thân chung (một `stream()`, một parser — cạm bẫy của
T-2.15). Hai lớp con khác nhau đúng phần bảng §9.1 nói là khác:
`SystemAdapter` (qua LiteLLM, tính vào quota) và `ByokAdapter` (thẳng tới
`provider.base_url`, khoá của user, không trừ quota — §10.5).
"""
