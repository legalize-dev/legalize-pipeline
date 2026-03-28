# Legalize — Especificación Técnica del Proyecto

> **Nombre del proyecto:** Legalize
> **Estado:** borrador v0.1
> **Fecha:** 2026-03-27
> **Autor:** Enrique

---

## 1. Visión y objetivos

### 1.1 Qué es esto

Un repositorio público en GitHub donde **cada ley española vigente es un fichero Markdown** y **cada reforma publicada en el BOE se representa como un commit**. El histórico de Git se convierte así en el historial legislativo real del país: cualquier persona puede hacer `git log` sobre la Constitución y ver exactamente qué cambió, cuándo, y por qué disposición.

### 1.2 Por qué importa

El BOE publica legislación consolidada, pero su interfaz no permite comparar versiones de forma sencilla. Los juristas, periodistas, investigadores y ciudadanos merecen poder hacer `diff` entre la versión de una ley antes y después de una reforma, ver quién (qué disposición) introdujo cada cambio, y navegar el historial legislativo con las mismas herramientas que los desarrolladores usan para el código. Existen precedentes parciales — repos como `hpalacio/leyes` o `lex-es/constitucion` — pero ninguno cubre el corpus legislativo de forma sistemática ni automatiza la ingesta desde la API del BOE.

### 1.3 Objetivos del proyecto

- **O1 — Fidelidad:** el texto Markdown de cada ley debe ser fiel al texto consolidado oficial del BOE, preservando estructura (títulos, capítulos, secciones, artículos, disposiciones).
- **O2 — Trazabilidad:** cada commit debe enlazar unívocamente con la disposición del BOE que motivó el cambio.
- **O3 — Automatización:** el pipeline debe ejecutarse sin intervención humana, detectando nuevas publicaciones del BOE y aplicándolas.
- **O4 — Accesibilidad:** cualquiera con un navegador debe poder consultar el histórico en GitHub sin herramientas especiales.
- **O5 — Extensibilidad:** la arquitectura debe permitir escalar de un subconjunto piloto al corpus completo sin rediseño.

---

## 2. Contexto y estado del arte

### 2.1 La API de datos abiertos del BOE

La Agencia Estatal BOE expone una API REST en `https://www.boe.es/datosabiertos/` con tres familias principales de endpoints:

| Familia | Endpoint base | Utilidad para el proyecto |
|---|---|---|
| **Sumarios BOE** | `/api/boe/sumario/{YYYYMMDD}` | Detectar nuevas disposiciones publicadas cada día |
| **Legislación consolidada — catálogo** | `/api/legislacion-consolidada` | Listar normas por tipo, rango, departamento, fecha |
| **Legislación consolidada — norma** | `/api/legislacion-consolidada/id/{id}/texto` | Obtener el XML completo con todas las versiones de cada bloque |
| **Legislación consolidada — metadatos** | `/api/legislacion-consolidada/id/{id}/metadatos` | Título, rango, fecha publicación, estado de vigencia |
| **Legislación consolidada — índice** | `/api/legislacion-consolidada/id/{id}/texto/indice` | Estructura de bloques con sus IDs |

La API acepta `Accept: application/xml` y `Accept: application/json`. Para el parsing de texto legislativo, XML es preferible porque conserva la estructura semántica completa (nodos `<bloque>`, atributos `tipo`, versiones con fechas).

### 2.2 Estructura XML del texto consolidado

El texto consolidado del BOE se organiza en **bloques** (`<bloque>`). Cada bloque representa una unidad estructural de la norma:

```
norma
├── bloque tipo="preambulo"
├── bloque tipo="titulo_preliminar"
│   ├── bloque tipo="articulo" (Artículo 1)
│   ├── bloque tipo="articulo" (Artículo 2)
│   └── ...
├── bloque tipo="titulo"
│   ├── bloque tipo="capitulo"
│   │   ├── bloque tipo="articulo"
│   │   └── ...
│   └── ...
├── bloque tipo="disposicion_adicional"
├── bloque tipo="disposicion_transitoria"
├── bloque tipo="disposicion_derogatoria"
└── bloque tipo="disposicion_final"
```

Cada bloque tiene un `id` único y puede contener **múltiples versiones**. Cuando una reforma modifica un artículo, el BOE añade una nueva versión dentro del mismo bloque, con la fecha de publicación de la norma modificadora y su identificador (`BOE-A-YYYY-XXXXX`). Esto es clave para el proyecto: nos permite reconstruir el historial de cambios de cada artículo.

**Implicación fundamental: no necesitamos IA para detectar cambios.** El XML del BOE ya contiene toda la información versionada de forma estructurada. El pipeline es un ETL determinista — puro parsing de XML, composición de texto por versión, y generación de Markdown. No hay ambigüedad que requiera interpretación semántica. Cada versión de cada bloque dice explícitamente: "este texto fue introducido por la disposición X en la fecha Y, reemplazando la versión anterior".

### 2.3 Proyectos existentes y lecciones aprendidas

| Proyecto | Enfoque | Limitación |
|---|---|---|
| `hpalacio/leyes` | Constitución en AsciiDoc, commits por reforma | Solo Constitución, formato AsciiDoc, manual |
| `lex-es/constitucion` | Constitución en Markdown | Solo Constitución, sin automatización |
| `Legislacion/Constitucion` | Constitución en texto plano | Sin estructura, sin pipeline |
| `ComputingVictor/MCP-BOE` | Servidor MCP para acceso a API BOE | No genera repo, es una herramienta de consulta |

**Lecciones:** usar Markdown (más universal que AsciiDoc), automatizar desde la API (no manual), y pensar desde el inicio en escala más allá de la Constitución.

---

## 3. Arquitectura técnica

### 3.1 Vista general del pipeline

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────┐
│   BOE API   │────▶│   Fetcher    │────▶│  Transformer │────▶│  Committer│
│  (sumario + │     │  (descarga   │     │  (XML → MD   │     │  (git add │
│  consolid.) │     │   XML/JSON)  │     │   + diff)    │     │  + commit)│
└─────────────┘     └──────────────┘     └──────────────┘     └───────────┘
                           │                     │                    │
                           ▼                     ▼                    ▼
                    ┌──────────────┐     ┌──────────────┐     ┌───────────┐
                    │  State Store │     │   Templates  │     │  GitHub   │
                    │  (último BOE │     │   (formato   │     │  (push)   │
                    │  procesado)  │     │   Markdown)  │     └───────────┘
                    └──────────────┘     └──────────────┘
