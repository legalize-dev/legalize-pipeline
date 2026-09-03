# eu-v2 — evidencia de RESEARCH-EU.md (3-sep-2026)

- `sq.py` — lanza una consulta SPARQL contra CELLAR: `python3 sq.py queries/x.rq`
  (usa curl por debajo; urllib falla con el certificado en macOS).
- `queries/` — las consultas que produjeron las cifras del documento.
- `samples/` — descargas reales desde CELLAR REST, para el inventario §0.2/§0.4:
  - `s-32016R0679.html`  RGPD, 807 KB, reglamento moderno con consolidación
  - `s-32014L0024.html`  Directiva de contratación pública, 1,5 MB — el tipo que HOY NO EXISTE en el corpus
  - `s-31968R1017.html`  Reglamento 1017/68, 52 KB — histórico, derogado, con estado declarado
  - `s-31993D0465.html`  Decisión de 1993, 62 KB
  - `s-11957E000.html`   Tratado CEE, 4,6 KB
  - `s-32019R0947.html`  Reglamento de drones, 367 KB — con tablas y anexos

- `parse-test.py` — pasa las muestras por el `EURLexTextParser` real. Es lo que
  destapó el §3.3: los documentos legacy salen en 2 párrafos.

  ```sh
  cd engine/research/eu-v2 && PYTHONPATH=../../src python3 parse-test.py
  ```

## Sondas del 3-sep (segunda tanda, tras las decisiones)

- `queries/06-consolidacion-por-estado.rq` — la que corrigió el §2.1: 20 de
  82.326 actos sin campo `in-force` tienen consolidación, frente al 18,9 % de los
  vigentes. Nunca se modificaron porque estaban agotados.
- `queries/07-texto-autentico.rq` — la que decidió `DEC_ENTSCHEID`: el 51 % no es
  auténtico en inglés, contra el 2,3 % de las decisiones que sí entran.

**Control positivo del §2.1** (que CELLAR no tiene el dato, y no es que la
consulta esté mal):

```sh
curl -sL -H "Accept: application/xml;notice=object" \
  https://publications.europa.eu/resource/celex/32016R0679 | grep -c "RESOURCE_LEGAL_IN-FORCE"   # → 2
curl -sL -H "Accept: application/xml;notice=object" \
  https://publications.europa.eu/resource/celex/32005R0002 | grep -c "RESOURCE_LEGAL_IN-FORCE"   # → 0
```

La web de EUR-Lex (`legal-content/EN/ALL/?uri=CELEX:...`) devuelve HTTP 202 con 0
bytes a un cliente no-navegador: no sirve como fuente del estado.
