import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../services/api';
import { useZoomPan } from '../hooks/useZoomPan';
import { NIVELES_DBZ, construirLUT, pintarEnCanvas, rgbCss } from '../utils/paletaDbz';
import { MapaDbz } from '../components/MapaDbz';
import { aInputLocal, haceHoras, mostrarFechaHora } from '../utils/fechas';

// ── Configuración ─────────────────────────────────────────────────────────────

const VELOCIDADES = [
  { ms: 1000, label: '1 cuadro/s' },
  { ms: 500,  label: '2 cuadros/s' },
  { ms: 250,  label: '4 cuadros/s' },
];
const PRECARGA = 4;          // cuadros que se piden por adelantado
const MAX_EN_CACHE = 200;    // ~85 MB de valores dBZ en memoria como máximo
const TODOS_LOS_NIVELES = NIVELES_DBZ.map((n) => n.dbz);

// ── Cache de cuadros (LRU por id) ─────────────────────────────────────────────

/** Guarda la promesa de cada cuadro para no pedirlo dos veces; descarta los más viejos. */
function useCacheCuadros() {
  const cache = useRef(new Map());

  const obtener = useCallback((id) => {
    const mapa = cache.current;
    let promesa = mapa.get(id);
    if (promesa) {
      mapa.delete(id);               // reinsertar = marcar como usado recién
    } else {
      promesa = api.obtenerVistaDbz(id).catch((err) => {
        mapa.delete(id);             // un error no queda cacheado
        throw err;
      });
    }
    mapa.set(id, promesa);
    while (mapa.size > MAX_EN_CACHE) mapa.delete(mapa.keys().next().value);
    return promesa;
  }, []);

  const vaciar = useCallback(() => cache.current.clear(), []);
  return { obtener, vaciar };
}

// ── Componentes ───────────────────────────────────────────────────────────────

function VisorDbz({ datos, activos }) {
  const canvasRef = useRef(null);
  const lut = useMemo(() => construirLUT(activos), [activos]);
  const { contenedorRef, vista, acercar, reiniciar, eventos, estiloContenido } = useZoomPan();

  // Repinta al cambiar de cuadro o de niveles visibles; el zoom se conserva.
  useEffect(() => {
    if (canvasRef.current && datos) pintarEnCanvas(canvasRef.current, datos, lut);
  }, [datos, lut]);

  return (
    <div className="bg-gray-900 rounded-md flex justify-center items-center p-2 min-h-[300px]">
      <div className="relative">
        <div
          ref={contenedorRef}
          className="overflow-hidden cursor-grab active:cursor-grabbing select-none"
          style={{ touchAction: 'none' }}
          title="Rueda o pellizco: zoom · Arrastrar: mover · Doble clic: restablecer"
          {...eventos}
        >
          <canvas
            ref={canvasRef}
            className={`block max-w-full ${datos ? '' : 'invisible'}`}
            style={{ ...estiloContenido, imageRendering: 'pixelated', maxHeight: '70vh',
                     width: 'auto', height: 'auto' }}
          />
        </div>
        {!datos && (
          <span className="absolute inset-0 flex items-center justify-center text-white/50 text-sm animate-pulse">
            Cargando cuadro…
          </span>
        )}
        <div className="absolute top-2 right-2 flex flex-col gap-1">
          {[['+', () => acercar(1.5), 'Acercar'], ['−', () => acercar(1 / 1.5), 'Alejar'],
            ['⟲', reiniciar, 'Restablecer']].map(([texto, accion, titulo]) => (
            <button key={titulo} onClick={accion} title={titulo}
                    className="w-8 h-8 rounded bg-white/80 hover:bg-white text-gray-800 font-bold shadow">
              {texto}
            </button>
          ))}
          <span className="text-[10px] text-center text-white/70">×{vista.escala.toFixed(1)}</span>
        </div>
      </div>
    </div>
  );
}

function Leyenda({ activos, onCambiar }) {
  const alternar = (dbz) => {
    const nuevos = new Set(activos);
    if (nuevos.has(dbz)) nuevos.delete(dbz);
    else nuevos.add(dbz);
    onCambiar(nuevos);
  };

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-gray-700">Niveles visibles</p>
        <div className="flex gap-2">
          <button className="text-xs text-celeste hover:underline"
                  onClick={() => onCambiar(new Set(TODOS_LOS_NIVELES))}>Todos</button>
          <button className="text-xs text-celeste hover:underline"
                  onClick={() => onCambiar(new Set())}>Ninguno</button>
        </div>
      </div>
      <div className="grid grid-cols-4 sm:grid-cols-8 lg:grid-cols-2 gap-2">
        {NIVELES_DBZ.map(({ dbz, rgb }) => (
          <label key={dbz}
                 className={`flex items-center gap-2 text-xs cursor-pointer select-none
                             ${activos.has(dbz) ? 'text-gray-800' : 'text-gray-300'}`}>
            <input type="checkbox" className="accent-celeste"
                   checked={activos.has(dbz)} onChange={() => alternar(dbz)} />
            <span className="inline-block w-4 h-4 rounded-sm border border-gray-200"
                  style={{ backgroundColor: rgbCss(rgb), opacity: activos.has(dbz) ? 1 : 0.3 }} />
            {dbz} dBZ
          </label>
        ))}
      </div>
      <p className="text-xs text-gray-400">
        Solo afecta la visualización: los GeoTIFF se descargan siempre completos.
      </p>
    </div>
  );
}

