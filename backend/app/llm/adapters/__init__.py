"""Cài đặt cụ thể của `LLMClient` (§9.1).

`SystemAdapter` (qua LiteLLM) có ở đây từ T-1.3. `ByokAdapter` (key của user,
gọi thẳng `provider.base_url` trong catalog) thuộc Phase 2 và sẽ dùng chung
`app/llm/parser.py`, không viết lại code parse stream.
"""
