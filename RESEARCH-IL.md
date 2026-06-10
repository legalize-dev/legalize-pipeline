# Israel (IL) — Knesset OData V4 Research

## 0.1 Source

- Official source: Knesset (Israeli parliament) Open Data, OData V4 service.
- Base service: `https://knesset.gov.il/OdataV4/ParliamentInfo/`
- Document files (law text): `https://fs.knesset.gov.il/...` (paths come from `FilePath` fields).
- Access pattern: OData V4 JSON API for discovery + metadata; binary document download for text.
  - JSON is the default; the client appends `&$format=json` (or sends `Accept: application/json`).
  - Query options used: `$filter`, `$expand`, `$top`, `$skip`, `@odata.nextLink` pagination.
- Anti-blocking: the Knesset edge is fronted by the **Reblaze WAF**, which can return an HTML
  challenge page with HTTP 200. The client ports a Reblaze detector (`is_reblaze_content`) and,
  on a detected block, backs off exponentially and retries before raising. A realistic
  `User-Agent` is sent and the request rate is throttled (`requests_per_second: 1.0`).
- Encoding: Hebrew, UTF-8 throughout. Right-to-left text. Legacy PDFs are frequently stored in
  **visual** (reversed) Hebrew order and must be detected and reversed (`is_visual_hebrew` /
  `reverse_visual_line`).
- ID space: primary laws are `KNS_IsraelLaw.Id` (the 18 Basic Laws are `2000037`–`2000051`,
  `2002342`, `2007162`, `2073986`). Discovery for the milestone is restricted to Basic Laws via
  `KNS_IsraelLaw?$filter=IsBasicLaw eq true` (`is_basic_law_only: true` in `config.yaml`).

## 0.2 Fixtures

Raw OData responses and sample documents are saved under `recon/` (scratch + sample mine).
The committed offline test fixtures used by `tests/test_parser_il.py` are inline JSON literals
(see "Known gap" below).

| Source call | Fixture | Notes |
|---|---|---|
| `OdataV4/ParliamentInfo/` (service document) | `recon/service.json` | Entity-set inventory |
| `$metadata` | `recon/metadata.xml` | Field types, keys, navigation properties |
| `KNS_IsraelLaw?$top=10` | `recon/KNS_IsraelLaw.json` | Primary law records |
| `KNS_IsraelLawName?...` | `recon/KNS_IsraelLawName.json` | Titles (1-to-many) |
| `KNS_IsraelLawClassificiation?...` | `recon/KNS_IsraelLawClassificiation.json` | Subjects (source misspelling kept) |
| `KNS_IsraelLawMinistry?...` | `recon/KNS_IsraelLawMinistry.json` | Owning ministry |
| `KNS_LawCorrections?...` | `recon/KNS_LawCorrections.json` | Amendment ledger with dates |
| `KNS_IsraelLawLawCorrections?$expand=KNS_LawCorrection` | `recon/corrections_for_law.json` | Law→correction join + dates |
| `KNS_LawBinding?...` | `recon/KNS_LawBinding.json` | Original/amending relationships |
| `KNS_Bill?$filter=Id eq ...&$expand=KNS_DocumentBill` | `recon/bill_with_docs.json`, `recon/bill2_with_docs.json` | Bill date + document list |
| `KNS_DocumentIsraelLaw?...` | `recon/KNS_DocumentIsraelLaw*.json` | Document `FilePath` pointers |
| `KNS_Status?...` | `recon/KNS_Status.json` | Status code → label |
| `KNS_SecondaryLaw`, `KNS_DocumentSecondaryLaw` | `recon/KNS_SecondaryLaw.json`, `recon/KNS_DocumentSecondaryLaw.json` | Secondary legislation (not yet bootstrapped) |
| Sample law documents | `recon/sample_law_1.pdf`, `recon/sample_law_1.doc` | Inspected for Decision Gate 1 |

**Known gap (vs. playbook Step 0.2):** fixtures are not yet copied to committed
`tests/fixtures/il/`; the tests use inline data instead. Follow-up to commit canonical fixtures.

## 0.3 Metadata Inventory

Metadata is assembled by `IsraelClient.get_metadata` from several entities and parsed by
`IsraelMetadataParser`. All field names below are confirmed from `recon/metadata.xml`.

