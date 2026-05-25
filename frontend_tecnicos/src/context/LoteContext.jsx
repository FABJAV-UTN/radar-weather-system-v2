// src/context/LoteContext.jsx
import { createContext, useContext, useState, useRef, useCallback } from 'react';
import { api, cancelRequest } from '../services/api';

const LoteContext = createContext(null);

export function LoteProvider({ children }) {
  const [archivos, setArchivos] = useState([]);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [procesados, setProcesados] = useState(0); // contador en tiempo real
  const [currentRequestId, setCurrentRequestId] = useState(null);
  const inputRef = useRef(null);

  const seleccionarArchivos = useCallback((files) => {
    const filtrados = Array.from(files).filter(
      f => f.name.endsWith('.gif') || f.name.endsWith('.png')
    );
    setArchivos(filtrados);
    setResultado(null);
    setError('');
    setProcesados(0);
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

    // 1. Señal directa al backend (fetch independiente, sin AbortController del lote)
    const token = localStorage.getItem('access_token');
    try {
      await fetch(`${import.meta.env.VITE_API_URL || '/api/v1'}/procesamiento/lote/cancelar`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    } catch {
      // ignorado
    }

    // 2. Abortar el fetch principal
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
      archivos, resultado, error, loading, procesados, inputRef,
      seleccionarArchivos, procesar, cancelar, limpiar,
    }}>
      {children}
    </LoteContext.Provider>
  );
}

export function useLote() {
  return useContext(LoteContext);
}
