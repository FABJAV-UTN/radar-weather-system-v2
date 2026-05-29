import { useRef } from 'react';
import { useLote } from '../context/LoteContext';

export function ProcesamientoLote() {
  const {
    cantidadArchivos,
    previewNombres,
    resultado,
    error,
    loading,
    cargandoArchivos,
    procesados,
    loteActual,
    lotesTotal,
    soportaCarpetaModerna,
    cargarCarpeta,
    seleccionarArchivos,
    procesar,
    cancelar,
    limpiar,
  } = useLote();

  const inputRef = useRef(null);

  const handleSeleccion = (e) => {
    const files = e.target.files;
    seleccionarArchivos(files);
    e.target.value = '';
  };

  const abrirSelectorArchivos = () => {
    const input = inputRef.current;
    input.removeAttribute('webkitdirectory');
    input.click();
  };

  const abrirSelectorCarpetaLegacy = () => {
    const input = inputRef.current;
    input.setAttribute('webkitdirectory', '');
    input.click();
  };

  const abrirSelectorCarpeta = async () => {
    if (soportaCarpetaModerna) {
      try {
        const dirHandle = await window.showDirectoryPicker({ mode: 'read' });
        await cargarCarpeta(dirHandle);
        return;
      } catch (err) {
        if (err?.name === 'AbortError') return;
      }
    }
    abrirSelectorCarpetaLegacy();
  };

  const ocupado = loading || cargandoArchivos;

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="card p-6">
        <h3 className="font-display text-lg font-bold text-gray-800 mb-4">
          📁 Procesamiento por Lote
        </h3>
        <p className="text-sm text-gray-500 mb-6">
          Seleccioná archivos <code className="bg-gray-100 px-1 rounded">.gif</code> o{' '}
          <code className="bg-gray-100 px-1 rounded">.png</code> desde tu computadora.
          Se suben al servidor en tandas de hasta 1.000 y se procesan secuencialmente.
        </p>

        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".gif,.png"
          onChange={handleSeleccion}
          className="hidden"
        />

        <div className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <button
              onClick={abrirSelectorArchivos}
              disabled={ocupado}
              className="btn btn-outline"
            >
              🗂️ Seleccionar archivos
            </button>
            <button
              onClick={abrirSelectorCarpeta}
              disabled={ocupado}
              className="btn btn-outline"
            >
              📁 Seleccionar carpeta
            </button>
            {cantidadArchivos > 0 && !ocupado && (
              <button onClick={limpiar} className="btn btn-outline text-gray-400 hover:text-red-500">
                ✕ Limpiar
              </button>
            )}
          </div>

          {cargandoArchivos && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <div className="flex items-center gap-3">
                <span className="animate-spin text-xl">⏳</span>
                <div>
                  <p className="text-sm font-medium text-blue-700">Cargando archivos...</p>
                  <p className="text-xs text-blue-500 mt-0.5">
                    Preparando la lista después de confirmar en el navegador.
                  </p>
                </div>
              </div>
            </div>
          )}

          {!cargandoArchivos && cantidadArchivos > 0 && (
            <div className="bg-celeste-light border border-celeste/20 rounded-lg p-4">
              <p className="text-sm font-medium text-celeste mb-2">
                ✅ {cantidadArchivos.toLocaleString()} archivo{cantidadArchivos !== 1 ? 's' : ''}{' '}
                .gif / .png listo{cantidadArchivos !== 1 ? 's' : ''} para procesar
              </p>
              {cantidadArchivos <= 10 && previewNombres.length > 0 && (
                <ul className="text-xs text-gray-500 space-y-0.5 max-h-32 overflow-auto">
                  {previewNombres.map((nombre, i) => (
                    <li key={i} className="font-mono">{nombre}</li>
                  ))}
                </ul>
              )}
              {cantidadArchivos > 10 && previewNombres.length > 0 && (
                <p className="text-xs text-gray-400 mt-1">
                  {previewNombres.join(', ')}
                  {cantidadArchivos > previewNombres.length &&
                    ` ... y ${(cantidadArchivos - previewNombres.length).toLocaleString()} más`}
                </p>
              )}
            </div>
          )}

          {loading && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
              <div className="flex items-center gap-3 mb-2">
                <span className="animate-spin text-xl">⏳</span>
                <p className="text-sm font-medium text-amber-700">
                  Procesando...
                  {lotesTotal > 0 && loteActual > 0 && ` tanda ${loteActual}/${lotesTotal}`}
                  {procesados > 0 &&
                    ` — ${procesados.toLocaleString()} / ${cantidadArchivos.toLocaleString()} archivos`}
                </p>
              </div>
              <div className="w-full bg-amber-100 rounded-full h-2">
                <div
                  className="bg-amber-400 h-2 rounded-full transition-all duration-500"
                  style={{
                    width: cantidadArchivos > 0
                      ? `${Math.min((procesados / cantidadArchivos) * 100, 95)}%`
                      : '10%',
                  }}
                />
              </div>
              <p className="text-xs text-amber-600 mt-2">
                Podés navegar a otras secciones — el procesamiento continúa en segundo plano.
              </p>
            </div>
          )}

          <div className="flex gap-3">
            <button
              onClick={procesar}
              disabled={ocupado || !cantidadArchivos}
              className="btn btn-primary"
            >
              {loading ? (
                <><span className="animate-spin inline-block">⏳</span> Procesando...</>
              ) : (
                <>▶️ Procesar {cantidadArchivos > 0 ? `(${cantidadArchivos.toLocaleString()})` : ''}</>
              )}
            </button>
            {loading && (
              <button onClick={cancelar} className="btn btn-danger animate-pulse">
                🛑 Cancelar
              </button>
            )}
          </div>
        </div>
      </div>

      {resultado && (
        <div className="card p-6">
          <h3 className="font-display text-lg font-bold text-gray-800 mb-4">
            {resultado.cancelado ? '⚠️ Procesamiento cancelado' : '✅ Lote completado'}
          </h3>

          {resultado.cancelado && (
            <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-4">
              Detuviste el lote. Los archivos que no se procesaron no se cuentan como errores.
            </p>
          )}

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
          <p className="text-red-600 text-sm">{error}</p>
        </div>
      )}
    </div>
  );
}
