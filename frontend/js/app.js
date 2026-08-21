import { api } from './api.js';
import { state, slotsByDate, EMPTY_FORM, EMPTY_QUOTE } from './state.js';
import { renderSite } from './views/site.js';
import { renderBooking } from './views/booking.js';
import { renderQuote } from './views/quote.js';

const app = document.getElementById('app');

// La partie éditoriale est figée après le chargement ; seul le bloc réservation
// se re-rend, pour ne jamais vider un formulaire en cours de saisie.
function renderBookingOnly() {
  const host = document.getElementById('booking');
  if (host) host.innerHTML = renderBooking();
}

function renderQuoteOnly() {
  const host = document.getElementById('quote');
  if (host) host.innerHTML = renderQuote();
}

function renderAll() {
  app.innerHTML = renderSite(state.content);
  app.setAttribute('aria-busy', 'false');
  renderBookingOnly();
  renderQuoteOnly();
  stampBuild();
}

async function stampBuild() {
  // Même repère que flip7 : distinguer d'un coup d'œil deux instances déployées.
  try {
    const text = (await (await fetch('/build.txt')).text()).trim();
    const host = document.getElementById('build-stamp');
    if (text && host) host.textContent = `mise en ligne ${text}`;
  } catch { /* purement cosmétique, ne doit jamais casser la page */ }
}

function captureForm() {
  const form = document.getElementById('booking-form');
  if (!form) return;
  for (const key of Object.keys(state.form)) {
    const field = form.elements[key];
    if (field) state.form[key] = field.value;
  }
}

function captureQuote() {
  const form = document.getElementById('quote-form');
  if (!form) return;
  for (const key of Object.keys(state.quoteForm)) {
    const field = form.elements[key];
    if (field) state.quoteForm[key] = field.value;
  }
}

async function submitQuote() {
  captureQuote();
  state.quoteError = '';
  const q = state.quoteForm;
  if (!q.name.trim() || !q.email.trim()) {
    // Volontairement peu exigeant : nom et e-mail suffisent. Tout le reste se
    // précise dans l'échange, et un formulaire qui refuse fait perdre la
    // demande plutôt que de l'améliorer.
    state.quoteError = "Il me faut au moins votre nom et votre e-mail pour vous répondre.";
    renderQuoteOnly();
    return;
  }
  state.quoteSubmitting = true;
  renderQuoteOnly();
  try {
    state.quoteConfirmation = await api.quote({
      name: q.name.trim(),
      email: q.email.trim(),
      phone: q.phone.trim(),
      city: q.city.trim(),
      wanted_date: q.wanted_date,
      service: q.service,
      flexibility: q.flexibility.trim(),
      guests: Number(q.guests) || 0,
      occasion: q.occasion,
      formula: q.formula,
      diets: [...state.quoteDiets].map((id) => ({ id, count: 1 })),
      message: q.message.trim(),
    });
    document.getElementById('devis')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    state.quoteError = err.message;
  } finally {
    state.quoteSubmitting = false;
    renderQuoteOnly();
  }
}

