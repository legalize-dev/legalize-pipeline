# 04 — Lo que se puede auditar sin la fuente: código, workflow y metadatos publicados

Medido el 2026-09-03 leyendo `fetcher/co/`, `monthly-update-co.yml` y ficheros ya publicados
en `legalize-co` (vía API de GitHub). **Cero peticiones a SUIN.**

## 4.1 El workflow: #114 está a medias, y el comentario sigue mintiendo

`monthly-update-co.yml` **ya tiene** `if: always()` en los pasos de rescate y un token
refrescado antes del push (7 ocurrencias; `ar` 4, `ch` 5). Esa parte del enunciado de la
sesión estaba desactualizada.

Lo que **no** está arreglado es lo que #114 demostró: `if: always()` **no sobrevive a
`timeout-minutes`**. Cuando el runner mata el trabajo por tiempo, esos pasos salen
`skipped`, no `run`. Y el bloque de comentarios del workflow sigue afirmando lo contrario:

> *"a cancelled fetch still leaves committable data on disk. Without always() here, a
> cancelled fetch skips this step too and every fetched-but-uncommitted ID is wasted work."*

Es exactamente el rescate que nunca ha rescatado nada en cuatro meses. Mientras el
comentario siga ahí, el siguiente que lo lea volverá a confiar en él. **Corregir el
comentario es parte del arreglo, no cosmética** — es el punto 2 del orden sugerido en #114 y
sigue sin hacerse.

Además el encabezado sigue documentando un `discovery_ids.txt` que no existe en el repo, y
un runtime de "~3h fetch (75K IDs × ~7 req/s)" que describe un diseño nunca implementado.
Con el índice de `02-descubrimiento.md`, ese `discovery_ids.txt` pasa de ser ficción a ser
justo lo que hay que construir — 10 peticiones y a disco.

## 4.2 `text_state`: `co` no está declarado — **no verificable hoy**

`countries.py:41` declara 8 países. `co` no está, así que `text_state_for("co")` devuelve
el default `POINT_IN_TIME`, *"the law as in force on last_updated"* — la afirmación **más
fuerte** del spec.

Nadie la ha comprobado nunca contra la fuente. Lo que se puede decir sin ella:

- El README del repo describe *"texto consolidado por norma"*, y el historial se reconstruye
  de bloques `LEGISLACIÓN ANTERIOR` que SUIN incrusta por artículo con su rango de vigencia.
- El frontmatter publicado lo respalda: `LEY-57-1887` lleva `last_updated: "1990-12-27"` y
  `modification_count: "102"`.

Esa forma —un texto consolidado único que la fuente mantiene, más un registro de reformas—
es la de `se` y `uy`, que están declarados **`CURRENT`**, no la de un texto reconstruido a
una fecha. La sospecha es que hoy **sobreafirmamos**.

**No se decide aquí.** Decidirlo exige la fuente viva: hay que comprobar si SUIN sirve el
texto *a fecha* (y entonces `POINT_IN_TIME` es correcto) o simplemente *el último que tiene*
(y entonces es `CURRENT`). Lo que sí aplica ya es la regla de dirección del fallo: ante la
duda, infravalorar. Queda como acción bloqueada, no como propuesta.

## 4.3 Inventario de metadatos (Step 0.3)

### Keys publicadas — **todas en inglés. `co` cumple #129.**

`title`, `identifier`, `country`, `rank`, `publication_date`, `last_updated`, `status`,
`source`, `department`, `document_status_raw`, `gazette_reference`, `gazette_number`,
`gazette_page`, `gazette_pdf_page`, `subtype`, `sector`, `comments`, `entry_into_force`,
`modification_count`, `modification_summary`.

Ninguna key no inglesa, a diferencia de las 6 de `es`. Los **valores** siguen en castellano
(`rank: "ley"`, `document_status_raw: "Vigente"`), que es lo acordado.

### Lo que la fuente ofrece y hoy se tira

