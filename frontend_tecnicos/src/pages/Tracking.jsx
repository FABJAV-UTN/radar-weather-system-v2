import { useState, useEffect, useCallback, useMemo } from 'react';
import { api } from '../services/api';

// ── Utilidades ──────────────────────────────────────────────────────────────

// Fechas en hora local (no usar toISOString: corre el día por la zona horaria)
function isoLocal(d) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function haceDias(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoLocal(d);
}
// "2025-01-06T15:04:00" → "06/01/2025" y "15:04" sin pasar por Date (evita corrimientos de zona)
const fFecha = (s) => (s ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : '—');
const fHora = (s) => (s ? s.slice(11, 16) : '—');
const fDia = (iso) => fFecha(iso + 'T');
const num = (v, d = 1) => (v == null ? '—' : Number(v).toFixed(d));

const RUMBOS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSO', 'SO', 'OSO', 'O', 'ONO', 'NO', 'NNO'];
const rumboTexto = (deg) => (deg == null ? '—' : RUMBOS[Math.round(deg / 22.5) % 16]);

// Mismos rangos que la página de Imágenes
const DBZ = [
  { min: 65, color: '#7c3aed', clase: 'bg-purple-100 text-purple-700', label: '≥ 65' },
  { min: 51, color: '#dc2626', clase: 'bg-red-100 text-red-700', label: '51–64' },
  { min: 35, color: '#ea580c', clase: 'bg-orange-100 text-orange-700', label: '35–50' },
  { min: 0, color: '#ca8a04', clase: 'bg-yellow-100 text-yellow-700', label: '< 35' },
];
const nivelDbz = (v) => DBZ.find((n) => (v ?? 0) >= n.min);

const ESTADO_BADGE = {
  activo: 'bg-celeste-light text-celeste',
  cerrado: 'bg-emerald-100 text-emerald-700',
  espurio: 'bg-gray-100 text-gray-500',
};

const SAN_RAFAEL = [-68.3301, -34.6177];

function Flecha({ deg }) {
  if (deg == null) return <span className="text-gray-300">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className="inline-block text-celeste font-bold" style={{ transform: `rotate(${deg}deg)` }}>↑</span>
      <span>{rumboTexto(deg)}</span>
      <span className="text-gray-400 text-xs">{Math.round(deg)}°</span>
    </span>
  );
}

// ── Mapa esquemático (SVG, lon/lat equirectangular) ─────────────────────────
// El mapa con fondo y capas (Leaflet) llega en F6; esto alcanza para ver las trayectorias.

