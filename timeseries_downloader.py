#!/usr/bin/env python3
"""
timeseries_downloader.py — Descarga series temporales LiCSBAS desde COMET VolcanoDB.

Para cada volcán mapeado en `comet_downloader.NOMBRE_A_COMET`, descarga el JSON
de desplazamiento (~22MB) desde:
  https://comet-volcanodb.org/data/disp_data[/_gacos]/south_america/{key}_{frame}_web_x100_filt.json

y lo reduce a una serie temporal pequeña (~5KB) en:
  docs/licsar/{Volcán_safe}/timeseries.json

IMPORTANTE — qué dato es "nuestro" y qué dato es de COMET:
  - El CUBO de desplazamiento (data_filt) es de COMET y NUNCA se modifica.
  - La SERIE 1D, la velocidad, la incertidumbre y los flags de calidad son
    productos DERIVADOS que calcula este script. Si están mal, es nuestro
    cálculo el que se corrige, no el dato de origen.

Reducción (productos derivados):
  - ROI ~20x20 px CENTRADO EN EL CRÁTER (usa lat/lon del volcán + grillas x/y
    del JSON), no en el centro geométrico del frame.
  - Filtra por máscara (mask==1) y descarta nulls.
  - Re-referencia a la mediana de los primeros N puntos (robusta a 1 outlier).
  - Velocidad robusta por Theil-Sen (mediana de pendientes pareadas).
  - Incertidumbre y significancia por OLS (error estándar, t-stat, R2).
  - Flag `velocity_significativa` = |t|>=2 y n suficiente y pocos gaps.
  - Latencia: días desde la última observación.
  - GACOS validado: se descarta si es todo cero/None.

Uso:
  python timeseries_downloader.py                     # todos los volcanes
  python timeseries_downloader.py --test              # solo 3 volcanes
  python timeseries_downloader.py --volcan "Lascar"   # uno solo
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Configuración y utilidades compartidas
from licsar_common import (
    DOCS_DIR,
    CATALOG_PATH,
    REGION,
    TIMESERIES_BASE,
    TIMESERIES_GACOS_BASE,
    COMET_SCALE,
    HEADERS,
    MAX_RETRIES,
    NOMBRE_A_COMET,
    TEST_VOLCANES,
    safe_dir_name,
    cargar_comet_frames,
    mapear_volcanes,
    cargar_catalog,
    guardar_catalog,
)

# ---------------------------------------------------------------------------
# Configuración específica de este script
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 120   # los JSON de desplazamiento pesan ~22 MB
DELAY = 1.5

# ROI: semilado en píxeles alrededor del cráter (ventana ~21x21)
ROI_HALF = 10
# Semilados a probar progresivamente si la cumbre está decorrelacionada (sin
# píxeles coherentes en la ventana ajustada). Crecer permite recuperar señal de
# flancos coherentes antes de declarar "sin datos".
ROI_HALF_STEPS = [10, 15, 22]
# Mínimo de píxeles coherentes para considerar la serie utilizable
MIN_PIXELS = 5
# Fallback cuando no hay lat/lon o grillas x/y: centro geométrico del frame
ROI_FALLBACK = (40, 60, 40, 60)

# Umbrales de calidad para declarar una velocidad como significativa/confiable
MIN_FECHAS = 20        # menos épocas -> tendencia no confiable
MAX_GAPS = 3           # demasiados huecos -> serie discontinua
T_SIGNIF = 2.0         # |t| >= 2 ~ 95% de confianza para n moderado
REF_N = 5              # nº de puntos iniciales para la referencia robusta


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


def roi_centrado(data: dict, lat: float | None, lon: float | None, half: int = ROI_HALF):
    """
    Devuelve (r0, r1, c0, c1) de una ventana cuadrada de semilado `half` px
    CENTRADA en el cráter.

    Fenómeno: el frame LiCSAR cubre ~250 km; el centro geométrico del recorte
    100x100 no necesariamente coincide con el edificio volcánico. Promediar un
    ROI fijo en el centro puede caer sobre roca estable y dar "deformación" que
    en realidad es ruido instrumental. Aquí ubicamos el píxel más cercano a las
    coordenadas reales del cráter usando las grillas de lon (x) y lat (y).
    """
    xs = data.get("x") or []   # longitudes por columna
    ys = data.get("y") or []   # latitudes por fila
    if not xs or not ys or lat is None or lon is None:
        return ROI_FALLBACK
    ci = min(range(len(xs)), key=lambda k: abs(xs[k] - lon))   # columna ~ lon
    ri = min(range(len(ys)), key=lambda k: abs(ys[k] - lat))   # fila ~ lat
    r0 = max(0, ri - half)
    r1 = min(len(ys), ri + half + 1)
    c0 = max(0, ci - half)
    c1 = min(len(xs), ci + half + 1)
    return r0, r1, c0, c1


def reducir_con_roi_adaptativo(data: dict, lat: float | None, lon: float | None):
    """
    Reduce el cubo probando ventanas crecientes hasta juntar >= MIN_PIXELS
    coherentes. Retorna (serie, px_validos, roi, centrado, half_usado).

    Si ni la ventana más amplia tiene píxeles coherentes, la cumbre está
    decorrelacionada (típico en volcanes con nieve/vegetación permanente) y la
    serie no es utilizable -> px_validos quedará 0 y se marcará 'sin_datos'.
    """
    centrado = (data.get("x") and data.get("y") and lat is not None and lon is not None)
    if not centrado:
        serie, px = reducir_cubo(data, ROI_FALLBACK)
        return serie, px, ROI_FALLBACK, False, None
    mejor = ([], 0, None, None)
    for half in ROI_HALF_STEPS:
        roi = roi_centrado(data, lat, lon, half=half)
        serie, px = reducir_cubo(data, roi)
        if px > mejor[1]:
            mejor = (serie, px, roi, half)
        if px >= MIN_PIXELS:
            return serie, px, roi, True, half
    serie, px, roi, half = mejor
    return serie, px, roi or ROI_FALLBACK, True, half


def reducir_cubo(data: dict, roi: tuple[int, int, int, int]) -> tuple[list[float], int]:
    """
    Promedio espacial por fecha sobre el ROI dado, usando mask==1 y descartando
    None/null. Retorna (serie[N], px_validos).

    Referencia robusta: el cubo de COMET ya está referenciado a su `refarea`,
    pero re-referenciar a un único primer valor ruidoso sesga toda la serie.
    Usamos la mediana de los primeros REF_N puntos como cero relativo.
    """
    cubo = data.get("data_filt") or data.get("data") or []
    mask = data.get("mask") or []
    r0, r1, c0, c1 = roi
    n = len(cubo)
    if n == 0:
        return [], 0

    coords = []
    for i in range(r0, r1):
        if i >= len(mask):
            continue
        row_mask = mask[i]
        for j in range(c0, c1):
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
        # Escalar a cm reales (COMET almacena cambio de rango LOS x100)
        serie.append((suma / cnt) / COMET_SCALE if cnt > 0 else 0.0)

    # Referencia robusta: mediana de los primeros REF_N puntos (no 1 solo punto)
    if serie:
        ref = statistics.median(serie[:min(REF_N, len(serie))])
        serie = [round(v - ref, 4) for v in serie]
    return serie, len(coords)


def _theil_sen(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """
    Pendiente robusta de Theil-Sen = mediana de las pendientes de todos los
    pares de puntos. Inmune a outliers (las primeras adquisiciones ruidosas de
    Sentinel-1 ya no dominan el ajuste, como sí pasaba con mínimos cuadrados).
    Retorna (pendiente_por_dia, intercepto).
    """
    n = len(xs)
    slopes = []
    for i in range(n):
        xi, yi = xs[i], ys[i]
        for j in range(i + 1, n):
            dx = xs[j] - xi
            if dx != 0:
                slopes.append((ys[j] - yi) / dx)
    if not slopes:
        return 0.0, (ys[0] if ys else 0.0)
    slope = statistics.median(slopes)
    intercept = statistics.median([ys[i] - slope * xs[i] for i in range(n)])
    return slope, intercept


def _ols_stats(xs: list[float], ys: list[float]) -> tuple[float, float, float] | None:
    """
    Mínimos cuadrados para cuantificar incertidumbre de la pendiente.
    Retorna (se_pendiente_por_dia, t_stat, r2) o None si n<3.
    """
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    syy = sum((y - my) ** 2 for y in ys)
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_res = sum((ys[i] - (slope * xs[i] + intercept)) ** 2 for i in range(n))
    r2 = (1 - ss_res / syy) if syy > 0 else 0.0
    s2 = ss_res / (n - 2)
    se_slope = (s2 / sxx) ** 0.5 if s2 > 0 else 0.0
    t_stat = slope / se_slope if se_slope > 0 else 0.0
    return se_slope, t_stat, r2


def velocidad_robusta(dates: list[str], serie: list[float]) -> dict:
    """
    Velocidad de deformación con incertidumbre.

    Reporta la velocidad robusta (Theil-Sen) como titular, y el error estándar /
    t-stat / R2 de OLS como medida de confianza. Un geólogo necesita saber no
    solo "cuánto" sino "qué tan seguro": una pendiente con |t|<2 es indistinguible
    de cero (sin deformación detectable).
    """
    out = {
        "velocity_cm_yr": 0.0,
        "velocity_se_cm_yr": None,
        "velocity_tstat": None,
        "r2": None,
    }
    if len(dates) < 2 or len(serie) < 2:
        return out
    xs = [float(_date_to_ordinal(d)) for d in dates]
    slope_day, _ = _theil_sen(xs, serie)
    out["velocity_cm_yr"] = round(slope_day * 365.25, 3)
    stats = _ols_stats(xs, serie)
    if stats:
        se_day, t_stat, r2 = stats
        out["velocity_se_cm_yr"] = round(se_day * 365.25, 3)
        out["velocity_tstat"] = round(t_stat, 2)
        out["r2"] = round(r2, 3)
    return out


def delta_180d(dates: list[str], serie: list[float]) -> tuple[float, int]:
    """
    Cambio (cm) en ~180 días. Retorna (delta, dias_reales_en_ventana).

    Como los pares no son uniformes (decorrelación estacional: nieve/vegetación
    en invierno austral), informamos también cuántos días reales abarca la
    ventana, para no llamar "180 días" a algo que en realidad son 300.
    """
    if not dates or not serie:
        return 0.0, 0
    last_ord = _date_to_ordinal(dates[-1])
    target = last_ord - 180
    idx = 0
    for i, d in enumerate(dates):
        if _date_to_ordinal(d) <= target:
            idx = i
        else:
            break
    dias_reales = last_ord - _date_to_ordinal(dates[idx])
    return round(serie[-1] - serie[idx], 4), dias_reales


def gacos_valido(serie: list[float] | None) -> bool:
    """True si la serie GACOS tiene señal real (no todo cero/None)."""
    if not serie:
        return False
    no_cero = [v for v in serie if v is not None and abs(v) > 1e-9]
    return len(no_cero) >= max(3, len(serie) // 10)


# ---------------------------------------------------------------------------
# Descomposición ascendente + descendente -> vertical + este
# ---------------------------------------------------------------------------

def direccion_frame(frame_id: str) -> str | None:
    """Devuelve 'A' (ascendente) o 'D' (descendente) según el frame_id LiCSAR."""
    if not frame_id:
        return None
    track = frame_id.split("_")[0]   # p.ej. "018A"
    if track.endswith("A"):
        return "A"
    if track.endswith("D"):
        return "D"
    return None


def frames_por_direccion(comet_key: str, comet_db: dict) -> dict:
    """
    Retorna {'A': frame_id_ascendente, 'D': frame_id_descendente} eligiendo el
    frame de mayor tamaño (mejor coherencia) por dirección. Ignora frames _dev.
    """
    frames = comet_db.get(comet_key, {}).get("frames", [])
    por_dir = {"A": [], "D": []}
    for f in frames:
        fid = f.get("id", "")
        if "_dev" in fid:
            continue
        d = direccion_frame(fid)
        if d in por_dir:
            por_dir[d].append(f)
    out = {}
    for d, lst in por_dir.items():
        if lst:
            out[d] = max(lst, key=lambda f: f.get("size", 0))["id"]
    return out


def vector_los_crater(data: dict, lat: float | None, lon: float | None) -> dict | None:
    """
    Vector unitario de línea de visión (e, n, u) en el píxel del cráter.
    Es la dirección con la que el satélite "ve" el suelo; permite proyectar el
    movimiento 3D a LOS (y viceversa al invertir asc+desc).
    """
    xs = data.get("x") or []
    ys = data.get("y") or []
    if not xs or not ys or lat is None or lon is None:
        return None
    ci = min(range(len(xs)), key=lambda k: abs(xs[k] - lon))
    ri = min(range(len(ys)), key=lambda k: abs(ys[k] - lat))

    def comp(key):
        arr = data.get(key)
        try:
            return float(arr[ri][ci])
        except (TypeError, ValueError, IndexError):
            return None

    e, n, u = comp("e_geo"), comp("n_geo"), comp("u_geo")
    if None in (e, n, u):
        return None
    return {"e": e, "n": n, "u": u}


def descomponer_vertical_este(vel_asc: float, vec_asc: dict,
                              vel_desc: float, vec_desc: dict) -> dict | None:
    """
    Separa velocidad LOS ascendente + descendente en vertical (U) y este (E).

    Fenómeno: un único interferograma mide solo la proyección del movimiento 3D
    sobre la línea de visión. Con dos geometrías (asc + desc) y despreciando la
    componente N-S (InSAR es casi ciego al norte-sur por la órbita casi polar:
    |n_geo| ~ 0.16), se resuelve un sistema 2x2:
        vel_LOS = e * vE + u * vU
    Retorna {vertical_cm_yr, este_cm_yr} o None si la geometría es degenerada.
    """
    if vel_asc is None or vel_desc is None or not vec_asc or not vec_desc:
        return None
    ea, ua = vec_asc["e"], vec_asc["u"]
    ed, ud = vec_desc["e"], vec_desc["u"]
    det = ea * ud - ed * ua
    if abs(det) < 1e-6:
        return None
    vE = (vel_asc * ud - vel_desc * ua) / det
    vU = (ea * vel_desc - ed * vel_asc) / det
    return {"vertical_cm_yr": round(vU, 3), "este_cm_yr": round(vE, 3)}


# ---------------------------------------------------------------------------
# Procesamiento por volcán
# ---------------------------------------------------------------------------

def procesar_volcan(nombre: str, comet_key: str, frame_id: str,
                    lat: float | None = None, lon: float | None = None,
                    comet_db: dict | None = None) -> dict | None:
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

    # Guarda geográfica: el frame elegido DEBE contener el cráter. Si no, es un
    # mal-mapeo (nombre ambiguo) y estaríamos mostrando otro volcán. No escribir.
    xs, ys = data.get("x") or [], data.get("y") or []
    if lat is not None and lon is not None and xs and ys:
        dentro = (min(xs) <= lon <= max(xs)) and (min(ys) <= lat <= max(ys))
        if not dentro:
            print(f"  ⚠ El cráter ({lat:.3f},{lon:.3f}) NO está en el frame "
                  f"(lon[{min(xs):.2f},{max(xs):.2f}] lat[{min(ys):.2f},{max(ys):.2f}]). "
                  f"Mal-mapeo: se descarta.")
            return None

    print(f"  N fechas: {len(dates)} ({dates[0]} -> {dates[-1]})")

    # ROI centrado en el cráter (no en el centro del frame), con expansión
    # adaptativa si la cumbre está decorrelacionada.
    serie_filt, px_validos, roi, centrado, half_usado = reducir_con_roi_adaptativo(data, lat, lon)
    sin_datos = px_validos < MIN_PIXELS
    print(f"  ROI filas {roi[0]}:{roi[1]} cols {roi[2]}:{roi[3]} "
          f"({'centrado en cráter' if centrado else 'FALLBACK centro frame'}"
          f"{f', semilado {half_usado}' if half_usado else ''})")
    print(f"  Píxeles ROI válidos: {px_validos}" + ("  [SIN DATOS COHERENTES]" if sin_datos else ""))
    print(f"  Primeros 5 valores los_cm_filt: {serie_filt[:5]}")

    if sin_datos:
        vstats = {"velocity_cm_yr": None, "velocity_se_cm_yr": None,
                  "velocity_tstat": None, "r2": None}
        d180, dias_ventana = None, None
        print(f"  Cumbre decorrelacionada — serie no utilizable")
    else:
        vstats = velocidad_robusta(dates, serie_filt)
        d180, dias_ventana = delta_180d(dates, serie_filt)
        print(f"  Velocidad (Theil-Sen): {vstats['velocity_cm_yr']} cm/año "
              f"| SE {vstats['velocity_se_cm_yr']} | t {vstats['velocity_tstat']} | R2 {vstats['r2']}")
        print(f"  Delta ~180d: {d180} cm (ventana real {dias_ventana} días)")

    # Intentar también GACOS como complemento (solo si la versión principal era filt)
    serie_gacos = None
    gacos_ok = False
    if "disp_data_gacos" not in url:
        time.sleep(DELAY)
        print(f"  Intentando complemento GACOS...")
        data_g, url_g, status_g, size_g = fetch_disp_json(comet_key, frame_id, gacos=True)
        print(f"    GET {url_g} -> HTTP {status_g}, {size_g/1024/1024:.2f} MB")
        if data_g is not None:
            dates_g = data_g.get("dates", [])
            if dates_g == dates:
                roi_g = roi_centrado(data_g, lat, lon)
                serie_g, _ = reducir_cubo(data_g, roi_g)
                if gacos_valido(serie_g):
                    serie_gacos = serie_g
                    gacos_ok = True
                    print(f"    GACOS válido (con señal)")
                else:
                    print(f"    GACOS descartado (todo cero/None)")
            else:
                print(f"    GACOS tiene fechas distintas, omitido")

    # --- Descomposición vertical/este usando la geometría opuesta (asc + desc) ---
    # Un solo frame mide LOS (mezcla vertical+horizontal). Con la geometría opuesta
    # se separan vertical (U) y este (E). Solo si hay datos coherentes y coords.
    descomposicion = None
    geometrias = None
    dir_primaria = direccion_frame(frame_id)
    if comet_db is not None and not sin_datos and lat is not None and lon is not None:
        vec_primario = vector_los_crater(data, lat, lon)
        fdir = frames_por_direccion(comet_key, comet_db)
        dir_opuesta = "D" if dir_primaria == "A" else "A"
        frame_op = fdir.get(dir_opuesta)
        if frame_op and vec_primario:
            time.sleep(DELAY)
            print(f"  Descomposición: bajando geometría opuesta {frame_op} ({dir_opuesta})...")
            data_op, url_op, st_op, sz_op = fetch_disp_json(comet_key, frame_op, gacos=False)
            print(f"    GET {url_op} -> HTTP {st_op}, {sz_op/1024/1024:.2f} MB")
            if data_op is not None:
                serie_op, px_op, _, _, _ = reducir_con_roi_adaptativo(data_op, lat, lon)
                vec_op = vector_los_crater(data_op, lat, lon)
                if px_op >= MIN_PIXELS and vec_op:
                    v_op = velocidad_robusta(data_op.get("dates", []), serie_op)
                    geo_pri = {"frame": frame_id, "velocity_los_cm_yr": vstats["velocity_cm_yr"],
                               "px": px_validos, "e": round(vec_primario["e"], 4),
                               "u": round(vec_primario["u"], 4)}
                    geo_op = {"frame": frame_op, "velocity_los_cm_yr": v_op["velocity_cm_yr"],
                              "px": px_op, "e": round(vec_op["e"], 4), "u": round(vec_op["u"], 4)}
                    if dir_primaria == "A":
                        geo_a, geo_d = geo_pri, geo_op
                    else:
                        geo_a, geo_d = geo_op, geo_pri
                    descomposicion = descomponer_vertical_este(
                        geo_a["velocity_los_cm_yr"], {"e": geo_a["e"], "u": geo_a["u"]},
                        geo_d["velocity_los_cm_yr"], {"e": geo_d["e"], "u": geo_d["u"]})
                    geometrias = {"ascendente": geo_a, "descendente": geo_d}
                    if descomposicion:
                        print(f"    -> vertical {descomposicion['vertical_cm_yr']:+.3f} | "
                              f"este {descomposicion['este_cm_yr']:+.3f} cm/año")
                else:
                    print(f"    geometría opuesta sin píxeles coherentes; sin descomposición")
            else:
                print(f"    no se pudo bajar la geometría opuesta")
        else:
            print(f"  Sin geometría opuesta disponible (una sola dirección)")

    gaps = data.get("gaps", []) or []
    n_fechas = len(dates)
    n_gaps = len(gaps)

    # Latencia: días desde la última observación (¿está "en vivo"?)
    dias_latencia = (date.today() - datetime.strptime(dates[-1], "%Y-%m-%d").date()).days

    # Significancia: ¿la pendiente es distinguible de cero y hay datos suficientes?
    t = vstats.get("velocity_tstat")
    significativa = (
        not sin_datos
        and t is not None and abs(t) >= T_SIGNIF
        and n_fechas >= MIN_FECHAS
        and n_gaps <= MAX_GAPS
    )
    if sin_datos:
        calidad = "sin_datos"
    elif n_fechas < MIN_FECHAS:
        calidad = "insuficiente"
    elif n_gaps > MAX_GAPS:
        calidad = "discontinua"
    elif significativa:
        calidad = "significativa"
    else:
        calidad = "no_significativa"
    print(f"  Calidad: {calidad} | latencia {dias_latencia} días | gaps {n_gaps}")

    out = {
        "volcan": nombre,
        "frame": frame_id,
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "fuente": "COMET LiCSBAS x100 filt (serie/velocidad calculadas por LiCSAR-v1)",
        "n_fechas": n_fechas,
        "rango_fechas": [dates[0], dates[-1]],
        "dias_latencia": dias_latencia,
        "roi": {
            "row_min": roi[0],
            "row_max": roi[1],
            "col_min": roi[2],
            "col_max": roi[3],
            "px_validos": px_validos,
            "centrado_en_crater": centrado,
            "semilado_px": half_usado,
        },
        "sin_datos": sin_datos,
        "dates": dates,
        "los_cm_filt": serie_filt,
        "los_cm_gacos": serie_gacos,
        "gacos_valido": gacos_ok,
        "velocity_cm_yr": vstats["velocity_cm_yr"],
        "velocity_se_cm_yr": vstats["velocity_se_cm_yr"],
        "velocity_tstat": vstats["velocity_tstat"],
        "velocity_significativa": significativa,
        "r2": vstats["r2"],
        "calidad": calidad,
        "delta_cm_180d": d180,
        "delta_dias_reales": dias_ventana,
        "n_gaps": n_gaps,
        "metodo_velocidad": "Theil-Sen (robusto); SE/t/R2 por OLS",
        "geometria_primaria": dir_primaria,
        "geometrias": geometrias,
        "descomposicion": descomposicion,
    }

    out_dir = DOCS_DIR / safe_dir_name(nombre)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "timeseries.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Escrito: {out_path} ({out_path.stat().st_size/1024:.1f} KB)")

    return out


# cargar_catalog y guardar_catalog ahora viven en licsar_common (importados arriba)


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

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
        vol_meta = catalog.get("volcanes", {}).get(nombre, {})
        lat = vol_meta.get("lat")
        lon = vol_meta.get("lon")
        try:
            res = procesar_volcan(nombre, comet_key, frame_id, lat=lat, lon=lon, comet_db=comet_db)
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