```

### 3.2 Componentes del sistema

#### 3.2.1 Fetcher — Obtención de datos

**Responsabilidad:** consultar la API del BOE, descargar sumarios diarios y textos consolidados.

**Flujo diario:**

1. Consultar `/api/boe/sumario/{fecha}` para obtener las disposiciones publicadas ese día.
2. Filtrar disposiciones que sean **modificaciones de normas existentes** o **nuevas normas** dentro del alcance del proyecto (por rango normativo: Ley Orgánica, Ley, Real Decreto-ley, Real Decreto Legislativo).
3. Para cada disposición relevante, identificar la norma afectada y descargar su texto consolidado actualizado vía `/api/legislacion-consolidada/id/{id}/texto`.
4. Almacenar el XML descargado en un directorio temporal de trabajo.

**Flujo de carga inicial (bootstrap):**

1. Consultar el catálogo completo de legislación consolidada filtrando por rango y fechas del alcance piloto.
2. Descargar el texto consolidado completo de cada norma.
3. Para cada norma, extraer **todas las versiones históricas** de cada bloque para reconstruir el historial de commits.

**Consideraciones:**

- La API del BOE no documenta rate limiting explícito, pero se debe implementar throttling voluntario (máx. 2 req/s, configurable) y backoff exponencial ante errores: espera inicial 2s, multiplicador x2, máximo 5 reintentos, con jitter aleatorio de ±25% para evitar thundering herd.
- Cachear respuestas XML localmente (directorio `.cache/`) con TTL de 24h para evitar re-descargas durante development y re-ejecuciones.
- Respetar cabeceras HTTP de cache (`ETag`, `Last-Modified`) para las llamadas a la API.

#### 3.2.2 Transformer — Conversión XML → Markdown

**Responsabilidad:** convertir el XML del BOE en Markdown estructurado y legible.

**Reglas de transformación:**

| Elemento XML | Resultado Markdown |
|---|---|
| `<bloque tipo="titulo_preliminar">` | `## Título Preliminar` |
| `<bloque tipo="titulo">` | `## Título I. De los derechos y deberes fundamentales` |
| `<bloque tipo="capitulo">` | `### Capítulo I. ...` |
| `<bloque tipo="seccion">` | `#### Sección 1.ª ...` |
| `<bloque tipo="articulo">` | `##### Artículo 1.` seguido del texto |
| `<bloque tipo="preambulo">` | Sección de preámbulo al inicio |
| `<bloque tipo="disposicion_adicional">` | `## Disposiciones adicionales` → `##### Primera.` |
| `<bloque tipo="disposicion_transitoria">` | `## Disposiciones transitorias` → `##### Primera.` |
| `<bloque tipo="disposicion_derogatoria">` | `## Disposición derogatoria` |
| `<bloque tipo="disposicion_final">` | `## Disposiciones finales` → `##### Primera.` |
| Párrafos dentro de bloques | Párrafos Markdown separados por línea en blanco |
| Listas numeradas en texto | Listas Markdown numeradas (`1.`, `2.`, etc.) |
| Notas a pie / referencias | Notas Markdown con `[^1]` si aplica |
| Tablas en el texto legal | Tablas Markdown con `|` |
| Texto en negrita/cursiva (énfasis) | `**negrita**` / `*cursiva*` según el original |

**Cabecera YAML frontmatter** (al inicio de cada fichero Markdown):

```yaml
---
titulo: "Constitución Española"
titulo_corto: "Constitución Española"
identificador_boe: "BOE-A-1978-31229"
rango: "constitucion"
fecha_publicacion: "1978-12-29"
fecha_ultima_modificacion: "2024-03-22"
estado: "vigente"
departamento: "Jefatura del Estado"
url_boe: "https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229"
url_pdf: "https://www.boe.es/buscar/pdf/1978/BOE-A-1978-31229-consolidado.pdf"
materias:
  - "Organización del Estado"
  - "Derechos fundamentales"
notas: ""
---
```

**Decisiones de diseño del Markdown:**

- Se usa **un solo fichero por norma**, no un fichero por artículo. Razón: facilita el `git diff` de reformas que tocan múltiples artículos de la misma ley a la vez, que es lo habitual.
- La jerarquía de headings refleja la estructura real de la norma (títulos > capítulos > secciones > artículos).
- No se incluye numeración automática en los headings — se usa la numeración original del BOE.
- Los párrafos dentro de un artículo se separan con líneas en blanco, preservando el formato original.

#### 3.2.3 Diffing Engine — Detección de cambios

**Responsabilidad:** comparar la versión actual del Markdown de una ley con la nueva versión generada tras una reforma, y producir los cambios mínimos necesarios.

**Estrategia:**

1. **Para el bootstrap (carga histórica):** se procesan las versiones en orden cronológico. La primera versión genera el fichero completo; cada versión posterior genera un diff respecto a la anterior.
2. **Para el flujo diario:** se regenera el Markdown de la norma afectada a partir del XML consolidado más reciente y se compara con el fichero existente en el repo.

**Granularidad del diff:** a nivel de fichero completo. Git se encarga del diff línea a línea. No necesitamos implementar diffing propio — simplemente sobreescribimos el fichero con la nueva versión y dejamos que `git diff` muestre los cambios.

**Caso especial — normas nuevas:** si la disposición crea una nueva ley (no modifica una existente), se genera un fichero nuevo y el commit es de tipo "añadir norma".

**Caso especial — derogaciones completas:** si una ley queda completamente derogada, se actualiza su frontmatter (`estado: "derogada"`) y opcionalmente se añade una nota al final del fichero indicando la disposición derogatoria. El fichero NO se elimina del repo (el historial debe preservarse).

#### 3.2.4 Committer — Generación de commits

**Responsabilidad:** crear commits Git con metadatos estructurados que permitan trazabilidad total.

**Formato del mensaje de commit:**

```
[tipo] Título breve de la modificación

Norma modificada: <identificador BOE de la ley afectada>
Disposición: <identificador BOE de la disposición modificadora>
Fecha BOE: <YYYY-MM-DD>
Título disposición: <título completo de la disposición del BOE>
Rango: <rango de la disposición (Ley, LO, RDL, etc.)>
URL: https://www.boe.es/diario_boe/txt.php?id=<id>

Artículos afectados: <lista de artículos modificados>
```

