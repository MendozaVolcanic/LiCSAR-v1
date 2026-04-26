# LiCSAR-v1 — Dashboard InSAR Volcanes Chile

**Dashboard de deformación volcánica** para 43 volcanes chilenos usando interferometría SAR (InSAR) de Sentinel-1, procesada por el proyecto COMET LiCSAR (UK NERC).

**[Ver Dashboard en vivo →](https://mendozavolcanic.github.io/LiCSAR-v1/)**

---

## Qué muestra

Para cada volcán el dashboard despliega tres bloques de información:

1. **Serie temporal de desplazamiento (LiCSBAS)** — gráfico interactivo Plotly con desplazamiento en cm vs fecha (2014→presente). Se calcula velocidad lineal en cm/año y cambio de los últimos 180 días sobre un ROI de 20×20 píxeles centrado en el cráter.
2. **Interferogramas COMET recortados** — selector de los 10 pares de fechas más recientes, JPG cropeado al volcán (no al frame de 250 km).
3. **Frames LiCSAR completos** — sección colapsable con los PNGs originales (asc/desc, fase desenvuelta + coherencia).

| Producto | Descripción |
|----------|-------------|
| **Serie temporal LiCSBAS** | Desplazamiento promedio en línea de visión (LOS). Tendencia ascendente = inflación, descendente = deflación. Versión con corrección atmosférica GACOS cuando está disponible. |
| **Probabilidad de deformación** | Score deep learning (0–1) por par. Semáforo en sidebar: rojo si >0.5, amarillo si >0.2. |
| **Fase desenvuelta (unw)** | Deformación relativa en cm. Cada franja ≈ 2.8 cm en LOS. Fringes concéntricos = inflación/deflación magmática. |
| **Coherencia (coh)** | Calidad de la señal (0–1). Blanco = alta coherencia (superficie estable). Negro = baja coherencia (vegetación, nieve, agua). |

Cobertura: **41/43 volcanes con ascendente + descendente**, 2 solo con una geometría. La combinación de ambas permite separar deformación vertical de horizontal. **41/43 con datos COMET** (interferogramas recortados + serie temporal LiCSBAS).

## Volcanes monitoreados (43)

| Zona | Volcanes |
|------|----------|
| **Norte** | Taapaca, Parinacota, Guallatiri, Isluga, Irruputuncu, Ollague, San Pedro, Lascar |
| **Centro** | Tupungatito, San Jose, Tinguiririca, Planchon-Peteroa, Descabezado Grande, Tatara-San Pedro, Laguna del Maule, Nevado de Longavi, Nevados de Chillan |
| **Sur** | Antuco, Copahue, Callaqui, Lonquimay, Llaima, Sollipulli, Villarrica, Quetrupillan, Lanin, Mocho-Choshuenco, Carran-Los Venados, Puyehue-Cordon Caulle, Antillanca-Casablanca |
| **Austral** | Osorno, Calbuco, Yate, Hornopiren, Huequi, Michinmahuida, Chaiten, Corcovado, Melimoyu, Mentolat, Cay, Maca, Hudson |

## Fuente de datos

- **Sensor:** Sentinel-1 SAR (banda C, λ = 5.6 cm), ESA
- **Procesamiento:** [COMET LiCSAR](https://comet.nerc.ac.uk/comet-lics-portal/) — UK NERC Centre for the Observation and Modelling of Earthquakes, Volcanoes and Tectonics
- **Portal:** [gws-access.jasmin.ac.uk](https://gws-access.jasmin.ac.uk/public/nceo_geohazards/LiCSAR_products) — acceso público sin autenticación
- **Productos:** Solo thumbnails PNG (`geo.unw.png`, `geo.cc.png`). No se descargan GeoTIFF.

## Arquitectura

```
frame_finder.py            → Identifica el frame LiCSAR más cercano a cada volcán (ASF API + polígonos JASMIN)
licsar_downloader.py       → Descarga PNGs del interferograma más reciente desde JASMIN
comet_downloader.py        → Descarga interferogramas recortados + probabilidad ML desde COMET VolcanoDB
timeseries_downloader.py   → Descarga JSONs de desplazamiento LiCSBAS (~22MB c/u) y los reduce a series 1D (~5KB)
docs/index.html            → Dashboard web (Plotly time series + COMET + frames colapsables)
docs/licsar/{Volcan}/      → Archivos por volcán: PNGs LiCSAR + comet/*.jpg + timeseries.json
docs/licsar/catalog.json   → Índice unificado (frames + COMET + flags timeseries)
datos/frames_volcanes.*    → Catálogo de tracks por volcán (CSV + JSON)
.github/workflows/         → Actualización automática 2x/día
```

## Actualización automática (GitHub Actions)

El workflow corre **2 veces al día** (07:00 y 19:00 UTC ≈ 04:00 y 16:00 Chile):

| Step | Cuándo se ejecuta | Acción |
|------|-------------------|--------|
| `frame_finder` | Solo lunes (o primera vez) | Redescubre frames disponibles |
| `licsar_downloader` | Lunes y jueves | Descarga PNGs LiCSAR del frame completo |
| `comet_downloader` | Cada ejecución (2x/día) | Interferogramas recortados + probabilidad ML |
| `timeseries_downloader` | Solo lunes | Series temporales LiCSBAS (descarga pesada) |

## Correr localmente

```bash
# Instalar dependencias
pip install requests

# Descubrir frames para los 43 volcanes
python frame_finder.py

# Descargar interferogramas más recientes
python licsar_downloader.py

# Ver dashboard (requiere servidor HTTP, no funciona con file://)
cd docs && python -m http.server 8765
# Abrir: http://localhost:8765
```

## Limitaciones conocidas

- **Decorrelación alta** en volcanes del sur (vegetación densa, nieve permanente)
- **Sin corrección atmosférica** (GACOS no incluida)
- **Resolución ~30 m** en los thumbnails PNG
- Los interferogramas corresponden al par de fechas más reciente disponible, no necesariamente el más informativo
- Cada volcán usa el frame LiCSAR cuyo centro geográfico está más cercano, minimizando superposición entre volcanes vecinos

## Contexto

Proyecto desarrollado en SERNAGEOMIN para monitoreo de deformación volcánica en Chile. Complementa el sistema MIROVA de monitoreo de anomalías termales.

> **Datos:** COMET LiCSAR (NERC) / ESA Sentinel-1. Dashboard y scripts: Nicolas Mendoza, SERNAGEOMIN.
