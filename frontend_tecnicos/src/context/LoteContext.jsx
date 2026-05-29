// src/context/LoteContext.jsx
import { createContext, useContext, useState, useRef, useCallback } from 'react';
import { flushSync } from 'react-dom';
import { api, cancelRequest, UPLOAD_LOTE_TAMANO } from '../services/api';

const MAX_DETALLE_RESULTADOS = 500;
const EXT_REGEX = /\.(gif|png)$/i;
const CARGA_CHUNK_SIZE = 5000;
const CARPETA_YIELD_CADA = 3000;

function incorporarRespuestaLote({ exitosos, fallidos, resultados }, data, soloExitos = false) {
  const nuevosExitosos = exitosos + data.exitosos;
  if (soloExitos) {
    const ok = (data.resultados || []).filter((r) => r.exito);
    return {
      exitosos: nuevosExitosos,
      fallidos,
      resultados: ok.length ? mergearResultados(resultados, ok) : resultados,
    };
  }
  const nuevosFallidos = fallidos + data.fallidos;
  const nuevosResultados = data.resultados?.length
    ? mergearResultados(resultados, data.resultados)
    : resultados;
  return { exitosos: nuevosExitosos, fallidos: nuevosFallidos, resultados: nuevosResultados };
}

function mergearResultados(acumulado, nuevos) {
  const merged = acumulado.concat(nuevos);
  if (merged.length <= MAX_DETALLE_RESULTADOS) return merged;
  const fallidos = merged.filter((r) => !r.exito);
  const exitosos = merged.filter((r) => r.exito);
  return [...fallidos, ...exitosos].slice(0, MAX_DETALLE_RESULTADOS);
}

function siguienteLote(fileList, desde, tamano) {
  const lote = [];
  let i = desde;
  while (i < fileList.length && lote.length < tamano) {
    const f = fileList[i++];
    if (EXT_REGEX.test(f.name)) lote.push(f);
  }
  return { lote, siguienteIndice: i };
}

const LoteContext = createContext(null);

