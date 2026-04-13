"""
licsar_downloader.py — Descarga thumbnails PNG de interferogramas LiCSAR

Lee datos/frames_volcanes.json (generado por frame_finder.py) y descarga
los PNGs de los interferogramas más recientes para cada volcán prioritario.

Solo descarga PNGs (no GeoTIFF), aproximadamente 300-800 KB por imagen.

Outputs:
  docs/licsar/{volcan}/asc_unw.png       — fase desenvuelta ascendente (última)
  docs/licsar/{volcan}/asc_coh.png       — coherencia ascendente (última)
  docs/licsar/{volcan}/desc_unw.png      — fase desenvuelta descendente (última)
  docs/licsar/{volcan}/desc_coh.png      — coherencia descendente (última)
  docs/licsar/catalog.json               — catálogo de datos disponibles

Uso:
  python licsar_downloader.py              # todos los volcanes en catalog
  python licsar_downloader.py --test       # solo Villarrica y Lascar
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

BASE_DIR = Path(__file__).resolve().parent
DATOS_DIR = BASE_DIR / "datos"
DOCS_DIR = BASE_DIR / "docs" / "licsar"
DOCS_DIR.mkdir(parents=True, exist_ok=True)
DATOS_DIR.mkdir(parents=True, exist_ok=True)

LICSAR_BASE = "https://gws-access.jasmin.ac.uk/public/nceo_geohazards/LiCSAR_products"
CEDA_BASE = "https://data.ceda.ac.uk/neodc/comet/data/licsar_products"
REQUEST_TIMEOUT = 30
DELAY = 1.5  # cortesía al servidor JASMIN

VOLCANES_PRIORITARIOS = [
    "Laguna del Maule", "Lascar", "Puyehue - Cordon Caulle",
    "Villarrica", "Copahue", "Nevados de Chillan",
    "Llaima", "Calbuco", "Chaiten"
]


def listar_interferogramas_frame(track: int, frame_id: str) -> list:
    """Lista los pares de fechas disponibles para un frame LiCSAR."""
    url = f"{LICSAR_BASE}/{track}/{frame_id}/interferograms/"
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return []
        # Los pares aparecen como archivos sin barra final
        pares = re.findall(r'href="(\d{8}_\d{8})"', r.text)
        return sorted(pares)
    except Exception as e:
        print(f"    WARN listar interferogramas {frame_id}: {e}")
        return []


def obtener_png_urls(track: int, frame_id: str, par: str) -> dict:
    """
    Lee el archivo de listing de un par y extrae las URLs directas de los PNGs.
    Retorna dict con claves 'unw' y 'cc'.
    """
    url = f"{LICSAR_BASE}/{track}/{frame_id}/interferograms/{par}"
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return {}
        unw = re.search(r"href='([^']+\.geo\.unw\.png)'", r.text)
        cc  = re.search(r"href='([^']+\.geo\.cc\.png)'", r.text)
        return {
            "unw": unw.group(1) if unw else None,
            "cc":  cc.group(1)  if cc  else None,
        }
    except Exception as e:
        print(f"    WARN obtener URLs {frame_id}/{par}: {e}")
        return {}


def descargar_png(url: str, dest: Path) -> bool:
    """Descarga un PNG desde LiCSAR. Retorna True si fue exitoso."""
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        if r.status_code != 200:
            return False
        dest.write_bytes(r.content)
        size_kb = dest.stat().st_size / 1024
        print(f"OK ({size_kb:.0f} KB)")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def procesar_volcan(nombre: str, info: dict, docs_dir: Path) -> dict:
    """Descarga los PNGs más recientes para un volcán (asc + desc)."""
    volcan_dir = docs_dir / nombre.replace(" ", "_").replace("-", "_")
    volcan_dir.mkdir(parents=True, exist_ok=True)

    resultado = {
        "nombre": nombre,
        "lat": info.get("lat"),
        "lon": info.get("lon"),
        "ascendente": None,
        "descendente": None,
        "actualizado": datetime.now(timezone.utc).isoformat()
    }

    for direccion in ["ascending", "descending"]:
        clave = "best_ascending" if direccion == "ascending" else "best_descending"
        frame_info = info.get(clave)
        if not frame_info:
            continue

        track = frame_info.get("track")
        frame_id = frame_info.get("frame_id")
        if not track or not frame_id or "?????" in str(frame_id):
            print(f"  {direccion}: frame no identificado")
            continue

        if not frame_info.get("licsar_available"):
            print(f"  {direccion}: track {track} no en LiCSAR")
            continue

        print(f"  {direccion}: track={track} frame={frame_id}")
        pares = listar_interferogramas_frame(track, frame_id)
        if not pares:
            print(f"    Sin interferogramas disponibles")
            continue

        par_reciente = pares[-1]
        print(f"    Par reciente: {par_reciente}")
        prefijo = "asc" if direccion == "ascending" else "desc"
        png_urls = obtener_png_urls(track, frame_id, par_reciente)

        print(f"    unw...", end=" ")
        unw_ok = descargar_png(png_urls.get("unw"), volcan_dir / f"{prefijo}_unw.png") if png_urls.get("unw") else False
        if not png_urls.get("unw"):
            print("sin URL")
        time.sleep(DELAY)

        print(f"    coh...", end=" ")
        coh_ok = descargar_png(png_urls.get("cc"), volcan_dir / f"{prefijo}_coh.png") if png_urls.get("cc") else False
        if not png_urls.get("cc"):
            print("sin URL")
        time.sleep(DELAY)

        dir_key = "ascendente" if direccion == "ascending" else "descendente"
        resultado[dir_key] = {
            "track": track,
            "frame_id": frame_id,
            "par_fechas": par_reciente,
            "total_interferogramas": len(pares),
            "unw_disponible": unw_ok,
            "coh_disponible": coh_ok,
            "ruta_local": str(volcan_dir.relative_to(docs_dir.parent))
        }

    return resultado


def cargar_catalog_frames() -> dict:
    """Carga el catálogo de frames generado por frame_finder.py."""
    json_path = DATOS_DIR / "frames_volcanes.json"
    if not json_path.exists():
        print("No se encontró datos/frames_volcanes.json")
        print("Ejecuta primero: python frame_finder.py")
        return {}
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def generar_catalog(resultados: list):
    """Genera docs/licsar/catalog.json con el índice de datos disponibles."""
    catalog = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "fuente": "COMET LiCSAR (Sentinel-1 InSAR)",
        "url_base": LICSAR_BASE,
        "nota": "Solo thumbnails PNG, no GeoTIFF completos",
        "volcanes": {r["nombre"]: r for r in resultados}
    }
    catalog_path = DOCS_DIR / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False))
    print(f"\nCatálogo guardado: {catalog_path}")


def main():
    test_mode = "--test" in sys.argv

    catalog = cargar_catalog_frames()
    if not catalog:
        return 1

    volcanes_a_procesar = list(catalog.keys())
    if test_mode:
        volcanes_a_procesar = [v for v in VOLCANES_PRIORITARIOS if v in catalog][:3]
        print(f"Modo test: {volcanes_a_procesar}")

    print(f"\n{'='*60}")
    print(f"LiCSAR DOWNLOADER — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Volcanes: {len(volcanes_a_procesar)} | Solo PNGs (no GeoTIFF)")
    print(f"{'='*60}\n")

    resultados = []
    descargados = 0
    errores = 0

    for i, nombre in enumerate(volcanes_a_procesar, 1):
        info = catalog[nombre]
        print(f"[{i}/{len(volcanes_a_procesar)}] {nombre}")
        resultado = procesar_volcan(nombre, info, DOCS_DIR)
        resultados.append(resultado)
        if resultado["ascendente"] or resultado["descendente"]:
            descargados += 1
        else:
            errores += 1

    generar_catalog(resultados)

    print(f"\n{'='*60}")
    print(f"RESUMEN: Con datos={descargados} | Sin datos={errores}")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
