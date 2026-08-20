# Portugal — the DRE OutSystems API

`diariodarepublica.pt` has no public API. The fetcher drives the same internal
OutSystems endpoints the website's own JavaScript calls, so every DRE redeploy
can move the ground under it. This file records what the contract looks like
and how it broke, so the next break is a five-minute diagnosis.

## The handshake

Three things are needed before any endpoint answers with JSON:

| What | Where it comes from |
|---|---|
| `X-CSRFToken` header | `AnonymousCSRFToken = "…"` in `/dr/scripts/OutSystems.js` |
| `versionInfo.moduleVersion` | `versionToken` from `/dr/moduleservices/moduleversioninfo` |
| `versionInfo.apiVersion` | per-action hash, from the screen's MVC JavaScript |

Get any of them wrong and OutSystems replies with an **HTML error page**, not a
JSON error. That is why `_post()` raises `DREApiError` on a non-JSON body
instead of letting `resp.json()` throw somewhere further down.

Session cookies matter too: the `requests.Session` picks them up during the
handshake GETs. The same POST issued with plain `curl` and no cookie jar comes
back `{"exception": {"message": "No role validation found"}}`.

## Endpoints are discovered, not hardcoded

Each screen's JS declares its data actions as:

```js
controller.callDataAction("DataActionGetDRByDataCalendarioAndCheckUserLog",
                          "screenservices/dr/Home/home/DataActionGetDRByDataCalendarioAndCheckUserLog",
                          "k+86ytikYIT6brie_oLQTQ", …)
```

`_SCREEN_ENDPOINTS` maps a logical endpoint to its JS file plus a list of known
action-name **prefixes**, and `_resolve_endpoint()` reads both the URL and the
hash out of that JS at session start. A hash rotation or a suffix added to an
action name is absorbed automatically. A wholesale rename raises `DREApiError`
listing every action the JS *does* contain, so adding the new prefix is a
one-line change.

## The May 2026 redeploy

DRE renamed two of the three actions the fetcher uses:

| Endpoint | Before | After |
|---|---|---|
| journals by date | `DataActionGetDRByDataCalendario` | `DataActionGetDRByDataCalendarioAndCheckUserLog` |
| documents by journal | `DataActionGetDadosAndApplicationSettings` | unchanged |
| document detail | `DataActionGetConteudoDataAndApplicationSettings` | `DataActionGetAllConteudoDetalheData` |

The client logged `Could not extract apiVersion`, kept POSTing to the old URLs,
got HTML back, and the daily still exited 0. Verified live 2026-08-20: the
first two endpoints work again with the renamed actions.

## Known open break: document detail input

`DataActionGetAllConteudoDetalheData` resolves and answers 200, but the screen
no longer accepts `DipLegisId` as its input variable — the string does not
appear anywhere in `dr.Legislacao_Conteudos.Conteudo_Detalhe.mvc.js`. Probed
without success: `ConteudoId`, `KeyConteudoId`, and both combined with
`ParteId`/`FragmentoVersaoId`.

An unrecognised input does **not** produce an error. DRE returns a default
record — `Id: 0`, `Numero: ""`, `DataPublicacao: "1900-01-01"` — which would be
committed as a law with no title, no date and no text. `get_document_detail()`
therefore raises `DREApiError` on a record with neither `Numero` nor `ELI`.

Until this is solved the daily discovers the right documents and then fails
red on the first text fetch. Leads for whoever picks it up:

- the document list gives `LinkSitemap`, e.g.
  `/dr/detalhe/decreto-lei/169-2026-1159106557` — the screen is URL-driven, so
  its input is probably derived from those segments rather than a raw id;
- the response carries `KeyConteudoId`, `NewKey`, `PageName`, `ElementType`,
  which smell like the resolved route parameters;
- the surest route is capturing the real request in a browser devtools session
  on a detail page and copying the `screenData.variables` block verbatim.

## Re-checking the contract by hand

```bash
curl -s https://diariodarepublica.pt/dr/moduleservices/moduleversioninfo
curl -s https://diariodarepublica.pt/dr/scripts/dr.Home.home.mvc.js \
  | grep -o 'callDataAction("[^"]*"' | sort -u
```
