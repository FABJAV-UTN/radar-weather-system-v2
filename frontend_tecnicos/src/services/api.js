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

export const api = {
  // Auth
  login: (username, password) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),

  me: () => request('/auth/me'),

  // Imágenes
  listarImagenes: (params = {}) => {
    const query = new URLSearchParams();
    if (params.estado) query.append('estado', params.estado);
    if (params.origen) query.append('origen', params.origen);
    if (params.limit) query.append('limit', params.limit);
    if (params.offset !== undefined) query.append('offset', params.offset);
    return request(`/imagenes?${query.toString()}`);
  },

  obtenerImagen: (id) => request(`/imagenes/${id}`),

  // ✅ FIX: usa API_BASE relativa para que pase por el proxy de Vite/nginx
  descargarGeotiff: async (id, filename) => {
    const token = localStorage.getItem('access_token');
    const response = await fetch(`${API_BASE}/imagenes/${id}/geotiff`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new ApiError(data.detail || `Error ${response.status}`, response.status);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || `radar_${id}.tif`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
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
    const { id, signal, abort } = createController();
    const promise = request('/procesamiento/local', {
      method: 'POST',
      body: JSON.stringify({ file_path: filePath }),
    }, signal);
    promise._cancel = abort;
    promise._id = id;
    return promise;
  },

  procesarCarpeta: (folderPath) => {
    const { id, signal, abort } = createController();
    const promise = request('/procesamiento/carpeta', {
      method: 'POST',
      body: JSON.stringify({ folder_path: folderPath }),
    }, signal);
    promise._cancel = abort;
    promise._id = id;
    return promise;
  },

  // Procesamiento lote via upload
  procesarUploadLote: (archivos) => {
    const { id, signal, abort } = createController();
    const formData = new FormData();
    for (const archivo of archivos) {
      formData.append('archivos', archivo);
    }
    const promise = request('/procesamiento/upload-lote', {
      method: 'POST',
      body: formData,
    }, signal);
    promise._cancel = abort;
    promise._id = id;
    return promise;
  },

  cancelarLote: () =>
    request('/procesamiento/lote/cancelar', { method: 'POST' }),

  // Scheduler — procesamiento continuo
  schedulerStart: (url = null, intervalo_segundos = 120) =>
    request('/procesamiento/scheduler/start', {
      method: 'POST',
      body: JSON.stringify({ url, intervalo_segundos }),
    }),

  schedulerStop: () =>
    request('/procesamiento/scheduler/stop', { method: 'POST' }),

  schedulerEstado: () =>
    request('/procesamiento/scheduler/estado'),

  // Métricas
  obtenerMetricas: (imagenId) => request(`/procesamiento/${imagenId}/metricas`),
  obtenerPasos: (imagenId) => request(`/procesamiento/${imagenId}/pasos`),

  // Admin
  listarUsuarios: () => request('/admin/usuarios'),
  crearUsuario: (data) => request('/admin/usuarios', { method: 'POST', body: JSON.stringify(data) }),
  cambiarEstado: (id, activo) => request(`/admin/usuarios/${id}/estado`, {
    method: 'PATCH',
    body: JSON.stringify({ activo }),
  }),
};

export { ApiError };
