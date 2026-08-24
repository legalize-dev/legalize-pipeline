# Portugal — metadata inventory (Step 0.3)

Companion to `RESEARCH-PT-v2.md` §4. Every number here was measured on 2026-08-21
against the live `diariodarepublica.pt`; the command or code that produced it is
given next to it. Nothing in this file is inferred from documentation.

**Headline results**

1. There is a **fourth surface** nobody had looked at: `/dr/analise-juridica/…`.
   It is reachable programmatically, it works for *every* diploma (Série I and II,
   1926 to today, consolidated or not), and it is the only place DRE publishes
   **the descriptor labels**, **a curated status code**, **the entry-into-force
   date**, and **the regional journal citation**.
2. **The descriptor problem is solved.** `eli:is_about → …/legal-subject/{id}` ids
   resolve exactly, **1364/1364 in the sample**, against
   `AnaliseJuridica.DataActionGetData → ThesaurusTreeList`. Recipe and code in §3.
3. `Vigencia` is not a boolean and not a free string. DRE ships a six-value static
   entity, extracted verbatim from the app manifest (§5), plus the full
   `TipoFragmento` (19 values) and `GrupoTipoModificacao` (9 values) vocabularies —
   which closes the "must be built during implementation" note in
   `RESEARCH-PT-v2.md` §3.3.
4. The as-published **ELI exists only from ~1990 onwards** (0/16 sampled diplomas
   before 1990 have one, 42/42 after). `TipoDiplomaAcronimo` is 100 % filled and
   carries the same ELI type token, so it — not `ELI` — is what identifier
   derivation (D2) must key on.

---

## §0 How this was measured

| | |
|---|---|
| Sample | **59 consolidated diplomas** drawn from `countries/data-pt/consolidated-catalogue.jsonl.gz` |
| Strata | 11 decades (1920s–2020s) × 14 ELI types × 3 jurisdictions |
| ELI types covered | `dec-lei` 15 · `declegreg` 9 · `port` 8 · `decregulreg` 5 · `resolconsmin` 4 · `dec` 3 · `lei` 3 · `leiorg` 3 · `decpresrep` 3 · `resolassrep` 1 · `acstj` 1 · `declretif` 1 · `av` 1 · `despnorm` 1 |
| Jurisdictions | national `p` 42 · Açores `a` 7 · Madeira `m` 7 · no-ELI 3 |
| Decades | 1920s 1 · 1930s 2 · 1940s 1 · 1950s 2 · 1960s 2 · 1970s 2 · 1980s 5 · 1990s 9 · 2000s 7 · 2010s 17 · 2020s 11 |
| Calls made | 59 surface-A headers · 58 surface-B details · 58 análise-jurídica pairs · 10 consolidated snapshots (666 fragments) · 7 association tabs |
| Rate | 1 request / 0.6–0.8 s, single connection (≤ 1.7 req/s), UA `legalize-bot/1.0 (+https://github.com/legalize-dev/legalize-pipeline)` |
| Errors | 1 of 59 (a `declaracao-retificacao` whose header returns no `DiplomaLegis.LinkSitemap`, so surface B is unreachable for it) |

Sample list, raw responses and the analysis scripts are reproducible from the
fixture `tests/fixtures/pt/metadata-sample-59.jsonl.gz` (one JSON object per
diploma: `cat` = catalogue row, `header` = surface A, `detail` = surface B with
`Texto`/`TextoFormatado` stripped, `aj` = análise jurídica).

**Surface labels used throughout.**

| Label | Screen / action | viewName |
|---|---|---|
| **A-hdr** | `LegCons_Detalhe` → `DataActionGetDiplomaFragByIdAndApplicationSetting` | `LegislacaoConsolidada.LegCons_Detalhe` |
| **A-doc** / **A-frag** | `LegCons_Detalhe` → `DataActionGetData` (point-in-time snapshot) | idem |
| **B** | `Conteudo_Detalhe` → `DataActionGetAllConteudoDetalheData` | `Legislacao_Conteudos.Conteudo_Detalhe` |
| **C** | the `ELIMetadataHTML` RDFa block inside **B** | — |
| **D** | `AnaliseJuridica` → `DataActionGetElementTypeAndApplicationSettings` + `DataActionGetData` | `AnaliseJuridica.AnaliseJuridica` |

Surface **D is new to this research** and is not mentioned in `RESEARCH-PT-v2.md`.

---

## §1 The merged field table

`Captured today?` is measured against `fetcher/pt/client.py::DREHttpClient.get_metadata`
+ `fetcher/pt/parser.py::DREMetadataParser.parse` (the daily path). The bootstrap
path uses the tretas.org SQLite client and captures strictly less.

### 1.1 Surface B — as-published detail (40 top-level fields + 8 sub-records)

| Source field | Surface | Type | Real example value | Maps to | Captured today? |
|---|---|---|---|---|---|
| `Id` | B | str(int) | `923288601` | `extra.dre_content_id` | yes (as `claint`, then **discarded** — never reaches the frontmatter) |
| `Titulo` | B | str | `Portaria n.º 416/2025/2 ` | `NormMetadata.title` | no (title is rebuilt from `TipoDiploma` + `Numero`) |
| `Publicacao` | B | str | `Diário da República n.º 125/2025, Série II de 2025-07-02` | `extra.publication_citation` | no |
| `Numero` | B | str | `416/2025/2` | `extra.official_number` | yes |
| `Resumo` | B | str | *(always empty — see §2)* | `extra.abstract` | yes (fallback for `notes`) |
| `Sumario` | B | str | `Autoriza o Exército a assumir os encargos plurianuais…` | `NormMetadata.summary` | yes |
| `Texto` | B | HTML | 244,249 chars for DLR 2/2025/M | body | yes — **but it is the poorer manifestation** (`RESEARCH-PT-v2.md` §4.2) |
| `TextoFormatado` | B | HTML | 300,147 chars, +472 `<a>`, +2,676 `<p>` | body | **no** (used only as a fallback) |
| `DataPublicacao` | B | date | `2025-07-02` | `NormMetadata.publication_date` | yes |
| `DataDistribuicao` | B | date | *always `1900-01-01`* | `extra.distribution_date` | no |
| `DataDisponibilizacao` | B | date | *always `1900-01-01`* | `extra.availability_date` | no |
| `DataAssinatura` | B | date | *always `1900-01-01`* | `extra.signature_date` | no |
| `Emissor` | B | str | `Ministério da Guerra - 3.ª Direcção Geral - 5.ª Repartição` | `NormMetadata.department` | yes |
| `EmissorAcronimo` | B | str | `MJ`, `RAA-AL` | `extra.issuer_acronym` | **no** |
| `Parte` | B | str | *always empty* | `extra.part` | yes (read, always `""`) |
| `Serie` | B | str | `I` / `II` | `extra.journal_series` | **no** (hardcoded `"Serie I"`) |
| `Suplemento` | B | str | *always empty even when the diploma is in a Suplemento* | `extra.supplement` | **no** — parse `Publicacao` instead (§2) |
| `Processo` | B | str | *always empty for legislation* | `extra.case_number` | no |
| `Vigencia` | B | enum str | `VIGENTE` / `NAO_VIGENTE` / `VIGENCIA_CONDICIONADA` | `NormMetadata.status` | **partial** — collapsed to a boolean (§5) |
| `URL_PDF` | B | url | `https://files.diariodarepublica.pt/1s/2025/07/13901/0000200003.pdf` | `NormMetadata.pdf_url` | yes |
| `TipoConteudo` | B | enum str | `DiplomaLegis` | `extra.content_type` | **no** |
| `TipoDiploma` | B | str | `Portaria` | `NormMetadata.rank` (via `RANK_MAP`) | yes |
| `TipoDiplomaAcronimo` | B | str | `port`, `dec-lei`, `declegreg` | **`extra.eli_type` / identifier stem** | **no** — and it is the field D2 should key on |
| `TipoDiplomaExterno` | B | str | *always empty for legislation* | `extra.external_type` | yes (as a `doc_type` fallback) |
| `Notas` | B | str | *always empty for legislation* | `extra.notes` | **no** |
| `Pagina` | B | str | `65 - 66` | `extra.pages` | **no** |
| `PaginaOffset` | B | str | *always empty* | — | no |
| `ELI` | B | url | `https://data.dre.pt/eli/lei/55-a/2025/07/22/p/dre/pt/html` | `NormMetadata.source` + `extra.eli` | yes |
| `ELIMetadataHTML` | B | HTML/RDFa | 8.7 KB block, 31 distinct predicates (§1.4) | see §1.4 | **no** |
| `IsDiplomaExterno` | B | bool | `False` | — | no |
| `IsDiplomaLegis` | B | bool | `True` | — | no |
| `LinkSitemap` | B | path | `/dr/detalhe/portaria/416-2025-923288601` | `extra.dre_path` | no (used transiently as the fetch key) |
| `DiarioRepublica.Numero` | B | str | `125` | `extra.dr_number` | yes |
| `DiarioRepublica.Id` | B | str(int) | `923135887` | `extra.dr_issue_id` | **no** |
| `DiarioRepublica.URL_PDF` | B | url | `…/gratuitos/2s/2025/07/2S125A0000S00.pdf` (the **whole issue** PDF) | `extra.dr_issue_pdf_url` | **no** |
| `DiarioRepublica.NumPaginas_PDF` | B | str(int) | `2` | `extra.pdf_page_count` | **no** |
| `DiarioRepublica.Tamanho_PDF` | B | str(int) | `560065` | `extra.pdf_bytes` | **no** |
| `DiplomaLegis.EntidadeProponente` | B | str | `Presidência do Conselho de Ministros` (1/58) | `extra.proposing_entity` | **no** |
| `DiplomaLegis.IsNoIndex` | B | bool | `False` | — | no |
| `DiplomaExterno.Descritores` | B | str | *always empty* — **the trap: this is NOT the descriptor field** | — | no |
| `DiplomaExterno.FonteDireito` | B | str | *always empty* | — | no |
| `DiplomaExterno.Relator` | B | str | *always empty* | — | no |
| `DiplomaLegacor.FonteRegional` | B | str | *always empty here* — populated on surface **D** instead | `extra.regional_journal` | **no** |
| `DiplomaLegacor.EntidadeEmitente_AJ` | B | list | *always empty here* — populated on **D** | `extra.issuing_bodies` | **no** |
| `DiplomaRegTrab.Fonte_AJ` | B | str | *always empty* (labour-regulation content type) | — | no |
| `AcordaoSTA.Assunto` | B | str | *always empty* (jurisprudence content type) | — | no |
| `AcordaoSTA.DataEmQueFoiProferido` | B | str | *always empty* | — | no |
| `AtosSocietarios.{Concelho,Conservatoria,Empresa}` | B | str | *always empty* (company-register content type) | — | no |
| `ContratoPublico.IsAnuncioAlteracao` | B | bool | `False` (public-procurement content type) | — | no |

