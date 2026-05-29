import { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';

// Rangos de dBZ — rangos contiguos e inclusivos (fix bug 1 anterior).
const DBZ_NIVELES = [
  { min: 65, max: Infinity, label: '≥ 65',  desc: 'Tormenta extrema',  color: 'bg-purple-100 text-purple-700' },
  { min: 51, max: 64,       label: '51–64', desc: 'Tormenta severa',   color: 'bg-red-100 text-red-700'       },
  { min: 35, max: 50,       label: '35–50', desc: 'Lluvia intensa',    color: 'bg-orange-100 text-orange-700' },
  { min: 20, max: 34,       label: '20–34', desc: 'Lluvia moderada',   color: 'bg-yellow-100 text-yellow-700' },
  { min: 10, max: 19,       label: '10–19', desc: 'Lluvia débil',      color: 'bg-blue-100 text-blue-600'     },
];

function getDbzNivel(dbz_max) {
  if (dbz_max == null || dbz_max < 10) return null;
  for (const nivel of DBZ_NIVELES) {
    if (dbz_max >= nivel.min && dbz_max <= nivel.max) return nivel;
  }
  return null;
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

function hoy() {
  return new Date().toISOString().slice(0, 10);
}

function haceUnaSemana() {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return d.toISOString().slice(0, 10);
}

export function Imagenes() {
  // ── Estado de datos ──────────────────────────────────────────────────────
  const [imagenes, setImagenes]       = useState([]);
  const [total, setTotal]             = useState(0);
  const [loading, setLoading]         = useState(true);
  const [descargando, setDescargando] = useState(null);

  // ── Filtros ──────────────────────────────────────────────────────────────
  const [filtro, setFiltro] = useState({ estado: '', origen: '' });

  // ── Paginación ───────────────────────────────────────────────────────────
  const [pagina, setPagina]       = useState(1);
  const [porPagina, setPorPagina] = useState(50);

  // ── Ordenamiento server-side ──────────────────────────────────────────────
  // sortCol y sortDir se envían como parámetros al backend en cada request.
  // El backend ordena TODOS los registros antes de paginar, por lo que el
  // orden es global (no solo la página visible).
  const [sortCol, setSortCol] = useState('id');
  const [sortDir, setSortDir] = useState('desc');

  // ── Panel descarga lote ───────────────────────────────────────────────────
  const [mostrarLote, setMostrarLote]         = useState(false);
  const [loteDesde, setLoteDesde]             = useState(haceUnaSemana);
  const [loteHasta, setLoteHasta]             = useState(hoy);
  const [descargandoLote, setDescargandoLote] = useState(false);
  const [errorLote, setErrorLote]             = useState('');

  // ── Carga de datos ────────────────────────────────────────────────────────
  // sort_by y sort_dir viajan como query params al backend → la DB ordena
  // el conjunto completo ANTES de aplicar limit/offset.
  const cargarImagenes = useCallback(async () => {
    setLoading(true);
    try {
      const offset = (pagina - 1) * porPagina;
      const data = await api.listarImagenes({
        ...filtro,
        limit: porPagina,
        offset,
        sort_by:  sortCol,
        sort_dir: sortDir,
      });
      const items = data.items || [];
      setImagenes(items);
      setTotal(data.total ?? items.length);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [filtro, pagina, porPagina, sortCol, sortDir]);

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

  // ── Ordenamiento ──────────────────────────────────────────────────────────
  // Al cambiar columna o dirección se vuelve a página 1 para evitar
  // mostrar una página "en el medio" del nuevo orden.
  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
    setPagina(1);
  };

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

  const ControlesPaginacion = () => (
    <div className="card p-3 flex flex-wrap items-center justify-between gap-3">
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

      {/* ── Controles de paginación ARRIBA ── */}
      {!loading && total > 0 && <ControlesPaginacion />}

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
                {imagenes.map((img) => {
                  const dbz = getDbzNivel(img.dbz_max);
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
                            <span className={`badge ${dbz.color}`}>
                              {img.dbz_max != null ? `${Math.round(img.dbz_max)} dBZ` : dbz.label}
                            </span>
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

      {/* ── Controles de paginación ABAJO ── */}
      {!loading && total > 0 && <ControlesPaginacion />}
    </div>
  );
}
