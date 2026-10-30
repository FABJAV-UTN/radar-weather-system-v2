"""
Medición de la marca de agua del DACC para el modelo de mezcla de la Fase 4.

Modelo (por píxel cubierto por la marca):

    observado = W + alfa · D        (recortado a 0-255)

    D     color original de la escala dBZ (DBZ_COLOR_MAP)
    W     color que la marca deja sobre fondo negro (sin eco)
    alfa  fracción del dato que queda visible bajo la marca

Procedimiento
-------------
1. W: en un GIF SECO (sin lluvia) la marca está sola sobre fondo negro, así
   que cada color que aparece ahí es un candidato a W (D = 0 → observado = W).
   Con varios GIF secos se usa el color más frecuente de cada píxel (la
   paleta del GIF varía levemente entre imágenes).
2. alfa: la marca está siempre en la misma posición del GIF. Para cada
   candidato W se toman sus píxeles y se miran esos mismos píxeles en GIF CON
   LLUVIA. Se prueba alfa de 0,70 a 1,00 y se elige el que mejor explica lo
   observado como W + alfa · (algún color de la escala).
3. Se conservan los W que explican al menos FRACCION_MIN de las
   observaciones con eco, con alfa < ALFA_MAX (alfa ≈ 1 es dato sin marca) y
   que no son un color de la escala (los ecos del GIF seco no son marca).

Uso (desde la raíz del repo; solo lee, no modifica nada):

    uv run python scripts/medir_marca_agua.py \
        --seco "<ruta>/seco.gif" \
        --lluvia "<ruta>/radar_2026-10-13_gif_originales"

Imprime la tabla de componentes y el bloque MARCA_AGUA_COMPONENTES listo
para copiar en src/subsistema1/limpiar.py.

Ambos GIF deben ser de la misma variante (mismo tamaño), porque se comparan
por posición. El resultado (colores y alfa) NO depende de la posición: en el
pipeline se usa como tabla de colores.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.subsistema1.limpiar import DBZ_COLOR_MAP  # noqa: E402

PUROS = np.array(list(DBZ_COLOR_MAP.values()), dtype=float)

MIN_PIXELES_SECO = 20       # píxeles mínimos del candidato en el GIF seco
MIN_OBS_CON_ECO = 200       # observaciones mínimas con eco para ajustar alfa
DIF_FONDO = 12              # |obs - W| (suma) por debajo: no hay eco encima
TOLERANCIA_AJUSTE = 6.0     # distancia RGB para considerar explicada una obs.
FRACCION_MIN = 0.10         # fracción explicada mínima para aceptar el W
ALFA_MAX = 0.985            # alfa por encima: es dato sin marca
DIST_MIN_A_PURO = 30.0      # un W más cerca que esto de la escala es eco
ALFAS = np.round(np.arange(0.70, 1.0001, 0.01), 2)


def _leer_rgb(ruta: Path) -> np.ndarray:
    img = Image.open(ruta)
    if getattr(img, "is_animated", False):
        img.seek(0)
    return np.array(img.convert("RGB")).astype(int)


def _moda_por_pixel(secos: list[np.ndarray]) -> np.ndarray:
    """
    Color más frecuente de cada píxel entre los GIF secos.

    La paleta del GIF varía levemente entre imágenes (p. ej. el oliva de la
    marca sale (24,30,8) o (24,29,7)) y un eco pasajero puede tapar algún
    píxel en una imagen: la moda da el W estable de cada píxel.
    """
    if len(secos) == 1:
        return secos[0]
    from scipy.stats import mode

    pila = np.stack(secos)                                   # (n, H, W, 3)
    codigos = (pila[..., 0] << 16) | (pila[..., 1] << 8) | pila[..., 2]
    moda = mode(codigos, axis=0, keepdims=False).mode
    return np.stack([(moda >> 16) & 255, (moda >> 8) & 255, moda & 255], axis=-1)


def medir(seco: list[Path], lluvia: list[Path]) -> list[tuple[tuple[int, int, int], float, int, float]]:
    """Devuelve [(W, alfa, píxeles en seco, fracción explicada)] aceptados."""
    forma = _leer_rgb(seco[0]).shape
    secos = [a for a in (_leer_rgb(p) for p in seco) if a.shape == forma]
    lluvias = np.stack([a for a in (_leer_rgb(p) for p in lluvia) if a.shape == forma])
    if len(lluvias) == 0:
        raise SystemExit(f"Ningún GIF con lluvia tiene el tamaño del seco {forma[:2]}")

    ref = _moda_por_pixel(secos)
    conteo = Counter(map(tuple, ref.reshape(-1, 3)))
    aceptados = []
    for w, n in conteo.items():
        if n < MIN_PIXELES_SECO:
            continue
        w_arr = np.array(w, dtype=float)
        if np.linalg.norm(PUROS - w_arr, axis=1).min() < DIST_MIN_A_PURO:
            continue  # color de la escala: eco presente en el GIF seco
        mascara = np.all(ref == w, axis=2)

        obs = lluvias[:, mascara].reshape(-1, 3)
        dif = obs - w_arr
        dif = dif[np.abs(dif).sum(axis=1) > DIF_FONDO]
        if len(dif) < MIN_OBS_CON_ECO:
            continue

        mejor_frac, mejor_alfa = 0.0, 1.0
        for a in ALFAS:
            pred = np.clip(w_arr + a * PUROS, 0, 255) - w_arr
            dist = np.linalg.norm(dif[:, None, :] - pred[None], axis=2).min(axis=1)
            frac = float(np.mean(dist < TOLERANCIA_AJUSTE))
            if frac > mejor_frac:
                mejor_frac, mejor_alfa = frac, float(a)

        if mejor_frac >= FRACCION_MIN and mejor_alfa < ALFA_MAX:
            aceptados.append((tuple(int(v) for v in w), mejor_alfa, int(mascara.sum()), mejor_frac))

    aceptados.sort(key=lambda x: -x[2])
    return aceptados


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seco", nargs="+", required=True, type=Path, help="GIF(s) sin lluvia")
    ap.add_argument("--lluvia", nargs="+", required=True, type=Path,
                    help="GIF con lluvia o carpeta(s) que los contienen")
    args = ap.parse_args()

    lluvia: list[Path] = []
    for p in args.lluvia:
        lluvia += sorted(p.glob("*.gif")) if p.is_dir() else [p]

    componentes = medir(args.seco, lluvia)

    print(f"GIF secos: {len(args.seco)} · GIF con lluvia: {len(lluvia)}")
    print(f"{'W (RGB)':<16}{'alfa':>6}{'px seco':>9}{'explicado':>11}")
    for w, a, n, f in componentes:
        print(f"{str(w):<16}{a:>6.2f}{n:>9}{f:>10.1%}")

    print("\n# Bloque para src/subsistema1/limpiar.py")
    print("MARCA_AGUA_COMPONENTES: tuple[tuple[tuple[int, int, int], float], ...] = (")
    for w, a, n, _ in componentes:
        print(f"    ({w}, {a:.2f}),  # {n} px")
    print(")")


if __name__ == "__main__":
    main()
