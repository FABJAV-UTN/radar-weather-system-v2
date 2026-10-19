const API_BASE = import.meta.env.VITE_API_URL || '/api/v1';

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

// ── AbortControllers activos ────────────────────────────────────────────────
const activeControllers = new Map();
let controllerId = 0;

function makeRequest(endpoint, options = {}, signal = null) {
  const token = localStorage.getItem('access_token');
  const isFormData = options.body instanceof FormData;

  const config = {
    ...options,
    signal,
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  };

  return fetch(`${API_BASE}${endpoint}`, config);
}

async function request(endpoint, options = {}, signal = null) {
  let response = await makeRequest(endpoint, options, signal);

  if (response.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      response = await makeRequest(endpoint, options, signal);
    } else {
      logout();
      window.location.href = '/login';
      throw new ApiError('Sesión expirada', 401);
    }
  }

  const data = response.headers.get('content-type')?.includes('application/json')
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    throw new ApiError(
      data.detail || data.message || `Error ${response.status}`,
      response.status,
      data
    );
  }

  return data;
}

/**
 * Pedido autenticado que devuelve la Response cruda (binarios: PNG, ZIP).
 * Renueva el token una vez si vence, igual que request().
 */
async function requestBinario(endpoint, signal = null) {
  const pedir = () => {
    const token = localStorage.getItem('access_token');
    return fetch(`${API_BASE}${endpoint}`, {
      signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  };

  let response = await pedir();
  if (response.status === 401 && await refreshAccessToken()) {
    response = await pedir();
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(data.detail || `Error ${response.status}`, response.status, data);
  }
  return response;
}

function nombreDesdeDisposition(response, porDefecto) {
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="([^"]+)"/);
  return match ? match[1] : porDefecto;
}

function guardarBlob(blob, nombre) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = nombre;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * PNG en gris del backend → valores dBZ (un byte por píxel).
 * colorSpaceConversion 'none' evita que el navegador ajuste los grises:
 * cada valor tiene que llegar exacto porque ES el dBZ.
 */
async function pngADbz(blob) {
  const bitmap = await createImageBitmap(blob, {
    colorSpaceConversion: 'none',
    premultiplyAlpha: 'none',
  });
  const canvas = document.createElement('canvas');
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  const rgba = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  const valores = new Uint8Array(canvas.width * canvas.height);
  for (let i = 0; i < valores.length; i++) valores[i] = rgba[i * 4];
  return { ancho: canvas.width, alto: canvas.height, valores };
}

async function refreshAccessToken() {
  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) return false;

  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (response.ok) {
      const data = await response.json();
      localStorage.setItem('access_token', data.access_token);
      return true;
    }
  } catch {
    // fall silently
  }
  return false;
}

export function logout() {
  const token = localStorage.getItem('refresh_token');
  if (token) {
    fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify({ refresh_token: token }),
    }).catch(() => {});
  }
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('username');
}

// ── Cancelación ─────────────────────────────────────────────────────────────

export function cancelAllRequests() {
  activeControllers.forEach((ctrl) => ctrl.abort());
  activeControllers.clear();
}

export function cancelRequest(id) {
  const ctrl = activeControllers.get(id);
  if (ctrl) {
    ctrl.abort();
    activeControllers.delete(id);
  }
}

function createController() {
  const id = ++controllerId;
  const ctrl = new AbortController();
  activeControllers.set(id, ctrl);
  return {
    id, signal: ctrl.signal, abort: () => {
      ctrl.abort();
      activeControllers.delete(id);
    }
  };
}

// ── API Export ────────────────────────────────────────────────────────────

/** Archivos por request en upload-lote (carpetas grandes: 100k+ en el cliente, 1000 por subida). */
export const UPLOAD_LOTE_TAMANO = 1000;

