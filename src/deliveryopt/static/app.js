'use strict';
/* Interface de l'optimiseur de livraisons. Toutes les données affichées passent par textContent
   (jamais innerHTML) : une adresse saisie ne peut pas injecter de code. */

const COLORS = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#E69F00', '#56B4E9', '#7A3E9D', '#333333', '#8C564B', '#2CA02C'];
const PARCEL_FIELDS = ['id_colis', 'adresse', 'latitude', 'longitude', 'heure_min', 'heure_max', 'heure_souhaitee', 'priorite', 'duree_remise_min', 'apres_colis', 'note'];
const LABELS = {
  depot_name: 'Nom du dépôt', depot_lat: 'Dépôt : latitude', depot_lon: 'Dépôt : longitude',
  cost_per_km_ar: 'Coût interne par km (Ar)', flat_price_ar: 'Tarif forfaitaire par adresse (Ar)',
  distant_price_per_km_ar: 'Adresse éloignée : prix par km (Ar)', distant_waiting_fee_ar: "Adresse éloignée : frais d'attente (Ar)",
  mean_leg_threshold_km: 'Seuil de distance moyenne entre arrêts (km)', max_leg_threshold_km: 'Seuil par trajet (km, vide = désactivé)',
  include_depot_leg_in_mean: 'Compter dépôt → 1er arrêt dans la moyenne', km_round_step: "Pas d'arrondi des km facturés", km_round_mode: "Mode d'arrondi (half_up ou ceil)",
  day_start: 'Heure de départ du dépôt (HH:MM)', day_end: 'Fin de journée (HH:MM)', max_drivers: 'Nombre maximum de livreurs',
  max_parcels_per_driver: 'Colis maximum par livreur', target_min_parcels: 'Cible minimale de colis par livreur', default_service_min: 'Durée de remise par défaut (min)',
  desired_tolerance_min: "Tolérance sur l'heure souhaitée (min)", duration_factor: 'Coefficient sur les durées de trajet (trafic)',
  driver_fixed_cost_ar: 'Coût fixe par livreur et par jour (Ar)', wait_cost_ar_per_min: "Coût d'attente (Ar/min)", desired_deviation_cost_ar_per_min: "Écart à l'heure souhaitée (Ar/min)",
  mean_excess_cost_ar_per_km: 'Pénalité au-delà de la moyenne de 3 km (Ar/km)', under_target_cost_ar_per_parcel: 'Pénalité sous la cible de colis (Ar/colis)',
  balance_cost_ar_per_min: "Pénalité d'écart entre tournées (Ar/min)", unassigned_penalty_ar: 'Pénalité par colis non attribué (Ar)',
  time_limit_s: 'Temps de calcul maximum (s)', restarts: 'Nombre de redémarrages', seed: 'Graine aléatoire',
};
const GROUP_TITLES = { pricing: 'Tarification et règles de distance', optimizer: 'Planification et poids de l\'objectif (valeurs provisoires)' };

const state = { me: null, parcels: [], settings: null, plan: null, planId: null, tab: 'colis', picking: null, openStop: null, selectedRow: null, date: new Date().toISOString().slice(0, 10), label: '', busy: false, geoChoices: {}, plans: [], users: [] };
let mapView = null;
let leafletReady = false;

/* ---------- utilitaires ---------- */
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  let value;
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value') value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected') el[k] = !!v;
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  if (value !== undefined) el.value = value ?? '';
  return el;
}
const fmtAr = (n) => new Intl.NumberFormat('fr-FR').format(Math.round(n ?? 0)).replace(/[  ]/g, ' ') + ' Ar';
const fmtKm = (n) => (n == null ? '—' : n.toFixed(1).replace('.', ',') + ' km');

