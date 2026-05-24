import { useState } from 'react';
import { api, cancelRequest } from '../services/api';

export function Procesamiento() {
  const [modo, setModo] = useState('url'); // 'url' | 'local'
  const [url, setUrl] = useState('');
  const [filePath, setFilePath] = useState('');
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentRequestId, setCurrentRequestId] = useState(null);
  const [logs, setLogs] = useState([]);

  const addLog = (msg, type = 'info') => {
    setLogs(prev => [...prev, { msg, type, time: new Date().toLocaleTimeString() }].slice(-20));
  };

  const handleProcesar = async () => {
    setError('');
    setResultado(null);
    setLoading(true);
    setLogs([]);

    try {
      let promise;
      if (modo === 'url') {
        addLog('Iniciando descarga desde URL DACC...', 'info');
        promise = api.procesarUrl(url || undefined);
      } else {
        addLog(`Procesando archivo local: ${filePath}`, 'info');
        promise = api.procesarLocal(filePath);
      }

      setCurrentRequestId(promise._id);
      addLog(`Request ID: ${promise._id} — Esperando respuesta...`, 'info');

      const data = await promise;
      setResultado(data);
      addLog(`✅ Completado — Imagen #${data.imagen_id}`, 'success');
      if (data.score_match) addLog(`Score geolocalización: ${(data.score_match * 100).toFixed(1)}%`, 'info');
    } catch (err) {
      if (err.name === 'AbortError' || err.message?.includes('abort')) {
        addLog('🛑 Procesamiento cancelado por el usuario', 'warning');
        setError('Cancelado por el usuario');
      } else {
        addLog(`❌ Error: ${err.message}`, 'error');
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
      addLog('🛑 Enviando señal de cancelación...', 'warning');
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Selector de modo */}
      <div className="card p-6">
        <div className="flex gap-2 mb-6">
          <button
            onClick={() => setModo('url')}
            className={`btn ${modo === 'url' ? 'btn-primary' : 'btn-outline'}`}
          >
            🌐 URL DACC
          </button>
          <button
            onClick={() => setModo('local')}
            className={`btn ${modo === 'local' ? 'btn-primary' : 'btn-outline'}`}
          >
            💾 Archivo Local
          </button>
        </div>

        {modo === 'url' ? (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                URL del radar (opcional — usa la URL por defecto si se deja vacío)
              </label>
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                className="form-input"
                placeholder="https://www2.contingencias.mendoza.gov.ar/radar/latest.gif"
              />
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Ruta absoluta al archivo
              </label>
              <input
                type="text"
                value={filePath}
                onChange={(e) => setFilePath(e.target.value)}
                className="form-input"
                placeholder="/home/fabio/Descargas/radar_20260524_143000.gif"
              />
              <p className="text-xs text-gray-400 mt-1">
                Formato esperado: radar_YYYYMMDD_HHMMSS.gif
              </p>
            </div>
          </div>
        )}

        <div className="flex gap-3 mt-6">
          <button
            onClick={handleProcesar}
            disabled={loading || (modo === 'local' && !filePath)}
            className="btn btn-primary"
          >
            {loading ? (
              <>
                <span className="animate-spin">⏳</span>
                Procesando...
              </>
            ) : (
              <>▶️ Procesar {modo === 'url' ? 'URL' : 'Archivo'}</>
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
      </div>

      {/* Logs en tiempo real */}
      {logs.length > 0 && (
        <div className="card p-4 bg-gray-900 text-gray-100 font-mono text-sm">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 font-semibold">📋 Log de operación</span>
            <span className="text-xs text-gray-500">{logs.length} eventos</span>
          </div>
          <div className="space-y-1 max-h-48 overflow-auto">
            {logs.map((log, i) => (
              <div key={i} className={`flex gap-2 ${
                log.type === 'error' ? 'text-red-400' :
                log.type === 'warning' ? 'text-amber-400' :
                log.type === 'success' ? 'text-emerald-400' :
                'text-gray-300'
              }`}>
                <span className="text-gray-600">[{log.time}]</span>
                <span>{log.msg}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Resultado */}
      {resultado && (
        <div className="card p-6 border-emerald-200 bg-emerald-50/30">
          <h3 className="font-display text-lg font-bold text-emerald-800 mb-4">
            ✅ Procesamiento completado
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white p-4 rounded-lg border border-emerald-100">
              <p className="text-xs text-gray-500 uppercase">Imagen ID</p>
              <p className="text-2xl font-bold text-gray-800">#{resultado.imagen_id}</p>
            </div>
            <div className="bg-white p-4 rounded-lg border border-emerald-100">
              <p className="text-xs text-gray-500 uppercase">Score Match</p>
              <p className="text-2xl font-bold text-emerald-600">
                {(resultado.score_match * 100).toFixed(1)}%
              </p>
            </div>
            <div className="bg-white p-4 rounded-lg border border-emerald-100">
              <p className="text-xs text-gray-500 uppercase">Píxeles originales</p>
              <p className="text-2xl font-bold text-gray-800">
                {resultado.pixeles_originales?.toLocaleString()}
              </p>
            </div>
            <div className="bg-white p-4 rounded-lg border border-emerald-100">
              <p className="text-xs text-gray-500 uppercase">Error relleno</p>
              <p className="text-2xl font-bold text-gray-800">
                {resultado.error_relleno_pct}%
              </p>
            </div>
          </div>
          {resultado.tiene_marco && (
            <p className="mt-3 text-sm text-gray-500">🖼️ Marco DACC detectado y recortado</p>
          )}
        </div>
      )}

      {/* Error */}
      {error && !resultado && (
        <div className="card p-6 border-red-200 bg-red-50">
          <h3 className="font-display text-lg font-bold text-red-700 mb-2">❌ Error</h3>
          <p className="text-red-600">{error}</p>
        </div>
      )}
    </div>
  );
}
