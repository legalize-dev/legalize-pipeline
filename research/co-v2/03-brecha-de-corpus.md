# 03 — El corpus de Colombia se detiene en 2014, y se sabe exactamente por qué

**Sondas 1 y 2.** Medido el 2026-09-03, **cero peticiones a SUIN**.
Reproducible con `python3 catalog-gap.py`; salida guardada en `gap-2026-09-03.txt`.

## El hallazgo

`legalize-co` publica **71.900** ficheros. Ninguno es posterior a 2014.

```
$ grep -oE '\-(201[5-9]|202[0-6])\.md$' repo_paths.txt | wc -l
0
```

Distribución por año de los últimos años publicados:

| Año | Ficheros |
|---|---:|
| 2011 | 687 |
| 2012 | 655 |
| 2013 | 728 |
| 2014 | **485** |
| 2015 … 2026 | **0** |

No es un corpus que se quedó obsoleto en abril de 2026. **Nunca tuvo nada posterior a 2014.**

Y no es un límite de la fuente. El catálogo oficial de SUIN sí publica esos años:

| Año | Normas en el catálogo |
|---|---:|
| 2015 | 634 |
| 2016 | 756 |
| 2017 | 742 |
| 2018 | 698 |
| 2019 | 650 |
| 2020 | 1.024 |
| 2021 | 847 |
| 2022 | 712 |
| 2023 | 1.456 |
| 2024 | 1.073 |
| 2025 | 1.320 |
| 2026 | 565 |
| **total ≥2015** | **10.477** |

## La brecha, medida por diferencia de conjuntos

El catálogo `fiev-nid6` indexa por tipo/número/año, que es exactamente nuestro esquema de
nombres de fichero. La comparación es una diferencia de conjuntos, no una estimación.

```
catálogo                        : 89.366
ficheros publicados             : 71.900
FALTAN (en catálogo, sin fichero): 17.087   (19,1 % del catálogo)
huérfanos (fichero sin catálogo) :     25   (0,03 % del corpus)
```

**Los 25 huérfanos son la prueba de que la unión es válida.** Si el criterio de unión fuera
malo, ese número sería enorme. Son artefactos de formato de nombre
(`DECRETO-1245 BIS-1923` con espacio, `CONSTITUCION-POLITICA-CP-1886-1886` con el año
duplicado), no normas inventadas. El otro sentido de la comparación se imprime siempre por
este motivo.

### Qué falta

| Por época | |
|---|---:|
| ≥2015 | **10.477** |
| ≤2014 | 6.589 |
| año ilegible en el catálogo | 21 |

| Por tipo | Faltan | En el catálogo | Publicadas |
|---|---:|---:|---:|
| RESOLUCION | **8.480** | 8.491 | **11** |
| DECRETO | 5.345 | 67.078 | 61.264 |
| LEY | 1.241 | 11.675 | 10.353 |
| CIRCULAR EXTERNA | 870 | 870 | **0** |
| DIRECTIVA PRESIDENCIAL | 316 | 316 | **0** |
| INSTRUCCION ADMINISTRATIVA CONJUNTA | 241 | 241 | **0** |
| CIRCULAR | 229 | 229 | **0** |
| ACUERDO | 222 | 222 | **0** |
| ACTO LEGISLATIVO | 38 | 136 | 100 |

Cinco clases documentales completas están al **0 %**. Las resoluciones, al **0,13 %**.

| Por vigencia | |
|---|---:|
| **Vigente** | **8.692** |
| NULL | 7.452 |
| Derogado | 621 |
| Compilado | 184 |

**8.692 de las normas que faltan están vigentes.** Entre ellas, los decretos únicos
reglamentarios —lo primero que consulta cualquiera que trabaje con derecho colombiano:

```
DECRETO 1072 de 2015 — Vigente — MINISTERIO DE TRABAJO          (Sector Trabajo)
DECRETO 1078 de 2015 — Vigente — MIN. TECNOLOGÍAS DE LA INFORMACIÓN
DECRETO 1079 de 2015 — Vigente — MINISTERIO DE TRANSPORTE
DECRETO 2016 de 2015 — Vigente — MINISTERIO DE DEFENSA NACIONAL
```