function notify(message, kind) {
  const box = document.getElementById('toast');
  const item = h('div', { class: kind === 'error' ? 'error' : '' }, message);
  box.append(item);
  setTimeout(() => item.remove(), kind === 'error' ? 9000 : 3500);
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method, credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* corps non JSON (export CSV) */ }
  if (!res.ok) {
    if (res.status === 401 && path !== '/api/login') { state.me = null; render(); }
    const err = new Error((data && data.message) || `Erreur ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}
async function guarded(fn) {
  try { return await fn(); } catch (e) { notify(e.message, 'error'); return undefined; }
}

/* ---------- carte : Leaflet si disponible, sinon plan schématique SVG ---------- */
function loadScript(src, timeoutMs) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    const t = setTimeout(() => { s.remove(); reject(new Error('délai dépassé')); }, timeoutMs);
    s.src = src; s.onload = () => { clearTimeout(t); resolve(); }; s.onerror = () => { clearTimeout(t); reject(new Error('échec')); };
    document.head.append(s);
  });
}
async function loadLeaflet() {
  const sources = [['/static/vendor/leaflet.js', '/static/vendor/leaflet.css'], ['https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css']];
  for (const [js, css] of sources) {
    try {
      await loadScript(js, 4000);
      document.head.append(h('link', { rel: 'stylesheet', href: css }));
      if (window.L) { leafletReady = true; return; }
    } catch (e) { /* source suivante */ }
  }
}

function createMap(container) {
  const model = { markers: [], lines: [], clickCb: null };
  const api = leafletReady ? leafletMap(container, model) : svgMap(container, model);
  return {
    set(markers, lines) { model.markers = markers; model.lines = lines; api.draw(); },
    onClick(cb) { model.clickCb = cb; },
    kind: leafletReady ? 'leaflet' : 'svg',
  };
}

function leafletMap(container, model) {
  // Bandeau d'attribution sans le préfixe « drapeau + Leaflet » ; le crédit OpenStreetMap (obligatoire) reste affiché.
  const map = L.map(container, { attributionControl: false }).setView([-18.91, 47.525], 12);
  L.control.attribution({ prefix: false }).addTo(map);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© contributeurs OpenStreetMap', referrerPolicy: 'strict-origin-when-cross-origin' }).addTo(map);
  const layer = L.layerGroup().addTo(map);
  map.on('click', (e) => model.clickCb && model.clickCb(e.latlng.lat, e.latlng.lng));
  let fitted = false;
  return {
    draw() {
      layer.clearLayers();
      const pts = [];
      for (const l of model.lines) L.polyline(l.points, { color: l.color, weight: 4, opacity: 0.8 }).addTo(layer);
      for (const m of model.markers) {
        pts.push([m.lat, m.lon]);
        const icon = L.divIcon({ className: '', html: `<div style="background:${m.color};color:#fff;border-radius:${m.square ? '4px' : '50%'};width:26px;height:26px;line-height:26px;text-align:center;font:600 12px system-ui;border:2px solid #fff;box-shadow:0 0 3px #0008">${Number.isFinite(m.label) ? m.label : ''}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] });
        const marker = L.marker([m.lat, m.lon], { icon }).addTo(layer);
        marker.bindTooltip(h('span', {}, m.title || ''));
        if (m.onclick) marker.on('click', (e) => { L.DomEvent.stopPropagation(e); m.onclick(); });
      }
      if (pts.length && !fitted) { map.fitBounds(pts, { padding: [30, 30], maxZoom: 15 }); fitted = true; }
    },
  };
}

function svgMap(container, model) {
  const W = 800, H = 520, NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Plan schématique des adresses (fond de carte indisponible)');
  container.append(svg);
  let bounds = null;
  const project = (lat, lon) => [40 + ((lon - bounds.minLon) / (bounds.maxLon - bounds.minLon)) * (W - 80), H - 40 - ((lat - bounds.minLat) / (bounds.maxLat - bounds.minLat)) * (H - 80)];
  const el = (name, attrs, text) => { const e = document.createElementNS(NS, name); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (text != null) e.textContent = text; return e; };
  svg.addEventListener('click', (ev) => {
    if (!model.clickCb || !bounds) return;
    const r = svg.getBoundingClientRect();
    const x = ((ev.clientX - r.left) / r.width) * W, y = ((ev.clientY - r.top) / r.height) * H;
    const lon = bounds.minLon + ((x - 40) / (W - 80)) * (bounds.maxLon - bounds.minLon);
    const lat = bounds.minLat + ((H - 40 - y) / (H - 80)) * (bounds.maxLat - bounds.minLat);
    model.clickCb(lat, lon);
  });
  return {
    draw() {
      while (svg.firstChild) svg.firstChild.remove();
      const lats = model.markers.map((m) => m.lat), lons = model.markers.map((m) => m.lon);
      if (!lats.length) { lats.push(-18.95, -18.87); lons.push(47.48, 47.57); }
      const padLat = Math.max((Math.max(...lats) - Math.min(...lats)) * 0.1, 0.01), padLon = Math.max((Math.max(...lons) - Math.min(...lons)) * 0.1, 0.01);
      bounds = { minLat: Math.min(...lats) - padLat, maxLat: Math.max(...lats) + padLat, minLon: Math.min(...lons) - padLon, maxLon: Math.max(...lons) + padLon };
      svg.append(el('rect', { x: 0, y: 0, width: W, height: H, fill: '#eef2f6' }));
      svg.append(el('text', { x: 12, y: H - 10, fill: '#667085', 'font-size': 12 }, 'Plan schématique (fond de carte indisponible). Nord en haut.'));
      for (const l of model.lines) svg.append(el('polyline', { points: l.points.map(([a, b]) => project(a, b).join(',')).join(' '), fill: 'none', stroke: l.color, 'stroke-width': 3, opacity: 0.8 }));
      for (const m of model.markers) {
        const [x, y] = project(m.lat, m.lon);
        const g = el('g', { class: 'marker', 'data-title': m.title || '' });
        g.style.cursor = 'pointer';
        g.append(m.square ? el('rect', { x: x - 11, y: y - 11, width: 22, height: 22, fill: m.color, stroke: '#fff', 'stroke-width': 2 }) : el('circle', { cx: x, cy: y, r: 12, fill: m.color, stroke: '#fff', 'stroke-width': 2 }));
        if (Number.isFinite(m.label)) g.append(el('text', { x, y: y + 4, 'text-anchor': 'middle', fill: '#fff', 'font-size': 11, 'font-weight': 700 }, String(m.label)));
        g.append(el('title', {}, m.title || ''));
        if (m.onclick) g.addEventListener('click', (ev) => { ev.stopPropagation(); m.onclick(); });
        svg.append(g);
      }
    },
  };
}

