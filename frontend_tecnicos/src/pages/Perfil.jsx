import { useAuth } from '../hooks/useAuth';

export function Perfil() {
  const { user, logout } = useAuth();

  if (!user) return null;

  return (
    <div className="max-w-2xl">
      <div className="card p-8">
        <div className="flex items-center gap-6 mb-8">
          <div className="w-20 h-20 rounded-full bg-nacion text-white flex items-center justify-center text-3xl font-bold">
            {user.username[0]?.toUpperCase()}
          </div>
          <div>
            <h2 className="font-display text-2xl font-bold text-gray-800">{user.username}</h2>
            <p className="text-gray-500">{user.email}</p>
            <span className={`badge mt-2 ${
              user.rol === 'admin' ? 'bg-red-100 text-red-700' :
              user.rol === 'operador' ? 'bg-celeste-light text-celeste' :
              'bg-gray-100 text-gray-600'
            }`}>
              {user.rol}
            </span>
          </div>
        </div>

        <div className="space-y-4 border-t border-gray-100 pt-6">
          <div className="flex justify-between py-2">
            <span className="text-gray-500">Estado</span>
            <span className={`font-medium ${user.activo ? 'text-emerald-600' : 'text-red-600'}`}>
              {user.activo ? 'Activo' : 'Inactivo'}
            </span>
          </div>
          <div className="flex justify-between py-2">
            <span className="text-gray-500">Último login</span>
            <span className="font-medium text-gray-700">
              {user.ultimo_login ? new Date(user.ultimo_login).toLocaleString('es-AR') : 'Nunca'}
            </span>
          </div>
          <div className="flex justify-between py-2">
            <span className="text-gray-500">Miembro desde</span>
            <span className="font-medium text-gray-700">
              {new Date(user.created_at).toLocaleDateString('es-AR')}
            </span>
          </div>
        </div>

        <div className="mt-8 pt-6 border-t border-gray-100">
          <button onClick={logout} className="btn btn-danger">
            🚪 Cerrar sesión
          </button>
        </div>
      </div>
    </div>
  );
}
