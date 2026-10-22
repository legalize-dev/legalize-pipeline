# Colombia — Step 0 rehecho con el playbook actual · decisiones

> **ESTADO: parado en el Paso 0, 2026-09-03.** La fuente está caída para todo el mundo desde
> el 2026-08-02, así que las sondas que la miden no se han ejecutado. Ninguna línea de código
> tocada, ningún commit, ningún fetch. `engine` limpio.
>
> **Para retomar:** ejecuta `python3 co-v2/probe-suin.py`. Si sale 0, SUIN contesta y lo
> pendiente está en §6. Si sale 1, sigue caída y no hay nada que hacer contra ella.
>
> **Lo que sí quedó medido, sin tocar SUIN:** el corpus publicado, el catálogo oficial del
> Ministerio y los sitemaps de SUIN recuperados del Internet Archive. Bastó para encontrar un
> defecto mayor que el que motivó la sesión.

---

## 0. Las cuatro decisiones

1. **No se lanza el workflow de sondas y no se levanta la VM de São Paulo.** SUIN no responde
   a nadie —ni a nosotros, ni a una red independiente, ni al Internet Archive, que llevaba
   1.855 capturas en julio y 0 desde el 2 de agosto—. Otra región no cambia nada. (§1)
2. **El descubrimiento se rehace sobre el índice, no sobre un barrido mejor acotado.** SUIN
   declara **24 sitemaps en su `robots.txt`** y el Ministerio publica el **catálogo completo
   en datos.gov.co**. 950.001 peticiones → **10**. (§2)
3. **La prioridad de `co` no es el timeout: es que faltan 17.087 normas, 10.477 de ellas
   posteriores a 2014.** El corpus publicado no tiene **ni un solo documento posterior a
   2014**, le faltan 8.480 de las 8.491 resoluciones y cinco clases documentales enteras están
   al 0 %. 8.692 de las que faltan están **vigentes**. (§3)
4. **El arreglo propuesto en #113 no habría arreglado esto.** Habría cerrado el ticket del
   coste dejando intacta la brecha de contenido, que es la que ven los usuarios. (§3.3)

---

## 1. La fuente está caída, y eso decide el resto de la sesión

Detalle y reproducción: **`01-fuente-caida.md`**. Arnés: `probe-suin.py`.

TCP conecta, TLS negocia, y no llega **ni un byte de HTTP** — en los dos puertos, con y sin
`www`, con HTTP/1.1 forzado, con `-k`, con UA de bot y de Chrome, y en el endpoint real
`viewDocument.asp`.

No es nuestra IP, y hay tres controles que lo dicen:

| Control | Resultado |
|---|---|
| `secretariasenado.gov.co` (IP colombiana, `200.7.106.227`) | **200** — la ruta a Colombia funciona |
| `r.jina.ai` (red independiente) | `ERR_EMPTY_RESPONSE` — mismo síntoma |
| Internet Archive, capturas por mes | jul **1.855** · ago **9** (días 1–2) · sep **0** |

La última captura con éxito es del **2026-08-02**. Un mes de silencio desde centros de datos
en EE. UU.

**Por eso no se levanta la VM.** `gcp_vm_fetch_protocol` sirve para geobloqueos —el caso de
InfoLEG—, y aquí la premisa no se cumple.

Queda **bloqueado**: densidad de ids por muestreo, frescura real, `text_state` contra el
documento, cobertura de formato contra el HTML, historial de versiones y el gate de calidad
letra a letra.

---

## 2. Rediseño del descubrimiento: 950.001 peticiones → 10

Detalle, tabla de población y negativos probados: **`02-descubrimiento.md`**.

`discovery.py:17` dice *"SUIN has no catalog API"*. Es falso, y **nuestro propio
`RESEARCH-CO.md` de abril ya decía lo contrario en la línea 13** — sin URL ni código de
estado, así que nadie pudo refutarlo en cinco meses.

**Hay dos índices y se complementan:**

| Índice | Peticiones | Qué da | Qué NO da |
|---|---:|---|---|
| 10 sitemaps por clase (declarados en `robots.txt`) | **10** | el `id` de cada documento, por clase | `lastmod`; la identidad tipo/número/año |
| Catálogo `fiev-nid6` en datos.gov.co | **1** | 89.366 normas con identidad, `vigencia`, `sector`, `entidad`, `subtipo`, `materia`, `art_culos` | el `id` de SUIN → no descarga |

El catálogo está en un host **que sigue vivo con SUIN caída** — de hecho es de donde salen
las cifras de §3.

**Diseño recomendado:**

```
discover_all:
    10 GET, uno por clase de LEGISLACIÓN, en la forma ?id=
    EXCLUIR cconstitucional / consejoestado / csuprema  ← jurisprudencia, 7.193+ documentos
                                                          fuera del alcance del corpus
    aserto: nº de ids del sitemap ≈ count(1) del catálogo por clase; fallar si no cuadra
    persistir la lista  ← el discovery_ids.txt que el workflow ya documenta y no existe
```

