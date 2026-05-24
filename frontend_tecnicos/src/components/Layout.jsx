import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { Radar, LogOut, Images, Settings, User, PlayCircle } from 'lucide-react';
import { useAuth } from '../hooks/useAuth.jsx';

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate('/login');
  }

  const navItems = [
    { to: '/', label: 'Imágenes', icon: Images },
    { to: '/procesamiento', label: 'Procesamiento', icon: PlayCircle },
    { to: '/perfil', label: 'Perfil', icon: User },
    { to: '/configuracion', label: 'Configuración', icon: Settings },
  ];

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-50 h-16 flex items-center justify-between px-6 sm:px-8"
        style={{
          background: 'linear-gradient(135deg, #003366 0%, #004a99 100%)',
          borderBottom: '3px solid #0099dd',
          boxShadow: '0 10px 30px rgba(0,51,102,0.12)'
        }}>
        <div className="flex items-center gap-3.5">
          <div className="w-9 h-9 rounded-full bg-celeste flex items-center justify-center flex-shrink-0">
            <Radar className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="font-display text-lg font-bold text-white uppercase tracking-wide">
              Sistema Radar DACC
            </h1>
            <p className="text-white/60 text-[11px] font-normal tracking-wide">
              Provincia de Mendoza — Procesamiento Meteorológico
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="hidden sm:inline text-white/80 text-sm font-medium">
            👤 {user?.username || user?.email || 'Usuario'}
          </span>
          <button
            onClick={handleLogout}
            className="flex items-center gap-2 px-4 py-1.5 rounded-md text-white text-xs font-medium border border-white/20 bg-white/10 hover:bg-white/20 transition-all"
          >
            <LogOut className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Cerrar sesión</span>
          </button>
        </div>
      </header>

      {/* Nav */}
      <nav className="bg-white border-b border-gray-200 px-6 sm:px-8 flex gap-0.5 shadow-sm overflow-x-auto">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-2 px-5 py-3.5 text-sm font-medium whitespace-nowrap border-b-[3px] transition-all ${
                isActive
                  ? 'text-nacion border-celeste bg-celeste-light/50'
                  : 'text-gray-500 border-transparent hover:text-celeste hover:bg-celeste-light/30'
              }`
            }
          >
            <Icon className="w-4 h-4" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Main */}
      <main className="flex-1 p-6 sm:p-8 max-w-[1440px] mx-auto w-full">
        <Outlet />
      </main>
    </div>
  );
}
