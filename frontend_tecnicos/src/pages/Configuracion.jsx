import { useState, useEffect } from 'react';
import { api } from '../services/api';
import { useAuth } from '../hooks/useAuth';

export function Configuracion() {
  const { isAdmin } = useAuth();
  const [usuarios, setUsuarios] = useState([]);
  const [loading, setLoading] = useState(true);
  const [nuevoUsuario, setNuevoUsuario] = useState({ username: '', email: '', password: '', rol: 'visualizador' });
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    if (isAdmin) cargarUsuarios();
  }, [isAdmin]);

  const cargarUsuarios = async () => {
    setLoading(true);
    try {
      const data = await api.listarUsuarios();
      setUsuarios(data.items || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleCrear = async (e) => {
    e.preventDefault();
    try {
      await api.crearUsuario(nuevoUsuario);
      setNuevoUsuario({ username: '', email: '', password: '', rol: 'visualizador' });
      setShowForm(false);
      cargarUsuarios();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleToggleEstado = async (id, activo) => {
    try {
      await api.cambiarEstado(id, !activo);
      cargarUsuarios();
    } catch (err) {
      alert(err.message);
    }
  };

  if (!isAdmin) {
    return (
      <div className="card p-12 text-center">
        <span className="text-4xl">🔒</span>
        <h3 className="font-display text-xl font-bold text-gray-800 mt-4">Acceso restringido</h3>
        <p className="text-gray-500 mt-2">Solo administradores pueden acceder a esta sección.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg font-bold text-gray-800">Gestión de Usuarios</h3>
        <button
          onClick={() => setShowForm(!showForm)}
          className="btn btn-success"
        >
          {showForm ? '✕ Cancelar' : '➕ Nuevo Usuario'}
        </button>
      </div>

      {showForm && (
        <div className="card p-6 animate-slide-up">
          <h4 className="font-semibold text-gray-700 mb-4">Crear usuario</h4>
          <form onSubmit={handleCrear} className="grid grid-cols-2 gap-4">
            <input
              type="text"
              placeholder="Usuario"
              className="form-input"
              value={nuevoUsuario.username}
              onChange={(e) => setNuevoUsuario({ ...nuevoUsuario, username: e.target.value })}
              required
              minLength={3}
            />
            <input
              type="email"
              placeholder="Email"
              className="form-input"
              value={nuevoUsuario.email}
              onChange={(e) => setNuevoUsuario({ ...nuevoUsuario, email: e.target.value })}
              required
            />
            <input
              type="password"
              placeholder="Contraseña (mín. 8 caracteres)"
              className="form-input"
              value={nuevoUsuario.password}
              onChange={(e) => setNuevoUsuario({ ...nuevoUsuario, password: e.target.value })}
              required
              minLength={8}
            />
            <select
              className="form-select"
              value={nuevoUsuario.rol}
              onChange={(e) => setNuevoUsuario({ ...nuevoUsuario, rol: e.target.value })}
            >
              <option value="visualizador">Visualizador</option>
              <option value="operador">Operador</option>
              <option value="admin">Administrador</option>
            </select>
            <div className="col-span-2">
              <button type="submit" className="btn btn-primary">
                💾 Crear Usuario
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="card overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-gray-400">Cargando...</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-3 text-left">Usuario</th>
                <th className="px-6 py-3 text-left">Email</th>
                <th className="px-6 py-3 text-left">Rol</th>
                <th className="px-6 py-3 text-left">Estado</th>
                <th className="px-6 py-3 text-left">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {usuarios.map((u) => (
                <tr key={u.id} className="hover:bg-gray-50/50">
                  <td className="px-6 py-4 font-medium">{u.username}</td>
                  <td className="px-6 py-4 text-gray-500">{u.email}</td>
                  <td className="px-6 py-4">
                    <span className={`badge ${
                      u.rol === 'admin' ? 'bg-red-100 text-red-700' :
                      u.rol === 'operador' ? 'bg-celeste-light text-celeste' :
                      'bg-gray-100 text-gray-600'
                    }`}>
                      {u.rol}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`badge ${u.activo ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'}`}>
                      {u.activo ? 'Activo' : 'Inactivo'}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <button
                      onClick={() => handleToggleEstado(u.id, u.activo)}
                      className={`text-sm font-medium ${u.activo ? 'text-red-600 hover:text-red-700' : 'text-emerald-600 hover:text-emerald-700'}`}
                    >
                      {u.activo ? 'Desactivar' : 'Activar'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