/* ---------- CSV ---------- */
function parseCSV(text) {
  text = text.replace(/^﻿/, '');
  const first = text.split(/\r?\n/, 1)[0] || '';
  const delim = (first.match(/;/g) || []).length >= (first.match(/,/g) || []).length ? ';' : ',';
  const rows = []; let row = [], cell = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') quoted = false; else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === delim) { row.push(cell); cell = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = ''; }
    else cell += c;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((x) => x.trim() !== ''));
}
const SYNONYMS = { id: 'id_colis', colis: 'id_colis', id_colis: 'id_colis', adresse: 'adresse', address: 'adresse', lat: 'latitude', latitude: 'latitude', lon: 'longitude', lng: 'longitude', longitude: 'longitude', heure_min: 'heure_min', heure_max: 'heure_max', heure_souhaitee: 'heure_souhaitee', priorite: 'priorite', duree_remise_min: 'duree_remise_min', duree: 'duree_remise_min', apres_colis: 'apres_colis', note: 'note' };
function csvToParcels(text) {
  const rows = parseCSV(text);
  if (rows.length < 2) throw new Error('Fichier vide ou sans ligne de données.');
  const norm = (s) => s.trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
  const keys = rows[0].map((c) => SYNONYMS[norm(c)] || null);
  if (!keys.includes('id_colis') || !keys.includes('adresse')) throw new Error('Colonnes obligatoires : id_colis et adresse.');
  return rows.slice(1).map((r) => { const p = blankParcel(); keys.forEach((k, i) => { if (k) p[k] = (r[i] || '').trim(); }); return p; });
}
const blankParcel = () => Object.fromEntries(PARCEL_FIELDS.map((f) => [f, f === 'priorite' ? 'normale' : '']));

/* ---------- vues ---------- */
function render() {
  const root = document.getElementById('app');
  root.replaceChildren();
  mapView = null;
  if (!state.me) { root.append(loginView()); return; }
  root.append(headerView(), h('main', {}, bannerEstimate(), tabBody()));
}

function loginView() {
  const user = h('input', { id: 'login-user', autocomplete: 'username', 'aria-label': 'Identifiant' });
  const pass = h('input', { id: 'login-pass', type: 'password', autocomplete: 'current-password', 'aria-label': 'Mot de passe' });
  const submit = async () => guarded(async () => {
    state.me = await api('POST', '/api/login', { username: user.value.trim(), password: pass.value });
    await bootstrap();
  });
  pass.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  return h('div', { class: 'login card' }, h('h1', {}, 'Optimisation des livraisons'), h('p', { class: 'muted' }, 'Connectez-vous pour continuer.'),
    h('label', { for: 'login-user' }, 'Identifiant'), user, h('label', { for: 'login-pass' }, 'Mot de passe'), pass,
    h('button', { id: 'login-btn', class: 'primary', onclick: submit }, 'Se connecter'));
}

