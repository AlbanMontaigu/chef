/* Page de suivi d'une réservation, ouverte par le lien reçu par e-mail.
 *
 * Elle ne décide rien : ce qu'elle affiche et ce qu'elle propose viennent de
 * `/api/r/{token}`, et le bouton « annuler » n'est qu'un affichage — le
 * serveur refait le contrôle au moment d'écrire. Un client qui laisse la page
 * ouverte trois jours ne doit pas pouvoir annuler passé le délai parce que son
 * onglet, lui, croit encore que c'est permis.
 */

import { request } from '../js/api.js';
import { escapeHtml, longDate, SERVICE_LABEL, dietBadges } from '../js/util.js';

const app = document.getElementById('app');
// Le jeton se lit dans l'URL, jamais dans la page : il n'est écrit nulle part
// dans le HTML rendu, donc rien à copier par-dessus l'épaule.
const TOKEN = decodeURIComponent(location.pathname.split('/').filter(Boolean)[1] ?? '');

const state = { data: null, error: '', busy: false, flash: '' };

const api = {
  read: () => request(`/api/r/${encodeURIComponent(TOKEN)}`),
  cancel: () => request(`/api/r/${encodeURIComponent(TOKEN)}/cancel`, { method: 'POST' }),
};

function header(d) {
  const cancelled = d.status !== 'confirmed';
  return `
    <header class="client-head ${cancelled ? 'is-cancelled' : ''}">
      <p class="eyebrow">${escapeHtml(d.site)}</p>
      <h1>${cancelled ? 'Réservation annulée' : 'Votre réservation'}</h1>
      <p class="big">${escapeHtml(longDate(d.date))} — ${escapeHtml(SERVICE_LABEL[d.service] ?? d.service)}</p>
      <p class="ref">Référence ${escapeHtml(d.ref)}</p>
    </header>`;
}

