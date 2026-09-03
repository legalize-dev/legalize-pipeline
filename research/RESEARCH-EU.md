# RESEARCH-EU — Unión Europea (EUR-Lex / CELLAR)

> **Fecha:** 2026-09-03 · **Spec:** v0.4 · **Estado del país:** publicando, sin revisar
> (uno de los 30 de `PLAN-MADUREZ-PAISES.md` §2).
>
> **Alcance aprobado el 3-sep-2026: 87.227 actos** (§6). Sin empezar.
>
> Este documento no existía. `eu` se onboardeó en abril de 2026 con el playbook
> anterior: no tiene RESEARCH, ni `TEXT_STATE`, ni `LAYOUT`, ni pasó el gate de
> calidad. Es la primera aplicación del `adding-a-country/` actual a este país.
>
> Toda cifra lleva debajo la consulta que la produjo. Las consultas están en
> `engine/research/eu-v2/` y se reproducen con `sq.py <fichero.rq>`.

---

## §1 El titular

**Publicamos 15.919 actos. EUR-Lex sirve 87.227 en el alcance defendible, y
102.098 contando todo lo descargable en inglés y HTML.** No falta una fuente
nueva. Faltan tipos de acto, sobra un filtro, y hay un parser que solo entiende
la mitad del corpus.

Tres cosas, ninguna documentada, explican el 82 % que falta:

1. **`config.yaml` limita `reg_types` a `REG, REG_IMPL, REG_DEL, REG_FINANC`.**
   Solo reglamentos. **No hay ni una directiva en el corpus.**
2. **`discovery.py:88` exige `resource_legal_in-force = true`.** Se lleva 128.543
   reglamentos. De ellos, 46.217 son derecho derogado de verdad y hay que
   recuperarlos; los otros 82.326 no llevan el campo, y resultaron ser
   instrumentos agotados el día que se publicaron (§3.1).
3. **El parser solo entiende el marcado moderno de EUR-Lex** (§0.7.2). Esto no
   limita el alcance: lo rompe. **1.926 ficheros ya publicados son bloques de
   texto sin un solo artículo** (§3.3).

La tercera no la buscaba nadie, es la más barata de arreglar, y es la que hay
que hacer primero — porque además es el prerrequisito de las otras dos (§4.0).

## §0.1 Las fuentes

| | |
|---|---|
| **SPARQL** | `https://publications.europa.eu/webapi/rdf/sparql` — Virtuoso, ontología CDM. Público, sin auth. Es el índice masivo. |
| **CELLAR REST** | `https://publications.europa.eu/resource/celex/{CELEX}` con `Accept-Language: eng`. Sirve el XHTML. |
| **Licencia** | Decisión 2011/833/UE — reutilización libre, incluida la comercial, con mención de la fuente. |

### §0.1.1 Todos los índices — resultado del barrido

El checklist completo, con lo que devolvió cada uno. Incluidos los fallos,
porque el siguiente que lea esto necesita saber qué ya se probó:

| Sonda | Resultado |
|---|---|
| `eur-lex.europa.eu/robots.txt` | 200. `Crawl-delay: 10`. Prohíbe `/legal-content/*/TXT/DOC/`, `/export-documents`, `/smartapi`. **No usamos ninguna.** |
| `eur-lex.europa.eu/sitemap.xml` | 200, pero es un índice de 21 páginas de portal, no del corpus. Inútil para descubrir. |
| `eur-lex.europa.eu/eli-register/sitemap.xml` | 404 |
| `publications.europa.eu/resource/oai` | 500 · `eur-lex.europa.eu/oai` → 404. **No hay OAI-PMH.** |
| `EURLexWebService?wsdl` | 200 — SOAP, pero requiere registro y cuota. El SPARQL no. |
| `op.europa.eu/robots.txt` | 200, `Allow: /`. **`/resource/cellar/` no está prohibido**: nuestra ruta de descarga es limpia. |
| **SPARQL CELLAR** | **El índice bueno.** El catálogo entero por tipo en 1 consulta, 0,6 s. |

**Conclusión del §0.1.1: no hay un índice más barato escondido.** A diferencia
de España (`/eli/sitemap.xml`, 3.700× más barato) o Colombia (24 sitemaps en
`robots.txt`), aquí ya estábamos usando el mejor índice desde el primer día. El
problema no es el índice, es el `WHERE` que le ponemos encima.

---

## §0.5 Historia de versiones y `text_state` — GATE

### §0.5.1 El spike pasa

EUR-Lex publica los textos consolidados como works aparte, enlazados con
`cdm:act_consolidated_based_on_resource_legal`, cada uno con su
`work_date_document`. El cliente ya los agrupa en un sobre multi-versión y el
pipeline emite un commit por reforma. **Verificado contra el repo publicado:**
el RGPD tiene 1 consolidación en CELLAR (`02016R0679-20160504`) y exactamente 1
commit en `legalize-eu`. Correcto.

