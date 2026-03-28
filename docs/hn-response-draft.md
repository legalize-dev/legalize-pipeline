# HN Response Draft

Post as reply to your own OP comment: https://news.ycombinator.com/item?id=47553799

HN uses plain text, not markdown. No bold, no bullets. Just text + links.
Max ~1500 chars. Don't oversell.

---

## Option A: Short and direct

OP here again. Several people asked if the parsing code is available — it is now.

The full pipeline is open source: https://github.com/legalize-dev/legalize-pipeline

It's Python. You implement 4 interfaces for your country's gazette (client, discovery, text parser, metadata parser) and the generic layers (markdown rendering, git commits, web app, API) work automatically. France is already working as a second country using Légifrance data.

Step-by-step guide to add a country: https://github.com/legalize-dev/legalize-pipeline/blob/main/docs/ADDING_A_COUNTRY.md

Countries people asked about in this thread: Germany, Portugal, Sweden, Finland, Netherlands, Brazil. PRs welcome. Even a partial parser is a great starting point.

Live site: https://legalize.dev

---

## Option B: Slightly warmer

OP here. Thank you for the incredible response — I did not expect this.

Many of you asked if the code is shared. It is now: https://github.com/legalize-dev

The pipeline is multi-country by design. France already works as a second country (Légifrance data). Adding a new country means implementing 4 Python interfaces for your national gazette. The rest (markdown, git, web, API) is generic.

I wrote a guide for contributors who want to add their country: https://github.com/legalize-dev/legalize-pipeline/blob/main/docs/ADDING_A_COUNTRY.md

From this thread alone, people asked about Germany, Portugal, Sweden, Finland, Netherlands, and Brazil. If you know your country's open data source for legislation, a PR is the best way to help.

I'll be honest — I don't know how much time I'll be able to dedicate to this, but I'd love to build something big. Legislation is massive (Spain alone is 8,642 laws with 27,000+ reforms) and scaling to more countries takes real infrastructure. I'm setting up an Open Collective to fund hosting and development: https://opencollective.com/legalize

Live site with browsable laws + diffs: https://legalize.dev

---

## Recommendation

Use Option B. It's human, answers the question people actually asked ("is the code available?"), and ends with a clear call to action (PR). Don't add emojis or bullet lists — HN readers prefer plain text.