function headerView() {
  const tabs = [['colis', 'Colis'], ['resultats', 'Résultats'], ['historique', 'Historique'], ['parametres', 'Paramètres'], ['compte', 'Compte']];
  return h('header', { class: 'top' }, h('h1', {}, 'Optimisation des livraisons'),
    h('nav', { class: 'tabs' }, tabs.map(([id, label]) => h('button', { 'data-tab': id, class: state.tab === id ? 'active' : '', onclick: () => { state.tab = id; render(); if (id === 'historique') loadHistory(); if (id === 'compte') loadUsers(); } }, label))),
    h('span', {}, h('span', { class: 'muted small' }, `${state.me.username} (${state.me.role}) `), h('button', { id: 'logout', onclick: () => guarded(async () => { await api('POST', '/api/logout', {}); state.me = null; render(); }) }, 'Déconnexion')));
}

function bannerEstimate() {
  if (state.me.billing_reliable) return null;
  return h('div', { class: 'banner critique', id: 'estimate-banner' }, 'MODE ESTIMATION : les distances sont calculées à vol d\'oiseau (× 1,4), pas sur les routes. Les résultats sont indicatifs et les tarifs ne doivent pas être facturés. Configurez OSRM pour des distances routières réelles.');
}

function tabBody() {
  switch (state.tab) {
    case 'resultats': return resultsView();
    case 'historique': return historyView();
    case 'parametres': return settingsView();
    case 'compte': return accountView();
    default: return parcelsView();
  }
}