function scrollToBooking() {
  document.getElementById('reserver')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function loadAvailability() {
  try {
    state.slots = (await api.availability()).slots;
    state.loadError = '';
  } catch (err) {
    state.loadError = `Impossible de charger les disponibilités (${err.message}).`;
  }
}

async function submit() {
  captureForm();
  state.error = '';
  const f = state.form;
  if (!f.name.trim() || !f.email.trim() || !f.guests) {
    state.error = 'Il me faut au moins votre nom, votre e-mail et le nombre de convives.';
    renderBookingOnly();
    return;
  }
  state.submitting = true;
  renderBookingOnly();
  try {
    state.confirmation = await api.book({
      slot_id: state.selectedSlot.id,
      name: f.name.trim(),
      email: f.email.trim(),
      phone: f.phone.trim(),
      address: f.address.trim(),
      city: f.city.trim(),
      guests: Number(f.guests),
      formula: f.formula,
      diets: [...state.diets].map(([id, count]) => ({ id, count })),
      message: f.message.trim(),
    });
    state.selectedSlot = null;
    state.selectedDate = null;
    scrollToBooking();
  } catch (err) {
    state.error = err.message;
    // 409/404 : le créneau est parti pendant la saisie. On rafraîchit la liste
    // plutôt que de laisser une date morte sélectionnée.
    if (err.status === 409 || err.status === 404) {
      await loadAvailability();
      state.selectedSlot = null;
      state.selectedDate = null;
    }
  } finally {
    state.submitting = false;
    renderBookingOnly();
  }
}

app.addEventListener('click', (event) => {
  const card = event.target.closest('[data-date]');
  if (card) {
    const date = card.dataset.date;
    state.selectedDate = state.selectedDate === date ? null : date;
    state.selectedSlot = null;
    state.error = '';
    // Un seul service ce jour-là : inutile de faire choisir entre une option.
    const slots = slotsByDate().get(state.selectedDate) ?? [];
    if (slots.length === 1) state.selectedSlot = slots[0];
    renderBookingOnly();
    if (state.selectedSlot) document.getElementById('booking-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    else document.getElementById('services')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    return;
  }

  const service = event.target.closest('[data-slot]');
  if (service) {
    const id = Number(service.dataset.slot);
    state.selectedSlot = state.slots.find((s) => s.id === id) ?? null;
    state.error = '';
    renderBookingOnly();
    document.getElementById('booking-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }

  if (event.target.closest('[data-change]')) {
    captureForm();
    state.selectedSlot = null;
    state.selectedDate = null;
    renderBookingOnly();
    scrollToBooking();
    return;
  }

  if (event.target.closest('[data-quote-reset]')) {
    state.quoteConfirmation = null;
    state.quoteForm = { ...EMPTY_QUOTE };
    state.quoteDiets = new Set();
    renderQuoteOnly();
    return;
  }

  if (event.target.closest('[data-reset]')) {
    state.confirmation = null;
    state.form = { ...EMPTY_FORM };
    state.diets = new Map();
    loadAvailability().then(renderBookingOnly);
  }
});

/* Cocher un régime re-rend le bloc réservation (le compteur apparaît), ce qui
   réécrit le formulaire : la saisie en cours est donc capturée avant. Écouté
   sur `change` et non sur `click` — un clic sur le libellé produit aussi un
   clic synthétique sur la case, et le régime se serait coché puis décoché. */
app.addEventListener('change', (event) => {
  const quoteBox = event.target.closest('[data-quote-diet]');
  if (quoteBox) {
    captureQuote();
    const id = quoteBox.dataset.quoteDiet;
    if (quoteBox.checked) state.quoteDiets.add(id); else state.quoteDiets.delete(id);
    renderQuoteOnly();
    return;
  }

  const box = event.target.closest('[data-diet]');
  if (!box) return;
  captureForm();
  const id = box.dataset.diet;
  if (box.checked) state.diets.set(id, state.diets.get(id) ?? 1);
  else state.diets.delete(id);
  renderBookingOnly();
});

/* Le nombre se met à jour SANS re-rendu : réécrire le formulaire à chaque
   frappe ferait perdre le focus au milieu de la saisie. */
app.addEventListener('input', (event) => {
  const field = event.target.closest('[data-diet-count]');
  if (!field) return;
  const n = Math.max(1, Math.min(100, Number(field.value) || 1));
  state.diets.set(field.dataset.dietCount, n);
});

app.addEventListener('submit', (event) => {
  if (event.target.id === 'booking-form') { event.preventDefault(); submit(); }
  if (event.target.id === 'quote-form') { event.preventDefault(); submitQuote(); }
});

async function start() {
  try {
    state.content = await api.content();
  } catch {
    app.innerHTML = '<p class="loading">Le site est momentanément indisponible.</p>';
    return;
  }
  document.title = `${state.content.name} — chef à domicile`;
  await loadAvailability();
  renderAll();
}

start();
