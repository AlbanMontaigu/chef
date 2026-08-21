import { api } from './api.js';
import { state } from './state.js';
import { renderSite } from './views/site.js';
import { renderBooking } from './views/booking.js';

const app = document.getElementById('app');

// The site copy is static per load; only the booking widget re-renders, so a
// visitor mid-form never has the page pulled out from under them.
function renderBookingOnly() {
  const host = document.getElementById('booking');
  if (host) host.innerHTML = renderBooking();
}

async function buildStamp() {
  // Same trick as flip7: a deployed instance can be told apart at a glance.
  try {
    const text = (await (await fetch('/build.txt')).text()).trim();
    if (text) {
      const footer = document.createElement('p');
      footer.className = 'build';
      footer.textContent = `mise en ligne ${text}`;
      app.appendChild(footer);
    }
  } catch { /* the stamp is cosmetic; never let it break the page */ }
}

function renderAll() {
  app.innerHTML = renderSite(state.content);
  app.setAttribute('aria-busy', 'false');
  renderBookingOnly();
  buildStamp();
}

function firstMonthWithSlots() {
  const dates = state.slots.map((s) => s.date).sort();
  const iso = dates[0] ?? new Date().toISOString().slice(0, 10);
  const [year, month] = iso.split('-').map(Number);
  return { year, month };
}

function shiftMonth(delta) {
  let { year, month } = state.month;
  month += delta;
  if (month < 1) { month = 12; year -= 1; }
  if (month > 12) { month = 1; year += 1; }
  state.month = { year, month };
}

function captureForm() {
  const form = document.getElementById('booking-form');
  if (!form) return;
  for (const key of Object.keys(state.form)) {
    const field = form.elements[key];
    if (field) state.form[key] = field.value;
  }
}

async function submit() {
  captureForm();
  state.error = '';
  const f = state.form;
  if (!f.name.trim() || !f.email.trim() || !f.guests) {
    state.error = 'Nom, e-mail et nombre de convives sont nécessaires.';
    renderBookingOnly();
    return;
  }
  state.submitting = true;
  renderBookingOnly();
  try {
    const result = await api.book({
      slot_id: state.selectedSlot.id,
      name: f.name.trim(),
      email: f.email.trim(),
      phone: f.phone.trim(),
      address: f.address.trim(),
      guests: Number(f.guests),
      formula: f.formula,
      message: f.message.trim(),
    });
    state.confirmation = result;
    state.selectedSlot = null;
    state.selectedDate = null;
  } catch (err) {
    state.error = err.message;
    // 409 means the slot went while the form was open: refresh the calendar
    // rather than leaving a dead date selected.
    if (err.status === 409 || err.status === 404) {
      await loadAvailability();
      state.selectedSlot = null;
    }
  } finally {
    state.submitting = false;
    renderBookingOnly();
  }
}

async function loadAvailability() {
  try {
    const data = await api.availability();
    state.slots = data.slots;
    state.loadError = '';
  } catch (err) {
    state.loadError = `Impossible de charger les disponibilités (${err.message}).`;
  }
}

app.addEventListener('click', (event) => {
  const nav = event.target.closest('[data-nav]');
  if (nav) { shiftMonth(Number(nav.dataset.nav)); renderBookingOnly(); return; }

  const day = event.target.closest('[data-date]');
  if (day) {
    captureForm();
    state.selectedDate = state.selectedDate === day.dataset.date ? null : day.dataset.date;
    state.selectedSlot = null;
    state.error = '';
    renderBookingOnly();
    return;
  }

  const service = event.target.closest('[data-slot]');
  if (service) {
    captureForm();
    const id = Number(service.dataset.slot);
    state.selectedSlot = state.selectedSlot?.id === id
      ? null : state.slots.find((s) => s.id === id) ?? null;
    state.error = '';
    renderBookingOnly();
    document.getElementById('booking-form')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    return;
  }

  if (event.target.closest('[data-reset]')) {
    state.confirmation = null;
    state.form = { name: '', email: '', phone: '', address: '', guests: '', formula: '', message: '' };
    loadAvailability().then(renderBookingOnly);
  }
});

app.addEventListener('submit', (event) => {
  if (event.target.id === 'booking-form') { event.preventDefault(); submit(); }
});

async function start() {
  try {
    state.content = await api.content();
  } catch {
    app.innerHTML = '<p class="error">Le site est momentanément indisponible.</p>';
    return;
  }
  document.title = state.content.name || document.title;
  await loadAvailability();
  state.month = firstMonthWithSlots();
  renderAll();
}

start();