**Tipos de commit:**

| Prefijo | Significado | Ejemplo |
|---|---|---|
| `[nueva]` | Se añade una nueva norma al repositorio | `[nueva] Ley 7/2024, de 20 de diciembre, del Libro` |
| `[reforma]` | Se modifica el texto de una norma existente | `[reforma] Modificación del art. 324 LECrim` |
| `[derogacion]` | Se deroga total o parcialmente una norma | `[derogacion] Derogación de la Ley 22/2003 Concursal` |
| `[correccion]` | Corrección de errores publicada en el BOE | `[correccion] Corrección de errores de la LO 1/2025` |
| `[bootstrap]` | Carga inicial histórica | `[bootstrap] Constitución Española — versión original 1978` |
| `[fix-pipeline]` | Corrección por error del pipeline (no del BOE) | `[fix-pipeline] Regenerar Código Penal por bug en transformer` |

**Metadatos del commit (git trailers):**

Además del cuerpo del mensaje, se utilizan git trailers para facilitar el filtrado programático:

```
BOE-Id: BOE-A-2024-12345
BOE-Fecha: 2024-06-15
Norma-Afectada: BOE-A-1978-31229
Rango: Ley Orgánica
```

**Autoría del commit:**

- `author`: el nombre y fecha de la disposición del BOE (ej: `Jefatura del Estado <boe@boe.es>` con fecha = fecha de publicación en BOE).
- `committer`: el pipeline automatizado (ej: `leyes-bot <bot@leyes-es.github.io>` con fecha = fecha de ejecución del pipeline).

Esto permite que `git log --format="%ai %s"` muestre el historial legislativo en orden cronológico real, no en orden de procesamiento.

#### 3.2.5 State Store — Estado del pipeline

**Responsabilidad:** recordar qué disposiciones ya se han procesado para evitar duplicados y permitir re-ejecuciones idempotentes.

**Implementación:** un fichero JSON en el propio repositorio (o en un directorio `.pipeline/`) que registra:

```json
{
  "ultimo_sumario_procesado": "2026-03-27",
  "normas_procesadas": {
    "BOE-A-1978-31229": {
      "ultima_version_aplicada": "2024-03-22",
      "total_versiones_aplicadas": 3
    }
  },
  "ejecuciones": [
    {
      "fecha": "2026-03-27T08:00:00Z",
      "sumarios_revisados": ["20260327"],
      "commits_generados": 2,
      "errores": []
    }
  ]
}
```

**Garantía de idempotencia:** el state.json se actualiza DESPUÉS de un `git push` exitoso. Si el push falla, el estado no se marca como procesado y la siguiente ejecución reintentará. Para evitar commits duplicados en caso de fallo parcial (commit creado pero push fallido), el pipeline comprueba antes de crear un commit si ya existe uno con el mismo `BOE-Id` en el trailer (vía `git log --grep`). Este doble check garantiza idempotencia incluso ante fallos de red.

**Alternativa considerada:** usar tags de Git para marcar el último sumario procesado. Descartada porque un fichero JSON permite almacenar más contexto y es más fácil de consultar programáticamente.

### 3.3 Evaluación de stack tecnológico

El usuario mencionó Go como posibilidad, sin preferencia fuerte. Evaluamos tres opciones:

| Criterio | Python | Go | Node.js/TypeScript |
|---|---|---|---|
| Parsing XML | Excelente (`lxml`, `ElementTree`) | Bueno (`encoding/xml`) | Bueno (`xml2js`, `cheerio`) |
| Manipulación Git | Excelente (`GitPython`, `subprocess`) | Bueno (`go-git`) | Bueno (`simple-git`) |
| Procesamiento de texto | Excelente (regex, `re`, rich string handling) | Aceptable (más verboso) | Bueno |
| Templating Markdown | Excelente (`jinja2`, f-strings) | Aceptable (`text/template`) | Bueno (template literals) |
| Ecosistema para ETL/scraping | Excelente | Limitado | Bueno |
| Rendimiento puro | Medio | Excelente | Medio |
| Binario único desplegable | No (requiere runtime) | Sí | No (requiere runtime) |
| Familiaridad comunidad open data ES | Alta | Baja | Media |

**Recomendación: Python** como lenguaje principal del pipeline. Las razones: el cuello de botella es I/O (llamadas a la API del BOE, escritura en disco) no CPU; el ecosistema de parsing XML y manipulación de texto en Python es superior; la comunidad de datos abiertos en España trabaja predominantemente con Python; y el despliegue en GitHub Actions es trivial.

**Alternativa viable: Go** si se valora un binario único sin dependencias y se planea distribuir la herramienta como CLI reutilizable. El rendimiento extra no aporta valor significativo para este caso de uso.

### 3.4 Opciones de ejecución en producción

| Opción | Pros | Contras | Coste |
|---|---|---|---|
| **GitHub Actions (cron)** | Cero infraestructura, el repo es la fuente de verdad, logs integrados, push directo | Límite de 2000 min/mes en plan gratuito; ejecución máx. 6h; no se puede ejecutar más de 1x/día fácilmente con cron | Gratis (plan público) |
| **VPS (Hetzner, OVH)** | Control total, puede ejecutarse múltiples veces/día, permite cola de tareas | Requiere mantenimiento, monitorización, costes fijos | ~5€/mes |
| **AWS Lambda / Cloud Functions** | Escalable, pago por uso, se puede triggear con EventBridge/Cloud Scheduler | Más complejidad de setup, cold starts, límite de ejecución 15min | ~0-2€/mes |
| **Híbrido: GitHub Actions + webhook** | Actions para el cron diario, webhook manual para re-procesos | Algo más de complejidad en el workflow | Gratis |

**Recomendación para el piloto: GitHub Actions con cron diario.** Es la opción más simple, no tiene coste para repos públicos, y el pipeline del piloto (Constitución + leyes recientes) debería ejecutarse en minutos, muy lejos del límite de 6 horas.

**Para producción a escala:** evaluar el híbrido o migrar a un VPS si el volumen de normas hace que la ejecución diaria supere los 30 minutos.

---

## 4. Modelo de datos y convenciones

### 4.1 Estructura del repositorio