Screen-level fields returned alongside `DetalheConteudo` (same response, outside it):

| Source field | Surface | Type | Real example value | Maps to | Captured today? |
|---|---|---|---|---|---|
| `HasIndice` | B (screen) | bool | `True` | `extra.has_index` | no |
| `IsConsolidado` | B (screen) | bool | `False` | **`extra.has_consolidated_version`** — the cheap A/B routing flag | **no** |
| `HasJurisprudenciaAssociada` | B (screen) | bool | `False` | `extra.has_case_law` | no |
| `HasIndiceDiplomaFragmentacao` | B (screen) | bool | `False` | — | no |
| `DiarioRepublicaLinkSitemap` | B (screen) | url | `…/dr/detalhe/diario-republica/125-2025-923135887` | `extra.dr_issue_url` | no |
| `PageName` | B (screen) | str | `Portaria n.º 416/2025/2, de 2 de julho` | `NormMetadata.short_title` candidate | no |
| `ElementType` | B (screen) | str | `DiplomaLegis` | — | no |
| `KeyConteudoId` | B (screen) | str | `923288601` | — | no |
| `Ano`, `DiplomaFragIdAux`, `KeyParteId`, `KeyFragmentoVersaoId`, `NewKey`, `IsVisible`, `HaveFragmentoVersaoOnURL`, `HaveEmissor_DecisaoJudicial`, `DomainName`, `ApplicationRoot`, `EnvironmentName` | B (screen) | mixed | plumbing | — | no |

### 1.2 Surface A — consolidated header and document

| Source field | Surface | Type | Real example value | Maps to | Captured today? |
|---|---|---|---|---|---|
| `DiplomaFrag.ELI` | A-hdr | url | `https://data.dre.pt/eli/dec/12704/1926/p/cons/19301031/pt/html` | `extra.eli_consolidated` + jurisdiction (§6.2) | **no** |
| `DiplomaFrag.Designacao` | A-hdr | str | `Código Civil - CC`, `Organização da Escola Militar` | **`NormMetadata.short_title`** | **no** |
| `DiplomaFrag.ConteudoTitle` | A-hdr | str | `Decreto-Lei n.º 47344 ` | `NormMetadata.title` | **no** |
| `DiplomaFrag.FormattedTitle` | A-hdr | str | `Decreto-Lei n.º 47344  - Diário do Governo n.º 274/1966, Série I de 1966-11-25` | `extra.formatted_title` | **no** |
| `DiplomaFrag.Nota` | A-hdr | HTML | `A alínea a) do artigo 34.º do Decreto-Lei n.º 96/2017 … revoga as disposições…` | `extra.consolidation_note` | **no** |
| `DiplomaFrag.DiplomaConsolidacaoEstadoId` | A-hdr | enum int | `4` (= `concluded`) | `extra.consolidation_state` | **no** |
| `DiplomaFrag.EmAtualizacao` | A-hdr | bool | `False` | `extra.consolidation_in_progress` | **no** |
| `DiplomaFrag.DiplomaLegisId` | A-hdr | str(int) | `161322` | `extra.dre_legis_id` | **no** |
| `DiplomaLegis.Numero` | A-hdr | str | `47344` | `extra.official_number` | no |
| `DiplomaLegis.Sumario` | A-hdr | str | `Aprova o Código Civil e regula a sua aplicação…` | `NormMetadata.summary` | no |
| `DiplomaLegis.Resumo` | A-hdr | str | *always empty on A* (populated on **D**) | `extra.abstract` | no |
| `DiplomaLegis.Emissor` | A-hdr | str | `Ministério da Justiça - Gabinete do Ministro` | `NormMetadata.department` | no |
| `DiplomaLegis.EmissorAcronimo` | A-hdr | str | *always empty on A* (populated on **B**) | `extra.issuer_acronym` | no |
| `DiplomaLegis.Vigencia` | A-hdr | str | **always empty on A** — use B or D | `NormMetadata.status` | no |
| `DiplomaLegis.IsRegional` | A-hdr | bool | `False` | jurisdiction fallback (unreliable, §6.2) | no |
| `DiplomaLegis.Consolidado` | A-hdr | str-bool | `True` | `extra.is_consolidated` | no |
| `DiplomaLegis.AnaliseJuridicaPublica` | A-hdr | str-bool | `True` | `extra.has_legal_analysis` | no |
| `DiplomaLegis.DataPublicacao` | A-hdr | datetime | `1966-11-25T00:00:00Z` | `NormMetadata.publication_date` | no |
| `DiplomaLegis.DataAlteracao` | A-hdr | datetime | `2026-08-04T12:13:30Z` | **`NormMetadata.last_modified`** (record mtime, not legal) | **no** — `last_modified` is never set today |
| `DiplomaLegis.DataCriacao` | A-hdr | datetime | `2014-04-01T13:09:09.987Z` | `extra.record_created` | no |
| `DiplomaLegis.LinkSitemap` | A-hdr | path | `/dr/detalhe/decreto-lei/47344-1966-477358` | the surface-B fetch key | no |
| `DiplomaLegis.Id` | A-hdr | str(int) | `477358` | `extra.dre_legis_id` | no |
| `DiplomaLegis.IsDiploma` / `IsIncludedInSiteMap` / `IsNoIndex` | A-hdr | bool | `True`/`True`/`False` | — | no |
| `DiarioRepublica.ConteudoTitle` | A-hdr | str | `Diário do Govêrno n.º 274/1966, Série I de 1966-11-25` | `extra.publication_citation` | no |
| `DiarioRepublica.LinkSitemap` | A-hdr | path | `/dr/detalhe/diario-republica/274-1966-67121` | `extra.dr_issue_url` | no |
| `DiarioRepublica.DataPublicacao` | A-hdr | datetime | `1966-11-25T00:00:00Z` | — | no |
| `Serie.Nome` | A-hdr | str | `I` | `extra.journal_series` | no |
| `TipoDiploma.Tipo` | A-hdr | str | `Decreto-Lei` | `NormMetadata.rank` | no |
| `TipoDiploma.Acronimo` | A-hdr | str | `dec-lei` | `extra.eli_type` | no |
| `CurrentConsolidacaoId` | A-doc | str(int) | `117352378` | `extra.consolidation_id` | **no** |
| `LastConsolidacaoId` | A-doc | str(int) | `117352378` | `extra.last_consolidation_id` | **no** |
| `DataUltimaConsolidada` | A-doc | date | `2018-12-12` | `extra.last_consolidated_on` | **no** |
| `IsVersaoInicial` | A-doc | bool | `False` | `extra.is_initial_version` | **no** |
| `IsMultipleConsolidation` | A-doc | bool | `False` | `extra.multiple_consolidations` | **no** |
| `HasIndice` / `HasFile` / `HasJurisprudenciaAssociada` | A-doc | bool | `False` | `extra.*` | **no** |
| `URLPDF` | A-doc | url | `https://files.diariodarepublica.pt/1s/2018/11/22200/0534305347.pdf` | `NormMetadata.pdf_url` | **no** |
| `Id`, `Query` | A-doc | str | always empty | — | no |

