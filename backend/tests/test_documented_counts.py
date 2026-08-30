"""The test counts written in the docs, checked against the suite that is running.

This number has gone stale four times: 409, then 793, then 856, then 987, each
correct when written. It is on the most-read line in the repository — the README
badge, which is also what search results and link previews show — and nothing in
the toolchain ever forced a second look at it, because adding a test does not
touch the file that counts them.

A test rather than a CI step, deliberately. CI would catch this after a push; a
test catches it before the commit, on whatever machine ran the suite, on all
three operating systems in the matrix, and without a new top-level directory in
a repository whose root clutter is already a recorded finding.

The frontend half is counted statically — by reading the `it(` and `test(` calls
out of `frontend/src/**/*.test.*` — because pytest cannot run vitest. Measured
2026-08-30, that count is 215 against vitest's own reported 215, and the two have
agreed at every size this file has been checked at. If they ever diverge the
static reading is the wrong one, and the fix is to stop counting this way rather
than to adjust the number.

What this file cannot see: the GitHub *About* description, which lives outside
git, is edited in a web form, and is where this number has actually been going
stale. It is recorded in TODOLIST.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# (file, pattern with one capture group, which count it claims). The pattern
# must match exactly once: a doc rewrite that moves the number would otherwise
# silently disable the check rather than fail it, which is how a guard becomes
# decoration.
CLAIMS = (
    ("README.md", r"\[!\[(\d+) offline tests\]", "total"),
    ("README.md", r"badge/tests-(\d+)%20offline", "total"),
    ("README.md", r"\| (\d+) offline, and what they are for", "total"),
    ("README.md", r"pytest\s+# (\d+) tests, offline", "backend"),
    ("README.md", r"npm test\s+# (\d+) tests", "frontend"),
    ("README.md", r"this repo — (\d+) backend", "backend"),
    # Added 2026-08-30 after the guard shipped without it: the count is
    # hyphenated here, so every sweep that looked for "N tests" walked past it.
    ("README.md", r"the (\d+)-test suite runs entirely offline", "backend"),
    ("README.md", r"backend, (\d+) frontend, seconds", "frontend"),
    ("docs/testing.md", r"pytest\s+# (\d+) tests, offline", "backend"),
    ("docs/testing.md", r"npm test\s+# (\d+) tests", "frontend"),
)

# Not guarded, and deliberately: the count of `network`-marked tests. They carry
# a module-level `pytestmark`, so a static reading of the sources finds zero, and
# they are excluded from `session.items` — neither half of this file's method can
# see them. Two other numbers that used to be written down were derived from this
# one (the collected total, and the count CI reports after one conditional skip);
# both were removed from docs/testing.md rather than guarded, because a number
# that is a sum of two others is best not restated at all.


def _frontend_test_count() -> int:
    """Test cases declared under `frontend/src`, counted without running them."""
    return sum(
        len(re.findall(r"^\s*(?:it|test)\(", p.read_text(encoding="utf-8"), re.M))
        for p in sorted((ROOT / "frontend" / "src").rglob("*.test.*"))
    )


def test_the_documented_test_counts_are_the_ones_that_ran(request):
    config = request.config
    # A filtered run counts a subset, and asserting on it would fail for the
    # wrong reason. `file_or_dir` is empty only when pytest fell back to the
    # `testpaths` in pytest.ini, which is what a plain run and CI both do.
    #
    # `--lf` and `--stepwise` are here because of the failure they cause rather
    # than by symmetry: they select from pytest's own cache without touching any
    # of the three options above, and rerunning with `--lf` is exactly what a
    # developer does *after* seeing this test fail. Without this arm the second
    # run reports "the suite has 3 backend tests", which is a worse message than
    # the one they were trying to act on.
    if (config.option.keyword or config.option.file_or_dir
            or config.option.markexpr != "not network"
            or getattr(config.option, "lf", False)
            or getattr(config.option, "stepwise", False)):
        pytest.skip("a filtered run cannot count the suite")

    backend = len(request.session.items)
    frontend = _frontend_test_count()
    measured = {"backend": backend, "frontend": frontend,
                "total": backend + frontend}

    wrong = []
    for name, pattern, kind in CLAIMS:
        text = (ROOT / name).read_text(encoding="utf-8")
        found = re.findall(pattern, text)
        assert len(found) == 1, (
            f"{name}: the pattern {pattern!r} matched {len(found)} times, so this "
            f"check is no longer reading what it thinks it reads")
        claimed = int(found[0])
        if claimed != measured[kind]:
            line = next(i for i, ln in enumerate(text.splitlines(), 1)
                        if re.search(pattern, ln))
            wrong.append(f"  {name}:{line} claims {claimed} {kind} tests, "
                         f"the suite has {measured[kind]}")

    assert not wrong, (
        "The documented test counts have gone stale again:\n" + "\n".join(wrong)
        + f"\n\nMeasured now: {backend} backend + {frontend} frontend "
          f"= {backend + frontend} offline.")
