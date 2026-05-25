import { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';

// Mapa de colores dBZ → descripción legible
const DBZ_NIVELES = [
  { min: 0,  max: 15,  label: '< 15',  desc: 'Sin lluvia',      color: 'bg-gray-100 text-gray-500' },
  { min: 15, max: 25,  label: '15–25', desc: 'Llovizna',        color: 'bg-blue-100 text-blue-600' },
  { min: 25, max: 35,  label: '25–35', desc: 'Lluvia leve',     color: 'bg-cyan-100 text-cyan-700' },
  { min: 35, max: 45,  label: '35–45', desc: 'Lluvia moderada', color: 'bg-yellow-100 text-yellow-700' },
  { min: 45, max: 55,  label: '45–55', desc: 'Lluvia intensa',  color: 'bg-orange-100 text-orange-700' },
  { min: 55, max: 999, label: '> 55',  desc: 'Tormenta severa', color: 'bg-red-100 text-red-700' },
];

function getDbzNivel(pixeles_originales, pixeles_limpios) {
  if (!pixeles_originales || pixeles_originales === 0) return null;
  const densidad = pixeles_limpios / pixeles_originales;
  if (densidad > 0.8) return DBZ_NIVELES[5];
  if (densidad > 0.6) return DBZ_NIVELES[4];
  if (densidad > 0.4) return DBZ_NIVELES[3];
  if (densidad > 0.2) return DBZ_NIVELES[2];
  if (densidad > 0.05) return DBZ_NIVELES[1];
  return DBZ_NIVELES[0];
}

const ESTADO_BADGE = {
  completado: 'bg-emerald-100 text-emerald-700',
  pendiente:  'bg-amber-100 text-amber-700',
  procesando: 'bg-celeste-light text-celeste',
  error:      'bg-red-100 text-red-700',
};

function SortIcon({ col, sortCol, sortDir }) {
  if (sortCol !== col) return <span className="ml-1 text-gray-300">↕</span>;
  return <span className="ml-1 text-celeste">{sortDir === 'asc' ? '↑' : '↓'}</span>;
}

// Fecha de hoy en formato YYYY-MM-DD para los inputs date
function hoy() {
  return new Date().toISOString().slice(0, 10);
}

// Fecha de hace 7 días
function haceUnaSemana() {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return d.toISOString().slice(0, 10);
}

export function Imagenes() {
  // ── Estado de datos ──────────────────────────────────────────────────────
  const [imagenes, setImagenes]   = useState([]);
  const [metricas, setMetricas]   = useState({});
  const [total, setTotal]         = useState(0);
  const [loading, setLoading]     = useState(true);
  const [descargando, setDescargando] = useState(null);

  // ── Filtros ──────────────────────────────────────────────────────────────
  const [filtro, setFiltro]       = useState({ estado: '', origen: '' });

  // ── Paginación ───────────────────────────────────────────────────────────
  const [pagina, setPagina]       = useState(1);
  const [porPagina, setPorPagina] = useState(50);

  // ── Ordenamiento ─────────────────────────────────────────────────────────
  const [sortCol, setSortCol]     = useState('id');
  const [sortDir, setSortDir]     = useState('desc');

  // ── Panel descarga lote ───────────────────────────────────────────────────
  const [mostrarLote, setMostrarLote]         = useState(false);
  const [loteDesde, setLoteDesde]             = useState(haceUnaSemana);
  const [loteHasta, setLoteHasta]             = useState(hoy);
  const [descargandoLote, setDescargandoLote] = useState(false);
  const [errorLote, setErrorLote]             = useState('');

  // ── Carga de datos ────────────────────────────────────────────────────────
  const cargarImagenes = useCallback(async () => {
    setLoading(true);
    try {
      const offset = (pagina - 1) * porPagina;
      const data = await api.listarImagenes({ ...filtro, limit: porPagina, offset });
      const items = data.items || [];
      setImagenes(items);
      setTotal(data.total ?? items.length);

      // Métricas en paralelo, solo para completadas de esta página
      const completadas = items.filter(i => i.estado === 'completado');
      const metricasMap = {};
      await Promise.allSettled(
        completadas.map(async (img) => {
          try {
            const m = await api.obtenerMetricas(img.id);
            metricasMap[img.id] = m;
          } catch { /* silencioso */ }
        })
      );
      setMetricas(metricasMap);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [filtro, pagina, porPagina]);

  useEffect(() => {
    cargarImagenes();
  }, [cargarImagenes]);

  // Al cambiar filtros o porPagina, volver a página 1
  const handleFiltro = (nuevoFiltro) => {
    setFiltro(nuevoFiltro);
    setPagina(1);
  };
  const handlePorPagina = (n) => {
    setPorPagina(n);
    setPagina(1);
  };

  // ── Ordenamiento ─────────────────────────────────────────────────────────
  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
  };

  const imagenesSorted = [...imagenes].sort((a, b) => {
    let va, vb;
    switch (sortCol) {
      case 'id':     va = a.id;                    vb = b.id;                    break;
      case 'fecha':  va = new Date(a.fecha_hora);  vb = new Date(b.fecha_hora);  break;
      case 'origen': va = a.origen;                vb = b.origen;                break;
      case 'estado': va = a.estado;                vb = b.estado;                break;
      case 'dbz':
        va = metricas[a.id]?.pixeles_limpios || 0;
        vb = metricas[b.id]?.pixeles_limpios || 0;
        break;
      default: va = a.id; vb = b.id;
    }
    if (va < vb) return sortDir === 'asc' ? -1 : 1;
    if (va > vb) return sortDir === 'asc' ?  1 : -1;
    return 0;
  });

  // ── Descarga individual ───────────────────────────────────────────────────
  const handleDescargar = async (img) => {
    if (img.estado !== 'completado' || descargando) return;
    setDescargando(img.id);
    try {
      const fecha = img.fecha_hora?.replace(/[:\s]/g, '_') || img.id;
      await api.descargarGeotiff(img.id, `radar_${img.id}_${fecha}.tif`);
    } catch (err) {
      alert(`Error al descargar: ${err.message}`);
    } finally {
      setDescargando(null);
    }
  };

  // ── Descarga lote (ZIP) ───────────────────────────────────────────────────
  const handleDescargarLote = async () => {
    if (!loteDesde || !loteHasta) return;
    setDescargandoLote(true);
    setErrorLote('');
    try {
      await api.descargarLote(loteDesde, loteHasta);
      setMostrarLote(false);
    } catch (err) {
      setErrorLote(err.message || 'Error al generar el ZIP');
    } finally {
      setDescargandoLote(false);
    }
  };

  // ── Paginación ────────────────────────────────────────────────────────────
  const totalPaginas = Math.max(1, Math.ceil(total / porPagina));

  const ThSortable = ({ col, children }) => (
    <th
      className="px-3 md:px-6 py-3 text-left font-semibold text-gray-600 cursor-pointer select-none hover:text-celeste whitespace-nowrap"
      onClick={() => handleSort(col)}
    >
      {children}
      <SortIcon col={col} sortCol={sortCol} sortDir={sortDir} />
    </th>
  );

  return (
    <div className="space-y-4">

      {/* ── Filtros + acciones ── */}
      <div className="card p-4 flex flex-wrap items-center gap-3">
        <select
          className="form-select w-full sm:w-44"
          value={filtro.estado}
          onChange={(e) => handleFiltro({ ...filtro, estado: e.target.value })}
        >
          <option value="">Todos los estados</option>
          <option value="completado">Completado</option>
          <option value="pendiente">Pendiente</option>
          <option value="procesando">Procesando</option>
          <option value="error">Error</option>
        </select>

        <select
          className="form-select w-full sm:w-44"
          value={filtro.origen}
          onChange={(e) => handleFiltro({ ...filtro, origen: e.target.value })}
        >
          <option value="">Todos los orígenes</option>
          <option value="local">Local</option>
          <option value="url">URL DACC</option>
        </select>

        <button onClick={cargarImagenes} className="btn btn-outline w-full sm:w-auto">
          🔄 Actualizar
        </button>

        {/* Botón descarga lote */}
        <button
          onClick={() => { setMostrarLote(v => !v); setErrorLote(''); }}
          className="btn btn-outline w-full sm:w-auto"
        >
          ⬇️ Descargar lote
        </button>

        {!loading && (
          <span className="text-xs text-gray-400 ml-auto">
            {total} imagen{total !== 1 ? 'es' : ''}
          </span>
        )}
      </div>

      {/* ── Panel descarga lote ── */}
      {mostrarLote && (
        <div className="card p-4 space-y-3 border border-celeste/30">
          <p className="text-sm font-semibold text-gray-700">
            Descargar GeoTIFFs como ZIP por rango de fechas
          </p>
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">Desde</label>
              <input
                type="date"
                className="form-input"
                value={loteDesde}
                max={loteHasta}
                onChange={(e) => setLoteDesde(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">Hasta</label>
              <input
                type="date"
                className="form-input"
                value={loteHasta}
                min={loteDesde}
                onChange={(e) => setLoteHasta(e.target.value)}
              />
            </div>
            <button
              onClick={handleDescargarLote}
              disabled={descargandoLote || !loteDesde || !loteHasta}
              className="btn btn-primary"
            >
              {descargandoLote ? '⏳ Generando ZIP…' : '⬇️ Confirmar descarga'}
            </button>
          </div>
          {errorLote && (
            <p className="text-sm text-red-600">⚠️ {errorLote}</p>
          )}
          <p className="text-xs text-gray-400">
            Solo se incluyen imágenes con estado <strong>completado</strong>.
          </p>
        </div>
      )}

      {/* ── Tabla ── */}
      <div className="card overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-gray-400">
            <span className="text-3xl animate-pulse">⏳</span>
            <p className="mt-2">Cargando imágenes...</p>
          </div>
        ) : imagenes.length === 0 ? (
          <div className="p-12 text-center text-gray-400">
            <span className="text-4xl">📭</span>
            <p className="mt-2">No hay imágenes registradas</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <ThSortable col="id">ID</ThSortable>
                  <ThSortable col="fecha">Fecha/Hora</ThSortable>
                  <ThSortable col="origen">Origen</ThSortable>
                  <ThSortable col="estado">Estado</ThSortable>
                  <ThSortable col="dbz">Nivel dBZ</ThSortable>
                  <th className="px-3 md:px-6 py-3 text-left font-semibold text-gray-600">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {imagenesSorted.map((img) => {
                  const m = metricas[img.id];
                  const dbz = m ? getDbzNivel(m.pixeles_originales, m.pixeles_limpios) : null;
                  const tieneGeotiff = img.estado === 'completado';

                  return (
                    <tr key={img.id} className="hover:bg-gray-50/50 transition-colors">
                      <td className="px-3 md:px-6 py-4 font-mono text-gray-400 text-xs">#{img.id}</td>

                      <td className="px-3 md:px-6 py-4 whitespace-nowrap">
                        <div className="font-medium text-gray-800 text-sm">
                          {new Date(img.fecha_hora).toLocaleDateString('es-AR')}
                        </div>
                        <div className="text-gray-400 text-xs">
                          {new Date(img.fecha_hora).toLocaleTimeString('es-AR')}
                        </div>
                      </td>

                      <td className="px-3 md:px-6 py-4">
                        <span className={`badge ${img.origen === 'url' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                          {img.origen === 'url' ? '🌐 URL' : '💾 Local'}
                        </span>
                      </td>

                      <td className="px-3 md:px-6 py-4">
                        <span className={`badge ${ESTADO_BADGE[img.estado] || 'bg-gray-100 text-gray-600'}`}>
                          {img.estado}
                        </span>
                      </td>

                      <td className="px-3 md:px-6 py-4">
                        {dbz ? (
                          <div>
                            <span className={`badge ${dbz.color}`}>{dbz.label} dBZ</span>
                            <p className="text-xs text-gray-400 mt-0.5 hidden sm:block">{dbz.desc}</p>
                          </div>
                        ) : (
                          <span className="text-gray-300 text-xs">—</span>
                        )}
                      </td>

                      <td className="px-3 md:px-6 py-4">
                        <button
                          onClick={() => handleDescargar(img)}
                          disabled={!tieneGeotiff || descargando === img.id}
                          className={`text-sm font-medium transition-colors flex items-center gap-1 ${
                            tieneGeotiff
                              ? 'text-celeste hover:text-nacion-light cursor-pointer'
                              : 'text-gray-300 cursor-not-allowed'
                          }`}
                          title={tieneGeotiff ? 'Descargar GeoTIFF' : 'GeoTIFF no disponible'}
                        >
                          {descargando === img.id ? (
                            <><span className="animate-spin">⏳</span> <span className="hidden sm:inline">Descargando...</span></>
                          ) : (
                            <><span>⬇️</span> <span className="hidden sm:inline">GeoTIFF</span></>
                          )}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Controles de paginación ── */}
      {!loading && total > 0 && (
        <div className="card p-3 flex flex-wrap items-center justify-between gap-3">
          {/* Selector por página */}
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <span>Mostrar</span>
            {[50, 100, 200].map(n => (
              <button
                key={n}
                onClick={() => handlePorPagina(n)}
                className={`px-2 py-1 rounded text-xs font-medium border transition-colors ${
                  porPagina === n
                    ? 'bg-celeste text-white border-celeste'
                    : 'border-gray-200 hover:border-celeste hover:text-celeste'
                }`}
              >
                {n}
              </button>
            ))}
            <span>por página</span>
          </div>

          {/* Página X de Y + botones */}
          <div className="flex items-center gap-2 text-sm">
            <button
              onClick={() => setPagina(p => Math.max(1, p - 1))}
              disabled={pagina === 1}
              className="btn btn-outline py-1 px-3 disabled:opacity-40"
            >
              ← Anterior
            </button>
            <span className="text-gray-600 whitespace-nowrap">
              Página <strong>{pagina}</strong> de <strong>{totalPaginas}</strong>
            </span>
            <button
              onClick={() => setPagina(p => Math.min(totalPaginas, p + 1))}
              disabled={pagina === totalPaginas}
              className="btn btn-outline py-1 px-3 disabled:opacity-40"
            >
              Siguiente →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
