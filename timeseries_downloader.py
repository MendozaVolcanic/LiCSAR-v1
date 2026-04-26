#!/usr/bin/env python3
"""
timeseries_downloader.py — Descarga series temporales LiCSBAS desde COMET VolcanoDB.

Para cada volcán mapeado en `comet_downloader.NOMBRE_A_COMET`, descarga el JSON
de desplazamiento (~22MB) desde:
  https://comet-volcanodb.org/data/disp_data[/_gacos]/south_america/{key}_{frame}_web_x100_filt.json

y lo reduce a una serie temporal pequeña (~5KB) en:
  docs/licsar/{Volcán_safe}/timeseries.json

Reducción:
  - ROI cuadrado central 20x20 (filas 40:60, cols 40:60)
  - Filtra por máscara (mask==1) y descarta nulls
  - Promedio espacial por fecha -> los_cm_filt[N]
  - Velocidad lineal cm/año por regresión simple
  - Cambio últimos 180 días

Uso:
  python timeseries_downloader.py                     # todos los volcanes
  python timeseries_downloader.py --test              # solo 3 volcanes
  python timeseries_downloader.py --volcan "Lascar"   # uno solo
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Reutiliza el mapping y funciones existentes
from comet_downloader import (
    NOMBRE_A_COMET,
    cargar_comet_frames,
    mapear_volcanes,
    safe_dir_name,
)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR / "docs" / "licsar"
CATALOG_PATH = DOCS_DIR / "catalog.json"

REGION = "south_america"
TIMESERIES_BASE = "https://comet-volcanodb.org/data/disp_data"
TIMESERIES_GACOS_BASE = "https://comet-volcanodb.org/data/disp_data_gacos"

REQUEST_TIMEOUT = 120
DELAY = 1.5
MAX_RETRIES = 2

# ROI cuadrado central
ROI_R0, ROI_R1 = 40, 60
ROI_C0, ROI_C1 = 40, 60

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, */*",
}

TEST_VOLCANES = ["Laguna del Maule", "Lascar", "Villarrica"]


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------

def fetch_disp_json(comet_key: str, frame_id: str, gacos: bool = False):
    """
    Descarga el JSON de desplazamiento desde COMET.
    Retorna (data, url, status_code, size_bytes) o (None, url, status, 0).
    """
    base = TIMESERIES_GACOS_BASE if gacos else TIMESERIES_BASE
    url = f"{base}/{REGION}/{comet_key}_{frame_id}_web_x100_filt.json"

    last_status = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS, stream=True)
            last_status = r.status_code
            if r.status_code == 404:
                return None, url, 404, 0
            if r.status_code != 200:
                print(f"    WARN HTTP {r.status_code} en {url}")
                if attempt < MAX_RETRIES:
                    time.sleep(2)
                    continue
                return None, url, r.status_code, 0
            content = r.content
            size = len(content)
            try:
                data = json.loads(content.decode("utf-8"))
            except MemoryError:
                print(f"    ERROR: MemoryError parseando {url}")
                return None, url, r.status_code, size
            return data, url, r.status_code, size
        except requests.exceptions.Timeout:
            print(f"    timeout, reintentando ({attempt+1}/{MAX_RETRIES})...")
            time.sleep(3)
        except Exception as e:
            print(f"    ERROR: {e}")
            break
    return None, url, last_status or 0, 0


# ---------------------------------------------------------------------------
# Reducción de cubo a serie temporal
# ---------------------------------------------------------------------------

def _date_to_ordinal(date_str: str) -> int:
    return datetime.strptime(date_str, "%Y-%m-%d").toordinal()


def reducir_cubo(data: dict) -> tuple[list[float], int]:
    """
    Promedio espacial por fecha sobre el ROI 40:60 x 40:60, usando mask==1
    y descartando None/null. Retorna (serie[N], px_validos).
    """
    cubo = data.get("data_filt") or data.get("data") or []
    mask = data.get("mask") or []
    n = len(cubo)
    if n == 0:
        return [], 0

    # Construir lista de coordenadas válidas según máscara
    coords = []
    for i in range(ROI_R0, ROI_R1):
        if i >= len(mask):
            continue
        row_mask = mask[i]
        for j in range(ROI_C0, ROI_C1):
            if j >= len(row_mask):
                continue
            m = row_mask[j]
            if m and m != 0:
                coords.append((i, j))

    serie: list[float] = []
    for k in range(n):
        slab = cubo[k]
        suma = 0.0
        cnt = 0
        for (i, j) in coords:
            if i >= len(slab):
                continue
            row = slab[i]
            if j >= len(row):
                continue
            val = row[j]
            if val is None:
                continue
            try:
                fv = float(val)
            except (TypeError, ValueError):
                continue
            suma += fv
            cnt += 1
        serie.append(suma / cnt if cnt > 0 else 0.0)

    # Re-referenciar a primer valor (desplazamiento relativo)
    if serie:
        ref = serie[0]
        serie = [round(v - ref, 4) for v in serie]
    return serie, len(coords)


def velocidad_lineal(dates: list[str], serie: list[float]) -> float:
    """Regresión lineal simple cm/año."""
    if len(dates) < 2 or len(serie) < 2:
        return 0.0
    xs = [_date_to_ordinal(d) for d in dates]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(serie) / n
    num = sum((xs[i] - mx) * (serie[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    slope_per_day = num / den
    return round(slope_per_day * 365.25, 4)


def delta_180d(dates: list[str], serie: list[float]) -> float:
    """Cambio (cm) entre la última fecha y la fecha más cercana hace 180 días."""
    if not dates or not serie:
        return 0.0
    last_ord = _date_to_ordinal(dates[-1])
    target = last_ord - 180
    # buscar índice más cercano <= target
    idx = 0
    for i, d in enumerate(dates):
        if _date_to_ordinal(d) <= target:
            idx = i
        else:
            break
    return round(serie[-1] - serie[idx], 4)


# ---------------------------------------------------------------------------
# Procesamiento por volcán
# ---------------------------------------------------------------------------

def procesar_volcan(nombre: str, comet_key: str, frame_id: str) -> dict | None:
    print(f"  Frame: {frame_id}")
    print(f"  Descargando disp_data (filt)...")
    data, url, status, size = fetch_disp_json(comet_key, frame_id, gacos=False)
    print(f"    GET {url}")
    print(f"    -> HTTP {status}, {size/1024/1024:.2f} MB")

    if data is None:
        # Intentar GACOS como fallback principal
        print(f"  Intentando disp_data_gacos...")
        data, url2, status2, size2 = fetch_disp_json(comet_key, frame_id, gacos=True)
        print(f"    GET {url2}")
        print(f"    -> HTTP {status2}, {size2/1024/1024:.2f} MB")
        if data is None:
            print(f"  Sin datos disponibles")
            return None

    dates = data.get("dates", [])
    if not dates:
        print(f"  JSON sin campo 'dates'")
        return None

    print(f"  N fechas: {len(dates)} ({dates[0]} -> {dates[-1]})")

    serie_filt, px_validos = reducir_cubo(data)
    print(f"  Píxeles ROI válidos: {px_validos}")
    print(f"  Primeros 5 valores los_cm_filt: {serie_filt[:5]}")

    vel = velocidad_lineal(dates, serie_filt)
    d180 = delta_180d(dates, serie_filt)
    print(f"  Velocidad: {vel} cm/año | Delta 180d: {d180} cm")

    # Intentar también GACOS como complemento (solo si la versión principal era filt)
    serie_gacos = None
    if "disp_data_gacos" not in url:
        time.sleep(DELAY)
        print(f"  Intentando complemento GACOS...")
        data_g, url_g, status_g, size_g = fetch_disp_json(comet_key, frame_id, gacos=True)
        print(f"    GET {url_g} -> HTTP {status_g}, {size_g/1024/1024:.2f} MB")
        if data_g is not None:
            dates_g = data_g.get("dates", [])
            if dates_g == dates:
                serie_g, _ = reducir_cubo(data_g)
                if serie_g:
                    serie_gacos = serie_g
            else:
                print(f"    GACOS tiene fechas distintas, omitido")

    gaps = data.get("gaps", []) or []

    out = {
        "volcan": nombre,
        "frame": frame_id,
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "fuente": "COMET LiCSBAS x100 filt",
        "n_fechas": len(dates),
        "rango_fechas": [dates[0], dates[-1]],
        "roi": {
            "row_min": ROI_R0,
            "row_max": ROI_R1,
            "col_min": ROI_C0,
            "col_max": ROI_C1,
            "px_validos": px_validos,
        },
        "dates": dates,
        "los_cm_filt": serie_filt,
        "los_cm_gacos": serie_gacos,
        "velocity_cm_yr": vel,
        "delta_cm_180d": d180,
        "n_gaps": len(gaps),
    }

    out_dir = DOCS_DIR / safe_dir_name(nombre)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "timeseries.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Escrito: {out_path} ({out_path.stat().st_size/1024:.1f} KB)")

    return out


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

def cargar_catalog() -> dict:
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"volcanes": {}, "actualizado": "", "fuente": ""}


def guardar_catalog(catalog: dict) -> None:
    CATALOG_PATH.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nCatálogo actualizado: {CATALOG_PATH}")


def frame_id_para(nombre: str, catalog: dict, comet_db: dict) -> tuple[str, str] | None:
    """
    Intenta obtener (comet_key, frame_id):
      1) desde catalog.json -> volcanes[nombre].comet.frame
      2) desde el catálogo COMET dinámico (frame de mayor size)
    """
    vol = catalog.get("volcanes", {}).get(nombre, {})
    comet_meta = vol.get("comet") if isinstance(vol, dict) else None
    if comet_meta and comet_meta.get("frame") and comet_meta.get("key"):
        return comet_meta["key"], comet_meta["frame"]

    comet_key = NOMBRE_A_COMET.get(nombre)
    if not comet_key or comet_key not in comet_db:
        # buscar substring
        cands = [k for k in comet_db if comet_key and (comet_key in k or k in comet_key)]
        if not cands:
            return None
        comet_key = cands[0]
    frames = comet_db[comet_key].get("frames", [])
    if not frames:
        return None
    frame = max(frames, key=lambda f: f.get("size", 0))
    return comet_key, frame["id"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> tuple[bool, str | None]:
    test = "--test" in argv
    volcan = None
    if "--volcan" in argv:
        i = argv.index("--volcan")
        if i + 1 < len(argv):
            volcan = argv[i + 1]
    return test, volcan


def main() -> int:
    test_mode, volcan_filter = parse_args(sys.argv[1:])

    print(f"\n{'='*60}")
    print(f"TIMESERIES DOWNLOADER — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    catalog = cargar_catalog()
    comet_db = cargar_comet_frames()
    if not comet_db:
        print("ERROR: no se pudo cargar el catálogo COMET")
        return 1

    mapping = mapear_volcanes(comet_db)
    nombres = list(mapping.keys())

    if volcan_filter:
        nombres = [n for n in nombres if n == volcan_filter]
        if not nombres:
            print(f"ERROR: volcán '{volcan_filter}' no encontrado en mapping COMET")
            return 1
    elif test_mode:
        nombres = [n for n in nombres if n in TEST_VOLCANES]
        print(f"Modo test: {nombres}\n")

    procesados = 0
    fallidos = 0
    for i, nombre in enumerate(nombres, 1):
        print(f"[{i}/{len(nombres)}] {nombre}")
        info = frame_id_para(nombre, catalog, comet_db)
        if not info:
            print(f"  Sin frame COMET\n")
            fallidos += 1
            continue
        comet_key, frame_id = info
        try:
            res = procesar_volcan(nombre, comet_key, frame_id)
        except Exception as e:
            print(f"  ERROR: {e}")
            res = None
        if res:
            procesados += 1
            vol = catalog.setdefault("volcanes", {}).setdefault(nombre, {"nombre": nombre})
            comet_block = vol.setdefault("comet", {})
            comet_block["key"] = comet_key
            comet_block["frame"] = frame_id
            comet_block["timeseries"] = True
        else:
            fallidos += 1
        print()
        time.sleep(DELAY)

    catalog["actualizado"] = datetime.now(timezone.utc).isoformat()
    guardar_catalog(catalog)

    print(f"\n{'='*60}")
    print(f"RESUMEN: {procesados} procesados | {fallidos} fallidos")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