export const api = {
  // Auth
  login: (username, password) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),

  me: () => request('/auth/me'),

  // Imágenes — sort_by y sort_dir se pasan al backend para ordenamiento server-side
  listarImagenes: (params = {}) => {
    const query = new URLSearchParams();
    if (params.estado)               query.append('estado',   params.estado);
    if (params.origen)               query.append('origen',   params.origen);
    if (params.limit)                query.append('limit',    params.limit);
    if (params.offset !== undefined) query.append('offset',   params.offset);
    if (params.sort_by)              query.append('sort_by',  params.sort_by);
    if (params.sort_dir)             query.append('sort_dir', params.sort_dir);
    return request(`/imagenes?${query.toString()}`);
  },

  obtenerImagen: (id) => request(`/imagenes/${id}`),

  // Carrusel: cuadros de un rango (fecha y hora locales 'AAAA-MM-DDTHH:MM')
  serieImagenes: (desde, hasta) =>
    request(`/imagenes/serie?${new URLSearchParams({ desde, hasta })}`),

  // Carrusel: valores dBZ de un cuadro → { ancho, alto, valores: Uint8Array, limites }
  // limites = [oeste, sur, este, norte] en grados (null si el TIF no está georreferenciado)
  obtenerVistaDbz: async (id, signal = null) => {
    const response = await requestBinario(`/imagenes/${id}/vista`, signal);
    const limites = response.headers.get('X-Limites')?.split(',').map(Number) ?? null;
    return { ...(await pngADbz(await response.blob())), limites };
  },

  // FIX: el filename se lee del header Content-Disposition que envía el backend,
  // que lo arma con strftime('%Y%m%d_%H%M%S') directo desde la DB → siempre 24h.
  // Ya no se recibe ni construye el filename en el frontend.
  descargarGeotiff: async (id) => {
    const response = await requestBinario(`/imagenes/${id}/geotiff`);
    guardarBlob(await response.blob(), nombreDesdeDisposition(response, `radar_${id}.tif`));
  },

  // Procesamiento único
  procesarUrl: (url) => {
    const { id, signal, abort } = createController();
    const promise = request('/procesamiento/url', {
      method: 'POST',
      body: JSON.stringify({ url: url || null }),
    }, signal);
    promise._cancel = abort;
    promise._id = id;
    return promise;
  },

  procesarLocal: (filePath) => {
    // Endpoint de procesamiento local individual deshabilitado intencionalmente.
    // Usar la funcionalidad de procesamiento por lote desde la sección "Lote".
    return Promise.reject(new ApiError('Procesamiento local individual deshabilitado. Usar Procesamiento por Lote.', 410));
  },

  procesarUploadUnico: (archivo) => {
    const { id, signal, abort } = createController();
    const formData = new FormData();
    formData.append('archivo', archivo);
    const promise = request('/procesamiento/upload', {
      method: 'POST',
      body: formData,
    }, signal);
    promise._cancel = abort;
    promise._id = id;
    return promise;
  },

  obtenerMetricas: (id) => request(`/procesamiento/${id}/metricas`),
  obtenerPasos: (id) => request(`/procesamiento/${id}/pasos`),

  iniciarLote: () =>
    request('/procesamiento/lote/iniciar', { method: 'POST' }),

  // Procesamiento lote (el frontend envía como máximo UPLOAD_LOTE_TAMANO archivos por request)
  procesarUploadLote: (archivos) => {
    const { id, signal, abort } = createController();
    const formData = new FormData();
    archivos.forEach((f) => formData.append('archivos', f));
    const promise = request('/procesamiento/upload-lote', {
      method: 'POST',
      body: formData,
    }, signal);
    promise._cancel = abort;
    promise._id = id;
    return promise;
  },

  // Scheduler
  iniciarScheduler: (intervalo, url) =>
    request('/procesamiento/scheduler/start', {
      method: 'POST',
      body: JSON.stringify({ intervalo_segundos: intervalo, url: url || null }),
    }),

  detenerScheduler: () =>
    request('/procesamiento/scheduler/stop', { method: 'POST' }),

  estadoScheduler: () => request('/procesamiento/scheduler/estado'),

  // Descarga lote ZIP — desde/hasta con fecha y hora ('AAAA-MM-DDTHH:MM').
  // Los GeoTIFF van completos (todos los niveles dBZ).
  descargarLote: async (desde, hasta) => {
    const response = await requestBinario(
      `/imagenes/descargar-lote?${new URLSearchParams({ desde, hasta })}`
    );
    const nombre = nombreDesdeDisposition(response, 'radar_lote.zip');
    guardarBlob(await response.blob(), nombre);
  },

  // Admin
  listarUsuarios: (params = {}) => {
    const query = new URLSearchParams();
    if (params.activo !== undefined) query.append('activo', params.activo);
    if (params.rol) query.append('rol', params.rol);
    return request(`/admin/usuarios?${query.toString()}`);
  },

  crearUsuario: (data) =>
    request('/admin/usuarios', { method: 'POST', body: JSON.stringify(data) }),

  cambiarRol: (id, rol) =>
    request(`/admin/usuarios/${id}/rol`, { method: 'PATCH', body: JSON.stringify({ rol }) }),

  cambiarEstado: (id, activo) =>
    request(`/admin/usuarios/${id}/estado`, { method: 'PATCH', body: JSON.stringify({ activo }) }),

  eliminarUsuario: (id) =>
    request(`/admin/usuarios/${id}`, { method: 'DELETE' }),

  listarIntentos: (limit = 20) =>
    request(`/admin/intentos-descarga?limit=${limit}`),
};