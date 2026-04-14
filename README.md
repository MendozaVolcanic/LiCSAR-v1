# LiCSAR-v1 — Dashboard InSAR Volcanes Chile

**Dashboard de deformación volcánica** para 43 volcanes chilenos usando interferometría SAR (InSAR) de Sentinel-1, procesada por el proyecto COMET LiCSAR (UK NERC).

**[Ver Dashboard en vivo →](https://mendozavolcanic.github.io/LiCSAR-v1/)**

---

## Qué muestra

Para cada volcán se muestran los interferogramas más recientes disponibles:

| Imagen | Descripción |
|--------|-------------|
| **Fase desenvuelta (unw)** | Deformación relativa en cm. Cada franja ≈ 2.8 cm en línea de visión del satélite (LOS). Fringes concéntricos sobre un volcán indican inflación o deflación magmática. |
| **Coherencia (coh)** | Calidad de la señal (0–1). Blanco = alta coherencia (superficie estable). Negro = baja coherencia (vegetación, nieve, agua). |

Cobertura: **41/43 volcanes con ascendente + descendente**, 2 solo con una geometría. La combinación de ambas permite separar deformación vertical de horizontal.

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
frame_finder.py          → Identifica el frame LiCSAR más cercano a cada volcán (ASF API + polígonos JASMIN)
licsar_downloader.py     → Descarga PNGs del interferograma más reciente
docs/index.html          → Dashboard web (sidebar + panel detalle + zoom)
docs/licsar/{Volcan}/    → PNGs por volcán (asc_unw, asc_coh, desc_unw, desc_coh)
docs/licsar/catalog.json → Índice de disponibilidad
datos/frames_volcanes.*  → Catálogo de tracks por volcán (CSV + JSON)
.github/workflows/       → Actualización automática 2x/semana
```

## Actualización automática (GitHub Actions)

| Workflow | Horario | Acción |
|----------|---------|--------|
| `frame_finder` | Lunes 06:00 UTC | Redescubre frames disponibles |
| `licsar_downloader` | Lunes + Jueves 08:00 UTC | Descarga interferogramas nuevos |

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
