# 02 — El índice existía, estaba declarado, y lo dice nuestro propio documento de abril

**Sonda 1 (descubrimiento), checklist de `step-0-research.md` §0.1.1.**
Medido el 2026-09-03. **Cero peticiones a SUIN** — está caído (`01-fuente-caida.md`); todo
lo de abajo sale del Internet Archive, de `datos.gov.co` y del repo publicado.

## La pregunta

`discovery.py:17` afirma:

> *"SUIN has no catalog API. We enumerate integer IDs in the range id_start..id_end."*

y sobre esa frase se construyó un barrido de **950.001 peticiones** para un corpus de 71.900.

`research/RESEARCH-CO.md:13`, escrito en abril por la misma persona que escribió el fetcher,
afirma lo contrario:

> *"Sitemaps are exposed for leyes, decretos, resoluciones, actos legislativos, and other
> document classes."*

Sin URL y sin código de estado, así que la afirmación no era comprobable. Lo es ahora.

## Resultado: hay DOS índices, y los dos son gratis

### Índice A — 24 sitemaps declarados en el propio `robots.txt`

`robots.txt` de SUIN, capturado por el Internet Archive el **2025-08-15** (la última captura
con `200`; copia íntegra en `suin-robots-2025-08-15.txt`):

```
User-agent:*
Disallow: /estad468/
Allow: /viewDocument.asp?ruta=*/*
Allow: /viewDocument.asp?id=*
Sitemap: https://www.suin-juriscol.gov.co/sitemap.xml
Sitemap: https://www.suin-juriscol.gov.co/sitemapleyes.xml
Sitemap: https://www.suin-juriscol.gov.co/sitemapleyessin.xml
Sitemap: https://www.suin-juriscol.gov.co/sitemapdecreto1.xml
Sitemap: https://www.suin-juriscol.gov.co/sitemapdecreto2.xml
Sitemap: https://www.suin-juriscol.gov.co/sitemapresoluciones.xml
… 24 en total
```

**24 sitemaps: 10 clases de legislación, 3 de jurisprudencia, vídeos y el del portal —
la mayoría en dos variantes.** La variante con sufijo `sin`
lleva la misma lista en la otra forma de URL — no es "sin vigencia", es sin la ruta de clase:

| | `sitemapactoslegislativos.xml` | `sitemapactoslegislativossin.xml` |
|---|---|---|
| forma | `viewDocument.asp?ruta=Acto/1000011` | `viewDocument.asp?id=1000011` |
| entradas | 133 | 133 — **los mismos ids, en el mismo orden** |

Así que **con 10 peticiones** —una por clase de legislación— se enumera el corpus entero. El fetcher
usa la forma `?id=`: 7 de esas clases tienen variante `…sin.xml` que la sirve,
`sitemapcircular.xml` ya viene en esa forma, y de `constituciones` e `instruccion` no se ha
podido comprobar la forma (el Archive no dejó descargarlos).

Contenido medido, sobre las capturas del **2025-06-17**:

| Sitemap | ids | ¿qué es? |
|---|---:|---|
| `sitemapdecreto1sin` | 49.961 | decretos |
| `sitemapdecreto2sin` | 16.129 | decretos (2.ª parte) |
| `sitemapleyes` | 11.347 | leyes |
| `sitemapresolucionessin` | 6.139 | resoluciones |
| `sitemapcircular` | 898 | circulares |
| `sitemapactoslegislativossin` | 133 | actos legislativos |
| `sitemapacuerdosin` | 121 | acuerdos |
| **subtotal legislación medido** | **84.728** | |
| `sitemapcconstitucionalsin` | 7.193 | **jurisprudencia — Corte Constitucional** |
| `sitemapconstituciones`, `sitemapinstruccion`, `sitemapdpresidenciales(sin)`, `sitemapconsejoestado(sin)`, `sitemapcsuprema`, `sitemapvideos` | — | no medidos: el Archive limitó las descargas |

**Ninguno lleva `<lastmod>`.** Comprobado en `sitemapleyes`, `sitemapactoslegislativos` y
`sitemapactoslegislativossin`: cero etiquetas. Los sitemaps dan el censo, **no** dan
detección de cambios. Esto importa para la sonda 3 y está sin resolver.

**Y la advertencia de población del §0.1.1 aplica aquí literalmente.** `cconstitucional`,
`consejoestado` y `csuprema` son **sentencias, no legislación**: 7.193 sólo en la primera.
Tomar "todos los sitemaps" metería miles de documentos fuera de alcance en un corpus que se
anuncia como legislación. Hay que elegir clases, no descargar el índice entero.

### Índice B — el catálogo oficial en Datos Abiertos, en 1 petición

Y este estaba enlazado **en el README del propio repo que publicamos**:

> Dataset (Datos Abiertos Colombia): https://www.datos.gov.co/…/fiev-nid6

Es un dataset Socrata, en un host **que está vivo aunque SUIN no lo esté**:

```
$ curl "https://www.datos.gov.co/resource/fiev-nid6.json?\$select=count(1)"
[{"count_1":"89366"}]
```