| Entity.Field | Type | Maps to | Notes |
|---|---|---|---|
| `KNS_IsraelLaw.Id` | Int32 (key) | `identifier` | Norm id (e.g. `2000037`) |
| `KNS_IsraelLaw.Name` | String | `title` fallback | Latest name preferred from `KNS_IsraelLawName` |
| `KNS_IsraelLaw.IsBasicLaw` | Boolean | `rank` | `true` → `basic_law` |
| `KNS_IsraelLaw.PublicationDate` | DateTimeOffset | `publication_date` | Original version date |
| `KNS_IsraelLaw.LatestPublicationDate` | DateTimeOffset | `last_updated` source | |
| `KNS_IsraelLaw.LawValidityDesc` | String | `status` | `תקף` → `in_force` |
| `KNS_IsraelLaw.LastUpdatedDate` | DateTimeOffset | daily cursor | See §0.5 / Gate 2 |
| `KNS_IsraelLaw.KnessetNum` | Int32 | `extra.knesset_num` | |
| `KNS_IsraelLaw.IsBudgetLaw` | Boolean | `extra.is_budget_law` | |
| `KNS_IsraelLaw.IsFavoriteLaw` | Boolean | `extra.is_favorite_law` | |
| `KNS_IsraelLawName.Name` | String | `title`, `short_title` | Laws are retitled; latest by `LastUpdatedDate` wins |
| `KNS_IsraelLawClassificiation.ClassificiationDesc` | String | `subjects` | Source misspelling kept verbatim |
| `KNS_IsraelLawMinistry.MinistryCategoryDesc` | String | `department` | Owning ministry |
| `KNS_Status.Desc` | String | status label | Resolves numeric status codes |
| `KNS_LawBinding.BindingTypeDesc` | String | original/reform routing | `החוק המקורי` = original act; `מתקן` = amending act |
| `KNS_LawBinding.LawID` | Int32 | amending bill id | Joins to `KNS_Bill.Id` and `KNS_DocumentBill.BillID` |
| `KNS_Bill.PublicationDate` | DateTimeOffset | **reform/version date** | Primary effective-date source (see §0.5) |
| `KNS_LawCorrection.BillID` | Int32 | reform date fallback join | |
| `KNS_LawCorrection.CommencementDate` / `.PublicationDate` / `.VoteDate` | DateTimeOffset | reform date fallback | Preference order: commencement → publication → vote |
| `KNS_DocumentBill.FilePath` / `.ApplicationDesc` | String | document download | `ApplicationDesc` ∈ {PDF, DOC, DOCX, PIC} |

Identifier scheme: the stable numeric `KNS_IsraelLaw.Id` is used as the filename
(`il/{id}.md`); the Hebrew title is preserved in frontmatter. (Transliterated slugs were
rejected as unstable for Hebrew.)

Rank mapping (`IsraelMetadataParser`): `IsBasicLaw` → `basic_law`; otherwise inferred from the
title prefix — `פקודה` → `ordinance`, `תקנות` → `regulation`, else `law`.

## 0.4 Formatting Inventory

Law text comes from binary documents (not structured XML), so formatting fidelity is limited by
PDF/DOC extraction rather than by markup richness.

| Construct | Present in source | Handled |
|---|---|---|
| Article markers (`סעיף N` / `N.` / `אות.`) | Yes | Yes — detected as `article` blocks |
| Chapter markers (`פרק`) | Yes | Yes — detected as `section` blocks |
| Preamble / opening text | Yes | Yes — `preamble` block |
| Right-to-left text | Yes | Paragraphs emitted with generic `parrafo` CSS class (RTL display handled by the website repo) |
| Visual (reversed) Hebrew in legacy PDFs | Yes | Detected and reversed; **heuristic** — can mis-handle mixed LTR/numeric runs |
| Tables (tax schedules, annexes) | Occasionally | **Not handled** — no pipe-table extraction yet |
| Bold / italic | Rare in extracted text | Not preserved (lost in PDF/DOC text extraction) |
| Niqqud / gershayim (`"` / `׳`) | Yes | Preserved (UTF-8) |
| Scanned-image documents (`ApplicationDesc = PIC`, `.TIF`) | Yes (older laws) | **Skipped** — would require OCR |

Confirmed parser behavior (`IsraelTextParser`):
- Document preference order in `_download_and_extract_text`: PDF → DOC/DOCX. PIC/TIF skipped.
- PDF text via `pdfplumber`, per-page, with visual-Hebrew reversal applied per line when detected.

## 0.5 Version History Spike

Israel exposes full amendment history; **Gate (≥2 dated versions from one law) PASSED.**

