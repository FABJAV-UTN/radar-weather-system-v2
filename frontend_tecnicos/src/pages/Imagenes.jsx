import { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';

// Mapa de colores dBZ → descripción legible
const DBZ_NIVELES = [
  { min: 0,  max: 15, label: '< 15',  desc: 'Sin lluvia',      color: 'bg-gray-100 text-gray-500' },
  { min: 15, max: 25, label: '15–25', desc: 'Llovizna',        color: 'bg-blue-100 text-blue-600' },
  { min: 25, max: 35, label: '25–35', desc: 'Lluvia leve',     color: 'bg-cyan-100 text-cyan-700' },
  { min: 35, max: 45, label: '35–45', desc: 'Lluvia moderada', color: 'bg-yellow-100 text-yellow-700' },
  { min: 45, max: 55, label: '45–55', desc: 'Lluvia intensa',  color: 'bg-orange-100 text-orange-700' },
  { min: 55, max: 999, label: '> 55', desc: 'Tormenta severa', color: 'bg-red-100 text-red-700' },
];

function getDbzNivel(pixeles_originales, pixeles_limpios) {
  // Estimación simple: si no hay datos de dBZ directo, usamos la densidad de píxeles
  // como proxy. En el futuro el backend puede devolver dBZ max directamente.
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

// ── Íconos de ordenamiento ────────────────────────────────────────────────────
function SortIcon({ col, sortCol, sortDir }) {
  if (sortCol !== col) return <span className="ml-1 text-gray-300">↕</span>;
  return <span className="ml-1 text-celeste">{sortDir === 'asc' ? '↑' : '↓'}</span>;
}

export function Imagenes() {
  const [imagenes, setImagenes] = useState([]);
  const [metricas, setMetricas] = useState({});
  const [loading, setLoading] = useState(true);
  const [descargando, setDescargando] = useState(null);
  const [filtro, setFiltro] = useState({ estado: '', origen: '' });
  const [sortCol, setSortCol] = useState('id');
  const [sortDir, setSortDir] = useState('desc');

  const cargarImagenes = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listarImagenes({ ...filtro, limit: 100 });
      const items = data.items || [];
      setImagenes(items);

      // Cargar métricas de las completadas (en paralelo, sin bloquear)
      const completadas = items.filter(i => i.estado === 'completado');
      const metricasMap = {};
      await Promise.allSettled(
        completadas.map(async (img) => {
          try {
            const m = await api.obtenerMetricas(img.id);
            metricasMap[img.id] = m;
          } catch {
            // silencioso
          }
        })
      );
      setMetricas(metricasMap);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [filtro]);

  useEffect(() => {
    cargarImagenes();
  }, [cargarImagenes]);

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
  };

  const handleDescargar = async (img) => {
    console.log('handleDescargar llamado', img.id);
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

  // Ordenamiento client-side
  const imagenesSorted = [...imagenes].sort((a, b) => {
    let va, vb;
    switch (sortCol) {
      case 'id':
        va = a.id; vb = b.id; break;
      case 'fecha':
        va = new Date(a.fecha_hora); vb = new Date(b.fecha_hora); break;
      case 'origen':
        va = a.origen; vb = b.origen; break;
      case 'estado':
        va = a.estado; vb = b.estado; break;
      case 'dbz':
        va = metricas[a.id]?.pixeles_limpios || 0;
        vb = metricas[b.id]?.pixeles_limpios || 0;
        break;
      default:
        va = a.id; vb = b.id;
    }
    if (va < vb) return sortDir === 'asc' ? -1 : 1;
    if (va > vb) return sortDir === 'asc' ? 1 : -1;
    return 0;
  });

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
      {/* Filtros */}
      <div className="card p-4 flex flex-wrap items-center gap-3">
        <select
          className="form-select w-full sm:w-44"
          value={filtro.estado}
          onChange={(e) => setFiltro({ ...filtro, estado: e.target.value })}
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
          onChange={(e) => setFiltro({ ...filtro, origen: e.target.value })}
        >
          <option value="">Todos los orígenes</option>
          <option value="local">Local</option>
          <option value="url">URL DACC</option>
        </select>
        <button onClick={cargarImagenes} className="btn btn-outline w-full sm:w-auto">
          🔄 Actualizar
        </button>
        {!loading && (
          <span className="text-xs text-gray-400 ml-auto">
            {imagenes.length} imagen{imagenes.length !== 1 ? 'es' : ''}
          </span>
        )}
      </div>

      {/* Tabla */}
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
                          onClick={() => { console.log('click', img.id, tieneGeotiff, descargando); handleDescargar(img); }}
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
    </div>
  );
}
