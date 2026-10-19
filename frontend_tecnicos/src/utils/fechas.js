// Fechas para inputs datetime-local y para mostrar la fecha_hora del backend.
// La base guarda hora argentina sin zona: se trabaja siempre con la hora
// local "tal cual", sin pasar por UTC (toISOString correría 3 horas).

const dos = (n) => String(n).padStart(2, '0');

/** Date → 'AAAA-MM-DDTHH:MM' en hora local (formato de <input type="datetime-local">). */
export function aInputLocal(fecha) {
  return `${fecha.getFullYear()}-${dos(fecha.getMonth() + 1)}-${dos(fecha.getDate())}`
    + `T${dos(fecha.getHours())}:${dos(fecha.getMinutes())}`;
}

/** Valor para un input datetime-local de hace `horas` horas. */
export function haceHoras(horas) {
  return aInputLocal(new Date(Date.now() - horas * 3600 * 1000));
}

/** '2026-10-13T11:02:00' → '13/10/2026 11:02' (sin conversión de zona). */
export function mostrarFechaHora(isoSinZona) {
  const [fecha, hora = ''] = isoSinZona.split('T');
  const [a, m, d] = fecha.split('-');
  return `${d}/${m}/${a} ${hora.slice(0, 5)}`;
}