- Discovery of versions: `KNS_LawBinding` rows where `BindingTypeDesc == "מתקן"` enumerate the
  amending acts of a law; each binding's `LawID` is the amending bill id.
- **Effective date per version:** resolved from the amending bill's own
  `KNS_Bill.PublicationDate` (fetched together with its documents via
  `KNS_Bill?$filter=Id eq {id}&$expand=KNS_DocumentBill`). Fallback: the earliest matching
  `KNS_LawCorrection` date (commencement → publication → vote) joined on `BillID`.
- Evidence: **Basic Law: The Knesset** (`2000037`) yields **55 versions** dated 1958 → 2025, in
  ascending order. Basic Law: Israel Lands (`2000049`) yields 21; Basic Law: The Government
  (`2000038`) yields 11. Zero placeholder dates.

History strategy (per Decision Gate 1 below): **Case B / amendment-ledger.** Each amending act is
committed as a separate, correctly-dated block (oldest-first per file). The pipeline does **not**
reconstruct diff-applied consolidated text, because the Knesset data exposes no structured
per-article edit operations — only the amending act's own publication and text.

> **Pre-1970 caveat:** Basic Laws enacted 1958–1968 cannot be represented by git fast-import's
> Unix timestamps and clamp to `1970-01-02` (generic committer behavior); the true year is kept
> in the commit message.

## 0.6 Scope

- Milestone scope: **18 Basic Laws** (`IsBasicLaw eq true`) → 17 Markdown files (one repealed/
  empty) and 130 commits in `legalize-il`. Bootstrap is fast at `requests_per_second: 1.0`,
  `max_workers: 2`.
- Full primary legislation (`KNS_IsraelLaw`, ~thousands) and secondary legislation
  (`KNS_SecondaryLaw` / תקנות) are reachable with the same client but not yet bootstrapped.
- Daily path: generic daily via `discover_daily` on `LastUpdatedDate` (Gate 2). No custom
  `daily.py` required.

## 0.7 Format Coverage

The same law document may be published as PDF, DOC/DOCX, or PIC (scanned TIF image).

| Format (`ApplicationDesc`) | Reachable | Covered | Justification |
|---|---|---|---|
| PDF | Most modern laws | Yes (primary) | `pdfplumber` extraction + visual-Hebrew reversal |
| DOC / DOCX | Some laws | Yes (`python-docx` for DOCX; DOC best-effort) | Fallback when no PDF |
| PIC (TIF scans) | Older laws | **No** | Image-only; needs OCR. Skipped and logged; counted as a coverage gap |

Skip justification: scanned-image (`PIC`/`.TIF`) documents carry no extractable text layer; OCR
is out of scope for this milestone. Documents that 406/time out are skipped gracefully (logged,
never written as law text). Quantifying the exact %-of-laws-only-reachable-via-PIC is a follow-up.

## Entity reference (confirmed from `recon/metadata.xml`)

Primary: `KNS_IsraelLaw` (key `Id`), `KNS_IsraelLawName`, `KNS_IsraelLawClassificiation`
(misspelling verbatim), `KNS_IsraelLawMinistry`, `KNS_LawBinding` / `KNS_IsraelLawBinding`,
`KNS_LawCorrections` + `KNS_IsraelLawLawCorrections` (amendment ledger), `KNS_DocumentIsraelLaw`,
`KNS_Bill` + `KNS_DocumentBill` (text + dates), `KNS_Status`.

Secondary (regulations): `KNS_SecondaryLaw`, `KNS_DocumentSecondaryLaw`,
`KNS_SecLawAuthorizingLaw`, `KNS_SecLawRegulator`, `KNS_SecToSecBinding`.

Full per-entity field lists are in `recon/RECON.md`.

## Decision Gate findings

### Gate 1 — Document semantics: **Case B (point-in-time publications)**
Documents on `fs.knesset.gov.il` are not consolidated texts but original acts plus separate
amending acts. Evidence: downloaded sample documents (`recon/sample_law_1.*`) and the
`KNS_LawBinding` original/amending split. Strategy: order amending acts chronologically by their
real publication date and commit each as a dated reform (amendment-ledger model).

### Gate 2 — Incremental discovery field: **`LastUpdatedDate`**
`KNS_IsraelLaw.LastUpdatedDate` supports OData `gt` filtering. Confirmed working syntax:
`KNS_IsraelLaw?$filter=LastUpdatedDate gt 2026-01-01T00:00:00Z`. Used by `discover_daily`.