/* --- colis --- */
function parcelsView() {
  const tbody = h('tbody');
  const info = h('div', { class: 'muted small', id: 'map-hint' });
  const container = h('div', { id: 'map' });
  const refreshMap = () => {
    if (!mapView) return;
    const s = state.settings;
    const markers = [];
    if (s) markers.push({ lat: s.depot_lat, lon: s.depot_lon, color: '#1d2433', square: true, title: `Dépôt : ${s.depot_name}` });
    state.parcels.forEach((p, i) => {
      const lat = parseFloat(String(p.latitude).replace(',', '.')), lon = parseFloat(String(p.longitude).replace(',', '.'));
      // Les points hors de Madagascar sont écartés par le serveur : on ne les trace pas, sinon ils déforment toute la carte.
      if (Number.isFinite(lat) && Number.isFinite(lon) && lat > -26 && lat < -11 && lon > 42 && lon < 51.5) markers.push({ lat, lon, color: i === state.selectedRow ? '#D55E00' : '#0b5cad', label: i + 1, title: `${p.id_colis} · ${p.adresse}`, onclick: () => { state.selectedRow = i; refreshRows(); refreshMap(); } });
    });
    mapView.set(markers, []);
    info.textContent = state.picking != null ? `Cliquez sur la carte pour placer le colis n° ${state.picking + 1}.` : 'Astuce : « Placer sur la carte » positionne un colis par un clic. Fond de carte : ' + (mapView.kind === 'leaflet' ? 'OpenStreetMap' : 'indisponible (plan schématique)');
  };
  const field = (i, name, cls, type) => h('input', { value: state.parcels[i][name], class: cls || '', type: type || 'text', 'aria-label': `${name} ligne ${i + 1}`, oninput: (e) => { state.parcels[i][name] = e.target.value; if (name === 'latitude' || name === 'longitude') refreshMap(); } });
  const refreshRows = () => {
    tbody.replaceChildren(...state.parcels.map((p, i) => {
      const choices = state.geoChoices[i];
      const main = h('tr', { class: i === state.selectedRow ? 'sel' : '', 'data-row': i },
        h('td', {}, i + 1), h('td', {}, field(i, 'id_colis', 'narrow')), h('td', {}, field(i, 'adresse', 'wide')),
        h('td', {}, field(i, 'latitude', 'narrow')), h('td', {}, field(i, 'longitude', 'narrow')),
        h('td', {}, field(i, 'heure_min', 'narrow')), h('td', {}, field(i, 'heure_max', 'narrow')), h('td', {}, field(i, 'heure_souhaitee', 'narrow')),
        h('td', {}, h('select', { value: p.priorite, 'aria-label': `Priorité ligne ${i + 1}`, onchange: (e) => { p.priorite = e.target.value; } }, ['normale', 'elevee', 'urgente'].map((v) => h('option', { value: v }, v === 'elevee' ? 'élevée' : v)))),
        h('td', {}, field(i, 'duree_remise_min', 'narrow')), h('td', {}, field(i, 'apres_colis', 'narrow')),
        h('td', { class: 'actions' }, h('button', { class: 'geo', title: 'Chercher les coordonnées de cette adresse', disabled: !state.me.geocoding_enabled, onclick: () => geocodeRow(i) }, 'Localiser'), ' ',
          h('button', { class: 'pick', onclick: () => { state.picking = i; state.selectedRow = i; refreshRows(); refreshMap(); } }, 'Placer sur la carte'), ' ',
          h('button', { class: 'danger del', 'aria-label': `Supprimer la ligne ${i + 1}`, onclick: () => { state.parcels.splice(i, 1); state.geoChoices = {}; refreshRows(); refreshMap(); } }, '✕')));
      const rows = [main];
      if (choices) rows.push(h('tr', {}, h('td', { colspan: 12, class: 'pickers' }, choices.length ? h('div', {}, h('span', { class: 'small' }, 'Choisissez le point (vérifiez-le sur la carte) : '), choices.map((c) => h('button', { onclick: () => { p.latitude = String(c.lat); p.longitude = String(c.lon); delete state.geoChoices[i]; refreshRows(); refreshMap(); } }, `${c.label}${c.approximate ? ' — approximatif' : ''}`))) : h('span', { class: 'small' }, 'Adresse introuvable : placez le point sur la carte.'))));
      return rows;
    }).flat());
  };
  async function geocodeRow(i) {
    const res = await guarded(() => api('POST', '/api/geocode', { address: state.parcels[i].adresse }));
    if (res) { state.geoChoices[i] = res.results; refreshRows(); }
  }
  const fileInput = h('input', { type: 'file', accept: '.csv,text/csv', id: 'csv-file', style: 'display:none', onchange: async (e) => {
    const f = e.target.files[0]; if (!f) return;
    try { state.parcels = csvToParcels(await f.text()); state.geoChoices = {}; notify(`${state.parcels.length} colis importés.`); refreshRows(); refreshMap(); } catch (err) { notify(err.message, 'error'); }
    e.target.value = '';
  } });
  const run = h('button', { id: 'optimize-btn', class: 'primary', disabled: state.busy, onclick: () => optimize(run) }, state.busy ? 'Calcul en cours…' : "Lancer l'optimisation");
  const view = h('div', { class: 'layout' },
    h('div', {},
      h('div', { class: 'card' }, h('h2', {}, 'Colis à livrer'),
        h('div', { class: 'row' },
          h('div', {}, h('label', { for: 'plan-date' }, 'Date'), h('input', { id: 'plan-date', type: 'date', value: state.date, onchange: (e) => { state.date = e.target.value; } })),
          h('div', {}, h('label', { for: 'plan-label' }, 'Nom du plan (facultatif)'), h('input', { id: 'plan-label', value: state.label, oninput: (e) => { state.label = e.target.value; } })),
          h('button', { id: 'add-parcel', onclick: () => { state.parcels.push(blankParcel()); refreshRows(); } }, '+ Ajouter un colis'),
          h('button', { id: 'import-btn', onclick: () => fileInput.click() }, 'Importer un fichier CSV'), fileInput,
          h('button', { id: 'demo-btn', onclick: () => guarded(async () => { const r = await fetch('/static/demo.csv'); state.parcels = csvToParcels(await r.text()); state.geoChoices = {}; refreshRows(); refreshMap(); notify('Données de démonstration (fictives) chargées.'); }) }, 'Charger la démonstration'),
          h('button', { id: 'clear-btn', onclick: () => { state.parcels = []; state.geoChoices = {}; refreshRows(); refreshMap(); } }, 'Vider'), run),
        h('p', { class: 'muted small' }, 'Heures au format HH:MM (ex. 10:00). « Après colis » : identifiant du colis qui doit être livré avant celui-ci. Plusieurs colis aux mêmes coordonnées forment un seul arrêt.'),
        h('div', { class: 'tablewrap' }, h('table', { id: 'parcel-table' }, h('thead', {}, h('tr', {}, ['#', 'Colis', 'Adresse', 'Latitude', 'Longitude', 'Heure min', 'Heure max', 'Souhaitée', 'Priorité', 'Remise (min)', 'Après colis', ''].map((t) => h('th', {}, t)))), tbody)))),
    h('div', {}, h('div', { class: 'card sticky' }, h('h2', {}, 'Carte'), container, info)));
  queueMicrotask(() => {
    mapView = createMap(container);
    mapView.onClick((lat, lon) => { if (state.picking == null) return; const p = state.parcels[state.picking]; p.latitude = lat.toFixed(6); p.longitude = lon.toFixed(6); state.picking = null; refreshRows(); refreshMap(); });
    refreshRows(); refreshMap();
  });
  return view;
}

async function optimize(button) {
  if (!state.parcels.length) { notify('Ajoutez au moins un colis.', 'error'); return; }
  state.busy = true; button.disabled = true; button.textContent = 'Calcul en cours…';
  try {
    const res = await api('POST', '/api/plans', { date: state.date, label: state.label, parcels: state.parcels });
    state.plan = res.result; state.planId = res.id; state.tab = 'resultats'; state.openStop = null;
    notify('Plan calculé.');
  } catch (e) { notify(e.message, 'error'); }
  state.busy = false; render();
}