El catálogo `fiev-nid6` trae 9 campos por norma. Contraste:

| Campo del catálogo | ¿En el frontmatter? | Nota |
|---|---|---|
| `tipo` | sí → `rank` | |
| `n_mero`, `a_o` | sí → `identifier` | |
| `sector` | sí → `sector` | ausente en parte del corpus (`LEY-57-1887` no lo lleva) |
| `entidad` | sí → `department` | |
| `subtipo` | sí → `subtype` | |
| `vigencia` | sí → `document_status_raw` | |
| **`materia`** | **NO** | materia jurídica; `NULL` en parte del catálogo, pero poblado en otra |
| **`art_culos`** | **NO** | nº de artículos **según la fuente** |

`art_culos` merece un párrafo. La memoria `article_count_architecture` registra que
`article_count` se calcula hoy con una regex sobre el Markdown y que tres sistemas adivinan
lo mismo por separado. **Aquí la fuente lo publica**, y publicarlo junto al calculado
convierte una adivinanza en un contraste: si no cuadran, o el parser perdió estructura o la
fuente se equivoca, y en los dos casos queremos saberlo. Es un campo, y sale gratis en la
misma petición del catálogo.

### Un defecto de forma ya publicado: `modification_summary`

`LEY-57-1887` lo publica así (un solo escalar YAML, sin truncar):

```yaml
modification_count: "102"
modification_summary: "Reformado [Artículo 49 LEY 153 de 1887](…) · Reformado [Artículo 13
LEY 118 de 1931](…) · Derogado [Artículo 31 LEY 1 de 1976](…) · … (102 entradas)"
```

Es el mismo patrón que #87 encontró en `gr` (la relación aplanada en una cadena unida por
comas), con dos agravantes: aquí **no** hay tope, y el contenido es Markdown dentro de YAML.
Cada entrada tiene estructura real —verbo, artículo afectado, norma que reforma, enlace con
`#ver_{id}`— y se está tirando al concatenar. Es el sitio natural de la normalización de
verbos que #87 propone, y `co` es el peor caso publicado.

`modification_count: "102"` es además un número serializado como cadena.

## 4.4 Cobertura de formato: lo que se ve sin la fuente

Contra el aviso del enunciado, **no hay que culpar al parser antes de leer #128**. Comprobado:

`grep -oE 'css_class="[^"]*"' fetcher/co/parser.py` devuelve **una sola** literal, `"table"`
—que es lo que #128 recoge—, pero eso es un artefacto del grep. En ejecución
`_paragraphs_from_element` asigna también `titulo_tit`, `capitulo_tit`, `seccion`,
`articulo`, `list_item`, `firma_rey` y `parrafo`. **`co` sí emite jerarquía.**

Las ocho están en el mapa compartido salvo `parrafo`, que cae por defecto **correctamente**
(párrafo llano), igual que anota #128.

Dos observaciones que sí son de `co` y no de la capa compartida:

1. **`firma_rey` en una república.** `parser.py:510` trata explícitamente esa clase. Colombia
   no tiene rey; es el mismo absurdo que #128 documenta en `nl`, `lv` e `it`, y `co` va a la
   lista.
2. **La detección de artículo está limitada a un párrafo por bloque.**
   `_paragraphs_from_element(..., promote_first_article=True)` sólo promueve a `articulo`
   el **primer** párrafo del bloque (`if promote_first_article and not paragraphs`). Si un
   bloque de SUIN contiene varios artículos, del segundo en adelante salen como `parrafo` y
   pierden el encabezado. **No se ha medido** cuánto corpus tiene esa forma: hace falta la
   fuente, o un clon local de los 2 GB del repo. Queda anotado como sospecha con mecanismo,
   no como defecto confirmado.

El resto de la sonda 6 —contrastar el `.md` publicado contra el HTML de origen, aplicar el
gate del >1 %— **está bloqueado**: exige la fuente.
