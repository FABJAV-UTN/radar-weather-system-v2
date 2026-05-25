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
          <h1 className="font-display text-2xl font-bold tracking-tight">RADAR DACC</h1>
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

      {/* Usuario + logout — siempre visible al fondo del sidebar */}
      <div className="p-4 border-t border-white/10 shrink-0">
        <div className="flex items-center gap-3 px-4 py-3">
          <div className="w-8 h-8 rounded-full bg-celeste flex items-center justify-center text-sm font-bold shrink-0">
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
    </>
  );

  return (
    <div className="h-screen bg-[#f5f7fa] flex overflow-hidden">

      {/* ── Overlay móvil ── */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-20 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ── Sidebar desktop (fijo) ── */}
      <aside className="hidden md:flex w-64 bg-nacion text-white flex-col shadow-xl shrink-0 h-full">
        <SidebarContent />
      </aside>

      {/* ── Sidebar móvil (drawer) ── */}
      <aside className={`
        fixed top-0 left-0 h-full w-72 bg-nacion text-white flex flex-col shadow-xl z-30
        transform transition-transform duration-300 ease-in-out md:hidden
        ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        <SidebarContent />
      </aside>

      {/* ── Main ── */}
      <main className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">

        {/* Header */}
        <header className="bg-white border-b border-gray-200 px-4 md:px-8 py-4 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            {/* Hamburguesa móvil */}
            <button
              onClick={() => setSidebarOpen(true)}
              className="md:hidden p-2 rounded-lg text-gray-500 hover:bg-gray-100 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <h2 className="font-display text-xl font-bold text-gray-800">{currentLabel}</h2>
          </div>
          <span className="badge bg-emerald-100 text-emerald-700">● Online</span>
        </header>

        {/* Contenido — scroll aquí, no en el sidebar */}
        <div className="flex-1 overflow-auto p-4 md:p-8">
          {children}
        </div>
      </main>
    </div>
  );
}
