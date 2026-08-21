import { request } from '../js/api.js';
import { escapeHtml, longDate, monthLabel, isoOf, daysInMonth, weekdayIndex, SERVICE_LABEL } from '../js/util.js';

const app = document.getElementById('app');
const WEEKDAYS = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];
const SERVICES = ['midi', 'soir'];

const view = {
  authenticated: false,
  configured: true,
  mailEnabled: true,
  month: null,
  slots: [],
  bookings: [],
  selectedDate: null,
  firstBookable: null,
  error: '',
  busy: false,
};

const api = {
  session: () => request('/api/admin/session'),
  login: (password) => request('/api/admin/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => request('/api/admin/logout', { method: 'POST' }),
  slots: (start, end) => request(`/api/admin/slots?start=${start}&end=${end}`),
  openSlots: (items) => request('/api/admin/slots', { method: 'POST', body: JSON.stringify({ items }) }),
  closeSlot: (id) => request(`/api/admin/slots/${id}`, { method: 'DELETE' }),
  bookings: () => request('/api/admin/bookings?status=confirmed'),
  cancel: (id, reason) => request(`/api/admin/bookings/${id}/cancel`, { method: 'POST', body: JSON.stringify({ reason }) }),
  resend: (id) => request(`/api/admin/bookings/${id}/resend`, { method: 'POST' }),
};

function monthBounds() {
  const { year, month } = view.month;
  return [isoOf(year, month, 1), isoOf(year, month, daysInMonth(year, month))];
}

function slotAt(date, service) {
  return view.slots.find((s) => s.date === date && s.service === service) ?? null;
}

// --- Rendering ---------------------------------------------------------

function loginView() {
  const warning = view.configured ? '' :
    `<p class="error">ADMIN_PASSWORD n'est pas configuré côté serveur : le back-office est inutilisable tant que la variable n'est pas posée dans Coolify.</p>`;
  return `
    <form class="admin-card admin-login" id="login-form">
      <h1>Back-office</h1>
      ${warning}
      <label>Mot de passe<input name="password" type="password" autocomplete="current-password" required></label>
      ${view.error ? `<p class="error" role="alert">${escapeHtml(view.error)}</p>` : ''}
      <button class="cta" type="submit" style="margin-top:1rem" ${view.busy ? 'disabled' : ''}>Entrer</button>
    </form>`;
}

function calendarView() {
  const { year, month } = view.month;
  const total = daysInMonth(year, month);
  const offset = weekdayIndex(isoOf(year, month, 1));
  const cells = [];
  for (let i = 0; i < offset; i += 1) cells.push('<div class="day empty"></div>');
  for (let d = 1; d <= total; d += 1) {
    const iso = isoOf(year, month, d);
    const open = SERVICES.map((s) => slotAt(iso, s)).filter(Boolean);
    const booked = open.some((s) => s.booking_id);
    const klass = booked ? 'day booked' : open.length ? 'day free' : 'day off';
    const dots = open.map((s) => `<i class="dot ${escapeHtml(s.service)}"></i>`).join('');
    const selected = view.selectedDate === iso ? ' selected' : '';
    cells.push(`<button type="button" class="${klass}${selected}" data-date="${iso}">
      <span>${d}</span><span class="dots">${dots}</span></button>`);
  }
  return `
    <div class="calendar">
      <div class="cal-head">
        <button type="button" class="nav" data-nav="-1">‹</button>
        <strong>${escapeHtml(monthLabel(year, month))}</strong>
        <button type="button" class="nav" data-nav="1">›</button>
      </div>
      <div class="weekdays">${WEEKDAYS.map((d) => `<span>${d}</span>`).join('')}</div>
      <div class="grid">${cells.join('')}</div>
      <p class="legend"><i class="dot midi"></i> déjeuner &nbsp; <i class="dot soir"></i> dîner &nbsp;— vert : ouvert · rouge : réservé</p>
    </div>`;
}

function dayPanel() {
  if (!view.selectedDate) {
    return `<div class="admin-card"><p class="hint" style="margin:0">Clique sur un jour du calendrier pour ouvrir ou fermer un créneau.</p></div>`;
  }
  const rows = SERVICES.map((service) => {
    const slot = slotAt(view.selectedDate, service);
    const label = SERVICE_LABEL[service];
    if (!slot) {
      return `<div class="toolbar"><strong>${label}</strong>
        <button class="btn-small" data-open="${service}">Ouvrir</button></div>`;
    }
    if (slot.booking_id) {
      return `<div class="toolbar"><strong>${label}</strong>
        <span class="badge bad">Réservé — ${escapeHtml(slot.name)} (${escapeHtml(slot.guests)} couverts, ${escapeHtml(slot.ref)})</span>
        <span class="hint">Annule depuis la liste ci-dessous pour libérer la date.</span></div>`;
    }
    // Open but inside the lead-in window: nobody can book it, say so.
    const tooSoon = view.firstBookable && slot.date < view.firstBookable;
    const badge = tooSoon
      ? `<span class="badge warn">Ouvert mais trop proche — invisible sur le site</span>`
      : `<span class="badge ok">Ouvert</span>`;
    return `<div class="toolbar"><strong>${label}</strong>
      ${badge}
      <button class="btn-small" data-close="${slot.id}">Fermer</button></div>`;
  }).join('');
  return `<div class="admin-card">
    <h2 class="day-title" style="margin-top:0">${escapeHtml(longDate(view.selectedDate))}</h2>
    ${rows}
  </div>`;
}

function mailBadge(booking) {
  const states = [booking.mail_client, booking.mail_chef];
  if (states.every((s) => s === 'sent')) return '<span class="badge ok">e-mails envoyés</span>';
  if (states.includes('failed')) {
    // The two recipients usually fail for the same reason; showing it twice
    // just makes the real message harder to read.
    const reasons = [...new Set(booking.mail_error.split(' | ').filter(Boolean))];
    return `<span class="badge bad">e-mail en échec</span> <span class="hint">${escapeHtml(reasons.join(' · '))}</span>`;
  }
  if (states.includes('disabled')) return '<span class="badge warn">envoi désactivé</span>';
  return '<span class="badge warn">envoi en cours…</span>';
}

function bookingsView() {
  if (!view.bookings.length) {
    return `<div class="admin-card"><h2 style="margin-top:0">Réservations</h2><p class="hint">Aucune réservation active.</p></div>`;
  }
  const rows = view.bookings.map((b) => `
    <div class="booking-row">
      <div class="when">${escapeHtml(longDate(b.date))} — ${escapeHtml(SERVICE_LABEL[b.service] ?? b.service)} · ${escapeHtml(b.guests)} couverts</div>
      <div class="who">${escapeHtml(b.name)} · ${escapeHtml(b.email)} · ${escapeHtml(b.phone || '—')}</div>
      <div class="meta">${escapeHtml(b.address || 'adresse non renseignée')} · ${escapeHtml(b.formula || 'formule à définir')} · réf. ${escapeHtml(b.ref)}</div>
      ${b.message ? `<div class="meta">« ${escapeHtml(b.message)} »</div>` : ''}
      <div class="toolbar" style="margin:0.4rem 0 0">
        ${mailBadge(b)}
        <button class="btn-small" data-cancel="${b.id}">Annuler</button>
        <button class="btn-small" data-resend="${b.id}">Renvoyer les e-mails</button>
      </div>
    </div>`).join('');
  return `<div class="admin-card"><h2 style="margin-top:0">Réservations à venir</h2>${rows}</div>`;
}

function render() {
  if (!view.authenticated) { app.innerHTML = loginView(); return; }
  const mailWarn = view.mailEnabled ? '' :
    `<div class="admin-card"><p class="error">SMTP_HOST n'est pas configuré : aucune confirmation ne part. Les réservations sont bien enregistrées, mais les clients ne reçoivent rien.</p></div>`;
  app.innerHTML = `
    <div class="admin-head">
      <h1>Back-office</h1>
      <div class="toolbar" style="margin:0">
        <a href="/" class="btn-small" style="text-decoration:none">Voir le site</a>
        <button class="btn-small" data-logout="1">Déconnexion</button>
      </div>
    </div>
    ${view.error ? `<div class="admin-card"><p class="error" role="alert">${escapeHtml(view.error)}</p></div>` : ''}
    ${mailWarn}
    <div class="admin-split">
      <div class="admin-card">${calendarView()}</div>
      ${dayPanel()}
    </div>
    ${bookingsView()}`;
}

// --- Data --------------------------------------------------------------

async function refresh() {
  const [start, end] = monthBounds();
  try {
    const [slots, bookings] = await Promise.all([api.slots(start, end), api.bookings()]);
    view.slots = slots.slots;
    view.firstBookable = slots.first_bookable;
    view.bookings = bookings.bookings;
    view.error = '';
  } catch (err) {
    if (err.status === 401) { view.authenticated = false; view.error = err.message; }
    else view.error = err.message;
  }
  render();
}

async function act(fn) {
  view.busy = true;
  try {
    await fn();
    view.error = '';
  } catch (err) {
    view.error = err.message;
    if (err.status === 401) view.authenticated = false;
  } finally {
    view.busy = false;
  }
  await refresh();
}

// --- Events ------------------------------------------------------------

app.addEventListener('submit', async (event) => {
  if (event.target.id !== 'login-form') return;
  event.preventDefault();
  const password = event.target.elements.password.value;
  view.busy = true; render();
  try {
    await api.login(password);
    view.authenticated = true;
    view.error = '';
    await refresh();
  } catch (err) {
    view.error = err.message;
    view.busy = false;
    render();
  }
});

app.addEventListener('click', (event) => {
  const nav = event.target.closest('[data-nav]');
  if (nav) {
    let { year, month } = view.month;
    month += Number(nav.dataset.nav);
    if (month < 1) { month = 12; year -= 1; }
    if (month > 12) { month = 1; year += 1; }
    view.month = { year, month };
    view.selectedDate = null;
    refresh();
    return;
  }
  const day = event.target.closest('[data-date]');
  if (day) {
    view.selectedDate = view.selectedDate === day.dataset.date ? null : day.dataset.date;
    render();
    return;
  }
  const open = event.target.closest('[data-open]');
  if (open) {
    act(() => api.openSlots([{ date: view.selectedDate, service: open.dataset.open, note: '' }]));
    return;
  }
  const close = event.target.closest('[data-close]');
  if (close) { act(() => api.closeSlot(Number(close.dataset.close))); return; }

  const cancel = event.target.closest('[data-cancel]');
  if (cancel) {
    const reason = prompt('Annuler cette réservation ? Le client sera prévenu par e-mail.\nMotif (facultatif, repris dans l\'e-mail) :');
    if (reason === null) return;
    act(() => api.cancel(Number(cancel.dataset.cancel), reason));
    return;
  }
  const resend = event.target.closest('[data-resend]');
  if (resend) { act(() => api.resend(Number(resend.dataset.resend))); return; }

  if (event.target.closest('[data-logout]')) {
    act(async () => { await api.logout(); view.authenticated = false; });
  }
});

async function start() {
  const now = new Date();
  view.month = { year: now.getFullYear(), month: now.getMonth() + 1 };
  try {
    const session = await api.session();
    view.authenticated = session.authenticated;
    view.configured = session.configured;
    view.mailEnabled = session.mail_enabled;
  } catch { /* fall through to the login screen */ }
  if (view.authenticated) await refresh();
  else render();
}

start();
