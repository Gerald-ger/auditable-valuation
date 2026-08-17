"""Guard the one place a docs/ file is a runtime dependency.

ai_client builds its system prompt from an excerpt of
docs/financial-models-reference.md, so that document is not just documentation —
it is what grounds every AI answer in the project's own methodology.

_reference_excerpt swallows OSError and returns "" when the file cannot be read.
That is the right behaviour at runtime (the chat should still work without the
reference) but it means reorganising docs/ would silently strip the methodology
out of the prompt: no error, no log line, just quietly worse answers. This test
is what turns that into a red CI run.
"""
from __future__ import annotations

from backend import ai_client


def test_reference_doc_is_readable_and_lands_in_the_prompt():
    excerpt = ai_client._reference_excerpt()
    assert excerpt, f"unreadable or empty: {ai_client.REFERENCE_DOC}"
    assert excerpt in ai_client._system_prompt("")
