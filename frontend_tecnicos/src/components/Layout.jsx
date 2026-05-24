import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export function Layout({ children }) {
  const { user, logout, isAdmin } = useAuth();
  const location = useLocation();

  const navItems = [
    { to: '/imagenes', label: 'Imágenes', icon: '📡' },
    { to: '/procesamiento', label: 'Procesar', icon: '⚙️' },
    { to: '/procesamiento-lote', label: 'Lote', icon: '📁' },
    ...(isAdmin ? [{ to: '/configuracion', label: 'Config', icon: '🔧' }] : []),
  ];

  return (
    <div className="min-h-screen bg-[#f5f7fa] flex">
      {/* Sidebar */}
      <aside className="w-64 bg-nacion text-white flex flex-col shadow-xl">
        <div className="p-6 border-b border-white/10">
          <h1 className="font-display text-2xl font-bold tracking-tight">
            RADAR DACC
          </h1>
          <p className="text-xs text-white/60 mt-1 font-body">Sistema Meteorológico</p>
        </div>

        <nav className="flex-1 p-4 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all ${
                  isActive
                    ? 'bg-celeste text-white shadow-md'
                    : 'text-white/70 hover:bg-white/10 hover:text-white'
                }`
              }
            >
              <span className="text-lg">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-white/10">
          <div className="flex items-center gap-3 px-4 py-3">
            <div className="w-8 h-8 rounded-full bg-celeste flex items-center justify-center text-sm font-bold">
              {user?.username?.[0]?.toUpperCase() || '?'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{user?.username}</p>
              <p className="text-xs text-white/50 capitalize">{user?.rol}</p>
            </div>
          </div>
          <button
            onClick={logout}
            className="w-full mt-2 px-4 py-2 text-sm text-white/70 hover:text-white hover:bg-white/10 rounded-lg transition-all text-left flex items-center gap-2"
          >
            <span>🚪</span> Cerrar sesión
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Header móvil / breadcrumb */}
        <header className="bg-white border-b border-gray-200 px-8 py-4 flex items-center justify-between">
          <div>
            <h2 className="font-display text-xl font-bold text-gray-800">
              {navItems.find(n => n.to === location.pathname)?.label || 'Dashboard'}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <span className="badge bg-emerald-100 text-emerald-700">
              ● Online
            </span>
          </div>
        </header>

        <div className="flex-1 p-8 overflow-auto">
          {children}
        </div>
      </main>
    </div>
  );
}
