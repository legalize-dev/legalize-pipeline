# RESEARCH-CO-v2 — Colombia, Step 0 rehecho con el playbook actual

> **ESTADO: Paso 0 PARADO, 2026-09-03.** SUIN-Juriscol lleva caída para todo el mundo desde
> el **2026-08-02**, así que las sondas que miden la fuente no se han ejecutado. Ninguna
> línea de código escrita, ningún commit, ningún fetch, `countries/co` ni siquiera clonado.
>
> **Para retomar:** ejecuta `python3 co-v2/probe-suin.py`. Sale **1** mientras SUIN no
> conteste, y explica en su propia salida si tiene sentido levantar una VM en otra región
> (hoy: no). Si sale **0**, lo pendiente está en `co-v2/00-DECISIONES.md` §6, y lo primero
> **no** es una sonda: es comprobar si SUIN ha vuelto **igual** — un mes de silencio es
> compatible con una reescritura del portal, y si cambian los `id`, los 71.900 `source:`
> publicados quedan colgando.
>
> **Artefactos reproducibles:** `co-v2/probe-suin.py` (4 comprobaciones, 2 peticiones a SUIN)
> y `co-v2/catalog-gap.py` (2 peticiones, **ninguna** a SUIN) con su salida
> `co-v2/gap-2026-09-03.txt`. Cuatro informes en `co-v2/01…04-*.md`. Copia del `robots.txt`
> de SUIN en `co-v2/suin-robots-2025-08-15.txt`.

Estado: **Paso 0 parado en el bloqueo de fuente — corpus intacto, sin código**
Fecha: 2026-09-03 · País: `co` · Fuente: SUIN-Juriscol (caída) + catálogo del Ministerio
Decisiones para el mantenedor: [`co-v2/00-DECISIONES.md`](co-v2/00-DECISIONES.md)

Este documento es a Colombia lo que `RESEARCH-ES.md` es a España: no un onboarding, la
auditoría de un país publicado. Sigue la estructura de
[`adding-a-country/step-0-research.md`](../adding-a-country/step-0-research.md) y da un
veredicto explícito por gate.

**Coste HTTP total de la pasada:** ~60 peticiones — 8 a `www.suin-juriscol.gov.co` (todas sin
respuesta), 3 a hosts `.gov.co` de control, ~10 a `datos.gov.co` y el resto al Internet
Archive. Sin 429. Muy por debajo del presupuesto, porque la fuente no admitía gasto.

---

## TL;DR

Colombia se incorporó en abril de 2026 y nunca pasó el Paso 0 con el playbook actual. La
sesión se abrió para rediseñar el descubrimiento (#113: 950.001 peticiones para 71.900
normas). Encontró algo mayor.

1. **La fuente lleva un mes caída para todo el mundo.** No es nuestra IP: el Internet
   Archive, desde EE. UU., pasó de 1.855 capturas en julio a **0 desde el 2 de agosto**,
   mientras otros hosts `.gov.co` contestan con normalidad desde este equipo. La VM de São
   Paulo no aplica.
2. **El índice que el fetcher declara inexistente existe, y estaba escrito en tres sitios
   nuestros.** SUIN declara **24 sitemaps en su `robots.txt`**, y el Ministerio publica el
   catálogo completo en datos.gov.co. **950.001 peticiones → 10.** `RESEARCH-CO.md:13` ya lo
   decía en abril; `discovery.py:17` afirma lo contrario; nadie comparó las dos frases.
3. **El corpus publicado no tiene ni un documento posterior a 2014.** Faltan **17.087**
   normas del catálogo oficial (19,1 %), **10.477** de ellas posteriores a 2014 y **8.692**
   vigentes. Cinco clases documentales enteras están al 0 %; de 8.491 resoluciones publicamos
   **11**.
4. **La causa es un solo mecanismo, y está medida.** SUIN numera en dos bloques y el barrido
   sólo visita uno. **72.351 ids caen dentro del rango configurado; hay 71.900 ficheros
   publicados** — coinciden al 99,4 %. Todo el bloque de los 30 millones, donde están las
   clases nuevas y lo reciente, no se ha visitado nunca.
5. **El arreglo propuesto en #113 no lo habría arreglado**: habría cerrado el ticket del coste
   dejando intacta la brecha de contenido.

