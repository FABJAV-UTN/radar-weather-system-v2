const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api/v1';

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function request(endpoint, options = {}) {
  const token = localStorage.getItem('access_token');

  // Detectar si el body es FormData (multipart) — en ese caso NO ponemos Content-Type
  const isFormData = options.body instanceof FormData;

  const config = {
    ...options,
    headers: {
      // Solo Content-Type: application/json si NO es FormData
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  };

  const response = await fetch(`${API_BASE}${endpoint}`, config);

  if (response.status === 401) {
    // Token expirado, intentar refresh
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return request(endpoint, options);
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

export const api = {
  // Auth
  login: (username, password) =>
    request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

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

  descargarGeotiff: async (id, filename) => {
    const token = localStorage.getItem('access_token');
    const response = await fetch(`${API_BASE}/imagenes/${id}/geotiff`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new ApiError('Error al descargar', response.status);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || `radar_${id}.tif`;
    a.click();
    URL.revokeObjectURL(url);
  },

  // Procesamiento
  procesarUrl: (url) =>
    request('/procesamiento/url', {
      method: 'POST',
      body: JSON.stringify({ url: url || null }),
    }),

  procesarLocal: (filePath) =>
    request('/procesamiento/local', {
      method: 'POST',
      body: JSON.stringify({ file_path: filePath }),
    }),

  // ── NUEVO: Lote via upload (sin rutas de filesystem) ──
  procesarLoteUpload: (files) => {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));

    return request('/procesamiento/lote-upload', {
      method: 'POST',
      body: formData,
      // No hace falta headers: {} — request() detecta FormData automáticamente
    });
  },

  // Loop
  iniciarLoop: (intervalo, url) =>
    request('/procesamiento/url/loop/iniciar', {
      method: 'POST',
      body: JSON.stringify({ intervalo_minutos: intervalo, url: url || null }),
    }),

  detenerLoop: () =>
    request('/procesamiento/url/loop/detener', { method: 'POST' }),

  estadoLoop: () => request('/procesamiento/url/loop/estado'),

  // Métricas
  obtenerMetricas: (imagenId) => request(`/procesamiento/${imagenId}/metricas`),
  obtenerPasos: (imagenId) => request(`/procesamiento/${imagenId}/pasos`),
};

export { ApiError };