```
legalize/                          # raíz del repo
├── README.md                          # descripción del proyecto
├── LICENSE                            # licencia (ver sección 4.7)
├── CONTRIBUTING.md                    # guía para contribuciones
│
├── constitucion/
│   └── constitucion-espanola.md       # CE 1978
│
├── leyes-organicas/
│   ├── LO-1-2025-reforma-lecrim.md
│   ├── LO-2-2024-paridad.md
│   └── ...
│
├── leyes/
│   ├── L-7-2024-libro.md
│   ├── L-13-2024-startups.md
│   └── ...
│
├── reales-decretos-ley/
│   ├── RDL-1-2025-medidas-urgentes.md
│   └── ...
│
├── reales-decretos-legislativos/
│   ├── RDLeg-2-2015-estatuto-trabajadores.md
│   └── ...
│
├── .pipeline/
│   ├── state.json                     # estado del pipeline
│   ├── config.yaml                    # configuración
│   └── mappings/
│       └── id-to-filename.json        # mapeo BOE-ID → ruta fichero
│
├── scripts/                           # código del pipeline
│   ├── fetcher.py
│   ├── transformer.py
│   ├── committer.py
│   ├── bootstrap.py
│   ├── daily.py                       # orquestador del flujo diario
│   └── utils/
│       ├── boe_client.py              # cliente HTTP para la API BOE
│       ├── xml_parser.py              # parsing del XML consolidado
│       ├── markdown_writer.py         # generación de Markdown
│       └── git_ops.py                 # operaciones Git
│
├── tests/
│   ├── test_transformer.py
│   ├── test_committer.py
│   ├── fixtures/                      # XMLs de ejemplo del BOE
│   │   ├── constitucion-sample.xml
│   │   └── reforma-sample.xml
│   └── snapshots/                     # Markdowns esperados
│       └── constitucion-expected.md
│
└── .github/
    └── workflows/
        ├── daily-update.yml           # cron diario
        ├── bootstrap.yml              # carga inicial (manual)
        └── validate.yml               # CI: linting y tests
```

### 4.2 Convención de nombrado de ficheros

**Formato general:**

```
{RANGO}-{NUMERO}-{AÑO}-{slug-descriptivo}.md
```

**Ejemplos:**

| Norma | Nombre de fichero |
|---|---|
| Constitución Española de 1978 | `constitucion-espanola.md` |
| Ley Orgánica 10/1995, de 23 de noviembre, del Código Penal | `LO-10-1995-codigo-penal.md` |
| Ley 39/2015, de 1 de octubre, del Procedimiento Administrativo Común | `L-39-2015-procedimiento-administrativo-comun.md` |
| Real Decreto-ley 8/2024, de 28 de diciembre | `RDL-8-2024-medidas-dana.md` |
| Real Decreto Legislativo 2/2015, Estatuto de los Trabajadores | `RDLeg-2-2015-estatuto-trabajadores.md` |

**Abreviaturas de rango:**

| Rango normativo | Abreviatura |
|---|---|
| Constitución | `constitucion` (sin abreviatura, caso único) |
| Ley Orgánica | `LO` |
| Ley | `L` |
| Real Decreto-ley | `RDL` |
| Real Decreto Legislativo | `RDLeg` |

**Reglas del slug:**

- Todo en minúsculas excepto la abreviatura de rango.
- Sin tildes ni caracteres especiales (normalización Unicode NFKD → ASCII).
- Palabras separadas por guiones.
- Máximo 60 caracteres para el slug (truncar si es necesario, sin cortar palabras).
- El slug se genera a partir del título corto de la norma, no del título completo.

### 4.3 Formato Markdown de una ley

A continuación, el ejemplo completo de cómo se vería un artículo de la Constitución:

```markdown
---
titulo: "Constitución Española"
titulo_corto: "Constitución Española"
identificador_boe: "BOE-A-1978-31229"
rango: "constitucion"
fecha_publicacion: "1978-12-29"
fecha_ultima_modificacion: "2024-03-22"
estado: "vigente"
departamento: "Jefatura del Estado"
url_boe: "https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229"
materias:
  - "Constitución"
  - "Organización del Estado"
  - "Derechos fundamentales y libertades públicas"
---

# Constitución Española

## Preámbulo

La Nación española, deseando establecer la justicia, la libertad y la seguridad
y promover el bien de cuantos la integran, en uso de su soberanía, proclama su
voluntad de:

Garantizar la convivencia democrática dentro de la Constitución y de las leyes
conforme a un orden económico y social justo.

[...]

## Título Preliminar

##### Artículo 1.

1. España se constituye en un Estado social y democrático de Derecho, que
propugna como valores superiores de su ordenamiento jurídico la libertad, la
justicia, la igualdad y el pluralismo político.

2. La soberanía nacional reside en el pueblo español, del que emanan los poderes
del Estado.

3. La forma política del Estado español es la Monarquía parlamentaria.

##### Artículo 2.

La Constitución se fundamenta en la indisoluble unidad de la Nación española,
patria común e indivisible de todos los españoles, y reconoce y garantiza el
derecho a la autonomía de las nacionalidades y regiones que la integran y la
solidaridad entre todas ellas.

[...]

## Título I. De los derechos y deberes fundamentales

##### Artículo 10.

1. La dignidad de la persona, los derechos inviolables que le son inherentes, el
libre desarrollo de la personalidad, el respeto a la ley y a los derechos de los
demás son fundamento del orden político y de la paz social.

2. Las normas relativas a los derechos fundamentales y a las libertades que la
Constitución reconoce se interpretarán de conformidad con la Declaración
Universal de Derechos Humanos y los tratados y acuerdos internacionales sobre las
mismas materias ratificados por España.

### Capítulo Primero. De los españoles y los extranjeros

##### Artículo 11.

1. La nacionalidad española se adquiere, se conserva y se pierde de acuerdo con
lo establecido por la ley.

2. Ningún español de origen podrá ser privado de su nacionalidad.

3. El Estado podrá concertar tratados de doble nacionalidad con los países
iberoamericanos o con aquellos que hayan tenido o tengan una particular
vinculación con España. En estos mismos países, aun cuando no reconozcan a sus
ciudadanos un derecho recíproco, podrán naturalizarse los españoles sin perder su
nacionalidad de origen.

[...]

## Disposiciones adicionales

##### Primera.

La Constitución ampara y respeta los derechos históricos de los territorios
forales.

La actualización general de dicho régimen foral se llevará a cabo, en su caso, en
el marco de la Constitución y de los Estatutos de Autonomía.

[...]

## Disposiciones transitorias

##### Primera.

En los territorios dotados de un régimen provisional de autonomía, sus órganos
colegiados superiores, mediante acuerdo adoptado por la mayoría absoluta de sus
miembros, podrán sustituir la iniciativa que el apartado 2 del artículo 143
atribuye a las Diputaciones Provinciales o a los órganos interinsulares
correspondientes.

[...]

## Disposición derogatoria

1. Queda derogada la Ley 1/1977, de 4 de enero, para la Reforma Política, así
como, en tanto en cuanto no estuvieran ya derogadas por la anteriormente
mencionada Ley, la de Principios del Movimiento Nacional, de 17 de mayo de 1958;
el Fuero de los Españoles, de 17 de julio de 1945; el del Trabajo, de 9 de marzo
de 1938; la Ley Constitutiva de las Cortes, de 17 de julio de 1942; la Ley de
Sucesión en la Jefatura del Estado, de 26 de julio de 1947, todas ellas
modificadas por la Ley Orgánica del Estado, de 10 de enero de 1967, y en los
mismos términos esta última y la de Referéndum Nacional de 22 de octubre de 1945.

2. En tanto en cuanto pudiera conservar alguna vigencia, se considera
definitivamente derogada la Ley de 25 de octubre de 1839 en lo que pudiera
afectar a las provincias de Álava, Guipúzcoa y Vizcaya.

En los mismos términos se considera definitivamente derogada la Ley de 21 de
julio de 1876.

3. Asimismo quedan derogadas cuantas disposiciones se opongan a lo establecido en
esta Constitución.

## Disposición final

Esta Constitución entrará en vigor el mismo día de la publicación de su texto
oficial en el boletín oficial del Estado. Se publicará también en las demás
lenguas de España.
```

