# Colombia (CO) — SUIN-Juriscol Research

## 0.1 Source

- Official source: SUIN-Juriscol, https://www.suin-juriscol.gov.co
- Law detail URL: `https://www.suin-juriscol.gov.co/viewDocument.asp?id=<INT>`
- Access pattern: HTML scraping only. No REST API found.
- TLS: the site currently has a broken certificate chain. The client uses `verify=False` and logs a warning.
- `robots.txt` checked from `https://www.suin-juriscol.gov.co/robots.txt`.
  - `Allow: /viewDocument.asp?id=*`
  - `Allow: /viewDocument.asp?ruta=*/*`
  - `Disallow: /estad468/`
  - Sitemaps are exposed for leyes, decretos, resoluciones, actos legislativos, and other document classes.
- ID range: `1_000_000..1_950_000`.
- Density: approximately 8%; estimated scope approximately 75,000 laws from probes.
- Known anchor: `id=1789030` -> `LEY-57-1887`.

## 0.2 Fixtures

Saved raw response bytes under `tests/fixtures/co/` using `requests.get(..., verify=False).content`.

| URL | Fixture | HTTP result |
|---|---|---|
| `https://www.suin-juriscol.gov.co/viewDocument.asp?id=1789030` | `sample-ley-1887.html` | `200 text/html` |
| `https://www.suin-juriscol.gov.co/viewDocument.asp?id=1000001` | `sample-acto-legislativo.html` | `200 text/html` |
| `https://www.suin-juriscol.gov.co/viewDocument.asp?id=1100073` | `sample-decreto.html` | `200 text/html`; `DECRETO-453-1981` |
| `https://www.suin-juriscol.gov.co/viewDocument.asp?id=1500073` | `sample-decreto-2900.html` | `200 text/html` |
| `https://www.suin-juriscol.gov.co/viewDocument.asp?id=1900000` | `sample-decreto-1993.html` | `200 text/html` |

## 0.3 Metadata Inventory

SUIN embeds metadata in a hidden block immediately after `a[name="arriba"]`. The stable extraction selector is `//span[@field]`; each field name is in the `field` attribute and the value is the span text.

| HTML element/selector | Field name | Example | Maps to |
|---|---|---|---|
| `//div[@id="titulotipo"]//h1` | Display identifier/title | `LEY 57 DE 1887` | `short_title`; identifier fallback |
| `//span[@field="tipo"]` | Rango / type | `LEY`, `DECRETO`, `ACTO LEGISLATIVO` | `rank`; identifier prefix |
| `//span[@field="numero"]` | Official number | `57` | `identifier` number |
| `//span[@field="anio"]` | Official year | `1887` | `identifier` year |
| `//span[@field="epigrafe"]` | Law title / epigraph | `Sobre adopción de Códigos y unificación de la legislación nacional` | `title`, `summary` |
| `//span[@field="estado_documento"]` | Estado de vigencia | `Vigente`, `DEROGADO`, `No vigente` | `status` |
| `//span[@field="documento_fuente"]` | Diario Oficial reference | `DIARIO OFICIAL. AÑO XXIII. N.7019. 20, ABRIL, 1887. PÁG.1` | `extra.gazette_reference` |
| `//span[@field="entidad_emisora"]` | Entidad emisora / department | `CONSEJO NACIONAL LEGISLATIVO` | `department` |
| `//span[@field="materia"]` | Materias / subjects | `Administración de justicia\|Penal` | `subjects` split on `|` |
| `//span[@field="fecha_diario_oficial"]` | Fecha publicación | `22/04/1887` | `publication_date` |
| `//span[@field="fecha_vigencia"]` | Fecha entrada en vigencia | `22/04/1887` | `extra.entry_into_force`; publication fallback |
| `//span[@field="fecha_expedicion"]` | Fecha expedición | `28/05/1910` | `extra.issued_date` |
| `//span[@field="fecha_fin_vigencia"]` | Fecha fin vigencia | `13/01/1994` | `extra.expiry_date` |
| `//span[@field="numero_diario_oficial"]` | Diario Oficial number | `7021` | `extra.gazette_number` |
| `//span[@field="pagina_diario_oficial"]` | Diario Oficial page | `445` | `extra.gazette_page` |
| `//span[@field="subtipo"]` | Subtype | `LEY ORDINARIA`, `DECRETO ORDINARIO` | `extra.subtype` |
| `//span[@field="sector"]` | Sector | `Función Pública`, `Minas y Energía` | `extra.sector` |
| `//span[@field="comentarios"]` | Comments | `La gran mayoría de las disposiciones...` | `extra.comments` |
| `//span[@field="fecha"]` | Compact date/script field | `188704 ... new Date(15/04/1887)` | Date fallback only |
| `//span[@field="descriptores"]` | Descriptors | empty in fixtures | Extra field not mapped |
| `//span[@field="division_documento"]` | Document division flag | `false` | Extra field not mapped |
| `//span[@field="es_reglamento"]` | Regulation flag | `false` | Extra field not mapped |
| `//span[@field="estado_excepcion"]` | Exception-state flag | `false` | Extra field not mapped |
| `//span[@field="tema"]` | Theme | empty in fixtures | Extra field not mapped |
| `//span[@field="titulo_uniforme"]` | Uniform title | empty in fixtures | Extra field not mapped |
| `//span[@field="es_codigo"]` | Code flag | `false` | Extra field not mapped |
| `//span[@field="marco_regulatorio"]` | Regulatory-framework flag | `false` | Extra field not mapped |
| `//span[@field="en_estudio_depuracion"]` | Depuration-study flag | `false` | Extra field not mapped |
| `//span[@field="Estatutos"]` | Estatutos | empty in fixtures | Extra field not mapped |
| `//span[@field="asunto"]` | Subject matter | empty in fixtures | Extra field not mapped |
| `//span[@field="de"]` | From field | empty in fixtures | Extra field not mapped |
| `//span[@field="documento_fuente2"]` | Secondary source reference | empty in fixtures | Extra field not mapped |
| `//span[@field="es_estatuto"]` | Statute flag | `false` in one fixture | Extra field not mapped |
| `//span[@field="fe_de_erratas"]` | Errata | empty in fixtures | Extra field not mapped |
| `//span[@field="fecha_diario_oficial2"]` | Secondary publication date | empty in fixtures | Extra field not mapped |
| `//span[@field="juris_estado_excepcion"]` | Exception-state jurisprudence | empty in fixtures | Extra field not mapped |
| `//span[@field="lugar_fecha"]` | Place/date | empty in fixtures | Extra field not mapped |
| `//span[@field="nombre_codigo"]` | Code name | empty in fixtures | Extra field not mapped |
| `//span[@field="notas_vigencias"]` | Validity notes | empty in fixtures | Extra field not mapped |
| `//span[@field="observaciones"]` | Observations | empty in fixtures | Extra field not mapped |
| `//span[@field="observaciones_internas"]` | Internal observations | empty in fixtures | Extra field not mapped |
| `//span[@field="pagina_diario_oficial_pdf"]` | Diario Oficial PDF page | `1`, `41` | Extra field not mapped |
| `//span[@field="pagina_diario_oficial2"]` | Secondary page | empty in fixtures | Extra field not mapped |
| `//span[@field="numero_diario_oficial2"]` | Secondary Diario Oficial number | empty in fixtures | Extra field not mapped |
| `//span[@field="para"]` | To field | empty in fixtures | Extra field not mapped |
| `//span[@field="separacion_numero"]` | Number separator | empty in fixtures | Extra field not mapped |
| `//div[contains(@id, "ResumenNotasVigencia")]//li[contains(@class, "referencia")]` | RESUMEN DE MODIFICACIONES | `Reformado Artículo 49 LEY 153 de 1887` | `extra.modification_count`, `extra.modification_summary` |
| Not found in captured fixtures | Última actualización | Not exposed in the five captured pages | Not mapped |

