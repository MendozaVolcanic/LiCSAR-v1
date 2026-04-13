# STATUS — LiCSAR-v1

## Estado actual (2026-04-12)
Infraestructura completa. Pendiente: primer run de frame_finder para generar catálogo.

## Objetivo
Dashboard de deformación InSAR para 43 volcanes chilenos usando frames públicos del portal COMET/JASMIN.

## Completado
- `frame_finder.py` — descubre frames LiCSAR para cada volcán via JASMIN HTML scraping
- `licsar_downloader.py` — descarga PNG thumbnails (geo.unw.png + geo.cc.png), sin GeoTIFF
- `.github/workflows/licsar.yml` — frame_finder lunes 06:00 UTC, downloader lun+jue 08:00 UTC
- `docs/index.html` — sidebar por zona, panel detalle, guía InSAR, zoom modal

## Pendiente CRÍTICO
- **`datos/frames_volcanes.json` no existe** — frame_finder.py nunca se ha ejecutado
- Sin este archivo licsar_downloader.py falla. Opciones:
  ```bash
  python frame_finder.py --test   # solo primeros 3 volcanes (prueba rápida)
  python frame_finder.py          # todos los 43
  ```
  O hacer push al repo y esperar el workflow del lunes 06:00 UTC.

## Pendiente menor
- GitHub Pages: activar en Settings → Pages → main/docs

## Arquitectura
```
datos/frames_volcanes.json       ← generado por frame_finder.py (FALTA)
docs/licsar/{Volcan}/
    asc_unw.png / asc_coh.png   ← fase + coherencia ascendente
    desc_unw.png / desc_coh.png ← fase + coherencia descendente
docs/licsar/catalog.json         ← índice de disponibilidad
```

## Notas técnicas
- JASMIN portal accesible sin auth desde GitHub Actions
- PNG thumbnails ~1-2 MB vs GeoTIFF ~17 MB (10x ahorro espacio)
- 8 volcanes prioritarios × 2 dirs × 2 PNGs ≈ 32-64 MB total
- Decorrelación alta en volcanes del sur (vegetación/nieve)
