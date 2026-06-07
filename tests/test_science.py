"""
Tests de las funciones científicas de timeseries_downloader.

No tocan la red: usan cubos sintéticos. Verifican las propiedades que importan
para no falsear ciencia: escala correcta, robustez a outliers, significancia,
y detección de cumbres decorrelacionadas.

Correr:  pytest -q
"""

import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import timeseries_downloader as ts
from licsar_common import COMET_SCALE, safe_dir_name, mapear_volcanes


# ---------------------------------------------------------------------------
# Helpers para construir cubos sintéticos
# ---------------------------------------------------------------------------

def _fechas_mensuales(n: int, inicio="2015-01-01") -> list[str]:
    d0 = date.fromisoformat(inicio)
    out = []
    for i in range(n):
        # ~30 días entre épocas
        d = d0 + timedelta(days=30 * i)
        out.append(d.isoformat())
    return out


def _cubo_constante(n_fechas, valor, size=100, mask_val=1):
    """Cubo donde cada píxel vale `valor` en todas las fechas."""
    mask = [[mask_val] * size for _ in range(size)]
    data = [[[valor] * size for _ in range(size)] for _ in range(n_fechas)]
    return {"data_filt": data, "mask": mask}


# ---------------------------------------------------------------------------
# Escala de unidades (el bug crítico: x100)
# ---------------------------------------------------------------------------

def test_escala_divide_por_100():
    """reducir_cubo debe dividir los valores crudos por COMET_SCALE (cm reales)."""
    cubo = _cubo_constante(3, 500.0)  # crudo 500 -> 5.0 cm
    serie, px = ts.reducir_cubo(cubo, (40, 60, 40, 60))
    assert px > 0
    # Re-referenciado a la mediana de los primeros REF_N -> serie constante = 0
    assert all(abs(v) < 1e-9 for v in serie)


def test_escala_pendiente_en_cm():
    """Una rampa cruda de 100/época debe dar 1.0 cm/época tras /100."""
    n = 12
    fechas = _fechas_mensuales(n)
    mask = [[1] * 100 for _ in range(100)]
    # valor crudo = 100 * indice_fecha  -> 1.0 cm por época tras /100
    data = [[[100.0 * k] * 100 for _ in range(100)] for k in range(n)]
    serie, _ = ts.reducir_cubo({"data_filt": data, "mask": mask}, (40, 60, 40, 60))
    # Diferencia entre épocas consecutivas ~ 1.0 cm
    difs = [serie[i + 1] - serie[i] for i in range(n - 1)]
    assert all(abs(d - 1.0) < 1e-6 for d in difs)


# ---------------------------------------------------------------------------
# Velocidad robusta (Theil-Sen) e incertidumbre
# ---------------------------------------------------------------------------

def test_velocidad_lineal_exacta():
    """Serie perfectamente lineal -> velocidad = pendiente real en cm/año."""
    fechas = _fechas_mensuales(24)
    xs = [ts._date_to_ordinal(f) for f in fechas]
    # 0.002 cm/día -> 0.7305 cm/año
    serie = [0.002 * (x - xs[0]) for x in xs]
    out = ts.velocidad_robusta(fechas, serie)
    assert math.isclose(out["velocity_cm_yr"], 0.002 * 365.25, rel_tol=1e-3)
    assert out["r2"] > 0.999
    assert abs(out["velocity_tstat"]) > 50  # tendencia clarísima


def test_theil_sen_robusto_a_outliers():
    """Theil-Sen debe ignorar outliers que arruinarían mínimos cuadrados."""
    fechas = _fechas_mensuales(30)
    xs = [ts._date_to_ordinal(f) for f in fechas]
    serie = [0.001 * (x - xs[0]) for x in xs]
    # Inyectar 3 outliers gigantes (como las primeras adquisiciones S1 ruidosas)
    serie[0] += 50.0
    serie[1] -= 40.0
    serie[2] += 45.0
    out = ts.velocidad_robusta(fechas, serie)
    # La pendiente robusta sigue cerca de 0.001 cm/día * 365.25
    esperado = 0.001 * 365.25
    assert abs(out["velocity_cm_yr"] - esperado) < esperado * 0.5


# ---------------------------------------------------------------------------
# ROI centrado en el cráter
# ---------------------------------------------------------------------------

def test_roi_centrado_en_crater():
    """El ROI debe centrarse en el píxel más cercano a la lat/lon del cráter."""
    xs = [-71.0 + 0.01 * i for i in range(100)]   # lon por columna
    ys = [-40.0 + 0.01 * i for i in range(100)]   # lat por fila
    data = {"x": xs, "y": ys}
    # Cráter cerca de columna 50 (lon -70.5), fila 30 (lat -39.7)
    r0, r1, c0, c1 = ts.roi_centrado(data, lat=-39.7, lon=-70.5, half=10)
    centro_col = (c0 + c1) // 2
    centro_fila = (r0 + r1) // 2
    assert abs(centro_col - 50) <= 1
    assert abs(centro_fila - 30) <= 1


def test_roi_fallback_sin_coords():
    """Sin lat/lon o grillas, usa el centro geométrico del frame."""
    assert ts.roi_centrado({}, lat=None, lon=None) == ts.ROI_FALLBACK


# ---------------------------------------------------------------------------
# Cumbre decorrelacionada -> sin datos (no fingir línea plana)
# ---------------------------------------------------------------------------

