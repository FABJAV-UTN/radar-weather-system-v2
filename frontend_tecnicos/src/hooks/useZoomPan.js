import { useCallback, useEffect, useRef, useState } from 'react';

// Zoom y desplazamiento de un contenido dentro de un contenedor con
// overflow oculto. Rueda del mouse = zoom centrado en el cursor; arrastrar =
// mover; dos dedos = pellizco. El contenido se transforma con
// translate(x, y) scale(escala) y transform-origin 0 0.

const ESCALA_MIN = 1;
const ESCALA_MAX = 16;
const PASO_RUEDA = 1.2;
const SIN_ZOOM = { escala: 1, x: 0, y: 0 };

const limitar = (v, min, max) => Math.min(max, Math.max(min, v));

/** Evita que el contenido deje bordes vacíos dentro del contenedor. */
function encuadrar({ escala, x, y }, ancho, alto) {
  return {
    escala,
    x: limitar(x, ancho - ancho * escala, 0),
    y: limitar(y, alto - alto * escala, 0),
  };
}

/** Zoom a `escalaNueva` dejando fijo el punto (px, py) del contenedor. */
function zoomEn(vista, escalaNueva, px, py, ancho, alto) {
  const escala = limitar(escalaNueva, ESCALA_MIN, ESCALA_MAX);
  const factor = escala / vista.escala;
  return encuadrar(
    { escala, x: px - (px - vista.x) * factor, y: py - (py - vista.y) * factor },
    ancho, alto,
  );
}

export function useZoomPan() {
  const contenedorRef = useRef(null);
  const [vista, setVista] = useState(SIN_ZOOM);
  const punteros = useRef(new Map());   // pointerId → {x, y}
  const pellizco = useRef(null);        // distancia previa entre dos dedos

  const medidas = () => {
    const r = contenedorRef.current.getBoundingClientRect();
    return { r, ancho: r.width, alto: r.height };
  };

  const acercar = useCallback((factor) => {
    const { ancho, alto } = medidas();
    setVista((v) => zoomEn(v, v.escala * factor, ancho / 2, alto / 2, ancho, alto));
  }, []);

  const reiniciar = useCallback(() => setVista(SIN_ZOOM), []);

  // Rueda: listener no pasivo para poder cancelar el scroll de la página.
  useEffect(() => {
    const el = contenedorRef.current;
    if (!el) return undefined;
    const alGirar = (e) => {
      e.preventDefault();
      const { r, ancho, alto } = medidas();
      const factor = e.deltaY < 0 ? PASO_RUEDA : 1 / PASO_RUEDA;
      setVista((v) => zoomEn(v, v.escala * factor, e.clientX - r.left, e.clientY - r.top, ancho, alto));
    };
    el.addEventListener('wheel', alGirar, { passive: false });
    return () => el.removeEventListener('wheel', alGirar);
  }, []);

  const onPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    punteros.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    pellizco.current = null;
  };

  const onPointerMove = (e) => {
    const previo = punteros.current.get(e.pointerId);
    if (!previo) return;
    const actual = { x: e.clientX, y: e.clientY };
    punteros.current.set(e.pointerId, actual);
    const { r, ancho, alto } = medidas();

    if (punteros.current.size === 2) {
      const [a, b] = [...punteros.current.values()];
      const distancia = Math.hypot(a.x - b.x, a.y - b.y);
      if (pellizco.current) {
        const cx = (a.x + b.x) / 2 - r.left;
        const cy = (a.y + b.y) / 2 - r.top;
        const factor = distancia / pellizco.current;
        setVista((v) => zoomEn(v, v.escala * factor, cx, cy, ancho, alto));
      }
      pellizco.current = distancia;
      return;
    }
    const dx = actual.x - previo.x;
    const dy = actual.y - previo.y;
    setVista((v) => encuadrar({ ...v, x: v.x + dx, y: v.y + dy }, ancho, alto));
  };

  const onPointerUp = (e) => {
    punteros.current.delete(e.pointerId);
    pellizco.current = null;
  };

  return {
    contenedorRef,
    vista,
    acercar,
    reiniciar,
    eventos: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel: onPointerUp,
      onDoubleClick: reiniciar,
    },
    estiloContenido: {
      transform: `translate(${vista.x}px, ${vista.y}px) scale(${vista.escala})`,
      transformOrigin: '0 0',
    },
  };
}
