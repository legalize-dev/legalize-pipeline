"""Catching Holland up writes each law's missed versions in date order, once.

``legalize daily --date D`` asks the SRU for every law modified on or after D and
renders each as it stood on D, so a range catch-up rolled newer text back to older
text and re-committed ~380 laws a day (1,910 bad commits were published before it
was stopped). The catch-up plans per law, from the versions the source lists.
"""

from __future__ import annotations

from datetime import date

from legalize.fetcher.nl import catchup


class FakeRepo:
    """Answers ``git show HEAD:nl/<id>.md`` with a frontmatter holding last_updated."""

    def __init__(self, last_updated: dict[str, str]):
        self._last = last_updated

    def _run(self, args, check=True):
        law = args[1].removeprefix("HEAD:nl/").removesuffix(".md")
        if law not in self._last:
            return ""
        return f'---\nidentifier: "{law}"\nlast_updated: "{self._last[law]}"\n---\n'


class FakeClient:
    def __init__(self, expressions: dict[str, list[str]]):
        self._exp = expressions

    def list_expressions(self, law_id):
        return [(d, f"{d}/xml/{law_id}.xml") for d in self._exp[law_id]]


class FakeDiscovery:
    def __init__(self, ids):
        self._ids = ids

    def discover_daily(self, client, since):
        yield from self._ids


UNTIL = date(2026, 10, 7)


class TestPlan:
    def test_only_versions_after_the_files_last_write_and_not_after_until(self):
        repo = FakeRepo({"A": "2026-04-15"})
        client = FakeClient({"A": ["2026-01-01", "2026-04-15", "2026-10-01", "2026-12-01"]})

        missing, _ = catchup.plan(repo, client, ["A"], UNTIL)

        # 2026-01-01 and 2026-04-15 are in the file already; 2026-12-01 has not happened.
        assert missing == [("2026-10-01", "A")]

    def test_oldest_first_across_laws_and_in_order_within_each(self):
        repo = FakeRepo({"A": "2026-01-01", "B": "2026-01-01"})
        client = FakeClient({"A": ["2026-09-01", "2026-10-01"], "B": ["2026-08-15", "2026-09-01"]})

        missing, _ = catchup.plan(repo, client, ["B", "A"], UNTIL)

        assert missing == [
            ("2026-08-15", "B"),
            ("2026-09-01", "A"),
            ("2026-09-01", "B"),
            ("2026-10-01", "A"),
        ]
        for law in ("A", "B"):
            own = [d for d, i in missing if i == law]
            assert own == sorted(own)

    def test_a_law_with_no_file_is_a_new_law_not_a_missed_version(self):
        repo = FakeRepo({})
        client = FakeClient({"N": ["2026-09-01"]})

        missing, without_file = catchup.plan(repo, client, ["N"], UNTIL)

        assert missing == []
        assert without_file == ["N"]

    def test_a_law_already_up_to_date_plans_nothing(self):
        repo = FakeRepo({"A": "2026-10-01"})
        client = FakeClient({"A": ["2026-09-01", "2026-10-01"]})

        assert catchup.plan(repo, client, ["A"], UNTIL)[0] == []


class TestCatchUp:
    def test_a_failed_version_stops_that_law_but_not_the_others(self):
        repo = FakeRepo({"A": "2026-01-01", "B": "2026-01-01"})
        client = FakeClient({"A": ["2026-09-01", "2026-10-01"], "B": ["2026-09-15"]})
        wrote = []

        def write(repo_, client_, meta, text, law_id, day):
            if (law_id, day.isoformat()) == ("A", "2026-09-01"):
                raise RuntimeError("source down")
            wrote.append((law_id, day.isoformat()))
            return True

        written, errors, _ = catchup.catch_up(
            repo,
            client,
            FakeDiscovery(["A", "B"]),
            None,
            None,
            date(2026, 8, 24),
            UNTIL,
            write=write,
        )

        # B lands; A's second version is not written over a gap in A's history.
        assert wrote == [("B", "2026-09-15")]
        assert written == 1
        assert any("A 2026-09-01: source down" in e for e in errors)
        assert any("A 2026-10-01: skipped" in e for e in errors)
