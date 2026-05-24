import { useState, useRef } from 'react';
import { api, cancelRequest } from '../services/api';

export function ProcesamientoLote() {
  const [archivos, setArchivos] = useState([]);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentRequestId, setCurrentRequestId] = useState(null);
  const inputRef = useRef(null);

  const handleSeleccion = (e) => {
    const files = Array.from(e.target.files).filter(
      f => f.name.endsWith('.gif') || f.name.endsWith('.png')
    );
    setArchivos(files);
    setResultado(null);
    setError('');
    // Resetear el input para que se pueda volver a seleccionar la misma carpeta
    e.target.value = '';
  };

  const abrirSelectorArchivos = () => {
    inputRef.current.removeAttribute('webkitdirectory');
    inputRef.current.click();
  };

  const abrirSelectorCarpeta = () => {
    inputRef.current.setAttribute('webkitdirectory', '');
    inputRef.current.click();
  };

  const handleProcesar = async () => {
    if (!archivos.length) return;
    setError('');
    setResultado(null);
    setLoading(true);

    try {
      const promise = api.procesarUploadLote(archivos);
      setCurrentRequestId(promise._id);
      const data = await promise;
      setResultado(data);
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
    if (currentRequestId) cancelRequest(currentRequestId);
  };

  const limpiarSeleccion = () => {
    setArchivos([]);
    setResultado(null);
    setError('');
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="card p-6">
        <h3 className="font-display text-lg font-bold text-gray-800 mb-4">
          📁 Procesamiento por Lote
        </h3>
        <p className="text-sm text-gray-500 mb-6">
          Seleccioná archivos <code className="bg-gray-100 px-1 rounded">.gif</code> o{' '}
          <code className="bg-gray-100 px-1 rounded">.png</code> desde tu computadora.
          Se suben al servidor y se procesan secuencialmente.
        </p>

        {/* Input oculto */}
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".gif,.png"
          onChange={handleSeleccion}
          className="hidden"
        />

        <div className="space-y-4">
          {/* Botones de selección */}
          <div className="flex gap-3">
            <button
              onClick={abrirSelectorArchivos}
              disabled={loading}
              className="btn btn-outline"
            >
              🗂️ Seleccionar archivos
            </button>
            <button
              onClick={abrirSelectorCarpeta}
              disabled={loading}
              className="btn btn-outline"
            >
              📁 Seleccionar carpeta
            </button>
            {archivos.length > 0 && !loading && (
              <button
                onClick={limpiarSeleccion}
                className="btn btn-outline text-gray-400 hover:text-red-500"
              >
                ✕ Limpiar
              </button>
            )}
          </div>

          {/* Archivos seleccionados */}
          {archivos.length > 0 && (
            <div className="bg-celeste-light border border-celeste/20 rounded-lg p-4">
              <p className="text-sm font-medium text-celeste mb-2">
                ✅ {archivos.length} archivo{archivos.length !== 1 ? 's' : ''} seleccionado{archivos.length !== 1 ? 's' : ''}
              </p>
              {archivos.length <= 10 && (
                <ul className="text-xs text-gray-500 space-y-0.5 max-h-32 overflow-auto">
                  {archivos.map((f, i) => (
                    <li key={i} className="font-mono">{f.name}</li>
                  ))}
                </ul>
              )}
              {archivos.length > 10 && (
                <p className="text-xs text-gray-400 mt-1">
                  {archivos.slice(0, 5).map(f => f.name).join(', ')} ... y {archivos.length - 5} más
                </p>
              )}
            </div>
          )}

          {/* Botones de acción */}
          <div className="flex gap-3">
            <button
              onClick={handleProcesar}
              disabled={loading || !archivos.length}
              className="btn btn-primary"
            >
              {loading ? (
                <>
                  <span className="animate-spin inline-block">⏳</span>
                  Procesando lote...
                </>
              ) : (
                <>▶️ Procesar {archivos.length > 0 ? `(${archivos.length})` : ''}</>
              )}
            </button>

            {loading && (
              <button
                onClick={handleCancelar}
                className="btn btn-danger animate-pulse"
              >
                🛑 Cancelar
              </button>
            )}
          </div>

          {loading && (
            <p className="text-xs text-gray-400">
              Los archivos ya procesados quedan guardados aunque canceles.
            </p>
          )}
        </div>
      </div>

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
                    <th className="px-4 py-2 text-left font-semibold text-gray-600">Archivo</th>
                    <th className="px-4 py-2 text-left font-semibold text-gray-600">Estado</th>
                    <th className="px-4 py-2 text-left font-semibold text-gray-600">ID</th>
                    <th className="px-4 py-2 text-left font-semibold text-gray-600">Score</th>
                    <th className="px-4 py-2 text-left font-semibold text-gray-600">Mensaje</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {resultado.resultados.map((r, i) => (
                    <tr key={i} className={r.exito ? '' : 'bg-red-50/30'}>
                      <td className="px-4 py-2 font-mono text-xs text-gray-600">{r.archivo}</td>
                      <td className="px-4 py-2">
                        <span className={`badge ${r.exito ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>
                          {r.exito ? '✓ OK' : '✗ Error'}
                        </span>
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">
                        {r.imagen_id ? `#${r.imagen_id}` : '—'}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">
                        {r.score_match != null ? `${(r.score_match * 100).toFixed(1)}%` : '—'}
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

      {/* Error */}
      {error && !resultado && (
        <div className="card p-6 border-red-200 bg-red-50">
          <p className="text-red-600 text-sm">{error}</p>
        </div>
      )}
    </div>
  );
}