function Controles({ indice, total, reproduciendo, velocidad, onIr, onReproducir, onVelocidad }) {
  const ultimo = total - 1;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button className="btn btn-outline px-3" onClick={() => onIr(0)} title="Primero">⏮</button>
      <button className="btn btn-outline px-3" onClick={() => onIr(indice === 0 ? ultimo : indice - 1)}
              title="Anterior (←)">◀</button>
      <button className="btn btn-primary px-4" onClick={onReproducir} title="Reproducir / pausar (espacio)">
        {reproduciendo ? '⏸ Pausa' : '▶ Reproducir'}
      </button>
      <button className="btn btn-outline px-3" onClick={() => onIr(indice === ultimo ? 0 : indice + 1)}
              title="Siguiente (→)">▶</button>
      <button className="btn btn-outline px-3" onClick={() => onIr(ultimo)} title="Último">⏭</button>
      <select className="form-select w-auto" value={velocidad}
              onChange={(e) => onVelocidad(Number(e.target.value))}>
        {VELOCIDADES.map((v) => <option key={v.ms} value={v.ms}>{v.label}</option>)}
      </select>
      <input type="range" className="w-full accent-celeste" min={0} max={ultimo} value={indice}
             onChange={(e) => onIr(Number(e.target.value))} />
    </div>
  );
}

// ── Página ────────────────────────────────────────────────────────────────────

