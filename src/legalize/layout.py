"""Where a law file lives — Legalize Format Spec v0.4.

The spec makes a repo declare its own shape instead of a consumer assuming one:
``.legalize.yml`` carries a path template, and a consumer fills it in to find
the file. See the hub's ``SPEC.md``, §Directory layout.

A placeholder is one of two things, and the difference is the whole design:

* a **derived** value the spec defines for every country — ``{directory}``,
  ``{identifier}``, ``{id_sha1_2}``;
* a **field**, which is any key of the law's own YAML frontmatter, used
  verbatim.

Opening it to fields is what lets a country choose a shape nobody anticipated
without a spec change, and it costs nothing to specify: the value is written in
the file it names, so a consumer holding the law's metadata can rebuild the path
with no country-specific code. It is also what the layout already did — the
``{directory}`` of v0.3 was the ``jurisdiction`` field under another name.

This module is the engine's single copy of that rule. It builds the paths *and*
writes the manifest that tells consumers how to rebuild them, from the same
dict — a manifest generated anywhere else could describe a layout the engine
does not actually produce, and the failure mode is every law's metadata
resolving while every body 404s.
"""

from __future__ import annotations

import hashlib
import string
from datetime import date

from legalize.models import NormMetadata

SPEC_VERSION = "0.4"

# The shapes in use. A country's template is a plain string so that a new one
# costs an entry in LAYOUT and nothing else.
FLAT = "{directory}/{identifier}.md"
SHARDED = "{directory}/{id_sha1_2}/{identifier}.md"

# Values the spec defines for every country, whatever its frontmatter holds.
# Anything else in a template is a frontmatter field, read from the law itself.
#
# Each takes a lookup function rather than an object, so the same definitions
# serve both sides of the spec: the publisher resolving them from a norm it is
# about to write, and a consumer resolving them from the frontmatter of a file
# it has read. Two implementations of one rule is the failure this whole module
# exists to prevent, so there is one.
DERIVED = {
    "directory": lambda get: get("jurisdiction") or get("country"),
    "identifier": lambda get: get("identifier"),
    "id_sha1_2": lambda get: hashlib.sha1(str(get("identifier")).encode("utf-8")).hexdigest()[:2],
}

# A path segment is a directory name, so a value carrying a separator or a
# traversal would silently write outside the tree it was meant to. The values
# come from official sources, which is exactly why this is checked rather than
# trusted: the parser is the only thing between a source's free-text field and
# a file path, and it changes every time a country is onboarded.
_FORBIDDEN = ("/", "\\", "\x00")


class TemplateError(ValueError):
    """A template that cannot be resolved. Never a guess, always a stop.

    A wrong path returns a 404 for a law that exists, which is the hardest
    failure here to notice: the metadata still resolves and only the body is
    missing, on every page at once.
    """


def placeholders_of(template: str) -> list[str]:
    """The placeholder names a template uses, in order."""
    return [name for _, name, _, _ in string.Formatter().parse(template) if name]


def _norm_lookup(metadata: NormMetadata):
    """Field lookup for a norm the pipeline is about to write."""

    def get(name: str):
        value = getattr(metadata, name, None)
        return dict(metadata.extra).get(name) if value is None else value

    return get


def _values(get, template: str, whose: str) -> dict[str, str]:
    """Resolve every placeholder a template uses, or refuse to build a path."""
    out: dict[str, str] = {}
    for name in placeholders_of(template):
        derive = DERIVED.get(name)
        raw = derive(get) if derive else get(name)
        if raw is None:
            raise TemplateError(
                f"{whose}: the template needs {{{name}}}, which is neither a value the "
                f"spec derives nor a field this law carries"
            )
        value = (raw.isoformat() if isinstance(raw, date) else str(raw)).strip()
        if not value:
            raise TemplateError(
                f"{whose}: {{{name}}} is empty, which would collapse a path segment"
            )
        if any(c in value for c in _FORBIDDEN) or value.strip(".") == "":
            raise TemplateError(f"{whose}: {{{name}}} = {value!r} is not a path segment")
        out[name] = value
    return out


def layout_for(country_code: str) -> str:
    """The path template for a country. Absent means flat (spec v0.4)."""
    return LAYOUT.get(country_code, FLAT)


def law_path(metadata: NormMetadata, template: str) -> str:
    """Where the pipeline writes a norm — the publisher's side of the rule."""
    return template.format(**_values(_norm_lookup(metadata), template, metadata.identifier))


def path_from_frontmatter(frontmatter: dict, template: str) -> str:
    """Where a law file should be, read from the file itself.

    The consumer's side of the same rule, and the one the spec describes: given a
    law's frontmatter and the template its repo declares, fill the template in.
    A repo conforms when this agrees with where the file actually is.
    """
    whose = str(frontmatter.get("identifier") or "?")
    return template.format(**_values(frontmatter.get, template, whose))


def manifest(country_code: str) -> str:
    """The ``.legalize.yml`` for a country repo.

    One entry covering ``*``: the engine gives every directory of a repo the
    same shape, so there is nothing to enumerate and nothing that goes stale
    when a country gains a jurisdiction.
    """
    return f"""\
# Legalize Format Spec v{SPEC_VERSION} — https://github.com/legalize-dev/legalize/blob/main/SPEC.md
#
# How to build the path to any law in this repo. A placeholder is either a value
# the spec derives ({", ".join(sorted(DERIVED))}) or a key of the law's own
# frontmatter, used verbatim.
# Generated by the pipeline; do not edit by hand.

spec_version: "{SPEC_VERSION}"
country: "{country_code}"

layout:
  - directories: ["*"]
    path: "{layout_for(country_code)}"
"""


# What shape each country's repo is in. A country absent from this map is FLAT,
# which is what every repo built before spec v0.4 already is — so adding a
# country here is a deliberate act and forgetting to is the safe failure. An
# entry here is a claim about a repo that already exists: it goes in with the
# rebuild that makes it true, never before, or the manifest promises consumers a
# shape the repo is not in and every body 404s.
#
# Changing a value rewrites every path in that repo. It breaks no public URL
# (the layout appears in none of them) but it is a full rebuild rather than an
# edit, so it is decided before the first bootstrap, together with the country.
# See ``adding-a-country/step-2-4-wiring.md``, Step 4.
LAYOUT: dict[str, str] = {
    # 164,278 files in one directory, an 8 MB tree that each of 300,732 commits
    # rewrites. Measured: 3 h 22 min of commit phase, 27 min of enumeration per
    # push, 74 min for the ``--name-only`` walk the DB seed needs, and a pack
    # GitHub rejects for exceeding 2.00 GiB.
    #
    # By year rather than by hash, which is the default answer: Portugal's
    # identifiers carry the year at a fixed position, so the key is immutable and
    # a reader can see what a directory holds. Measured over 171,737 laws and 74
    # years, a commit touches 3,260 tree entries against 928 for the hash and
    # 171,737 flat — both are far below where the cost starts to matter, and only
    # this one is legible. Sharding by type was measured too and rejected: one
    # type holds 49 % of the corpus, which is the flat problem again.
    "pt": "{directory}/{year}/{identifier}.md",
}


# A template that cannot parse should fail here, at import, and not four hours
# into a bootstrap. A field name that no law carries cannot be caught until a
# law is in hand; that one fails loudly on the first norm instead.
for _code, _template in LAYOUT.items():
    if not placeholders_of(_template):
        raise TemplateError(f"{_code}: {_template!r} has no placeholders")
    if "{identifier}" not in _template:
        raise TemplateError(f"{_code}: {_template!r} does not use the identifier")