### §0.5.2 Pero el `text_state` está mal declarado, y a lo grande

De los **102.098** actos del alcance completo:

| | actos | % |
|---|---:|---:|
| con al menos un texto consolidado | 9.593 | 9,4 % |
| **sin ninguna consolidación** | **92.505** | **90,6 %** |

Y del corpus **que ya está publicado hoy** (16.127 descubiertos):

| | actos | % |
|---|---:|---:|
| con consolidación | 3.046 | 18,9 % |
| **sin consolidación** | **13.081** | **81,1 %** |

`countries.py::TEXT_STATE` **no declara `eu`**, así que cae al default
`POINT_IN_TIME`: "el cuerpo es la ley tal como estaba en vigor en
`last_updated`". Para 13.081 ficheros publicados eso no es lo que hay dentro —
lo que hay es el acto tal como se adoptó.

**Es exactamente el perfil de Portugal** (DRE consolida 5.561 y publica 159.000
como enacted), y la solución es la que ya está escrita en `countries.py`:

```python
"eu": TextState.AS_ENACTED,  # CELLAR consolida el 9%; el resto es el acto adoptado
```

…con el parser devolviendo `POINT_IN_TIME` por norma en las que sí tienen
consolidación. Es una línea más una condición, ya hecha una vez para `pt`.

Cambiar esto reescribe la salida publicada → **exige reemisión** (regla
"Output format is FINAL"). Lo cual encaja, porque el §2.2 obliga a reemitir de
todos modos.

---

## §0.6 Alcance y coste

| | |
|---|---|
| Actos en el alcance recomendado (§4) | **87.227** |
| Peticiones de descubrimiento | ~90 consultas SPARQL paginadas (1.000/página) |
| Descargas | 1 por acto + 1 por consolidación ≈ **100.000** |
| Tiempo de fetch a 8 req/s | **~3,5 h** |
| Tamaño del repo proyectado | **~1,9 GB** (354 MB / 15.919 × 87.227) |

El fetch no es el problema. **El repo sí.** `legalize-eu` son 354 MB con 15.919
leyes en un único directorio `eu/` plano. A 87.227 son ~1,9 GB, pegado al techo
de 2 GiB de GitHub, y con el coste de árbol plano que el §Sharding de la spec
midió: a 50.000 ficheros, 401 s por push contra 4 s sharded; a 157.504, el pack
no cabe y el repo no se puede subir. Es literalmente lo que le pasó a `pt`.

---

## §0.7 Cobertura de formatos — GATE

Este país tiene **dos** dimensiones de formato, no una. Saltarse la segunda es lo
que produjo el defecto §3.3.

### §0.7.1 Dimensión 1 — el fichero (HTML vs PDF)

Reglamentos (`REG*`, sin corrigenda), por estado del campo `in-force`:

| Estado | Works | Con EN + HTML | % |
|---|---:|---:|---:|
| `in-force = true` | 16.171 | **16.127** | 99,7 % |
| `in-force = false` | 46.217 | **35.819** | 77,5 % |
| **campo ausente** | 82.326 | **12.748** | 15,5 % |
| **Total** | 144.714 | 64.694 | 44,7 % |

Los que **no** tienen HTML en inglés:

| Formato | Works que solo lo tienen así |
|---|---:|
| `print` | 66.632 |
| `pdfa1b` | 60.233 |
| `pdf` | 6.322 |
| *(sin ninguna expresión en inglés)* | 13.379 |

**El formato con más cobertura del corpus histórico es PDF/A, no HTML** — el
mismo patrón que Suiza. Un fetcher que solo lee HTML techa en 64.694 de 144.714
reglamentos.

**Decisión del gate:** se justifica **no** cubrir PDF/A en esta iteración, y la
justificación no es de coste sino de contenido: los works que solo existen en
PDF son en su enorme mayoría el Diario Oficial pre-1998 y el material rutinario
del §4.3. **Se revisa cuando el §4.2 esté hecho**, que es donde está la ley.

### §0.7.2 Dimensión 2 — el marcado dentro del HTML · **la que nos ha mordido**

"HTML" no es un formato aquí, son dos, y el parser solo entiende uno:

| | Moderno (desde ~2005) | Legacy (hasta ~2004) |
|---|---|---|
| Envoltorio | XHTML con clases semánticas | `<TXT_TE>` |
| Artículos | `class="oj-ti-art"` (94 en la directiva de 2014) | `<p>` pelado, "Article N" solo como texto |
| Estructura | `eli-subdivision` (241), `eli-title` (119) | ninguna |
| Tablas | `oj-table` (1.486) | ninguna marca |
| Notas | `oj-note` (51), `oj-super` | ninguna marca |
| Clases totales | ~12 distintas | 4, y ninguna del contenido |

