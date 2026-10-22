# 01 — SUIN-Juriscol no responde, y no es nuestra IP

**Fecha de la medición: 2026-09-03.** Reproducible con `python3 probe-suin.py`.

## El síntoma

TCP conecta, TLS negocia, y el servidor no envía **ni un byte de HTTP**.

```
$ curl -sSk -o /dev/null -w "http=%{http_code} size=%{size_download} ip=%{remote_ip}\n" \
    https://www.suin-juriscol.gov.co/
curl: (52) Empty reply from server
http=000 size=0 ip=186.86.242.143
```

Idéntico en las seis variantes probadas, todas el 2026-09-03:

| Prueba | Resultado |
|---|---|
| `https://www.suin-juriscol.gov.co/` | `curl (52)`, `http=000`, 0 bytes |
| `https://suin-juriscol.gov.co/` (sin www) | `curl (52)`, `http=000` |
| `http://www.suin-juriscol.gov.co/` (puerto 80) | `curl (52)`, `http=000` |
| `--http1.1` forzado | `curl (52)`, `http=000` |
| `-k` (sin verificar TLS) | `curl (52)`, `http=000` |
| `/viewDocument.asp?id=1` (el endpoint real) | `curl (52)`, `http=000` |
| UA de bot y UA de Chrome | sin diferencia |

El handshake TLS **sí** completa, así que el puerto está vivo y hay un proceso detrás:

```
subject=... C=CO, O=Ministerio de Justicia y del Derecho, CN=www.suin-juriscol.gov.co
Protocol: TLSv1.2   Cipher: ECDHE-RSA-AES256-GCM-SHA384
Verify return code: 21 (unable to verify the first certificate)   ← la cadena rota de siempre
```

La cadena rota es un defecto viejo y conocido (`client.py` ya usa `verify=False` por ello).
**No es la causa de este fallo**: `-k` falla igual.

## Por qué NO es un geobloqueo contra nosotros

Tres controles independientes, y los tres apuntan al mismo sitio.

**1. La ruta a Colombia funciona.** Otro host `.gov.co` alojado en direcciones colombianas
—no detrás de un CDN global— contesta desde este mismo equipo, el mismo día:

| Host | IP | Resultado |
|---|---|---|
| `secretariasenado.gov.co` | `200.7.106.227` (Colombia) | **200**, 83.176 bytes |
| `funcionpublica.gov.co/eva/gestornormativo` | `44.199.160.6` | **200**, 1.230.041 bytes |
| `gov.co` | `13.224.83.47` | **200** |

**2. Otra red tampoco entra.** `r.jina.ai` (Chrome headless sobre infraestructura ajena a la
nuestra) devuelve exactamente el mismo error:

```
"Failed to goto https://www.suin-juriscol.gov.co/: net::ERR_EMPTY_RESPONSE"
```

**3. Y el dato que cierra la cuestión: el Internet Archive tampoco.** El IA rastrea desde
centros de datos en EE. UU., de forma continua y sin motivo para parar. Capturas del dominio
`suin-juriscol.gov.co` por mes en 2026:

| Mes | Capturas |
|---|---:|
| enero | 1.123 |
| febrero | 441 |
| marzo | 2.150 |
| abril | 899 |
| mayo | 717 |
| junio | 651 |
| julio | **1.855** |
| agosto | **9** — todas del 1 y 2 de agosto |
| septiembre | **0** |

```
curl "http://web.archive.org/cdx/search/cdx?url=suin-juriscol.gov.co&matchType=domain\
&from=20260101&fl=timestamp&limit=200000" | cut -c1-6 | sort | uniq -c
```

La última captura con éxito es del **2026-08-02**. Un mes entero de silencio, desde una red
que no es la nuestra y que estaba entrando 1.855 veces el mes anterior.

## Veredicto

**SUIN-Juriscol lleva caído para todo el mundo desde ~2026-08-02.** No es una caída puntual
del 3 de septiembre, y no es un bloqueo contra nuestra IP.

**Consecuencia operativa: la VM de São Paulo no sirve para esto.** El protocolo
`gcp_vm_fetch_protocol` existe para bloqueos geográficos —el caso de InfoLEG en Argentina—,
y aquí la premisa no se cumple: si el Internet Archive, desde EE. UU., lleva un mes sin sacar
un byte, otra región no va a sacarlo tampoco. Levantarla sería gastar sin ninguna
probabilidad de éxito.

Esto **bloquea** las sondas que miden la fuente viva: densidad de IDs por muestreo, frescura
real, `text_state` contra el documento, cobertura de formato contra el HTML, historial de
versiones, y el gate de calidad letra a letra. Lo que sí se ha podido medir sin SUIN está en
`02-descubrimiento.md` y `03-brecha-de-corpus.md`, y resulta ser lo importante.

## Lo que hay que vigilar

`probe-suin.py` responde la pregunta en unos segundos y **se explica solo**: distingue
"caído" de "bloqueado contra nosotros" comparando con el host de control y con la actividad
reciente del Archive, y dice en cada caso si tiene sentido levantar una VM. Sale con código 1
mientras SUIN no conteste, así que sirve de guarda en cualquier automatismo.

Cuando vuelva, conviene comprobar además si vuelve **igual**: la reescritura de un portal es
una causa habitual de un mes de silencio, y si los `id` cambian, el corpus publicado pierde
su anclaje con la fuente.
