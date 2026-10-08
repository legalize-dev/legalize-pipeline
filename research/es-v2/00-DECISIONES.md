# es v2 — decisiones que hay que tomar antes de tocar código

3-sep-2026 · Base: las 8 sondas de `engine/research/es-v2/` y las 12 refutaciones de
`99-refutaciones.md`. Al menos **1.887 peticiones** a boe.es (947 de las sondas, 925 de once
de los doce verificadores —el duodécimo no declara su cuenta— y 15 mías reverificando las
cifras que deciden). Ningún 429.

**Lo que ha cambiado respecto a lo que dabas por sabido**, en una línea cada uno:

1. El volumen ya no se estima: el BOE lo cuenta. **78.908** actos de Sección I desde 1979.
   El repo no pasa a 120.000 ficheros; pasa a ~66.000 con la regla de corte aplicada.
2. El sumario **no** es el único índice. `/eli/sitemap.xml` enumera 103.070 normas en
   4 peticiones y trae `lastmod`; hay un Atom feed para el diario. El barrido de 14.926
   sumarios que parecía inevitable no hay que construirlo.
3. La fecha de entrada en vigor **sí está a nivel de bloque**, en el 100 % de los sellos.
   El medio arreglo caro de #106.2 no existe: no hace falta re-fetch para ninguna de las
   dos mitades.
4. El «año suelo» del texto no es un año. Es una propiedad por documento, y la regla
   correcta —`<texto>` vacío → salta— es gratis y exacta en 1889 igual que en 1984.
5. La fidelidad de lo no consolidado **no** está medida contra el acto oficial. Cuando se
   mide, 4 actos de 76 llevan el **2,1 %** de su texto: el resto son 405 PNG de página
   completa. Son el 5,3 % de los actos y el **25,4 %** de las páginas de gaceta.
6. **La regla se ha ejecutado** sobre 420 leyes reales (§8), y rompe en dos sitios: el
   oráculo `estado_consolidacion` falla con un código que nadie documenta, y el árbol de
   artículos se pierde en el **23 %** de lo que emitiría — no en el 3,3 % que se creía.

---

## 0. Decisiones tomadas (Enrique, 3-sep-2026)

Cerradas. Lo que sigue en este documento es la evidencia que las sostiene.

### 0.1 El residuo: **se queda y se etiqueta**

Los ~27–33 % de actos singulares/administrativos entran en el corpus. No se filtran en git;
se filtran después, en la web y en la DB, cuando haya criterio.

**La etiqueta no debe ser una clase semántica.** El 23,5 % de la población no encaja en
ninguna categoría sin un juicio previo, así que un campo `act_class` con la taxonomía sería
una adivinanza cristalizada en 68.000 ficheros. Lo que se emite son **las señales que la
regla sí puede calcular**:

| Campo | De dónde sale | Estado |
|---|---|---|
| `rank_code` | `rango@codigo` | **ya se emite** |
| `references_previous` con el verbo | `<anteriores><palabra>` | ya se emite (y con `<texto>` desde #106.2) |
| **`has_articles`** | el detector del §8: `class="articulo"` ∨ el regex de respaldo | **nuevo, 1 línea** |
| `page_start` / `page_end` | ya se emiten | ya se emite |

Con `rank_code` + `has_articles` se filtra el 80 % de lo que quieras filtrar en SQL, sin
haber decidido nada irreversible. Y si mañana quieres la taxonomía fina, se calcula sobre
esos campos sin tocar el repo.

### 0.2 Los actos-imagen: **se excluyen, con lista**

La puerta de densidad del §2 paso 5 los salta (medido: **1,0 %** de los actos, 4 de 420).
Pero **no en silencio**: el skip escribe un registro durable, no una línea de log.

```
{data_dir}/skipped-low-density.json   ->  [{id, pages, chars, chars_per_page, images,
                                            rango, titulo, fecha_publicacion}, ...]
```

Ese fichero **es** el trabajo futuro: cuando se decida atacarlos (OCR, o publicar el índice
con la galería y un aviso, o enlazar el PDF), la lista ya está y no hay que volver a barrer.

**Y recogerlos después es barato**, que es lo que hace segura la exclusión: un acto que se
añade más tarde es un fichero nuevo con su primer commit fechado en su fecha de publicación,
y la integridad es por fichero, no por repo. No perturba nada de lo ya publicado.

### 0.3 El corte: **dos poblaciones, dos reglas** — y el suelo no toca lo consolidado

Esto era una confusión mía en la redacción anterior y hay que dejarlo explícito, porque un
suelo mal aplicado tira leyes que ya están publicadas.

| Población | Regla | Volumen | Suelo de año |
|---|---|---:|---|
| **Catálogo consolidado** | se coge **entero**, como ya se hace hoy | 12.387, de **1835** a hoy | **ninguno** |
| **Barrido del diario** (lo que añade #66) | aquí se elige el corte | ~68.458 desde 1979 | 1979 |

Medido: **427 normas consolidadas se publicaron antes de 1979, y las 427 ya están en el
repo.** La más antigua es `BOE-A-1835-2348` (Real Orden de 30 de octubre de 1835); por ahí
están la Ley del Notariado de 1862 (`BOE-A-1862-4073`) y el Código Civil de 1889. Un suelo de
1975 aplicado al *descubrimiento* habría tirado 286 de ellas.

### 0.4 Y el corolario: el barrido va **por tandas**, no de una vez

Corrección a lo que este documento decía antes, repitiendo el issue #66: *«un rebuild que
aterrice sin esto no puede recogerlos después sin volver a reconstruir»*. **Es falso.**
Añadir ficheros nuevos después no exige rebuild — lo que lo exige es cambiar el frontmatter
o la ruta de los 12.299 que ya están. Son dos cosas distintas y el plan se parte en dos:

- **Un solo rebuild, obligatorio, sobre las 12.299 actuales.** Sharding, `effective_date`,
  el `include_all`, `fecha_caducidad`, los arreglos de render, la expansión de metadatos.
  Todo eso reescribe ficheros existentes y no se puede hacer en trozos.
- **El corpus nuevo, en tandas.** Y hay una primera tanda obvia, elegida por la medición y no
  por gusto: **2009→hoy tiene 0 % de fallo de estructura** (146 actos del dry-run, 0 fallos),
  mientras 1979–2005 va al 40,4 %.

| Tanda | Alcance | Ficheros nuevos | Repo | Trabajo de parser que exige |
|---|---|---:|---:|---|
| **1ª** | 2010→hoy | ~14.300 | ~26.600 (2,2×) | **ninguno** — el `@class` marca los artículos al 100 % |
| **2ª** | 1984–2009 | ~40.000 | ~66.000 | el respaldo por regex del §8, ya diseñado y probado |
| **3ª** | 1979–1983 | ~14.000 | ~80.000 | decidir qué se hace con `<texto>` vacío |
| (opcional) | 1960–1978 | ~26.000 | ~106.000 | otro producto, decisión aparte |

Ship la primera, mírala en producción, y la segunda entra con el regex ya validado contra
ella. Es lo contrario de jugarse 68.000 ficheros a una sola tirada.

---

## 1. Volumen por año de corte, y qué le hace cada opción al repo

Todas las cifras de las dos primeras columnas son **exactas**, no proyecciones. Sección I
la cuenta el buscador del propio BOE (`/buscar/boe.php`, filtro `ORIS`+`FPU`, verificado a
mano hoy y por dos verificadores con consultas construidas de forma distinta); lo
consolidado sale de enumerar el catálogo (2 peticiones, 12.387 entradas, 12.142 con id
`BOE-A-`).

| Corte | Sección I (exacto) | Consolidadas vía Sec. I¹ | Ficheros nuevos brutos | Con regla de corte² | Repo final | × hoy | Peticiones del barrido³ | Horas @4 r/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **No lo hacemos** | — | — | 0 | 0 | 12.385⁴ | 1,0× | 12.387 | 0,9 |
| **2010→hoy** | 23.012 | 5.496 | 17.516 | ~13.800 | **~26.100** | 2,1× | 17.516 | 1,2 |
| **2000→hoy** | 38.347 | 8.082 | 30.265 | ~23.900 | **~36.200** | 2,9× | 30.265 | 2,1 |
| **1979→hoy** | 78.908 | 10.450 | 68.458 | ~54.100 | **~66.400** | 5,4× | 68.458 | 4,8 |
| 1975→hoy | 86.335 | 10.576 | 75.759 | ~59.900 | ~72.200 | 5,9× | 75.759 | 5,3 |
| 1960→hoy⁵ | 112.251 | 10.754 | 101.497 | ~80.200 | ~92.500 | 7,5× | 101.497 | 7,0 |

¹ El catálogo tiene normas que nunca pasaron por Sección I: medido, el **89,2 %** de las
consolidadas aparece en Sección I, el 9,8 % en Sección III y el 1,0 % en II-B (n=102;
reproducido al 95,0 % en una muestra independiente de 20, agregado 90,2 % sobre 122). Las
245 con id de boletín autonómico no aparecen en ningún sumario del BOE por construcción.
² Aplicando la regla de §2: quita judiciales + correcciones (medido 19,0 % y 22,5 % en dos
censos independientes; uso 21 %). **Este es el único número extrapolado de la tabla.**
³ Un `xml.php?id=` por acto: no hay endpoint masivo. Media medida **29.155 B**/documento
(n=24), mediana 19.784. El descubrimiento en sí son 4 peticiones, no 14.926 (§3).
⁴ Hoy hay 12.299 ficheros y el catálogo tiene 12.387: **88 normas consolidadas no están en
el repo** (86 cuando corrieron las sondas), y no es sólo deriva reciente: 46 son de
2026 pero **42 se publicaron antes**, la más antigua de 1982 (`BOE-A-1982-9070`). Causa medida
en `03-descubrimiento.md` §2.5: `daily.py::_commit_reforms` hace `if not repo.has_file(...)
: continue`, así que una norma que el BOE consolida *por primera vez* años después de
publicarse no puede entrar nunca. ~130/año, y sigue.
⁵ El sumario del BOE empieza exactamente el **1960-09-01** (probado: 08-31 → 404, 09-01 →
200). El buscador llega a 1960-01-01 y devuelve 2.233 actos por debajo del suelo del
sumario. Debajo de 1960 está *Gazeta* (1661–1959, 1.496.594 documentos), que es otra base
de datos y otra decisión.

### Lo que le hace al repo, más allá del número de ficheros

- **Commits.** Un acto no consolidado tiene una sola versión → un commit. Con el corte de
  1979 el repo pasa de 44.295 commits a ~98.000. Aparte, pasar a `fecha_vigencia` mueve el
  **86,6 %** de las fechas de commit y añade **+5,5 %** de commits (~+2.400): un acto que
  escalona su entrada en vigor deja de colapsar en un commit.
- **Tamaño y el límite de 2 GiB.** Hoy 1,58 GiB. Los ficheros nuevos son de un commit, así
  que dominan los blobs y no el churn de árboles: sumando ~54.000 × ~20 KB el repo se va a
  **~3–4 GiB**. Cruza el límite de push, así que va con `legalize push` por rebanadas desde
  el primer día — no es algo que se descubra al final (ver `legalize_push_2gib`).
- **Sharding.** Con 66.000 ficheros el sharding deja de ser una optimización de 45× y pasa
  a ser obligatorio. Y hay un detalle que no está en #106: el esquema tiene que sobrevivir a
  `DOGC-f-2019-90497` igual que a `BOE-A-1978-31229` (245 ids sin número de documento BOE).
- **Fetch local.** ~2,0 GB de XML del diario para el corte de 1979. Cachéalo en disco por
  id y permanentemente: un sumario de 1985 no puede cambiar, y el `FileCache` actual tiene
  TTL de 24 h, que es la política equivocada para esto.

**Recomendación: 1979-01-01.** Es el corte donde convergen las cuatro rutas de medida
independientes, es la era constitucional, y ~66.000 ficheros es un repo que sigue siendo
manejable con sharding. 1960 añade 26.000 ficheros de la dictadura por 2,2 h más de fetch;
es defendible pero es otro producto. 2010 es el corte que no compensa: el 70 % del valor
histórico está antes.

---

## 2. Regla de corte recomendada, y los casos que no puede decidir sola

Se evalúa sobre **un solo documento** — `https://www.boe.es/diario_boe/xml.php?id={id}` —
que hay que traer de todos modos. Cero peticiones extra respecto al barrido.

```
ENTRADA: un id que aparece en Sección I (codigo="1")

1. PUERTA — frescura.  si (hoy − fecha_publicacion) < 180 días → DIFERIR
     No 30 días. Medido sobre la cohorte limpia (n=186, publicadas después del
     re-sellado masivo de dic-2025, corregida por censura a derecha): mediana 12
     días, solo el 44 % consolida en ≤7 d, y el 33 % llega DESPUÉS del día 30.
     Con puerta a 30 d se clasifican mal como «nunca consolidadas» un tercio de
     las que sí lo estarán. A 180 d el error residual es 3,4 %.

2. ORÁCULO — superficie.  si <estado_consolidacion codigo> ∈ {"3","4"} → RUTA ACTUAL
     CORREGIDO tras el dry-run de 420 actos. La condición que escribí primero
     —`codigo != "0"`— es INCORRECTA, y lo dije al revés: llamé a `!= "0"` «la
     mitad estable». `BOE-A-2001-3498` (Ley Foral 17/2000) trae
     `estado_consolidacion codigo="1"` con texto vacío, NO está en el catálogo,
     y `/texto` y `/metadatos` dan 404: es no consolidada, y `!= "0"` la manda
     por la ruta consolidada. El `1` no lo declara nadie — el endpoint
     `/api/datos-auxiliares/estados-consolidacion` sólo dice {3: Finalizado,
     4: Desactualizado}.
     Concordancia con la pertenencia al catálogo: 419/420 con el test positivo,
     1/420 de desacuerdo con el negativo. El dominio drifta en los DOS sentidos
     (además del `1`, hay un «Sin consolidar» vivo en 1 fichero publicado), así
     que el test tiene que ser positivo sobre los valores documentados **y
     registrar en el log cualquier código fuera de {0,3,4}** en vez de asumir.
     Para el bootstrap la autoridad sigue siendo la pertenencia al catálogo.

3. DESCARTE — no es norma.  rango codigo ∈ {1590, 1240, 63, 1250}
                            O cualquier <palabra> ~ /^(CORRECCIÓN|CORRIGE)/
     El lado del descarte es lo más sólido de todo el trabajo: **0 de las 12.387
     entradas del catálogo llevan ninguno de esos códigos**, y 0 aparecen entre
     los 12.299 ficheros publicados. 12/12 y 14/14 descartes correctos, 0 falsos
     descartes, en dos censos disjuntos.
     Dos correcciones sobre lo que decía la sonda:
       · añadir 1250 «Auto» — BOE-A-2004-13466, providencia del TC, está en
         Sección I y el conjunto original lo dejaba pasar;
       · el rango NO basta para las correcciones — BOE-A-2011-20653 es una
         corrección de errores de la CNMV con rango 1370 «Resolución», y su
         título empieza «Resolución de 28 de diciembre…», así que ni el rango ni
         el prefijo del título la cogen. La `<palabra>` sí: 12/12.
     E invierte el test a medio plazo: en vez de mantener una lista negra de
     códigos, **quédate con los 19 códigos de rango que el catálogo consolidado
     usa y manda lo demás a una cola de revisión**. La lista negra falla abierta
     con el próximo 1250; la blanca falla cerrada.

4. PUERTA — texto.  si <documento><texto> está vacío → METADATOS-SOLO o SALTAR
     Esto sustituye a cualquier «año suelo». Es exacto, gratis, y correcto tanto
     en el Código Civil de 1889 (639.684 caracteres, 1.992 <p class="articulo">)
     como en BOE-A-1984-50024 (vacío, nueve años DESPUÉS del suelo de 1975 que
     proponía la sonda).
     TRAMPA: <texto> no es único en el documento. <analisis><referencias>
     <anterior><texto> existe y un `.//texto` lo coge primero — dos agentes
     distintos cayeron en ella hoy, y el síntoma es un render de 0 caracteres,
     no un error. Es `root.find("texto")`, hijo directo de <documento>.

5. PUERTA — densidad.  chars(<texto>) / (pagina_final − pagina_inicial + 1)
     Si < ~600 y hay ≥5 <img>, el acto es un índice con una galería de imágenes.
     Mediana medida sobre 76 actos: 2.896 chars/página. Los cuatro marcados:
     37 · 102 · 346 · 374. Recomiendo MARCAR, no descartar (ver §4).
     Las páginas están en el <metadatos> del mismo documento: cero peticiones.

6. QUEDARSE — emitir fichero.  text_state = as_enacted (ver §5)
```

### Lo que la regla no puede decidir, y su tamaño

**El residuo son los actos singulares/administrativos: ≥27 % de la población no
consolidada, y 27 % es un suelo.** Dos censos independientes lo miden en 27,0 % y 27,6 %,
y sube al **32,7 %** si las publicaciones paramétricas recurrentes cuentan como singulares.
Peor: **el 23,5 %** de la población no encaja en ninguna categoría sin un juicio previo, o
sea que los porcentajes existen sólo después de haber decidido.

El caso que lo cierra, y merece que lo mires porque es el argumento entero — mismo día,
mismo `rango 1340`, misma `seccion`, mismo `origen`, mismo `estatus`, ambos sin consolidar,
ambos con `<anteriores>` = `DE CONFORMIDAD con`:

| id | Título | Chars | Qué es |
|---|---|---:|---|
| `BOE-A-2025-17506` | RD 769/2025 … por el que se regula la **concesión directa de subvenciones** | 37.455 | acto singular |
| `BOE-A-2024-20999` | RD 919/2024 … por el que se **establece una cualificación profesional** | 1.534.689 | norma general |

Nada en `rango`, `seccion`, `departamento`, `origen_legislativo`, `estatus_legislativo`,
`materias` ni `epigrafe` los separa. Seis campos más se probaron contra el residuo en una
segunda pasada (`url_eli`, `vigencia_agotada`, `estatus_derogacion`,
`judicialmente_anulada`, `estatus_legislativo`, `subseccion`) y **ninguno decide**. Lo único
que los distingue es el verbo del título, que es prosa — y `sumario.py` ya lleva un
comentario escrito para no volver a leer palabras de un título.

Otros seis casos reales que la regla no coloca, con id para poder discutirlos:

- **Traspaso de funciones a una CCAA** (7 en una muestra de 98): `BOE-A-2006-7320/1/2/3`. Un
  RD que aprueba el acuerdo de una Comisión Mixta; el contenido normativo está en el anexo.
- **Vehículo de publicación**: `BOE-A-2026-10887` publica el Acuerdo que **aprueba los
  Estatutos de la Universidad de La Rioja** — norma constitutiva completa. `BOE-A-2025-25277`
  publica un Acuerdo de Consejo de Ministros que declara oficiales unos doctorados — acto
  singular. Mismo `rango 1370`, misma forma, mismo verbo *se publica*. Caen a lados
  opuestos de la línea.
- **Boletín paramétrico recurrente**: precios de carburantes, poder calorífico, bases de
  cotización. `BOE-A-2000-24371/2`, `BOE-A-2011-20649`. El BOE los publicó **semanalmente
  durante más de una década**: meterlos como leyes es una decisión de cinco cifras tomada
  por una definición, no por una regla.
- **Acto singular vestido de Ley**: `BOE-A-2011-3432`, *Ley Foral 24/2010*, cuyo contenido
  íntegro es desafectar 101.986,68 m² de terreno comunal. `rango 1450`. Esto mata la salida
  de emergencia de «excluir el residuo por lista de rangos»: **el residuo no vive sólo en
  los rangos bajos**.
- **Derogación pura**: `BOE-A-2016-3975`. No tiene texto autónomo pero no dice «por el que
  se modifica».
- **Fragmento de un acto serializado**: `BOE-A-1986-49992`, *ADR … (Continuación.)*,
  `<texto>` vacío, id fuera del bloque del día. La regla lo *queda* y emitiría un torso.
  n=2 confirmados; si es el 1 %, son varios cientos de ficheros tronco.

**DECIDIDO (§0.1): se queda y se etiqueta.** Excluirlo significaría una heurística sobre
prosa, que es exactamente el fallo que #106.4 acaba de arreglar. Lo que se emite son las
señales calculables —`rank_code`, la `<palabra>` de cada referencia, y el nuevo
`has_articles`— **no** una clase semántica: el 23,5 % de la población no encaja en ninguna
categoría sin un juicio previo, y cristalizar esa adivinanza en 68.000 ficheros es peor que
no tenerla. Con esos campos el sitio y la DB deciden qué enseñan **sin** volver a reemitir.

(Corrección: una versión anterior de este párrafo decía que añadir los actos más tarde
exigiría otro rebuild, repitiendo el #66. Es falso — ver §0.4. Añadir ficheros es barato;
lo caro es tocar los 12.299 existentes.)

**Una consecuencia de las correcciones que hay que decidir aparte:** de 9 correcciones de
errores en una muestra, **7 corrigen un acto que tampoco está consolidado** —
`BOE-A-2011-3428` son 43.597 caracteres que republican anexos de tarifas enteros. «Se
descarta porque el BOE la integra en el texto consolidado» falla el 78 % de las veces. Si se
descartan, hay que **aplicarlas y referenciarlas**, no ignorarlas.

---

## 3. Diseño de descubrimiento para #99 + #66, y su coste

El bloqueo de #99 no es un rename: fallan el nombre (`iter_norms_from_catalog` nunca ha
existido), el tipo (`create({**cc.source, ...})` pasa un dict y `catalogo.py` espera un
`Config`) y las claves (`normas_fijas`, `rangos` ya no están en `config.yaml`). Y
`discover_daily` tampoco se llama nunca: `cli.py:528` prefiere `fetcher/es/daily.py`, que
invoca `sumario.parse_summary` directamente. La clase no tiene ni un llamante vivo.

### 3.1 `discover_all` — el catálogo consolidado (#99)

```
GET /datosabiertos/api/legislacion-consolidada
    ?limit=-1&offset={0,10000}&query={"sort":[{"identificador":"asc"}]}
```

**2 peticiones, 16,0 MB, ~28 s, 12.387 ids.** Medido cinco veces hoy por agentes distintos
con tres paginaciones distintas (`limit=10000`, `5000`, `6000`) y por un segundo eje de
enumeración (ventanas de `fecha_actualizacion`): mismo conjunto, 0 duplicados, 0 huecos.

Cuatro cosas que **no** son opcionales, todas medidas:

1. **`sort` por `identificador` es el arreglo, no un adorno.** El orden por defecto es
   `fecha_actualizacion desc` y **el 72,7 % de las entradas comparte marca de tiempo con
   otra** (6.020 marcas distintas para 12.387 filas, el grupo más grande son 72, y el
   19-dic-2025 tiene 3.299). Paginar con `start`/`rows` de Solr sobre una clave no única es
   el sitio clásico donde las páginas se solapan o se saltan. Hoy no pasó por suerte: la
   frontera entre página 1 y 2 cae *entre* dos grupos.
2. **No lo conviertas en un cursor.** `range` sobre `identificador` se **descarta en
   silencio** con un 200: devuelve la página completa de 10.000. Un walk escrito como
   `identificador > último_visto` nunca termina y parece sano.
3. **Termina en `len(pagina) < limit`, no en `data` vacío.** `limit=0` y «pasado el final»
   son la misma respuesta 200.
4. **No reintentes un 5xx que has construido tú.** Un `query` con JSON malformado devuelve
   **500**, no 400. Un typo se disfraza de caída del BOE y el pipeline hace backoff y alerta.

### 3.2 `discover_published` — lo no consolidado (#66)

**Esto es lo que hay que cambiar respecto a lo que parecía obvio.** El barrido de 14.926
sumarios (2,03 GB, 4,1 h) no hay que construirlo. Hay dos índices publicados que nadie
había mirado, los dos enlazados desde `/legislacion/eli.php`:

| Vía | Peticiones | Bytes | Da |
|---|---:|---:|---|
| `/eli/sitemap.xml` + `sitemap{0,1,2}.xml` | **4** | 11,6 MB | **103.070** URIs ELI resolubles, cada una con `lastmod`, 18 jurisdicciones (`es` + 17 `es-*`), 1851→2026 |
| `/eli/eli-update-feed.atom` | **1** | 187 KB | ventana rodante de ~8 semanas de cambios — el diario se autocura si falla un cron un mes |
| `/buscar/boe.php` (sección + rango de fechas, 2.000/página) | **40** | ~90 MB | id, fecha, nº de boletín, sección, departamento, **título**, y el **total exacto por adelantado** |
| `/rss/boe.php?s=1` | 1 | 5 KB | los ids de Sección I de hoy |

Verificado por mí ahora mismo: `/eli/sitemap.xml` → 200, sitemapindex de tres ficheros, y
`/eli/eli-update-feed.atom` → 200, 186.852 B. Y `{eli_uri}/dof/spa/xml` devuelve **el mismo
XML del diario** que `xml.php?id=`, byte a byte en el caso comprobado — así que el índice te
da directamente la URL de fetch.

**El sitemap está verificado por mí, entero.** 3 peticiones: 50.000 + 50.000 + 3.070 =
**103.070 `<loc>`, todas únicas, todas con `<lastmod>`**, 18 jurisdicciones (`es` 93.172 +
17 `es-*`), **8.920** entradas `/corrigendum/`, rango 1851→2026, 1.126 anteriores a 1979.

**Pero el sitemap no es la población de Sección I, y esto no lo planteó nadie.** Quitando
los corrigenda quedan **94.150 normas base**, y su reparto por tipo ELI es
`res` 31.142 · `o` 25.681 · `rd` 17.772 · `l` 8.745 · `ai` 4.913 · `lf` 1.036 · `lo` 396.
Las Resoluciones y Órdenes son 56.823 de las 94.150 y **la mayoría se publica en Sección III,
no en I**. O sea: el sitemap es el corpus *identificado con ELI*, que solapa con Sección I
—95,9 % de concordancia a nivel de título sobre 1.582 disposiciones numeradas de tres
años— pero **no es el mismo conjunto**: incluye material de Sección III y excluye las
resoluciones judiciales, que no tienen ELI.

Indexar desde el sitemap y filtrar después por el campo `seccion` del documento traído
funciona y es gratis en peticiones de índice, pero paga el filtro en **~26.000 fetches de
documento fuera de alcance** (≈1,8 h y 760 MB tirados). El buscador filtra por sección **en
el servidor**, así que no hay desperdicio:

| Diseño | Peticiones de índice | Fetches de documento | Desperdicio |
|---|---:|---:|---:|
| Barrido de sumarios (el original) | 14.926 | 68.458 | 0 |
| Sitemap solo, filtrando al traer | **4** | 94.150 | **~26.000** |
| **Buscador por sección + sitemap para `lastmod`** | **44** | **68.458** | **0** |

**Recomendación: los tres, cada uno para lo que sirve.**

- **Índice del bootstrap: `/buscar/boe.php` filtrado por sección** (40 peticiones). Da el
  **total exacto por adelantado** —así el run sabe qué significa «completo» antes de
  empezar, que el barrido sólo aprende como subproducto cuatro horas después—, el título, el
  departamento y la fecha. Validado contra la API del sumario en 3+1 días elegidos
  independientemente: **6 vs 6, 20 vs 20, 5 vs 5, y 87 vs 87** sobre una ventana contigua de
  dos semanas. Cero ítems en un lado y no en el otro.
- **`lastmod` y clave de shard: el sitemap** (4 peticiones), unido por la URI ELI. El
  segmento de jurisdicción (`es`, `es-ct`, `es-nc`, …) **es exactamente el reparto de
  directorios que el repo ya tiene**, así que el shard sale gratis; y `lastmod` en las
  103.070 entradas da detección de cambios, que el barrido no tiene.
- **Diario: el Atom** (1 petición) además de la llamada al sumario que `daily.py` ya hace.
  Ventana rodante de ~8 semanas, o sea que un cron caído un mes se autocura — el barrido no
  tiene ese margen.
- **Plan B: el barrido de sumarios**, que es el diseño original y ya está costeado.

Y las tres cosas que hay que saber de las superficies elegidas, medidas:

- **El buscador es HTML y no está documentado.** Su markup puede cambiar. La mitigación es
  barata y va en el diseño: **contrasta los ids parseados contra el total `de N` que la
  propia página declara**, y si falla la aserción, cae al barrido para esa ventana. El token
  `id_busqueda` es opaco y de TTL desconocido (probado sólo a 3 peticiones y ~5 s), así que
  **ventana por años**: acota el daño a una ventana y la recuperación a una petición.
- **El sitemap va con retraso.** Se regenera con cadencia (parece mensual: su `lastmod` es
  del 1-sep y la entrada más nueva de `sitemap2` del 5-ago) y el Atom ya traía 9 URIs que no
  estaban en él. Nunca te fíes del sitemap para las últimas semanas.
- **Un artefacto histórico de la sección.** Filtrando `dato[0][1]=1` en 1985 salen filas
  etiquetadas **«V. Comunidades Autónomas»** (178 de 2.000) junto a «I. Disposiciones
  generales» (1.703) y el suplemento del TC (119). La codificación de secciones del BOE **no
  es estable entre eras**: «sección I» en 2014 y en 1985 no son el mismo conjunto, y el
  total de 78.908 incluye esas filas de la sección V antigua. Los tres días de contraste
  (1979, 2000, 2025) casaron exactos con la API del sumario, así que es una etiqueta y no
  una fuga del filtro — pero un barrido que dé por fijo el vocabulario de secciones
  clasificará mal los años 80.

### 3.3 El coste real, y dónde estaba mal contado

El titular «#66 cuesta 14.926 peticiones y 1 hora» es el coste **del descubrimiento**. El de
la función es otro: no hay endpoint masivo del diario, así que es un `xml.php` por acto.

| Fase (corte 1979, Sección I) | Peticiones | Bytes |
|---|---:|---:|
| Descubrimiento consolidado | 2 | 16,0 MB |
| Descubrimiento no consolidado (buscador, 40 + sitemap, 4) | **44** | ~102 MB |
| Textos consolidados (`/texto` × 12.387) | 12.387 | — |
| **Documentos del diario (`xml.php` × 68.458)** | **68.458** | **~2,0 GB** |
| **Total** | **~80.890** | **≥2,1 GB** |

**4,8 h a 4 r/s**, 22 h a 1 r/s. El descubrimiento se abaratraba 3.700×; la función cuesta
5× más de lo que decía el titular. Lo que hay que hacer resumible y cacheable es la mitad
caravanera —el fetch por documento—, no la barata.

### 3.4 Config, y qué se borra

```yaml
  es:
    source:
      # ... conexión, sin cambios ...
      search_url: "https://www.boe.es/buscar/boe.php"          # índice del bootstrap
      eli_sitemap: "https://www.boe.es/eli/sitemap.xml"        # lastmod + clave de shard
      eli_update_feed: "https://www.boe.es/eli/eli-update-feed.atom"   # diario
      earliest_publication_date: "1979-01-01"   # ver §1; la fuente llega a 1960-09-01
      summary_sections: ["1"]                   # sustituye a `rangos`; ver §7 sobre "T"
```

- `normas_fijas` **no vuelve**: era una muleta de la fase 2 y el catálogo entero son 2
  peticiones.
- `rangos` **no vuelve**: filtrar por rango era el eje equivocado. El eje es la **sección**,
  que es lo que la fuente declara, y el rango sólo sirve para el descarte de §2.
- `_LEGISLATIVE_SECTIONS = {"1", "1A", "T"}` en `sumario.py:44`: **`1A` no existe.** Cero
  apariciones en 131 + 25 + 18 sumarios de 1970 a 2026, y el eje `ORIS` del buscador no lo
  ofrece. Está muerto.
- `catalogo.py` se borra: `iter_fixed_norms` pierde su clave y `iter_norms_from_summaries`
  se convierte en el barrido cacheado *si se decide* mantenerlo como plan B del sitemap.
- **`create(source: dict)` lee las claves del dict**, como todos los demás países. Eso
  arregla el desajuste `Config`-vs-dict de #99 borrando la suposición en vez de fontanearla.

### 3.5 Dos cosas más que este diseño tiene que cambiar

1. **Quita el `if not repo.has_file(...): continue` de `daily.py::_commit_reforms`.** Es la
   causa medida de las 88 normas que faltan y seguirá costando ~130/año después de la
   reemisión. Una norma que el BOE consolida por primera vez años después de publicarse
   entra por la ventana de reformas sin fichero en el repo, y se tira.
2. **Pagina la ventana `from`/`to`.** Trunca en 10.000 con un **200 y sin ningún total,
   flag ni cabecera `Link`**. `from=20251201&to=20251231` devuelve 10.000 cuando hay 10.017.
   El margen «770× el volumen diario» no existe: el BOE re-selló 9.980 normas en una semana
   de dic-2025, y un backfill tras una caída aterriza justo ahí.

---

## 4. ¿Alcanza lo no consolidado el estándar de fidelidad, y desde qué año?

**Sí en estructura, no en un 5 % de los actos, y la pregunta del año está mal planteada.**

**Estructura: sí, y es reutilizable tal cual.** El XML del diario usa **el mismo vocabulario
`<p class="…">` que el consolidado**. El despacho de párrafos actual (`_parse_p`,
`_table_paragraph`, `_parse_blockquote`, `_image_paragraph`) renderiza sin tocar una línea:
**0 de 22.318 unidades de texto perdidas en 76 actos**, 0 etiquetas HTML residuales, 0
mojibake. Y donde `class="articulo"` está, está bien: recuperación del árbol de artículos
100 % en 6 de 10 actos comprobados contra los preceptos del consolidado, 99,2 % y 98,9 % en
otros dos.

**Lo que no llega, en orden de gravedad:**

1. **El 25,4 % de las páginas de gaceta de una muestra son mapas de bits.** Cuatro actos de
   76 (5,3 %) llevan el **2,1 %** de su texto oficial; el resto son 405 PNG. Abrí uno:
   `disp/2014/315/13617_5290.png`, 2126×2493 px, y **es el ANEXO I como prosa jurídica
   ordinaria** — epígrafes en negrita, lista de letras, nombres de perfil con superíndices.
   No es una figura. `BOE-A-2014-13617` son 198 páginas oficiales y nuestro render son ~25
   líneas más 196 enlaces a imagen. El peor caso es **2014**, no 1975. Y **ya está
   embarcado**: 1.400 de los 8.690 ficheros de `es/` tienen ≥1 imagen, y en 20 de ellos más
   del 30 % de las líneas no vacías son enlaces a imagen (`BOE-A-2020-17283`: 180 de 274).
   Ninguna superficie —ni el XML ni el HTML del BOE— tiene ese texto; sólo el PDF.
2. **Dos actos de 60 salen con CERO encabezados.** `BOE-A-2007-11450` y `BOE-A-2008-10206`
   usan una familia de clases heredada en mayúsculas (`ATEXTO_NORMAL`,
   `RBF_SFRANySIG_ARTICULO`, `FIRMA_MINISTRO`) que no está en el mapa; el 100 % de sus
   párrafos cae a texto plano. No es un lote de un día de 2005 como parecía: son 2007 y
   2008, ministerios distintos, y otros 3 actos del 2006-11-30. El mismo
   `BOE-A-2007-11450` publicado tiene 10 encabezados porque viene del consolidado.
3. **150 centinelas del propio BOE se filtran al texto**: `[precepto]`, `[encabezado]`,
   `[ignorar]`, `[firma]`, en el 25 % de los documentos. Salen literales:
   `###### [precepto]Primera.`. No existen en la superficie consolidada. Y son, a la vez,
   **la única señal de tipo de bloque que tiene el diario**: consumidos arreglan gratis el
   encabezado de grupo que hoy se pierde; ignorados son 150 artefactos por 60 documentos.
   `[ignorar]` es la fuente diciendo «este párrafo no forma parte del acto» — 20 párrafos en
   la muestra — y **necesita una decisión, no un default**.
4. **`class="articulo"` no significa «artículo», significa «unidad numerada»**: 219 párrafos
   en 25 de 40 documentos que empiezan por *Disposición adicional/transitoria/final* llevan
   la misma clase. Y el encabezado de grupo que los desambigua (`DISPOSICIONES ADICIONALES`)
   va en `<p class="capitulo">` a secas, que **no está mapeada**. Resultado en la
   Constitución renderizada desde el diario: **ocho H6 con el mismo texto** (`###### Primera.`
   ×2 …) y el encabezado que los separaba degradado a prosa. Los anclas se generan del texto
   del encabezado, así que es un generador de colisiones.
5. **Cero `<a>` en el diario** (0 en 60–76 documentos). Las referencias cruzadas sólo
   existen en `<analisis><referencias>`. El corpus mixto tendrá enlaces en la mitad
   consolidada y ninguno en la otra.
6. **Los organicos vienen cinco veces.** `BOE-A-2026-10881` trae el mismo acto en
   castellano, euskera, catalán, gallego y valenciano dentro de un `<texto>`: el castellano
   es el **22,3 %**, multiplicador **4,47×**. Detectable por el `centro_cursiva` que abre
   cada traducción y por los `url_pdf_*` del `<metadatos>`. Decídelo a propósito: son los
   documentos más leídos del corpus.

**«Desde qué año» no tiene respuesta como año, y esto es un cambio de plan.** Tres sondas
dieron tres suelos —1984, 1975 y 1835— y las tres se refutaron:

- Hay XML plenamente usable en **todos** los años de 1889 a 1974: 20 de 20 documentos
  poblados, el Código Civil de 1889 con 639.684 caracteres y 1.992 `<p class="articulo">`.
- Hay `<texto/>` **vacío** en 1981 y 1984 — `BOE-A-1981-50082` y `BOE-A-1984-50024`, los dos
  Reales Decretos, los dos con el título terminando en *(Conclusión.)* / *(Continuación.)*.
- En un mismo día de 1970, del mismo Sección I, **5 de 14 tienen texto y 9 no**.
- La tasa post-1975 es **94,4 %** (34/36 en días completos), no 100 %.
- El `txt.php` oficial de los vacíos también viene vacío: el texto no existe en ninguna
  superficie HTML, sólo en el PDF. **No hay estado intermedio** de «cuerpo escaneado»: o
  texto completo o nada.

Por qué las sondas se contradijeron, y merece saberlo porque es el patrón: la que dijo 1835
muestreó documentos que **también estaban consolidados**; el BOE retro-digitalizó texto
sólo de lo que consolidó. Y por debajo de 1975 el BOE cargó ~2.000 actos/año en una
secuencia baja de ids y el resto en un bloque alto, así que un muestreo por sumario ve un
acantilado que es del universo de documentos, no del texto.

**Consecuencia: fuera el suelo por año, dentro la puerta por documento** (§2, paso 4). Es
gratis —el documento ya está en la mano—, exacta, y un suelo en 1975 aplicado al
descubrimiento **habría tirado 286 leyes ya publicadas, entre ellas el Código Civil y la Ley
Hipotecaria**.

**Recomendación:** sí, adelante, con la puerta de texto y la de densidad, y **marcando** los
actos de baja densidad en el frontmatter (un `text_completeness` o equivalente) en vez de
descartarlos en silencio. Un fichero que dice «esto son 198 páginas de las que tengo 25
líneas» es honesto; uno que no lo dice, entre 68.000, es el defecto que nadie encuentra.

---

## 5. El override de `text_state` concreto

**`TEXT_STATE["es"] = TextState.AS_ENACTED`**, y el parser promociona las consolidadas a
`POINT_IN_TIME` por norma. Espejo exacto de `pt`, en dirección contraria.

```python
# countries.py
# BOE consolidates 12,387 norms and publishes everything else as enacted. The
# country default is the majority; the parser promotes the consolidated ones
# back to POINT_IN_TIME per norm.
"es": TextState.AS_ENACTED,
```

**Lo primero que hay que saber es que la elección es invisible en la salida.**
`frontmatter.py:70-74` sólo escribe la clave cuando el estado no es `POINT_IN_TIME`, así que
las dos opciones producen ficheros idénticos byte a byte. Se decide por el modo de fallo:

| | fichero consolidado | fichero no consolidado |
|---|---|---|
| A — `es` fuera de `TEXT_STATE`, el parser pone `AS_ENACTED` a lo no consolidado | *(sin clave)* | `text_state: "as_enacted"` |
| B — `es: AS_ENACTED`, el parser promociona lo consolidado | *(sin clave)* | `text_state: "as_enacted"` |

**B**, por tres razones:

1. **Dirección del fallo.** Si la decisión por norma se salta alguna vez —una ruta nueva, un
   fetch sin XML del diario, un re-parse desde el JSON cacheado que perdió el override—, A
   publica en silencio `point_in_time`, que es la afirmación **más fuerte** del spec, sobre
   un cuerpo que es un texto de 1979 sin reformar. B publica `as_enacted`, que **infravalora**
   un fichero consolidado. Infravalorar se recupera; sobreafirmar es lo que pone una ley
   equivocada delante de un abogado. `storage.py:223-226` ya protege el round-trip por este
   mismo motivo y su comentario nombra el mismo peligro.
2. **Fallo ruidoso.** Con B, una promoción rota se ve como 12.387 ficheros **ganando** una
   línea en un diff. Con A, una democión rota no se ve como nada.
3. **La regla que ya está escrita en `countries.py`**: «el default del país es la mayoría».
   Con el corte de 1979, lo no consolidado es ~5× lo consolidado.

**La condición exacta que lo voltea** — y no es un test, es un hecho que el parser ya tiene:

> `text_state = POINT_IN_TIME` si y sólo si la norma se construyó desde
> `/api/legislacion-consolidada/id/{id}/texto`. En cualquier otro caso, el default del país.

En `es`, a diferencia de `pt`, las dos superficies son **endpoints distintos con esquemas
distintos**: una norma consolidada son bloques con sellos `<version>`; un acto no consolidado
es una tirada plana de `<p>` dentro del `<texto>` del diario. Y no hay tercer caso:
`/metadatos` y `/texto` concuerdan 28/28, así que un acto tiene los dos o ninguno. La rama
la decide **qué endpoint contestó**, antes de llamar al parser.

Dos formas mecánicas de la misma condición, las dos verificadas:

| Dónde | Condición | Coste | Verificado |
|---|---|---|---|
| descubrimiento / bootstrap | `identificador in catalogue_ids` | 2 peticiones para todo el país | 79/79, 41/41, 0 FP, 0 FN |
| parser, con el XML del diario en mano | `<estado_consolidacion codigo> ∈ {"3","4"}` | 0 peticiones extra | 419/420 a n=420 — **1 desacuerdo**, ver §8 |

**Dónde va en el fetcher.** `parse_metadata` (`fetcher/es/metadata.py:243`) es el **único**
constructor de `NormMetadata` para `es`, con tres llamantes (`fetch.py::fetch_one`,
`daily.py::_commit_reforms`, `parser.py::BOEMetadataParser.parse`), y hoy no toca
`text_state`, así que todo hereda el default. Para la mitad consolidada es **una línea**:
`text_state=TextState.POINT_IN_TIME` en la llamada a `NormMetadata(...)` de
`metadata.py:334-350` — espejo de `pt/parser.py:827`+`:856`.

Para la mitad no consolidada **no hay ruta de código**, y eso es el trabajo real. No es un
flag en la función existente, es una hermana:

| qué | dónde |
|---|---|
| construir el set de ids del catálogo una vez | `fetcher/es/catalogo.py` — el bucle de paginación duplicado en `fetch.py:110-131` y `:200-221` se muda aquí |
| decidir la superficie por id | `fetcher/es/discovery.py::BOEDiscovery` — devuelve id + superficie, como `pt/bootstrap.py` separa `published` de `consolidated` |
| metadatos de una consolidada | `metadata.py::parse_metadata` — añadir `text_state=POINT_IN_TIME` |
| metadatos de una no consolidada | **nuevo** `metadata.py::parse_diario_metadata(diario_xml, id_boe)` — no pone **nada**: ahí está la gracia de elegir `AS_ENACTED` de default |
| cuerpo de una no consolidada | **nuevo** — `parse_text_xml()` devuelve **0 bloques** sobre un XML del diario, porque itera `root.iter("bloque")` y no hay ninguno. Sin un despacho aparte, la ruta no consolidada emite ficheros vacíos en silencio |

**Qué hay que pasar de una función a otra: nada.** Ese es el argumento de poner el default en
`AS_ENACTED`: la ruta nueva no fija ningún `text_state` y acierta; sólo la consolidada, que
por construcción *sabe* que lo es porque acaba de parsear un `/texto`, pone el override.

**`last_amendment`**: sale de `<analisis><referencias><posteriores><posterior>` del mismo
documento del diario, cero peticiones extra. La maquinaria ya existe —
`pipeline.py:172-186` `_with_last_amendment` lo pone en cada commit no primero de una norma
`AS_ENACTED`, y `storage.py:225` lo round-tripea — así que lo que hay que construir son las
filas `Reform` a partir de los `<posterior>` amendatorios, como `pt/amendments.py` hace con
`eli:amended_by`. Tres trampas medidas:

- **`<posterior>` no lleva fecha.** Sólo `referencia`, `<palabra>` y `<texto>`; la fecha está
  dentro de la prosa (*«por Ley 3/2010, de 21 de mayo»*). Y `Reform` necesita `date`.
- **Hay que filtrar por verbo.** `SE DICTA DE CONFORMIDAD` (341), `SE DICTA EN RELACIÓN`
  (195) y `SE DESARROLLA` (48) **no son reformas**: es el mismo hecho que #106.6 midió como
  «1 de cada 4 commits `[reform]` es una cita», aquí en la fuente antes de que exista commit.
- **El 12,5 % de las referencias no son `BOE-A`** (`BOJA-b-…`, `BOIB-i-…`, `BOCT-c-…`), y
  `legalize verify` (`cli.py:965-988`) reporta un `last_amendment` irresoluble como WARN.

### El coste de que cada ley se autodeclare

Medido sobre `countries/es` en `origin/main`: **12.299 ficheros, 0 con clave `text_state`,
0 con `last_amendment`.** Confirmado.

Pero hay un matiz que cambia el tamaño de la reescritura y merece que lo decidas explícito:

- **Con el emisor tal como está**, un `es` mixto deja el frontmatter de las 12.299
  consolidadas **igual en este aspecto** — siguen sin clave, porque son point-in-time. Sólo
  los actos nuevos ganan `text_state: "as_enacted"`. (Se reescriben igual por el sharding,
  pero no *por esto*.)
- **Si «cada ley declara el suyo» es literal**, el emisor tiene que escribir la clave
  siempre, y eso añade `text_state: "point_in_time"` a **12.299 de 12.299** ficheros — y al
  corpus de todos los demás países que comparten el emisor (`fr`, `de`, `at`, `se`, `pt`,
  `ie`, …). **Es una decisión de 34 países, no de `es`.**

Verificado contra el spec tal como está implementado: la ausencia **sí** significa
`point_in_time` (`models.py:100-105`, `countries.py:56`, `frontmatter.py:70-74`,
`cli.py:1198` lo lee como `front.get("text_state") or "point_in_time"`). Y no hay texto
v0.4 que lo cambie: `text_state` sigue documentado como v0.3 en todas partes; lo que v0.4
toca es directorios, fechas, historia e identidad git.

**Recomendación: no cambiar el emisor.** El corpus mixto ya es autodescriptivo — un fichero
sin clave es point-in-time por spec — y cambiarlo reescribe seis corpus para declarar un
default que ya declaran. Si aun así lo quieres literal, que sea una decisión aparte y
declarada para los 34 países, no un efecto colateral de `es`.

---

## 6. Cifras que los verificadores DISPUTARON — **no aptas para decidir**

| Afirmación de la sonda | Lo que midió el verificador | Por qué difieren |
|---|---|---|
| Sección I + T 1979→hoy = **121.896** (CI 88.493–155.298) | **90.603** exacto | Extrapolación de 30 días × 14.926. Dos verificadores independientes, con consultas distintas, dan la misma cifra exacta al dígito |
| Repo final «~122.000 ficheros, 10×» | **~91.000, 7,4×** (I+T) / **~80.800** (sólo I) | Se arrastra de la anterior |
| «El sumario diario es el único índice. Nada más enumera» | `/eli/sitemap.xml` = **4 peticiones**; `/buscar/boe.php` = 40 | Probó `/sitemap.xml` en la raíz (404) y `robots.txt` (sin directiva) y generalizó. El sitemap está en `/eli/` y se anuncia en `/legislacion/eli.php`, una página que no se abrió |
| Descubrimiento = 14.926 pet. / 2,03 GB / 1 h | **4 pet. / 11,6 MB / ~4 s** | Idem |
| «Coste total del bootstrap: 14.928 peticiones» | **~91.000** para el mismo alcance | El titular era el coste del *descubrimiento*; la tabla decía «discovery only» y el titular no |
| Suelo del texto = **1975** | XML usable en **20/20** documentos de 1889–1974; `<texto/>` vacío en **1981 y 1984** | Muestreó sólo por sumario y sólo los primeros actos del día; el suelo es por documento, no por año |
| Suelo del texto = **1984** (otra sonda) | idem | Muestra de un día; el único acto de 1982 con texto era el único consolidado del día |
| «Texto completo desde 1835, 21/21» (tercera sonda) | Los 21 estaban **también consolidados** | El BOE retro-digitalizó sólo lo que consolidó |
| Fidelidad del diario = **identidad 1,0000** | **2,1 %** del texto del PDF oficial en 4 actos; **25,4 %** de las páginas de la muestra son bitmaps | Comparó el XML del BOE contra el HTML del BOE **generado desde ese mismo XML**, y nunca tocó el Markdown renderizado. La propia sonda lo nombró en su caveat 3 y dejó el titular |
| «Las imágenes son figuras, fórmulas y rúbricas, no escaneos de página» | Una abierta: **2126×2493 px, el ANEXO I como prosa jurídica**; 405 así en 4 actos | Se contó `<img>`, no se abrió ninguna |
| «0 etiquetas HTML residuales» | **77** en 46 renders; **159.677** en el corpus publicado (`<small>` 94.680, `<sub>` 34.518, `<sup>` 30.479) | Cierto en sus 3 actos; falso como afirmación general |
| Cuota consolidada de Sección I, **2020s = 32,3 %** → «dos de cada tres sin consolidar» | **20,0 %** y **19,0 %** por el modelo de la propia sonda → **cuatro de cada cinco** | Sus días de los 2020 se concentran en 2020 y 2023, los dos años de mayor consolidación (2020: 52,1 %, 2025: 3,3 %). Y hay sesgo medido de agrupación: los días grandes de Sección I están al 13,5 % y los pequeños al 22,6 % (z=2,32, p=0,020) |
| Cuotas por década (2000s 8,7 %, 2010s 18,8 %) | 30,8 % y 34,5 % en otra muestra; 16,3 % y 28,6 % por modelo | Tres rutas, hasta 3,5× de diferencia. **Ninguna forma de la curva está establecida** |
| No consolidado = **88,4 %** de Sección I | **78,4 %** · **73,0 %** · **82,2 %** en tres muestras | Su denominador (112/28 días) mete 4 días que había traído *para otra medición* (la bisección de digitalización pre-1984), elegidos por ser antiguos. Su propia caché dice 84,0 % sobre 75. Agregado ~80 %, y **la cuota es fuertemente dependiente de la era y bajando** (88,3 % pre-2005 → 67,9 % en 2025-26) |
| Sección I = **4,00 ítems/día**; «se está encogiendo», 2,07/día en 2025-26; estado estable 1,4 actos/día | **8,71** · **5,88** · **7,00**/día | Su escalera de 2025-26 tiene **5 de 14 días con cero ítems**: el receso legislativo de agosto. La métrica está sobredispersa (0–26/día) y **ninguna muestra de 20-30 días la fija**. Irrelevante ahora: los totales son exactos |
| Lag de consolidación: mediana **1,5 d**, «decidido a día 30» | Mediana **12 d**; sólo el **44 %** en ≤7 d; **33 %** después del día 30 | Su instrumento era `fecha_actualizacion`, y **el 80,6 % del catálogo lleva un re-sellado masivo de dic-2025** (9.980 filas en 5 días, con años de publicación de 1851 a 2025). Su única fila limpia era «publicadas en los últimos 30 días», que por censura a derecha **no puede** exhibir un lag de 30 |
| Puerta de frescura a **30 días** | **180 días** (error residual 3,4 % vs 33,3 %) | Se arrastra de la anterior |
| «El rango basta» para las correcciones | **11/12** y **8/9**; la `<palabra>` da 12/12 | `BOE-A-2011-20653` es corrección con `rango 1370` |
| Conjunto de descarte `{1590, 1240, 63}` completo | Falta **1250 Auto** (`BOE-A-2004-13466`) y **41 Nota Diplomática** sin mapear | n=1 cada uno, pero el arreglo es gratis |
| «Las sentencias del TC no están en Sección I» | Las *sentencias* no; los actos **procesales** del TC sí — **10 de 13** judiciales, 7 en un solo día | Quitar la sección T no saca al Tribunal del barrido; lo que lo saca es `rango 63` |
| «El árbol de artículos se recupera de `@class` solo, sin regex» | **23,0 %** de lo que la regla emitiría (78 de 339) está articulado y sale sin un encabezado — medido en el dry-run de §8, no 2 de 60 | La sonda contó clases sin leer el texto; el verificador leyó el texto pero sobre 60 documentos de un solo día por año |
| Defecto D1 de sangrado: **79.176** líneas | **115.948** (`^    \S` no cuenta `sangrado_2`, que emite ocho espacios) | Regex incompleto |
| Residuo indecidible = **27,0 %** | 27,6 % forzando el encaje; **32,7 %** si los boletines paramétricos cuentan como singulares; y **23,5 %** de la población no encaja en ninguna categoría sin juicio | El número es la salida de una elección definicional, no una medida |
| `A(2026) = 28.801` | **18.508** medido | Anualizó un día de agosto para un año que va por septiembre |
| Consolidadas por corte: 11.713 / 9.058 / 6.159 | 11.958 / 9.288 / 6.335 desde el catálogo | Diferencia = las 245 con id autonómico. Restarlas es correcto, pero el artefacto no lo decía |

### Y lo que SÍ es seguro (reproducido por al menos dos muestras disjuntas)

- Catálogo = **12.385** (12.387 hoy; ~8 entradas/día de churn), **2 peticiones**, 16,0 MB.
  Cinco volcados independientes, tres paginaciones, y un segundo eje de enumeración
  (ventanas de `fecha_actualizacion`): mismo conjunto, 0 duplicados, 0 huecos.
- **11.715** consolidadas con id `BOE-A` publicadas ≥1979 (contado por mí hoy).
- **86** normas del catálogo sin fichero en el repo, **0** huérfanos, y la causa localizada.
- **89,2 % / 90,2 % / 95,0 %** de las consolidadas están en Sección I → la constante 0,892.
- El oráculo de pertenencia: **79/79** y **41/41**, cero falsos positivos y negativos,
  incluido el caso más afilado disponible (cuatro Leyes Forales consecutivas del mismo día:
  16 y 17/2010 consolidadas, 18 y 19/2010 no, porque estas dos sólo modifican).
- `<estado_consolidacion codigo>` del XML del diario: **419/420** de acuerdo con el catálogo
  con el test positivo. Flag por acto a coste cero, pero **no exacto**: el 48/48 y el
  159/159 que se reportaron no aguantan a n=420 (§8).
- Los domingos no se publica y **todos** los días no domingo sí: 0/8 y 0/5 domingos con 200;
  18/18 y **26/26** no domingos con 200, incluida una tirada contigua de Navidad y Año Nuevo.
- **`fecha_vigencia` está en el 100 % de los sellos `<version>`** (11.379/11.379) y difiere
  de `fecha_publicacion` en el **96,4 %**, mediana 22 días, p90 366.
- Pasar a `effective_date` mueve el **86,6 %** de las fechas de commit y añade **+5,5 %**.
- `bloque@fecha_caducidad`: 1.281 de 9.723 bloques (13,2 %) en 12 de 53 documentos, de los
  cuales **622 (6,4 %) publican texto derogado como si estuviera vigente**.
- **0 mojibake, 0 caracteres de control, 0 NBSP** en los 12.299 ficheros. La limpieza funciona.
- El árbol de artículos, donde `class="articulo"` existe, es **exacto**: 100 % en 6 de 10
  actos comprobados contra los preceptos del consolidado.
- **0 `<a>`** en la superficie del diario (60 y 76 documentos).
- Las clases de `_STRIP_CLASSES` están **siempre** dentro de un `<td>`: 10.964/10.964 y
  94.310/94.310. El guardián nunca ha borrado una celda.

---

## 7. Preguntas abiertas, ordenadas por lo que costaría equivocarse

**1. El alcance: qué actos y hasta dónde. Equivocarse = un segundo rebuild completo.**
El residuo (≥27 %, techo 33 %) y la sección T (11.695 ficheros) son ±35.000 ficheros sobre
un repo de 66.000. Y #66 ya avisa: *un rebuild que aterrice sin esto no puede recogerlos
después sin volver a reconstruir.*
→ **Lo más barato que lo zanja: haz el barrido ANTES de decidir.** Las 4 peticiones de
descubrimiento y los ~68.000 fetches son idempotentes y cacheables en disco; producen el
censo exacto —rango, `<palabra>`, longitud de `<texto>`, densidad por página, clase de
`@class`— **como subproducto**. Decides sobre datos reales en vez de sobre un 27 % que es la
salida de una definición, y el fetch no se repite. Es la mitad caravanera del trabajo y no
depende de ninguna de las decisiones pendientes.

**2. Los actos sustituidos por imágenes. Equivocarse = publicar 198 páginas como 25 líneas,
en silencio, dentro de 68.000.** 5,3 % de los actos, 25,4 % de las páginas de gaceta, y el
peor caso es 2014. Ya embarcado en 20 ficheros del corpus actual.
→ El detector es `chars(<texto>) / páginas`, **cero peticiones**, sobre el fetch cacheado.
Decide si excluyes, marcas en frontmatter o embarcas — pero no que pase por defecto.

**3. `[ignorar]`. Equivocarse = publicar texto que la fuente marca como andamiaje
superado, sin marca ninguna.** 20 párrafos en 60 documentos; es la fuente hablando.
→ Lo zanja leer los 20 y decidir. Una tarde.

**4. ¿Cada ley declara su `text_state`? Equivocarse = reescribir el corpus de 34 países
para declarar un default que ya declaran.** Con el emisor actual el corpus mixto ya es
autodescriptivo; cambiarlo es una decisión transversal.
→ Recomendación en §5: no cambiarlo. Si lo cambias, que sea su propio PR y su propio
reproceso, no un efecto colateral de `es`.

**5. Los fragmentos `(Continuación.)`. Equivocarse = varios cientos de ficheros tronco.**
n=2 confirmados (1981, 1984, y un tercero de 1986), detectables por `<texto>` vacío + id
fuera del bloque del día + título terminado en `(Continuación.)`/`(Conclusión.)`.
→ La puerta de texto ya los para. Lo que falta es decidir si se **cosen** al acto cabeza —
y eso sólo se puede dimensionar con el censo del punto 1.

**6. Las familias de clases heredadas. Equivocarse = unos miles de leyes sin árbol de
artículos, verdes en cualquier check actual.** Medido en §8: **23,0 %** de lo que la regla
emitiría, concentrado en 1984–2005 y nulo desde 2009. Ya no es un riesgo estimado, es una
tasa, y exige un respaldo por regex además de la instrumentación.
→ **Instrumenta el reproceso**: cuenta cada `@class` no mapeada y **falla** cualquier
documento que termine con cero encabezados. Barato, y es lo único que ve este fallo. El
contra-oráculo por acto también es gratis: comparar el número de `class="articulo"` contra
el de preceptos del consolidado allí donde existan las dos superficies.

**7. La sección T (Tribunal Constitucional). Equivocarse = 11.695 ficheros que no son
normas, o perder las anulaciones.** Con `_LEGISLATIVE_SECTIONS` incluyendo `"T"`, un barrido
se traga la sección entera. Pero una sentencia del TS que **anula un reglamento** es
exactamente el evento para el que existe la tabla `reforms`: descartarla en silencio pierde
la anulación.
→ Recomendación: sección I sola en el corpus, y las anulaciones a `reforms` vía
`references_*`, no como ficheros de ley.

**8. Las versiones en lenguas cooficiales. Equivocarse = 4,47× de tamaño en las leyes
orgánicas, que son las más leídas.**
→ Detectable desde el catálogo sin un solo fetch de texto: `url_pdf_catalan` /
`_euskera` / `_gallego` / `_valenciano` no vacíos. Cuéntalo antes de decidir. Y el mismo
apartado tiene un hermano sin decidir: los PDF oficiales traducidos cubren el **24,5 %**
(catalán), 19,3 % (gallego), 4,6 % (valenciano) y 2,9 % (euskera) del corpus actual, y no
publicamos nada de ellos.

**9. Qué pasa cuando un acto `as_enacted` se consolida semanas después.** El cuerpo se
sustituye y la clave `text_state` desaparece. Es un evento con forma de `[reform]` legítimo,
**y el pipeline no lo modela**. Con la puerta de 180 días es raro en el bootstrap, pero es el
caso normal del diario.

**10. `fecha_disposicion` vs `fecha_publicacion`.** Divergen **hasta 13 años**: el
2011-12-31 hay 9 leyes vascas **de 1998** republicadas en el BOE. Cualquier cosa que
shardee, feche, ordene commits o nombre ficheros por año de publicación coloca una ley de
1998 en 2011. Dado que el orden por `Source-Date` ya es una clase de defecto conocida en
#106, decídelo antes del barrido.

**11. La numeración que Markdown roba.** 167.666 de 391.038 tiradas de lista ordenada
(42,9 %) en **9.396 de 12.299 ficheros (76,4 %)** no empiezan en 1 o no son consecutivas, y
CommonMark las renumera: la ley dice «3.» y la página muestra «1.». El fichero es fiel; el
render no. Es el mayor ítem de fidelidad del corpus actual y la reemisión es la única ocasión
barata.
→ Antes de tocarlo, comprueba si el renderer de legalize.dev ya lo suprime. Una ley con una
tirada que empiece en 3 lo dice en un minuto.

**12. `<sup>` / `<sub>` / `<small>`: 159.677 en el corpus embarcado.** O la prioridad 1 del
playbook lleva una excepción documentada, o la reemisión los convierte. Hoy es lo primero de
facto y no está escrito en ningún sitio.

---

---

## 8. Dry run: la regla ejecutada sobre 420 leyes reales

Todo lo anterior era medir la fuente. Esto es distinto: es **el diseño corrido de punta a
punta**, porque un diseño que nadie ha ejecutado no está validado. Lo que las sondas
produjeron sobre la regla de corte venía de clasificar a mano 63, 75 o 98 actos; lo de la
estructura, de 2 documentos en 60.

**Método.** 12 años repartidos 1979–2025, una petición de buscador por año para la lista
completa de ids de Sección I, muestra aleatoria con semilla de 35 por año → **420 actos,
todos HTTP 200**, traídos como XML del diario a 1 pet./s. Cada acto pasado por el
procedimiento de §2 y su cuerpo por el **despacho real del engine**, sin tocar una línea.
432 peticiones. Arnés y XML en `/Users/neli/.claude/jobs/5bf7ddf4/tmp/dryrun/`.

| Paso | Salta en | Tasa | Contra lo que se afirmaba |
|---|---:|---:|---|
| **3 — descarte** (rango ∪ `<palabra>`) | 75 / 420 | **17,9 %** | coherente con el 19,0 % y el 22,5 % de dos censos a mano |
| — que coge `<palabra>` y NO el rango | 3 | 0,7 % | confirma al verificador: el rango solo no basta |
| — que coge el rango y NO `<palabra>` | 32 | 7,6 % | el rango hace el grueso; hacen falta las dos claves |
| **4 — puerta de texto** | 6 / 345 | **1,7 %** | solo 1979 y 1984 → suelo por documento, no por año |
| **5 — puerta de densidad** | 4 / 420 | **1,0 %** | el 5,3 % del verificador venía de días elegidos por contenido difícil; 1,0 % es la tasa en muestra aleatoria |
| **oráculo** `estado_consolidacion` | 419/420 | **1 desacuerdo** | el 48/48 y el 159/159 **no aguantan a n=420** |
| centinelas `[precepto]`/`[ignorar]` en el render | 10 docs, 46 casos | **2,9 %** | menos que el 25 % de documentos que se reportó sobre 60 |

**Lo que rompe.** Dos cosas, y las dos estaban escritas como instrucción:

1. **El oráculo, ya corregido arriba en §2 paso 2.** `BOE-A-2001-3498` con
   `estado_consolidacion codigo="1"`. Mi condición `!= "0"` lo clasificaba mal.
2. **El fallo de estructura es del 23,0 %, no del 3,3 %**, y la causa no era la que se
   diagnosticó. Sobre los 339 actos que la regla emitiría como ley: 147 (43,4 %) salen sin
   ningún encabezado, y de esos **78 (23,0 %) tienen texto que abre párrafos con `Artículo` /
   `Art.` / `Disposición` y ni un `class="articulo"`**. Ejemplo verificado en el XML crudo:
   `BOE-A-1993-15903` (RD 819/1993) tiene **482 párrafos, todos `class="parrafo"`**, con
   `Artículo 1.` y `Artículo 2.` como párrafos planos. La familia de clases en mayúsculas —
   que era el diagnóstico del verificador — son otros 20 actos (5,9 %), todos de 2005, y los
   peores casos del 23 % **no** la llevan.

   El reparto, que es lo que lo hace manejable:

   | | n | con `class="articulo"` | articulado sin marcar |
   |---|---:|---:|---:|
   | Consolidadas | 53 | 52 (98 %) | **0 %** |
   | **No consolidadas** | 286 | 130 (45 %) | **27 %** |

   Y dentro de las no consolidadas, por año muestreado: **0 % en 1979**, luego **67 %
   (1984), 36 % (1989), 50 % (1993), 62 % (1997), 61 % (2001), 45 % (2005)**, y **0 % en
   2009, 2013, 2017, 2021 y 2025**. O sea: **el diario es sólido para 2009→hoy y para 1979,
   y hay que meterle un respaldo por regex para 1984–2005.** El mismo regex que detecta el
   problema recupera la estructura — encontró 96 artículos en el RD 819/1993 donde `@class`
   encontró 0 — así que el arreglo y el detector son la misma línea, y el detector
   (`parece articulado` ∧ `sin class="articulo"`) salta en el 23,9 % y es gratis.

**Lo que el dry run NO cubre**, para que no se lea como más de lo que es: ejercita los pasos
3, 4 y 5 y el despacho del cuerpo. No ejercita la puerta de frescura (haría falta actos de
menos de 180 días), ni el override de `text_state` (no hay código), ni `last_amendment`, ni
la ruta de commit, ni la decisión del residuo — que es política y ninguna regla la resuelve.
Y 420 de ~78.908 es el 0,53 %: las tasas por año descansan en ~25 actos emitidos cada una,
así que el orden es sólido y el segundo dígito no.

## Orden de trabajo que se deduce de todo esto

1. **#106.1 y #106.2** (horas). Ya estaban decididas y no cambian.
2. **El barrido, ya**, con el sitemap ELI y la caché permanente en disco. Es la mitad caras,
   es idempotente, no depende de ninguna decisión pendiente, y **produce el censo que hace
   decidibles los puntos 1, 2, 5, 6 y 8** de arriba.
3. **Decidir** el alcance sobre ese censo: residuo, sección T, densidad, lenguas.
4. **Código**: el despacho del diario, `parse_diario_metadata`, el `text_state` de §5, el
   `effective_date` de #106.2, `fecha_caducidad`, los códigos de rango que faltan (1676,
   1590, 1240, 63, 1250, 41, 1220), los nueve arreglos de render de `06-cobertura-formato.md`
   y la instrumentación de `@class` no mapeadas.
5. **Un solo rebuild**, sharded, con `legalize push` por rebanadas.
6. **Full-local sync obligatorio** después: cambian todos los shas.

Y un aviso sobre el paso 4 que sale de las mediciones: **`markdown.py`, `_tables.py` y
`get_block_at_date` son código compartido por 34 países.** Los arreglos de sangrado,
`<caption>`, cabecera fantasma de tabla, tablas anidadas y `effective_date` los tocan todos.
#106 ya lo advierte para `include_all` (Austria depende del fallback) y aquí vuelve a
aplicar: **re-mide at/fr/se/ee/cz/sk/uk/ar/pt antes de aterrizar cualquiera de ellos.**