Frontera medida fetcheando `3{año}R0001` año por año: `TXT_TE` en 1985, 2000 y
2003; `oj-ti-art` desde 2005. **La frontera está en 2004/2005.**

Prueba pasando las muestras por `EURLexTextParser` real
(`research/eu-v2/samples/`):

| CELEX | Caso | Bloques | Párrafos | Caracteres |
|---|---|---:|---:|---:|
| `32016R0679` | RGPD, moderno | 1 | **1.234** | 348.455 |
| `32014L0024` | Directiva contratación, moderno | 1 | **1.212** | 376.141 |
| `32019R0947` | Drones, moderno con tablas | 1 | **277** | 45.782 |
| `31968R1017` | Reglamento 1968, **legacy** | 1 | **2** | 46.614 |
| `31993D0465` | Decisión 1993, **legacy** | 1 | **2** | 57.136 |
| `11957E000` | Tratado CEE, **legacy** | 1 | **2** | 2.956 |

El texto se extrae (46.614 caracteres de un fichero de 51.667 bytes), pero la
estructura se pierde entera: todo cae en dos párrafos gigantes.

**Reparto del alcance recomendado por marcado:**

| | Moderno (`oj-*`) | **Legacy (`TXT_TE`)** | Total |
|---|---:|---:|---:|
| En vigor | 28.457 | **8.258** | 36.715 |
| Derogado | 13.109 | **37.403** | 50.512 |
| **Total** | **41.566** | **45.661** | **87.227** |

**El 52 % del alcance es legacy.** El gate del playbook dice que todo formato que
aporte más del 1 % debe estar cubierto o el salto justificado por escrito. Aquí
aporta el 52 % y no está cubierto. **El gate §0.7 no se pasa hoy.**

Matiz que salva la mayor parte del corpus actual: **EUR-Lex reedita los textos
consolidados en el formato moderno**, aunque el acto base sea de 1968. Por eso
`eu/32003R0001.md` (Reglamento 1/2003, de 2002) sí tiene sus 41 artículos: se
publica desde su consolidación, no desde el original. El daño se concentra en
los actos **sin** consolidación — que son el 91 % del alcance (§0.5.2).

## §0.3 Inventario de metadatos — lo que la fuente da y no capturamos

El work del RGPD expone **41 propiedades** en CELLAR. El frontmatter publicado
lleva 13. La regla del playbook §0.3 es "si la fuente lo da, lo capturas".

Lo que ya capturamos: `title`, `identifier`, `country`, `rank`,
`publication_date`, `last_updated`, `status`, `source`, `department`, `eli`,
`entry_into_force`, `end_of_validity`, `celex`, `regulation_type`.

Lo que la fuente da y tiramos:

| Propiedad CDM | Qué es | Por qué importa |
|---|---|---|
| `work_is_about_concept_eurovoc` | descriptores EuroVoc (9 en el RGPD) | Es la materia, normalizada y multilingüe. El buscador no tiene nada equivalente. |
| `resource_legal_is_about_concept_directory-code` | código del Repertorio | La clasificación oficial por materia. |
| `resource_legal_is_about_subject-matter` | materia | |
| `resource_legal_eea` | relevancia EEE | Determina si aplica a Noruega/Islandia/Liechtenstein. |
| `resource_legal_based_on_concept_treaty` | base jurídica en los Tratados | Lo primero que mira un jurista. |
| `resource_legal_repeals_resource_legal` | qué deroga | Grafo de derogaciones. |
| `resource_legal_amends_resource_legal` | **qué modifica** | **Es el `amends` de la spec v0.4 §Amending acts, servido en bandeja.** |
| `resource_legal_published_in_official-journal` | referencia al DO | Cita canónica. |
| `resource_legal_date_signature` | fecha de firma | |
| `resource_legal_date_entry-into-force` | ya capturado | |
| `work_cites_work` | citas (33 en el RGPD) | |
| `resource_legal_id_sector`, `_year`, `_number_natural` | descomposición del CELEX | |

Dos redundancias que además hay que limpiar en la reemisión:

- **`celex` duplica `identifier`.** Son el mismo valor, byte a byte.
- **`regulation_type` se queda sin sentido** en cuanto entren directivas. El
  nombre correcto es `resource_type`.

---

## §2 Conformidad con la spec v0.4

| Cláusula | Estado |
|---|---|
| **§Identifiers — único en todo el repo** | ✅ **Se cumple por construcción.** 187.750 works ↔ 187.750 CELEX distintos, **0 colisiones**. El CELEX ya lleva el discriminante (sector + año + tipo + número). Es el mejor identificador de todos los países. |
| **§History — la historia git es la del corpus** | ✅ Verificado contra el RGPD. |
| **§Conformance — `.legalize.yml`** | ❌ **No existe.** `gh api .../contents/.legalize.yml` → 404. El repo es anterior a la v0.4. |
| **§Directory layout / §Sharding** | ❌ Directorio `eu/` plano. A 87.227 ficheros es el caso que la spec mide como imposible de subir. |
| **§Text state** | ❌ Sin declarar; el 81% del corpus publicado dice `point_in_time` y no lo es (§0.5.2). |
| **§Amending acts — `amends`** | ⚪ Ausente y opcional. Pero `resource_legal_amends_resource_legal` está ahí (§0.3): es de las pocas fuentes que permite emitirlo **completo**, que es lo que la spec exige para poder emitirlo. |
| **§Dates** | ✅ Sin placeholders detectados. |