### 4.4 Reglas de formato del texto

1. **Ancho de línea:** no se fuerza un ancho máximo. Cada párrafo legal es una línea larga (soft wrap). Razón: facilita el `git diff` — un cambio en un párrafo afecta solo a esa línea, no a múltiples líneas rewrapeadas.
2. **Apartados numerados:** los apartados numerados dentro de un artículo (ej: "1.", "2.") se mantienen como párrafos separados, con su número al inicio. No se convierten en listas Markdown numeradas para preservar la fidelidad al formato oficial.
3. **Letras en subapartados:** los subapartados con letra (ej: "a)", "b)") se mantienen como texto, no como listas Markdown.
4. **Tablas:** si el texto legal contiene tablas (común en leyes tributarias), se representan como tablas Markdown.
5. **Notas de vigencia:** si un artículo está derogado o tiene vigencia parcial, se incluye una nota al final del artículo entre corchetes: `[Nota: artículo derogado por LO 1/2025, de 2 de enero]`.
6. **Texto consolidado, no original:** el fichero siempre refleja la versión vigente consolidada. El historial de versiones anteriores se preserva en el histórico de Git.

### 4.5 Mapeo BOE-ID → Fichero

El fichero `.pipeline/mappings/id-to-filename.json` mantiene la correspondencia entre identificadores BOE y rutas de fichero:

```json
{
  "BOE-A-1978-31229": "constitucion/constitucion-espanola.md",
  "BOE-A-1995-25444": "leyes-organicas/LO-10-1995-codigo-penal.md",
  "BOE-A-2015-10565": "leyes/L-39-2015-procedimiento-administrativo-comun.md"
}
```

Este mapeo se genera automáticamente durante el bootstrap y se actualiza cuando se añaden nuevas normas. Es la pieza clave que conecta las disposiciones del sumario diario con los ficheros del repo.

### 4.6 Configuración del pipeline

Fichero `.pipeline/config.yaml`:

```yaml
# Configuración del pipeline legalize
proyecto:
  nombre: "legalize"
  descripcion: "Legislación española versionada en Git"
  url_repo: "https://github.com/legalize/legalize"

boe:
  base_url: "https://www.boe.es/datosabiertos"
  request_timeout_seconds: 30
  max_retries: 3
  retry_backoff_base_seconds: 2
  requests_per_second: 2  # rate limiting voluntario
  user_agent: "legalize-bot/1.0 (+https://github.com/legalize)"

alcance:
  rangos_incluidos:
    - "constitucion"
    - "ley_organica"
    - "ley"
    - "real_decreto_ley"
    - "real_decreto_legislativo"
  fecha_desde: "2024-01-01"  # para el piloto
  fecha_hasta: null           # null = hasta hoy
  # Para el piloto, se incluyen también normas anteriores a fecha_desde
  # si son normas fundamentales (Constitución, Código Penal, etc.)
  normas_fijas:
    - "BOE-A-1978-31229"  # Constitución Española

git:
  author_name: "BOE"
  author_email: "boe@boe.es"
  committer_name: "leyes-bot"
  committer_email: "bot@legalize.github.io"
  branch: "main"
  sign_commits: false  # por ahora; considerar GPG en producción

markdown:
  frontmatter: true
  encoding: "utf-8"
  line_ending: "lf"
```

### 4.7 Licencia y aspectos legales

