from __future__ import annotations

from app.sse import SSEEventFormatter, format_sse_event


def test_format_sse_event_uses_compact_utf8_json() -> None:
    event = format_sse_event("metadata", {"mode": "rag", "answer": "中文"})

    assert event == 'event: metadata\ndata: {"mode":"rag","answer":"中文"}\n\n'


def test_delta_events_include_monotonic_sequence_numbers() -> None:
    formatter = SSEEventFormatter()

    first = formatter.delta("客户")
    second = formatter.delta(" P1")

    assert first == 'event: delta\ndata: {"seq":1,"text":"客户"}\n\n'
    assert second == 'event: delta\ndata: {"seq":2,"text":" P1"}\n\n'


def test_error_and_done_events() -> None:
    formatter = SSEEventFormatter()

    assert (
        formatter.error("llm_upstream_error", "LLM stream failed")
        == 'event: error\ndata: {"code":"llm_upstream_error","message":"LLM stream failed"}\n\n'
    )
    assert formatter.done() == 'event: done\ndata: {"status":"ok"}\n\n'
    assert formatter.done(status="error") == 'event: done\ndata: {"status":"error"}\n\n'
