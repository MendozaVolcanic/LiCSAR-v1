#!/usr/bin/env python3
"""
comet_downloader.py — Descarga interferogramas recortados del portal COMET VolcanoDB.

A diferencia de licsar_downloader.py (que descarga PNGs genéricos del frame completo),
este script descarga JPGs recortados al volcán específico desde comet-volcanodb.org.

Productos descargados:
  - Últimos N interferogramas como JPG (fase+coherencia combinados, ~96KB c/u)
  - Probabilidad de deformación (deep learning, 0-1)

Outputs:
  docs/licsar/{Volcán}/comet/{par_fechas}.jpg  — interferogramas recortados
  docs/licsar/catalog.json                     — catálogo actualizado con datos COMET

Uso:
  python comet_downloader.py              # todos los volcanes
  python comet_downloader.py --test       # solo 3 volcanes de prueba
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR / "docs" / "licsar"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

COMET_DATA_BASE = "https://comet-volcanodb.org/data"
COMET_IMGS_BASE = "https://comet-volcanodb.org/images/licsar_images"
COMET_FRAMES_URL = f"{COMET_DATA_BASE}/volcanoes_frames/volcanoes_frames.js"

REGION = "south_america"
REQUEST_TIMEOUT = 45
DELAY = 1.0
MAX_INTERFEROGRAMAS = 10  # últimos N pares a descargar
MAX_RETRIES = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "image/*, application/json, */*",
}

TEST_VOLCANES = ["Laguna del Maule", "Lascar", "Villarrica"]

# ---------------------------------------------------------------------------
# Mapping: nombre dashboard → posibles keys COMET
# ---------------------------------------------------------------------------
NOMBRE_A_COMET = {
    "Taapaca": "taapaca",
    "Parinacota": "parinacota",
    "Guallatiri": "guallatiri",
    "Isluga": "isluga",
    "Irruputuncu": "irruputuncu",
    "Ollague": "ollague",
    "San Pedro": "san_pedro",
    "Lascar": "lascar",
    "Tupungatito": "tupungatito",
    "San Jose": "san_jose",
    "Tinguiririca": "tinguiririca",
    "Planchon-Peteroa": "planchon-peteroa",
    "Descabezado Grande": "descabezado_grande",
    "Tatara-San Pedro": "tatara-san_pedro",
    "Laguna del Maule": "laguna_del_maule",
    "Nevado de Longavi": "nevado_de_longavi",
    "Nevados de Chillan": "nevados_de_chillan",
    "Antuco": "antuco",
    "Copahue": "copahue",
    "Callaqui": "callaqui",
    "Lonquimay": "lonquimay",
    "Llaima": "llaima",
    "Sollipulli": "sollipulli",
    "Villarrica": "villarrica",
    "Quetrupillan": "quetrupillan",
    "Lanin": "lanin",
    "Mocho-Choshuenco": "mocho-choshuenco",
    "Carran - Los Venados": "carran-los_venados",
    "Puyehue - Cordon Caulle": "puyehue_cordon_caulle",
    "Antillanca - Casablanca": "antillanca",
    "Osorno": "osorno",
    "Calbuco": "calbuco",
    "Hornopiren": "hornopiren",
    "Huequi": "huequi",
    "Michinmahuida": "michinmahuida",
    "Chaiten": "chaiten",
    "Corcovado": "corcovado",
    "Yate": "yate",
    "Melimoyu": "melimoyu",
    "Mentolat": "mentolat",
    "Maca": "maca",
    "Cay": "cay",
    "Hudson": "cerro_hudson",
}


def safe_dir_name(nombre: str) -> str:
    """Convierte nombre de volcán a nombre de directorio."""
    return nombre.replace(" ", "_").replace("-", "_")


# ---------------------------------------------------------------------------
# Funciones de descarga
# ---------------------------------------------------------------------------

def fetch_json(url: str) -> dict | None:
    """Descarga un JSON con reintentos."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            print(f"    WARN HTTP {r.status_code} en {url}")
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                print(f"    timeout, reintentando ({attempt+1}/{MAX_RETRIES})...")
                time.sleep(3)
            else:
                print(f"    timeout definitivo")
        except Exception as e:
            print(f"    ERROR: {e}")
            break
    return None


