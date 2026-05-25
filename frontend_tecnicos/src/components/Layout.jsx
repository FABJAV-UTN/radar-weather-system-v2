import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export function Layout({ children }) {
  const { user, logout, isAdmin } = useAuth();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const navItems = [
    { to: '/imagenes', label: 'Imágenes', icon: '📡' },
    { to: '/procesamiento', label: 'Procesar', icon: '⚙️' },
    { to: '/procesamiento-lote', label: 'Lote', icon: '📁' },
    ...(isAdmin ? [{ to: '/configuracion', label: 'Config', icon: '🔧' }] : []),
  ];

  const currentLabel = navItems.find(n => n.to === location.pathname)?.label || 'Dashboard';

  const SidebarContent = () => (
    <>
      {/* Logo */}
      <div className="p-6 border-b border-white/10 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight">Procesamiento Radar</h1>
          <p className="text-xs text-white/60 mt-1 font-body">Sistema Meteorológico</p>
        </div>
        {/* Cerrar en móvil */}
        <button
          onClick={() => setSidebarOpen(false)}
          className="md:hidden text-white/60 hover:text-white text-xl p-1"
        >
          ✕
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={() => setSidebarOpen(false)}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all ${
                isActive
                  ? 'bg-white/15 text-white'
                  : 'text-white/70 hover:bg-white/10 hover:text-white'
              }`
            }
          >
            <span className="text-base">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      {/* User footer */}
      <div className="p-4 border-t border-white/10">
        <NavLink
          to="/perfil"
          onClick={() => setSidebarOpen(false)}
          className="flex items-center gap-3 px-4 py-2 rounded-lg text-white/70 hover:bg-white/10 hover:text-white transition-all text-sm"
        >
          <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center font-bold text-xs">
            {user?.username?.[0]?.toUpperCase()}
          </div>
          <div className="min-w-0">
            <p className="font-medium truncate">{user?.username}</p>
            <p className="text-xs text-white/40 truncate capitalize">{user?.rol}</p>
          </div>
        </NavLink>
        <button
          onClick={logout}
          className="mt-2 w-full flex items-center gap-2 px-4 py-2 rounded-lg text-white/50 hover:text-white/80 hover:bg-white/5 transition-all text-xs"
        >
          🚪 Cerrar sesión
        </button>
      </div>
    </>
  );

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Sidebar desktop */}
      <aside className="hidden md:flex flex-col w-64 bg-nacion text-white shrink-0">
        <SidebarContent />
      </aside>

      {/* Sidebar móvil */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div
            className="fixed inset-0 bg-black/50"
            onClick={() => setSidebarOpen(false)}
          />
          <aside className="relative flex flex-col w-64 bg-nacion text-white">
            <SidebarContent />
          </aside>
        </div>
      )}

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top bar */}
        <header className="bg-white border-b border-gray-200 px-4 md:px-6 py-3 flex items-center gap-4 shrink-0">
          <button
            onClick={() => setSidebarOpen(true)}
            className="md:hidden text-gray-500 hover:text-gray-700 text-xl"
          >
            ☰
          </button>
          <h2 className="font-display text-lg font-bold text-gray-800">{currentLabel}</h2>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-auto p-4 md:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
