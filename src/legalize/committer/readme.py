"""Render a country repo's README from :mod:`legalize.country_meta`.

The README is written in the country's native language. Section labels come from
:data:`legalize.country_meta.LABELS` (loaded from ``readme_data.json``); languages
not present fall back to English.
"""

from __future__ import annotations

from legalize.country_meta import LABELS, CountryMeta


def render_readme(meta: CountryMeta) -> str:
    """Render the README Markdown for one country."""
    labels = LABELS.get(meta.language, LABELS["en"])
    out: list[str] = [f"# legalize-{meta.code}", ""]
    out.append(labels["tagline"].format(name=meta.name))
    out.append("")
    out.append(labels["intro"])

    if meta.scope:
        out += ["", meta.scope]

    if meta.norm_types:
        out += ["", f"## {labels['whats_inside']}", ""]
        for nt in meta.norm_types:
            head = f"**{nt.label}**"
            if nt.pattern:
                head += f" (`{nt.pattern}`)"
            tail = ""
            if nt.examples:
                tail = " — " + ", ".join(f"`{e}`" for e in nt.examples)
            elif nt.note:
                tail = " — " + nt.note
            out.append(f"- {head}{tail}")

    if meta.source_name:
        out += ["", f"## {labels['source']}", "", f"- **{meta.source_name}**"]
        for url in meta.source_urls:
            out.append(f"  - {url}")

    if meta.attribution:
        out += ["", f"## {labels['attribution']}", "", meta.attribution]

    if meta.notes:
        out += ["", meta.notes.strip()]

    out += ["", f"## {labels['other_countries']}", "", labels["other_countries_body"]]

    out += ["", f"## {labels['support']}", "", labels["support_body"]]

    out += [
        "",
        f"## {labels['license']}",
        "",
        "- " + labels["license_code"],
        "- " + labels["license_data"].format(data_license=meta.data_license),
    ]

    return "\n".join(out) + "\n"