function MapaTrayectorias({ tracks, seleccionado, onSeleccionar }) {
  const W = 760, H = 380, M = 34;
  const lineas = tracks.filter((t) => t.trayectoria?.coordinates?.length >= 2);

  const vista = useMemo(() => {
    const pts = lineas.flatMap((t) => t.trayectoria.coordinates).concat([SAN_RAFAEL]);
    let [x0, x1] = [Math.min(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[0]))];
    let [y0, y1] = [Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[1]))];
    const k = Math.cos((((y0 + y1) / 2) * Math.PI) / 180);        // 1° lon es más corto que 1° lat
    let w = (x1 - x0) * k, h = y1 - y0;
    const pad = Math.max(w, h, 0.2) * 0.12;
    x0 -= pad / k; x1 += pad / k; y0 -= pad; y1 += pad;
    w = (x1 - x0) * k; h = y1 - y0;
    const esc = Math.min((W - 2 * M) / w, (H - 2 * M) / h);
    const ox = (W - w * esc) / 2, oy = (H - h * esc) / 2;
    const P = ([lon, lat]) => [ox + (lon - x0) * k * esc, oy + (y1 - lat) * esc];
    const paso = h > 1.5 ? 0.5 : h > 0.6 ? 0.25 : 0.1;
    const grilla = (a, b) => {
      const out = [];
      for (let v = Math.ceil(a / paso) * paso; v <= b; v += paso) out.push(+v.toFixed(2));
      return out;
    };
    const kmPx = esc / 111.32;                                    // px por km
    // extensión realmente visible (el encuadre se centra y sobra lugar a los costados)
    const vLon0 = x0 - ox / (k * esc), vLon1 = x0 + (W - ox) / (k * esc);
    const vLat1 = y1 + oy / esc, vLat0 = y1 - (H - oy) / esc;
    return { P, lons: grilla(vLon0, vLon1), lats: grilla(vLat0, vLat1), y1: vLat1, x0: vLon0, kmPx };
  }, [lineas]);

  const { P } = vista;
  const barraKm = [5, 10, 20, 50].find((km) => km * vista.kmPx > 60) || 50;
  const [sx, sy] = P(SAN_RAFAEL);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto bg-slate-50 rounded-lg">
      <defs>
        {DBZ.map((n, i) => (
          <marker key={i} id={`fl-${i}`} viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill={n.color} />
          </marker>
        ))}
      </defs>
      {/* grilla */}
      {vista.lons.map((lon) => {
        const [x] = P([lon, vista.y1]);
        return (
          <g key={`x${lon}`}>
            <line x1={x} x2={x} y1={0} y2={H} stroke="#e2e8f0" />
            <text x={x + 3} y={H - 6} fontSize="10" fill="#94a3b8">{lon.toFixed(2)}°</text>
          </g>
        );
      })}
      {vista.lats.map((lat) => {
        const [, y] = P([vista.x0, lat]);
        return (
          <g key={`y${lat}`}>
            <line x1={0} x2={W} y1={y} y2={y} stroke="#e2e8f0" />
            <text x={4} y={y - 3} fontSize="10" fill="#94a3b8">{lat.toFixed(2)}°</text>
          </g>
        );
      })}
      {/* San Rafael */}
      <g>
        <rect x={sx - 4} y={sy - 4} width="8" height="8" fill="#003366" transform={`rotate(45 ${sx} ${sy})`} />
        <text x={sx + 9} y={sy + 4} fontSize="11" fontWeight="600" fill="#003366">San Rafael</text>
      </g>
      {/* trayectorias */}
      {lineas.map((t) => {
        const i = DBZ.indexOf(nivelDbz(t.dbz_max));
        const pts = t.trayectoria.coordinates.map(P);
        const sel = seleccionado === t.id;
        const atenuado = seleccionado != null && !sel;
        const [x0, y0] = pts[0];
        const [xn, yn] = pts[pts.length - 1];
        return (
          <g key={t.id} onClick={() => onSeleccionar(t.id)} className="cursor-pointer" opacity={atenuado ? 0.3 : 1}>
            <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke="transparent" strokeWidth="14" />
            <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke={DBZ[i].color}
              strokeWidth={sel ? 4 : 2.5} strokeLinejoin="round" strokeLinecap="round" markerEnd={`url(#fl-${i})`} />
            {pts.map(([x, y], k) => <circle key={k} cx={x} cy={y} r={sel ? 2.6 : 1.6} fill={DBZ[i].color} />)}
            <circle cx={x0} cy={y0} r="4.5" fill="#fff" stroke={DBZ[i].color} strokeWidth="2" />
            <text x={xn + 8} y={yn - 6} fontSize="11" fontWeight={sel ? 700 : 600} fill="#334155">{t.codigo.slice(-3)}</text>
          </g>
        );
      })}
      {/* escala y norte */}
      <g transform={`translate(${W - 24 - barraKm * vista.kmPx}, ${H - 26})`}>
        <rect width={barraKm * vista.kmPx} height="4" fill="#475569" />
        <text x={(barraKm * vista.kmPx) / 2} y="-4" fontSize="10" fill="#475569" textAnchor="middle">{barraKm} km</text>
      </g>
      <g transform={`translate(${W - 26}, 26)`}>
        <path d="M0,-12 L6,6 L0,2 L-6,6 z" fill="#475569" />
        <text y="20" fontSize="10" fill="#475569" textAnchor="middle">N</text>
      </g>
    </svg>
  );
}

// ── Página ──────────────────────────────────────────────────────────────────

