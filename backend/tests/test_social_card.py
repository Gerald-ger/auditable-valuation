"""The social card's title, checked against the README's.

The card carried the project's *old* name for four days. `5d97578` renamed the
project on 2026-08-28 and swept every text surface in the repository; a PNG is
not a text surface, so the rename could not reach it and nothing afterwards
could see it — not grep, not the link checker, not `test_documented_counts.py`,
not any of CI's eight legs. It was found by eye, which is the only instrument
that was ever pointed at it.

Committing `docs/images/social-card.html` beside the PNG is what makes this test
possible: the card's words are text again, and text is the one thing this repo
already knows how to guard.

What this test cannot see, stated so nobody mistakes its coverage for more than
it is:

  * Whether `social-preview.png` was rendered from the HTML this test read. It
    can be an old image beside a corrected source and this stays green. A test
    that re-rendered and compared bytes cannot run — CI is Ubuntu and has no
    'Segoe UI Variable Text', so all three operating systems would disagree with
    the committed bytes for reasons that are not defects.
  * Whether the image is the one uploaded to GitHub's social-preview setting,
    which lives outside git and has no API. Same blindness the count guard
    records for the About description.
  * The card's claim line. It is a compression of README's model list, not a
    quotation of it, so no equality check applies and a fuzzy one would pass
    whatever it was given. Left unguarded rather than guarded for show.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

CARD = ROOT / "docs" / "images" / "social-card.html"
README = ROOT / "README.md"


def test_the_social_card_carries_the_projects_current_name():
    html = CARD.read_text(encoding="utf-8")

    # Exactly once, for the same reason `CLAIMS` insists on it next door: a
    # rewrite that leaves two h1s, or none, must fail the check rather than
    # quietly pick one and keep passing.
    titles = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    assert len(titles) == 1, f"{CARD.name}: expected one <h1>, found {len(titles)}"
    card_title = titles[0].strip()

    first_line = README.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("# "), f"README.md:1 is not an h1: {first_line!r}"
    readme_title = first_line[2:].strip()

    assert card_title == readme_title, (
        f"{CARD.name} says {card_title!r} and README.md:1 says {readme_title!r}. "
        "If the project was renamed, re-render the card and upload the PNG at "
        "Settings -> General -> Social preview; the render command is in the "
        "comment at the top of the HTML."
    )
