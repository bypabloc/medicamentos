# Medicamentos y principios activos (Ecuador, Colombia y España)

Catálogo unificado de **medicamentos con registro sanitario vigente** y de sus **principios activos**, con las mismas columnas en los tres países y un diccionario común de principios activos. Pensado para autocompletar recetas médicas: se busca por nombre comercial o por principio activo y se obtiene concentración, forma farmacéutica, vía y código ATC.

| Archivo | Contenido | Filas | Fuente |
| :--- | :--- | ---: | :--- |
| `medicamentos-ec.csv` | Ecuador: registros sanitarios vigentes al 19/11/2026 | 6 376 | ARCSA, compilado en `fuentes/arcsa-2026-11-19.xlsx` |
| `medicamentos-co.csv` | Colombia: expedientes con CUM activo (una fila por expediente) | 9 176 | INVIMA, [CUM vigentes](https://www.datos.gov.co/d/i7cb-raxc) |
| `medicamentos-es.csv` | España: medicamentos comercializados | 16 107 | AEMPS, [CIMA](https://cima.aemps.es/cima/publico/home.html) |
| `principios-activos.csv` | Diccionario común de principios activos (DCI), con ATC y sinónimos | 7 127 | Las tres anteriores + [Wikidata](https://www.wikidata.org/) |
| `rechazados.csv` | Filas descartadas y su motivo | 192 | — |
| `reporte.json` | Conteos, cobertura y formas o vías que no se pudieron clasificar | — | — |

**¿Hay diferencia con Ecuador?** Sí en los productos: cada país registra sus propias marcas, laboratorios y presentaciones, y una receta en Ecuador debe usar lo que se vende ahí (`medicamentos-ec.csv`). No en los principios activos: la DCI es internacional, así que el diccionario es común y Colombia, España y Wikidata lo completan con sinónimos, sales y códigos ATC.

```text
.
├── medicamentos-{ec,co,es}.csv   # resultado final
├── principios-activos.csv        # resultado final
├── rechazados.csv, reporte.json  # control de calidad de la corrida
├── build.py                      # paso 2: normaliza, une y valida
├── scripts/fetch.py              # paso 1: descarga INVIMA, CIMA y Wikidata a source/
├── fuentes/arcsa-*.xlsx          # entrada de Ecuador (no hay descarga pública)
└── source/                       # descargas del paso 1 (no se versiona)
```

## Columnas de `medicamentos-*.csv`

| Columna | Descripción |
| :--- | :--- |
| `country` | `ec`, `co` o `es` |
| `id` | Único por archivo: registro sanitario ARCSA (`ec`), expediente INVIMA (`co`), número de registro AEMPS (`es`) |
| `registration` | Registro sanitario tal como lo publica la autoridad |
| `trade_name` | Nombre comercial |
| `brand` | Marca (`ec`); vacío en genéricos |
| `kind` | `brand` o `generic` (vacío si la fuente no lo dice) |
| `ingredients` | Principios activos limpios, separados por ` + ` |
| `ingredient_ids` | `id` de `principios-activos.csv`, separados por `|`, en el mismo orden |
| `strength` | Concentración legible (`500 mg + 65 mg`, `5 %`, `200 mg/5 mL`) |
| `dosage_form` | Forma normalizada: `tablet`, `capsule`, `syrup`, `suspension`, `solution`, `cream`, `ointment`, `gel`, `drops`, `injectable`, `inhaler`, `pessary`, `suppository`, `patch`, `powder`, `other` |
| `dosage_form_raw` | Forma tal como viene en la fuente |
| `routes` | Vías normalizadas separadas por `|`: `oral`, `sublingual`, `topical`, `ophthalmic`, `otic`, `nasal`, `inhalation`, `intramuscular`, `intravenous`, `subcutaneous`, `rectal`, `vaginal` |
| `route_raw` | Vía tal como viene en la fuente |
| `presentation` | Presentación comercial (envase) |
| `holder`, `holder_country` | Titular del registro y su país (`holder_country` solo en `ec`) |
| `sale_condition` | `prescription`, `otc` o `controlled` (`ec` y `es`) |
| `in_cnmb` | `true`/`false`: pertenece al Cuadro Nacional de Medicamentos Básicos (`ec`) |
| `atc_code` | Código ATC de nivel 5 (o 4 si la fuente no da el 5) |
| `valid_until` | Vigencia del registro (ISO `YYYY-MM-DD`) |

## Columnas de `principios-activos.csv`

| Columna | Descripción |
| :--- | :--- |
| `id` | Estable entre corridas: `PA-` + la clave normalizada sin sales (`PA-amoxicilina`) |
| `name` | Nombre en español: la etiqueta de Wikidata o la ortografía más frecuente en las fuentes |
| `atc_codes` | Códigos ATC conocidos, separados por `|` |
| `synonyms` | Otras escrituras, sales y el nombre en inglés, separados por `|` |
| `wikidata_id` | `Q…` si se enlazó con Wikidata |
| `products_ec`, `products_co`, `products_es` | Cantidad de productos que lo contienen en cada país |
| `sources` | Fuentes que lo nombran: `ec`, `co`, `es`, `wikidata` |
| `quality` | `verified` si está en Wikidata o lo nombran dos fuentes; `unverified` si solo lo nombra una (revisar antes de usarlo como sugerencia) |

## Control de calidad

Cada corrida aplica estas reglas y deja la evidencia en `rechazados.csv` y `reporte.json`:

* **Rechazo**: fila sin registro, con registro repetido, sin nombre comercial o sin ningún principio activo reconocible.
* **Limpieza del principio activo**: quita cantidades, unidades, farmacopeas (`USP`, `BP`), paréntesis y texto de fórmula (`cada … contiene`, `exceso`, `pellets`, `núcleo`); de «X equivalente a Y» conserva Y; descarta lo que no parece un nombre (menos de tres letras, más de seis palabras, palabras de envase).
* **Unión**: dos nombres son el mismo principio si coinciden sin tildes, mayúsculas, sales ni hidratos (`clorhidrato de metformina` → `metformina`), o si Wikidata los da como alias.
* **Formas y vías** sin regla quedan como `other` o vacías y se cuentan en `reporte.json` (`unmapped_top`).

## Licencias y atribución

| Fuente | Licencia | Atribución |
| :--- | :--- | :--- |
| INVIMA, datos.gov.co | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | Instituto Nacional de Vigilancia de Medicamentos y Alimentos (INVIMA), Colombia |
| AEMPS, CIMA | Reutilización con cita de la fuente | Agencia Española de Medicamentos y Productos Sanitarios (AEMPS) |
| Wikidata | CC0 | — |
| ARCSA | Información pública de registros sanitarios de Ecuador, compilada a mano | Agencia Nacional de Regulación, Control y Vigilancia Sanitaria (ARCSA) |

* `medicamentos-co.csv` y `principios-activos.csv` (que incorpora datos de INVIMA) se distribuyen bajo **CC BY-SA 4.0**.
* Solo se publica el **código** ATC: los nombres de los grupos ATC del WHOCC no se redistribuyen.
* No es una fuente clínica oficial: verifica en la autoridad sanitaria antes de una decisión regulatoria.

## Reproducir

```bash
python3 scripts/fetch.py                                        # descarga INVIMA, CIMA y Wikidata a source/
uv run --python 3.12 --with openpyxl python build.py           # genera los CSV, rechazados.csv y reporte.json
```

Para actualizar Ecuador (productos nuevos o descontinuados), reemplaza `fuentes/arcsa-<fecha>.xlsx` por una compilación nueva con las mismas hojas y columnas, y vuelve a correr `build.py`.

**CSV:** separador `,`, UTF-8 sin BOM, comillas solo cuando hacen falta, fin de línea `\n`, encabezado en la primera fila. Léelos como texto (`dtype=str` en pandas) para no perder ceros ni códigos.