### §2.1 `status` cuando la fuente calla — investigado el 3-sep, y NO hace falta tocar la spec

> **Corrección.** La primera versión de este documento sostenía que la ausencia
> del campo `in-force` en 82.326 reglamentos era una laguna de metadatos de
> EUR-Lex, y proponía añadir `status: unknown` a la spec v0.5. **Las dos cosas
> eran falsas.** Lo que sigue es lo que salió al ir a buscar el dato de verdad.

**Primero: CELLAR no tiene el dato, y está verificado con control positivo.**

| Sonda | Resultado |
|---|---|
| Web de EUR-Lex (`legal-content/EN/ALL/?uri=CELEX:...`) | HTTP 202, 0 bytes. **Ojo: era una caída del servicio**, no una defensa anti-bot — comprobado en navegador el 3-sep, todo documento redirige a `TodayOJ` con el aviso *"EUR-Lex is temporarily not fully available"*. Habrá que reintentarlo. |
| `Accept: application/xml;notice=branch` | HTTP 400 |
| `notice=object` sobre `32005R0002` (cubo sin campo) | 200, 53 KB, **sin ninguna mención de estado** |
| `notice=tree` sobre el mismo | 200, 1 MB, **igual** |
| **`notice=object` sobre `32016R0679` (control)** | 200, 900 KB, **`RESOURCE_LEGAL_IN-FORCE` ×2 con `<VALUE>true</VALUE>`** |

El control es lo que hace válido el negativo: el mismo tipo de petición sí trae
el campo cuando existe. **No hay un endpoint escondido con el estado.**

**Segundo, y es lo que cambia la conclusión: la ausencia del campo _es_
información.** EUR-Lex mantiene el flag para el corpus vigente que cura; nunca
metió ahí los actos que se agotaron al publicarse. Dos medidas independientes lo
demuestran:

| Cubo | Works | Con texto consolidado | Tasa |
|---|---:|---:|---:|
| `in-force = true` | 16.171 | 3.055 | 18,9 % |
| `in-force = false` | 46.217 | 3.005 | 6,5 % |
| **campo ausente** | **82.326** | **20** | **0,02 %** |

**20 de 82.326.** Un acto que alguien modificó alguna vez tiene consolidación;
estos no la tienen porque **nunca se modificaron**, que es lo que le pasa a un
acto que fija el precio del arroz para el martes que viene.

Y la clasificación por título, con un patrón deliberadamente ancho:

| Cubo | Instrumento agotado | Resto |
|---|---:|---:|
| **campo ausente** | **12.154 (95,3 %)** | 594 |
| `in-force = false` *(control)* | 11.105 (31 %) | 24.714 |

El patrón sobredispara a propósito — en el cubo de derogados marca un 31 % que
sí es ley sustantiva. Aun así el contraste es 95 % contra 31 %.

**Tercero: comprobado acto por acto, en el navegador y en el texto (3/4-sep).**

| Acto | Qué se comprobó | Resultado |
|---|---|---|
| `32005R0002` | Su propio texto en CELLAR | *"This Regulation shall enter into force on 4 January 2005."* Su contenido es una tabla de valores para ese día. |
| **La serie entera** | Cuántos actos comparten ese título | **5.510 reglamentos** *"standard import values for determining the entry price"*, del **3-ene-1995 al 30-may-2017** — uno por día laborable durante 22 años. Ese único patrón es el 43 % del cubo. |
| `32026R1214`, `32026R1166`, `32026R1167` | Navegador, página del DO | **Aparecen en el Diario Oficial del 3-sep-2026.** O sea: hoy. |

**Y eso último obliga a un matiz que la regla no tenía.** El cubo sin campo no es
homogéneo: tiene el grueso agotado *y una cola de actos recién publicados a los
que EUR-Lex aún no ha asignado el flag*. Son pocos — la tabla por décadas da **4
en los 2020**, y resultan ser exactamente estos, de la Gaceta de hoy — pero el
error sería el peor posible: **publicar como `expired` un reglamento que acaba de
entrar en vigor**, que además es el que más gente va a consultar.

**Guardarraíl obligatorio, entonces:** la regla `campo ausente → expired` **solo
se aplica pasada una ventana de gracia** desde la publicación en el DO (algo del
orden de 6-12 meses, a medir contra el ritmo real con que EUR-Lex asigna el
flag). Dentro de la ventana el acto no se clasifica: o se espera, o se publica
sin tocar el estado. El daily lo recogerá cuando EUR-Lex lo marque.

