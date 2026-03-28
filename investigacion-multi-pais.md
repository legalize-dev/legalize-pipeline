# Investigación: APIs de Legislación para Expansión Multi-País

**Fecha:** 2026-03-28
**Objetivo:** Evaluar Francia, Reino Unido y Alemania como siguiente país para Legalize
**Estado actual:** España completa (8.642 leyes del BOE)

---

## Índice

1. [Francia (Légifrance / DILA)](#1-francia)
2. [Reino Unido (legislation.gov.uk)](#2-reino-unido)
3. [Alemania (gesetze-im-internet.de)](#3-alemania)
4. [Arquitectura de repos multi-país](#4-arquitectura-de-repos)
5. [Análisis del código actual — ¿Qué hay que cambiar?](#5-análisis-del-código-actual)
6. [Comparativa y recomendación final](#6-comparativa-y-recomendación)

---

## 1. Francia (Légifrance / DILA) {#1-francia}

### A) API Disponible

| Campo | Detalle |
|-------|---------|
| **URL base (sandbox)** | `https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app/` |
| **URL base (producción)** | `https://api.aife.economie.gouv.fr/dila/legifrance-beta/lf-engine-app/` |
| **Autenticación** | OAuth 2.0 (Client Credentials). Registro gratuito en https://piste.gouv.fr |
| **Formatos** | JSON (API), XML (open data descargable) |
| **Rate limits** | No documentados públicamente |
| **Documentación** | https://piste.gouv.fr + https://www.legifrance.gouv.fr/contenu/menu/pied-de-page/foire-aux-questions-api |

**Alternativa Open Data (sin API key):**
- Dump completo de la base LEGI en XML: `ftp://echanges.dila.gouv.fr/LEGI/`
- Dataset en data.gouv.fr: https://www.data.gouv.fr/datasets/legi-codes-lois-et-reglements-consolides
- ~1.5 millones de ficheros XML, ~10 GB descomprimido
- Snapshot completo 2x/año + actualizaciones diarias incrementales por FTP

### B) Estructura de Datos

**Identificadores:**
- `LEGITEXT000006069414` — identificador único de texto consolidado
- `LEGIARTI000006307920` — identificador de artículo (con versión)
- `JORFTEXT` — identificador de publicación en el Journal Officiel
- `NOR` — identificador normalizado (desde 1987)
- `CID` — identificador común entre versiones de un mismo objeto

**Texto consolidado con versiones históricas:**
- SÍ. La base LEGI proporciona texto consolidado con versiones históricas embebidas
- Los artículos están versionados: cada LEGIARTI es una versión específica
- Se puede obtener un artículo tal como estaba en una fecha concreta
- Las versiones modificadas/derogadas coexisten con las vigentes
- Metadatos incluyen fechas de modificación → reconstrucción de historial determinista

**Metadatos disponibles:**
- Identificador (LEGIARTI, LEGITEXT)
- Tipo de norma (loi, décret, ordonnance, code...)
- Fecha de publicación
- Fecha de última actualización
- Estado jurídico (en vigueur, abrogé, etc.)
- Referencia JORF
- URL fuente

**Estructura del texto:**
- Códigos → Títulos/Libros → Capítulos → Secciones → Artículos
- Artículos con atributo `num` (ej: "L111-1" en Code du travail)
- XML sigue DTD_LEGIFRANCE con DTDs genéricos y específicos por base

### C) Catálogo

- **77 códigos oficiales en vigor** (Code civil, Code du travail, Code pénal, etc.)
- **29 códigos abrogados/históricos**
- **Constitución de 1958** con enmiendas + preámbulos (1946, 1789)
- Leyes, decretos-ley, ordenanzas, decretos desde 1945
- **Jerarquía:** Constitution → Lois organiques → Lois ordinaires → Ordonnances → Décrets → Arrêtés
- **Filtros:** por estado (vigente/derogado), tipo, rango de fechas
- **Volumen total LEGI:** ~1.5M ficheros XML

### D) Viabilidad

**ALTA. ETL determinista totalmente factible.**

Razones:
1. Texto consolidado con versiones embebidas (como el BOE)
2. XML estructurado con metadata clara
3. No requiere IA ni scraping
4. Registro histórico completo desde 1945

**Proyecto existente casi idéntico a Legalize:**
- **Archéo Lex** (https://archeo-lex.fr / GitHub: `Legilibre/Archeo-Lex`)
  - Convierte TODA la base LEGI a Git + Markdown
  - Usa XML consolidado y metadata de versiones
  - ETL determinista con commits con fechas históricas
  - **Es literalmente lo que hace Legalize para España**

Otros proyectos:
- `Legilibre/Legit.jl` — librería Julia para LEGI → Git + Markdown
- `steeve/france.code-civil` — Code Civil como repo Git
- `rdassignies/pylegifrance` — cliente Python para la API
- `Envinorma/leginorma` — wrapper Python con `consult_article()`, `consult_law_decree()`

### E) Ejemplo Real

**Llamada a la API (POST):**
```
POST https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app/consult/getArticle
Authorization: Bearer <token>
Content-Type: application/json

{"id": "LEGIARTI000006307920"}
```

**Respuesta (estructura):**
```json
{
  "executionTime": 45,
  "article": {
    "id": "LEGIARTI000006307920",
    "idTexte": "LEGITEXT000006069414",
    "type": "article",
    "num": "1",
    "texte": "La France est une République indivisible...",
    "dateVersion": "2008-07-23"
  }
}
```

**XML Open Data (estructura LEGI):**
```xml
<article num="1">
  <version date="1958-10-04">
    <texte>La France est une République indivisible...</texte>
  </version>
  <version date="2008-07-23">
    <texte>La France est une République indivisible, laïque, démocratique...</texte>
  </version>
</article>
```

---

## 2. Reino Unido (legislation.gov.uk) {#2-reino-unido}

### A) API Disponible

| Campo | Detalle |
|-------|---------|
| **URL base** | `https://www.legislation.gov.uk` |
| **Autenticación** | **Ninguna.** API completamente abierta |
| **Formatos** | XML (CLML), XML (Akoma Ntoso), HTML, RDF/XML, PDF, Atom feeds |
| **Rate limits** | **3.000 peticiones / 5 minutos** por IP. Requiere header `User-Agent` |
| **Documentación** | https://www.legislation.gov.uk/developer + https://legislation.github.io/data-documentation/api/overview.html |

**Acceso:** RESTful. Añadir `/data.xml` a cualquier URL de legislación para obtener XML. Añadir `/data.feed` para Atom.

### B) Estructura de Datos

**Identificadores (URIs jerárquicos):**
```
https://www.legislation.gov.uk/{type}/{year}/{number}
```

Tipos principales:
- `ukpga` — UK Public General Acts
- `ukla` — UK Local Acts
- `uksi` — UK Statutory Instruments
- `asp` — Acts of the Scottish Parliament
- `aep` — Acts of English Parliament (desde 1267!)

Ejemplos:
- Human Rights Act 1998: `ukpga/1998/42`
- Transport Act 1985: `ukpga/1985/67`

**Texto consolidado y versiones históricas:**
- **Versión actual:** URL base devuelve texto consolidado con todas las enmiendas incorporadas
- **Versión original:** Versión "as enacted" disponible por separado
- **Point-in-time:** Acceso a la ley tal como estaba en cualquier fecha específica:
  ```
  https://www.legislation.gov.uk/ukpga/1985/67/1997-06-01
  ```
- **Fecha base:** 1 de febrero de 1991 para la mayoría de legislación
- **Timeline of Changes:** Metadata con todas las fechas en que entraron en vigor cambios

**Metadatos disponibles:**
- Título
- URN (identificador único)
- Fecha de promulgación/entrada en vigor
- Fecha de publicación
- Extensión geográfica (England, Scotland, Wales, NI)
- Estado (in force, repealed, etc.)
- Enmiendas aplicadas y pendientes
- Enlaces a legislación que la modifica
- Dublin Core metadata

**Estructura del texto (CLML XML):**
```xml
<Body>
  <Part>
    <Number>1</Number>
    <Title>Introduction</Title>
    <Chapter>
      <Section>
        <Number>1</Number>
        <Heading>The Convention Rights</Heading>
        <Subsection>
          <Number>1</Number>
          <Text>...</Text>
```

### C) Catálogo

- **~7.000+ Acts** (legislación primaria en vigor)
- **50.000+ Statutory Instruments** (legislación secundaria)
- **Toda la legislación desde 1267** (cobertura parcial pre-1801, completa post-1988)
- Browse por tipo: `https://www.legislation.gov.uk/ukpga` (orden cronológico inverso)
- Search API con filtros por tipo, año, texto completo
- **Publication Log Feed:** actualizaciones diarias publicadas en 24h
  ```
  https://www.legislation.gov.uk/update/data.feed
  ```

### D) Viabilidad

**MUY ALTA. La API más fácil de las tres.**

Razones:
1. **Sin autenticación** — completamente abierta
2. **URIs estables y predecibles** — `type/year/number`
3. **Point-in-time integrado** — no hay que reconstruir historial
4. **3.000 req/5min** = 36.000 req/hora → suficiente para ~7.000 acts
5. **Publication Log** → sabe qué cambió cada día (como el sumario BOE)
6. **XML CLML** bien documentado con schema propio

Desafíos:
- Retraso editorial: no todas las leyes están perfectamente al día
- Cobertura histórica incompleta antes de 1991
- Catálogo grande (50.000+ SIs puede ser mucho volumen)

**Proyecto existente:**
- `kclquantlaw/pipeline` (GitHub) — pipeline cross-Act para parsear desde legislation.gov.uk
- Demuestra ETL determinista factible

### E) Ejemplo Real

**Human Rights Act 1998 — XML:**
```
GET https://www.legislation.gov.uk/ukpga/1998/42/data.xml
```

**Acceso granular:**
```
/ukpga/1998/42/part/1/data.xml     → solo Part 1
/ukpga/1998/42/section/1/data.xml  → solo Section 1
/ukpga/1998/42/schedule/1/data.xml → solo Schedule 1
```

**Point-in-time:**
```
/ukpga/1998/42/1998-10-02  → versión original al promulgarse
/ukpga/1998/42             → versión consolidada actual
```

**Estructura XML (CLML):**
```xml
<Metadata>
  <dc:title>Human Rights Act 1998</dc:title>
  <dc:identifier>http://www.legislation.gov.uk/id/ukpga/1998/42</dc:identifier>
  <dc:date name="made">1998-11-09</dc:date>
</Metadata>
<Body>
  <Part Number="1" id="part-1">
    <Title>The Convention Rights</Title>
    <Section Number="1" id="section-1">
      <Heading>The Convention Rights.</Heading>
      <Subsection>
        <Number>(1)</Number>
        <Text>In this Act "the Convention rights" means the rights...</Text>
      </Subsection>
    </Section>
  </Part>
</Body>
```

---

## 3. Alemania (gesetze-im-internet.de) {#3-alemania}

### A) API Disponible

#### Fuente principal: gesetze-im-internet.de

| Campo | Detalle |
|-------|---------|
| **URL base** | `https://www.gesetze-im-internet.de/` |
| **Autenticación** | **Ninguna.** Acceso abierto |
| **Formatos** | XML (descarga directa), HTML, PDF, ePUB |
| **Rate limits** | No publicados (respetar carga del servidor) |
| **Catálogo XML** | `https://www.gesetze-im-internet.de/gii-toc.xml` |
| **DTD** | `https://www.gesetze-im-internet.de/dtd/1.01/gii-norm.dtd` |

**Patrón de descarga directa:**
```
https://www.gesetze-im-internet.de/{abreviatura}/xml.zip
```
Ejemplo: `https://www.gesetze-im-internet.de/gg/xml.zip` (Grundgesetz)

#### Fuente secundaria: OffeneGesetze.de (BGBl digitalizado)

| Campo | Detalle |
|-------|---------|
| **API** | `https://api.offenegesetze.de/v1/veroeffentlichung/` |
| **Autenticación** | Ninguna |
| **Formato** | JSON REST |
| **Contenido** | Todas las publicaciones del BGBl desde 1949 |

#### Fuente emergente: rechtsinformationen.bund.de (NeuRIS)

| Campo | Detalle |
|-------|---------|
| **API** | `https://testphase.rechtsinformationen.bund.de/v1` |
| **Autenticación** | Ninguna |
| **Formato** | JSON REST + XML/HTML |
| **Estándar** | ELI (European Legislation Identifier) |
| **Estado** | Fase de pruebas (2025) |

### B) Estructura de Datos

**Identificadores (múltiples sistemas):**
- **Abreviatura:** `gg` (Grundgesetz), `bgb` (BGB), `stgb` (StGB)
- **BGBl:** `bgbl1-2021-40-5` (Teil I, año, número, página)
- **ELI:** `eli/bund/BGBl-1/2021/40` (estándar europeo, en NeuRIS)

**Texto consolidado SIN versiones históricas embebidas:**
- gesetze-im-internet.de proporciona solo la versión consolidada actual
- **NO hay equivalente a los `<bloque>` del BOE ni a las versiones de Légifrance**
- Para reconstruir historial: cruzar con publicaciones del BGBl
- Las fechas de enmienda están en los metadatos (`stand: letzte Fassung vom...`)

**Metadatos disponibles:**
- Título de la ley
- Fecha de promulgación
- Fecha de última enmienda
- Estado (vigente/derogada — implícito por presencia en el catálogo)
- URL fuente oficial

**Estructura del texto XML:**
```xml
<norm>
  <head>
    <metadaten>
      <ID>gg</ID>
      <titel>Grundgesetz für die Bundesrepublik Deutschland</titel>
      <stand>letzte Fassung vom 25. März 2025</stand>
    </metadaten>
  </head>
  <body>
    <artikel>
      <enbez>Artikel 1</enbez>
      <abs>
        <enbez>Abs. 1</enbez>
        <p>Die Würde des Menschen ist unantastbar...</p>
      </abs>
    </artikel>
  </body>
</norm>
```

Notas:
- Artículos con `<enbez>` (§ N o Artikel N)
- Párrafos con `<abs>` + `<p>`
- Tablas con `<row>` y `<entry>` (no HTML estándar)

### C) Catálogo

- **>6.000 leyes federales** en el catálogo
- Incluye: Bundesgesetze, Verordnungen, Bundesrechtsverordnungen
- Catálogo completo en XML: `https://www.gesetze-im-internet.de/gii-toc.xml`
- Actualizaciones diarias
- **Sin filtros nativos por tipo** — hay que filtrar post-descarga
- Traducciones al inglés disponibles para leyes seleccionadas

### D) Viabilidad

**MEDIA-ALTA. Factible pero más complejo que Francia o UK.**

La dificultad principal: **no hay versiones históricas embebidas**. Hay que reconstruir el historial cruzando con el BGBl.

Estrategia de reconstrucción:
1. Descargar XML consolidado actual de gesetze-im-internet.de
2. Obtener cadena de enmiendas del BGBl vía OffeneGesetze.de
3. Reconstruir versiones anteriores restando enmiendas (o tomando snapshots del catálogo)
4. Crear commits con fechas históricas desde los metadatos del BGBl

**Proyectos existentes (demuestran viabilidad):**
1. **bundestag/gesetze** (GitHub) — Todas las leyes federales en Markdown con historial Git. **Referencia directa.**
2. **bundestag/gesetze-tools** — Scripts Python para XML → Markdown
3. **maxsagt/de_laws_to_json** — Procesa las 6.000+ leyes a JSON
4. **OffeneGesetze.de** — Archivo BGBl completo (1949–presente) con API
5. **OKF DE / Bundes-Git** — Proyecto pionero de leyes alemanas en GitHub

### E) Ejemplo Real

**Descarga del Grundgesetz:**
```bash
curl -o gg.xml.zip https://www.gesetze-im-internet.de/gg/xml.zip
unzip gg.xml.zip
```

**Consulta de enmiendas recientes (OffeneGesetze):**
```
GET https://api.offenegesetze.de/v1/veroeffentlichung/?kind=bgbl1&q=Grundgesetz
```

**Respuesta JSON (estructura):**
```json
{
  "id": "bgbl1-2025-94",
  "kind": "bgbl1",
  "year": 2025,
  "number": 94,
  "date": "2025-03-27",
  "title": "69. Änderung des Grundgesetzes",
  "num_pages": 15
}
```

---

## 4. Arquitectura de Repos Multi-País {#4-arquitectura-de-repos}

### El problema de escala

Con España ya tenemos 8.642 leyes con múltiples commits cada una (bootstrap + reformas). Si metemos UK (~7.000 acts + 50.000 SIs), Francia (~77 códigos + miles de leyes) y Alemania (~6.000 leyes), un monorepo tendría cientos de miles de commits y decenas de miles de ficheros. `git clone` sería impracticable para los usuarios.

### Decisión: un repo por país + repo hub

**Estructura de GitHub:**

```
EnriqueLop/legalize           → Hub: web (legalize.dev), docs, CLI unificado, índice
EnriqueLop/legalize-es        → Leyes españolas (migración del actual legalize)
EnriqueLop/legalize-uk        → Leyes UK (primer país nuevo)
EnriqueLop/legalize-fr        → Leyes francesas
EnriqueLop/legalize-de        → Leyes alemanas
EnriqueLop/legalize-pipeline  → Este repo (genera todos los anteriores)
```

### ¿Por qué no submodules?

Los submodules de Git son problemáticos para los usuarios finales: requieren `--recursive` en el clone, las actualizaciones necesitan `git submodule update --init`, los forks rompen las referencias, y los diffs entre submodules son hashes crípticos. Añaden fricción sin aportar valor real a un proyecto donde cada repo es independiente.

### El repo `legalize` como hub

El repo `legalize` NO contiene legislación. Es un repo ligero que contiene:

1. **README índice** — Lista de países disponibles con enlaces a cada repo, estadísticas (número de leyes, último update), y badges de estado.

2. **Web legalize.dev** — GitHub Pages (o similar) como punto de entrada unificado. Desde aquí se puede navegar y buscar legislación de todos los países.

3. **CLI unificado** (opcional, futuro) — Un `legalize search "constitución"` que consulta todos los repos vía API de GitHub o clones locales. Esto se puede añadir más adelante cuando haya masa crítica de países.

4. **Documentación** — Cómo contribuir, cómo usar los repos, el formato de los ficheros, la convención de commits.

### Migración del repo actual

Pasos para migrar `legalize` → `legalize-es`:

1. En GitHub: `EnriqueLop/legalize` → Settings → Rename → `legalize-es`
   (preserva todos los commits, issues, stars; GitHub redirige URLs antiguas)
2. Crear nuevo repo `EnriqueLop/legalize` (vacío, con README inicial)
3. Actualizar remotes en clones locales:
   ```bash
   git remote set-url origin git@github.com:EnriqueLop/legalize-es.git
   ```
4. Actualizar `config.yaml` del pipeline para apuntar a `legalize-es`

### Impacto en el pipeline

El pipeline necesita saber a qué repo empujar cada país. Cambios en `config.yaml`:

```yaml
# Antes
output:
  repo: "legalize"

# Después
countries:
  es:
    repo: "legalize-es"
    dir: "spain"
    source: "boe"
  uk:
    repo: "legalize-uk"
    dir: "uk"
    source: "legislation_gov_uk"
```

El `git_ops.py` ya trabaja con rutas configurables, así que el cambio es mínimo: pasar el repo de destino como parámetro en vez de tenerlo hardcodeado.

### Convenciones entre repos de país

Todos los repos de país siguen el mismo formato para que la web y el CLI puedan consumirlos uniformemente:

- **Estructura de ficheros:** `{identificador}.md` en la raíz (sin subcarpeta de país, ya que el repo ES el país)
- **Frontmatter YAML:** mismos campos (`titulo`, `identificador`, `pais`, `rango`, `estado`, `fuente`, etc.)
- **Commits:** mismos tipos (`[bootstrap]`, `[reforma]`, `[nueva]`, `[derogacion]`...) y trailers (`Source-Id`, `Source-Date`, `Norm-Id`)
- **Author:** `Legalize <legalize@legalize.es>` (o un dominio por país, TBD)

Esto permite que cualquier herramienta que funcione con un repo funcione con todos.

---

## 5. Análisis del Código Actual — ¿Qué Hay Que Cambiar? {#5-análisis-del-código-actual}

### Lo que YA es genérico (no hay que tocar)

| Módulo | Estado | Detalles |
|--------|--------|----------|
| **models.py** — Data models | ✅ Genérico | `COUNTRIES` dict preparado para multi-país. `NormaMetadata` usa campos genéricos (`identificador`, `pais`, `fuente`). `CommitType` y `EstadoNorma` son universales. `Bloque`, `Version`, `Reform` son agnósticos de la fuente. |
| **transformer/markdown.py** | ✅ Genérico | Mapeo CSS→MD data-driven. Trabaja con objetos `Paragraph` normalizados. `render_norma_at_date()` no sabe nada del BOE. |
| **transformer/frontmatter.py** | ✅ Genérico | YAML genérico: `titulo`, `identificador`, `pais`, `rango`, `estado`, `fuente`. |
| **transformer/slug.py** | ✅ Genérico | Patrón `{country_dir}/{identificador}.md`. Usa `country_dir(metadata.pais)`. |
| **committer/git_ops.py** | ✅ Genérico | Toma `CommitInfo`, no sabe de BOE. Soporta fechas históricas. |
| **committer/message.py** | ✅ Genérico | Trailers genéricos: `Source-Id`, `Source-Date`, `Norm-Id`. |
| **state/store.py** | ✅ Genérico | `state.json` con campos genéricos. |

### Lo que está ACOPLADO al BOE (necesita abstracción)

#### 1. `fetcher/client.py` — **Completamente BOE-specific** 🔴

`BOEClient` con endpoints BOE hardcodeados:
- `get_sumario()`, `get_texto_consolidado()`, `get_metadatos()`, `get_catalogo()`
- Todas las URLs construidas desde `boe.base_url = "https://www.boe.es/datosabiertos"`
- **No hay capa de abstracción** — para añadir Francia necesitarías un `JORFClient` paralelo

**Lo que falta:** una interfaz `LegislativeSource` (ABC):
```python
class LegislativeSource(ABC):
    def fetch_metadata(self, norm_id: str) -> NormaMetadata: ...
    def fetch_text(self, norm_id: str) -> bytes: ...
    def discover_norms(self, scope: ScopeConfig) -> Iterator[str]: ...
```

#### 2. `transformer/metadata.py` — **Completamente BOE-specific** 🔴

- `parse_metadatos()` parsea el schema XML del BOE con campos hardcodeados
- `_RANGO_CODE_MAP` con códigos BOE (1070=Constitución, 1010=LO...)
- `_RANGO_MAP` con términos jurídicos españoles
- Línea ~200: `pais="es"` hardcodeado
- `_infer_rango_from_titulo()` usa patrones de títulos españoles

**Lo que falta:** un `MetadataParser` (ABC) con implementaciones por país.

#### 3. `fetcher/sumario.py` — **Completamente BOE-specific** 🔴

- Parsea XML del sumario diario del BOE
- Secciones legislativas hardcodeadas: `_SECCIONES_LEGISLATIVAS = {"1", "1A", "T"}`
- Excluye domingos (calendario de publicación del BOE)
- Inferencia de rango por título usando patrones españoles

**Lo que falta:** un `DiscoveryStrategy` (ABC) — cada país descubre normas de forma diferente.

#### 4. `fetcher/catalogo.py` — **BOE-specific** 🟡

- `iter_normas_from_sumarios()` asume sumarios diarios (modelo BOE)
- No generalizable a otros calendarios de publicación

#### 5. `models.py` — Enum `Rango` **solo español** 🟡

- Solo define tipos de documentos españoles: `CONSTITUCION`, `LEY_ORGANICA`, `LEY`, `REAL_DECRETO_LEY`...
- Francia necesitaría: `LOI`, `DECRET`, `ORDONNANCE`, `CODE`...
- Alemania: `BUNDESGESETZ`, `VERORDNUNG`, `GRUNDGESETZ`...
- UK: `ACT`, `STATUTORY_INSTRUMENT`...

**Lo que falta:** sistema de tipos de documento por país (enum separado o registro dinámico).

#### 6. `config.py` — Clase `BOEConfig` 🟡

- Hardcodea `base_url = "https://www.boe.es/datosabiertos"`
- Estructura de peticiones asume API BOE
- Necesita ser extensible por país

#### 7. `pipeline.py` — Usa `BOEClient` directamente 🟡

```python
from legalize.fetcher.client import BOEClient
with BOEClient(config.boe, cache) as client:
    meta_xml = client.get_metadatos(boe_id)
```
Necesitaría usar la interfaz genérica `LegislativeSource`.

### Estrategia de implementación: país paralelo (sin refactoring previo)

En vez de abstraer antes de implementar (riesgo de sobre-ingeniería), la estrategia es crear UK como módulo paralelo que reutiliza las capas genéricas sin tocar el código de España. Cuando tengamos dos países funcionando, extraemos las interfaces comunes con conocimiento real.

| Fase | Qué hacer | Esfuerzo | Cuándo |
|------|-----------|----------|--------|
| **1. Migrar repo** | Renombrar `legalize` → `legalize-es`, crear hub `legalize` | Bajo | Antes de todo |
| **2. Config multi-repo** | Extender `config.yaml` con repo de destino por país | Bajo | Con la migración |
| **3. Módulo UK paralelo** | Nuevo `sources/uk/` con fetcher, parser, metadata propios | Medio | Primer país nuevo |
| **4. Reutilizar capas genéricas** | UK usa `markdown.py`, `frontmatter.py`, `git_ops.py`, `message.py` | Bajo | Automático |
| **5. Abstraer (posterior)** | Extraer `LegislativeSource` ABC cuando haya 2 implementaciones reales | Medio | Tras UK funcionando |

**Estructura propuesta (fase UK):**
```
src/legalize/
├── fetcher/              # España (sin tocar)
│   ├── client.py
│   ├── sumario.py
│   └── catalogo.py
├── sources/              # NUEVO — países adicionales
│   └── uk/
│       ├── client.py     # UKClient (legislation.gov.uk)
│       ├── discovery.py  # Descubrimiento via Atom feed
│       └── metadata.py   # Parser de CLML metadata
├── transformer/
│   ├── metadata.py       # actual (BOE-specific, no tocar)
│   ├── xml_parser.py     # genérico (reutilizable)
│   ├── xml_parser_uk.py  # NUEVO — parser CLML → Bloque
│   ├── markdown.py       # genérico (reutilizable tal cual)
│   └── frontmatter.py    # genérico (reutilizable tal cual)
├── committer/            # genérico, sin cambios
├── models.py             # añadir RangoUK + ampliar COUNTRIES
├── pipeline.py           # añadir flujo uk_bootstrap(), uk_daily()
└── config.yaml           # sección countries con repo destino por país
```

**Nota sobre slug.py:** Con repos separados por país, el patrón cambia de `{country_dir}/{identificador}.md` a simplemente `{identificador}.md` (el país ya está implícito en el repo). Esto se ajusta en la config.

---

## 6. Comparativa y Recomendación Final {#6-comparativa-y-recomendación}

### Tabla comparativa

| Criterio | 🇫🇷 Francia | 🇬🇧 Reino Unido | 🇩🇪 Alemania |
|----------|------------|---------------|------------|
| **API abierta (sin key)** | ❌ Requiere OAuth (gratuito) | ✅ Completamente abierta | ✅ Descarga directa |
| **Formato** | JSON (API) / XML (open data) | XML (CLML) + 5 formatos más | XML (descarga zip) |
| **Versiones históricas** | ✅ Embebidas (como BOE) | ✅ Point-in-time por URL | ❌ Solo versión actual |
| **Rate limits** | No documentados | 3.000 req / 5 min | No documentados |
| **Catálogo listable** | ✅ (open data dump) | ✅ (browse + feed) | ✅ (`gii-toc.xml`) |
| **Tamaño catálogo** | ~77 códigos + miles de leyes | ~7.000 acts + 50.000 SIs | ~6.000+ leyes federales |
| **Proyecto precedente** | ✅ Archéo Lex (idéntico) | ✅ kclquantlaw/pipeline | ✅ bundestag/gesetze (idéntico) |
| **Similitud con BOE** | ⭐⭐⭐⭐⭐ (muy similar) | ⭐⭐⭐⭐ (similar, diferente formato) | ⭐⭐⭐ (sin versiones embebidas) |
| **Esfuerzo implementación** | Medio | **Bajo** | Medio-Alto |
| **Complejidad de historial** | Baja (embebido) | **Muy baja** (URL por fecha) | Alta (reconstruir desde BGBl) |

### Recomendación: 🇬🇧 Reino Unido primero

**El siguiente país más fácil de añadir es Reino Unido**, por estas razones:

1. **API sin autenticación** — no hay que gestionar tokens OAuth ni registros
2. **Point-in-time por URL** — el historial viene gratis, sin parsing de versiones
3. **Formato CLML bien documentado** — schema público en GitHub (`legislation/clml-schema`)
4. **Rate limit generoso** — 36.000 req/hora es más que suficiente para bootstrap
5. **Publication Log** — equivalente directo al sumario diario del BOE
6. **URIs predecibles** — `type/year/number` es incluso más limpio que BOE-A-XXXX

**Segundo lugar: Francia**, porque:
- Archéo Lex demuestra que es 100% factible
- La base LEGI es extremadamente similar al BOE
- Pero requiere registro OAuth y gestionar tokens

**Tercer lugar: Alemania**, porque:
- No hay versiones históricas embebidas → hay que reconstruir desde BGBl
- Pero bundestag/gesetze ya lo resolvió, así que hay referencia

### Plan de ejecución

| Paso | Qué | Esfuerzo | Notas |
|------|-----|----------|-------|
| 0 | Renombrar `legalize` → `legalize-es` en GitHub | 5 min | Settings → Rename |
| 1 | Crear repo hub `legalize` con README + web | 1 hora | Punto de entrada unificado |
| 2 | Actualizar `config.yaml` con estructura multi-repo | 1 hora | Nuevo campo `countries.es.repo` |
| 3 | Crear `sources/uk/client.py` — fetcher legislation.gov.uk | 1-2 días | API abierta, sin OAuth |
| 4 | Crear `sources/uk/metadata.py` — parser CLML | 1 día | Extraer metadata de XML CLML |
| 5 | Crear `transformer/xml_parser_uk.py` — CLML → Bloques | 1-2 días | Mapear estructura CLML a modelo existente |
| 6 | Ampliar `models.py` con `RangoUK` y `COUNTRIES["uk"]` | 2 horas | Añadir tipos de documento UK |
| 7 | Añadir flujo `uk_bootstrap()` en `pipeline.py` | 1 día | Paralelo a `bootstrap()` de España |
| 8 | Tests + bootstrap real con Human Rights Act 1998 | 1 día | Validar end-to-end |

**Total estimado: ~1 semana** para tener UK funcionando sin tocar nada de España.

---

## Fuentes y Enlaces

### Francia
- [DILA API en api.gouv.fr](https://api.gouv.fr/les-api/DILA_api_Legifrance)
- [Portal PISTE](https://piste.gouv.fr)
- [FAQ API Légifrance](https://www.legifrance.gouv.fr/contenu/menu/pied-de-page/foire-aux-questions-api)
- [Dataset LEGI en data.gouv.fr](https://www.data.gouv.fr/datasets/legi-codes-lois-et-reglements-consolides)
- [Archéo Lex](https://archeo-lex.fr/)
- [pylegifrance](https://github.com/rdassignies/pylegifrance)

### Reino Unido
- [Developer Zone](https://www.legislation.gov.uk/developer)
- [Data Documentation (GitHub)](https://legislation.github.io/data-documentation/api/overview.html)
- [CLML Schema](https://github.com/legislation/clml-schema)
- [Publication Log](https://legislation.github.io/data-documentation/api/publication-log.html)
- [kclquantlaw/pipeline](https://github.com/kclquantlaw/pipeline)

### Alemania
- [gesetze-im-internet.de](https://www.gesetze-im-internet.de/)
- [OffeneGesetze.de](https://offenegesetze.de/)
- [NeuRIS docs](https://docs.rechtsinformationen.bund.de/)
- [bundestag/gesetze](https://github.com/bundestag/gesetze)
- [bundestag/gesetze-tools](https://github.com/bundestag/gesetze-tools)
- [Bundes-Git (OKF)](https://okfn.de/en/projekte/bundesgit/)
