"""Report country repos that have gone quiet for longer than their cadence allows.

The existing alert in ``engine-alert.yml`` turns a failed or cancelled scheduled
run into an issue. It cannot see the other way a country stops publishing: a run
that ends **green** having committed nothing, every day, for months. That is not
hypothetical — ``it`` and ``pl`` sat that way from April to the end of August
(#115), and ``co``/``ch``/``ar`` did the same from the cancelled side (#114).
On every dashboard we have, a healthy country and a dead one look identical.

So this asks the only question that distinguishes them: when did the repo last
receive anything?

Prints one ``code<TAB>cadence<TAB>days<TAB>limit`` line per silent country.
"""

from __future__ import annotations

import glob
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

WORKFLOWS = pathlib.Path(__file__).resolve().parents[1] / "workflows"

# Generous on purpose, because a false alarm here costs more than a late one:
# the whole value of this check is that an issue from it means something. A
# daily country that has published nothing in two weeks is not having a quiet
# fortnight, and a monthly one gets its cadence plus a full extra cycle.
LIMIT_DAYS = {"daily": 14, "monthly": 45}


def scheduled_countries() -> dict[str, str]:
    """Map country code -> cadence, read from the workflows themselves.

    Never a second list maintained here: a country added to the daily matrix is
    watched the same day, and one removed stops being watched, with no chance of
    the two drifting apart.
    """
    daily_yml = (WORKFLOWS / "daily-update.yml").read_text()
    # Two JSON arrays sit on that line: the workflow_dispatch override
    # (`["{0}"]`) and the real matrix. The matrix is the longer one.
    matrix = max(re.findall(r"'(\[[^\]]*\])'", daily_yml), key=len)
    cadence = {code: "daily" for code in json.loads(matrix)}
    for path in glob.glob(str(WORKFLOWS / "monthly-update-*.yml")):
        cadence.setdefault(pathlib.Path(path).stem.rsplit("-", 1)[-1], "monthly")
    return cadence


def main() -> int:
    cadence = scheduled_countries()
    repos = json.loads(
        subprocess.run(
            ["gh", "search", "repos", "--owner", "legalize-dev",
             "--topic", "legalize-country", "--limit", "100",
             "--json", "name,pushedAt"],
            capture_output=True, text=True, check=True,
        ).stdout
    )

    now = datetime.now(timezone.utc)
    silent = []
    for repo in repos:
        code = repo["name"].removeprefix("legalize-")
        how_often = cadence.get(code)
        if how_often is None:
            continue  # unscheduled on purpose — silence is the expected state
        # pushed_at, not the date of the last commit: country repos carry
        # commits dated from the source, and some of those dates are in the
        # future (`it` has one at 2027-01-11), so commit dates cannot order
        # anything. A meta push (README, LICENSE) does reset this, which makes
        # the check miss a country for one cycle rather than cry wolf.
        days = (now - datetime.fromisoformat(repo["pushedAt"])).days
        if days > LIMIT_DAYS[how_often]:
            silent.append((code, how_often, days, LIMIT_DAYS[how_often]))

    for row in sorted(silent, key=lambda r: -r[2]):
        print("\t".join(str(field) for field in row))
    print(f"{len(silent)} silent of {len(cadence)} scheduled", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
