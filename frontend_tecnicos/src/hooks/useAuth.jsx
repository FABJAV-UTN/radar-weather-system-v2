import { useState, useEffect, useCallback } from 'react';
import { api, logout } from '../services/api';

export function useAuth() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    const token = localStorage.getItem('access_token');
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const data = await api.me();
      setUser(data);
    } catch (err) {
      // Si el backend aún arranca (proxy 500), reintentar una vez antes de cerrar sesión
      if (err?.status >= 500) {
        await new Promise((r) => setTimeout(r, 2500));
        try {
          const data = await api.me();
          setUser(data);
          return;
        } catch {
          // cae al logout
        }
      }
      logout();
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = async (username, password) => {
    const data = await api.login(username, password);
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    localStorage.setItem('username', username);
    await checkAuth();
    return data;
  };

  const doLogout = () => {
    logout();
    setUser(null);
    window.location.href = '/login';
  };

  return { user, loading, login, logout: doLogout, isAdmin: user?.rol === 'admin' };
}
