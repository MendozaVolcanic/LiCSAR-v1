#!/usr/bin/env python3
"""
licsar_common.py — Configuración y utilidades compartidas del pipeline LiCSAR-v1.

Centraliza lo que antes estaba duplicado en comet_downloader.py,
timeseries_downloader.py y licsar_downloader.py:
  - Rutas del proyecto (BASE_DIR, DOCS_DIR)
  - Región y URLs de COMET VolcanoDB
  - Cabeceras HTTP (User-Agent de browser; COMET responde 403 sin él)
  - Mapping nombre dashboard -> key COMET (NOMBRE_A_COMET)
  - Helpers: safe_dir_name, fetch_json, cargar_comet_frames, mapear_volcanes

Importar desde aquí en vez de redefinir constantes en cada script.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR / "docs" / "licsar"
DATOS_DIR = BASE_DIR / "datos"
CATALOG_PATH = DOCS_DIR / "catalog.json"

# ---------------------------------------------------------------------------
# COMET VolcanoDB
# ---------------------------------------------------------------------------
REGION = "south_america"
COMET_DATA_BASE = "https://comet-volcanodb.org/data"
COMET_IMGS_BASE = "https://comet-volcanodb.org/images/licsar_images"
COMET_FRAMES_URL = f"{COMET_DATA_BASE}/volcanoes_frames/volcanoes_frames.js"
TIMESERIES_BASE = f"{COMET_DATA_BASE}/disp_data"
TIMESERIES_GACOS_BASE = f"{COMET_DATA_BASE}/disp_data_gacos"

# Factor de escala de COMET: los archivos "_web_x100_" almacenan el cambio de
# rango LOS multiplicado por 100; dividiendo por 100 se obtienen cm reales.
COMET_SCALE = 100.0

# ---------------------------------------------------------------------------
# Red
# ---------------------------------------------------------------------------
DEFAULT_TIMEOUT = 45
DEFAULT_DELAY = 1.0
MAX_RETRIES = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "image/*, application/json, */*",
}

# Volcanes de prueba (subconjunto representativo: norte, centro, sur)
TEST_VOLCANES = ["Laguna del Maule", "Lascar", "Villarrica"]

# ---------------------------------------------------------------------------
# Mapping: nombre dashboard -> key COMET
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


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def safe_dir_name(nombre: str) -> str:
    """Convierte nombre de volcán a nombre de directorio seguro."""
    return nombre.replace(" ", "_").replace("-", "_")


def fetch_json(url: str, timeout: int = DEFAULT_TIMEOUT,
               max_retries: int = MAX_RETRIES) -> dict | None:
    """Descarga un JSON con reintentos. Retorna dict o None (404/fallo)."""
    for attempt in range(max_retries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers=HEADERS)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            print(f"    WARN HTTP {r.status_code} en {url}")
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                print(f"    timeout, reintentando ({attempt+1}/{max_retries})...")
                time.sleep(3)
            else:
                print(f"    timeout definitivo")
        except Exception as e:
            print(f"    ERROR: {e}")
            break
    return None


def cargar_comet_frames(timeout: int = 60, max_retries: int = MAX_RETRIES) -> dict:
    """Descarga y parsea volcanoes_frames.js, filtrado a la REGION."""
    print("[1/4] Descargando catálogo COMET...")
    for attempt in range(max_retries + 1):
        try:
            r = requests.get(COMET_FRAMES_URL, timeout=timeout, headers=HEADERS)
            if r.status_code == 200:
                text = r.text.replace("var volcanoes_frames = ", "")
                if text.endswith(";"):
                    text = text[:-1]
                data = json.loads(text)
                sa = {k: v for k, v in data.items() if v.get("region") == REGION}
                print(f"    {len(sa)} volcanes sudamericanos en COMET")
                return sa
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                print(f"    timeout, reintentando...")
                time.sleep(5)
        except Exception as e:
            print(f"    ERROR: {e}")
    return {}


def mapear_volcanes(comet_db: dict) -> dict:
    """Mapea nuestros volcanes a keys COMET. {nombre_nuestro: (comet_key, frames)}."""
    mapping = {}
    for nombre, comet_key in NOMBRE_A_COMET.items():
        if comet_key in comet_db:
            frames = comet_db[comet_key].get("frames", [])
            mapping[nombre] = (comet_key, frames)
        else:
            found = [k for k in comet_db if comet_key in k or k in comet_key]
            if found:
                key = found[0]
                frames = comet_db[key].get("frames", [])
                mapping[nombre] = (key, frames)
    return mapping


def cargar_catalog() -> dict:
    """Carga catalog.json o devuelve un esqueleto vacío."""
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"volcanes": {}, "actualizado": "", "fuente": ""}


def guardar_catalog(catalog: dict) -> None:
    """Guarda catalog.json con formato estable."""
    CATALOG_PATH.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nCatálogo actualizado: {CATALOG_PATH}")
