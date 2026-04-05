#!/usr/bin/env python3
"""
frame_finder.py - Identify COMET LiCSAR frames covering 43 Chilean volcanoes.

Queries:
  1. ASF (Alaska Satellite Facility) API for Sentinel-1 SLC scenes intersecting
     each volcano coordinate, extracting relative orbit + flight direction to
     derive ascending/descending frame candidates.
  2. COMET LiCSAR portal to check whether each candidate track already has
     interferometric products available.

Outputs (in datos/):
  - frames_volcanes.csv   : one row per volcano with best asc/desc frames
  - frames_volcanes.json  : full metadata per volcano (all candidate frames)
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Try to use the asf_search library; fall back to raw REST API otherwise
# ---------------------------------------------------------------------------
try:
    import asf_search as asf
    HAS_ASF_LIB = True
except ImportError:
    HAS_ASF_LIB = False

# ---------------------------------------------------------------------------
# Volcano dictionary (43 Chilean volcanoes)
# ---------------------------------------------------------------------------
VOLCANES = {
    "Taapaca": {"lat": -18.109, "lon": -69.506},
    "Parinacota": {"lat": -18.171, "lon": -69.145},
    "Guallatiri": {"lat": -18.428, "lon": -69.085},
    "Isluga": {"lat": -19.167, "lon": -68.822},
    "Irruputuncu": {"lat": -20.733, "lon": -68.560},
    "Ollague": {"lat": -21.307, "lon": -68.179},
    "San Pedro": {"lat": -21.885, "lon": -68.407},
    "Lascar": {"lat": -23.367, "lon": -67.736},
    "Tupungatito": {"lat": -33.408, "lon": -69.822},
    "San Jose": {"lat": -33.787, "lon": -69.897},
    "Tinguiririca": {"lat": -34.808, "lon": -70.349},
    "Planchon-Peteroa": {"lat": -35.242, "lon": -70.572},
    "Descabezado Grande": {"lat": -35.604, "lon": -70.748},
    "Tatara-San Pedro": {"lat": -35.998, "lon": -70.845},
    "Laguna del Maule": {"lat": -36.071, "lon": -70.498},
    "Nevado de Longavi": {"lat": -36.200, "lon": -71.170},
    "Nevados de Chillan": {"lat": -37.411, "lon": -71.352},
    "Antuco": {"lat": -37.419, "lon": -71.341},
    "Copahue": {"lat": -37.857, "lon": -71.168},
    "Callaqui": {"lat": -37.926, "lon": -71.461},
    "Lonquimay": {"lat": -38.382, "lon": -71.585},
    "Llaima": {"lat": -38.712, "lon": -71.734},
    "Sollipulli": {"lat": -38.981, "lon": -71.516},
    "Villarrica": {"lat": -39.421, "lon": -71.939},
    "Quetrupillan": {"lat": -39.532, "lon": -71.703},
    "Lanin": {"lat": -39.628, "lon": -71.479},
    "Mocho-Choshuenco": {"lat": -39.934, "lon": -72.003},
    "Carran - Los Venados": {"lat": -40.379, "lon": -72.105},
    "Puyehue - Cordon Caulle": {"lat": -40.559, "lon": -72.125},
    "Antillanca - Casablanca": {"lat": -40.771, "lon": -72.153},
    "Osorno": {"lat": -41.135, "lon": -72.497},
    "Calbuco": {"lat": -41.329, "lon": -72.611},
    "Hornopiren": {"lat": -41.874, "lon": -72.431},
    "Huequi": {"lat": -42.378, "lon": -72.578},
    "Michinmahuida": {"lat": -42.790, "lon": -72.440},
    "Chaiten": {"lat": -42.839, "lon": -72.650},
    "Corcovado": {"lat": -43.192, "lon": -72.079},
    "Yate": {"lat": -41.755, "lon": -72.396},
    "Melimoyu": {"lat": -44.081, "lon": -72.857},
    "Mentolat": {"lat": -44.700, "lon": -73.082},
    "Maca": {"lat": -45.100, "lon": -73.174},
    "Cay": {"lat": -45.059, "lon": -72.984},
    "Hudson": {"lat": -45.900, "lon": -72.970},
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "datos"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CSV_PATH = OUTPUT_DIR / "frames_volcanes.csv"
JSON_PATH = OUTPUT_DIR / "frames_volcanes.json"

ASF_API_URL = "https://api.daac.asf.alaska.edu/services/search/param"
LICSAR_PRODUCTS_URL = (
    "https://gws-access.jasmin.ac.uk/public/nceo_geohazards/LiCSAR_products"
)
COMET_VOLCANO_URL = (
    "https://comet-volcanodb.org/volcano-index/South%20America/Chile/"
)

REQUEST_TIMEOUT = 30  # seconds
DELAY_BETWEEN_QUERIES = 1.0  # be polite to APIs


# ---------------------------------------------------------------------------
# ASF query helpers
# ---------------------------------------------------------------------------

def query_asf_library(lat: float, lon: float, max_results: int = 50) -> list[dict]:
    """Query ASF using the asf_search Python library."""
    try:
        results = asf.geo_search(
            intersectsWith=f"POINT({lon} {lat})",
            platform=[asf.PLATFORM.SENTINEL1],
            processingLevel=[asf.PRODUCT_TYPE.SLC],
            maxResults=max_results,
        )
        scenes = []
        for r in results:
            props = r.properties
            scenes.append({
                "granule": props.get("fileID", ""),
                "platform": props.get("platform", ""),
                "orbit": props.get("pathNumber"),
                "flight_direction": props.get("flightDirection", ""),
                "frame": props.get("frameNumber"),
                "start_time": props.get("startTime", ""),
                "url": props.get("url", ""),
            })
        return scenes
    except Exception as exc:
        print(f"    [asf_search lib error] {exc}")
        return []


def query_asf_api(lat: float, lon: float, max_results: int = 50) -> list[dict]:
    """Query ASF using the REST API directly."""
    params = {
        "intersectsWith": f"point({lon}+{lat})",
        "platform": "Sentinel-1",
        "processingLevel": "SLC",
        "output": "json",
        "maxResults": str(max_results),
    }
    try:
        resp = requests.get(ASF_API_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        # ASF returns a list directly or wrapped in a list
        records = data if isinstance(data, list) else data.get("results", data)
        # Handle GeoJSON format
        if isinstance(records, dict) and "features" in records:
            records = records["features"]
        scenes = []
        for r in records:
            props = r.get("properties", r) if isinstance(r, dict) else {}
            scenes.append({
                "granule": props.get("fileID", props.get("granuleName", "")),
                "platform": props.get("platform", props.get("sensor", "")),
                "orbit": (
                    props.get("pathNumber")
                    or props.get("relativeOrbit")
                    or props.get("path")
                ),
                "flight_direction": (
                    props.get("flightDirection", "")
                    or props.get("ascending_descending", "")
                ),
                "frame": props.get("frameNumber", props.get("frame", None)),
                "start_time": props.get("startTime", props.get("acquisitionDate", "")),
                "url": props.get("url", props.get("downloadUrl", "")),
            })
        return scenes
    except Exception as exc:
        print(f"    [ASF API error] {exc}")
        return []


def query_asf(lat: float, lon: float) -> list[dict]:
    """Attempt ASF library first, then fall back to REST API."""
    if HAS_ASF_LIB:
        scenes = query_asf_library(lat, lon)
        if scenes:
            return scenes
    return query_asf_api(lat, lon)


# ---------------------------------------------------------------------------
# Frame grouping
# ---------------------------------------------------------------------------

def group_frames(scenes: list[dict]) -> dict:
    """
    Group scenes by (orbit, direction) and count occurrences.
    Returns dict keyed by (orbit, direction) with scene count and sample info.
    """
    groups: dict[tuple, dict] = {}
    for s in scenes:
        orbit = s.get("orbit")
        direction = (s.get("flight_direction") or "").upper()
        if not orbit:
            continue
        # Normalise direction to A/D
        if direction.startswith("A"):
            direction = "A"
        elif direction.startswith("D"):
            direction = "D"
        else:
            direction = "?"
        key = (int(orbit), direction)
        if key not in groups:
            groups[key] = {
                "orbit": int(orbit),
                "direction": direction,
                "count": 0,
                "sample_granule": s.get("granule", ""),
                "sample_frame": s.get("frame"),
                "sample_time": s.get("start_time", ""),
            }
        groups[key]["count"] += 1
    return groups


def pick_best_frame(groups: dict, direction: str) -> dict | None:
    """Pick the frame group with the most scenes for a given direction."""
    candidates = [g for g in groups.values() if g["direction"] == direction]
    if not candidates:
        return None
    return max(candidates, key=lambda g: g["count"])


# ---------------------------------------------------------------------------
# LiCSAR portal check
# ---------------------------------------------------------------------------

def check_licsar_track(track: int) -> bool:
    """Check if a track directory exists on the COMET LiCSAR products portal."""
    url = f"{LICSAR_PRODUCTS_URL}/{track}/"
    try:
        resp = requests.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        return resp.status_code == 200
    except Exception:
        return False


def check_licsar_frame(track: int, frame_id: str) -> bool:
    """Check if a specific frame directory exists under a track."""
    url = f"{LICSAR_PRODUCTS_URL}/{track}/{frame_id}/"
    try:
        resp = requests.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        return resp.status_code == 200
    except Exception:
        return False


def list_licsar_frames_for_track(track: int) -> list[str]:
    """Try to list frame subdirectories under a track on the LiCSAR portal."""
    url = f"{LICSAR_PRODUCTS_URL}/{track}/"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []
        # Simple HTML parsing: look for href="NNNX_NNNNN_NNNNNN/"
        import re
        pattern = re.compile(r'href="(\d{3}[AD]_\d{5}_\d{6})/"')
        return pattern.findall(resp.text)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# COMET VolcanoDB check (best-effort)
# ---------------------------------------------------------------------------

def check_comet_volcanodb() -> dict[str, str]:
    """
    Try to fetch the COMET VolcanoDB Chile page to see which volcanoes
    have pages / data. Returns dict {volcano_name: url} best effort.
    """
    results: dict[str, str] = {}
    try:
        resp = requests.get(COMET_VOLCANO_URL, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            import re
            links = re.findall(
                r'href="([^"]*)"[^>]*>\s*([^<]+)', resp.text
            )
            for href, name in links:
                name_clean = name.strip()
                if name_clean:
                    results[name_clean] = href
    except Exception as exc:
        print(f"[COMET VolcanoDB] Could not fetch: {exc}")
    return results


# ---------------------------------------------------------------------------
# LiCSAR frame ID builder
# ---------------------------------------------------------------------------

def build_licsar_frame_id(track: int, direction: str, lat: float) -> str:
    """
    Build a plausible LiCSAR frame ID in the format TTTS_BBBBB_FFFFFF
    where TTT = zero-padded track, S = A or D,
    BBBBB and FFFFFF are burst/frame identifiers.

    Since we don't know the exact burst/frame from ASF alone, we attempt
    to look up the track listing and find the frame closest to the volcano
    latitude. If that fails, return a placeholder.
    """
    track_str = f"{track:03d}{direction}"
    frames = list_licsar_frames_for_track(track)
    if frames:
        # Filter to matching track prefix
        matching = [f for f in frames if f.startswith(track_str)]
        if matching:
            # Return the first match (could improve with lat-based selection)
            return matching[0]
    return f"{track_str}_?????_??????"


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_volcanoes() -> tuple[list[dict], dict]:
    """
    Main loop: query ASF for each volcano, group frames, check LiCSAR.
    Returns (csv_rows, full_json_data).
    """
    print("=" * 78)
    print("  COMET LiCSAR Frame Finder - 43 Chilean Volcanoes")
    print("=" * 78)
    print()

    if HAS_ASF_LIB:
        print("[INFO] Using asf_search library for queries.")
    else:
        print("[INFO] asf_search not installed; using ASF REST API directly.")
    print()

    # Best-effort COMET VolcanoDB check
    print("[1/3] Checking COMET VolcanoDB for Chile volcanoes ...")
    comet_db = check_comet_volcanodb()
    if comet_db:
        print(f"       Found {len(comet_db)} entries on COMET VolcanoDB.")
    else:
        print("       Could not retrieve COMET VolcanoDB data (not critical).")
    print()

    csv_rows: list[dict] = []
    json_data: dict[str, dict] = {}

    total = len(VOLCANES)
    print(f"[2/3] Querying ASF for {total} volcanoes ...")
    print("-" * 78)

    licsar_cache: dict[int, bool] = {}  # track -> available

    for idx, (name, coords) in enumerate(VOLCANES.items(), 1):
        lat, lon = coords["lat"], coords["lon"]
        print(f"  [{idx:2d}/{total}] {name:<30s} ({lat:8.3f}, {lon:9.3f}) ", end="")
        sys.stdout.flush()

        scenes = query_asf(lat, lon)
        groups = group_frames(scenes)

        best_asc = pick_best_frame(groups, "A")
        best_desc = pick_best_frame(groups, "D")

        frame_asc_str = ""
        frame_desc_str = ""
        licsar_asc = False
        licsar_desc = False

        # Check ascending
        if best_asc:
            track = best_asc["orbit"]
            frame_asc_str = f"{track:03d}A"
            if track not in licsar_cache:
                licsar_cache[track] = check_licsar_track(track)
            licsar_asc = licsar_cache[track]

        # Check descending
        if best_desc:
            track = best_desc["orbit"]
            frame_desc_str = f"{track:03d}D"
            if track not in licsar_cache:
                licsar_cache[track] = check_licsar_track(track)
            licsar_desc = licsar_cache[track]

        licsar_available = licsar_asc or licsar_desc

        status = "OK" if scenes else "NO DATA"
        licsar_flag = "LiCSAR" if licsar_available else ""
        print(f"-> ASC:{frame_asc_str or '---':>5s}  DESC:{frame_desc_str or '---':>5s}  "
              f"[{status}] {licsar_flag}")

        # CSV row
        csv_rows.append({
            "volcan": name,
            "lat": lat,
            "lon": lon,
            "frame_asc": frame_asc_str,
            "frame_desc": frame_desc_str,
            "licsar_available": licsar_available,
        })

        # JSON detail
        all_candidates = []
        for key, g in sorted(groups.items()):
            all_candidates.append({
                "orbit": g["orbit"],
                "direction": g["direction"],
                "scene_count": g["count"],
                "sample_granule": g["sample_granule"],
                "sample_frame": g["sample_frame"],
                "sample_time": g["sample_time"],
            })

        json_data[name] = {
            "lat": lat,
            "lon": lon,
            "total_scenes": len(scenes),
            "best_ascending": {
                "track": best_asc["orbit"] if best_asc else None,
                "scene_count": best_asc["count"] if best_asc else 0,
                "licsar_available": licsar_asc,
            },
            "best_descending": {
                "track": best_desc["orbit"] if best_desc else None,
                "scene_count": best_desc["count"] if best_desc else 0,
                "licsar_available": licsar_desc,
            },
            "all_candidates": all_candidates,
            "comet_volcanodb": name in comet_db or any(
                name.lower() in k.lower() for k in comet_db
            ),
        }

        time.sleep(DELAY_BETWEEN_QUERIES)

    print("-" * 78)
    print()
    return csv_rows, json_data


def save_csv(rows: list[dict]) -> None:
    """Save results to CSV."""
    fieldnames = ["volcan", "lat", "lon", "frame_asc", "frame_desc", "licsar_available"]
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[CSV] Saved to {CSV_PATH}")


def save_json(data: dict) -> None:
    """Save detailed results to JSON."""
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"[JSON] Saved to {JSON_PATH}")


def print_summary(rows: list[dict]) -> None:
    """Print a formatted summary table."""
    print()
    print("=" * 78)
    print("  SUMMARY TABLE")
    print("=" * 78)
    header = (
        f"{'Volcano':<28s} {'Lat':>8s} {'Lon':>9s} "
        f"{'ASC':>5s} {'DESC':>5s} {'LiCSAR':>7s}"
    )
    print(header)
    print("-" * 78)

    n_asc = 0
    n_desc = 0
    n_licsar = 0

    for r in rows:
        asc = r["frame_asc"] or "---"
        desc = r["frame_desc"] or "---"
        lic = "Yes" if r["licsar_available"] else "No"
        if r["frame_asc"]:
            n_asc += 1
        if r["frame_desc"]:
            n_desc += 1
        if r["licsar_available"]:
            n_licsar += 1
        print(
            f"{r['volcan']:<28s} {r['lat']:>8.3f} {r['lon']:>9.3f} "
            f"{asc:>5s} {desc:>5s} {lic:>7s}"
        )

    print("-" * 78)
    print(
        f"  Totals: {len(rows)} volcanoes | "
        f"{n_asc} with ASC frame | {n_desc} with DESC frame | "
        f"{n_licsar} with LiCSAR products"
    )
    print("=" * 78)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    try:
        csv_rows, json_data = process_volcanoes()
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Partial results will not be saved.")
        sys.exit(1)

    # Save outputs
    print("[3/3] Saving results ...")
    save_csv(csv_rows)
    save_json(json_data)

    # Print summary
    print_summary(csv_rows)

    print()
    print("Done. Output files:")
    print(f"  - {CSV_PATH}")
    print(f"  - {JSON_PATH}")


if __name__ == "__main__":
    main()