def descargar_jpg(url: str, dest: Path) -> bool:
    """Descarga un JPG. Retorna True si exitoso."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS, stream=True)
            if r.status_code != 200:
                return False
            dest.write_bytes(r.content)
            return True
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                time.sleep(2)
            else:
                return False
        except Exception:
            return False
    return False


# ---------------------------------------------------------------------------
# Catálogo COMET
# ---------------------------------------------------------------------------

def cargar_comet_frames() -> dict:
    """Descarga y parsea volcanoes_frames.js."""
    print("[1/4] Descargando catálogo COMET...")
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.get(COMET_FRAMES_URL, timeout=60, headers=HEADERS)
            if r.status_code == 200:
                text = r.text.replace("var volcanoes_frames = ", "")
                if text.endswith(";"):
                    text = text[:-1]
                data = json.loads(text)
                sa = {k: v for k, v in data.items()
                      if v.get("region") == REGION}
                print(f"    {len(sa)} volcanes sudamericanos en COMET")
                return sa
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                print(f"    timeout, reintentando...")
                time.sleep(5)
        except Exception as e:
            print(f"    ERROR: {e}")
    return {}


def mapear_volcanes(comet_db: dict) -> dict:
    """Mapea nuestros volcanes a keys COMET. Retorna {nombre_nuestro: (comet_key, frames)}."""
    mapping = {}
    for nombre, comet_key in NOMBRE_A_COMET.items():
        if comet_key in comet_db:
            frames = comet_db[comet_key].get("frames", [])
            mapping[nombre] = (comet_key, frames)
        else:
            # Buscar por substring
            found = [k for k in comet_db if comet_key in k or k in comet_key]
            if found:
                key = found[0]
                frames = comet_db[key].get("frames", [])
                mapping[nombre] = (key, frames)
    return mapping


# ---------------------------------------------------------------------------
# Procesamiento por volcán
# ---------------------------------------------------------------------------

def procesar_volcan_comet(nombre: str, comet_key: str, frames: list) -> dict | None:
    """Procesa un volcán: descarga interferogramas y probabilidad desde COMET."""
    if not frames:
        print(f"  Sin frames en COMET")
        return None

    # Seleccionar frame principal (el de mayor tamaño = más datos)
    frame = max(frames, key=lambda f: f.get("size", 0))
    frame_id = frame["id"]
    print(f"  Frame COMET: {frame_id} (size={frame.get('size', 0)//1024}KB)")

    # --- Interferogramas ---
    licsar_url = f"{COMET_DATA_BASE}/licsar_data/{REGION}/{comet_key}_{frame_id}.json"
    licsar_data = fetch_json(licsar_url)
    time.sleep(DELAY)

    interferogramas = []
    if licsar_data and licsar_data.get("count", 0) > 0:
        count = licsar_data["count"]
        dates = licsar_data.get("dates", [])
        images = licsar_data.get("images", [])
        print(f"  Interferogramas: {count} (desde {dates[0]} hasta {dates[-1]})")

        # Descargar últimos N
        n = min(MAX_INTERFEROGRAMAS, len(images))
        volcan_dir = DOCS_DIR / safe_dir_name(nombre) / "comet"
        volcan_dir.mkdir(parents=True, exist_ok=True)

        descargados = 0
        for i in range(len(images) - n, len(images)):
            img_name = images[i]
            date_pair = dates[i]
            # Normalizar par de fechas para filename
            par_clean = date_pair.replace(" - ", "_").replace("-", "")
            # Formato: YYYYMMDD_YYYYMMDD
            parts = date_pair.split(" - ")
            if len(parts) == 2:
                par_clean = parts[0].replace("-", "") + "_" + parts[1].replace("-", "")

            dest = volcan_dir / f"{par_clean}.jpg"
            img_url = f"{COMET_IMGS_BASE}/{REGION}/{comet_key}_{frame_id}/{img_name}"

            if not dest.exists() or dest.stat().st_size < 100:
                ok = descargar_jpg(img_url, dest)
                if ok:
                    descargados += 1
                time.sleep(DELAY * 0.5)
            else:
                descargados += 1  # ya existe

            interferogramas.append({
                "par": par_clean,
                "fecha": date_pair,
                "imagen": f"comet/{par_clean}.jpg",
            })

        print(f"  Descargados: {descargados}/{n} JPGs")
    else:
        print(f"  Sin datos de interferogramas en COMET")

    # --- Probabilidad de deformación ---
    prob_url = f"{COMET_DATA_BASE}/prob_data/{REGION}/{comet_key}_{frame_id}.json"
    prob_data = fetch_json(prob_url)
    time.sleep(DELAY)

    prob_deformacion = None
    prob_max_reciente = None
    if prob_data and prob_data.get("count", 0) > 0:
        means = prob_data.get("means", [])
        maxs = prob_data.get("maxs", [])
        if means:
            # Últimos 5 valores promedio
            recientes = means[-5:]
            prob_deformacion = max(recientes)
        if maxs:
            prob_max_reciente = max(maxs[-5:])
        print(f"  Probabilidad: mean={prob_deformacion:.3f}, max={prob_max_reciente:.3f}")
    else:
        print(f"  Sin datos de probabilidad")

    return {
        "key": comet_key,
        "frame": frame_id,
        "total_interferogramas": licsar_data.get("count", 0) if licsar_data else 0,
        "interferogramas": interferogramas,
        "prob_deformacion": prob_deformacion,
        "prob_max": prob_max_reciente,
    }


# ---------------------------------------------------------------------------
# Integración con catálogo existente
# ---------------------------------------------------------------------------

def cargar_catalog_existente() -> dict:
    """Carga el catalog.json existente (generado por licsar_downloader.py)."""
    catalog_path = DOCS_DIR / "catalog.json"
    if catalog_path.exists():
        with open(catalog_path, encoding="utf-8") as f:
            return json.load(f)
    return {"volcanes": {}, "actualizado": "", "fuente": ""}


def guardar_catalog(catalog: dict):
    """Guarda catalog.json actualizado."""
    catalog_path = DOCS_DIR / "catalog.json"
    catalog_path.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"\nCatálogo actualizado: {catalog_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    test_mode = "--test" in sys.argv

    print(f"\n{'='*60}")
    print(f"COMET DOWNLOADER — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Últimos {MAX_INTERFEROGRAMAS} interferogramas + probabilidad de deformación")
    print(f"{'='*60}\n")

    # 1. Descargar catálogo COMET
    comet_db = cargar_comet_frames()
    if not comet_db:
        print("ERROR: No se pudo descargar el catálogo COMET")
        return 1

    # 2. Mapear volcanes
    print("[2/4] Mapeando volcanes...")
    mapping = mapear_volcanes(comet_db)
    print(f"    {len(mapping)}/{len(NOMBRE_A_COMET)} volcanes encontrados en COMET")

    if test_mode:
        mapping = {k: v for k, v in mapping.items() if k in TEST_VOLCANES}
        print(f"    Modo test: {list(mapping.keys())}")
    print()

    # 3. Procesar volcanes
    print(f"[3/4] Procesando {len(mapping)} volcanes...")
    print("-" * 60)

    catalog = cargar_catalog_existente()
    con_datos = 0
    con_prob = 0

    for i, (nombre, (comet_key, frames)) in enumerate(mapping.items(), 1):
        print(f"[{i}/{len(mapping)}] {nombre}")
        resultado = procesar_volcan_comet(nombre, comet_key, frames)

        if resultado:
            # Merge datos COMET con bloque existente (preserva flags como timeseries:true)
            vol = catalog.setdefault("volcanes", {}).setdefault(nombre, {"nombre": nombre})
            comet_block = vol.setdefault("comet", {})
            comet_block.update(resultado)

            if resultado["interferogramas"]:
                con_datos += 1
            if resultado["prob_deformacion"] is not None:
                con_prob += 1

        print()

    # 4. Re-marcar flags timeseries:true escaneando archivos en disco
    # (defensa contra pérdida del flag por sync de workflow)
    ts_marcados = 0
    for nombre, vol in catalog.get("volcanes", {}).items():
        ts_path = DOCS_DIR / safe_dir_name(nombre) / "timeseries.json"
        if ts_path.exists():
            vol.setdefault("comet", {})["timeseries"] = True
            ts_marcados += 1
    if ts_marcados:
        print(f"  Flags timeseries re-marcados: {ts_marcados} volcanes")

    # 5. Guardar catálogo
    print(f"[4/4] Guardando catálogo...")
    catalog["actualizado"] = datetime.now(timezone.utc).isoformat()
    catalog["fuente_comet"] = "COMET VolcanoDB (comet-volcanodb.org)"
    guardar_catalog(catalog)

    # Resumen
    print(f"\n{'='*60}")
    print(f"RESUMEN: {con_datos} con interferogramas | {con_prob} con probabilidad")
    no_match = len(NOMBRE_A_COMET) - len(mapping)
    if no_match > 0:
        no_encontrados = [k for k in NOMBRE_A_COMET if k not in mapping]
        print(f"Sin match COMET ({no_match}): {', '.join(no_encontrados)}")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
