import { useState, useCallback, useRef } from 'react';
import { api } from '../services/api';

export default function ProcesamientoLote() {
  const [files, setFiles] = useState([]);
  const [resultado, setResultado] = useState(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files)
      .filter(f => f.name.match(/\.(gif|png)$/i));
    setFiles(prev => [...prev, ...dropped]);
  }, []);

  const onFileSelect = (e) => {
    const selected = Array.from(e.target.files)
      .filter(f => f.name.match(/\.(gif|png)$/i));
    setFiles(prev => [...prev, ...selected]);
  };

  const removeFile = (index) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  const procesar = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setResultado(null);

    try {
      const res = await api.procesarLoteUpload(files);
      setResultado(res);
      setFiles([]);
    } catch (err) {
      alert('Error: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto p-6">
      <h1 className="text-2xl font-display font-bold text-nacion mb-6">
        Procesamiento por Lotes
      </h1>

      {/* Drop zone */}
      <div
        onDrop={onDrop}
        onDragOver={e => e.preventDefault()}
        onClick={() => inputRef.current?.click()}
        className="border-2 border-dashed border-celeste rounded-xl p-10 text-center 
                   hover:bg-celeste-light cursor-pointer transition-colors"
      >
        <div className="text-4xl mb-2">📁</div>
        <p className="font-semibold text-gray-700">
          Arrastrá archivos .gif o .png aquí
        </p>
        <p className="text-sm text-gray-500 mt-1">
          O hacé click para seleccionar
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".gif,.png"
          onChange={onFileSelect}
          className="hidden"
        />
      </div>

      {/* Lista de archivos */}
      {files.length > 0 && (
        <div className="mt-6 card p-4">
          <h3 className="font-semibold mb-3">
            {files.length} archivo{files.length > 1 ? 's' : ''} seleccionado{files.length > 1 ? 's' : ''}
          </h3>
          <ul className="space-y-2">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex items-center justify-between bg-gray-50 px-3 py-2 rounded">
                <span className="text-sm truncate">{f.name}</span>
                <button 
                  onClick={() => removeFile(i)}
                  className="text-red-500 hover:text-red-700 text-sm"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
          <button
            onClick={procesar}
            disabled={loading}
            className="btn btn-primary w-full mt-4 justify-center"
          >
            {loading ? (
              <>
                <span className="animate-pulse-dot">⏳</span> Procesando...
              </>
            ) : (
              <>🚀 Procesar {files.length} archivo{files.length > 1 ? 's' : ''}</>
            )}
          </button>
        </div>
      )}

      {/* Resultados */}
      {resultado && (
        <div className="mt-6 card p-4 animate-slide-up">
          <h3 className="font-semibold mb-3 text-nacion">Resultados</h3>
          <div className="grid grid-cols-4 gap-2 mb-4 text-center">
            <div className="bg-gray-50 p-2 rounded">
              <div className="text-lg font-bold">{resultado.total}</div>
              <div className="text-xs text-gray-500">Total</div>
            </div>
            <div className="bg-emerald-50 p-2 rounded">
              <div className="text-lg font-bold text-emerald-600">{resultado.exitosos}</div>
              <div className="text-xs text-emerald-600">Éxitos</div>
            </div>
            <div className="bg-red-50 p-2 rounded">
              <div className="text-lg font-bold text-red-600">{resultado.fallidos}</div>
              <div className="text-xs text-red-600">Fallidos</div>
            </div>
            <div className="bg-amber-50 p-2 rounded">
              <div className="text-lg font-bold text-amber-600">{resultado.saltados}</div>
              <div className="text-xs text-amber-600">Duplicados</div>
            </div>
          </div>

          <div className="space-y-1 max-h-60 overflow-y-auto">
            {resultado.resultados.map((r, i) => (
              <div key={i} className={`text-sm px-3 py-2 rounded flex justify-between
                ${r.estado === 'ok' ? 'bg-emerald-50 text-emerald-700' : 
                  r.estado === 'saltado' ? 'bg-amber-50 text-amber-700' : 
                  'bg-red-50 text-red-700'}`}>
                <span className="truncate">{r.archivo}</span>
                <span className="text-xs font-mono">
                  {r.estado === 'ok' ? `✓ ID:${r.imagen_id}` : 
                   r.estado === 'saltado' ? '⚠ duplicado' : 
                   `✗ ${r.error.slice(0, 30)}`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}