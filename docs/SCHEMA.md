# Esquema de datos — LiCSAR-v1

Contrato de los archivos JSON que consume el dashboard. Tres scripts escriben
sobre `catalog.json` (deben **mergear**, no sobrescribir, el bloque `comet`).

> **Capas de datos.** El cubo de desplazamiento y las imágenes son de COMET y no
> se modifican. La serie 1D, la velocidad y los flags de calidad son **productos
> derivados** calculados por este repo (`timeseries_downloader.py`).

---

## `docs/licsar/catalog.json`

```jsonc
{
  "actualizado": "2026-06-07T09:35:00+00:00",   // ISO UTC, última corrida
  "fuente_comet": "COMET VolcanoDB (comet-volcanodb.org)",
  "volcanes": {
    "Laguna del Maule": {
      "nombre": "Laguna del Maule",
      "lat": -36.071,            // cráter (usado para centrar el ROI)
      "lon": -70.498,
      "ascendente":  { "track": "18",  "unw_disponible": true, "coh_disponible": true },
      "descendente": { "track": "83",  "unw_disponible": true, "coh_disponible": true },
      "comet": {
        "key": "laguna_del_maule",
        "frame": "018A_12668_131313",
        "total_interferogramas": 2150,
        "interferogramas": [                     // últimos N pares (JPG recortado)
          { "par": "20260412_20260418", "fecha": "2026-04-12 - 2026-04-18",
            "imagen": "comet/20260412_20260418.jpg" }
        ],
        "prob_deformacion": 0.0,                 // score ML COMET (0-1), NO validado
        "prob_max": 0.06,
        "timeseries": true                       // existe docs/licsar/{vol}/timeseries.json
      }
    }
  }
}
```

**Reglas de escritura**
- `licsar_downloader.py` → escribe `ascendente`/`descendente` (PNGs del frame completo).
- `comet_downloader.py` → mergea `comet.{key,frame,total_interferogramas,interferogramas,prob_*}`
  y re-marca `comet.timeseries=true` escaneando archivos en disco.
- `timeseries_downloader.py` → setea `comet.{key,frame,timeseries}`.
- Nunca reemplazar el dict `comet` entero (se perderían flags de otro script).

---

## `docs/licsar/{Volcán}/timeseries.json` (producto derivado)

```jsonc
{
  "volcan": "Laguna del Maule",
  "frame": "018A_12668_131313",
  "actualizado": "2026-06-07T09:35:00+00:00",
  "fuente": "COMET LiCSBAS x100 filt (serie/velocidad calculadas por LiCSAR-v1)",
  "n_fechas": 336,
  "rango_fechas": ["2014-10-06", "2026-05-12"],
  "dias_latencia": 26,                 // días desde la última observación InSAR
  "roi": {
    "row_min": 37, "row_max": 58, "col_min": 38, "col_max": 59,
    "px_validos": 294,                 // píxeles coherentes promediados
    "centrado_en_crater": true,
    "semilado_px": 10                  // ventana usada (10/15/22 adaptativa)
  },
  "dates": ["2014-10-06", "..."],      // N fechas
  "los_cm_filt": [0.0, -0.42, "..."],  // desplazamiento LOS en cm (ya /100)
  "los_cm_gacos": null,                // serie con corrección GACOS o null
  "gacos_valido": false,
  "velocity_cm_yr": 0.70,              // Theil-Sen (robusto); null si sin_datos
  "velocity_se_cm_yr": 0.01,           // error estándar (OLS)
  "velocity_tstat": 141.06,            // |t|>=2 => distinguible de cero
  "velocity_significativa": true,
  "r2": 0.983,
  "calidad": "significativa",          // significativa|no_significativa|insuficiente|discontinua|sin_datos
  "delta_cm_180d": 0.07,               // cambio en ~180 días
  "delta_dias_reales": 180,            // días reales que abarca la ventana
  "n_gaps": 2,
  "sin_datos": false,                  // true si la cumbre está decorrelacionada
  "metodo_velocidad": "Theil-Sen (robusto); SE/t/R2 por OLS",

  // --- Descomposición vertical/este (solo si hay asc + desc) ---
  "geometria_primaria": "A",           // dirección del frame principal (A/D)
  "geometrias": {
    "ascendente":  { "frame": "018A_12668_131313", "velocity_los_cm_yr": 0.70,
                     "px": 294, "e": -0.568, "u": 0.807 },
    "descendente": { "frame": "083D_12636_131313", "velocity_los_cm_yr": 0.43,
                     "px": 28, "e": 0.596, "u": 0.784 }
  },
  "descomposicion": {                  // null si solo hay una órbita
    "vertical_cm_yr": 0.72,            // +inflación / -deflación (el número clave)
    "este_cm_yr": -0.22
  }
}
```

### Descomposición asc + desc
Un solo frame mide **línea de visión** (mezcla vertical+horizontal). Con ambas
órbitas se resuelve, por píxel del cráter, el sistema 2×2 (despreciando N-S, al
que InSAR es casi ciego):

```
vel_LOS_asc  = e_asc · vEste + u_asc · vVertical
vel_LOS_desc = e_desc · vEste + u_desc · vVertical
```

Usa los vectores `e_geo`/`u_geo` propios de COMET con su `data_filt`, por lo que
es autoconsistente. Test de signo verificado: Laguna del Maule (inflación conocida)
da `vertical_cm_yr` **positivo**. Si falta una órbita o la opuesta no tiene píxeles
coherentes, `descomposicion` es `null` y el dashboard muestra "una sola órbita".

### Valores de `calidad`
| Valor | Significado | Acción del dashboard |
|-------|-------------|----------------------|
| `significativa` | \|t\|≥2, n≥20, ≤3 huecos | Muestra velocidad ± SE en verde |
| `no_significativa` | Pendiente indistinguible de cero | Velocidad mostrada, sin alerta |
| `insuficiente` | < 20 fechas | Marca datos insuficientes |
| `discontinua` | > 3 huecos | Marca serie discontinua |
| `sin_datos` | < 5 px coherentes (cumbre decorrelacionada) | Oculta el gráfico, muestra aviso |

### Unidades — crítico
El cubo COMET (`_web_x100_`) trae el cambio de rango LOS **×100**. Todas las series
están **divididas por 100 = cm reales**. Positivo ≈ acercamiento al satélite (posible
inflación). La velocidad es en **línea de visión** (LOS), no vertical.