export function LoteProvider({ children }) {
  const [cantidadArchivos, setCantidadArchivos] = useState(0);
  const [previewNombres, setPreviewNombres] = useState([]);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [cargandoArchivos, setCargandoArchivos] = useState(false);
  const [procesados, setProcesados] = useState(0);
  const [loteActual, setLoteActual] = useState(0);
  const [lotesTotal, setLotesTotal] = useState(0);
  const [currentRequestId, setCurrentRequestId] = useState(null);
  const fileListRef = useRef(null);
  const fileHandlesRef = useRef(null);
  const canceladoPorUsuario = useRef(false);
  const cargaGenRef = useRef(0);

  const activarCarga = useCallback(() => {
    flushSync(() => {
      setCargandoArchivos(true);
      setCantidadArchivos(0);
      setPreviewNombres([]);
      setResultado(null);
      setError('');
      setProcesados(0);
    });
    fileListRef.current = null;
    fileHandlesRef.current = null;
  }, []);

  /**
   * Carpeta vía showDirectoryPicker: tras “Aceptar” mostramos carga al instante
   * y recorremos el árbol sin bloquear (sin input webkit de 100k+).
   */
  const cargarCarpeta = useCallback(async (dirHandle) => {
    const gen = ++cargaGenRef.current;
    activarCarga();

    const handles = [];
    const nombres = [];

    async function walk(dir) {
      for await (const entry of dir.values()) {
        if (gen !== cargaGenRef.current) return;
        if (entry.kind === 'directory') {
          await walk(entry);
        } else if (EXT_REGEX.test(entry.name)) {
          handles.push(entry);
          if (nombres.length < 5) nombres.push(entry.name);
        }
        if (handles.length > 0 && handles.length % CARPETA_YIELD_CADA === 0) {
          await new Promise((r) => setTimeout(r, 0));
        }
      }
    }

    try {
      await walk(dirHandle);
      if (gen !== cargaGenRef.current) return;
      fileHandlesRef.current = handles;
      setCantidadArchivos(handles.length);
      setPreviewNombres(nombres);
    } catch (err) {
      if (gen === cargaGenRef.current) {
        setError(err.message || 'No se pudo leer la carpeta');
      }
    } finally {
      if (gen === cargaGenRef.current) {
        setCargandoArchivos(false);
      }
    }
  }, [activarCarga]);

  /** Fallback: input webkitdirectory (el freeze ocurre antes del onChange; ahí pintamos con flushSync). */
  const seleccionarArchivos = useCallback((files) => {
    if (!files?.length) {
      setCargandoArchivos(false);
      return;
    }

    const gen = ++cargaGenRef.current;
    activarCarga();

    const fileList = files;
    fileListRef.current = fileList;

    let total = 0;
    const nombres = [];
    let i = 0;

    const tick = () => {
      if (gen !== cargaGenRef.current) return;

      const fin = Math.min(i + CARGA_CHUNK_SIZE, fileList.length);
      for (; i < fin; i++) {
        const f = fileList[i];
        if (EXT_REGEX.test(f.name)) {
          total++;
          if (nombres.length < 5) nombres.push(f.name);
        }
      }

      if (i < fileList.length) {
        setTimeout(tick, 0);
      } else {
        setCantidadArchivos(total);
        setPreviewNombres(nombres);
        setCargandoArchivos(false);
      }
    };

    setTimeout(tick, 0);
  }, [activarCarga]);

  const procesar = useCallback(async () => {
    const handles = fileHandlesRef.current;
    const fileList = fileListRef.current;
    const hayHandles = handles?.length > 0;
    const hayLista = fileList?.length > 0;

    if ((!hayHandles && !hayLista) || cantidadArchivos === 0) return;

    setError('');
    setResultado(null);
    setLoading(true);
    setProcesados(0);
    canceladoPorUsuario.current = false;

    await api.iniciarLote();

    const totalAProcesar = cantidadArchivos;
    const totalLotes = Math.ceil(totalAProcesar / UPLOAD_LOTE_TAMANO);
    setLotesTotal(totalLotes);
    setLoteActual(0);

    let exitosos = 0;
    let fallidos = 0;
    let resultados = [];
    let cancelado = false;
    let loteNum = 0;

    const subirLote = async (archivos) => {
      const promise = api.procesarUploadLote(archivos);
      setCurrentRequestId(promise._id);
      return promise;
    };

    try {
      if (hayHandles) {
        for (let i = 0; i < handles.length; i += UPLOAD_LOTE_TAMANO) {
          if (canceladoPorUsuario.current) {
            cancelado = true;
            break;
          }

          const slice = handles.slice(i, i + UPLOAD_LOTE_TAMANO);
          const archivos = await Promise.all(slice.map((h) => h.getFile()));

          loteNum += 1;
          setLoteActual(loteNum);

          const data = await subirLote(archivos);

          if (canceladoPorUsuario.current) {
            cancelado = true;
            break;
          }

          ({ exitosos, fallidos, resultados } = incorporarRespuestaLote(
            { exitosos, fallidos, resultados },
            data,
            data.cancelado,
          ));
          setProcesados(exitosos + fallidos);

          if (data.cancelado) {
            cancelado = true;
            break;
          }
        }
      } else {
        let indice = 0;
        while (indice < fileList.length) {
          if (canceladoPorUsuario.current) {
            cancelado = true;
            break;
          }

          const { lote, siguienteIndice } = siguienteLote(fileList, indice, UPLOAD_LOTE_TAMANO);
          indice = siguienteIndice;
          if (!lote.length) continue;

          loteNum += 1;
          setLoteActual(loteNum);

          const data = await subirLote(lote);

          if (canceladoPorUsuario.current) {
            cancelado = true;
            break;
          }

          ({ exitosos, fallidos, resultados } = incorporarRespuestaLote(
            { exitosos, fallidos, resultados },
            data,
            data.cancelado,
          ));
          setProcesados(exitosos + fallidos);

          if (data.cancelado) {
            cancelado = true;
            break;
          }
        }
      }

      setResultado({
        total: totalAProcesar,
        exitosos,
        fallidos,
        resultados,
        cancelado,
      });
    } catch (err) {
      if (err.name === 'AbortError' || err.message?.includes('abort')) {
        cancelado = true;
        setError('Procesamiento cancelado por el usuario');
      } else {
        setError(err.message);
      }
      if (exitosos > 0 || resultados.length > 0 || cancelado) {
        setResultado({
          total: totalAProcesar,
          exitosos,
          fallidos,
          resultados,
          cancelado: cancelado || canceladoPorUsuario.current,
        });
      }
    } finally {
      setLoading(false);
      setCurrentRequestId(null);
      setLoteActual(0);
      setLotesTotal(0);
    }
  }, [cantidadArchivos]);

  const cancelar = useCallback(async () => {
    canceladoPorUsuario.current = true;

    const token = localStorage.getItem('access_token');
    try {
      await fetch(`${import.meta.env.VITE_API_URL || '/api/v1'}/procesamiento/lote/cancelar`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    } catch {
      // ignorado
    }

    if (currentRequestId) {
      cancelRequest(currentRequestId);
    }
  }, [currentRequestId]);

  const limpiar = useCallback(() => {
    cargaGenRef.current += 1;
    fileListRef.current = null;
    fileHandlesRef.current = null;
    setCantidadArchivos(0);
    setPreviewNombres([]);
    setResultado(null);
    setError('');
    setProcesados(0);
    setCargandoArchivos(false);
  }, []);

  return (
    <LoteContext.Provider value={{
      cantidadArchivos,
      previewNombres,
      resultado,
      error,
      loading,
      cargandoArchivos,
      procesados,
      loteActual,
      lotesTotal,
      soportaCarpetaModerna: typeof window !== 'undefined' && 'showDirectoryPicker' in window,
      cargarCarpeta,
      seleccionarArchivos,
      procesar,
      cancelar,
      limpiar,
    }}>
      {children}
    </LoteContext.Provider>
  );
}

export function useLote() {
  return useContext(LoteContext);
}
