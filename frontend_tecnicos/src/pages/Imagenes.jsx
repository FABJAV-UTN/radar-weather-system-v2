import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Download, RefreshCw, ChevronUp, ChevronDown, ArrowUpDown,
  ImageOff, Calendar, Filter, X
} from 'lucide-react';
import { api } from '../services/api.js';

// ── Helpers ──────────────────────────────────────────────────────────────────
function fmtDate(d) {
  if (!d) return '—';
  return new Date(d).toLocaleString('es-AR', {
    dateStyle: 'short',
    timeStyle: 'short',
  });
}

function fmtScore(s) {
  if (s == null) return '—';
  return (s * 100).toFixed(1) + '%';
}

function estadoBadge(estado) {
  const map = {
    completado: 'bg-emerald-50 text-emerald-600 border-emerald-200',
    error: 'bg-red-50 text-red-600 border-red-200',
    procesando: 'bg-amber-50 text-amber-600 border-amber-200',
    pendiente: 'bg-sky-50 text-sky-600 border-sky-200',
  };
  return (
    <span className={`badge border ${map[estado] || map.pendiente}`}>
      {estado}
    </span>
  );
}

const MESES = [
  'Enero','Febrero','Marzo','Abril','Mayo','Junio',
  'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'
];

// ── Componente: Fila expandible con detalles ─────────────────────────────────
function FilaDetalle({ imagen }) {
  const [metricas, setMetricas] = useState(null);
  const [pasos, setPasos] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.obtenerMetricas(imagen.id).catch(() => null),
      api.obtenerPasos(imagen.id).catch(() => []),
    ]).then(([m, p]) => {
      setMetricas(m);
      setPasos(p);
      setLoading(false);
    });
  }, [imagen.id]);

  return (
    <tr>
      <td colSpan={9} className="bg-gray-50/80 border-b border-gray-200">
        <div className="p-5 grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Métricas */}
          <div className="space-y-3">
            <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Métricas de calidad</h4>
            {loading ? (
              <div className="text-sm text-gray-400">Cargando...</div>
            ) : metricas ? (
              <div className="space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-gray-500">Píxeles originales:</span> <strong>{metricas.pixeles_originales?.toLocaleString()}</strong></div>
                <div className="flex justify-between"><span className="text-gray-500">Píxeles limpios:</span> <strong>{metricas.pixeles_limpios?.toLocaleString()}</strong></div>
                <div className="flex justify-between"><span className="text-gray-500">Píxeles rellenados:</span> <strong className="text-emerald-600">{metricas.pixeles_rellenados?.toLocaleString()}</strong></div>
                <div className="flex justify-between"><span className="text-gray-500">Píxeles perdidos:</span> <strong className="text-red-500">{metricas.pixeles_perdidos?.toLocaleString()}</strong></div>
                <div className="flex justify-between"><span className="text-gray-500">Error de relleno:</span> <strong>{metricas.error_relleno_pct}%</strong></div>
              </div>
            ) : (
              <div className="text-sm text-gray-400">Sin métricas disponibles</div>
            )}
          </div>

          {/* Pasos */}
          <div className="space-y-3">
            <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Pasos del pipeline</h4>
            {pasos.length > 0 ? (
              <div className="space-y-1.5">
                {pasos.map(p => (
                  <div key={p.id} className="flex items-center gap-2 text-sm">
                    <span className={`w-2 h-2 rounded-full ${p.exitoso ? 'bg-emerald-500' : 'bg-red-500'}`} />
                    <span className="capitalize">{p.paso}</span>
                    <span className="text-gray-400 text-xs ml-auto">{fmtDate(p.ejecutado_en)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-sm text-gray-400">Sin pasos registrados</div>
            )}
          </div>

          {/* Metadatos */}
          <div className="space-y-3">
            <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Metadatos</h4>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-gray-500">ID:</span> <span className="font-mono">#{imagen.id}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">CRS:</span> <span>{imagen.crs || '—'}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Transform:</span> <span className="font-mono text-xs truncate max-w-[180px]">{imagen.transform_affine || '—'}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Origen:</span> <span>{imagen.origen}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Creado:</span> <span>{fmtDate(imagen.created_at)}</span></div>
            </div>
          </div>
        </div>
      </td>
    </tr>
  );
}

// ── Página principal ─────────────────────────────────────────────────────────
export default function Imagenes() {
  const [imagenes, setImagenes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Filtros
  const [filtroEstado, setFiltroEstado] = useState('');
  const [filtroOrigen, setFiltroOrigen] = useState('');
  const [filtroAnio, setFiltroAnio] = useState('');
  const [filtroMes, setFiltroMes] = useState('');
  const [filtroTemporada, setFiltroTemporada] = useState(''); // verano/otoño/invierno/primavera
  const [busqueda, setBusqueda] = useState('');

  // Ordenamiento
  const [sortField, setSortField] = useState('fecha_hora');
  const [sortDir, setSortDir] = useState('desc');

  // Paginación
  const [page, setPage] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const LIMIT = 50;

  // UI
  const [expandedId, setExpandedId] = useState(null);
  const [descargando, setDescargando] = useState(null);

  const cargar = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = { limit: LIMIT, offset: page * LIMIT };
      if (filtroEstado) params.estado = filtroEstado;
      if (filtroOrigen) params.origen = filtroOrigen;
      const data = await api.listarImagenes(params);
      setImagenes(data.items || []);
      setTotalPages(Math.max(1, Math.ceil((data.total || 0) / LIMIT)));
    } catch (err) {
      setError(err.message);
      setImagenes([]);
    } finally {
      setLoading(false);
    }
  }, [page, filtroEstado, filtroOrigen]);

  useEffect(() => {
    cargar();
  }, [cargar]);

  // Reset página cuando cambian filtros
  useEffect(() => {
    setPage(0);
  }, [filtroEstado, filtroOrigen, filtroTemporada]);

  // Determinar temporada según mes
  function getTemporada(mes) {
    if ([12, 1, 2].includes(mes)) return 'verano';
    if ([3, 4, 5].includes(mes)) return 'otoño';
    if ([6, 7, 8].includes(mes)) return 'invierno';
    return 'primavera';
  }

  // Filtrado local (año, mes, temporada, búsqueda)
  const filtradas = useMemo(() => {
    return imagenes.filter(img => {
      const d = new Date(img.fecha_hora);
      const mes = d.getMonth() + 1;
      const anio = d.getFullYear();

      if (filtroAnio && anio !== parseInt(filtroAnio)) return false;
      if (filtroMes && mes !== parseInt(filtroMes)) return false;
      if (filtroTemporada && getTemporada(mes) !== filtroTemporada) return false;
      if (busqueda) {
        const q = busqueda.toLowerCase();
        const match =
          String(img.id).includes(q) ||
          img.estado?.toLowerCase().includes(q) ||
          img.origen?.toLowerCase().includes(q) ||
          fmtDate(img.fecha_hora).toLowerCase().includes(q);
        if (!match) return false;
      }
      return true;
    });
  }, [imagenes, filtroAnio, filtroMes, filtroTemporada, busqueda]);

  // Ordenamiento
  const ordenadas = useMemo(() => {
    const sorted = [...filtradas].sort((a, b) => {
      let va = a[sortField];
      let vb = b[sortField];

      if (va == null) va = sortField === 'score_match' ? -1 : '';
      if (vb == null) vb = sortField === 'score_match' ? -1 : '';

      if (typeof va === 'string') {
        va = va.toLowerCase();
        vb = String(vb).toLowerCase();
      }

      if (va < vb) return sortDir === 'asc' ? -1 : 1;
      if (va > vb) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [filtradas, sortField, sortDir]);

  function toggleSort(field) {
    if (sortField === field) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  }

  function SortIcon({ field }) {
    if (sortField !== field) return <ArrowUpDown className="w-3 h-3 opacity-40" />;
    return sortDir === 'asc'
      ? <ChevronUp className="w-3.5 h-3.5" />
      : <ChevronDown className="w-3.5 h-3.5" />;
  }

  async function descargar(id, fechaHora) {
    setDescargando(id);
    try {
      const fecha = new Date(fechaHora).toISOString().slice(0, 16).replace('T', '_').replace(':', '');
      await api.descargarGeotiff(id, `radar_${id}_${fecha}.tif`);
    } catch (e) {
      alert('Error al descargar: ' + e.message);
    } finally {
      setDescargando(null);
    }
  }

  // Stats
  const stats = useMemo(() => {
    const completadas = filtradas.filter(i => i.estado === 'completado').length;
    const conError = filtradas.filter(i => i.estado === 'error').length;
    const scores = filtradas.filter(i => i.score_match != null).map(i => i.score_match);
    const avgScore = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
    const maxDbz = scores.length > 0 ? Math.max(...scores) : 0;
    return { total: filtradas.length, completadas, conError, avgScore, maxDbz };
  }, [filtradas]);

  const anios = useMemo(() => {
    const set = new Set(imagenes.map(i => new Date(i.fecha_hora).getFullYear()));
    return [...set].sort((a, b) => b - a);
  }, [imagenes]);

  const hayFiltros = filtroEstado || filtroOrigen || filtroAnio || filtroMes || filtroTemporada || busqueda;

  function limpiarFiltros() {
    setFiltroEstado('');
    setFiltroOrigen('');
    setFiltroAnio('');
    setFiltroMes('');
    setFiltroTemporada('');
    setBusqueda('');
    setPage(0);
  }

  return (
    <div className="space-y-6">
      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {[
          { label: 'Imágenes', value: stats.total, color: 'text-nacion' },
          { label: 'Completadas', value: stats.completadas, color: 'text-emerald-600' },
          { label: 'Con error', value: stats.conError, color: 'text-red-500' },
          { label: 'Score promedio', value: (stats.avgScore * 100).toFixed(1) + '%', color: 'text-nacion', small: true },
          { label: 'Score máximo', value: (stats.maxDbz * 100).toFixed(1) + '%', color: 'text-celeste', small: true },
        ].map((s, i) => (
          <div key={i} className="card p-5 text-center hover:shadow-md transition-shadow">
            <div className={`font-display text-3xl font-extrabold ${s.color} ${s.small ? 'text-2xl' : ''}`}>
              {s.value}
            </div>
            <div className="text-[11px] text-gray-400 uppercase tracking-wider font-semibold mt-1.5">
              {s.label}
            </div>
          </div>
        ))}
      </div>

      {/* Tabla */}
      <div className="card">
        {/* Header de tabla */}
        <div className="flex items-center justify-between px-6 py-4"
          style={{ background: 'linear-gradient(135deg, #003366, #004a99)' }}>
          <h2 className="font-display text-base font-bold text-white uppercase tracking-wide">
            🗂 Imágenes Procesadas
          </h2>
          <button
            onClick={cargar}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium text-white border border-white/20 bg-white/10 hover:bg-white/20 transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Actualizar
          </button>
        </div>

        {/* Filtros */}
        <div className="p-4 bg-gray-50 border-b border-gray-200">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1.5 min-w-[130px]">
              <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">Estado</span>
              <select className="form-select py-2" value={filtroEstado} onChange={e => setFiltroEstado(e.target.value)}>
                <option value="">Todos</option>
                <option value="completado">Completado</option>
                <option value="error">Error</option>
                <option value="procesando">Procesando</option>
                <option value="pendiente">Pendiente</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5 min-w-[110px]">
              <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">Origen</span>
              <select className="form-select py-2" value={filtroOrigen} onChange={e => setFiltroOrigen(e.target.value)}>
                <option value="">Todos</option>
                <option value="local">Local</option>
                <option value="url">URL</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5 min-w-[110px]">
              <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">Año</span>
              <select className="form-select py-2" value={filtroAnio} onChange={e => setFiltroAnio(e.target.value)}>
                <option value="">Todos</option>
                {anios.map(a => <option key={a} value={a}>{a}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1.5 min-w-[130px]">
              <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">Mes</span>
              <select className="form-select py-2" value={filtroMes} onChange={e => setFiltroMes(e.target.value)}>
                <option value="">Todos</option>
                {MESES.map((m, i) => <option key={i + 1} value={i + 1}>{m}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1.5 min-w-[130px]">
              <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">Temporada</span>
              <select className="form-select py-2" value={filtroTemporada} onChange={e => setFiltroTemporada(e.target.value)}>
                <option value="">Todas</option>
                <option value="verano">☀️ Verano</option>
                <option value="otoño">🍂 Otoño</option>
                <option value="invierno">❄️ Invierno</option>
                <option value="primavera">🌸 Primavera</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5 min-w-[180px] flex-1 max-w-xs">
              <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">Buscar</span>
              <div className="relative">
                <input
                  type="text"
                  value={busqueda}
                  onChange={e => setBusqueda(e.target.value)}
                  placeholder="ID, estado, origen..."
                  className="form-input py-2 pr-8"
                />
                {busqueda && (
                  <button onClick={() => setBusqueda('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                    <X className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
            {hayFiltros && (
              <button
                onClick={limpiarFiltros}
                className="btn btn-outline btn-sm py-2 mb-0.5"
              >
                <Filter className="w-3.5 h-3.5" />
                Limpiar
              </button>
            )}
          </div>
        </div>

        {/* Contenido */}
        {loading ? (
          <div className="p-16 text-center">
            <div className="w-10 h-10 border-3 border-nacion/20 border-t-celeste rounded-full animate-spin mx-auto" />
            <p className="text-gray-400 text-sm mt-4">Cargando imágenes...</p>
          </div>
        ) : error ? (
          <div className="p-16 text-center">
            <div className="text-red-500 text-sm">{error}</div>
            <button onClick={cargar} className="btn btn-outline mt-4">Reintentar</button>
          </div>
        ) : ordenadas.length === 0 ? (
          <div className="p-16 text-center">
            <ImageOff className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-400 text-sm">No hay imágenes con los filtros aplicados</p>
            {hayFiltros && (
              <button onClick={limpiarFiltros} className="btn btn-outline mt-4 text-xs">
                Limpiar filtros
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr style={{ background: '#003366' }}>
                    {[
                      ['id', 'ID'],
                      ['fecha_hora', <><Calendar className="w-3.5 h-3.5 inline mr-1" />Fecha / Hora</>],
                      ['origen', 'Origen'],
                      ['estado', 'Estado'],
                      ['tiene_marco', 'Marco'],
                      ['score_match', 'Score Match'],
                      ['crs', 'CRS'],
                      ['fecha_procesamiento', 'Procesado'],
                    ].map(([field, label]) => (
                      <th
                        key={field}
                        onClick={() => toggleSort(field)}
                        className={`px-4 py-3 text-left text-white font-display text-xs font-bold uppercase tracking-wider whitespace-nowrap cursor-pointer select-none transition-colors hover:bg-nacion-light ${sortField === field ? 'bg-nacion-light' : ''}`}
                      >
                        <div className="flex items-center gap-1">
                          {label}
                          <SortIcon field={field} />
                        </div>
                      </th>
                    ))}
                    <th className="px-4 py-3 text-left text-white font-display text-xs font-bold uppercase tracking-wider">
                      Acciones
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ordenadas.map(img => (
                    <>
                      <tr
                        key={img.id}
                        onClick={() => setExpandedId(expandedId === img.id ? null : img.id)}
                        className="border-b border-gray-100 hover:bg-celeste-light/40 cursor-pointer transition-colors"
                      >
                        <td className="px-4 py-3">
                          <strong className="text-nacion">#{img.id}</strong>
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">{fmtDate(img.fecha_hora)}</td>
                        <td className="px-4 py-3">
                          <span className={`badge ${img.origen === 'url' ? 'bg-sky-50 text-sky-600 border-sky-200' : 'bg-amber-50 text-amber-600 border-amber-200'}`}>
                            {img.origen}
                          </span>
                        </td>
                        <td className="px-4 py-3">{estadoBadge(img.estado)}</td>
                        <td className="px-4 py-3 text-center">
                          {img.tiene_marco ? <span className="text-emerald-600 font-bold">✓</span> : '—'}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`font-semibold ${
                            img.score_match > 0.35 ? 'text-emerald-600' :
                            img.score_match > 0.25 ? 'text-amber-500' : 'text-red-500'
                          }`}>
                            {fmtScore(img.score_match)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-400 text-xs">{img.crs || '—'}</td>
                        <td className="px-4 py-3 text-gray-400 text-xs">{fmtDate(img.fecha_procesamiento)}</td>
                        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                          {img.estado === 'completado' ? (
                            <button
                              onClick={() => descargar(img.id, img.fecha_hora)}
                              disabled={descargando === img.id}
                              className="btn btn-outline btn-sm py-1.5 px-3 text-xs"
                            >
                              {descargando === img.id ? (
                                <div className="w-3.5 h-3.5 border-2 border-nacion/20 border-t-celeste rounded-full animate-spin" />
                              ) : (
                                <><Download className="w-3.5 h-3.5" /> GeoTIFF</>
                              )}
                            </button>
                          ) : (
                            <span className="text-gray-300 text-xs">—</span>
                          )}
                        </td>
                      </tr>
                      {expandedId === img.id && <FilaDetalle imagen={img} />}
                    </>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Paginación */}
            <div className="flex items-center justify-between px-5 py-3.5 border-t border-gray-200 text-sm text-gray-600">
              <span>
                Página {page + 1} de {totalPages} — <strong>{ordenadas.length}</strong> registros mostrados
              </span>
              <div className="flex gap-1">
                <button
                  onClick={() => setPage(0)}
                  disabled={page === 0}
                  className="page-btn px-3 py-1.5 border border-gray-200 rounded bg-white text-gray-600 hover:border-celeste hover:text-celeste disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  «
                </button>
                <button
                  onClick={() => setPage(p => p - 1)}
                  disabled={page === 0}
                  className="page-btn px-3 py-1.5 border border-gray-200 rounded bg-white text-gray-600 hover:border-celeste hover:text-celeste disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  ‹
                </button>
                <span className="px-3 py-1.5 bg-celeste text-white rounded font-semibold">
                  {page + 1}
                </span>
                <button
                  onClick={() => setPage(p => p + 1)}
                  disabled={page >= totalPages - 1}
                  className="page-btn px-3 py-1.5 border border-gray-200 rounded bg-white text-gray-600 hover:border-celeste hover:text-celeste disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  ›
                </button>
                <button
                  onClick={() => setPage(totalPages - 1)}
                  disabled={page >= totalPages - 1}
                  className="page-btn px-3 py-1.5 border border-gray-200 rounded bg-white text-gray-600 hover:border-celeste hover:text-celeste disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  »
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
