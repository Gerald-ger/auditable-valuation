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
    # Added 2026-08-31. Fourth miss of the same class and a new shape: this one
    # is not hyphenated at all, it simply sits on a line that never says
    # "test" — the word is on the line below it. It had been wrong since before
    # the guard existed, by 22 and then by 24.
    ("README.md", r"\*\*(\d+) of those run offline\*\*", "total"),
    # Added 2026-08-30 after an independent re-verification found it. Third
    # miss of the same shape: the count is hyphenated *and* has a word before
    # "suite", so both the "N tests" sweep and the "N-test suite" sweep that
    # was widened to catch the last one walked past it.
    ("backend/tests/fixtures/PROVENANCE.md",
     r"the (\d+)-test backend suite", "backend"),
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


def _measured(request) -> dict[str, int]:
    """The three counts, or skip because this run cannot see all of them."""
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
    return {"backend": backend, "frontend": frontend, "total": backend + frontend}


# The files the two checks below cover, taken from `CLAIMS` so the pair cannot
# drift apart: a claim added to a new file brings that file under both.
GUARDED_FILES = tuple(dict.fromkeys(name for name, _, _ in CLAIMS))

# A three- or four-digit number on a line that mentions tests is a count claim,
# unless it is something else wearing the same shape. Both exclusions were
# measured rather than imagined: a unit after it makes it a size — the fixtures
# directory's "297 KB" — and a dot after it makes it a Hong Kong ticker,
# `0002.HK` and `1177.HK`, of which this repository is full. Percent-encoding is
# deliberately *not* excluded, so the badge URL's `tests-1008%20offline` is still
# seen. Verified 2026-08-30: zero unaccounted numbers across the guarded files.
COUNT_SHAPED = re.compile(
    r"(?<![.\d])\b(\d{3,4})\b(?!\.|\s*(?:KB|MB|GB|kB|bytes|lines|chars|characters))")


def test_no_test_count_in_those_files_is_unaccounted_for(request):
    """The completeness half: `CLAIMS` says the numbers we know about are right,
    this says there are no numbers we do not know about.

    It exists because the same blind spot got past three separate sweeps in one
    day. `780 tests` was found. `780-test suite` was not, and was found by a
    reviewer. The pattern was widened to catch that, and `780-test backend
    suite` — the same shape with one word inserted — was not caught either, and
    was found by the next reviewer. Each widening was cut to fit the last miss,
    and the next instance sat just outside it.

    A net that fails on any number it cannot account for does not need widening.
    The cost is that a new, correct number in a new phrasing also fails, and has
    to be added to `CLAIMS` or given a shape this ignores — which is the right
    trade, because that is the moment someone is looking at it.
    """
    measured = _measured(request)
    known = set(measured.values())

    unaccounted = []
    for name in GUARDED_FILES:
        for i, line in enumerate(
                (ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower()
            # "offline" as well as "test", because the fourth miss said neither
            # on its own line: README's "**987 of those run offline**" carries
            # the count while the word "test" sits on the line below. Measured
            # 2026-08-31 across the guarded files, adding it surfaces exactly
            # that one number and no false positive.
            if "test" not in lowered and "offline" not in lowered:
                continue
            for m in COUNT_SHAPED.finditer(line):
                if int(m.group(1)) not in known:
                    unaccounted.append(f"  {name}:{i} has {m.group(1)} — "
                                       f"{line.strip()[:70]}")

    assert not unaccounted, (
        "A test-count-shaped number in a guarded file matches none of the three "
        "real counts. Either it is a claim that has gone stale, or it is not a "
        "count at all and needs a shape this check skips:\n"
        + "\n".join(unaccounted)
        + f"\n\nThe real counts are {measured['backend']} backend, "
          f"{measured['frontend']} frontend, {measured['total']} offline.")


def test_the_documented_test_counts_are_the_ones_that_ran(request):
    measured = _measured(request)
    backend, frontend = measured["backend"], measured["frontend"]

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