### 1.3 Surface A — fragment level (`LegConsBase.List[]`)

Measured on 666 fragments across 10 diplomas.

| Source field | Surface | Type | Real example value | Maps to | Captured today? |
|---|---|---|---|---|---|
| `ConsolidacaoFragmento.Id` | A-frag | str(int) | `73641748` | `Block.id` (stable across versions) | **no** |
| `ConsolidacaoFragmento.FragmentoVersaoId` | A-frag | str(int) | `117352102` | `Version` identity | **no** |
| `ConsolidacaoFragmento.PaiId` | A-frag | str(int) | `73641748` | tree parent | **no** |
| `ConsolidacaoFragmento.Orderm` | A-frag | int | `1` | sibling order | **no** |
| `ConsolidacaoFragmento.IndexOrdem` | A-frag | str | `1.00`, `3.02.01` | dotted outline position | **no** |
| `ConsolidacaoFragmento.FullName` | A-frag | str | `Diploma > Livro III > Artigo 1425.º` | `extra`/breadcrumb | **no** |
| `ConsolidacaoFragmento.Name` | A-frag | str | `Artigo 1425.º` | `Block.title` | **no** |
| `ConsolidacaoFragmento.Epigrafe` | A-frag | str | `Disposições Gerais` | `Block.title` suffix | **no** |
| `ConsolidacaoFragmento.NextId` / `PreviousID` | A-frag | str(int) | `73641753` / `73641750` | linked list | **no** |
| `ConsolidacaoFragmento.IsAnexo` | A-frag | bool | `False` | annex flag | **no** |
| `ConsolidacaoFragmento.IsActive` | A-frag | bool | `True` | render/skip | **no** |
| `ConsolidacaoFragmento.FragmentoVersoesAnterioresId` | A-frag | str(int) | `73641750` | previous-version link | **no** |
| `ConsolidacaoFragmento.ConsolidacaoId` / `Cid` | A-frag | str(int) | `117352378` | `extra.consolidation_id` | **no** |
| `ConsolidacaoFragmento.DataVersao` | A-frag | datetime | `2018-11-19T00:00:00Z` | version stamp | **no** |
| `ConsolidacaoFragmento.AssociacaoOrigemTitle` | A-frag | str | `Declaração de Retificação n.º 39/2018 …` | **the amending act** → `Reform.norm_id` | **no** |
| `ConsolidacaoFragmento.AssociacaoDescription` | A-frag | str | `Retificado pelo/a [L]Declaração de Retificação n.º 39/2018…` | reform note | **no** |
| `ConsolidacaoFragmento.AssociacaoParams` | A-frag | str | `id=117343946` | amending act id | **no** |
| `ConsolidacaoFragmento.GrupoTipoModificacaoEnumId` | A-frag | enum int | `2` (= `rectifica`) | `CommitType` (§5, appendix) | **no** |
| `ConsolidacaoFragmento.IsWithAssociation` | A-frag | bool | `False` | — | **no** |
| `ConsolidacaoFragmento.IsDescriptionVisible` | A-frag | bool | `True` | — | no |
| `ConsolidacaoFragmento.CreationDate` / `ModificationDate` | A-frag | datetime | `2018-12-12T09:42:00.113Z` | record mtimes | no |
| `ConsolidacaoFragmento.Temp_Log` | A-frag | str | always empty | — | no |
| `FragmentoVersao.Id` | A-frag | str(int) | `117352102` | `Version` id | **no** |
| `FragmentoVersao.FragmentoId` / `FragmentoPaiId` | A-frag | str(int) | `117366187` | tree | **no** |
| `FragmentoVersao.Texto` | A-frag | text or HTML | plain text with `\n`, 8.4 % contains HTML | `Paragraph.text` | **no** (today's parser re-derives everything from a flat HTML blob) |
| `FragmentoVersao.Epigrafe` | A-frag | str | `Disposições Gerais` | `Block.title` | **no** |
| `FragmentoVersao.Identificacao` | A-frag | str | `1425.º`, `I` | heading number | **no** |
| `FragmentoVersao.Tituo` *(sic — DRE typo)* | A-frag | str | `Diploma`, `Artigo` | heading word | **no** |
| `FragmentoVersao.TipoFragmentoId` | A-frag | enum int | `11` (= `artigo`) | `Block.block_type`, heading level | **no** |
| `FragmentoVersao.VersaoEstadoId` | A-frag | enum int | `6` (= `validada`), `4` (= `revogada`) | per-article status | **no** |
| `FragmentoVersao.DataEntradaVigor` | A-frag | datetime | `2018-11-20T00:00:00Z` | **`Version.publication_date`** (the commit date) | **no** |
| `FragmentoVersao.DataProducaoEfeitos` | A-frag | datetime | `2024-04-02T00:00:00Z` | `extra.effect_date` | **no** |
| `FragmentoVersao.DataSuspensao` | A-frag | datetime | never populated in the sample | `extra.suspension_date` | **no** |
| `FragmentoVersao.DataVersao` | A-frag | datetime | `2018-11-19T00:00:00Z` | — | **no** |
| `FragmentoVersao.Ordem` | A-frag | int | `1` | order | **no** |
| `FragmentoVersao.AssociacaoPrincipalId` / `AssociacaoSecundariaId` | A-frag | str(int) | `117348709` / `117348724` | amending-act links | **no** |
| `FragmentoVersao.Root` / `KeepEstado` / `OmitTipo` / `UsaAssociacaoSecundaria` | A-frag | bool | `True`/`False`/`False`/`False` | rendering hints | **no** |
| `FragmentoVersao.DataCriacao` / `DataModificacao` | A-frag | datetime | `2018-12-12T09:22:50.743Z` | record mtimes | no |
| `Nivel` | A-frag | int | `1` … `9` | heading depth | **no** |
| `HasFilhos` | A-frag | bool | `True` | tree | **no** |
| `TodosFilhosRevogados` | A-frag | bool | `False` | "all children repealed" | **no** |
| `DataEntradaVigorProximaVersao` | A-frag | date | `2018-11-24` | next-version date | **no** |
| `Nota.List[]` | A-frag | list of HTML | `<a href="/dr/detalhe/decreto-lei/7-2023-206618939">Artigo 4.º, Decreto-Lei…` | `nota_pie` paragraphs | **no** |
| `AlteracoesList.List[]` | A-frag | list of HTML | `Retificado pelo/a [L]<a rel="nofollow" href="/dr/detalhe/declaracao-…` | amendment notes | **no** |
| `IsHidden` / `IsOpen` | A-frag | bool | UI state | — | no |

### 1.4 Surface C — the ELI RDFa block (`ELIMetadataHTML`)

31 distinct predicates observed. Percentages are of the **42 sampled diplomas that
have an `ELIMetadataHTML` block at all** (see §2 for who does).

| Source field | Surface | Type | Real example value | Maps to | Captured today? |
|---|---|---|---|---|---|
| `eli:number` | C | str | `29/2026` | `extra.official_number` | no |
| `eli:id_local` | C | str(int) | `570109` | `extra.dre_content_id` | no |
| `eli:title` | C | str | `Decreto-Lei n.º 365/99 ` | `NormMetadata.title` | no |
| `eli:description` | C | str | `Estabelece o regime jurídico do acesso, do exercício…` | `NormMetadata.summary` | no |
| `eli:type_document` | C | uri | `…/authority/resource-type/dec-lei` | `extra.eli_type` | no |
| `eli:date_publication` | C | date | `1999-09-17` | `publication_date` | no |
| `eli:in_force` | C | uri enum | `…ontology#InForce-inForce` / `#InForce-notInForce` | `NormMetadata.status` (2-valued, §5) | **no** |
| `eli:legal_value` | C | uri | `…ontology#LegalValue-official` | `extra.legal_value` | no |
| `eli:language` | C | uri | `…/authority/language/POR` | — | no |
| `eli:publisher` / `eli:publisher_agent` / `eli:rightsholder_agent` | C | str / uri | `INCM` / `…/legal-institution/incm` | `extra.publisher` | no |
| `eli:licence` | C | uri | `…/eli/dec-lei/83/2016/p/dr/pt/html` | `extra.licence` (readme evidence) | no |
| `eli:uri_schema` | C | uri | `…/geral/ligacoes-interesse/identificador-europeu-legislacao-eli` | — | no |
| `eli:format` / `eli:media-type` | C | uri / str | `…/media-types/text/html`, `application/pdf;type=archival` | — | no |
| `eli:realizes` / `eli:is_realized_by` / `eli:embodies` / `eli:published_in_format` | C | uri | `…/eli/dec-lei/365/1999/09/17/p/dre/pt` | FRBR plumbing | no |
| **`eli:is_about`** | C | uri × n | `http://data.dre.pt/eli/authority/legal-subject/30211723` | **`NormMetadata.subjects`** — resolvable via §3 | **no** |
| **`eli:cites`** | C | uri × n | `…/eli/dec-lei/15/2022/…`, `http://data.europa.eu/eli/dir/2019/944/oj` | `extra.cites` (national **and EU**) | **no** |
| **`eli:cited_by`** | C | uri × n | `…/eli/resolassrep/149/2011/12/09/p/dre` | `extra.cited_by` | **no** |
| `eli:based_on` | C | uri × n | `…/eli/lei/87-B/1998/12/31/p/dr` | `extra.based_on` (enabling act) | **no** |
| `eli:consolidated_by` | C | uri | `…/eli/dec-lei/365/1999/p/cons/20150811` | link A ↔ B | **no** |
| `eli:amended_by` | C | uri × n | `…/eli/declretif/39/2010/12/29/p/dr/pt/html` | reform graph | **no** |
| `eli:amends` | C | uri × n | `…/eli/dec-lei/11/2023/2/10/p/dr/pt/html` | reform graph | **no** |
| `eli:transposes` | C | **free text** | `Art. 11º do Regulamento (CE) n.° 882/2004 do Parlamento Europeu…` | `extra.transposes` | **no** |
| `eli:responsibility_of_agent` | C | uri | `…/authority/legal-agent/mf` | `extra.responsible_agent` | no |
| `eli:responsibility_of` | C | free text | `Ministérios da Justiça e do Trabalho e da Solidariedade` | `NormMetadata.department` | no |

### 1.5 Surface D — análise jurídica (new)

| Source field | Surface | Type | Real example value | Maps to | Captured today? |
|---|---|---|---|---|---|
| **`ThesaurusTreeList[].ThesaurusElementId`** | D | str(int) | `30215271` | key for `eli:is_about` | **no** |
| **`ThesaurusTreeList[].ThesaurusElementName`** | D | str | `Código Civil`, `Direito de Família` | **`NormMetadata.subjects`** | **no** |
| `ThesaurusTreeList[].ThesaurusBroaderElementId` | D | str(int) | `30217529` | thesaurus parent | **no** |
| `ThesaurusTreeList[].ThesaurusElementType` | D | enum str | `Descriptor` (`Term` also exists in the enum) | — | **no** |
| **`DetalheAJ.Vigencia`** | D | enum int | `3` | `NormMetadata.status` (§5) | **no** |
| **`DetalheAJ.VigenciaDescricao`** | D | str | `Não vigente. Revogado a partir de 08.10.2015 pelo(a) Lei n.º 141/2015 …` | `extra.status_note` | **no** |
| **`DetalheAJ.DataEntradaVigor`** | D | str (free) | `1968-01-01` | **`extra.entry_into_force`** — not on A or B | **no** |
| `DetalheAJ.ProducaoEfeitos` | D | str (free) | `a presente portaria produz efeitos nos termos definidos no seu art. 56.º.` | `extra.effects_note` | **no** |
| `DetalheAJ.Notas` | D | str | `Vale como lei.` | `extra.legal_note` | **no** |
| `DetalheAJ.Nota_TextoIntegral` | D | str | `Na al. b) do n.º 4 do art. 22.º onde se lê «Centro Cultural…` | `extra.full_text_note` | **no** |
| **`DetalheAJ.FonteRegional`** | D | str | `JORNAL OFICIAL DOS AÇORES - 1.ª SÉRIE, Nº 85/2021, de 2021-06-01, Pág. 2118 - 2130` | **`extra.regional_journal`** (Açores/Madeira citation) | **no** |
| `DetalheAJ.Fonte` | D | str | `DIARIO DO GOVERNO - 1.ª SERIE, Nº 261, de 1926-11-22` | `extra.publication_citation` | **no** |
| `DetalheAJ.Resumo` | D | str | `Organização da Escola Militar.` | `NormMetadata.summary` (100 % filled, unlike B's `Resumo`) | **no** |
| `DetalheAJ.EntidadeEmitente[]` | D | list of str | `["Ministério da Guerra"]` | `extra.issuing_bodies` (normalised, unlike `Emissor`) | **no** |
| `DetalheAJ.DiplomaLegis.Referencia` | D | str | `19262466` | `extra.dre_reference` | **no** |
| `DetalheAJ.DiplomaLegis.Visibility` | D | enum str | `PUBLIC` | — | no |
| `DetalheAJ.DiplomaLegis.Serie` / `.Emissor` | D | str | `I` / `Ministério da Guerra - …` | duplicates B | no |
| `DetalheAJ.{Titulo,Numero,TipoDiploma,Id}` | D | str | duplicates B | — | no |
| `DetalheAJ.Tratamento` | D | bool | `False` | `extra.aj_processed` | no |
| `HasLegCons` | D | bool | `False` | `extra.has_consolidated_version` | **no** |
| `HasJurisprudenciaAssociada` | D | bool | `False` | `extra.has_case_law` | no |
| `DRAno` / `DRNumero` / `FragId` | D | mixed | `1926-11-22` / empty / `0` | — | no |
| `Associacoes.InversasList[]` | D | list of records | see §4 | `extra.*` / reform prose | **no** |

---

## §2 Fill rates

Reproduce with `metadata-sample-59.jsonl.gz` and the flatten-and-count script in §0.
"Empty" counts `""`, `0`, `1900-01-01`, and empty lists as not populated.

### 2.1 Surface B — as-published (n = 58)

| Field | % non-empty | Notes |
|---|---|---|
| `Id`, `Numero`, `Titulo`, `Publicacao`, `Sumario`, `Texto`, `TextoFormatado`, `DataPublicacao`, `Emissor`, `Serie`, `Pagina`, `URL_PDF`, `LinkSitemap`, `TipoConteudo`, `TipoDiploma`, `TipoDiplomaAcronimo`, `DiarioRepublica.*` (5 fields), `IsDiplomaLegis` | **100 %** | 58/58 |
| `Vigencia` | **96.6 %** | 56/58 — empty for the two pre-1931 `decreto`s |
| `ELI` | **72.4 %** | 42/58 — **0/16 before 1990, 42/42 from 1990 on** |
| `ELIMetadataHTML` | **72.4 %** | exactly the same 42 diplomas |
| `EmissorAcronimo` | **72.4 %** | 42/58 |
| `DiplomaLegis.EntidadeProponente` | **1.7 %** | 1/58 |
| `Resumo` | **0 %** | always empty for `DiplomaLegis`; the abstract lives in `Sumario` (B) and `Resumo` (D) |
| `Notas` | **0 %** | always empty for legislation — the legal note lives on surface **D** |
| `Suplemento` | **0 %** | **9/58 diplomas *are* in a Suplemento** (the word appears in `Publicacao`) yet the field is never set. Parse `Publicacao`. |
| `Parte`, `PaginaOffset`, `Processo`, `TipoDiplomaExterno` | **0 %** | 0/58 |
| `DataAssinatura`, `DataDistribuicao`, `DataDisponibilizacao` | **0 %** | always the sentinel `1900-01-01`. Do not map them. |
| `DiplomaExterno.{Descritores,FonteDireito,Relator}` | **0 %** | `Descritores` is the trap named in `RESEARCH-PT-v2.md` §2.4 — it is a *DiplomaExterno* field and is never populated for Portuguese legislation |
| `DiplomaLegacor.{FonteRegional,EntidadeEmitente_AJ}` | **0 %** | populated on surface **D** instead (12.1 % / 100 %) |
| `DiplomaRegTrab.Fonte_AJ`, `AcordaoSTA.*`, `AtosSocietarios.*` | **0 %** | other content types; dead weight for legislation |

Screen level: `HasIndice`, `IsConsolidado`, `HasJurisprudenciaAssociada`,
`DiarioRepublicaLinkSitemap`, `PageName`, `KeyConteudoId`, `ElementType` 100 %;
`Ano`, `KeyParteId`, `KeyFragmentoVersaoId`, `NewKey`, `DiplomaFragIdAux` 0 %.

### 2.2 Surface A — header (n = 59)

| Field | % non-empty | Notes |
|---|---|---|
| `DiplomaLegis.{DataPublicacao,DataAlteracao,DataCriacao,Consolidado,AnaliseJuridicaPublica,IsDiploma,IsIncludedInSiteMap,IsRegional,IsNoIndex}`, `DiarioRepublica.DataPublicacao`, `DiplomaFrag.EmAtualizacao` | **100 %** | 59/59 |
| `DiplomaFrag.{ConteudoTitle,Designacao,FormattedTitle,DiplomaLegisId}`, `DiplomaLegis.{ConteudoTitle,Emissor,FormattedTitle,Id,LinkSitemap,Numero,Sumario}`, `Serie.Nome`, `TipoDiploma.{Tipo,Acronimo}`, `DiarioRepublica.{ConteudoTitle,LinkSitemap}` | **98.3 %** | 58/59 — one `declaracao-retificacao` returns an empty header |
| `DiplomaFrag.DiplomaConsolidacaoEstadoId` | **96.6 %** | 57/59 |
| `DiplomaFrag.ELI` | **94.9 %** | 56/59 — **works for 1926 diplomas** where surface B has none |
| `DiplomaFrag.Nota` | **5.1 %** | 3/59 — rare but genuinely legal content |
| `DiplomaLegis.EmissorAcronimo` | **0 %** | 0/59 — always empty on A (B has it 72.4 %) |
| `DiplomaLegis.Resumo` | **0 %** | 0/59 |
| `DiplomaLegis.Vigencia` | **0 %** | 0/59 — **never populated on surface A.** Status must come from B or D. |

### 2.3 Surface A — document and fragment level (n = 10 diplomas, 666 fragments)

| Field | % non-empty | Notes |
|---|---|---|
| `CurrentConsolidacaoId`, `LastConsolidacaoId`, `DataUltimaConsolidada`, `HasFile`, `HasIndice`, `HasJurisprudenciaAssociada`, `IsMultipleConsolidation`, `IsVersaoInicial`, `URLPDF` | **100 %** | 10/10 |
| `Id`, `Query` | **0 %** | plumbing |
| `ConsolidacaoFragmento.{Id,Cid,FragmentoVersaoId,FullName,Name,Orderm,IsActive,IsAnexo,DataVersao,CreationDate,IsWithAssociation,IsDescriptionVisible}`, `FragmentoVersao.{Id,FragmentoId,Ordem,Tituo,TipoFragmentoId,VersaoEstadoId,Root,DataVersao,DataCriacao,DataModificacao,KeepEstado,OmitTipo,UsaAssociacaoSecundaria}`, `HasFilhos`, `IsHidden`, `IsOpen`, `TodosFilhosRevogados` | **100 %** | 666/666 |
| `ConsolidacaoFragmento.ModificationDate` | 98.6 % | |
| `ConsolidacaoFragmento.{PaiId,IndexOrdem}`, `FragmentoVersao.FragmentoPaiId`, `Nivel` | 98.5 % | the 1.5 % gap is the root fragment |
| `ConsolidacaoFragmento.{ConsolidacaoId,Epigrafe}`, `FragmentoVersao.{Epigrafe,Identificacao}` | 97.0 % | |
| `ConsolidacaoFragmento.NextId` / `PreviousID` | 94.4 % / 93.7 % | first/last of each list |
| **`FragmentoVersao.Texto`** | **87.8 %** | 585/666 — **12 % of fragments carry no text**: they are pure structural headings (Livro, Título, …). The renderer must handle a text-less block. |
| `ConsolidacaoFragmento.{AssociacaoDescription,AssociacaoOrigemTitle,AssociacaoParams,GrupoTipoModificacaoEnumId}` | 31.1 % | 207/666 — every fragment touched by an amendment |
| `FragmentoVersao.AssociacaoSecundariaId` | 30.8 % | |
| **`FragmentoVersao.DataEntradaVigor`** | **30.0 %** | 200/666 — **only amended fragments carry it.** For the other 70 % the effective date is the diploma's. A parser that reads it blindly will write `1900-01-01`. |
| `FragmentoVersao.DataProducaoEfeitos` | 23.1 % | |
| `FragmentoVersao.AssociacaoPrincipalId` | 4.7 % | |
| `ConsolidacaoFragmento.FragmentoVersoesAnterioresId` | 2.3 % | |
| `DataEntradaVigorProximaVersao` | 1.5 % | |
| `Nota` (list) | **2.4 %** | 16/666 fragments carry at least one note |
| `AlteracoesList` (list) | **31.7 %** | 211/666 fragments carry at least one amendment note |
| `FragmentoVersao.DataSuspensao`, `ConsolidacaoFragmento.Temp_Log` | **0 %** | never populated in the sample |

Content shape of `FragmentoVersao.Texto` (585 non-empty): **96.8 % contain a newline**
(hard line breaks, not paragraphs), **8.4 % (49) contain any HTML tag**. Tag census:
`p` 455 · `td` 432 · `tr` 205 · `sup` 66 · `th` 25 · `div` 8 · `table` 8 · `thead` 8 ·
`tbody` 8 · **`img` 5** · `br` 4 · `span` 3. Consolidated text therefore *does*
sometimes carry images and real tables — the parser must handle both shapes and the
image policy applies to surface A too.

`TipoFragmentoId` histogram over the 666 fragments:
`11 artigo` 539 · `1 capitulo` 44 · `8 seccao` 28 · `14 anexo` 16 · `13 titulo` 14 ·
`15 root` 10 · `7 assinatura` 9 · `3 subseccao` 4 · `4 parte` 2.
`VersaoEstadoId`: `6 validada` 490 · **`4 revogada` 175** · `5 por_validar` 1 —
i.e. **26 % of fragments in a current snapshot are repealed articles** that DRE
still renders. That flag is the only way to mark them.

### 2.4 Surface C — ELI RDFa (n = 42, the diplomas that have the block)

| Predicate | % of the 42 | Notes |
|---|---|---|
| `eli:is_about`, `eli:cited_by`, `eli:consolidated_by`, `eli:number`, `eli:id_local`, `eli:title`, `eli:description`, `eli:type_document`, `eli:date_publication`, `eli:in_force`, `eli:language`, `eli:legal_value`, `eli:licence`, `eli:publisher`, `eli:publisher_agent`, `eli:rightsholder_agent`, `eli:uri_schema`, `eli:format`, `eli:media-type`, `eli:realizes`, `eli:is_realized_by`, `eli:embodies`, `eli:published_in_format` | **100 %** | 42/42 |
| `eli:responsibility_of_agent` | 90.5 % | 38/42 |
| `eli:cites` | 88.1 % | 37/42; 530 references in total |
| `eli:based_on` | 64.3 % | 27/42; 143 references |
| `eli:amended_by` | 31.0 % | 13/42 |
| `eli:responsibility_of` (free text) | 9.5 % | 4/42 |
| `eli:transposes` (free text, **not a URI**) | 4.8 % | 2/42 |
| `eli:amends` | 2.4 % | 1/42 |

Volumes across the 42: **1,365 `eli:is_about`** (1,000 distinct subject ids),
**625 `eli:cited_by`**, **530 `eli:cites`**, **143 `eli:based_on`**.
`eli:in_force` takes exactly two values in the sample: `InForce-inForce` (34) and
`InForce-notInForce` (8).

**The 72.4 % / 0-before-1990 boundary is the single most important fill-rate fact
here.** Sampled diplomas with no `ELI`: 1926, 1930, 1936, 1940, 1956, 1959, 1960,
1967, 1978, 1979, 1983, 1984, 1985, 1986, 1987, 1990. Sampled diplomas with an
`ELI`: everything from 1991 on. Since the repo reaches back to 1911, **the
ELI-derived identifier of D2 cannot be the primary key** for the ~104,000
as-published diplomas. `TipoDiplomaAcronimo` (100 % filled, and identical to the
ELI type token: `dec-lei`, `port`, `lei`, `declegreg`, `leiorg`, `decpresrep`,
`resolconsmin`, `declretif`, `av`, `despnorm`, `acstj`, `dec`, `resolassrep`,
`decregulreg`) is the field to build on, with the ELI used only to confirm it.

### 2.5 Surface D — análise jurídica (n = 58)

| Field | % non-empty | Notes |
|---|---|---|
| `ThesaurusTreeList` | **100 %** | 58/58 — **every diploma has descriptors**, including Série II portarias and 1926 decretos |
| `DetalheAJ.{Id,Titulo,Numero,TipoDiploma,Resumo,IsDiplomaLegis,Tratamento}`, `DetalheAJ.DiarioRepublica.*` (5), `DetalheAJ.DiplomaLegis.{Emissor,Referencia,Serie,Visibility}`, `DetalheAJ.EntidadeEmitente`, `HasLegCons`, `HasJurisprudenciaAssociada` | **100 %** | |
| `DetalheAJ.Fonte` | 98.3 % | |
| `DetalheAJ.Vigencia` / `VigenciaDescricao` | **96.6 %** | same 56/58 as surface B |
| `DetalheAJ.DataEntradaVigor` | **53.4 %** | 31/58 — free text, not a date type (`1968-01-01`, but also prose) |
| `DetalheAJ.Notas` | 44.8 % | 26/58 |
| `DetalheAJ.ProducaoEfeitos` | 13.8 % | 8/58, free text |
| `DetalheAJ.FonteRegional` | **12.1 %** | 7/58 — approximately the regional diplomas; the Jornal Oficial dos Açores / da Madeira citation |
| `DetalheAJ.Nota_TextoIntegral` | 1.7 % | 1/58 |
| `DRNumero`, `FragId`, `DetalheAJ.ConteudoId`, `DetalheAJ.TipoConteudoId` | 0 % | plumbing |

Descriptor volume: **1,489 descriptor references, 1,075 distinct ids** across 58
diplomas — per diploma min 1, median 9, mean 25.7, max 438 (Decreto-Lei 32/2022).
All 1,489 are `ThesaurusElementType = "Descriptor"`; 22 of them carry a non-zero
`ThesaurusBroaderElementId`, so the thesaurus hierarchy is exposed but sparsely.

---

## §3 The descriptor problem — SOLVED

### 3.1 What does not work (so nobody retries it)

| Attempt | Result |
|---|---|
| `GET http://data.dre.pt/eli/authority/legal-subject/30211723` with `Accept: text/turtle`, `application/rdf+xml`, `application/ld+json`, `text/html` | **301 to `https://diariodarepublica.pt/dr/pesquisa`** in all four cases. The URI is not dereferenceable and content negotiation is not implemented. |
| `DiplomaExterno.Descritores` on surface B | **0/58 populated.** It belongs to the *DiplomaExterno* content type, not to legislation. |
| `dr.Pesquisas.PesquisaAvancada` → `DataActionGetListsForDropdown` | Returns `Elastic_Results_Descritores` as an **Elasticsearch terms-aggregation bucket** `{key, key_as_string, doc_count, isActive}`. `key` is the *label*; there is **no id** in the bucket. The dropdown's "value" is the row number (`getCurrentRowNumber`), not a DRE id. Called anonymously it returns an empty list. |
| The search filter | Filters on `descritor_facet.keyword` — again a label, not an id. |
| `dr.Legislacao_Conteudos.Conteudo_Detalhe` | The string `descritor` does not appear anywhere in the screen's JS. There is no "Descritores" section on the diploma detail page. |
| `DREMultiIndexAutocomplete` | Only `DataActionGetDiplomaAutoCompleteResults` and `DataActionGetFragmentIndexAutoCompleteResults`; no descriptor index. |
| `dr.Lexionario.*` | A separate legal *dictionary*, keyed by its own entry ids; not the ELI subject thesaurus. |

### 3.2 What works

`/dr/analise-juridica/informacoes-gerais/{tipo}/{key}` →
`AnaliseJuridica.DataActionGetData` returns `ThesaurusTreeList`, a list of
`{ThesaurusElementId, ThesaurusBroaderElementId, ThesaurusElementName, ThesaurusElementType}`.
**`ThesaurusElementId` is the same integer as the `legal-subject/{id}` in `eli:is_about`.**

Verified across the whole sample:

```
compared 42 diplomas: eli is_about ids 1364, thesaurus ids 1364,
intersection 1364;  eli is_about subset of thesaurus in 42/42
```

Every single `eli:is_about` id resolved, with no id left over on either side.

### 3.3 The recipe

Two protocol facts, both of which cost time to find:

1. **`DataActionGetElementTypeAndApplicationSettings` needs `ConteudoId`, not just
   `Tipo`/`Key`.** The SPA parses the key `47344-1966-477358` client-side into
   `Numero=47344`, `Year=1966`, `ConteudoId=477358` *before* the first data action
   fires. Post `Tipo`/`Key` alone and DRE answers `IsNullElementType: true` with all
   ids `0` — a **silent** empty result, exactly like the `Id: 0` default record
   documented in `docs/pt-dre-api.md`. Treat `IsNullElementType == true` as an error.
2. **`DataActionGetData` reads the previous action's output off the screen state** —
   same shape as the `LegCons_Detalhe` gotcha in `RESEARCH-PT-v2.md` §2.3. The whole
   `GetElementTypeAndApplicationSettings` response must be echoed back under that key,
   and `DiplomaLegisId` set from `DiplomaLegisIdOut`.

```python
# Both actions post under viewName "AnaliseJuridica.AnaliseJuridica".
ET = "screenservices/dr/AnaliseJuridica/AnaliseJuridica/DataActionGetElementTypeAndApplicationSettings"
GD = "screenservices/dr/AnaliseJuridica/AnaliseJuridica/DataActionGetData"

def _aj_vars(tipo: str, key: str, assoc: str = "informacoes-gerais") -> dict:
    numero, ano, conteudo_id = key.rsplit("-", 2)      # "47344-1966-477358"
    return {
        # --- the three URL segments -------------------------------------
        "Associacao": assoc, "_associacaoInDataFetchStatus": 1,
        "Tipo": tipo,        "_tipoInDataFetchStatus": 1,
        "Key": key,          "_keyInDataFetchStatus": 1,
        # --- what the SPA derives from the key before the first call ----
        "ConteudoId": conteudo_id, "Numero": numero,
        "Year": int(ano) if ano.isdigit() else 0,
        # --- the rest of the screen state, at its defaults --------------
        "TipoAssociacaoIdAux": "0", "HasAssociacoesEcra": True, "DiplomaFragId": "0",
        "IsRended": True, "DiplomaLegisId": "0", "DiplomaDGOId": "0",
        "DiplomaRegTrabId": "0", "DiplomaLegacorId": "0", "DiplomaDGAPId": "0",
        "TipoAssociacaoId": "0", "AssociacaoAnaliseJuridicaId": "0",
        "IsWordExport": False, "IsExcelExport": False, "TipoExportacao": "",
        "CountEcra": 0, "HasJurisprudenciaAssociadaVar": False,
        "IsDiretaChecked": True, "IsInversaChecked": True, "AssociacoesCounter": 0,
        "IsPageTracked": True, "IsShowConteudoRelacionado": True, "Print": False,
        "TotalAssociacoes": 0, "HasAssociacoesFetched": False,
    }

def descriptors(dre, tipo: str, key: str) -> dict[str, str]:
    """{'30215271': 'Codigo Civil', ...} — keys match eli:is_about legal-subject ids."""
    v = _aj_vars(tipo, key)
    et = dre.call(ET, api_of(ET), v, view="AnaliseJuridica.AnaliseJuridica")
    if et["IsNullElementType"]:                       # never degrade to {}
        raise DREApiError(f"analise-juridica did not resolve {tipo}/{key}")
    v["GetElementTypeAndApplicationSettings"] = et
    v["DiplomaLegisId"] = et["DiplomaLegisIdOut"]
    data = dre.call(GD, api_of(GD), v, view="AnaliseJuridica.AnaliseJuridica")
    return {t["ThesaurusElementId"]: t["ThesaurusElementName"]
            for t in data["ThesaurusTreeList"]["List"]}
```

`tipo` and `key` are the two segments of `DiplomaLegis.LinkSitemap`, i.e. exactly
what `_split_sitemap_ref()` already produces — no new identifier plumbing.
`api_of()` resolves the per-action hash from
`/dr/scripts/dr.AnaliseJuridica.AnaliseJuridica.mvc.js`, the same way
`_resolve_endpoint()` already does. Hashes as of 2026-08-21:
`Sqcov8FRhkfucWnBGGlq7A` (`GetElementTypeAndApplicationSettings`),
`+g8I98j+9Jv6bbQdGPFb8A` (`GetData`),
`9MyPV2Gjy472bHyiD+T4BQ` (`GetTipoAssociacoes`), and
`O_j4bxHBZyDzcYIMIY8_sA` (`FetchAssociacoes`, from
`dr.AnaliseJuridica.WB_AnaliseJuridica_Associacoes.mvc.js`).

### 3.4 What this buys, and what it costs

- `NormMetadata.subjects` becomes real Portuguese labels for **100 % of diplomas**,
  not just the 72.4 % that have an ELI block and not just the 5,561 consolidated ones.
- The thesaurus is **shared**: 1,489 references collapse to 1,075 distinct ids in a
  58-diploma sample, so a global `{id: label}` cache built while fetching pays for
  itself immediately and can be persisted to `countries/data-pt/thesaurus.json`.
- Cost: **2 extra requests per diploma**. At ~110,000 diplomas that is ~220,000
  requests on top of D1's ~150,000. If that is too much, the cheaper variant is to
  call surface D **only for diplomas whose `ELIMetadataHTML` contains `is_about`**
  (72.4 %) and rely on the shared cache — but note that would leave every pre-1990
  diploma without subjects, which is where the thesaurus is arguably most useful.

---

## §4 The análise jurídica screens

All of them are the same screen (`AnaliseJuridica.AnaliseJuridica`) with a different
`Associacao` URL segment. `DataActionGetElementTypeAndApplicationSettings` returns
the `TipoAssociacaoId` for that segment; `WB_AnaliseJuridica_Associacoes.DataActionFetchAssociacoes`
then returns the list. Measured on the Código Civil (`decreto-lei/47344-1966-477358`):

| URL segment | `TipoAssociacaoIdOut` | Diretas | Inversas | What it is |
|---|---|---|---|---|
| `informacoes-gerais` | 0 | — | — | `DetalheAJ` + `ThesaurusTreeList` (§1.5) |
| `modificacoes` | **162** | 0 | **90** | Acts that modified this diploma (and vice-versa), as prose |
| `retificacoes` | **165** | 0 | **9** | Rectifications (`Declaração de Retificação`), as prose |
| `regulamentacao` | **164** | 0 | 0 | Implementing acts (empty for the CC) |
| `direito-uniao-europeia` | **158** | 0 | 0 | EU-law relations (empty for the CC) |
| `outros-tipos` with `157` "Atos de Aplicação" | 157 | 1 | **467** | Acts that *apply* the diploma |
| `outros-tipos` with `160` "Doutrina Associada" | 160 | **20** | 0 | `NOTAJUR.…` legal-doctrine notes |
| `outros-tipos` with `161` "Jurisprudência Associada" | 161 | **83** | 1 | Court decisions on the diploma |

(The three `outros-tipos` ids come from `DataActionGetTipoAssociacoes`, which returns
`{Id, Nome, Descricao, DescricaoInversa, PermiteNotas, LigaConstituicao, AlteraVigencia, Ordem, VisivelPublico, DestacamentoPublico}` per type.)

Record shape returned by `DataActionFetchAssociacoes`
(`{ApplicationRoot, CountDiretas, CountInversas, DiretasList, DomainName, InversasList, StaticContentPath}`):

- `InversasList[]`: `Data · Texto · Sumario · Diploma · TipoDiploma · NumeroAJ ·
  NumeroDiploma · LinkSitemapAnaliseJuridica · DiplomaLegisId · DiplomaDGOId ·
  DiplomaRegTrabId · DiplomaLegacorId · DiplomaDGAPId · ActoSocietarioId ·
  AcordaoSTADiplomaId · ContratoPublicoId`
- `DiretasList[]`: `Data · Texto · AssociacaoAnaliseJuridicaId · HasLink ·
  HasInversa · DiplomaLinkId · Numero · Tipo`

### 4.1 Does it add anything over the consolidated timeline?

**For `modificacoes` and `retificacoes`, on a consolidated diploma: no — it is
strictly poorer.** `DataActionGetConsolidacaoByDiplomaFrag` gives 102 amending
diplomas and 1,165 individually-dated, article-resolved modifications for the Código
Civil; the AJ `modificacoes` tab gives 90 prose sentences. Compare one of each:

```
timeline : {"TipoModificacao":"Altera", "FragmentoDestinoModificacao":"Artigo 1425.º",
            "FragmentoVersaoDestinoId":"1138222475", "DataEntradaVigor":"2026-07-01",
            "PathDestinoModificacao":"Anexo > Livro III > Titulo II > Capitulo VI > Seccao III"}

AJ       : {"Data":"2026-06-23",
            "Texto":"Altera, a partir de 1 de julho de 2026, o artigo 1425.o do Codigo Civil,
                     aprovado pelo Decreto-Lei n.o 47344, de 25 de novembro de 1966
                     pelo(a) Lei n.o 29/2026 - Diario da Republica n.o 119/2026, Serie I de 2026-06-23"}
```

`Data` on the AJ record is the amending act's **publication** date, not the effective
date, which is buried inside the prose. Use the timeline.

**For everything else, yes, and substantially:**

| Adds | Where the timeline has nothing |
|---|---|
| **Descriptors** (`ThesaurusTreeList`) | §3 — the whole reason this surface matters |
| **`Vigencia` + `VigenciaDescricao`** | the diploma-level status, and a prose explanation of *how* it was repealed (§5) |
| **`DataEntradaVigor`** (diploma level, 53.4 %) | neither A nor B publishes a diploma-level entry-into-force date |
| **`FonteRegional`** | the Jornal Oficial dos Açores/Madeira citation for regional law |
| **`Notas` / `Nota_TextoIntegral`** | curated legal notes (`Vale como lei.`) |
| **`EntidadeEmitente[]`** | a normalised list, against B's single free-text `Emissor` |
| `Atos de Aplicação` (467), `Doutrina` (20), `Jurisprudência` (83) | relation types that exist nowhere else |
| **Availability** | **the AJ screens work for non-consolidated diplomas.** Verified on `lei/29-2026-…` (12 descriptors, 2 modificações), `lei/55-a-2025-…` (3 descriptors, 1 modificação) and the Série II `portaria/416-2025-…` (5 descriptors). The consolidated surface returns nothing for any of them. |

**Recommendation:** call `informacoes-gerais` for every diploma; call
`modificacoes` only for **non-consolidated** diplomas, where it is the only
amendment signal that exists (prose-only, so it cannot produce content-bearing
reform commits — but it can populate `extra.amended_by` and flag laws that need
watching). Skip `retificacoes`/`regulamentacao`/`direito-uniao-europeia` for
consolidated diplomas — the timeline's `GrupoTipoModificacao` covers rectification.

### 4.2 `/dr/decisoes-judiciais/{tipo}/{key}`

Screen `DecisoesJudiciais.Decisoes_Judiciais`, action
`DataActionGetConteudoDataAndApplicationSettings`
(`OFpabfMwEChtxw_i_qnpmg`), inputs `{Tipo, Key}` only — no screen-state echo needed.

It is **not** a per-diploma view. It is the detail screen for a *court decision*,
keyed by that decision's own sitemap ref. Called with
`acordao-supremo-tribunal-justica/3-2021-169602022` it returns a 10-field
`DetalheConteudo` (`DataAssinatura, DataDisponibilizacao, DataDistribuicao,
DataEntradaVigor, DataPublicacao, LinkSitemap, Resumo, TipoConteudo, TipoDiploma,
Titulo`) plus `JSON_Resultados`, a **raw Elasticsearch response** of related
decisions (`{"took":4,…,"hits":{"total":{"value":0}}}` for that acórdão).

**It adds nothing for legislation.** The per-diploma link into case law is the
`Jurisprudência Associada` association (`TipoAssociacaoId 161`) of §4, not this
screen. Jurisprudence is out of scope per `RESEARCH-PT-v2.md` §11.

### 4.3 One data-cleaning gotcha found here

`DiretasList[].Texto` contains **raw NUL bytes** (`U+0000`) at the end of several
records, e.g. `" 1ª parte do nº 2 do art. 109º da CRP."` followed by two NULs. If any
of this text is ever rendered, `fetcher/_text.py::scrub_control` is mandatory —
consistent with the `feedback_engine_gotchas` memory.

---

## §5 Status mapping

### 5.1 The vocabulary is a static entity, not a free string

DRE ships its enumerations in the OutSystems app manifest. Extracted verbatim by
cross-referencing the `Object.defineProperty(drModel.staticEntities.…)` names in
`/dr/scripts/dr.model.js` with the numeric ids in
`/dr/moduleservices/moduleinfo` (`data.modules[…].staticEntities[…]`):

```
TipoVigencia (entity 35ecb19a-d40c-48cd-b4f8-07892037ebeb)
  0 = NULL
  1 = Vigencia Condicionada     <- VIGENCIA_CONDICIONADA on surface B
  2 = Omisso
  3 = Vigente                   <- VIGENTE
  4 = Nao Vigente               <- NAO_VIGENTE
  5 = Caducado
```

This is the **complete** vocabulary — there is no sixth value hiding in the corpus.
Surface B exposes it as the screaming-snake string, surface D as the integer plus a
prose `VigenciaDescricao`. Observed in the 58-diploma sample:

| `DetalheAJ.Vigencia` | B `Vigencia` | `VigenciaDescricao` prefix | Count |
|---|---|---|---|
| `3` | `VIGENTE` | `Em vigor` | 44 |
| `4` | `NAO_VIGENTE` | `Não vigente. Revogado a partir de …` | 11 |
| `1` | `VIGENCIA_CONDICIONADA` | `Vigência Condicionada. Revogado pelo(a) … sem prejuízo do disposto no art. 32.º` | 1 |
| `0` | `""` | *(empty)* | 2 |

`2 Omisso` and `5 Caducado` did not occur in 58 diplomas; they are in the vocabulary
and the mapping must handle them.

Two further status signals exist and **agree in a useful way**:

```
DiplomaConsolidacaoEstado (entity 3bc51315-3569-4de5-87f6-4e506c0a4235)
  1 = revoked · 2 = inProgress · 3 = partiallyConcluded
  4 = concluded · 5 = expired · 6 = conditional
```

observed on `DiplomaFrag.DiplomaConsolidacaoEstadoId`: `4` × 45, `1` × 11, `0` × 2,
`6` × 1 — it tracks `TipoVigencia` almost exactly (`concluded` ↔ `Vigente`,
`revoked` ↔ `Não Vigente`, `conditional` ↔ `Vigência Condicionada`), which is a free
cross-check.

```
VersaoEstado (per fragment, FragmentoVersao.VersaoEstadoId)
  1 = inactiva · 2 = suspensa · 3 = inconstitucional
  4 = revogada  · 5 = por_validar · 6 = validada
```

observed over 666 fragments: `6` × 490, **`4 revogada` × 175**, `5` × 1.

### 5.2 Proposed mapping

```python
# Preferred source: DetalheAJ.Vigencia (surface D, integer, 96.6 % filled).
# Fallback:         DetalheConteudo.Vigencia (surface B, string, same coverage).
# Never:            DiplomaLegis.Vigencia (surface A) — 0 % filled.

_PT_STATUS = {
    "3": NormStatus.IN_FORCE,           # Vigente
    "4": NormStatus.REPEALED,           # Nao Vigente
    "5": NormStatus.EXPIRED,            # Caducado
    "1": NormStatus.PARTIALLY_REPEALED, # Vigencia Condicionada  (see note)
    "2": NormStatus.IN_FORCE,           # Omisso  - DRE has no record; assume in force
    "0": NormStatus.IN_FORCE,           # NULL    - idem
}
_PT_STATUS_STR = {                      # surface B equivalents
    "VIGENTE": NormStatus.IN_FORCE,
    "NAO_VIGENTE": NormStatus.REPEALED,
    "VIGENCIA_CONDICIONADA": NormStatus.PARTIALLY_REPEALED,
    "": NormStatus.IN_FORCE,
}
```

Notes on the two judgement calls:

- **`1 Vigência Condicionada` maps to `partially_repealed`.** The one sampled case is
  Decreto Regulamentar Regional 28/2006/A: *"Vigência Condicionada. Revogado pelo(a)
  Decreto Legislativo Regional n.º 2/2023/A …, **sem prejuízo do disposto no art.
  32.º**"* — a repeal with a surviving carve-out, which is precisely
  `partially_repealed`. The alternative reading is "conditionally in force", but the
  prose in every DRE example is a partial repeal, so this is the honest mapping.
  Record the raw code in `extra.vigencia_code` so the choice is reversible without a
  reprocess.
- **`0 NULL` and `2 Omisso` map to `in_force`.** DRE means "we have not recorded a
  status", not "not in force". Both empty cases in the sample are 1920s–30s decretos
  that are formally still on the books. Defaulting to `repealed` would be wrong;
  defaulting to `in_force` matches the current parser's behaviour
  (`in_force = Vigencia != "NAO_VIGENTE"`) without inheriting its blindness to the
  other three values.
- **`annulled`** has no DRE counterpart at diploma level. It exists at *fragment*
  level as `VersaoEstadoId 3 inconstitucional` (a Constitutional Court declaration of
  unconstitutionality with `força obrigatória geral`). If a diploma's fragments are
  all state 3, `annulled` is the correct diploma status; otherwise carry it per-block.
- **`4 revogada` at fragment level** is what today's parser has no way to express.
  With 26 % of fragments in a current snapshot repealed, this belongs in the block
  metadata, not only in the diploma status.

Also worth storing verbatim: `VigenciaDescricao` into `extra.status_note`. It names
the repealing act and the date (*"Revogado a partir de 08.10.2015 pelo(a) Lei n.º
141/2015 …, nos termos do art. 4.º"*), which is exactly the sentence a reader wants
at the top of a repealed law's page and which no structured field carries.

---

## Appendix A — DRE static enumerations (complete, from the app manifest)

Saved as `tests/fixtures/pt/dre-static-entities.json`. These are authoritative
vocabularies, not samples; they resolve the "must be built during implementation"
note in `RESEARCH-PT-v2.md` §3.3.

| Entity | Values |
|---|---|
| **`TipoFragmento`** | 0 NULL · 1 capítulo · 2 base · 3 subsecção · 4 parte · 5 subtítulo · 6 subdivisão · 7 assinatura · 8 secção · 9 divisão · **10 subcapítulo** · 11 artigo · 12 livro · 13 título · 14 anexo · 15 root · **16 número** · **17 alínea** · **18 subalínea** |
| **`GrupoTipoModificacao`** | 1 movimenta · 2 rectifica · 3 altera · 4 suspende · 5 revoga · 6 adita · 7 elimina · 8 repõe em vigor · 9 declara inconstitucionalidade |
| **`TipoVigencia`** | 0 NULL · 1 vigência condicionada · 2 omisso · 3 vigente · 4 não vigente · 5 caducado |
| **`VersaoEstado`** | 1 inactiva · 2 suspensa · 3 inconstitucional · 4 revogada · 5 por validar · 6 validada |
| **`DiplomaConsolidacaoEstado`** | 1 revoked · 2 inProgress · 3 partiallyConcluded · 4 concluded · 5 expired · 6 conditional |
| **`DiplomaFragEstado`** | 1 inProgress · 2 inRectification · 3 waitingValidation · 4 validated · 5 unknown |
| **`ConsolidacaoEstado`** | 1 organizingStructure · 2 waitingValidation · 3 waitingUserSelection · 4 inRectification · 5 inProgress · 6 inValidationBySystem · 7 published |
| **`ThesaurusElementType`** | 1 term · 2 descriptor |
| **`TipoNotaAnalise`** | 1 resumo · 2 dados gerais · 3 texto integral · 4 associações |
| **`TipoConteudo`** | 1 contratoPublico · 2 diplomaDGO · 3 jurisprudencia · 4 diarioRepublica · **5 diplomaLegis** · 6 actoSocietario · 7 tradutorJuridico · 8 guiasPraticos · 9 diplomaRegTrab · 10 servicoAlertas · 11 dicionarioJuridico · **12 consolidacao** · 13 textoJuridico · 14 acordaoSTA · 15 diplomaLegacor · 16 diplomaTraduzido · 17 newsletter · 18 FAQ · 19 diplomaDGAP · **20 analiseJuridica** · 21 acordaoSTADiploma · 22 diplomaExterno · **23 diplomaFrag** |
| `DiplomaRelacionadoType` | 1 retifica |
| `TipoFicheiroDiploma` | 1 manualInstrucao · 2 outro · 3 avaliacaoImpacto · 4 diploma |

**How to re-derive them** (they are versioned with the app, so re-check after a DRE
redeploy):

```bash
UA='legalize-bot/1.0 (+https://github.com/legalize-dev/legalize-pipeline)'
curl -sS -A "$UA" https://diariodarepublica.pt/dr/moduleservices/moduleinfo -o moduleinfo.json
curl -sS -A "$UA" https://diariodarepublica.pt/dr/scripts/dr.model.js -o dr.model.js
# dr.model.js:  drModel.staticEntities.<group>, "<name>"  ->  get...Record("<uuid>")
# moduleinfo:   data.modules["<moduleKey>"].staticEntities["<entityKey>"]["<uuid>"] = "<id>"
```

`moduleinfo` also contains `manifest.urlVersions`, the complete list of **158
screen JS files** — the fastest way to find any future DRE screen.

## Appendix B — new fixtures

| Path | Size | What |
|---|---|---|
| `tests/fixtures/pt/metadata-sample-59.jsonl.gz` | 125 KB | The 59-diploma sample: catalogue row + surface A header + surface B detail (`Texto`/`TextoFormatado` stripped, `ELIMetadataHTML` kept) + surface D. Every fill rate in §2 is reproducible from it. |
| `tests/fixtures/pt/aj-informacoes-gerais-codigo-civil.json` | 9.3 KB | `DetalheAJ` + the 40-entry `ThesaurusTreeList` for the Código Civil |
| `tests/fixtures/pt/aj-associacoes-codigo-civil.json` | 24 KB | All 7 association tabs (lists trimmed to 5 rows each) |
| `tests/fixtures/pt/legcons-snapshot-portaria-298-2018.json` | 67 KB | A complete 20-fragment consolidated snapshot — the smallest one that still has `Nota`, `AlteracoesList`, an anexo and a signature block |
| `tests/fixtures/pt/dre-static-entities.json` | 2.7 KB | Appendix A as JSON |