export function Tracking() {
  const [desde, setDesde] = useState(() => haceDias(7));
  const [hasta, setHasta] = useState(() => haceDias(0));
  const [datos, setDatos] = useState(null);         // respuesta de /tormentas/tracks
  const [buscado, setBuscado] = useState(null);     // rango de la última búsqueda
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');
  const [selId, setSelId] = useState(null);
  const [detalle, setDetalle] = useState(null);
  const [cargandoDetalle, setCargandoDetalle] = useState(false);

  const rangoInvalido = !desde || !hasta || hasta < desde;

  const buscar = useCallback(async (d = desde, h = hasta) => {
    if (!d || !h || h < d) return;
    setCargando(true);
    setError('');
    setSelId(null);
    setDetalle(null);
    try {
      const r = await api.listarTracks({ desde: d, hasta: h });
      setDatos(r);
      setBuscado({ desde: d, hasta: h });
    } catch (err) {
      setDatos(null);
      setBuscado({ desde: d, hasta: h });
      setError(
        err?.status === 503 ? err.message
          : err?.status === 422 ? `Rango inválido: ${err.message}`
            : 'No se pudo consultar el tracking. ¿Está levantado el backend?'
      );
    } finally {
      setCargando(false);
    }
  }, [desde, hasta]);

  useEffect(() => { buscar(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const rapido = (dias) => {
    const d = haceDias(dias), h = haceDias(0);
    setDesde(d); setHasta(h); buscar(d, h);
  };

  const seleccionar = async (id) => {
    if (id === selId) { setSelId(null); setDetalle(null); return; }
    setSelId(id);
    setCargandoDetalle(true);
    try {
      setDetalle(await api.obtenerTrack(id));
    } catch {
      setDetalle(null);
    } finally {
      setCargandoDetalle(false);
    }
  };

  const tracks = datos?.items ?? [];
  const resumen = useMemo(() => {
    if (!tracks.length) return null;
    const vels = tracks.map((t) => t.vel_media_kmh).filter((v) => v != null);
    return {
      n: tracks.length,
      km: tracks.reduce((a, t) => a + (t.distancia_total_km || 0), 0),
      vel: vels.length ? vels.reduce((a, b) => a + b, 0) / vels.length : null,
      dbz: Math.max(...tracks.map((t) => t.dbz_max ?? 0)),
      dur: Math.max(...tracks.map((t) => t.duracion_min ?? 0)),
    };
  }, [tracks]);

  return (
    <div className="space-y-4">
      {/* ── Filtro ── */}
      <div className="card p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Desde</label>
            <input type="date" className="form-input" value={desde} max={hasta}
              onChange={(e) => setDesde(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Hasta</label>
            <input type="date" className="form-input" value={hasta} min={desde}
              onChange={(e) => setHasta(e.target.value)} />
          </div>
          <button onClick={() => buscar()} disabled={cargando || rangoInvalido} className="btn btn-primary">
            {cargando ? '⏳ Buscando…' : '🌀 Buscar tracking'}
          </button>
          <div className="flex gap-1.5 flex-wrap">
            {[['Hoy', 0], ['7 días', 7], ['30 días', 30]].map(([t, n]) => (
              <button key={t} onClick={() => rapido(n)} disabled={cargando}
                className="px-2.5 py-1 rounded text-xs font-medium border border-gray-200 hover:border-celeste hover:text-celeste transition-colors">
                {t}
              </button>
            ))}
          </div>
          {buscado && !error && (
            <span className="text-xs text-gray-400 ml-auto">
              {datos?.total ?? 0} track{(datos?.total ?? 0) !== 1 ? 's' : ''} · {fDia(buscado.desde)} – {fDia(buscado.hasta)}
            </span>
          )}
        </div>
        {rangoInvalido && <p className="text-xs text-red-600 mt-2">⚠️ La fecha "hasta" no puede ser anterior a "desde".</p>}
      </div>

      {/* ── Estados ── */}
      {cargando ? (
        <div className="card p-12 text-center text-gray-400">
          <span className="text-3xl animate-pulse">⏳</span>
          <p className="mt-2">Buscando tormentas…</p>
        </div>
      ) : error ? (
        <div className="card p-10 text-center">
          <span className="text-4xl">⚠️</span>
          <p className="mt-2 text-gray-700 font-medium">{error}</p>
        </div>
      ) : buscado && tracks.length === 0 ? (
        <div className="card p-12 text-center text-gray-500">
          <span className="text-4xl">📭</span>
          <p className="mt-3 font-medium text-gray-700">
            No hay tracks de tormentas entre el {fDia(buscado.desde)} y el {fDia(buscado.hasta)}.
          </p>
          {datos?.total_en_base === 0 ? (
            <p className="mt-2 text-sm text-gray-400 max-w-lg mx-auto">
              Todavía no se calculó ningún tracking. Se va a generar con el detector y el tracker (F2–F3).
            </p>
          ) : (
            <p className="mt-2 text-sm text-gray-400">Probá con otro rango de fechas.</p>
          )}
        </div>
      ) : resumen && (
        <>
          {/* ── Resumen ── */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {[
              ['Tracks', resumen.n, ''],
              ['Recorrido total', num(resumen.km), 'km'],
              ['Velocidad media', num(resumen.vel), 'km/h'],
              ['Duración máx.', Math.round(resumen.dur), 'min'],
              ['dBZ máx.', resumen.dbz, 'dBZ'],
            ].map(([t, v, u]) => (
              <div key={t} className="card p-4">
                <p className="text-xs text-gray-500">{t}</p>
                <p className="font-display text-2xl font-bold text-nacion mt-0.5">
                  {v} <span className="text-sm font-body font-medium text-gray-400">{u}</span>
                </p>
              </div>
            ))}
          </div>

          {/* ── Mapa ── */}
          <div className="card p-4">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <p className="text-sm font-semibold text-gray-700">Trayectorias</p>
              <div className="flex flex-wrap gap-3 text-xs text-gray-500">
                {DBZ.slice(0, 3).map((n) => (
                  <span key={n.label} className="inline-flex items-center gap-1.5">
                    <span className="w-4 h-1 rounded" style={{ background: n.color }} /> {n.label} dBZ
                  </span>
                ))}
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full border-2 border-gray-400 bg-white" /> inicio
                </span>
              </div>
            </div>
            <MapaTrayectorias tracks={tracks} seleccionado={selId} onSeleccionar={seleccionar} />
            <p className="text-xs text-gray-400 mt-2">Tocá una trayectoria o una fila para ver el detalle. Esquema en lon/lat; el mapa con fondo llega en F6.</p>
          </div>

          {/* ── Tabla de tracks ── */}
          <div className="card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr className="text-left text-gray-600">
                    {['Código', 'Inicio', 'Fin', 'Duración', 'Celdas', 'Recorrido', 'Vel. media', 'Dirección', 'dBZ máx.', 'Estado'].map((h) => (
                      <th key={h} className="px-3 md:px-4 py-3 font-semibold whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {tracks.map((t) => {
                    const n = nivelDbz(t.dbz_max);
                    return (
                      <tr key={t.id} onClick={() => seleccionar(t.id)}
                        className={`cursor-pointer transition-colors ${selId === t.id ? 'bg-celeste-light' : 'hover:bg-gray-50/70'}`}>
                        <td className="px-3 md:px-4 py-3 font-mono text-xs text-nacion font-semibold whitespace-nowrap">{t.codigo}</td>
                        <td className="px-3 md:px-4 py-3 whitespace-nowrap">
                          <div className="text-gray-800">{fHora(t.inicio)}</div>
                          <div className="text-gray-400 text-xs">{fFecha(t.inicio)}</div>
                        </td>
                        <td className="px-3 md:px-4 py-3 whitespace-nowrap text-gray-800">{fHora(t.fin)}</td>
                        <td className="px-3 md:px-4 py-3 whitespace-nowrap">{Math.round(t.duracion_min ?? 0)} min</td>
                        <td className="px-3 md:px-4 py-3">{t.n_celdas}</td>
                        <td className="px-3 md:px-4 py-3 whitespace-nowrap">{num(t.distancia_total_km)} km</td>
                        <td className="px-3 md:px-4 py-3 whitespace-nowrap">{num(t.vel_media_kmh)} km/h</td>
                        <td className="px-3 md:px-4 py-3"><Flecha deg={t.direccion_media_deg} /></td>
                        <td className="px-3 md:px-4 py-3"><span className={`badge ${n.clase}`}>{t.dbz_max ?? '—'}</span></td>
                        <td className="px-3 md:px-4 py-3"><span className={`badge ${ESTADO_BADGE[t.estado] || ''}`}>{t.estado}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* ── Detalle ── */}
          {selId && (
            <div className="card p-4 animate-slide-up">
              {cargandoDetalle ? (
                <p className="text-sm text-gray-400">⏳ Cargando detalle…</p>
              ) : !detalle ? (
                <p className="text-sm text-red-600">⚠️ No se pudo cargar el detalle del track.</p>
              ) : (
                <>
                  <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
                    <p className="font-display text-xl font-bold text-nacion">{detalle.codigo}</p>
                    <p className="text-xs text-gray-500">
                      {fFecha(detalle.inicio)} · {fHora(detalle.inicio)}–{fHora(detalle.fin)} ·
                      desplazamiento neto {num(detalle.desplazamiento_neto_km)} km ·
                      vel. máx. {num(detalle.vel_max_kmh)} km/h · área máx. {num(detalle.area_max_km2)} km²
                    </p>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50 border-b border-gray-200 text-gray-600">
                        <tr className="text-left">
                          {['Hora', 'Lat', 'Lon', 'Área km²', 'Núcleo km²', 'dBZ máx/med', 'Paso m', 'km/h', 'Rumbo', ''].map((h) => (
                            <th key={h} className="px-3 py-2 font-semibold whitespace-nowrap">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {detalle.celdas.map((c) => (
                          <tr key={c.id}>
                            <td className="px-3 py-1.5 font-medium">{fHora(c.fecha_hora)}</td>
                            <td className="px-3 py-1.5 font-mono">{num(c.lat, 4)}</td>
                            <td className="px-3 py-1.5 font-mono">{num(c.lon, 4)}</td>
                            <td className="px-3 py-1.5">{num(c.area_km2)}</td>
                            <td className="px-3 py-1.5">{num(c.area_nucleo_km2)}</td>
                            <td className="px-3 py-1.5">{c.dbz_max} / {num(c.dbz_medio, 0)}</td>
                            <td className="px-3 py-1.5">{c.distancia_m == null ? '—' : Math.round(c.distancia_m)}</td>
                            <td className="px-3 py-1.5">{num(c.velocidad_kmh)}</td>
                            <td className="px-3 py-1.5"><Flecha deg={c.direccion_deg} /></td>
                            <td className="px-3 py-1.5">{c.geo_corregida && <span title="Imagen con salto de georreferenciación corregido (D13)">⚑</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