| | Hoy | Propuesto |
|---|---:|---:|
| Descubrimiento | 950.001 peticiones | **10** |
| Descarga | ~71.900 útiles de 950.001 | ~89.000, todas útiles |
| Pasada completa a 5,9 req/s | ~45 h | **~4,2 h** |
| ¿Cabe en 6 h? | No | Sí, sin margen — trocear por clase, que ya viene troceado |

**Dos avisos que no son opcionales.** (a) Los sitemaps **no llevan `<lastmod>`** (comprobado
en tres), así que dan el censo pero **no** detección de cambios: el incremental sigue sin
resolver y `discover_daily` no se arregla con esto. (b) Tres sitemaps son **sentencias, no
legislación**; tomar "todos" metería miles de documentos fuera de alcance — la misma trampa
de población que en `es` costó ~26.000 descargas.

---

## 3. El defecto que de verdad importa: el corpus se detiene en 2014

Detalle y método: **`03-brecha-de-corpus.md`**. Arnés: `catalog-gap.py` (2 peticiones, ninguna
a SUIN). Salida: `gap-2026-09-03.txt`.

### 3.1 La brecha

```
catálogo oficial                 : 89.366
ficheros publicados              : 71.900
FALTAN                           : 17.087   (19,1 %)
huérfanos (fichero sin catálogo) :     25   (0,03 %)  ← valida el criterio de unión
```

| Falta | |
|---|---:|
| posterior a 2014 | **10.477** |
| **vigente** | **8.692** |
| RESOLUCION | **8.480** de 8.491 (publicamos **11**) |
| CIRCULAR EXTERNA / DIRECTIVA PRESIDENCIAL / CIRCULAR / ACUERDO / INSTRUCCION ADM. CONJUNTA | **1.878 — el 100 % de cada clase** |

**El corpus no tiene ni un fichero posterior a 2014.** No es que se quedara obsoleto en abril
de 2026: nunca lo tuvo. Entre lo que falta están los decretos únicos reglamentarios
(1072/2015 Trabajo, 1078/2015 TIC, 1079/2015 Transporte) — lo primero que consulta cualquiera
que trabaje con derecho colombiano, y lo que no están recibiendo las dos organizaciones que
consultan **sólo** Colombia.

### 3.2 La causa, con el mecanismo

SUIN numera en **dos bloques**; `config.yaml` sólo visita uno (`1000000..1950000`):

| Clase | ids | Dentro | **Fuera — nunca visitados** |
|---|---:|---:|---:|
| decretos (1+2) | 66.090 | 61.823 | 4.267 |
| leyes | 11.347 | 10.429 | 918 |
| **resoluciones** | 6.139 | **0** | **6.139 (100 %)** |
| **circulares** | 898 | **0** | **898 (100 %)** |
| **acuerdos** | 121 | **0** | **121 (100 %)** |
| actos legislativos | 133 | 99 | 34 |
| **total medido** | **84.728** | **72.351** | **12.377 (14,6 %)** |

> **72.351 ids dentro del rango · 71.900 ficheros publicados · coinciden al 99,4 %.**

El bootstrap capturó exactamente lo que el barrido podía ver. Todo lo del bloque de los 30
millones —donde están las clases nuevas y los documentos recientes— **no se ha visitado ni una
vez**. Un solo mecanismo explica el corte en 2014, las 11 resoluciones y las cinco clases al
0 %. Una muestra independiente de 17.136 ids del rastreo del Archive da el mismo reparto.

### 3.3 Por qué #113 no lo habría arreglado

#113 propone *"walk the IDs we already know … plus a bounded probe of the high end of the
range"*. Los ids que ya conocemos son los que ya tenemos, así que no recuperan nada; y el
tramo alto de 1.0M–1.95M está esencialmente vacío — los ids nuevos aparecen en los 30M.
Ese arreglo habría cerrado el ticket del coste **dejando la brecha de 17.087 intacta**.

---

## 4. Qué hace falta para que el mensual publique de verdad

En orden, y sólo lo primero depende de que SUIN vuelva:

1. **Rehacer `discover_all` sobre los sitemaps** (§2), con el aserto contra el catálogo y la
   lista persistida. Sin esto no publica nada, aunque el timeout se arregle.
2. **Un bootstrap, no un mensual.** Faltan 17.087 documentos: eso es una repoblación, y el
   mensual no es el sitio.
