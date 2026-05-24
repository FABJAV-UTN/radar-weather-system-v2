import { useState } from 'react';
import { api, cancelRequest } from '../services/api';

export function ProcesamientoLote() {
  const [folderPath, setFolderPath] = useState('');
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentRequestId, setCurrentRequestId] = useState(null);
  const [progreso, setProgreso] = useState({ actual: 0, total: 0 });

  const handleProcesar = async () => {
    if (!folderPath) return;
    setError('');
    setResultado(null);
    setLoading(true);
    setProgreso({ actual: 0, total: 0 });

    try {
      const promise = api.procesarCarpeta(folderPath);
      setCurrentRequestId(promise._id);

      // Simular progreso visual (el backend no envía progreso en tiempo real aún)
      const progressInterval = setInterval(() => {
        setProgreso(p => ({ ...p, actual: p.actual + 1 }));
      }, 800);

      const data = await promise;
      clearInterval(progressInterval);
      setResultado(data);
      setProgreso({ actual: data.exitosos + data.fallidos, total: data.total });
    } catch (err) {
      if (err.name === 'AbortError' || err.message?.includes('abort')) {
        setError('Procesamiento cancelado por el usuario');
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
      setCurrentRequestId(null);
    }
  };

  const handleCancelar = () => {
    if (currentRequestId) {
      cancelRequest(currentRequestId);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="card p-6">
        <h3 className="font-display text-lg font-bold text-gray-800 mb-4">
          📁 Procesamiento por Lote
        </h3>
        <p className="text-sm text-gray-500 mb-4">
          Procesa todos los archivos <code>.gif</code> y <code>.png</code> de una carpeta secuencialmente.
          Cada archivo usa su propia sesión de base de datos.
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Ruta de la carpeta
            </label>
            <input
              type="text"
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value)}
              className="form-input"
              placeholder="/home/fabio/Descargas/compartir-Fabio"
            />
          </div>

          <div className="flex gap-3">
            <button
              onClick={handleProcesar}
              disabled={loading || !folderPath}
              className="btn btn-primary"
            >
              {loading ? (
                <>
                  <span className="animate-spin">⏳</span>
                  Procesando lote...
                </>
              ) : (
                <>▶️ Procesar Carpeta</>
              )}
            </button>

            {loading && (
              <button
                onClick={handleCancelar}
                className="btn btn-danger animate-pulse"
              >
                🛑 Cancelar Lote
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Barra de progreso */}
      {loading && (
        <div className="card p-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Progreso</span>
            <span className="text-sm text-gray-500">
              ~{progreso.actual} archivos procesados
            </span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
            <div
              className="bg-celeste h-full rounded-full transition-all duration-500"
              style={{ width: `${Math.min((progreso.actual / Math.max(progreso.total, 1)) * 100, 100)}%` }}
            />
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Presioná "Cancelar" para detener el procesamiento. Los archivos ya procesados quedan guardados.
          </p>
        </div>
      )}

      {/* Resultado */}
      {resultado && (
        <div className="card p-6">
          <h3 className="font-display text-lg font-bold text-gray-800 mb-4">
            {resultado.cancelado ? '⚠️ Procesamiento parcial' : '✅ Lote completado'}
          </h3>

          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-emerald-50 p-4 rounded-lg border border-emerald-100 text-center">
              <p className="text-3xl font-bold text-emerald-600">{resultado.exitosos}</p>
              <p className="text-xs text-emerald-700 uppercase font-medium">Exitosos</p>
            </div>
            <div className="bg-red-50 p-4 rounded-lg border border-red-100 text-center">
              <p className="text-3xl font-bold text-red-600">{resultado.fallidos}</p>
              <p className="text-xs text-red-700 uppercase font-medium">Fallidos</p>
            </div>
            <div className="bg-gray-50 p-4 rounded-lg border border-gray-200 text-center">
              <p className="text-3xl font-bold text-gray-600">{resultado.total}</p>
              <p className="text-xs text-gray-500 uppercase font-medium">Total</p>
            </div>
          </div>

          {resultado.resultados?.length > 0 && (
            <div className="overflow-auto max-h-96">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-4 py-2 text-left">Archivo</th>
                    <th className="px-4 py-2 text-left">Estado</th>
                    <th className="px-4 py-2 text-left">ID</th>
                    <th className="px-4 py-2 text-left">Mensaje</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {resultado.resultados.map((r, i) => (
                    <tr key={i} className={r.exito ? '' : 'bg-red-50/30'}>
                      <td className="px-4 py-2 font-mono text-xs">{r.archivo}</td>
                      <td className="px-4 py-2">
                        <span className={`badge ${r.exito ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>
                          {r.exito ? '✓' : '✗'}
                        </span>
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">
                        {r.imagen_id ? `#${r.imagen_id}` : '—'}
                      </td>
                      <td className="px-4 py-2 text-xs text-gray-500">
                        {r.mensaje_error || 'OK'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {error && !resultado && (
        <div className="card p-6 border-red-200 bg-red-50">
          <p className="text-red-600">{error}</p>
        </div>
      )}
    </div>
  );
}
