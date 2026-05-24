import { useState, useEffect } from 'react';
import { api } from '../services/api';

export function Imagenes() {
  const [imagenes, setImagenes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filtro, setFiltro] = useState({ estado: '', origen: '' });

  useEffect(() => {
    cargarImagenes();
  }, [filtro]);

  const cargarImagenes = async () => {
    setLoading(true);
    try {
      const data = await api.listarImagenes({ ...filtro, limit: 50 });
      setImagenes(data.items || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const getEstadoBadge = (estado) => {
    const map = {
      completado: 'bg-emerald-100 text-emerald-700',
      pendiente: 'bg-amber-100 text-amber-700',
      procesando: 'bg-celeste-light text-celeste',
      error: 'bg-red-100 text-red-700',
    };
    return map[estado] || 'bg-gray-100 text-gray-600';
  };

  return (
    <div className="space-y-6">
      {/* Filtros */}
      <div className="card p-4 flex items-center gap-4">
        <select
          className="form-select w-48"
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
          className="form-select w-48"
          value={filtro.origen}
          onChange={(e) => setFiltro({ ...filtro, origen: e.target.value })}
        >
          <option value="">Todos los orígenes</option>
          <option value="local">Local</option>
          <option value="url">URL DACC</option>
        </select>
        <button onClick={cargarImagenes} className="btn btn-outline">
          🔄 Actualizar
        </button>
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
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-3 text-left font-semibold text-gray-600">ID</th>
                <th className="px-6 py-3 text-left font-semibold text-gray-600">Fecha/Hora</th>
                <th className="px-6 py-3 text-left font-semibold text-gray-600">Origen</th>
                <th className="px-6 py-3 text-left font-semibold text-gray-600">Estado</th>
                <th className="px-6 py-3 text-left font-semibold text-gray-600">Score</th>
                <th className="px-6 py-3 text-left font-semibold text-gray-600">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {imagenes.map((img) => (
                <tr key={img.id} className="hover:bg-gray-50/50 transition-colors">
                  <td className="px-6 py-4 font-mono text-gray-500">#{img.id}</td>
                  <td className="px-6 py-4">
                    <div className="font-medium text-gray-800">
                      {new Date(img.fecha_hora).toLocaleDateString('es-AR')}
                    </div>
                    <div className="text-gray-400 text-xs">
                      {new Date(img.fecha_hora).toLocaleTimeString('es-AR')}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`badge ${img.origen === 'url' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                      {img.origen === 'url' ? '🌐 URL' : '💾 Local'}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`badge ${getEstadoBadge(img.estado)}`}>
                      {img.estado}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    {img.score_match ? (
                      <span className="font-mono font-medium text-gray-700">
                        {(img.score_match * 100).toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-gray-300">—</span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex gap-2">
                      <button
                        onClick={() => api.descargarGeotiff(img.id, `radar_${img.id}_${img.fecha_hora?.replace(/[:\s]/g, '_')}.tif`)}
                        className="text-celeste hover:text-nacion-light text-sm font-medium"
                        disabled={!img.geotiff_data}
                        title={img.geotiff_data ? 'Descargar GeoTIFF' : 'No disponible'}
                      >
                        ⬇️ GeoTIFF
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