/* --- résultats --- */
function resultsView() {
  const plan = state.plan;
  if (!plan) return h('div', { class: 'card' }, h('p', {}, 'Aucun plan affiché. Saisissez des colis puis lancez l\'optimisation, ou ouvrez un plan depuis l\'historique.'));
  const t = plan.totals;
  const kpis = [[t.drivers, 'livreur(s)'], [t.parcels_planned, 'colis planifiés'], [fmtKm(t.distance_km), 'distance totale'], [fmtAr(t.cost_ar), 'coût interne'], [fmtAr(t.revenue_ar), plan.billing_reliable ? 'total à facturer' : 'total (non facturable)'], [fmtAr(t.margin_ar), 'marge'], [t.distant_addresses, 'adresses éloignées']];
  const container = h('div', { id: 'map' });
  const alerts = plan.alerts.map((a) => h('div', { class: 'banner ' + (a.severity === 'critique' ? 'critique' : a.severity === 'info' ? 'info' : 'attention'), 'data-alert': a.code }, a.message));
  const verification = plan.verification_errors && plan.verification_errors.length
    ? h('div', { class: 'banner critique', id: 'verification-banner' }, 'Le vérificateur indépendant a détecté des incohérences : ', plan.verification_errors.join(' ; '))
    : h('div', { class: 'banner ok small', id: 'verification-ok' }, 'Vérification indépendante : toutes les contraintes, horaires et tarifs recalculés sont cohérents.');
  const routes = plan.routes.map((r) => routeCard(r));
  const unassigned = plan.unassigned.length ? h('div', { class: 'card', id: 'unassigned' }, h('h2', {}, 'Colis non attribués'), plan.unassigned.map((u) => h('div', { class: 'banner critique' }, h('b', {}, `${u.parcel_ids.join(', ')} · ${u.address}`), h('div', {}, u.reason), h('ul', {}, u.suggestions.map((s) => h('li', {}, s)))))) : null;
  const rejected = plan.rejected.length ? h('div', { class: 'card', id: 'rejected' }, h('h2', {}, 'Colis écartés'), h('p', { class: 'muted small' }, 'Ces colis ne sont pas planifiés : corrigez-les puis relancez.'), h('ul', {}, plan.rejected.map((r) => h('li', {}, h('b', {}, r.parcel_id), ' : ', r.message)))) : null;
  const issues = plan.issues.length ? h('div', { class: 'card' }, h('h2', {}, 'Points à vérifier'), h('ul', {}, plan.issues.map((i) => h('li', {}, i.message)))) : null;
  const choice = plan.drivers_choice.text ? h('div', { class: 'card' }, h('h2', {}, 'Pourquoi ce nombre de livreurs ?'), h('pre', { class: 'text' }, plan.drivers_choice.text)) : null;
  const view = h('div', { class: 'layout' },
    h('div', {}, h('div', { class: 'row' }, h('h2', {}, state.planId ? `Plan n° ${state.planId}` : 'Plan'), state.planId ? h('a', { class: 'btn', id: 'export-csv', href: `/api/plans/${state.planId}/export.csv` }, 'Exporter en CSV') : null),
      verification, alerts, h('div', { class: 'cards' }, kpis.map(([v, l]) => h('div', { class: 'kpi' }, h('b', {}, v), h('span', {}, l)))), routes, unassigned, rejected, issues, choice),
    h('div', {}, h('div', { class: 'card sticky' }, h('h2', {}, 'Carte des tournées'), container, h('p', { class: 'muted small' }, 'Les traits relient les arrêts en ligne droite (ordre de passage) ; ils ne représentent pas le tracé routier.'))));
  queueMicrotask(() => {
    mapView = createMap(container);
    const markers = [{ lat: plan.depot.lat, lon: plan.depot.lon, color: '#1d2433', square: true, title: `Dépôt : ${plan.depot.name}` }], lines = [];
    plan.routes.forEach((r) => {
      const color = COLORS[(r.driver - 1) % COLORS.length];
      lines.push({ color, points: [[plan.depot.lat, plan.depot.lon], ...r.stops.map((s) => [s.lat, s.lon])] });
      r.stops.forEach((s) => markers.push({ lat: s.lat, lon: s.lon, color, label: s.order, title: `Livreur ${r.driver} · ${s.order}. ${s.address} (${s.service_start})`, onclick: () => { state.openStop = `${r.driver}-${s.order}`; render(); } }));
    });
    mapView.set(markers, lines);
  });
  return view;
}