**Conclusión: no hay `status` desconocido aquí, hay `status: expired`** — que ya
está en el vocabulario de la spec v0.4 y no requiere cambiarla. La regla honesta
es: *un acto que EUR-Lex nunca incorporó al corpus vigente y que nunca fue
modificado, está agotado.*

Esto **no** cierra el caso de Austria (#123), que es el contrario y sigue abierto:
allí hay ~1.900 leyes **vivas** marcadas como derogadas. Una fuente que calla
sobre un acto agotado y una fuente que miente sobre un acto vivo no son el mismo
problema, y solo el segundo es un argumento para tocar la spec.

### §2.2 La consecuencia: esto es una reemisión, no una ampliación

Tres cosas obligan a reconstruir el repo entero, y las tres coinciden:

1. El sharding cambia la ruta de **todos** los ficheros (§Sharding: "un país lo
   adopta en una reconstrucción completa, no en sitio").
2. El `text_state` cambia el contenido publicado de 13.081 ficheros.
3. Los metadatos nuevos del §0.3 entran en el frontmatter de todos.

Hacerlas por separado son tres reemisiones. Juntas, una.

**Bonus:** los commits de bootstrap de `eu` están en español ("*versión original
2016*"), de antes de la migración de la v0.2. La spec los da por inmutables,
pero una reconstrucción los regenera en inglés sin trabajo extra.

---

## §3 Defectos del código actual

### §3.1 🔴 `status` se inventa cuando la fuente calla

`fetcher/eu/parser.py:820-824`:

```python
force_val = first.get("force", {}).get("value", "")
if force_val in ("1", "true"):
    status = NormStatus.IN_FORCE
else:
    status = NormStatus.REPEALED      # ← "la fuente no dice nada" → "derogado"
```

Hoy no muerde porque el discovery solo trae `in-force = true`. En cuanto se toque
el filtro, los 82.326 works sin el campo se publican como `repealed`, y eso es
falso por partida doble: ni la fuente lo dice, ni es el valor correcto — son
actos **agotados**, y la spec tiene `expired` para eso (§2.1).

`repealed` y `expired` no son sinónimos: derogar es un acto del legislador,
expirar es que se cumplió el plazo que la propia norma se puso. Publicar 82.326
"derogados" inventa 82.326 derogaciones que nunca ocurrieron.

**Arreglo:** tres ramas explícitas en vez de dos.

```
in-force = true   → in_force
in-force = false  → repealed
campo ausente     → expired   SOLO si el acto lleva publicado más que la ventana
                              de gracia; dentro de ella, no se clasifica (§2.1)
```

Y, como cinturón: si alguna vez apareciera un acto sin el campo **con**
consolidación (hoy son 20 de 82.326), es que la regla no aplica a ese caso —
merece un aviso en el log, no un `expired` silencioso.

### §3.2 🔴 Una directiva se publicaría con `rank: regulation`

`fetcher/eu/parser.py:48-53` — `_RANK_MAP` solo tiene los 4 tipos de reglamento,
y el fallback es literal:

```python
rank = Rank(_RANK_MAP.get(rtype_code, "regulation"))
```

Ampliar `reg_types` sin tocar esto publica 4.326 directivas, 23.390 decisiones y
7.284 tratados etiquetados como reglamentos. **El mapa se amplía en el mismo PR
que el config, nunca después.**

### §3.3 🔴 1.926 ficheros publicados no tienen estructura — en producción hoy

El parser solo entiende el marcado moderno (§0.7.2). Un acto servido desde su
texto original pre-2005 sale como un bloque plano, sin artículos.

**No es una hipótesis, está publicado.** `eu/31961R0007.md`, `eu/31963R0018.md`,
`eu/31964R0182.md`: 1 encabezado cada uno (el H1 del título), **0 encabezados de
artículo**, y "Article N" apareciendo 4 veces en el texto corrido sin promoverse
nunca a encabezado.

Cuántos son, medido:

| | Actos |
|---|---:|
| Publicados hoy (`REG*` en vigor con HTML) | 16.127 |
| …de ellos pre-2005 | 2.315 |
| …pre-2005 **y sin consolidación** = servidos del original legacy | **1.926** |

**1.926 ficheros, el 12 % del corpus de `eu`.** Los otros 389 se salvan porque su
consolidación viene reeditada en formato moderno.

Consecuencias que se propagan: `article_count` es una regex sobre los
encabezados del Markdown, así que esos 1.926 cuentan 0 artículos; y el buscador
indexa un bloque sin jerarquía.

**Arreglo:** despachar el parser por marcado. Al detectar `<TXT_TE>` o la
ausencia de clases `oj-*`, segmentar por `<p>` cuyo texto case
`^Article \d+`/`^ANNEX`/`^CHAPTER`. Es el mismo trabajo que ya se hizo en otros
países y es **la pieza que desbloquea todo lo demás** (§5).

### §3.4 🟠 El asunto del commit pierde la identidad del acto — en producción

`fetcher/eu/parser.py:782` deriva `short_title` con
`re.search(r"\bon\b\s+(.+?)(?:\s*\(|$)")`: se queda con lo que va detrás del
primer " on ". Como el nombre oficial va **delante** de ese "on", el commit
pierde de qué norma habla. Commits reales de `legalize-eu`, hoy:

```
[reform] type-approval of motor vehicles and engines and of systems, ...
[reform] determining the type of evidence to be provided by importers ...
[reform] product intervention and positions
[reform] the market and use of biocidal products  Text with EEA relevance
```

frente a los que se salvan porque su título no lleva " on ":

```
[reform] Commission Implementing Regulation (EU) 2026/1965 of 26 August 2026 amending ...
```

Afecta a ~la mitad del log. El doble espacio de la última línea es otro resto:
quitar el sufijo `(Text with EEA relevance)` no colapsa el espacio.

### §3.5 🟠 El H1 sale duplicado

En `eu/32016R0679.md` el título aparece dos veces seguidas: el H1 del
frontmatter y luego el encabezado propio del documento en mayúsculas. Se ve en
legalize.dev.

### §3.6 🟡 Trampa de datos para quien toque `amends`

`resource_legal_amends_resource_legal` devuelve, junto a CELEX buenos, valores
basura de fragmentos de textos consolidados — sobre el Reglamento 1017/68
salieron `"04"`, `"B"`, `"05"`. **Hay que validar la forma del CELEX antes de
emitir `amends`**, o la spec §Amending acts ("es una lista de `identifier` tal
como los nombra este repo") se incumple.

---

## §4 Qué se puede meter, medido

Actos con texto en inglés y HTML, sin corrigenda, por tipo y estado:

| Tipo | En vigor | Derogado | Sin dato | Total |
|---|---:|---:|---:|---:|
| `REG` + `REG_IMPL` + `REG_DEL` + `REG_FINANC` | **16.127** | 35.819 | 12.748 | 64.694 |
| `DIR` + `DIR_IMPL` + `DIR_DEL` | 1.303 | 3.022 | 1 | 4.326 |
| `DEC` + `DEC_IMPL` + `DEC_DEL` | 12.519 | 9.053 | 1.818 | 23.390 |
| `DEC_ENTSCHEID` (decisiones pre-Lisboa) | 10.751 | 10.398 | 151 | 21.300 |
| `TREATY` | 5.723 | 1.262 | 299 | 7.284 |
| `AGREE_INTERNATION` | 1.043 | 1.356 | 5 | 2.404 |
| `RECO` | 580 | 331 | 1.374 | 2.285 |

*(la columna "En vigor" de `REG` es lo único que existe hoy: 16.127 descubiertos
→ 15.919 publicados, 98,7 % — el descubrimiento y el commit funcionan bien; lo
que no funciona es el parser en el 12 % de ellos, §3.3)*

### §4.0 El prerrequisito que sale de la nada

**Antes de cualquier nivel hay que arreglar el parser legacy (§3.3).** No es una
tarea del alcance nuevo: es un defecto de producción de hoy sobre 1.926
ficheros. Pero además condiciona todo lo de abajo, porque el material legacy no
está donde uno esperaría:

| | Moderno | **Legacy** |
|---|---:|---:|
| Ya publicado (`REG` en vigor) | 14.201 | **1.926** ← roto hoy |
| Nivel 1 (tipos que faltan, vigentes) | ~14.645 | **~5.943** |
| Nivel 2 (derogados) | 13.109 | **37.403** |

Sin ese arreglo, el Nivel 1 añade ~5.943 bloques sin estructura y el Nivel 2
otros 37.403. **Con él hecho, los dos niveles vuelven a ser lo que parecían: una
línea de `config.yaml`.**

### §4.1 Nivel 1 — los tipos que faltan, vigentes · **+20.588** · ✅ **APROBADO 3-sep-2026**

`DIR` 1.303 + `DEC` 12.519 + `TREATY` 5.723 + `AGREE` 1.043.

Es ley europea vigente que sencillamente no tenemos, con el estado declarado por
la fuente y sin ninguna duda de calidad. **Que un corpus de derecho de la UE no
tenga ni una directiva es el agujero más difícil de defender de todo Legalize.**

Verificado que el parser los digiere: la Directiva 2014/24 de contratación
pública sale con 1.212 párrafos, igual que un reglamento moderno (§0.7.2). El
71 % del Nivel 1 es marcado moderno y entra tal cual.

Coste, hecho el §4.0: una línea de `config.yaml` y el mapa de rangos del §3.2.

### §4.2 Nivel 2 — el derecho derogado · **+50.512** · ✅ **APROBADO 3-sep-2026** · después del §4.0

`REG` 35.819 + `DIR` 3.022 + `DEC` 9.053 + `TREATY` 1.262 + `AGREE` 1.356.

Aquí está el grueso, y **la calidad del contenido es alta, medida, no supuesta**.
Clasificando por título contra los patrones de gestión agrícola rutinaria:

| Cubo | Rutina agrícola | Ley de verdad |
|---|---:|---:|
| `in-force = false` | 1.240 (3,5 %) | **34.579 (96,5 %)** |
| campo ausente | 8.487 (67 %) | 4.261 (33 %) |

El cubo de derogados es 96,5 % ley real, con `status` declarado por la fuente y
`status: repealed` ya en el vocabulario de la spec. Un corpus jurídico sin
derecho derogado no puede responder "qué decía la ley en 2010", que es
justamente lo que vende el producto.

**Pero el 74 % de este nivel (37.403) es marcado legacy**, así que su valor real
depende por completo del §4.0. Meterlo antes sería multiplicar por 20 el defecto
§3.3.

### §4.3 Nivel 3 — los que no declaran estado · **+16.396** · 🔴 no · **decidido**

`REG` 12.748 + `DEC` 1.818 + `RECO` 1.374 + resto.

Fuera, y ahora con una razón más limpia que la que había: **el 95,3 % son
instrumentos agotados el día de su publicación**, medido con un patrón de título
deliberadamente ancho (12.154 de 12.748; el resto son 594). Y solo 20 de 82.326
llegaron a tener una consolidación, es decir, **casi ninguno se modificó jamás**
(§2.1).

Muestra literal: *"establishing the standard import values for determining the
entry price of certain fruit and vegetables"* (uno por día laborable durante
décadas), *"opening an invitation to tender for the reduction in the duty on
sorghum imported into Spain"*, *"determining the world market price for unginned
cotton"*, *"suspending the buying-in of butter in certain Member States"*.

Meterlos hundiría la relevancia del buscador (`PLAN-BUSCADOR.md`) y sumaría
~900 MB de repo por material con vigencia de un día. **Ya sabemos cómo
etiquetarlos correctamente si algún día se quieren** (`expired`, §2.1), así que
la puerta queda abierta y sin deuda de diseño.

### §4.4 `DEC_ENTSCHEID` — **fuera, decidido el 3-sep-2026** · 🟡 revisable

21.149 decisiones pre-Lisboa con estado declarado. La razón de peso no es que
sean actos individuales, es una que se puede medir:

| | «Only the X text is authentic» | Inglés auténtico |
|---|---:|---:|
| **`DEC_ENTSCHEID`** | **10.789 (51 %)** | 10.361 |
| `DEC` + `DEC_IMPL` + `DEC_DEL` *(los que sí entran)* | 487 (2,3 %) | 21.086 |

**En la mitad de ellas, el texto inglés no es la ley** — es una traducción de
cortesía, y el propio título lo dice. Publicarlas en un corpus que solo sirve
inglés sería servir 10.789 documentos que no son auténticos en el único idioma
en el que los servimos. La frontera entre lo que entra y lo que no resulta ser
un criterio de la propia fuente (51 % contra 2,3 %), no una preferencia nuestra.

**¿Encaja en el producto? ¿Alguien lo buscaría?** Sí hay demanda real: los
abogados de ayudas de Estado y competencia viven de estas decisiones. Pero no
buscan lo que tendríamos:

- Las citan por **número de asunto** (`SA.38517`, `N 341/2007`), no por CELEX, y
  hoy no capturamos ese número.
- Necesitan el texto **auténtico** en su idioma, que es justo el que no damos.
- Y ya tienen dónde: el registro de asuntos de competencia de la Comisión es
  público, gratuito y buscable por asunto.

Entraríamos terceros con la copia peor. Un corpus de 21.149 documentos que un
especialista descarta a la primera vale menos que no tenerlo.

**Cuándo reabrirlo:** solo si Legalize deja de ser monolingüe en `eu`. Ahí la
pregunta cambia entera, porque entonces sí podríamos servir el texto auténtico.
Mientras tanto, el trabajo que rinde en esta dirección son las `DEC` normales
(12.519 vigentes), que ya están en el Nivel 1 y sí son auténticas en inglés.

### §4.5 El total

| Escenario | Actos | Repo estimado |
|---|---:|---:|
| Hoy | 15.919 | 354 MB |
| + Nivel 1 | 36.715 | ~820 MB |
| **+ Nivel 2 (recomendado)** | **87.227** | **~1,9 GB** |
| + `DEC_ENTSCHEID` | 108.376 | ~2,4 GB ⚠️ sobre el techo de GitHub |
| + Nivel 3 | ~124.772 | ~2,8 GB ⚠️ |

**Recomendado: 87.227 actos, ×5,5 el corpus actual.** Y el sharding deja de ser
opcional a partir del Nivel 1.

---

## §5 El orden

Nada de esto es un parche incremental: el §2.2 obliga a reemitir, así que el
orden lo manda lo que congela el código. Y el primer paso resultó ser el que
menos se esperaba: **lo que hay que arreglar de todos modos es lo que desbloquea
el resto.**

| # | Paso | Por qué aquí |
|---|---|---|
| 1 | **Parser despachado por marcado (§3.3)** | Arregla 1.926 ficheros rotos **hoy** y es el prerrequisito de los dos niveles (§4.0). Si solo se hace una cosa de esta lista, es esta. |
| 2 | **`status` (§3.1) y `_RANK_MAP` (§3.2)** | Los dos que corrompen datos. Van antes de tocar el alcance, no después. |
| 3 | **`short_title` (§3.4) y H1 doble (§3.5)** | Baratos, y se llevan por delante todo el log al reemitir. |
| 4 | **Declarar `TEXT_STATE["eu"] = AS_ENACTED`** + override por norma | Una línea. Decide qué dicen de sí mismos 92.505 ficheros. |
| 5 | **`.legalize.yml` + sharding `{id_sha1_2}`** en `layout.py::LAYOUT` | El manifiesto y el sharding son el mismo cambio, y una entrada en un dict. |
| 6 | **Ampliar `reg_types`** a Nivel 1 + Nivel 2 | Ya sin riesgo, porque 1-5 están hechos. |
| 7 | **Ampliar el frontmatter** con el §0.3 (EuroVoc, base jurídica, EEE, DO) | Mismo pase, mismo coste. |
| 8 | **Inventario §0.2/§0.4 y ensayo de bootstrap** sobre muestra estratificada | El gate que falta (§7). |
| 9 | **Reemisión completa + `legalize push`** | 87.227 actos, ~3,5 h de fetch. |

Los pasos 1-5 son de código, no dependen del bootstrap, y se pueden mergear sin
decidir todavía el alcance final. El paso 1 tiene valor por sí solo aunque el
resto no se haga nunca.

## §6 Decisiones

Tomadas el **3-sep-2026**:

| Pregunta | Decisión | Dónde |
|---|---|---|
| ¿Entra el derecho derogado? | **Sí.** 50.512 actos. | §4.2 |
| ¿`DEC_ENTSCHEID`? | **No**, y anotado por qué se podría reabrir. | §4.4 |
| ¿`status: unknown` para la spec v0.5? | **No hace falta.** Se fue a buscar el dato y resultó que el valor correcto es `expired`, que la spec ya tiene. | §2.1 |
| `RECO` (soft law, 580 vigentes) | **Pendiente.** No bloquea nada; se decide con el Nivel 1 delante. | §4 |

**Alcance aprobado: 87.227 actos** (36.715 vigentes + 50.512 derogados), ×5,5 el
corpus de hoy.

### Lo que queda por decidir, y no corre prisa

1. **`RECO`.** 580 recomendaciones vigentes. No vinculan, pero `rank` es libre y
   caben sin violentar nada.
2. **PDF/A** (§0.7.1). Techamos en 64.694 de 144.714 reglamentos por leer solo
   HTML. Se revisa **después** del §4.2, cuando se vea qué queda fuera de verdad.
3. **Si el repo se pasa de 2 GiB** con el alcance aprobado (proyección: ~1,9 GB,
   con poco margen). El sharding del paso 5 es lo que decide si aguanta.

## §7 Lo que este análisis NO cubre

- **Otros idiomas.** Todo lo medido es la expresión inglesa. Publicar en 24
  idiomas multiplica el corpus por 24 y no cabe; queda fuera por diseño, pero
  hay 13.379 reglamentos **sin ninguna expresión en inglés** (anteriores a 1973)
  que hoy son invisibles y que en francés o alemán sí existen.
- **PDF/A** (§0.7.1): justificado saltarlo, revisable después del §4.2.
- **Jurisprudencia** (TJUE): `case-law` está en CELLAR y es otro producto.
- **§0.4 inventario de formato rico.** Las muestras están descargadas y pasadas
  por el parser real (§0.7.2), que es lo que destapó el §3.3. Lo que **no** se ha
  hecho es el cotejo fino de tablas, notas al pie, fórmulas y anexos contra el
  original — ni siquiera en el marcado moderno, donde el parser sí ve
  `oj-table` (1.486 en la directiva de 2014) y `oj-note` (51). **Es el gate que
  falta antes del paso 8**, y el precedente de `es` (30 % del payload perdido en
  tablas anidadas) dice que no se salta.
- **La comprobación de que el §3.3 arreglado produce buen Markdown.** Está
  medido que hoy pierde la estructura; no está medido cuánto recupera una
  segmentación por `^Article \d+`. Eso se mide con el arreglo delante.
