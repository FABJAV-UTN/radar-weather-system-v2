import { useState } from 'react';
import { Radar, AlertTriangle } from 'lucide-react';
import { useAuth } from '../hooks/useAuth.jsx';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await login(username, password);
    } catch (err) {
      setError(err.message || 'Credenciales inválidas');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden"
      style={{
        background: 'linear-gradient(160deg, #003366 0%, #004a99 50%, #0099dd 100%)'
      }}>
      {/* Patrón de fondo */}
      <div className="absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage: 'repeating-linear-gradient(45deg, #fff 0px, #fff 1px, transparent 1px, transparent 40px)'
        }} />

      <div className="relative z-10 w-full max-w-md mx-4 animate-slide-up">
        <div className="bg-white rounded-2xl shadow-2xl p-10 sm:p-12">
          {/* Logo */}
          <div className="text-center mb-8">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full flex items-center justify-center"
              style={{ background: 'linear-gradient(135deg, #003366, #0099dd)' }}>
              <Radar className="w-8 h-8 text-white" />
            </div>
            <h1 className="font-display text-3xl font-extrabold text-nacion uppercase tracking-wide">
              Sistema Radar
            </h1>
            <p className="text-celeste font-display text-lg font-semibold mt-1">DACC Mendoza</p>
            <p className="text-gray-400 text-sm mt-2">
              Dirección de Alerta, Contingencias y Cambio Climático
            </p>
          </div>

          <hr className="border-gray-200 mb-6" />

          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-md px-4 py-3 mb-4 text-sm text-red-600">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Usuario
              </label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="Ingresá tu usuario"
                autoFocus
                required
                className="form-input"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Contraseña
              </label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                className="form-input"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="btn btn-primary w-full justify-center mt-2"
            >
              {loading ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Ingresando...
                </>
              ) : (
                'Ingresar al sistema'
              )}
            </button>
          </form>

          <p className="text-center text-gray-400 text-xs mt-6">
            Sistema de procesamiento meteorológico v2
          </p>
        </div>
      </div>
    </div>
  );
}
