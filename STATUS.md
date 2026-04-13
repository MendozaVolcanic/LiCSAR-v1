# STATUS — LiCSAR-v1

## Estado actual (2026-04-13)
Pipeline completo funcionando. 43/43 volcanes con datos InSAR en el dashboard.

## Objetivo
Dashboard de deformación InSAR para 43 volcanes chilenos usando frames públicos del portal COMET/JASMIN.

## Completado
- `frame_finder.py` — descubre frames LiCSAR via ASF API + JASMIN, guarda frame_id real
- `licsar_downloader.py` — descarga PNG thumbnails (geo.unw.png + geo.cc.png) desde CEDA/JASMIN
- `.github/workflows/licsar.yml` — frame_finder lunes 06:00 UTC, downloader lun+jue 08:00 UTC
- `docs/index.html` — sidebar por zona, panel detalle, guía InSAR, zoom modal
- `datos/frames_volcanes.json` — catálogo de tracks para los 43 volcanes
- `docs/licsar/catalog.json` — índice de disponibilidad con rutas a PNGs
- 170 PNGs descargados (43 volcanes × ASC+DESC × unw+coh)

## Bugs corregidos (sesión 2026-04-13)
- ASF API: WKT usaba `+` en lugar de espacio → error 400
- ASF API: respuesta envuelta en `[[...]]`, campos `relativeOrbit`/`granuleName`
- frame_finder: no guardaba `frame_id` en el JSON → downloader saltaba todo
- JASMIN: pares de interferogramas sin `/` final en HTML → regex fallaba
- URLs de PNGs: cada frame tiene su propia base URL en CEDA o LiCSAR_products.public

## Pendiente menor
- GitHub Pages: activar en Settings → Pages → main/docs (para URL pública)
- 4 volcanes del norte (Taapaca, Parinacota, Guallatiri, Isluga) sin DESC:
  track 054D existe en JASMIN pero sin interferogramas disponibles

## Arquitectura
```
datos/frames_volcanes.json       ← generado por frame_finder.py
datos/frames_volcanes.csv        ← resumen tabular
docs/licsar/{Volcan}/
    asc_unw.png / asc_coh.png   ← fase + coherencia ascendente
    desc_unw.png / desc_coh.png ← fase + coherencia descendente
docs/licsar/catalog.json         ← índice de disponibilidad
docs/index.html                  ← dashboard web
```

## Notas técnicas
- JASMIN portal accesible sin auth desde GitHub Actions
- PNGs servidos desde CEDA (data.ceda.ac.uk) o LiCSAR_products.public según el frame
- URLs de PNGs extraídas del listing de cada par (no construidas a mano)
- 8 volcanes prioritarios × 2 dirs × 2 PNGs ≈ 32-64 MB total
- Decorrelación alta en volcanes del sur (vegetación/nieve)
- Dashboard requiere servidor HTTP (no funciona con file://) → `python -m http.server 8765`