export function Carrusel() {
  const [desde, setDesde] = useState(() => haceHoras(6));
  const [hasta, setHasta] = useState(() => aInputLocal(new Date()));
  const [cuadros, setCuadros] = useState([]);
  const [truncada, setTruncada] = useState(false);
  const [indice, setIndice] = useState(0);
  const [datos, setDatos] = useState(null);
  const [reproduciendo, setReproduciendo] = useState(false);
  const [velocidad, setVelocidad] = useState(500);
  const [activos, setActivos] = useState(() => new Set(TODOS_LOS_NIVELES));
  const [cargandoSerie, setCargandoSerie] = useState(false);
  const [descargando, setDescargando] = useState(false);
  const [error, setError] = useState('');
  const [buscado, setBuscado] = useState(false);
  const [modo, setModo] = useState('mapa');        // 'mapa' | 'imagen'
  const [opacidad, setOpacidad] = useState(0.8);
  const { obtener, vaciar } = useCacheCuadros();

  const rangoValido = Boolean(desde && hasta && desde <= hasta);

  const cargarSerie = async () => {
    setReproduciendo(false);
    setCargandoSerie(true);
    setError('');
    vaciar();
    const horaActual = cuadros[indice]?.fecha_hora;
    try {
      const respuesta = await api.serieImagenes(desde, hasta);
      // Si el cuadro que se estaba mirando sigue en el rango, se queda ahí.
      const mismo = respuesta.items.findIndex((c) => c.fecha_hora === horaActual);
      setCuadros(respuesta.items);
      setTruncada(respuesta.truncada);
      setIndice(Math.max(0, mismo));
      setDatos(null);
      setBuscado(true);
    } catch (err) {
      setError(err.message || 'No se pudo cargar el rango');
    } finally {
      setCargandoSerie(false);
    }
  };

  const descargarLote = async () => {
    setDescargando(true);
    setError('');
    try {
      await api.descargarLote(desde, hasta);
    } catch (err) {
      setError(err.message || 'Error al generar el ZIP');
    } finally {
      setDescargando(false);
    }
  };

  // Cuadro visible + precarga de los siguientes
  useEffect(() => {
    if (cuadros.length === 0) return undefined;
    let vigente = true;
    obtener(cuadros[indice].id)
      .then((d) => { if (vigente) setDatos(d); })
      .catch((err) => {
        if (!vigente) return;
        setReproduciendo(false);
        setError(`Cuadro #${cuadros[indice].id}: ${err.message}`);
      });
    for (let k = 1; k <= PRECARGA && k < cuadros.length; k++) {
      obtener(cuadros[(indice + k) % cuadros.length].id).catch(() => {});
    }
    return () => { vigente = false; };
  }, [cuadros, indice, obtener]);

  // Reproducción: avanza recién cuando el cuadro actual ya se mostró
  useEffect(() => {
    if (!reproduciendo || cuadros.length < 2 || !datos) return undefined;
    const timer = setTimeout(() => setIndice((i) => (i + 1) % cuadros.length), velocidad);
    return () => clearTimeout(timer);
  }, [reproduciendo, datos, velocidad, cuadros.length]);

  // Teclado: ← → para moverse, espacio para reproducir
  useEffect(() => {
    if (cuadros.length === 0) return undefined;
    const alPresionar = (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName) && e.target.type !== 'range') return;
      const n = cuadros.length;
      if (e.key === 'ArrowRight') setIndice((i) => (i + 1) % n);
      else if (e.key === 'ArrowLeft') setIndice((i) => (i - 1 + n) % n);
      else if (e.key === ' ') setReproduciendo((r) => !r);
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', alPresionar);
    return () => window.removeEventListener('keydown', alPresionar);
  }, [cuadros.length]);

  const cuadroActual = cuadros[indice];

  return (
    <div className="space-y-4">

      {/* ── Rango ── */}
      <div className="card p-4 flex flex-wrap gap-3 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500">Desde</label>
          <input type="datetime-local" className="form-input" value={desde} max={hasta}
                 onChange={(e) => setDesde(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500">Hasta</label>
          <input type="datetime-local" className="form-input" value={hasta} min={desde}
                 onChange={(e) => setHasta(e.target.value)} />
        </div>
        <button className="btn btn-primary" onClick={cargarSerie}
                disabled={!rangoValido || cargandoSerie}>
          {cargandoSerie ? '⏳ Buscando…' : buscado ? '🔄 Actualizar' : '🎞️ Ver imágenes'}
        </button>
        <button className="btn btn-outline" onClick={descargarLote}
                disabled={!rangoValido || descargando}>
          {descargando ? '⏳ Generando ZIP…' : '⬇️ Descargar lote'}
        </button>
        <p className="text-xs text-gray-400 w-full">
          Hora argentina. El lote incluye los GeoTIFF completos de todas las imágenes del rango.
        </p>
      </div>

      {error && <div className="card p-3 text-sm text-red-600">⚠️ {error}</div>}

      {truncada && (
        <div className="card p-3 text-sm text-amber-700 bg-amber-50">
          El rango tiene más imágenes de las que entran en el carrusel: se muestran las
          primeras {cuadros.length}. Acotá el rango para ver el resto.
        </div>
      )}

      {buscado && cuadros.length === 0 && !cargandoSerie && (
        <div className="card p-12 text-center text-gray-400">
          <span className="text-4xl">📭</span>
          <p className="mt-2">No hay imágenes completadas en ese rango</p>
        </div>
      )}

      {/* ── Visor ── */}
      {cuadroActual && (
        <div className="grid gap-4 lg:grid-cols-[1fr_16rem]">
          <div className="card p-4 space-y-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-semibold text-gray-800">{mostrarFechaHora(cuadroActual.fecha_hora)}</p>
              <p className="text-xs text-gray-400">
                Cuadro {indice + 1} de {cuadros.length} · #{cuadroActual.id}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex rounded-md border-2 border-celeste overflow-hidden text-sm font-semibold">
                {[['mapa', '🗺️ Mapa'], ['imagen', '🖼️ Imagen']].map(([valor, texto]) => (
                  <button key={valor} onClick={() => setModo(valor)}
                          className={`px-3 py-1.5 ${modo === valor ? 'bg-celeste text-white' : 'bg-white text-celeste'}`}>
                    {texto}
                  </button>
                ))}
              </div>
              {modo === 'mapa' && (
                <label className="flex items-center gap-2 text-xs text-gray-500">
                  Opacidad del radar
                  <input type="range" className="accent-celeste" min={0.2} max={1} step={0.05}
                         value={opacidad} onChange={(e) => setOpacidad(Number(e.target.value))} />
                </label>
              )}
            </div>
            {modo === 'mapa'
              ? <MapaDbz datos={datos} activos={activos} opacidad={opacidad} />
              : <VisorDbz datos={datos} activos={activos} />}
            <Controles
              indice={indice}
              total={cuadros.length}
              reproduciendo={reproduciendo}
              velocidad={velocidad}
              onIr={setIndice}
              onReproducir={() => setReproduciendo((r) => !r)}
              onVelocidad={setVelocidad}
            />
          </div>
          <Leyenda activos={activos} onCambiar={setActivos} />
        </div>
      )}
    </div>
  );
}