3. **Corregir el comentario de `if: always()`** en los tres workflows mensuales. Ya tiene el
   `if: always()` y el token refrescado, pero **`if: always()` no sobrevive a
   `timeout-minutes`** (#114) y el comentario sigue afirmando que sí. Mientras siga ahí, el
   siguiente lector volverá a confiar en un rescate que en cuatro meses no ha rescatado nada.
   (`04-codigo-workflow-metadatos.md` §4.1)
4. **`discover_daily` sigue vacío y los sitemaps no lo arreglan** — no llevan `lastmod`. Si el
   catálogo `fiev-nid6` se actualiza de forma fiable (visto: 2026-07-08), el incremental
   plausible es diffear el catálogo contra el estado local: 1 petición al día. **Sin verificar.**
5. Declarar `text_state` para `co` (§5) y publicar `materia` y `art_culos`, que vienen gratis
   en la misma petición del catálogo.

---

## 5. `text_state` — propuesto, **no** decidido

`co` no está en `TEXT_STATE`, así que cae al default `POINT_IN_TIME`, la afirmación más
fuerte del spec, sin que nadie la haya verificado nunca.

La evidencia disponible sin la fuente (README del repo: *"texto consolidado por norma"*;
frontmatter de `LEY-57-1887`: `last_updated: 1990-12-27`, `modification_count: 102`) apunta a
la forma de `se` y `uy`, declarados **`CURRENT`**. La sospecha es que hoy **sobreafirmamos**.

**No se decide aquí**: exige comprobar contra SUIN si sirve el texto *a fecha* o simplemente
*el último que tiene*. Aplica la regla de dirección del fallo — ante la duda, infravalorar.
Detalle en `04-codigo-workflow-metadatos.md` §4.2.

---

## 6. Lo que queda bloqueado, para cuando SUIN vuelva

Por orden de lo que cuesta equivocarse:

| # | Sonda | Por qué exige la fuente |
|---|---|---|
| 7 | **Historial de versiones** | El gate que decidió rehacer Italia entera. Hay que ver si `LEGISLACIÓN ANTERIOR` da versiones fechadas de verdad. **Antes que nada.** Y ojo con el aviso de `es`: si aparece un patrón por años, sospechar — allí la disponibilidad era **por documento**, no por año. |
| 4 | `text_state` | §5 |
| 8 | Gate de calidad | Comparar el **Markdown que producimos** contra el documento oficial (no la fuente consigo misma), y medir **cuánto texto oficial falta**, no sólo si hay etiquetas sueltas |
| 6 | Cobertura de formato | Incluido medir la sospecha de §4.4: `promote_first_article` sólo promueve el **primer** párrafo del bloque |
| 3 | Frescura y cadencia | Si el mensual es la cadencia correcta, y si `fiev-nid6` sirve de incremental |
| 2 | Densidad por muestreo | Ya no hace falta para decidir: con índice, la densidad es irrelevante |
| 9 | **Dry run** | ~400 normas por el despacho **real** del engine. Es la que caza los errores que las demás no ven. Arnés en `dry-run-*.py`, **sin escribir** |

**Lo primero cuando vuelva no es ninguna de ellas**: es comprobar si vuelve **igual**. Un mes
de silencio es compatible con una reescritura del portal, y si los `id` cambian, los 71.900
`source:` publicados quedan colgando y el anclaje del corpus con la fuente se rompe.

---

## 7. Cifras disputadas — **no aptas para decidir**

No hubo verificadores adversariales: la sesión se paró en el Paso 0 y no se lanzó el
workflow. Estas cifras son las que **yo mismo** marco como no firmes, con el motivo:

| Cifra | Por qué no es firme |
|---|---|
| **84.728 ids en los sitemaps** | Es un **suelo**. Seis sitemaps (`constituciones`, `instruccion`, `dpresidenciales`, `consejoestado`, `csuprema`, `videos`) no se pudieron descargar: el Internet Archive limitó las peticiones. El total real es mayor. |
| **14,6 % de ids fuera del rango** | Calculado sobre esos 84.728, es decir sobre las clases que **sí** se pudieron bajar. Las que faltan podrían moverlo en cualquier dirección. |
| Todas las cifras de sitemaps | Salen de capturas del **2025-06-17**, no del estado de hoy. Sirven para demostrar que el índice existe y que hay ids fuera del rango; **no** como censo actual. |
| **17.136 ids** de la muestra del Archive | Es una muestra de **rastreo**, con el sesgo de lo que el Archive decidió visitar. No es un censo. Se usa sólo como confirmación independiente del reparto, no como cifra. |
| Reparto por bloques de la unión de sitemaps (91 % en 10M–100M) | **Contaminado**: lo domina `cconstitucional` (7.193 sentencias), que no es legislación. La tabla por clase de §3.2 es la buena; esa unión **no debe usarse**. |
| `text_state = CURRENT` | Sospecha razonada, **sin una sola comprobación contra la fuente**. |
| Sospecha de `promote_first_article` | Mecanismo leído en el código, **incidencia sin medir**. |
| `~4,2 h` de pasada completa | Extrapolación de los 5,9 req/s que #113 midió en el run `31013542577`, aplicada a ~89.000 documentos. Ese ritmo se midió sobre páginas de error baratas; las páginas reales pueden ser más lentas. |
| **Todas las cifras de la fuente** | La fuente lleva un mes caída. Nada de lo de aquí se ha comprobado contra SUIN el 2026-09-03. |

Firmes, en cambio, porque no dependen de SUIN y se reproducen en dos peticiones: las
**89.366** filas del catálogo, los **71.900** ficheros publicados, los **17.087** que faltan,
los **10.477** posteriores a 2014, los **8.692** vigentes, y el corte de 2014.