def test_roi_adaptativo_sin_datos():
    """Mask toda cero -> px_validos 0 en todas las ventanas -> sin datos."""
    n = 10
    mask = [[0] * 100 for _ in range(100)]   # nada coherente
    data = {
        "data_filt": [[[0.0] * 100 for _ in range(100)] for _ in range(n)],
        "mask": mask,
        "x": [-71 + 0.01 * i for i in range(100)],
        "y": [-40 + 0.01 * i for i in range(100)],
    }
    serie, px, roi, centrado, half = ts.reducir_con_roi_adaptativo(data, -39.7, -70.5)
    assert px == 0


def test_roi_adaptativo_recupera_con_ventana_mayor():
    """Si la ventana chica está vacía pero hay coherencia más lejos, debe expandir."""
    n = 8
    size = 100
    mask = [[0] * size for _ in range(size)]
    # Coherencia solo en un anillo lejano del centro (filas 0-5)
    for i in range(0, 6):
        for j in range(size):
            mask[i][j] = 1
    data = {
        "data_filt": [[[1.0] * size for _ in range(size)] for _ in range(n)],
        "mask": mask,
        # Cráter cerca de la fila 3 (lat correspondiente)
        "x": [-71 + 0.01 * j for j in range(size)],
        "y": [-40 + 0.01 * i for i in range(size)],
    }
    serie, px, roi, centrado, half = ts.reducir_con_roi_adaptativo(data, lat=-39.97, lon=-70.5)
    assert px >= ts.MIN_PIXELS


# ---------------------------------------------------------------------------
# GACOS y delta 180d
# ---------------------------------------------------------------------------

def test_gacos_valido():
    assert ts.gacos_valido([0.0] * 50) is False        # todo cero -> inválido
    assert ts.gacos_valido(None) is False
    assert ts.gacos_valido([0.0, 0.0, 1.2, 0.5, 0.8, 0.9, 1.1]) is True


def test_delta_180d_reporta_dias_reales():
    fechas = _fechas_mensuales(12)
    serie = [float(i) for i in range(12)]
    delta, dias = ts.delta_180d(fechas, serie)
    assert dias > 0
    assert delta != 0


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------

def test_safe_dir_name():
    assert safe_dir_name("Puyehue - Cordon Caulle") == "Puyehue___Cordon_Caulle"
    assert safe_dir_name("Laguna del Maule") == "Laguna_del_Maule"


def test_mapear_volcanes_match_directo():
    comet_db = {"lascar": {"frames": [{"id": "X", "size": 1}]}}
    m = mapear_volcanes(comet_db)
    assert "Lascar" in m
    assert m["Lascar"][0] == "lascar"


# ---------------------------------------------------------------------------
# Descomposición ascendente + descendente
# ---------------------------------------------------------------------------

def test_direccion_frame():
    assert ts.direccion_frame("018A_12668_131313") == "A"
    assert ts.direccion_frame("083D_12636_131313") == "D"
    assert ts.direccion_frame("") is None


def test_frames_por_direccion_elige_mayor_e_ignora_dev():
    db = {"x": {"frames": [
        {"id": "018A_1_1", "size": 100},
        {"id": "018A_1_1_dev", "size": 0},
        {"id": "083D_1_1", "size": 200},
    ]}}
    fd = ts.frames_por_direccion("x", db)
    assert fd["A"] == "018A_1_1"
    assert fd["D"] == "083D_1_1"


def test_descomposicion_recupera_vertical_puro():
    """Movimiento puramente vertical -> vE~0, vU = la señal real."""
    # Geometría tipo LdM: asc mira al oeste (e<0), desc al este (e>0)
    vec_a = {"e": -0.57, "u": 0.81}
    vec_d = {"e": 0.60, "u": 0.78}
    vU_real = 1.0  # cm/año hacia arriba
    # LOS = e*vE + u*vU, con vE=0
    vel_a = vec_a["u"] * vU_real
    vel_d = vec_d["u"] * vU_real
    out = ts.descomponer_vertical_este(vel_a, vec_a, vel_d, vec_d)
    assert abs(out["vertical_cm_yr"] - 1.0) < 0.02
    assert abs(out["este_cm_yr"]) < 0.02


def test_descomposicion_recupera_este_puro():
    """Movimiento puramente al este -> vU~0, vE = la señal real."""
    vec_a = {"e": -0.57, "u": 0.81}
    vec_d = {"e": 0.60, "u": 0.78}
    vE_real = 0.5
    vel_a = vec_a["e"] * vE_real
    vel_d = vec_d["e"] * vE_real
    out = ts.descomponer_vertical_este(vel_a, vec_a, vel_d, vec_d)
    assert abs(out["este_cm_yr"] - 0.5) < 0.02
    assert abs(out["vertical_cm_yr"]) < 0.02


def test_descomposicion_geometria_degenerada():
    """Dos geometrías idénticas -> sistema singular -> None."""
    vec = {"e": -0.5, "u": 0.8}
    assert ts.descomponer_vertical_este(0.5, vec, 0.5, vec) is None


def test_vector_los_crater():
    data = {
        "x": [-71 + 0.01 * i for i in range(100)],
        "y": [-40 + 0.01 * i for i in range(100)],
        "e_geo": [[-0.5] * 100 for _ in range(100)],
        "n_geo": [[-0.16] * 100 for _ in range(100)],
        "u_geo": [[0.8] * 100 for _ in range(100)],
    }
    v = ts.vector_los_crater(data, lat=-39.7, lon=-70.5)
    assert v == {"e": -0.5, "n": -0.16, "u": 0.8}
