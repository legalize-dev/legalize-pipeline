"""Render a country repo's ``LICENSE`` file from :mod:`legalize.country_meta`.

Unlike the README (written in the country's native language), the LICENSE is
written in English so it is universally readable, with the country's own
data-license statement embedded verbatim. The pipeline code is MIT; the
legislative content follows each official source's terms (``meta.data_license``).

Like the README and funding config, this is a repo-level meta file, NOT a law
file and NOT part of the legislative record.
"""

from __future__ import annotations

from legalize.country_meta import CountryMeta

PIPELINE_URL = "https://github.com/legalize-dev/legalize-pipeline"


def render_license(meta: CountryMeta) -> str:
    """Render the English ``LICENSE`` text for one country repo."""
    return (
        f"LEGALIZE — {meta.name}: legislation as open data\n"
        "\n"
        "SOFTWARE / PIPELINE\n"
        "The software that generates and maintains this repository is open source\n"
        f"under the MIT License:\n"
        f"  {PIPELINE_URL}\n"
        "\n"
        "LEGISLATIVE CONTENT (DATA)\n"
        f"{meta.data_license}\n"
        "These are official public-sector texts reproduced from their official\n"
        "source. The original source of each document is recorded in the `source`\n"
        "field of that file's YAML front matter.\n"
        "\n"
        "DISCLAIMER\n"
        "Automated reproduction of official sources. This is not an official or\n"
        "verified legal text. Always consult the official source for authoritative\n"
        "versions.\n"
    )