---

## §0.1 Fuente — **GATE: FAIL** (caída, un mes)

`01-fuente-caida.md`. TCP conecta, TLS negocia, cero bytes de HTTP en las seis variantes
probadas. Controles: `secretariasenado.gov.co` (IP colombiana) **200**; `r.jina.ai` (red
independiente) mismo `ERR_EMPTY_RESPONSE`; Internet Archive **0 capturas desde 2026-08-02**.

Veredicto: caída global, no geobloqueo. **No levantar la VM.**

## §0.1.1 Encontrar todos los índices — **GATE: FAIL** (existían y no se usaban)

`02-descubrimiento.md`.

| Índice | Peticiones | Cubre | Omite | ¿Documentado? |
|---|---:|---|---|---|
| 10 sitemaps por clase | **10** | el `id` de cada documento, por clase | `lastmod`; identidad tipo/número/año | Sí — `robots.txt` |
| Catálogo `fiev-nid6` (datos.gov.co) | **1** | 89.366 normas: identidad, `vigencia`, `sector`, `entidad`, `subtipo`, `materia`, `art_culos` | el `id` de SUIN → no descarga | Sí — y en nuestro README |
| Barrido de enteros (hoy) | **950.001** | el ~85 % que cae en 1.0M–1.95M | el 14,6 % que no | No |

Negativos probados, con URL y estado, en `02-descubrimiento.md`. Incluye el dataset
`pj9b-rf8w`, que **no** sirve: es una visualización (`"no row or column access to
non-tabular tables"`).

**Aviso de población:** tres sitemaps (`cconstitucional`, `consejoestado`, `csuprema`) son
**jurisprudencia**, 7.193 documentos sólo en el primero. Hay que elegir clases.

**No ejecutado:** abrir la UI de búsqueda y leer las peticiones de red (§0.1.1 lo exige).
Requiere la fuente viva.

## §0.2 Fixtures — **NO REHECHOS**

Los cinco de abril siguen en `tests/fixtures/co/`. No se han refrescado: la fuente no
responde. Ninguno cubre las clases que faltan (resoluciones, circulares, acuerdos), que es
justo donde hará falta un fixture nuevo.

## §0.3 Inventario de metadatos — **GATE: PASS con dos huecos**

`04-codigo-workflow-metadatos.md` §4.3.

- **Las 20 keys publicadas están en inglés.** `co` cumple #129 — a diferencia de las 6 keys
  castellanas de `es`. Los valores siguen en castellano, que es lo acordado.
- **Se tiran dos campos que la fuente publica**: `materia` y `art_culos`. El segundo importa
  más de lo que parece: `article_count` se calcula hoy con una regex sobre el Markdown
  (memoria `article_count_architecture`), y aquí la fuente da el número. Publicar los dos
  convierte una adivinanza en un contraste.
- **Defecto de forma ya publicado:** `modification_summary` aplana 102 reformas con
  estructura real —verbo, artículo, norma, enlace `#ver_{id}`— en un único escalar YAML sin
  tope. Es el patrón de #87 (el `gr` unido por comas), y `co` es el peor caso publicado.

## §0.4 Cobertura de formato — **GATE: BLOQUEADO**

`04-codigo-workflow-metadatos.md` §4.4. Contrastar el `.md` contra el HTML de origen exige la
fuente.

Sí se comprobó, contra el aviso de #128, que **`co` no está roto por la capa compartida**: el
grep sólo ve la literal `"table"`, pero en ejecución emite además `titulo_tit`,
`capitulo_tit`, `seccion`, `articulo`, `list_item`, `firma_rey` y `parrafo`. Las ocho están
mapeadas salvo `parrafo`, que cae por defecto correctamente.

