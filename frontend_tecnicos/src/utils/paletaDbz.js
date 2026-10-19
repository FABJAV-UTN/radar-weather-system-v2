// Paleta dBZ del radar — la misma Color Table que lleva el GeoTIFF
// (src/subsistema1/geolocalizar.py, DBZ_COLOR_MAP), así el carrusel se ve
// igual que QGIS.

export const NIVELES_DBZ = [
  { dbz: 10, rgb: [72, 61, 139] },
  { dbz: 20, rgb: [0, 90, 0] },
  { dbz: 30, rgb: [0, 112, 0] },
  { dbz: 35, rgb: [8, 127, 219] },
  { dbz: 36, rgb: [28, 71, 232] },
  { dbz: 39, rgb: [110, 13, 198] },
  { dbz: 42, rgb: [200, 15, 134] },
  { dbz: 45, rgb: [192, 100, 135] },
  { dbz: 48, rgb: [210, 136, 59] },
  { dbz: 51, rgb: [250, 196, 49] },
  { dbz: 54, rgb: [252, 252, 12] },
  { dbz: 57, rgb: [254, 154, 88] },
  { dbz: 60, rgb: [254, 95, 5] },
  { dbz: 65, rgb: [253, 52, 28] },
  { dbz: 70, rgb: [190, 190, 190] },
  { dbz: 80, rgb: [211, 211, 211] },
];

export const rgbCss = ([r, g, b]) => `rgb(${r}, ${g}, ${b})`;

/**
 * Tabla de búsqueda valor dBZ → RGBA (256 entradas × 4 bytes).
 * Los niveles que no están en `activos` y el 0 (sin dato) quedan transparentes.
 */
export function construirLUT(activos) {
  const lut = new Uint8ClampedArray(256 * 4);
  for (const { dbz, rgb } of NIVELES_DBZ) {
    if (!activos.has(dbz)) continue;
    lut.set([...rgb, 255], dbz * 4);
  }
  return lut;
}

/** Ajusta el canvas al tamaño del cuadro y lo pinta con la LUT. */
export function pintarEnCanvas(canvas, datos, lut) {
  if (canvas.width !== datos.ancho) canvas.width = datos.ancho;
  if (canvas.height !== datos.alto) canvas.height = datos.alto;
  const ctx = canvas.getContext('2d');
  const imagen = ctx.createImageData(datos.ancho, datos.alto);
  pintarDbz(imagen, datos.valores, lut);
  ctx.putImageData(imagen, 0, 0);
}

/** Pinta en un ImageData los valores dBZ (uno por píxel) usando la LUT. */
export function pintarDbz(imageData, valores, lut) {
  const destino = imageData.data;
  for (let i = 0; i < valores.length; i++) {
    const k = valores[i] * 4;
    const j = i * 4;
    destino[j] = lut[k];
    destino[j + 1] = lut[k + 1];
    destino[j + 2] = lut[k + 2];
    destino[j + 3] = lut[k + 3];
  }
}