Identifier normalization:

- `LEY 57 DE 1887` -> `LEY-57-1887`
- `DECRETO 2900 DE 1966` -> `DECRETO-2900-1966`
- `ACTO LEGISLATIVO 1 DE 1910` -> `ACTO-LEGISLATIVO-1-1910`

## 0.4 Formatting Inventory

| Fixture | Body tables | Bold/italic | Numbered/lettered subsections | Article headings | Chapter/title headings | Footnotes | Cross-reference links | Signatories | Annexes |
|---|---|---|---|---|---|---|---|---|---|
| `sample-ley-1887.html` | No | Yes | Yes | Yes | Yes | No | Yes | Yes | No |
| `sample-acto-legislativo.html` | No | Yes | No | Yes | No | No | Yes | Yes | No |
| `sample-decreto.html` | No | Yes | Yes | No | No | No | No | Yes | No |
| `sample-decreto-2900.html` | No | Yes | No | Yes | No | No | No | Yes | No |
| `sample-decreto-1993.html` | Yes | Yes | Yes | Yes | No | No | Yes | Yes | No |

Confirmed text selectors:

- Body container: `//div[contains(@style, "padding: 15px")]`
- Article blocks: `.//div[starts-with(@id, "toggle_")]` inside the body container
- Article heading patterns: `Art. 1°.`, `Artículo 1º`, `ARTICULO 1o.`, `Artículo único.`
- Chapter/title heading patterns: paragraph text beginning `CAPITULO`, `CAPÍTULO`, `TITULO`, `TÍTULO`, `LIBRO`, `PARTE`, or `SECCIÓN`
- Signatory blocks: bottom plain `div` blocks after articles, often with `p[style*="text-align:right"]`
- Body tables: `.//table[not(contains(@class, "toc"))]` inside the body container
- Cross-reference links: `.//a[contains(@href, "viewDocument.asp")]`

## 0.5 Version History Spike

SUIN shows `RESUMEN DE MODIFICACIONES` as article-level reform cross-references. For `LEY-57-1887`, the summary contains 102 `li.referencia` items, with referenced years ranging from 1887 to 1990.

The summary identifies affected articles and source norms, for example `Reformado Artículo 49 LEY 153 de 1887` and `Derogado Artículo 31 LEY 1 de 1976`. It does not expose point-in-time full text for those historical states in the captured HTML, and no point-in-time API was found.

Decision: ship Colombia as single-snapshot, same as Latvia (`lv`). Capture reform cross-references in `extra.modification_summary` and `extra.modification_count`.

Follow-up: add full history only if SUIN later exposes point-in-time text or a documented historical text endpoint.

## 0.6 Scope

- Approximately 75,000 laws total, based on probed density across the configured ID range.
- One GET per law; metadata is embedded in the same HTML page as the text.
- Estimated bootstrap: approximately 50 hours at 5 workers with 1 second per-worker delay.
- No separate daily feed found. `generic_daily` / `discover_daily` yields nothing.

## 0.7 Format Coverage

Single-format source (HTML only); §0.7 N/A.
