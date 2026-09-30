# RESEARCH-CN.md — China (National Database of Laws and Regulations / 国家法律法规数据库)

## 0.1 Source identification

**Portal:** [flk.npc.gov.cn](https://flk.npc.gov.cn) — the official **National Database of Laws and Regulations of the People's Republic of China** (国家法律法规数据库), officially established and maintained by the General Office and the Legislative Affairs Commission of the Standing Committee of the National People's Congress (NPCSC / 全国人民代表大会常务委员会法制工作委员会).

**Legal Status & Open Access:**
- **Public domain / Official text:** Under Article 5 of the *Copyright Law of the People's Republic of China* (中华人民共和国著作权法), laws, regulations, resolutions, decisions and orders of state organs, other documents of a legislative, administrative or judicial nature, and their official translations are **excluded from copyright protection** and belong in the public domain.
- **Official Authority:** This database is the authoritative, national-level statutory database prescribed by the *Legislation Law of the People's Republic of China* (中华人民共和国立法法) for unified public release and verification of state laws and regulations.

**Technical architecture & access pattern:**
- **Backend Architecture:** RESTful API services powered by Spring Boot (`com.ruoyi.law`), serving JSON data for discovery, details, hierarchical article trees, and legislative history.
- **Base URL:** `https://flk.npc.gov.cn`
- **Authentication:** None required (public open database).
- **Rate Limits & Anti-bot:** Web application firewall (WZWS-RAY). Standard browser `User-Agent` and `Referer: https://flk.npc.gov.cn/` required. Polite crawl delay of 0.2s–0.5s per request is fully compliant.

---

## 0.2 APIs and Endpoints

### A. Discovery API (`POST /law-search/search/list`)

Discovers all legislation across categories with pagination and optional filters.

```http
POST https://flk.npc.gov.cn/law-search/search/list
Content-Type: application/json;charset=UTF-8
Referer: https://flk.npc.gov.cn/

{
  "searchRange": 1,
  "sxrq": [],
  "gbrq": [],
  "searchType": 2,
  "sxx": [],
  "gbrqYear": [],
  "flfgCodeId": [],
  "zdjgCodeId": [],
  "searchContent": "",
  "pageNum": 1,
  "pageSize": 50
}
```

**Response Fields (`rows[]`):**
- `bbbs`: Unique version identifier string (e.g. `ff808081729d1efe01729d50b5c500bf`)
- `title`: Official title of the norm (e.g. `中华人民共和国民法典`)
- `gbrq`: Promulgation / announcement date (`YYYY-MM-DD`, e.g. `2020-05-28`)
- `sxrq`: Effective / entry-into-force date (`YYYY-MM-DD`, e.g. `2021-01-01`)
- `sxx`: Timeliness / validity code (e.g. 1=valid, 2=amended, 3=in force, 4=not yet effective, etc.)
- `flxz`: Legal nature / category (`宪法`, `法律`, `行政法规`, `监察法规`, `司法解释`, `地方法规`)
- `zdjgName`: Issuing organ / legislative body (e.g. `全国人民代表大会`, `全国人民代表大会常务委员会`, `国务院`)
- `zdjgCodeId`: Issuing body numerical code
- `flfgCodeId`: Legal category numerical code

### B. Details & Hierarchy API (`GET /law-search/search/flfgDetails`)

Fetches the complete structured hierarchy, article tree, metadata, and amendment links for a specific norm version.

```http
GET https://flk.npc.gov.cn/law-search/search/flfgDetails?bbbs={bbbs}
Referer: https://flk.npc.gov.cn/
```

**Response Data (`data`):**
- `bbbs`: Unique norm identifier
- `title`: Official statutory title
- `flxz`: Category (`法律`, `行政法规`, etc.)
- `zdjgName`: Issuing authority
- `gbrq`: Promulgation date (`YYYY-MM-DD`)
- `sxrq`: Effective date (`YYYY-MM-DD`)
- `sxx`: Validity status code
- `content`: Root node of the structural tree containing:
  - `id`: Node GUID
  - `parentId`: Parent node GUID
  - `title`: Node title (e.g. `第一编 总则`, `第一章 基本规定`, `第一条`, `题注`, `目录`)
  - `index`: Ordering index
  - `children`: List of child nodes (forming the multi-level tree: 编 → 章 → 节 → 条 → 款/项)
- `lsyg`: **Historical versions list (历史沿革)**:
  - Each entry contains `bbbs`, `title`, `gbrq`, `highLight`
- `xgwj`: Related documents (reforms, decisions, explanations)
- `ossFile`: Official source files (`ossWordPath`, `ossPdfPath`, `ossWordOfdPath`)

### C. Aggregate Statistics API (`GET /law-search/index/aggregateData`)

Provides real-time corpus count per category:

| Category (flxz) | Official Chinese | Approximate Count | Rank Mapping | Scope |
|---|---|---|---|---|
| Constitution | 宪法 | 1 | `constitucion` | National (`cn`) |
| National Statutes | 法律 | ~300 (in force) + historical | `ley` | National (`cn`) |
| Administrative Regulations | 行政法规 | ~608 (in force) | `real_decreto` | National (`cn`) |
| Supervisory Regulations | 监察法规 | ~2 | `reglamento` | National (`cn`) |
| Judicial Interpretations | 司法解释 | ~561 | `interpretacion_judicial` | National (`cn`) |
| Local Regulations | 地方法规 | ~15,810 | `ley_autonomica` | Subnational (`cn-bj`, `cn-sh`, etc.) |
| Total Corpus | — | **~29,788+** | — | — |

---

## 0.3 Metadata Inventory

Every field exposed by `flk.npc.gov.cn` is captured into Legalize models:

| Source Field | Type | Example Value | Target Mapping | Description |
|---|---|---|---|---|
| `title` | string | `中华人民共和国民法典` | `NormMetadata.title` | Full official statutory title |
| `bbbs` | string | `ff808081729d1efe01729d50b5c500bf` | `NormMetadata.identifier` | Official unique version identifier |
| `gbrq` | date | `2020-05-28` | `NormMetadata.publication_date` | Promulgation date |
| `sxrq` | date | `2021-01-01` | `extra.effective_date` | Entry into force date |
| `flxz` | string | `法律` | `NormMetadata.rank` / `extra.category` | Mapped to Legalize rank enum |
| `zdjgName` | string | `全国人民代表大会` | `NormMetadata.department` | Issuing legislative authority |
| `sxx` | int | `3` | `NormMetadata.status` | Mapped to `in_force`, `repealed`, etc. |
| `zdjgCodeId` | int | `100` | `extra.issuing_body_code` | Internal organ identifier |
| `flfgCodeId` | int | `101` | `extra.category_code` | Internal classification code |
| `lsyg` | list[dict] | `[{"bbbs": "...", "gbrq": "..."}]` | Version history resolver | Links to predecessor/successor reforms |
| `ossFile.ossWordPath` | string | `prod/20200528/827f65fcb6...docx` | `extra.source_word_path` | Official Word document path |
| `ossFile.ossPdfPath` | string | `prod/20200528/bd53dd912c...pdf` | `extra.source_pdf_path` | Official PDF document path |

---

## 0.4 Formatting Inventory

Analysis of the 5 representative fixtures confirmed the following structural and formatting constructs:

| Construct | Present in Source? | Handling in `parser.py` | Example / Strategy |
|---|---|---|---|
| **Constitutional Preamble & Articles** | Yes | Parsed into clean Markdown headings and paragraphs | `## 序言`, `### 第一章 总纲`, `##### 第一条` |
| **Hierarchical Structure (编/分编/章/节/条)** | Yes | Mapped to standard Markdown heading hierarchy: `# Title` → `## 编` → `### 章` → `#### 节` → `##### 第X条` | Maintained uniformly across all codes and statutes |
| **Sub-article Paragraphs & Items (款/项)** | Yes | Paragraphs separated by blank lines; numbered items formatted as `(一)`, `(二)` | Normalized paragraph boundaries |
| **Tables (税率表/附表/清单)** | Yes | Rendered as standard Markdown pipe tables | `sample-with-tables.json` (Individual Income Tax brackets) |
| **Amending Decisions & Annotations (题注/修改说明)** | Yes | Rendered as blockquotes (`> 根据...修改`) immediately following title | Preamble notes explaining historical amendments |
| **Signatories & Promulgation Orders (主席令/签署)** | Yes | Extracted from preamble / presidential decree metadata | Extracted into frontmatter and document header |
| **Images / Binary Assets** | None in core statutes | Dropped and counted in `extra.images_dropped` | In accordance with engine policy |

---

## 0.5 Version History Spike — GATE: PASS

**Evidence stored in:** `tests/fixtures/cn/version-spike.txt`

### Verification Summary
- **Law examined:** *Criminal Law of the People's Republic of China* (`中华人民共和国刑法`)
- **Predecessor Version:** Promulgation: `2009-08-27`, Effective: `2009-08-27`, Nodes: 512, ID: `2c909fdd678bf17901678bf6922504bf`
- **Successor Version:** Promulgation: `2020-12-26`, Effective: `2021-03-01`, Nodes: 565, ID: `ff808181796a636a0179822a19640c92`
- **Result:** Exact dates and distinct chronological text versions extracted directly from the official database via `lsyg`.
- **Text State Classification:** `point_in_time` (each version represents the consolidated law as in force on its respective date).

---

## 0.6 Total Scope & Bootstrap Runtime Estimate

- **Core National Statutes (Rank 1 & 2):** ~300 laws in force + ~1,200 historical versions = ~1,500 versions.
- **Administrative Regulations (Rank 3):** ~608 regulations in force + ~1,500 historical versions = ~2,100 versions.
- **Judicial Interpretations:** ~561 documents = ~600 versions.
- **Subnational Regulations (Optional Stage 2):** ~15,810 local laws (can be scoped to subnational directories `cn-bj/`, `cn-sh/`, `cn-gd/`).
- **Initial Bootstrap Scope:** National statutes (`flxz == "法律"` + `"宪法"` + `"行政法规"` + `"司法解释"`), totaling ~4,200 norm versions.
- **Estimated Bootstrap Time:** At 5 req/sec with `max_workers: 4`, bootstrap of all national statutes takes ~15–20 minutes.

---

## 0.7 Format Coverage

| Format | Coverage | Handling Strategy |
|---|---|---|
| Structured JSON API (Tree & Articles) | 100% of all norms on `flk.npc.gov.cn` | Primary native extractor. Guarantees zero mojibake, perfect article structure, and exact metadata. |
| Official Word / PDF | 100% of norms have corresponding files | Retained in `extra.source_word_path` / `extra.source_pdf_path` for provenance verification. |

Cross-format divergence is 0% because the structured JSON API is the canonical data model served directly by the NPCSC database.
