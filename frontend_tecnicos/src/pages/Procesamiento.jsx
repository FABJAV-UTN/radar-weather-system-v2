import { useState, useEffect } from 'react';
import {
  Play, Square, Download, FolderOpen, FileText, Globe,
  RefreshCw, CheckCircle, XCircle, SkipForward, AlertCircle,
  Clock, Activity
} from 'lucide-react';
import { api } from '../services/api.js';

export default function Procesamiento() {
  // ── Loop ─────────────────────────────────────────────────────────────────
  const [loopEstado, setLoopEstado] = useState({
    activo: false,
    ciclos_completados: 0,
    ciclos_exitosos: 0,
    intervalo_minutos: 2,
    ultimo_error: '',
    url: null,
  });
  const [loopIntervalo, setLoopIntervalo] = useState(2);
  const [loopUrl, setLoopUrl] = useState('');
  const [loopLoading, setLoopLoading] = useState(false);

  // ── URL única ────────────────────────────────────────────────────────────
  const [urlUnica, setUrlUnica] = useState('');
  const [urlLoading, setUrlLoading] = useState(false);
  const [urlResult, setUrlResult] = useState(null);
  const [urlError, setUrlError] = useState('');

  // ── Lote ─────────────────────────────────────────────────────────────────
  const [carpeta, setCarpeta] = useState('');
  const [patron, setPatron] = useState('*.gif');
  const [loteLoading, setLoteLoading] = useState(false);
  const [loteResult, setLoteResult] = useState(null);
  const [loteError, setLoteError] = useState('');

  // ── Local ──────────────────────────────────────────────────────────────────
  const [archivoLocal, setArchivoLocal] = useState('');
  const [localLoading, setLocalLoading] = useState(false);
  const [localResult, setLocalResult] = useState(null);
  const [localError, setLocalError] = useState('');

  // Poll loop status
  useEffect(() => {
    cargarLoopEstado();
    const interval = setInterval(cargarLoopEstado, 5000);
    return () => clearInterval(interval);
  }, []);

  async function cargarLoopEstado() {
    try {
      const res = await api.estadoLoop();
      setLoopEstado(res);
    } catch {
      // silently fail
    }
  }

  async function iniciarLoop() {
    setLoopLoading(true);
    try {
      await api.iniciarLoop(loopIntervalo, loopUrl);
      await cargarLoopEstado();
    } catch (err) {
      alert(err.message);
    } finally {
      setLoopLoading(false);
    }
  }

  async function detenerLoop() {
    setLoopLoading(true);
    try {
      await api.detenerLoop();
      await cargarLoopEstado();
    } catch (err) {
      alert(err.message);
    } finally {
      setLoopLoading(false);
    }
  }

  async function procesarUrl(e) {
    e.preventDefault();
    setUrlLoading(true);
    setUrlResult(null);
    setUrlError('');
    try {
      const data = await api.procesarUrl(urlUnica);
      setUrlResult(data);
    } catch (err) {
      setUrlError(err.message);
    } finally {
      setUrlLoading(false);
    }
  }

  async function procesarLote(e) {
    e.preventDefault();
    setLoteLoading(true);
    setLoteResult(null);
    setLoteError('');
    try {
      const data = await api.procesarLote(carpeta, patron);
      setLoteResult(data);
    } catch (err) {
      setLoteError(err.message);
    } finally {
      setLoteLoading(false);
    }
  }

  async function procesarLocal(e) {
    e.preventDefault();
    setLocalLoading(true);
    setLocalResult(null);
    setLocalError('');
    try {
      const data = await api.procesarLocal(archivoLocal);
      setLocalResult(data);
    } catch (err) {
      setLocalError(err.message);
    } finally {
      setLocalLoading(false);
    }
  }

  function fmtScore(s) {
    if (s == null) return '—';
    return (s * 100).toFixed(1) + '%';
  }

  return (
    <div className="space-y-6 max-w-5xl">
      {/* ── LOOP URL ─────────────────────────────────────────────────────── */}
      <div className="card">
        <div className="flex items-center justify-between px-6 py-4"
          style={{ background: 'linear-gradient(135deg, #003366, #004a99)' }}>
          <h2 className="font-display text-base font-bold text-white uppercase tracking-wide flex items-center gap-2">
            <Activity className="w-5 h-5" />
            Descarga Periódica (URL DACC)
          </h2>
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-semibold ${
            loopEstado.activo
              ? 'bg-emerald-50 text-emerald-600 border border-emerald-200'
              : 'bg-gray-100 text-gray-500 border border-gray-200'
          }`}>
            {loopEstado.activo ? (
              <><div className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse-dot" /> Activo</>
            ) : (
              <><div className="w-2.5 h-2.5 rounded-full bg-gray-400" /> Inactivo</>
            )}
          </div>
        </div>

        <div className="p-6 space-y-5">
          {loopEstado.activo && (
            <div className="flex items-start gap-3 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3 text-sm text-emerald-700">
              <CheckCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold">Loop corriendo</p>
                <p className="text-emerald-600/80 mt-0.5">
                  {loopEstado.ciclos_completados} ciclos totales, {loopEstado.ciclos_exitosos} exitosos.
                  {loopEstado.ultimo_error && (
                    <span className="block mt-1 text-red-500">Último error: {loopEstado.ultimo_error}</span>
                  )}
                </p>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
                <Clock className="w-3.5 h-3.5 inline mr-1" />
                Intervalo (minutos)
              </label>
              <input
                type="number"
                min={1}
                max={60}
                value={loopIntervalo}
                onChange={e => setLoopIntervalo(parseInt(e.target.value) || 2)}
                disabled={loopEstado.activo}
                className="form-input"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
                <Globe className="w-3.5 h-3.5 inline mr-1" />
                URL alternativa (opcional)
              </label>
              <input
                type="text"
                value={loopUrl}
                onChange={e => setLoopUrl(e.target.value)}
                placeholder="Dejar vacío para usar URL del .env"
                disabled={loopEstado.activo}
                className="form-input"
              />
            </div>
          </div>

          <div className="flex gap-3">
            <button
              onClick={iniciarLoop}
              disabled={loopEstado.activo || loopLoading}
              className="btn btn-success"
            >
              {loopLoading && !loopEstado.activo ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <><Play className="w-4 h-4" /> Iniciar loop</>
              )}
            </button>
            <button
              onClick={detenerLoop}
              disabled={!loopEstado.activo || loopLoading}
              className="btn btn-danger"
            >
              {loopLoading && loopEstado.activo ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <><Square className="w-4 h-4" /> Detener loop</>
              )}
            </button>
            <button
              onClick={cargarLoopEstado}
              className="btn btn-outline"
              title="Actualizar estado"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* ── DESCARGA ÚNICA URL ─────────────────────────────────────────────── */}
      <div className="card">
        <div className="px-6 py-4" style={{ background: 'linear-gradient(135deg, #003366, #004a99)' }}>
          <h2 className="font-display text-base font-bold text-white uppercase tracking-wide flex items-center gap-2">
            <Download className="w-5 h-5" />
            Descarga Única (URL)
          </h2>
        </div>
        <div className="p-6">
          <form onSubmit={procesarUrl} className="space-y-4">
            <div>
              <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
                URL alternativa (opcional)
              </label>
              <input
                type="text"
                value={urlUnica}
                onChange={e => setUrlUnica(e.target.value)}
                placeholder="Dejar vacío para usar URL DACC por defecto"
                className="form-input"
              />
            </div>

            {urlError && (
              <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-600">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                {urlError}
              </div>
            )}

            {urlResult && (
              <div className={`flex items-start gap-2 rounded-lg px-4 py-3 text-sm ${
                urlResult.exito
                  ? 'bg-emerald-50 border border-emerald-200 text-emerald-700'
                  : 'bg-red-50 border border-red-200 text-red-600'
              }`}>
                {urlResult.exito ? <CheckCircle className="w-4 h-4 flex-shrink-0 mt-0.5" /> : <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />}
                <div>
                  {urlResult.exito
                    ? <>Imagen <strong>#{urlResult.imagen_id}</strong> procesada — Score: <strong>{fmtScore(urlResult.score_match)}</strong></>
                    : <>Error: {urlResult.mensaje_error}</>
                  }
                </div>
              </div>
            )}

            <button type="submit" disabled={urlLoading} className="btn btn-primary">
              {urlLoading ? (
                <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Procesando...</>
              ) : (
                <><Download className="w-4 h-4" /> Descargar y procesar</>
              )}
            </button>
          </form>
        </div>
      </div>

      {/* ── LOTE ───────────────────────────────────────────────────────────── */}
      <div className="card">
        <div className="px-6 py-4" style={{ background: 'linear-gradient(135deg, #003366, #004a99)' }}>
          <h2 className="font-display text-base font-bold text-white uppercase tracking-wide flex items-center gap-2">
            <FolderOpen className="w-5 h-5" />
            Procesamiento por Lote
          </h2>
        </div>
        <div className="p-6">
          <form onSubmit={procesarLote} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
                  Ruta de la carpeta (absoluta)
                </label>
                <input
                  type="text"
                  value={carpeta}
                  onChange={e => setCarpeta(e.target.value)}
                  placeholder="/home/usuario/radar/imagenes"
                  required
                  className="form-input"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
                  Patrón de archivos
                </label>
                <select value={patron} onChange={e => setPatron(e.target.value)} className="form-select">
                  <option value="*.gif">*.gif</option>
                  <option value="*.png">*.png</option>
                  <option value="*.GIF">*.GIF (mayúsculas)</option>
                </select>
              </div>
            </div>

            {loteError && (
              <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-600">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                {loteError}
              </div>
            )}

            {loteResult && (
              <div className="space-y-3">
                <div className={`flex items-start gap-2 rounded-lg px-4 py-3 text-sm ${
                  loteResult.fallidos === 0
                    ? 'bg-emerald-50 border border-emerald-200 text-emerald-700'
                    : 'bg-amber-50 border border-amber-200 text-amber-700'
                }`}>
                  <Activity className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  <div className="flex gap-4 flex-wrap">
                    <span>Total: <strong>{loteResult.total}</strong></span>
                    <span className="text-emerald-600">✓ Exitosos: <strong>{loteResult.exitosos}</strong></span>
                    <span className="text-red-500">✗ Fallidos: <strong>{loteResult.fallidos}</strong></span>
                    <span className="text-gray-500">⊘ Saltados: <strong>{loteResult.saltados}</strong></span>
                  </div>
                </div>

                {loteResult.total > 0 && (
                  <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${(loteResult.exitosos / loteResult.total) * 100}%`,
                        background: 'linear-gradient(90deg, #0099dd, #0066cc)'
                      }}
                    />
                  </div>
                )}

                {loteResult.resultados?.filter(r => r.estado !== 'ok').length > 0 && (
                  <details className="group">
                    <summary className="cursor-pointer text-sm text-gray-500 font-semibold flex items-center gap-1 hover:text-gray-700">
                      <AlertCircle className="w-4 h-4" />
                      Ver archivos con problemas ({loteResult.resultados.filter(r => r.estado !== 'ok').length})
                    </summary>
                    <div className="mt-3 max-h-52 overflow-y-auto space-y-1.5">
                      {loteResult.resultados.filter(r => r.estado !== 'ok').map((r, i) => (
                        <div key={i} className="text-xs px-3 py-2 border-l-3 border-red-400 bg-red-50/50 text-gray-600 rounded-r">
                          <strong className="text-gray-800">{r.archivo}</strong>: {r.error}
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )}

            <button type="submit" disabled={loteLoading || !carpeta} className="btn btn-primary">
              {loteLoading ? (
                <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Procesando lote...</>
              ) : (
                <><Play className="w-4 h-4" /> Iniciar procesamiento por lote</>
              )}
            </button>
          </form>
        </div>
      </div>

      {/* ── ARCHIVO LOCAL ────────────────────────────────────────────────── */}
      <div className="card">
        <div className="px-6 py-4" style={{ background: 'linear-gradient(135deg, #003366, #004a99)' }}>
          <h2 className="font-display text-base font-bold text-white uppercase tracking-wide flex items-center gap-2">
            <FileText className="w-5 h-5" />
            Archivo Local Único
          </h2>
        </div>
        <div className="p-6">
          <form onSubmit={procesarLocal} className="space-y-4">
            <div>
              <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
                Ruta completa al archivo
              </label>
              <input
                type="text"
                value={archivoLocal}
                onChange={e => setArchivoLocal(e.target.value)}
                placeholder="/home/usuario/radar/radar_20260523_1430.gif"
                required
                className="form-input"
              />
            </div>

            {localError && (
              <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-600">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                {localError}
              </div>
            )}

            {localResult && (
              <div className={`flex items-start gap-2 rounded-lg px-4 py-3 text-sm ${
                localResult.exito
                  ? 'bg-emerald-50 border border-emerald-200 text-emerald-700'
                  : 'bg-red-50 border border-red-200 text-red-600'
              }`}>
                {localResult.exito ? <CheckCircle className="w-4 h-4 flex-shrink-0 mt-0.5" /> : <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />}
                <div>
                  {localResult.exito
                    ? <>Imagen <strong>#{localResult.imagen_id}</strong> procesada — Score: <strong>{fmtScore(localResult.score_match)}</strong></>
                    : <>Error: {localResult.mensaje_error}</>
                  }
                </div>
              </div>
            )}

            <button type="submit" disabled={localLoading || !archivoLocal} className="btn btn-primary">
              {localLoading ? (
                <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Procesando...</>
              ) : (
                <><Play className="w-4 h-4" /> Procesar archivo</>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