function routeCard(r) {
  const color = COLORS[(r.driver - 1) % COLORS.length];
  const rows = r.stops.flatMap((s) => {
    const key = `${r.driver}-${s.order}`;
    const open = state.openStop === key;
    const win = s.window.earliest || s.window.latest ? `${s.window.earliest || ''}–${s.window.latest || ''}` : '';
    const main = h('tr', { class: 'stop-row' + (s.is_distant ? ' distant' : ''), 'data-stop': key, tabindex: 0, onclick: () => { state.openStop = open ? null : key; render(); } },
      h('td', {}, s.order), h('td', {}, s.address, s.is_distant ? h('div', {}, h('span', { class: 'tag warn' }, 'éloignée')) : null), h('td', {}, s.parcel_ids.join(', ')),
      h('td', {}, s.service_start, s.wait_min > 0.5 ? h('div', { class: 'muted small' }, `arrivée ${s.arrival}, attente ${Math.round(s.wait_min)} min`) : null),
      h('td', {}, win), h('td', {}, fmtKm(s.leg_km)), h('td', {}, fmtAr(s.price_ar)));
    if (!open) return [main];
    const list = (items) => h('ul', {}, items.map((x) => h('li', {}, x)));
    return [main, h('tr', { class: 'detail' }, h('td', { colspan: 7 }, h('h4', {}, 'Pourquoi ce livreur et ce groupe'), list(s.why_assigned), h('h4', {}, 'Pourquoi cet ordre'), list(s.why_order), h('h4', {}, 'Pourquoi ce prix'), h('p', {}, s.price_explanation)))];
  });
  return h('div', { class: 'card route-card', 'data-driver': r.driver },
    h('h2', {}, h('span', { class: 'dot', style: `background:${color}` }), `Livreur ${r.driver}`),
    h('p', { class: 'muted small' }, `${r.parcel_count} colis · ${fmtKm(r.distance_km)} · fin de tournée ${r.end_time} · distance moyenne entre arrêts ${fmtKm(r.mean_leg_km)} · coût ${fmtAr(r.cost_ar)} · facturé ${fmtAr(r.revenue_ar)} · marge ${fmtAr(r.margin_ar)}`),
    r.alerts.filter((a) => a.code !== 'CLIENT_ELOIGNE').map((a) => h('div', { class: 'banner attention small' }, a.message)),
    h('div', { class: 'tablewrap' }, h('table', {}, h('thead', {}, h('tr', {}, ['#', 'Adresse', 'Colis', 'Remise', 'Contrainte', 'Trajet', 'Prix'].map((x) => h('th', {}, x)))), h('tbody', {}, rows))),
    h('p', { class: 'muted small' }, 'Cliquez sur un arrêt pour voir les explications chiffrées.'));
}

/* --- historique --- */
async function loadHistory() { const r = await guarded(() => api('GET', '/api/plans')); if (r) { state.plans = r.plans; if (state.tab === 'historique') render(); } }
function historyView() {
  return h('div', { class: 'card' }, h('h2', {}, 'Historique des plans'),
    state.plans.length ? h('table', { id: 'history-table' }, h('thead', {}, h('tr', {}, ['N°', 'Nom', 'Date', 'Créé par', 'Livreurs', 'Colis', 'Total', ''].map((x) => h('th', {}, x)))), h('tbody', {}, state.plans.map((p) => h('tr', {}, h('td', {}, p.id), h('td', {}, p.label), h('td', {}, p.date || ''), h('td', {}, p.created_by), h('td', {}, p.totals.drivers), h('td', {}, p.totals.parcels_planned), h('td', {}, fmtAr(p.totals.revenue_ar)),
      h('td', {}, h('button', { class: 'open-plan', onclick: () => guarded(async () => { const full = await api('GET', `/api/plans/${p.id}`); state.plan = full.result; state.planId = full.id; state.tab = 'resultats'; render(); }) }, 'Ouvrir')))))) : h('p', { class: 'muted' }, 'Aucun plan enregistré.'));
}

