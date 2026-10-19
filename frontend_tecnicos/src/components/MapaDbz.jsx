import { useEffect, useMemo, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { construirLUT, pintarEnCanvas } from '../utils/paletaDbz';
// Límite de Mendoza, Natural Earth 1:10m (ver datos_referencia/LEEME.txt)
import limiteMendoza from '../assets/limite_mendoza.json';

// Cuadro del radar apoyado sobre un mapa web (Leaflet).
// Los GeoTIFF están en EPSG:3857, la misma proyección del mapa: el cuadro se
// coloca con sus límites en grados y calza sin deformarse.

// Esri World Street Map: sin clave y sin restricción por sitio de origen
// (OpenStreetMap rechaza los pedidos hechos desde localhost/IP del lab).
// Ojo: la URL de Esri va en orden {z}/{y}/{x}.
const FONDO = {
  url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
  atribucion: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, USGS, '
    + '<a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
};
// Fondo apagado para que los colores del radar resalten.
const FILTRO_FONDO = 'grayscale(70%) brightness(1.05)';
const VISTA_INICIAL = { centro: [-34.6, -68.5], zoom: 7 };

export function MapaDbz({ datos, activos, opacidad }) {
  const divRef = useRef(null);
  const mapaRef = useRef(null);
  const capaRef = useRef(null);
  const encuadrado = useRef(false);
  const canvas = useMemo(() => document.createElement('canvas'), []);
  const lut = useMemo(() => construirLUT(activos), [activos]);

  // Mapa, fondo y límite provincial: una sola vez
  useEffect(() => {
    const mapa = L.map(divRef.current).setView(VISTA_INICIAL.centro, VISTA_INICIAL.zoom);
    L.tileLayer(FONDO.url, { maxZoom: 19, attribution: FONDO.atribucion }).addTo(mapa);
    mapa.getPane('tilePane').style.filter = FILTRO_FONDO;
    L.geoJSON(limiteMendoza, {
      interactive: false,
      style: { color: '#1F3864', weight: 1.5, fill: false },
    }).addTo(mapa);
    mapaRef.current = mapa;
    return () => {
      mapa.remove();
      mapaRef.current = null;
      capaRef.current = null;
      encuadrado.current = false;
    };
  }, []);

  // Cuadro del radar: se repinta al cambiar de cuadro o de niveles visibles
  useEffect(() => {
    const mapa = mapaRef.current;
    if (!mapa || !datos?.limites) return;
    pintarEnCanvas(canvas, datos, lut);
    const url = canvas.toDataURL('image/png');
    const [oeste, sur, este, norte] = datos.limites;
    const limites = L.latLngBounds([sur, oeste], [norte, este]);

    if (capaRef.current) {
      capaRef.current.setUrl(url);
      capaRef.current.setBounds(limites);
    } else {
      capaRef.current = L.imageOverlay(url, limites, { opacity: opacidad, interactive: false }).addTo(mapa);
      capaRef.current.getElement().style.imageRendering = 'pixelated';
    }
    if (!encuadrado.current) {
      mapa.fitBounds(limites);
      encuadrado.current = true;
    }
    // la opacidad tiene su propio efecto: no hace falta repintar al cambiarla
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datos, lut, canvas]);

  useEffect(() => {
    capaRef.current?.setOpacity(opacidad);
  }, [opacidad]);

  return (
    <div className="relative isolate">
      <div ref={divRef} className="rounded-md overflow-hidden z-0" style={{ height: '70vh', minHeight: 320 }} />
      {datos && !datos.limites && (
        <div className="absolute inset-x-0 top-2 mx-auto w-fit z-[500] bg-amber-50 text-amber-700 text-xs px-3 py-1 rounded shadow">
          Este cuadro no tiene georreferencia: usá la vista Imagen.
        </div>
      )}
    </div>
  );
}
