"""Tầng model: một protocol duy nhất cho cả hệ thống (§9.1, A9).

`client.py` khai `LLMClient` + `Chunk`; `adapters/` cài đặt nó bằng SDK
`openai`; `parser.py` là code chuẩn hoá stream mà mọi adapter dùng CHUNG.
Không module nào ngoài `adapters/` được import SDK của provider (ADR-03).
"""
