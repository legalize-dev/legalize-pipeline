"""Slice boundaries for `legalize push`.

Getting these wrong is expensive in a way tests are cheap: an off-by-one pushes
a tip the remote is already past, which git reports as "non-fast-forward" — a
message about the ref that says nothing about the real mistake.
"""

import pytest

from legalize.pipeline import slice_boundaries


def test_exact_multiple_still_ends_with_head():
    commits = [f"c{i}" for i in range(10)]
    # 10 commits in slices of 5: boundaries at c4 and c9, plus HEAD for the
    # (empty) remainder — pushing HEAD when it is already the tip is a no-op.
    assert slice_boundaries(commits, 5) == ["c4", "c9", "HEAD"]


def test_remainder_is_covered_by_head():
    commits = [f"c{i}" for i in range(12)]
    assert slice_boundaries(commits, 5) == ["c4", "c9", "HEAD"]


def test_history_shorter_than_one_slice_is_a_single_push():
    assert slice_boundaries(["a", "b"], 25000) == ["HEAD"]


def test_boundaries_are_in_ancestor_order():
    commits = [f"c{i}" for i in range(100)]
    boundaries = slice_boundaries(commits, 25)
    positions = [commits.index(sha) for sha in boundaries if sha != "HEAD"]
    assert positions == sorted(positions), "a later slice must never precede an earlier one"


def test_zero_slice_size_is_rejected():
    with pytest.raises(ValueError):
        slice_boundaries(["a"], 0)
