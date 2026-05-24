import { User, Lock, Bell, Shield } from 'lucide-react';

export default function Perfil() {
  return (
    <div className="max-w-3xl">
      <div className="card">
        <div className="px-6 py-4" style={{ background: 'linear-gradient(135deg, #003366, #004a99)' }}>
          <h2 className="font-display text-base font-bold text-white uppercase tracking-wide flex items-center gap-2">
            <User className="w-5 h-5" />
            Perfil de Usuario
          </h2>
        </div>
        <div className="p-8">
          <div className="text-center py-12">
            <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-celeste-light flex items-center justify-center">
              <User className="w-10 h-10 text-celeste" />
            </div>
            <h3 className="text-lg font-semibold text-gray-700 mb-2">
              Aquí podrá configurar su perfil de usuario
            </h3>
            <p className="text-gray-400 text-sm max-w-md mx-auto">
              Cambio de contraseña, datos personales y preferencias del sistema.
              <br />
              <span className="text-celeste font-medium">Funcionalidad disponible próximamente.</span>
            </p>
          </div>

          {/* Preview de secciones futuras */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-8">
            {[
              { icon: Lock, title: 'Contraseña', desc: 'Cambiar contraseña' },
              { icon: Bell, title: 'Notificaciones', desc: 'Alertas y avisos' },
              { icon: Shield, title: 'Seguridad', desc: 'Sesiones activas' },
            ].map(({ icon: Icon, title, desc }) => (
              <div key={title} className="p-4 border border-gray-200 rounded-lg bg-gray-50/50 opacity-60">
                <Icon className="w-6 h-6 text-gray-400 mb-2" />
                <h4 className="text-sm font-semibold text-gray-600">{title}</h4>
                <p className="text-xs text-gray-400 mt-1">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