Las dos organizaciones que consultan **sólo** Colombia (143 peticiones en 10 días, #113) están
recibiendo un corpus sin ninguna de ellas.

## La causa: SUIN usa dos bloques de identificadores y el barrido sólo visita uno

`config.yaml` fija `id_start: 1000000`, `id_end: 1950000`. Los sitemaps demuestran que los
identificadores de SUIN **no viven sólo ahí**:

```xml
<url><loc>	https://www.suin-juriscol.gov.co/viewDocument.asp?id=1685914	</loc></url>
<url><loc>	https://www.suin-juriscol.gov.co/viewDocument.asp?id=30044701	</loc></url>
```

Reparto de los ids reales de cada sitemap respecto al rango configurado:

| Clase | ids | Dentro de 1.0M–1.95M | **Fuera — invisibles** | % perdido |
|---|---:|---:|---:|---:|
| decretos (1) | 49.961 | 48.171 | 1.790 | 3,6 % |
| decretos (2) | 16.129 | 13.652 | 2.477 | 15,4 % |
| leyes | 11.347 | 10.429 | 918 | 8,1 % |
| **resoluciones** | 6.139 | **0** | **6.139** | **100 %** |
| **circulares** | 898 | **0** | **898** | **100 %** |
| **acuerdos** | 121 | **0** | **121** | **100 %** |
| actos legislativos | 133 | 99 | 34 | 25,6 % |
| **total medido** | **84.728** | **72.351** | **12.377** | **14,6 %** |

Y aquí está la confirmación de que ésta es *la* causa y no *una* causa:

> **72.351 ids caen dentro del rango configurado. Hay 71.900 ficheros publicados.**
> Coinciden al **99,4 %**.

El bootstrap capturó exactamente lo que el barrido podía ver, y nada más. Todo lo que SUIN
numeró en el bloque de los 30 millones —que es donde están las clases nuevas y los documentos
recientes— nunca ha sido visitado ni una vez.

Eso explica los tres síntomas a la vez, con un solo mecanismo:

1. **el corte en 2014** — lo publicado después lleva id del bloque alto;
2. **las 11 resoluciones de 8.491** — la clase entera está fuera del rango;
3. **las cinco clases al 0 %** — ídem.

Una muestra independiente de 17.136 ids distintos, sacada del rastreo del Internet Archive
(no de los sitemaps), da el mismo reparto: 84,7 % dentro del rango, 14,3 % en el bloque
10M–100M. Dos fuentes distintas, la misma conclusión.

## Lo que esto cambia respecto a #113

#113 diagnosticó bien el desperdicio (950.001 peticiones para 71.900 normas) pero propuso
como arreglo:

> *"walk the IDs we already know … plus a bounded probe of the high end of the range, where
> new IDs appear."*

**Los dos términos fallan.** Los ids que ya conocemos son justamente los que ya tenemos, así
que recorrerlos no recupera nada de lo que falta; y "the high end of the range" —el tramo
alto de 1.0M–1.95M— está esencialmente vacío: los ids nuevos no aparecen ahí, aparecen en los
30M. Ese arreglo habría cerrado el ticket dejando la brecha de 17.087 documentos intacta,
que es la parte que de verdad afecta a los usuarios.

El arreglo es el índice (`02-descubrimiento.md`), no un barrido mejor acotado.

## Aviso sobre la calidad del catálogo

`fiev-nid6` tiene 21 filas con el año ilegible (`234-2016`, `20243`, `2023|`, `996`, `9`) y
1.356 claves tipo/número/año duplicadas (89.366 filas → 88.010 claves distintas). Quien una
por esa clave tiene que decidir qué hace con los duplicados; ignorarlos silenciosamente es
volver a la trampa de #113 en otra capa. Se registra aquí porque cualquier aserto que se
escriba contra este catálogo tiene que tolerarlo.
