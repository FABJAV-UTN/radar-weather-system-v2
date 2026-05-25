import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import { Layout } from './components/Layout';
import { Login } from './pages/Login';
import { Imagenes } from './pages/Imagenes';
import { Procesamiento } from './pages/Procesamiento';
import { ProcesamientoLote } from './pages/ProcesamientoLote';
import { Configuracion } from './pages/Configuracion';
import { Perfil } from './pages/Perfil';
import { LoteProvider } from './context/LoteContext';

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-gray-400">Cargando...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

export default function App() {
  return (
    <BrowserRouter>
      <LoteProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<ProtectedRoute><Imagenes /></ProtectedRoute>} />
          <Route path="/imagenes" element={<ProtectedRoute><Imagenes /></ProtectedRoute>} />
          <Route path="/procesamiento" element={<ProtectedRoute><Procesamiento /></ProtectedRoute>} />
          <Route path="/procesamiento-lote" element={<ProtectedRoute><ProcesamientoLote /></ProtectedRoute>} />
          <Route path="/configuracion" element={<ProtectedRoute><Configuracion /></ProtectedRoute>} />
          <Route path="/perfil" element={<ProtectedRoute><Perfil /></ProtectedRoute>} />
        </Routes>
      </LoteProvider>
    </BrowserRouter>
  );
}
