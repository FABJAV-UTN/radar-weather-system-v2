import { useState, useEffect, useRef } from 'react';
import { api, cancelRequest } from '../services/api';

// ── Panel: Procesamiento único (URL o archivo local) ──────────────────────────

function PanelUnico() {
  const [modo, setModo] = useState('url');
  const [url, setUrl] = useState('');
  const [filePath, setFilePath] = useState('');
  const [archivoLocal, setArchivoLocal] = useState(null);
  const [localSubmodo, setLocalSubmodo] = useState('subir');
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentRequestId, setCurrentRequestId] = useState(null);
  const [logs, setLogs] = useState([]);
  const logsEndRef = useRef(null);

  const addLog = (msg, type = 'info') => {
    setLogs(prev => [...prev, { msg, type, time: new Date().toLocaleTimeString() }].slice(-30));
  };

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

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
      } else if (localSubmodo === 'subir') {
        addLog(`Subiendo archivo: ${archivoLocal.name}`, 'info');
        promise = api.procesarUploadUnico(archivoLocal);
      } else {
        addLog(`Procesando archivo en servidor: ${filePath}`, 'info');
        promise = api.procesarLocal(filePath);
      }

      setCurrentRequestId(promise._id);
      addLog(`Request #${promise._id} — Procesando pipeline de 7 fases...`, 'info');

      const data = await promise;
      setResultado(data);
      addLog(`✅ Completado — Imagen #${data.imagen_id}`, 'success');
      if (data.score_match != null) addLog(`Score geolocalización: ${(data.score_match * 100).toFixed(1)}%`, 'info');
      if (data.tiene_marco) addLog('Marco DACC detectado y recortado', 'info');
    } catch (err) {
      if (err.name === 'AbortError' || err.message?.includes('abort')) {
        addLog('🛑 Cancelado por el usuario', 'warning');
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
    <div className="space-y-4">
      <div className="card p-6">
        <h3 className="font-display text-lg font-bold text-gray-800 mb-1">⚡ Procesamiento único</h3>
        <p className="text-sm text-gray-500 mb-5">
          Ejecuta el pipeline una sola vez desde la URL del DACC o subiendo un archivo .gif/.png.
        </p>

        {/* Selector de modo */}
        <div className="flex gap-2 mb-5">
          <button onClick={() => setModo('url')} className={`btn ${modo === 'url' ? 'btn-primary' : 'btn-outline'}`}>
            🌐 URL DACC
          </button>
          <button onClick={() => setModo('local')} className={`btn ${modo === 'local' ? 'btn-primary' : 'btn-outline'}`}>
            💾 Archivo Local
          </button>
        </div>

        {modo === 'url' ? (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              URL del radar <span className="text-gray-400 font-normal">(opcional — usa la URL por defecto si se deja vacío)</span>
            </label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="form-input"
              placeholder="https://www2.contingencias.mendoza.gov.ar/radar/latest.gif"
            />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setLocalSubmodo('subir')}
                className={`btn text-sm ${localSubmodo === 'subir' ? 'btn-primary' : 'btn-outline'}`}
              >
                📤 Subir archivo
              </button>
              <button
                type="button"
                onClick={() => setLocalSubmodo('ruta')}
                className={`btn text-sm ${localSubmodo === 'ruta' ? 'btn-primary' : 'btn-outline'}`}
              >
                🖥️ Ruta en servidor
              </button>
            </div>

            {localSubmodo === 'subir' ? (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Archivo .gif o .png desde tu computadora
                </label>
                <input
                  type="file"
                  accept=".gif,.png"
                  onChange={(e) => {
                    setArchivoLocal(e.target.files?.[0] || null);
                    e.target.value = '';
                  }}
                  className="form-input file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:bg-celeste file:text-white file:cursor-pointer"
                />
                {archivoLocal && (
                  <p className="text-xs text-gray-500 mt-2">
                    Seleccionado: <span className="font-mono">{archivoLocal.name}</span>
                  </p>
                )}
              </div>
            ) : (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Ruta absoluta al archivo dentro del contenedor backend
                </label>
                <input
                  type="text"
                  value={filePath}
                  onChange={(e) => setFilePath(e.target.value)}
                  className="form-input"
                  placeholder="/app/data/radar_20260524_143000.gif"
                />
                <p className="text-xs text-gray-400 mt-1">
                  Solo para archivos que ya están en el servidor (Docker), no en tu PC.
                </p>
              </div>
            )}
          </div>
        )}

        <div className="flex gap-3 mt-5">
          <button
            onClick={handleProcesar}
            disabled={
              loading
              || (modo === 'local' && localSubmodo === 'subir' && !archivoLocal)
              || (modo === 'local' && localSubmodo === 'ruta' && !filePath)
            }
            className="btn btn-primary"
          >
            {loading
              ? <><span className="animate-spin">⏳</span> Procesando...</>
              : <>▶️ Procesar {modo === 'url' ? 'URL' : 'Archivo'}</>
            }
          </button>
          {loading && (
            <button onClick={handleCancelar} className="btn btn-danger animate-pulse">
              🛑 Cancelar
            </button>
          )}
        </div>
      </div>

      {/* Log de operación */}
      {logs.length > 0 && (
        <div className="card p-4 bg-gray-900 text-gray-100 font-mono text-sm">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 font-semibold">📋 Log</span>
            <span className="text-xs text-gray-500">{logs.length} eventos</span>
          </div>
          <div className="space-y-1 max-h-40 overflow-auto">
            {logs.map((log, i) => (
              <div key={i} className={`flex gap-2 ${
                log.type === 'error' ? 'text-red-400' :
                log.type === 'warning' ? 'text-amber-400' :
                log.type === 'success' ? 'text-emerald-400' :
                'text-gray-300'
              }`}>
                <span className="text-gray-600 shrink-0">[{log.time}]</span>
                <span>{log.msg}</span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}

      {/* Resultado */}
      {resultado && (
        <div className="card p-6 border-emerald-200 bg-emerald-50/30">
          <h3 className="font-display text-lg font-bold text-emerald-800 mb-4">✅ Pipeline completado</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white p-4 rounded-lg border border-emerald-100 text-center">
              <p className="text-xs text-gray-500 uppercase">Imagen ID</p>
              <p className="text-2xl font-bold text-gray-800">#{resultado.imagen_id}</p>
            </div>
            <div className="bg-white p-4 rounded-lg border border-emerald-100 text-center">
              <p className="text-xs text-gray-500 uppercase">Score Match</p>
              <p className="text-2xl font-bold text-emerald-600">{(resultado.score_match * 100).toFixed(1)}%</p>
            </div>
            <div className="bg-white p-4 rounded-lg border border-emerald-100 text-center">
              <p className="text-xs text-gray-500 uppercase">Píxeles orig.</p>
              <p className="text-2xl font-bold text-gray-800">{resultado.pixeles_originales?.toLocaleString()}</p>
            </div>
            <div className="bg-white p-4 rounded-lg border border-emerald-100 text-center">
              <p className="text-xs text-gray-500 uppercase">Error relleno</p>
              <p className="text-2xl font-bold text-gray-800">{resultado.error_relleno_pct}%</p>
            </div>
          </div>
          {resultado.tiene_marco && (
            <p className="mt-3 text-sm text-gray-500">🖼️ Marco DACC detectado y recortado</p>
          )}
        </div>
      )}

      {error && !resultado && (
        <div className="card p-5 border-red-200 bg-red-50">
          <p className="text-red-600 text-sm">{error}</p>
        </div>
      )}
    </div>
  );
}


// ── Panel: Scheduler continuo ─────────────────────────────────────────────────

function PanelScheduler() {
  const [estado, setEstado] = useState(null);
  const [loadingAccion, setLoadingAccion] = useState(false);
  const [error, setError] = useState('');
  const [intervalo, setIntervalo] = useState(120);
  const [urlCustom, setUrlCustom] = useState('');
  const pollingRef = useRef(null);

  const cargarEstado = async () => {
    try {
      const data = await api.schedulerEstado();
      setEstado(data);
    } catch (err) {
      console.error('Error al obtener estado del scheduler:', err);
    }
  };

  useEffect(() => {
    cargarEstado();
    // Polling cada 5 segundos para actualizar el estado
    pollingRef.current = setInterval(cargarEstado, 5000);
    return () => clearInterval(pollingRef.current);
  }, []);

  const handleIniciar = async () => {
    setError('');
    setLoadingAccion(true);
    try {
      await api.schedulerStart(urlCustom || null, intervalo);
      await cargarEstado();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingAccion(false);
    }
  };

  const handleDetener = async () => {
    setError('');
    setLoadingAccion(true);
    try {
      await api.schedulerStop();
      await cargarEstado();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingAccion(false);
    }
  };

  const activo = estado?.activo ?? false;

  return (
    <div className="space-y-4">
      {/* Estado actual */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="font-display text-lg font-bold text-gray-800">🔄 Procesamiento continuo</h3>
            <p className="text-sm text-gray-500 mt-0.5">
              Descarga y procesa automáticamente cada N segundos. Si falla, espera y reintenta.
            </p>
          </div>
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-semibold ${
            activo ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'
          }`}>
            <span className={`w-2 h-2 rounded-full ${activo ? 'bg-emerald-500 animate-pulse' : 'bg-gray-400'}`} />
            {activo ? 'Activo' : 'Detenido'}
          </div>
        </div>

        {/* Contadores */}
        {estado && (
          <div className="grid grid-cols-3 gap-3 mb-5">
            <div className="bg-emerald-50 rounded-lg p-3 border border-emerald-100 text-center">
              <p className="text-2xl font-bold text-emerald-600">{estado.total_exitosos}</p>
              <p className="text-xs text-emerald-700 uppercase font-medium">Exitosos</p>
            </div>
            <div className="bg-red-50 rounded-lg p-3 border border-red-100 text-center">
              <p className="text-2xl font-bold text-red-500">{estado.total_fallidos}</p>
              <p className="text-xs text-red-600 uppercase font-medium">Fallidos/Saltados</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3 border border-gray-200 text-center">
              <p className="text-2xl font-bold text-gray-600">
                {estado.proximo_intento_en != null ? `${estado.proximo_intento_en}s` : '—'}
              </p>
              <p className="text-xs text-gray-500 uppercase font-medium">Próximo en</p>
            </div>
          </div>
        )}

        {/* Último resultado */}
        {estado?.ultimo_resultado && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 mb-5">
            <p className="text-xs text-gray-400 uppercase font-medium mb-1">Último resultado</p>
            <p className="text-sm text-gray-700">{estado.ultimo_resultado}</p>
            {estado.ultimo_intento && (
              <p className="text-xs text-gray-400 mt-1">
                {new Date(estado.ultimo_intento).toLocaleString('es-AR')}
              </p>
            )}
          </div>
        )}

        {/* Config (solo si está detenido) */}
        {!activo && (
          <div className="space-y-3 mb-5 p-4 bg-gray-50 rounded-lg border border-gray-200">
            <p className="text-xs font-semibold text-gray-500 uppercase">Configuración</p>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Intervalo entre descargas (segundos)
              </label>
              <input
                type="number"
                min={30}
                max={3600}
                value={intervalo}
                onChange={(e) => setIntervalo(Number(e.target.value))}
                className="form-input w-40"
              />
              <p className="text-xs text-gray-400 mt-1">Mínimo recomendado: 120s (2 minutos)</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                URL alternativa <span className="text-gray-400 font-normal">(opcional)</span>
              </label>
              <input
                type="url"
                value={urlCustom}
                onChange={(e) => setUrlCustom(e.target.value)}
                className="form-input"
                placeholder="Dejar vacío para usar la URL por defecto del servidor"
              />
            </div>
          </div>
        )}

        {/* Botones */}
        <div className="flex gap-3">
          {!activo ? (
            <button
              onClick={handleIniciar}
              disabled={loadingAccion}
              className="btn btn-success"
            >
              {loadingAccion ? <><span className="animate-spin">⏳</span> Iniciando...</> : <>▶️ Iniciar scheduler</>}
            </button>
          ) : (
            <button
              onClick={handleDetener}
              disabled={loadingAccion}
              className="btn btn-danger"
            >
              {loadingAccion ? <><span className="animate-spin">⏳</span> Deteniendo...</> : <>⏹️ Detener scheduler</>}
            </button>
          )}
          <button onClick={cargarEstado} className="btn btn-outline text-sm" disabled={loadingAccion}>
            🔃 Actualizar
          </button>
        </div>

        {error && (
          <p className="mt-3 text-sm text-red-600">{error}</p>
        )}

        {activo && (
          <p className="mt-3 text-xs text-gray-400">
            El scheduler corre en el servidor — podés cerrar esta pestaña y seguirá funcionando.
            El polling se actualiza automáticamente cada 5 segundos.
          </p>
        )}
      </div>
    </div>
  );
}


// ── Componente principal ──────────────────────────────────────────────────────

export function Procesamiento() {
  const [tab, setTab] = useState('unico');

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit">
        <button
          onClick={() => setTab('unico')}
          className={`px-5 py-2 rounded-md text-sm font-semibold transition-all ${
            tab === 'unico'
              ? 'bg-white text-gray-800 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          ⚡ Una vez
        </button>
        <button
          onClick={() => setTab('continuo')}
          className={`px-5 py-2 rounded-md text-sm font-semibold transition-all ${
            tab === 'continuo'
              ? 'bg-white text-gray-800 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          🔄 Continuo
        </button>
      </div>

      {tab === 'unico' ? <PanelUnico /> : <PanelScheduler />}
    </div>
  );
}
