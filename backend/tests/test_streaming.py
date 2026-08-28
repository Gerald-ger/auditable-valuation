"""The NDJSON wrapper behind the four AI endpoints, which had no tests at all.

`/ai/chat`, `/ai/predict/{t}`, `/score/{t}/narrative` and `/ai/debate/{t}` all
return through `main._ndjson`, and until 2026-08-28 every one of them answered
**200** no matter what happened — including when the model was never reached.
A client doing the ordinary thing could not see a failure:

    r = requests.post(".../ai/debate/AAPL", stream=True)
    r.raise_for_status()            # never raised

The app's own `stream()` was never fooled — it checks `res.ok` and reads
`detail` off the body (frontend/src/api.js) — so nothing visible was wrong, and
nothing would have reported it.

These use `asyncio.run` rather than pytest-asyncio: `requirements-test.txt` is
deliberately the minimum needed to lint and run offline, and five tests do not
justify a sixth entry in it.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from backend import ai_client, main


async def _gen(events, raise_after=None):
    """A stream that yields `events`, then optionally fails."""
    for e in events:
        yield e
    if raise_after is not None:
        raise raise_after


async def _collect(response) -> list[dict]:
    """Everything a StreamingResponse would put on the wire, parsed."""
    out = []
    async for chunk in response.body_iterator:
        for line in chunk.decode().splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def test_a_model_that_was_never_reached_answers_503_rather_than_200():
    """The common case, and the one that was invisible.

    `ai_client` raises AIUnavailable from the `except (ClientError, TimeoutError)`
    wrapped around `session.post`, so an absent Ollama fails on connect — before
    any event exists. Nothing is on the wire yet, so a real status is still
    possible, and this is the path every request takes today: Ollama has never
    been installed on the machine this is developed on.
    """
    boom = ai_client.AIUnavailable("Local AI unreachable (Cannot connect to host).")

    async def go():
        with pytest.raises(HTTPException) as excinfo:
            await main._ndjson(_gen([], raise_after=boom))
        return excinfo.value

    exc = asyncio.run(go())
    assert exc.status_code == 503
    # `detail`, not some other key: frontend/src/api.js reads `err.detail`, and
    # any other shape shows the reader `res.statusText` instead of the reason.
    assert "Local AI unreachable" in exc.detail


def test_an_unexpected_failure_before_the_stream_starts_is_a_500():
    """Not every pre-stream failure is the model being absent."""
    async def go():
        with pytest.raises(HTTPException) as excinfo:
            await main._ndjson(_gen([], raise_after=ValueError("bad context")))
        return excinfo.value

    exc = asyncio.run(go())
    assert exc.status_code == 500
    assert "bad context" in exc.detail


def test_a_failure_after_the_first_event_stays_200_and_keeps_what_was_sent():
    """HTTP's asymmetry, pinned rather than assumed.

    Once one event is out, 200 is on the wire and cannot be withdrawn, so a
    mid-stream failure has to arrive in the body. `ai_client` raises AIUnavailable
    from here too — a chunk carrying `{"error": ...}` — and this half genuinely
    cannot become a status code.
    """
    boom = ai_client.AIUnavailable("model errored mid-reply")
    sent = [{"delta": "Apple "}, {"delta": "looks"}]

    async def go():
        resp = await main._ndjson(_gen(sent, raise_after=boom))
        return resp.status_code, await _collect(resp)

    status, events = asyncio.run(go())
    assert status == 200
    assert events[:2] == sent, "the events that did make it were lost"
    assert events[-1] == {"error": "ai_unavailable", "message": "model errored mid-reply"}


def test_the_peek_does_not_swallow_the_first_event():
    """The one regression this design could introduce, and the reason for a test.

    `_ndjson` pulls a single event before returning, to learn whether the stream
    can start at all. If that event were not replayed into the body, every AI
    reply in the app would silently lose its first token — and with `delta`
    fragments that is a missing word, not a visible break.
    """
    sent = [{"delta": "one"}, {"delta": "two"}, {"delta": "three"}]

    async def go():
        return await _collect(await main._ndjson(_gen(sent)))

    assert asyncio.run(go()) == sent


def test_a_stream_that_yields_nothing_is_an_empty_200_not_an_error():
    """A model with nothing to say is not a failure, and was not one before."""
    async def go():
        resp = await main._ndjson(_gen([]))
        return resp.status_code, await _collect(resp)

    status, events = asyncio.run(go())
    assert status == 200
    assert events == []