/* --- paramètres --- */
function settingsView() {
  const s = state.settings, admin = state.me.role === 'admin';
  if (!s) return h('div', { class: 'card' }, 'Chargement…');
  const inputs = {};
  const fieldFor = (group, key, value) => {
    const id = `set-${group || 'root'}-${key}`;
    let input;
    if (typeof value === 'boolean') input = h('input', { id, type: 'checkbox', checked: value, disabled: !admin });
    else if (typeof value === 'number' || value === null) input = h('input', { id, type: 'number', step: 'any', value: value === null ? '' : value, disabled: !admin });
    else input = h('input', { id, value, disabled: !admin });
    inputs[`${group}.${key}`] = { input, type: typeof value, nullable: value === null };
    return h('div', {}, h('label', { for: id }, LABELS[key] || key), input);
  };
  const section = (group) => h('div', { class: 'card' }, h('h2', {}, GROUP_TITLES[group]), h('div', { class: 'grid2' }, Object.entries(s[group]).map(([k, v]) => fieldFor(group, k, v))));
  const save = () => guarded(async () => {
    const out = { pricing: {}, optimizer: {}, depot_name: '', depot_lat: 0, depot_lon: 0 };
    for (const [path, { input, type, nullable }] of Object.entries(inputs)) {
      const [group, key] = path.split('.');
      const target = group === 'root' ? out : out[group];
      target[key] = type === 'boolean' ? input.checked : (type === 'number' || nullable) ? (input.value === '' ? null : Number(input.value)) : input.value;
    }
    state.settings = await api('PUT', '/api/settings', out); notify('Paramètres enregistrés.'); render();
  });
  return h('div', {}, !admin ? h('div', { class: 'banner info' }, 'Lecture seule : seuls les administrateurs modifient les paramètres.') : null,
    h('div', { class: 'card' }, h('h2', {}, 'Dépôt (point de départ de tous les livreurs)'), h('div', { class: 'grid2' }, fieldFor('root', 'depot_name', s.depot_name), fieldFor('root', 'depot_lat', s.depot_lat), fieldFor('root', 'depot_lon', s.depot_lon))),
    section('pricing'), section('optimizer'), admin ? h('button', { id: 'save-settings', class: 'primary', onclick: save }, 'Enregistrer les paramètres') : null);
}

/* --- compte et utilisateurs --- */
async function loadUsers() { if (state.me.role !== 'admin') return; const r = await guarded(() => api('GET', '/api/users')); if (r) { state.users = r.users; if (state.tab === 'compte') render(); } }
function accountView() {
  const oldP = h('input', { id: 'old-pass', type: 'password', autocomplete: 'current-password' }), newP = h('input', { id: 'new-pass', type: 'password', autocomplete: 'new-password' });
  const nu = h('input', { id: 'new-user' }), np = h('input', { id: 'new-user-pass', type: 'password', autocomplete: 'new-password' }), nr = h('select', { id: 'new-user-role' }, h('option', { value: 'operateur' }, 'opérateur'), h('option', { value: 'admin' }, 'administrateur'));
  return h('div', {},
    h('div', { class: 'card' }, h('h2', {}, 'Mon mot de passe'), h('div', { class: 'row' }, h('div', {}, h('label', { for: 'old-pass' }, 'Ancien'), oldP), h('div', {}, h('label', { for: 'new-pass' }, 'Nouveau (8 caractères minimum)'), newP),
      h('button', { id: 'change-pass', onclick: () => guarded(async () => { await api('POST', '/api/password', { old_password: oldP.value, new_password: newP.value }); oldP.value = newP.value = ''; notify('Mot de passe modifié.'); }) }, 'Modifier'))),
    state.me.role === 'admin' ? h('div', { class: 'card' }, h('h2', {}, 'Utilisateurs'),
      h('table', { id: 'users-table' }, h('thead', {}, h('tr', {}, ['Identifiant', 'Rôle', ''].map((x) => h('th', {}, x)))), h('tbody', {}, state.users.map((u) => h('tr', {}, h('td', {}, u.username), h('td', {}, u.role), h('td', {}, u.username === state.me.username ? '' : h('button', { class: 'danger', onclick: () => guarded(async () => { await api('DELETE', `/api/users/${encodeURIComponent(u.username)}`); await loadUsers(); }) }, 'Supprimer')))))),
      h('div', { class: 'row' }, h('div', {}, h('label', { for: 'new-user' }, 'Identifiant'), nu), h('div', {}, h('label', { for: 'new-user-pass' }, 'Mot de passe'), np), h('div', {}, h('label', { for: 'new-user-role' }, 'Rôle'), nr),
        h('button', { id: 'add-user', class: 'primary', onclick: () => guarded(async () => { await api('POST', '/api/users', { username: nu.value.trim(), password: np.value, role: nr.value }); notify('Utilisateur créé.'); await loadUsers(); }) }, 'Créer'))) : null);
}

async function bootstrap() {
  state.settings = await guarded(() => api('GET', '/api/settings'));
  render();
}

(async function init() {
  await loadLeaflet();
  try { state.me = await api('GET', '/api/me'); await bootstrap(); } catch (e) { state.me = null; render(); }
})();