El contenido del BOE es **reutilizable** bajo las condiciones del [Real Decreto 1495/2011](https://www.boe.es/buscar/act.php?id=BOE-A-2011-17560) que regula la reutilización de la información del sector público. Las condiciones principales son:

- Prohibido alterar el contenido de la información.
- Obligatorio citar la fuente (Agencia Estatal BOE).
- Obligatorio mencionar la fecha de la última actualización.

**Licencia recomendada para el repositorio:** doble licencia:

- **Contenido legislativo (los .md):** se redistribuye bajo las condiciones de reutilización del BOE, citando la fuente. No podemos aplicar una licencia tipo Creative Commons sobre contenido que no es nuestro, pero sí podemos indicar las condiciones de reutilización.
- **Código del pipeline (scripts/):** MIT o Apache 2.0.

El README debe incluir un aviso claro de que el repositorio **no es una fuente oficial** y que el texto de referencia es siempre el publicado en el BOE.

---

## 5. Flujos de operación detallados

### 5.1 Bootstrap — Carga inicial histórica

El bootstrap es el proceso más complejo y costoso. Su objetivo es reconstruir el historial completo de commits a partir de las versiones históricas disponibles en el XML del BOE.

**Algoritmo:**

```
PARA CADA norma en el alcance del piloto:
  1. Descargar XML consolidado completo (con todas las versiones)
  2. Extraer lista de versiones ordenada cronológicamente
     - Cada versión tiene: fecha_publicacion, id_norma_modificadora, bloques_afectados
  3. PARA CADA versión (de la más antigua a la más reciente):
     a. Generar el Markdown de la norma tal como quedaba tras esa versión
     b. Escribir el fichero .md al sistema de ficheros
     c. Crear commit con:
        - author date = fecha_publicacion de la versión
        - mensaje con metadatos de la disposición modificadora
     d. Actualizar state.json
```

**Reto principal: reconstruir versiones intermedias.** El XML del BOE almacena todas las versiones de cada bloque, pero necesitamos "componer" el texto completo de la norma en cada punto temporal. Esto requiere:

1. Partir de la versión original (todos los bloques en su versión 0).
2. Ir aplicando las versiones posteriores de cada bloque en orden cronológico.
3. Si una reforma toca los artículos 1, 5 y 12, reemplazar esos tres bloques y dejar el resto igual.

**Caso especial: reformas simultáneas.** Si dos disposiciones publicadas el mismo día modifican la misma norma (raro pero posible), se procesan como dos commits separados con el mismo `author date`, ordenados por número de disposición.

**Estimación para el piloto:**

- Constitución Española: ~3 versiones (original 1978, reforma 1992 art. 13.2, reforma 2011 art. 135, reforma 2024 art. 49). Son ~4 commits.
- Leyes publicadas 2024-2026: cada una tendrá 1 commit (versión original) más los que correspondan a reformas posteriores. Estimación: ~100-200 normas, ~150-300 commits.
- Tiempo estimado: <1 hora (dominado por las llamadas a la API).

### 5.2 Flujo diario — Procesamiento del BOE del día

```
1. Obtener fecha actual (o la siguiente fecha no procesada)
2. Consultar sumario del BOE para esa fecha
3. PARA CADA disposición en el sumario:
   a. ¿Es un rango normativo incluido en el alcance? → Si no, saltar
   b. ¿Es una norma nueva?
      → Sí: descargar texto, generar MD, crear fichero, commit [nueva]
   c. ¿Modifica una norma existente en el repo?
      → Sí: descargar texto consolidado actualizado de la norma afectada,
             regenerar MD, comparar con fichero actual, commit [reforma]
   d. ¿Es una corrección de errores?
      → Sí: similar a reforma, pero commit [correccion]
4. Push al repositorio remoto
5. Actualizar state.json con la fecha procesada
```

**Idempotencia:** si el pipeline se ejecuta dos veces para la misma fecha, la segunda ejecución no debe generar commits duplicados. El state.json registra las disposiciones ya procesadas. Además, si el Markdown generado es idéntico al existente (no hay cambios reales), no se crea commit.

**Gestión de errores:**

| Error | Acción |
|---|---|
| API BOE no disponible (5xx) | Reintentar con backoff. Si persiste, registrar en state.json y saltar. Siguiente ejecución reintentará. |
| XML malformado | Registrar error, no generar commit para esa norma, continuar con las demás. |
| Norma referenciada no encontrada en el repo | Puede ser una norma fuera del alcance actual. Registrar como `pendiente_de_inclusion`. |
| Commit falla (conflicto Git) | No debería pasar (pipeline es el único writer), pero si ocurre: abortar y alertar. |

### 5.3 Flujo de re-procesamiento

Puede ser necesario reprocesar normas por bugs en el transformer, mejoras en el formato Markdown, o datos corregidos en el BOE.

**Estrategia:** un script de re-bootstrap parcial que:

1. Acepta una lista de identificadores BOE.
2. Regenera los ficheros Markdown desde cero usando el XML actual.
3. Crea un commit especial: `[fix-pipeline] Regenerar {norma} por {razón}`.

No se reescribe el historial de Git (no `rebase` ni `force push`). Los commits correctivos se añaden al final.

---

## 6. Calidad y validación

### 6.1 Tests del pipeline

| Tipo | Qué valida | Herramienta |
|---|---|---|
| **Unit tests** | Transformer: dado un XML de ejemplo, produce el MD esperado | pytest + fixtures XML |
| **Unit tests** | Committer: dado un cambio, genera el mensaje de commit correcto | pytest |
| **Snapshot tests** | El MD generado para la Constitución coincide con el snapshot esperado | pytest + `snapshot_test` |
| **Integration tests** | Flujo completo: fetch → transform → commit sobre un repo Git temporal | pytest + `tmp_path` |
| **Validación de Markdown** | Los ficheros generados son Markdown válido y parseable | `markdownlint` en CI |
| **Validación de frontmatter** | El YAML frontmatter tiene todos los campos requeridos y tipos correctos | Schema JSON + script de validación |
| **Diff fidelity** | El texto generado coincide carácter a carácter con el texto visible en boe.es | Test manual periódico + script de comparación |

### 6.2 CI/CD con GitHub Actions

```yaml
# .github/workflows/validate.yml
name: Validación
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v

  lint-markdown:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: DavidAnson/markdownlint-cli2-action@v16
        with:
          globs: "**/*.md"

  validate-frontmatter:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python scripts/validate_frontmatter.py
```

```yaml
# .github/workflows/daily-update.yml
name: Actualización diaria
on:
  schedule:
    - cron: "0 10 * * 1-6"  # L-S a las 10:00 UTC (12:00 hora española)
  workflow_dispatch:          # permite ejecución manual

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0      # historial completo para commits con dates correctas
          token: ${{ secrets.BOT_TOKEN }}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: python scripts/daily.py
      - name: Push changes
        run: |
          git push origin main
```

**Nota sobre el schedule:** el BOE se publica de lunes a sábado (no domingos ni festivos nacionales). El cron se ejecuta L-S a las 10:00 UTC para dar margen a que el sumario del día esté disponible en la API (normalmente se publica a primera hora de la mañana).

### 6.3 Monitorización

Para el piloto, monitorización mínima:

- **GitHub Actions:** notificaciones de fallo a email/Slack.
- **Métricas en state.json:** número de commits por ejecución, errores acumulados.
- **Badge en README:** último estado del workflow de actualización diaria.

Para producción, considerar:

- Dashboard con número de normas, último commit, cobertura por rango normativo.
- Alertas si pasan 3+ días laborables sin commits (indica fallo silencioso).
- Log de normas procesadas vs. normas esperadas (basado en el sumario).

---

## 7. Decisiones de diseño pendientes

Aspectos que necesitan decisión antes o durante la implementación del piloto:

### 7.1 Nombre del proyecto y organización GitHub

Opciones para el nombre del repo:

- `legalize` — descriptivo, claro.
- `boe-git` — enfatiza la conexión BOE + Git.
- `lex-es` — corto, pero ya existe una org con ese nombre.
- `legislacion-es` — formal, completo.

Recomendación: crear una **organización de GitHub** (no un repo personal) para dar aspecto institucional y permitir múltiples repos en el futuro (ej: uno para leyes estatales, otro para autonómicas).

### 7.2 Un repo vs. múltiples repos

| Opción | Pros | Contras |
|---|---|---|
| **Un solo repo** | Un solo `git clone`, búsqueda unificada, `git log` global | Puede crecer mucho (miles de ficheros) |
| **Repo por rango normativo** | Repos más manejables, clonado parcial | Pierde la vista unificada, complica el pipeline |
| **Monorepo con directorios** | Equilibrio: un repo, organización por carpetas | El favorito — ver estructura en sección 4.1 |

Recomendación: **monorepo con directorios** (la opción de la sección 4.1). Git maneja bien miles de ficheros y el corpus legislativo español vigente no debería superar los 10.000 ficheros.

### 7.3 Tratamiento de normas que aún no están consolidadas

El BOE puede tardar días o semanas en actualizar la versión consolidada de una norma tras una reforma. Opciones:

- **Esperar:** solo procesar cuando el texto consolidado está disponible. Más fiable pero con retraso.
- **Aplicar cambios manualmente:** leer la disposición modificadora y aplicar los cambios al Markdown. Más rápido pero propenso a errores.

Recomendación para el piloto: **esperar a la versión consolidada**. La prioridad es fiabilidad.

### 7.4 Lenguas cooficiales

El BOE publica determinadas normas también en catalán, euskera, gallego y valenciano. ¿Se incluyen?

Recomendación para el piloto: **solo castellano**. Evaluar en fases posteriores si hay demanda.

### 7.5 Metadatos enriquecidos

Posibles extensiones del frontmatter para fases posteriores:

- `materias_eurovoc`: clasificación temática estandarizada.
- `afectada_por`: lista de disposiciones que han modificado esta norma.
- `afecta_a`: lista de normas que esta disposición modifica.
- `transpone`: directiva europea que transpone (si aplica).
- `comunidades_autonomas`: ámbito territorial si no es estatal.

---

## 8. Roadmap por fases

### Fase 0 — Preparación (1-2 semanas)

**Objetivo:** tener la infraestructura base lista.

| Tarea | Detalle | Criterio de aceptación |
|---|---|---|
| Crear organización y repo en GitHub | Con README, LICENSE, estructura de carpetas | Repo público con estructura vacía |
| Configurar entorno de desarrollo | Python 3.12+, dependencias, pre-commit hooks | `pip install -r requirements.txt` funciona |
| Implementar `boe_client.py` | Cliente HTTP para la API del BOE con reintentos | Tests pasan contra la API real |
| Implementar `xml_parser.py` | Parsear XML consolidado, extraer bloques y versiones | Puede parsear la Constitución correctamente |
| Configurar CI básico | GitHub Actions: tests + linting | Workflow verde en cada push |

### Fase 1 — Piloto: Constitución (2-3 semanas)

**Objetivo:** demostrar el concepto end-to-end con la Constitución Española.

| Tarea | Detalle | Criterio de aceptación |
|---|---|---|
| Implementar `markdown_writer.py` | Conversión bloque XML → Markdown | Output fiel al texto de boe.es |
| Implementar `committer.py` | Creación de commits con metadatos | Commit messages correctos |
| Implementar `bootstrap.py` | Carga histórica completa | Constitución con 4 commits (1978, 1992, 2011, 2024) |
| Validación manual | Comparar Markdown generado vs. texto en boe.es | 100% fidelidad textual |
| Publicar piloto | Push a GitHub, README descriptivo | Repo público con la Constitución versionada |

**Entregable:** repositorio público con la Constitución Española en Markdown, 4 commits representando las 3 reformas históricas, verificable contra boe.es.

### Fase 2 — Ampliación piloto: leyes 2024-2026 (3-4 semanas)

**Objetivo:** escalar el pipeline a decenas/cientos de normas.

| Tarea | Detalle | Criterio de aceptación |
|---|---|---|
| Implementar catálogo | Listar normas del alcance usando la API | Lista correcta de normas 2024-2026 |
| Bootstrap masivo | Cargar todas las normas del piloto | Todos los ficheros .md generados |
| Implementar `daily.py` | Flujo diario automatizado | Detecta y procesa nuevas disposiciones |
| Configurar GitHub Actions cron | Ejecución diaria L-S | Al menos 1 semana de ejecución correcta |
| Gestión de errores | Reintentos, logging, idempotencia | Pipeline sobrevive a errores transitorios |
| Documentación | CONTRIBUTING.md, wiki del proyecto | Alguien externo puede entender el sistema |

**Entregable:** repositorio con la Constitución + todas las leyes (LO, L, RDL, RDLeg) publicadas entre 2024 y 2026, actualizándose automáticamente cada día.

### Fase 3 — Producción: corpus completo (6-8 semanas)

**Objetivo:** cubrir toda la legislación vigente.

| Tarea | Detalle |
|---|---|
| Ampliar alcance temporal | Todas las normas vigentes, sin límite de fecha |
| Cargar normas fundamentales históricas | Código Civil, Código Penal, LECrim, LEC, Estatuto de los Trabajadores, etc. |
| Optimizar rendimiento | Paralelización de descargas, caché agresivo |
| Monitorización | Dashboard, alertas, métricas |
| GitHub Pages / web | Interfaz web simple para navegar las leyes |
| Revisión de la comunidad | Buscar feedback de juristas y desarrolladores |

### Fase 4 — Mejoras y extensiones (ongoing)

Ideas para el futuro, priorizables según demanda:

- **Búsqueda full-text:** GitHub Code Search funciona sobre el repo, pero podría añadirse Algolia o similar.
- **API propia:** endpoint JSON para consultar el estado de cualquier norma.
- **Legislación autonómica:** extender a DOCV, DOGC, BOJA, etc.
- **Comparador visual:** interfaz web tipo "Split diff" para comparar versiones de un artículo.
- **RSS/Atom feed:** notificaciones de cambios legislativos por materia.
- **Integración con Wikidata:** enlazar entidades (normas, materias) con sus equivalentes en Wikidata.
- **LLM summaries:** resumen automático de cada reforma en lenguaje llano (como commit message extendido).

---

## 9. Riesgos y mitigaciones

| Riesgo | Impacto | Probabilidad | Mitigación |
|---|---|---|---|
| **La API del BOE cambia o se cae** | Alto — el pipeline deja de funcionar | Media | Cachear XML localmente; monitorizar; tener plan B (scraping HTML como fallback) |
| **XML del BOE tiene inconsistencias** | Medio — ficheros MD incorrectos | Alta (ya documentado en foros) | Tests robustos; validación post-generación; log de anomalías |
| **Reformas muy complejas** (ej: ley que reordena artículos, añade y elimina a la vez) | Medio — el diff puede ser confuso | Media | Commit message detallado; considerar split en múltiples commits si es más claro |
| **Volumen excesivo para GitHub Actions** | Bajo — el pipeline supera el tiempo límite | Baja (piloto) / Media (producción) | Migrar a VPS o paralelizar en múltiples workflows |
| **Cambios retroactivos en el BOE** (correcciones de errores que alteran texto ya procesado) | Medio — el historial del repo no refleja la realidad temporal | Baja | Commit tipo [correccion] que actualiza el fichero; nota en el commit indicando que es retroactivo |
| **Falta de interés / adopción** | Bajo — esfuerzo desperdiciado | Media | Validar con la comunidad jurídica y de datos abiertos antes de la Fase 3 |
| **Problemas legales con la reutilización** | Alto — takedown del repo | Muy baja (la reutilización está regulada y permitida) | Cumplir escrupulosamente con la normativa de reutilización; citar fuente siempre |

---

## 10. Métricas de éxito

### Piloto (Fases 1-2)

- El pipeline genera correctamente la Constitución con sus 4 versiones históricas.
- El `git diff` entre versiones es legible y corresponde a la reforma real.
- El pipeline diario se ejecuta correctamente durante 30 días consecutivos sin intervención manual.
- Al menos 95% de las normas del piloto (2024-2026) se procesan sin errores.

### Producción (Fase 3+)

- Cobertura: >99% de las normas consolidadas vigentes del alcance están en el repo.
- Latencia: una reforma publicada en el BOE se refleja en el repo en <24 horas.
- Fiabilidad: <1% de errores en el procesamiento diario.
- Adopción: >100 stars en GitHub en los primeros 6 meses (indicador de interés).

---

## Apéndice A: Ejemplo completo de flujo para una reforma

**Escenario:** el BOE del 15 de junio de 2025 publica la "Ley Orgánica 3/2025, de 13 de junio, por la que se modifica la Ley Orgánica 10/1995, de 23 de noviembre, del Código Penal, en materia de delitos informáticos".

**Paso 1 — Fetcher:**

```
GET https://www.boe.es/datosabiertos/api/boe/sumario/20250615
→ Encuentra disposición BOE-A-2025-XXXXX (LO 3/2025)
→ Identifica que modifica BOE-A-1995-25444 (Código Penal)
→ Descarga texto consolidado actualizado del Código Penal
```

**Paso 2 — Transformer:**

```
Parsea XML del Código Penal con las versiones actualizadas
Genera nuevo Markdown completo
Escribe a leyes-organicas/LO-10-1995-codigo-penal.md
```

**Paso 3 — Diffing:**

```
git diff muestra cambios en los artículos 197 bis, 264, 264 bis
(los artículos modificados por la LO 3/2025)
```

**Paso 4 — Committer:**

```
git add leyes-organicas/LO-10-1995-codigo-penal.md
git commit con:
  author: "Jefatura del Estado <boe@boe.es>"
  author date: 2025-06-15
  message:
    [reforma] Modificación del Código Penal en materia de delitos informáticos

    Norma modificada: BOE-A-1995-25444
    Disposición: BOE-A-2025-XXXXX
    Fecha BOE: 2025-06-15
    Título disposición: Ley Orgánica 3/2025, de 13 de junio, por la que se
    modifica la Ley Orgánica 10/1995, de 23 de noviembre, del Código Penal,
    en materia de delitos informáticos
    Rango: Ley Orgánica
    URL: https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-XXXXX

    Artículos afectados: 197 bis, 264, 264 bis

    BOE-Id: BOE-A-2025-XXXXX
    BOE-Fecha: 2025-06-15
    Norma-Afectada: BOE-A-1995-25444
    Rango: Ley Orgánica
```

**Paso 5 — Push:**

```
git push origin main
```

**Resultado visible en GitHub:** al visitar el fichero del Código Penal, el usuario ve el historial de commits con cada reforma. Al hacer clic en un commit, ve exactamente qué artículos cambiaron y cómo.

---

## Apéndice B: Dependencias Python estimadas

```
# requirements.txt
lxml>=5.0              # parsing XML
requests>=2.31         # HTTP client (o httpx para async)
gitpython>=3.1         # operaciones Git
pyyaml>=6.0            # configuración y frontmatter
click>=8.1             # CLI
rich>=13.0             # logging bonito en terminal
pytest>=8.0            # tests
markdownlint-cli2      # (npm, no pip — se instala aparte en CI)
```

---

## Apéndice C: Glosario

| Término | Definición |
|---|---|
| **BOE** | Boletín Oficial del Estado — diario oficial de España |
| **Disposición** | Unidad de publicación en el BOE (una ley, un decreto, una corrección, etc.) |
| **Norma consolidada** | Texto de una norma con todas sus modificaciones integradas |
| **Bloque** | Unidad estructural del XML del BOE (artículo, título, capítulo, etc.) |
| **Sumario** | Índice diario del BOE con todas las disposiciones publicadas ese día |
| **Rango normativo** | Tipo de norma según su jerarquía (LO > L > RDL > RDLeg > RD > OM) |
| **Bootstrap** | Proceso de carga inicial que reconstruye el historial de commits |
| **Pipeline** | Conjunto de scripts que automatizan el flujo fetch → transform → commit |
| **Frontmatter** | Metadatos YAML al inicio de un fichero Markdown |
| **Git trailer** | Metadatos estructurados al final de un mensaje de commit (clave: valor) |
