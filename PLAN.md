# LiCSAR-v1 — Plan de Proyecto

## Objetivo
Monitoreo automatizado de deformacion volcanica para 43 volcanes chilenos usando productos pre-procesados de COMET LiCSAR (Sentinel-1 InSAR).

## Por que importa
- La deformacion del suelo es uno de los precursores mas confiables de erupciones
- Cordon Caulle mostro inflacion NO detectada por sismica
- Calbuco: 12 cm subsidencia co-eruptiva documentada con InSAR
- LiCSAR procesa automaticamente — no necesitamos procesar SAR nosotros

## Arquitectura
```
COMET LiCSAR (procesado en JASMIN, productos GeoTIFF)
    |
    v
LiCSAR-v1/
├── config_volcanes.py        — 43 volcanes + frames Sentinel-1
├── frame_finder.py           — Identifica frames S1 por coordenadas
├── licsar_downloader.py      — Descarga interferogramas via HTTP
├── coherence_monitor.py      — Monitorea coherencia (cambios superficiales)
├── deformation_tracker.py    — Seguimiento de desplazamiento temporal
├── alert_generator.py        — Alertas por deformacion anomala
├── visualizador.py           — Interferogramas + series temporales
├── docs/index.html           — Dashboard GitHub Pages
└── .github/workflows/
    └── licsar.yml            — Workflow semanal (sync con LiCSAR)
```

## Fases

### Fase 1: Descubrimiento de frames (semana 1)
1. Identificar frames Sentinel-1 para cada uno de los 43 volcanes
2. Usar asf_search o portal COMET para mapear volcan→frame
3. Verificar cobertura ascendente + descendente
4. Documentar coherencia tipica por zona (norte vs sur)

### Fase 2: Pipeline de descarga (semana 2)
5. Implementar descarga automatica de interferogramas desde JASMIN
6. Descargar coherencia + fase wrapped + unwrapped
7. Organizar por volcan/fecha
8. Generar previsualizaciones PNG

### Fase 3: Series temporales (semana 3)
9. Implementar LiCSBAS2 para inversion de series temporales
10. Calcular velocidad de deformacion por volcan
11. Establecer baseline (velocidad normal)
12. Detectar cambios en tasa de deformacion

### Fase 4: Dashboard + alertas (semana 4)
13. Dashboard con interferogramas mas recientes por volcan
14. Series temporales interactivas de desplazamiento
15. Alertas cuando deformacion > umbral
16. Cross-reference con alertas termicas Copernicus-v1

## Dashboard
- Carpeta en Automatizacion web (no repo separado)
- Interferograma mas reciente por volcan
- Serie temporal de desplazamiento
- Mapa de velocidad de deformacion
- Indicador de coherencia (calidad de datos)

## Dependencias
- LiCSBAS2 o LiCSAR-web-tools (descarga)
- rasterio (lectura GeoTIFF)
- numpy, scipy (analisis)
- matplotlib (visualizacion)
- asf_search (descubrimiento de frames)
