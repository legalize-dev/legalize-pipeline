"""Repo-level meta files committed to each country repo.

These are NOT law files and are NOT part of the legislative record. They are
project metadata (funding config today; README / LICENSE could be added here
later). They are committed as a standalone meta commit which the reform-history
sync ignores, because they carry no ``Source-Date`` trailer (see
``state/store.py``).
"""

from __future__ import annotations

# GitHub-native funding config. Renders a "Sponsor" button on every repo and
# keeps the support links identical across all country repos, the hub, and the
# website. Use the project-branded accounts, never a personal one.
FUNDING_YML = """\
# Support Legalize — open legal data for everyone.
# https://legalize.dev
buy_me_a_coffee: legalizedev
"""


def repo_meta_files(country: str) -> dict[str, str]:
    """Return the repo-level meta files to write for a country repo.

    Maps ``relative_path -> content``. The funding config is identical
    everywhere; the README is generated in the country's own language when
    presentation metadata exists for it (see :mod:`legalize.country_meta`).
    """
    from legalize.committer.readme import render_readme
    from legalize.country_meta import COUNTRY_META

    files = {".github/FUNDING.yml": FUNDING_YML}

    meta = COUNTRY_META.get(country)
    if meta is not None:
        files["README.md"] = render_readme(meta)

    return files