Dos apuntes propios de `co`: emite **`firma_rey` en una república** (a la lista de #128), y
`promote_first_article` sólo promueve a `articulo` el **primer** párrafo de cada bloque —
sospecha con mecanismo leído, **incidencia sin medir**.

## §0.5 Historial de versiones — **GATE: BLOQUEADO**

El gate que obligó a rehacer Italia entera (memoria `feedback_versions_mandatory`). `co`
publica `modification_count` y `modification_summary`, así que la fuente **registra**
reformas; queda sin comprobar si `LEGISLACIÓN ANTERIOR` da **versiones fechadas** utilizables.
Es lo primero que hay que medir cuando SUIN vuelva.

Aviso de `es`: si aparece un patrón por años, sospechar — allí tres sondas dieron tres años
suelo distintos y las tres se refutaron; la disponibilidad era **por documento**.

## §0.6 `text_state` — **GATE: BLOQUEADO** (y hoy probablemente sobreafirma)

`co` no está en `TEXT_STATE` → default `POINT_IN_TIME`, la afirmación más fuerte del spec,
nunca verificada. La evidencia indirecta apunta a `CURRENT` (la forma de `se` y `uy`).
Decidirlo exige la fuente. Regla de dirección del fallo: ante la duda, infravalorar.

## §0.7 / Step 7 Gate de calidad — **GATE: BLOQUEADO**

Comparar el Markdown que producimos contra el documento oficial exige la fuente. Cuando se
haga, dos reglas de `es`: **no comparar la fuente consigo misma**, y medir **cuánto texto
oficial falta**, no sólo si hay etiquetas sueltas.

## §0.8 Cobertura del corpus — **GATE: FAIL** (el hallazgo de la sesión)

`03-brecha-de-corpus.md`. Único gate que se pudo cerrar en firme, porque no depende de SUIN.

```
catálogo oficial : 89.366        faltan  : 17.087  (19,1 %)
publicados       : 71.900        huérfanos:     25  (0,03 %)  ← valida la unión
```

| | |
|---|---:|
| posteriores a 2014 que faltan | **10.477** |
| que faltan y están **vigentes** | **8.692** |
| resoluciones publicadas / existentes | **11** / 8.491 |
| clases documentales al 0 % | **5** |
| documentos publicados posteriores a 2014 | **0** |

Causa medida: SUIN numera en dos bloques, el barrido visita uno. **72.351 ids dentro del
rango, 71.900 ficheros publicados — 99,4 % de coincidencia.**

## Cadencia y `discover_daily` — **GATE: FAIL, y sin arreglar**

`discover_daily` devuelve vacío, así que el mensual es el **único** camino por el que
Colombia puede publicar. **Los sitemaps no lo arreglan: no llevan `<lastmod>`** (comprobado
en tres). Vía plausible y **sin verificar**: diffear el catálogo `fiev-nid6` contra el estado
local, 1 petición al día.

## Workflow — **GATE: PARCIAL**

`04-codigo-workflow-metadatos.md` §4.1. `monthly-update-co.yml` **ya** tiene `if: always()` y
token refrescado antes del push. Lo que sigue roto es lo que #114 demostró: **`if: always()`
no sobrevive a `timeout-minutes`**, y el comentario del workflow sigue afirmando que sí.
Sigue documentando además un `discovery_ids.txt` que no existe — que con §0.1.1 pasa de
ficción a ser exactamente lo que hay que construir.

---

## Resumen de gates

| Gate | Veredicto |
|---|---|
| §0.1 Fuente accesible | **FAIL** — caída global desde 2026-08-02 |
| §0.1.1 Todos los índices encontrados | **FAIL** — existían, documentados, sin usar |
| §0.2 Fixtures | **NO REHECHOS** |
| §0.3 Inventario de metadatos | **PASS** — keys en inglés; 2 campos desaprovechados |
| §0.4 Cobertura de formato | **BLOQUEADO** |
| §0.5 Historial de versiones | **BLOQUEADO** — lo primero al volver |
| §0.6 `text_state` | **BLOQUEADO** — hoy probablemente sobreafirma |
| §0.7 Gate de calidad | **BLOQUEADO** |
| §0.8 Cobertura del corpus | **FAIL** — faltan 17.087; nada posterior a 2014 |
| Cadencia / `discover_daily` | **FAIL** — vacío, y los sitemaps no lo resuelven |
| Workflow mensual | **PARCIAL** — el comentario de `if: always()` sigue mintiendo |
| Sonda 9 · dry run | **NO EJECUTADO** — requiere la fuente |

Cifras disputadas y no aptas para decidir: `co-v2/00-DECISIONES.md` §7.