function details(d) {
  const address = [d.address, d.city].filter(Boolean).join(', ');
  const rows = [
    ['Convives', `${d.guests}`],
    ['Formule', d.formula || 'à définir ensemble'],
    ['Lieu', address || 'adresse non communiquée'],
  ].map(([k, v]) => `<div class="kv"><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`).join('');
  return `
    <section class="panel">
      <h2>Le repas</h2>
      <dl class="kvs">${rows}</dl>
      <p class="label-line">Contraintes alimentaires</p>
      <p class="diet-line">${dietBadges(d.diets)}</p>
      ${d.message ? `<p class="label-line">Ce que vous m'avez écrit</p><p class="quote">« ${escapeHtml(d.message)} »</p>` : ''}
      <p class="hint">Une erreur, un convive en plus, une allergie oubliée ? Répondez à
        l'e-mail de confirmation : c'est le plus simple, et j'ai encore le temps de m'adapter.</p>
    </section>`;
}

/* Le menu, tel que le chef l'a envoyé. Absent tant qu'il ne l'a pas envoyé :
   un brouillon n'existe que pour lui, et le client découvrirait un menu que
   personne ne lui a présenté. */
function menuPanel(d) {
  const m = d.menu;
  if (!m) return '';
  const lines = m.lines.map((l) => `
    <div class="menu-line">
      ${l.course ? `<span class="menu-course">${escapeHtml(l.course)}</span>` : '<span></span>'}
      <span class="menu-dish">${escapeHtml(l.dish)}</span>
    </div>`).join('');
  return `
    <section class="panel menu-card">
      <h2>${escapeHtml(m.title || 'Votre menu')}</h2>
      <div class="menu-lines">${lines}</div>
      ${m.note ? `<p class="quote">${escapeHtml(m.note)}</p>` : ''}
      <p class="hint">Une envie, une réserve, un convive de plus ? Répondez à l'e-mail :
        tant que les courses ne sont pas faites, tout est encore possible.</p>
    </section>`;
}

/* L'argent n'est affiché que quand il y a quelque chose à en dire. Une section
   « 0 € » sur une réservation jamais facturée invente une créance. */
function moneyPanel(d) {
  const i = d.invoice;
  if (!i) {
    if (!d.paid_cents) return '';
    return `<section class="panel">
      <h2>Votre règlement</h2>
      <p>Vous avez versé <strong>${escapeHtml(d.paid)}</strong>. La facture vous
        parviendra après le repas.</p>
    </section>`;
  }
  const settled = i.balance_cents <= 0;
  return `
    <section class="panel">
      <h2>Votre facture</h2>
      <p><strong>${escapeHtml(i.number)}</strong> du ${escapeHtml(longDate(i.issued_on))} —
        ${escapeHtml(i.total)}</p>
      <p class="meta">Réglé ${escapeHtml(i.paid)}${settled
        ? ' · <span class="badge ok">soldée</span>'
        : ` · <strong>reste ${escapeHtml(i.balance)}</strong>${i.due_on ? ` · à régler avant le ${escapeHtml(longDate(i.due_on))}` : ''}`}</p>
      <p class="actions"><a class="btn" href="/api/r/${encodeURIComponent(TOKEN)}/invoice"
        target="_blank" rel="noopener">Voir / imprimer la facture</a></p>
    </section>`;
}

function cancelPanel(d) {
  if (d.status !== 'confirmed') {
    return `<section class="panel">
      <h2>Annulation</h2>
      <p>Cette réservation est annulée${d.cancelled_at ? ` depuis le ${escapeHtml(longDate(d.cancelled_at.slice(0, 10)))}` : ''}.
        Le créneau est de nouveau libre sur le site.</p>
      <p class="hint">Envie de reprendre une date ? Répondez à l'e-mail, je vous en garde une.</p>
    </section>`;
  }
  const c = d.cancellation;
  if (!c.allowed) {
    // Le motif vient du serveur : la page n'invente pas de règle et ne peut
    // donc pas en afficher une qui ne serait plus celle appliquée.
    return `<section class="panel">
      <h2>Annuler</h2>
      <p>${escapeHtml(c.reason)}</p>
      ${d.contact?.email ? `<p class="actions"><a class="btn" href="mailto:${escapeHtml(d.contact.email)}?subject=${encodeURIComponent(`Réservation ${d.ref}`)}">Écrire au chef</a></p>` : ''}
    </section>`;
  }
  return `<section class="panel">
    <h2>Annuler</h2>
    <p class="hint">${escapeHtml(c.reason)}</p>
    ${d.paid_cents > 0 ? `<p class="warn">Vous avez versé ${escapeHtml(d.paid)} : l'annulation ne
      déclenche pas le remboursement toute seule, le chef vous recontacte pour le faire.</p>` : ''}
    <p class="actions"><button class="btn danger" data-cancel="1" ${state.busy ? 'disabled' : ''}>
      ${state.busy ? 'Annulation…' : 'Annuler ma réservation'}</button></p>
  </section>`;
}

function render() {
  app.setAttribute('aria-busy', 'false');
  if (state.error && !state.data) {
    app.innerHTML = `<div class="wrap client-wrap"><section class="panel">
      <h2>Lien inconnu</h2><p>${escapeHtml(state.error)}</p>
      <p class="hint">Vérifiez que le lien est complet — les e-mails le coupent parfois en deux lignes.</p>
    </section></div>`;
    return;
  }
  const d = state.data;
  app.innerHTML = `<div class="wrap client-wrap">
    ${header(d)}
    ${state.flash ? `<p class="flash">${escapeHtml(state.flash)}</p>` : ''}
    ${state.error ? `<p class="error" role="alert">${escapeHtml(state.error)}</p>` : ''}
    ${details(d)}
    ${menuPanel(d)}
    ${moneyPanel(d)}
    ${cancelPanel(d)}
    <p class="build"><a href="/">Retour au site</a></p>
  </div>`;
}

app.addEventListener('click', async (event) => {
  if (!event.target.closest('[data-cancel]')) return;
  if (!confirm("Annuler cette réservation ?\n\nLe créneau repartira sur le site et le chef sera prévenu.")) return;
  state.busy = true; state.error = ''; state.flash = ''; render();
  try {
    state.data = await api.cancel();
    state.flash = 'Votre annulation est enregistrée. Le chef vient d\'en être informé.';
  } catch (err) {
    // 409 : le délai a expiré, ou une facture est partie, pendant que la page
    // était ouverte. Le message du serveur dit laquelle des deux.
    state.error = err.message;
    try { state.data = await api.read(); } catch { /* on garde l'affichage courant */ }
  } finally {
    state.busy = false;
    render();
  }
});

async function start() {
  try {
    state.data = await api.read();
  } catch (err) {
    state.error = err.message;
  }
  render();
  if (state.data) document.title = `Réservation ${state.data.ref} — ${state.data.site}`;
}

start();
