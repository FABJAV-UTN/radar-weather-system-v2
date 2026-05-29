// src/context/LoteContext.jsx
import { createContext, useContext, useState, useRef, useCallback } from 'react';
import { api, cancelRequest } from '../services/api';

const LoteContext = createContext(null);

export function LoteProvider({ children }) {
  const [archivos, setArchivos] = useState([]);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [escaneando, setEscaneando] = useState(false);
  const [procesados, setProcesados] = useState(0);
  const [currentRequestId, setCurrentRequestId] = useState(null);
  const inputRef = useRef(null);

  const seleccionarArchivos = useCallback((files) => {
    // CRÍTICO: convertir FileList a array JS ANTES del setTimeout.
    // El FileList del browser se invalida cuando se limpia el input (e.target.value = '')
    // y dentro del setTimeout ya aparece vacío.
    const todosLosArchivos = Array.from(files);

    setEscaneando(true);
    setResultado(null);
    setError('');
    setProcesados(0);

    // setTimeout(0) le da al browser un tick para renderizar el cartel "escaneando"
    // antes de bloquearse filtrando (puede ser 100k+ archivos)
    const inicio = Date.now();
    const MINIMO_MS = 800;

    setTimeout(() => {
      const filtrados = todosLosArchivos.filter(
        f => /\.(gif|png)$/i.test(f.name)
      );
      setArchivos(filtrados);

      // El cartel dura mínimo MINIMO_MS para que no sea un flash imperceptible
      const restante = MINIMO_MS - (Date.now() - inicio);
      setTimeout(() => setEscaneando(false), Math.max(0, restante));
    }, 0);
  }, []);

  const procesar = useCallback(async () => {
    if (!archivos.length) return;
    setError('');
    setResultado(null);
    setLoading(true);
    setProcesados(0);

    try {
      const promise = api.procesarUploadLote(archivos);
      setCurrentRequestId(promise._id);
      const data = await promise;
      setResultado(data);
      setProcesados(data.exitosos + data.fallidos);
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
  }, [archivos]);

  const cancelar = useCallback(async () => {
    if (!currentRequestId) return;

    const token = localStorage.getItem('access_token');
    try {
      await fetch(`${import.meta.env.VITE_API_URL || '/api/v1'}/procesamiento/lote/cancelar`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    } catch {
      // ignorado
    }

    cancelRequest(currentRequestId);
  }, [currentRequestId]);

  const limpiar = useCallback(() => {
    setArchivos([]);
    setResultado(null);
    setError('');
    setProcesados(0);
  }, []);

  return (
    <LoteContext.Provider value={{
      archivos, resultado, error, loading, escaneando, procesados, inputRef,
      seleccionarArchivos, procesar, cancelar, limpiar,
    }}>
      {children}
    </LoteContext.Provider>
  );
}

export function useLote() {
  return useContext(LoteContext);
}