| | |
|---|---|
| Nombre | *Lista de normas cargadas en el Sistema Único de Información Normativa SUIN-Juriscol* |
| Filas | **89.366** |
| Actualizado | **2026-07-08** |
| Creado | 2021-05-27 |
| Columnas | `tipo`, `n_mero`, `a_o`, `sector`, `subtipo`, `vigencia`, `entidad`, `materia`, `art_culos` |
| Coste del censo completo | **1 petición** (`.csv?$limit=100000`, 11 MB) |
| Coste del recuento exacto | **1 petición** (SoQL `$select=count(1)`) |

**Lo que cubre y lo que omite.** Cubre la identidad de la norma (tipo/número/año) más metadatos
que hoy tiramos. **No trae el `id` interno de SUIN**, así que por sí solo no permite descargar
nada: es el censo y el detector de huecos, no la lista de descarga. Los sitemaps son lo
contrario: traen el `id` pero no la identidad.

**Se complementan, no compiten** — que es exactamente lo que dice el §0.1.1.

## Tabla del §0.1.1

| Índice | Peticiones para enumerarlo | Qué cubre | Qué omite | ¿Documentado? |
|---|---:|---|---|---|
| Sitemaps por clase de legislación | **10** | el `id` de cada documento, por clase | `lastmod`; la identidad tipo/número/año | Sí — `robots.txt` |
| Catálogo `fiev-nid6` | **1** | 89.366 normas con identidad + `vigencia`, `sector`, `entidad`, `subtipo`, `materia`, `art_culos` | el `id` de SUIN → no descarga | Sí — datos.gov.co, y nuestro README |
| Barrido de enteros (hoy) | **950.001** | el ~85 % que cae en 1.0M–1.95M | **el 14,6 % que no** | No |

## Lo que se probó y salió negativo (para que sea refutable)

| Probado | Resultado |
|---|---|
| `https://www.suin-juriscol.gov.co/robots.txt` (en vivo, 2026-09-03) | `curl (52)`, `http=000` — fuente caída |
| `https://www.suin-juriscol.gov.co/sitemap.xml` (en vivo) | `curl (52)`, `http=000` |
| `sitemap.xml` archivado (2025-06-17) | `200` — **es un sitemap de páginas del portal**, 2,4 KB, no de normas |
| Dataset Socrata `pj9b-rf8w` ("Normas cargadas en el SUIN") | `200` en metadatos; filas → `{"error":true,"message":"no row or column access to non-tabular tables"}` — es una **visualización**, no una tabla |
| Búsqueda en el catálogo Socrata de `datos.gov.co` por `juriscol` | 2 resultados: `fiev-nid6` (el bueno) y `pj9b-rf8w` (la visualización) |
| Interfaz de búsqueda de SUIN, leyendo peticiones de red | **NO EJECUTADO** — requiere la fuente viva. Pendiente |

## Rediseño recomendado del descubrimiento

```
discover_all:
    10 GET, uno por clase de LEGISLACIÓN, en la forma ?id=
      (leyes, decreto1, decreto2, resoluciones, circular, acuerdo,
       actoslegislativos, constituciones, instruccion, dpresidenciales)
      → lista completa de ids, incluidos los bloques que hoy no se visitan
    EXCLUIR cconstitucional / consejoestado / csuprema (jurisprudencia)
    aserto: nº de ids ≈ filas del catálogo fiev-nid6 por clase; fallar si no cuadra
```

| | Hoy | Propuesto |
|---|---:|---:|
| Peticiones de descubrimiento | 950.001 | **10** |
| Peticiones de descarga | ~71.900 útiles de 950.001 | ~89.000, todas útiles |
| Tiempo de una pasada a 5,9 req/s | ~45 h | **~4,2 h** |
| ¿Cabe en las 6 h de GitHub Actions? | **No** | Sí, justo — ver abajo |

Cabe, pero sin margen. Dos formas de partirlo, y las dos son baratas ahora que hay un índice:
descubrir una vez y persistir la lista (que es lo que el workflow ya *dice* que hace con un
`discovery_ids.txt` que no existe), y trocear por clase, que ya viene troceada de origen.

**Y el aserto del §0.1.1 no es opcional aquí**: contrastar el recuento de ids del sitemap
contra el `count(1)` del catálogo por clase, y fallar si no cuadran. Es una petición, y es lo
único que va a avisar de que el sitemap se ha truncado en silencio.

## La lección, que es la misma de `es`

En España el índice real estaba publicado y enlazado en prosa desde una página que nadie
abrió: 4 peticiones frente a las 14.926 que se diseñaron encima de la conclusión contraria.

En Colombia es peor, porque no hubo que abrir nada: **estaba en el `robots.txt`, estaba
escrito en nuestro propio `RESEARCH-CO.md` de abril, y estaba enlazado en el README que
publicamos en el repo del país.** El fetcher se escribió afirmando lo contrario y nadie
comparó las dos frases. El coste ha sido 950.001 peticiones por pasada, cuatro pasadas
mensuales canceladas, y —lo de verdad caro— los **17.087 documentos** de
`03-brecha-de-corpus.md`.

Ese es el motivo por el que §0.1.1 exige URL y código de estado: una afirmación sin ellos no
se puede refutar, y ésta sobrevivió cinco meses sin que nadie pudiera.
