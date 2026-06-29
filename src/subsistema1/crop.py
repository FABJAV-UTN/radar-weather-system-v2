# src/subsistema1/crop.py
"""
Fase 3 del pipeline: Recorte condicional (Crop).

Solo se ejecuta si la imagen tiene marco (detectar_marco() == True).
Busca el color de referencia #5e9d9f desde los 4 bordes y calcula
los puntos de corte con offsets fijos definidos en la guia de diseño.

Sin I/O: opera sobre numpy arrays en memoria.
"""
'''
por qué este codigo vuelve a buscar los marcos? 
respuesta: El código vuelve a buscar los marcos porque su objetivo es recortar la imagen eliminando el marco DACC. 
Para lograr esto, necesita identificar los bordes del marco en la imagen utilizando un color de referencia específico (#5e9d9f) 
y aplicar ciertos offsets para determinar los puntos exactos de corte.
El proceso de búsqueda de los marcos se realiza desde los cuatro bordes de la imagen (izquierda, derecha, superior e inferior) 
para encontrar las apariciones del color de referencia. 
Una vez que se encuentran las posiciones de los bordes del marco, se aplican los offsets definidos en la guía de diseño para calcular 
los límites finales del recorte. Esto asegura que el recorte sea preciso y consistente, eliminando el marco sin afectar el contenido principal de la imagen.   
contra: pero si ya se detectó que hay un marco, ¿no sería más eficiente almacenar las posiciones de los bordes del marco en lugar de buscarlos nuevamente?
respuesta: Sí, sería más eficiente almacenar las posiciones de los bordes del marco en lugar de buscarlos nuevamente. 
Si el proceso de detección del marco ya ha identificado las posiciones de los bordes del marco, se podría pasar esa información directamente 
a la función de recorte, evitando la necesidad de realizar la búsqueda nuevamente. Esto reduciría el tiempo de procesamiento 
y mejoraría la eficiencia del código.
Pero por ahora, el código actual realiza la búsqueda de los bordes del marco cada vez que se llama a la función de recorte,
lo que puede ser redundante si ya se ha detectado previamente la presencia del marco.
A futuro, se podría optimizar el flujo de trabajo para almacenar y reutilizar las posiciones de los bordes del marco,
lo que permitiría un recorte más rápido y eficiente sin necesidad de realizar la búsqueda nuevamente.   
Es decir que detectar_marco.py y crop.py podrían compartir 
información sobre los bordes del marco, evitando la duplicación de esfuerzos y mejorando el rendimiento general del proceso de recorte.  
A nivel algoritmo, esto implicaría modificar la función de detección del marco para que devuelva las posiciones de los bordes del marco,
y luego pasar esa información a la función de recorte en lugar de realizar la búsqueda nuevamente.

por tanto este algoritmo de crop
FUNCIÓN crop_imagen(imagen, color_referencia, tolerancia):
arr ← convertir_a_RGB(imagen)
alto, ancho ← dimensiones(arr)
fila_central ← alto / 2
col_central ← ancho / 2
col_iz ← encontrar_color_en_fila(arr, fila_central, ..., desde_derecha=F, n=1)
col_de ← encontrar_color_en_fila(arr, fila_central, ..., desde_derecha=V, n=4)
fil_su ← encontrar_color_en_columna(arr, col_central, ..., desde_abajo=F, n=4)
fil_in ← encontrar_color_en_columna(arr, col_central, ..., desde_abajo=V, n=2)
corte_izq ← col_iz + 3
 // offset calibrado
corte_der ← col_de - 6
 // offset calibrado
corte_sup ← fil_su + 18 // offset calibrado
corte_inf ← fil_in - 3
 // offset calibrado
// Validar y ajustar para no salirse del array
izq ← max(0, min(corte_izq, ancho-1))
der ← max(0, min(corte_der, ancho))
sup ← max(0, min(corte_sup, alto-1))
inf ← max(0, min(corte_inf, alto))
RETORNAR arr[sup:inf, izq:der]
FIN FUNCIÓN

tendria que ser así:

'''
from __future__ import annotations

import numpy as np
from PIL import Image

# ── Constantes ────────────────────────────────────────────────────────────────
# Color de referencia para calcular los cortes (cadet blue del marco DACC)
CROP_COLOR_RGB: tuple[int, int, int] = (94, 157, 159)   # #5e9d9f
CROP_TOLERANCE: int = 10

# Offsets de corte según guía de diseño
OFFSET_IZQUIERDA: int = +3   # 1ª aparición desde izquierda + 3px
OFFSET_DERECHA: int = -6     # 4ª aparición desde derecha − 6px
OFFSET_SUPERIOR: int = +18   # 4ª aparición desde arriba + 18px
OFFSET_INFERIOR: int = -3    # 2ª aparición desde abajo − 3px


# ── Helpers ───────────────────────────────────────────────────────────────────

