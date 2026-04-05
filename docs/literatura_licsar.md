# Literatura: InSAR para Deformacion Volcanica — COMET LiCSAR

## Sistema LiCSAR

### Acceso a Datos
- Portal principal: https://comet.nerc.ac.uk/comet-lics-portal/
- Portal volcanes: https://comet-volcanodb.org/
- Chile confirmado: volcanes chilenos indexados (Calbuco, Villarrica, etc.)
- Base URL descarga: https://gws-access.jasmin.ac.uk/public/nceo_geohazards/LiCSAR_products/
- NO hay API REST formal — acceso via HTTP directo + scripts Python
- 1,500+ frames globales, 470+ frames cubriendo 1,024 volcanes
- Volcanes activos: 3 actualizaciones/semana

### Productos de Datos
| Archivo | Descripcion | Formato |
|---------|------------|---------|
| geo.cc.tif | Coherencia (0-255) | GeoTIFF |
| geo.diff_pha.tif | Fase wrapped (-pi a pi) | GeoTIFF |
| geo.unw.tif | Fase unwrapped (SNAPHU) | GeoTIFF |
| geo.mli.tif | Intensidad multi-looked | GeoTIFF |
| sltd.geo.tif | Marea solida terrestre | GeoTIFF |
| ztd.geo.tif | Delay troposferico zenital | GeoTIFF |

### Resolucion
- 0.001 grados (~100m), multilooking 5x rango, 20x azimut
- DEM: SRTM 1 arc-segundo
- 3 interferogramas por epoca (estrategia small baseline)

### Frame ID: OOOP_AAAAA_BBBBBB
- OOO = orbita relativa (001-175)
- P = direccion: A (ascendente) o D (descendente)
- AAAAA = co-latitud x100
- BBBBBB = bursts por subswath IW

## Herramientas Python

### LiCSBAS2 (RECOMENDADO)
- GitHub: github.com/yumorishita/LiCSBAS2
- Version: v1.9.2 (Sep 2025)
- Descarga + inversion de serie temporal + velocidad
- NOTA: Step01 del LiCSBAS original se rompio en junio 2024

### LiCSAR-web-tools (Descarga)
- GitHub: github.com/matthew-gaddes/LiCSAR-web-tools
- `download_LiCSAR_portal_data(frameID, date_start, date_end)`
- Version: V1.1.1 (Feb 2025)

### LiCSAlert (Deteccion de Anomalias)
- GitHub: github.com/matthew-gaddes/LiCSAlert
- Deteccion automatica de cambios en deformacion volcanica via ICA
- Corre en JASMIN monitoreando mayoria de volcanes subaereos del mundo

### Alternativas
| Herramienta | Proposito | URL |
|-------------|----------|-----|
| MintPy | Series temporales SBAS | github.com/insarlab/MintPy |
| ASF HyP3 | Procesamiento on-demand ARIA-GUNW | hyp3-docs.asf.alaska.edu |
| PyGMTSAR | Pipeline InSAR completo en Python | github.com/AlexeyPechnikov/pygmtsar |
| asf_search | Busqueda/descarga Sentinel-1 | pypi.org/project/asf-search |

## Papers sobre Chile

### Villarrica, Llaima, Calbuco (2002-2015)
- Multi-satelite InSAR: Calbuco 2015 produjo 12 cm subsidencia co-eruptiva a 8-11 km profundidad
- Villarrica 2015: 5 cm uplift post-erupcion
- DOI: buscar en ScienceDirect 10.1016/j.jvolgeores.2017

### Laguna del Maule
- Monitoreo automatizado con MasTer toolbox
- Inflacion significativa de varios cm/ano

### Cordon Caulle
- Inflacion post-erupcion 2011-2012 descubierta por CEOS Latin America Pilot
- NO detectada por red sismica

### CEOS Latin America Pilot Project (2013-2017)
- InSAR regional de Mexico a Chile
- Trabajo directamente con SERNAGEOMIN
- DOI: 10.1186/s13617-018-0074-0

## Sentinel-1 en Chile
- S1A + S1C (lanzado dic 2024): revisita de 6 dias restaurada
- Chile cubierto por tracks ascendentes y descendentes
- Sur de Chile: problemas de decorrelacion por vegetacion/nieve
- Norte de Chile (Atacama): coherencia excelente

## NISAR (operativo desde Nov 2025)
- Banda L: penetra vegetacion y nubes mejor que banda C de Sentinel-1
- Datos gratuitos, revisita 12 dias
- Superior para volcanes boscosos del sur de Chile

## Items NO encontrados
- Lista completa de frames LiCSAR cubriendo los 43 volcanes chilenos
- Productos LiCSAR en NetCDF (solo GeoTIFF)
- Procesamiento on-demand LiCSAR para areas custom