def encontrar_color_en_fila(
    arr: np.ndarray,
    fila: int,
    color: tuple[int, int, int],
    tolerancia: int,
    desde_derecha: bool = True,
    num_apariciones: int = 1,
) -> tuple[int | None, int]:
    """
    Busca un color en una fila del array de izquierda a derecha o viceversa.

    Args:
        arr: Array numpy (H, W, 3).
        fila: Índice de la fila a escanear.
        color: Color buscado como tupla (R, G, B).
        tolerancia: Margen máximo por canal RGB.
        desde_derecha: Si True, empieza desde la columna más a la derecha.
        num_apariciones: Número de apariciones a contar.

    Returns:
        (columna_encontrada | None, contador_total).
    """
    ancho = arr.shape[1]
    rango = range(ancho - 1, -1, -1) if desde_derecha else range(ancho)
    contador = 0
    for col in rango:
        pixel = arr[fila, col]
        if (
            abs(int(pixel[0]) - color[0]) <= tolerancia
            and abs(int(pixel[1]) - color[1]) <= tolerancia
            and abs(int(pixel[2]) - color[2]) <= tolerancia
        ):
            contador += 1
            if contador == num_apariciones:
                return col, contador
    return None, contador


def encontrar_color_en_columna(
    arr: np.ndarray,
    columna: int,
    color: tuple[int, int, int],
    tolerancia: int,
    desde_abajo: bool = False,
    num_apariciones: int = 1,
) -> tuple[int | None, int]:
    """
    Busca un color en una columna del array de arriba a abajo o viceversa.

    Args:
        arr: Array numpy (H, W, 3).
        columna: Índice de la columna a escanear.
        color: Color buscado como tupla (R, G, B).
        tolerancia: Margen máximo por canal RGB.
        desde_abajo: Si True, empieza desde la fila más baja.
        num_apariciones: Número de apariciones a contar.

    Returns:
        (fila_encontrada | None, contador_total).
    """
    alto = arr.shape[0]
    rango = range(alto - 1, -1, -1) if desde_abajo else range(alto)
    contador = 0
    for fila in rango:
        pixel = arr[fila, columna]
        if (
            abs(int(pixel[0]) - color[0]) <= tolerancia
            and abs(int(pixel[1]) - color[1]) <= tolerancia
            and abs(int(pixel[2]) - color[2]) <= tolerancia
        ):
            contador += 1
            if contador == num_apariciones:
                return fila, contador
    return None, contador


# ── API pública ───────────────────────────────────────────────────────────────

def crop_imagen(
    image: Image.Image,
    color_referencia: tuple[int, int, int] = CROP_COLOR_RGB,
    tolerancia: int = CROP_TOLERANCE,
) -> np.ndarray:
    """
    Recorta la imagen eliminando el marco DACC usando los bordes de color.

    Calcula los puntos de corte desde los 4 bordes con los offsets de la guía:
    - Izquierda:  1ª aparición + 3px
    - Derecha:    4ª aparición − 6px
    - Superior:   4ª aparición + 18px
    - Inferior:   2ª aparición − 3px

    Args:
        image: Imagen PIL (cualquier modo; se convierte a RGB).
        color_referencia: Color del marco a buscar (tupla RGB).
        tolerancia: Margen de tolerancia por canal.

    Returns:
        Array numpy (H, W, 3) uint8 con la imagen recortada.
    """
    if getattr(image, "is_animated", False):
        image.seek(0)
    rgb = image.convert("RGB")
    arr = np.array(rgb)
    alto, ancho = arr.shape[0], arr.shape[1]

    fila_central = alto // 2
    col_central = ancho // 2

    # ── Izquierda: 1ª aparición + 3px ────────────────────────────────────────
    col_iz, _ = encontrar_color_en_fila(
        arr, fila_central, color_referencia, tolerancia,
        desde_derecha=False, num_apariciones=1,
    )
    corte_izq = (col_iz + OFFSET_IZQUIERDA) if col_iz is not None else 0

    # ── Derecha: 4ª aparición − 6px ──────────────────────────────────────────
    col_der, _ = encontrar_color_en_fila(
        arr, fila_central, color_referencia, tolerancia,
        desde_derecha=True, num_apariciones=4,
    )
    corte_der = (col_der + OFFSET_DERECHA) if col_der is not None else ancho - 1

    # ── Superior: 4ª aparición + 18px ────────────────────────────────────────
    fila_sup, _ = encontrar_color_en_columna(
        arr, col_central, color_referencia, tolerancia,
        desde_abajo=False, num_apariciones=4,
    )
    corte_sup = (fila_sup + OFFSET_SUPERIOR) if fila_sup is not None else 0

    # ── Inferior: 2ª aparición − 3px ─────────────────────────────────────────
    fila_inf, _ = encontrar_color_en_columna(
        arr, col_central, color_referencia, tolerancia,
        desde_abajo=True, num_apariciones=2,
    )
    corte_inf = (fila_inf + OFFSET_INFERIOR) if fila_inf is not None else alto - 1

    # ── Validar y ajustar límites ─────────────────────────────────────────────
    izq = max(0, min(corte_izq, ancho - 1))
    der = max(0, min(corte_der, ancho))
    sup = max(0, min(corte_sup, alto - 1))
    inf = max(0, min(corte_inf, alto))

    if izq >= der:
        izq, der = min(izq, der), max(izq, der)
        if izq == der:
            der = min(ancho, izq + 1)
    if sup >= inf:
        sup, inf = min(sup, inf), max(sup, inf)
        if sup == inf:
            inf = min(alto, sup + 1)

    return arr[sup:inf, izq:der]