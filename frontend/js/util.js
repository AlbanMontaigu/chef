// Toute chaîne fournie par un visiteur et interpolée dans du HTML passe par
// escapeHtml. Noms, adresses et messages sont du texte libre et sont réaffichés
// dans le back-office — ne jamais en interpoler un brut.
export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

const DAYS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'];
const DAYS_SHORT = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.'];
const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
  'août', 'septembre', 'octobre', 'novembre', 'décembre'];
const MONTHS_SHORT = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.',
  'août', 'sept.', 'oct.', 'nov.', 'déc.'];

export const SERVICE_LABEL = { midi: 'Déjeuner', soir: 'Dîner' };

// Les dates circulent en chaînes YYYY-MM-DD de bout en bout. Les convertir en
// Date invite un décalage de fuseau qui déplacerait une réservation d'un jour.
export function parseISO(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function weekdayIndex(iso) {
  return (parseISO(iso).getUTCDay() + 6) % 7; // 0 = lundi
}

export function longDate(iso) {
  const d = parseISO(iso);
  return `${DAYS[weekdayIndex(iso)]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

export function shortWeekday(iso) { return DAYS_SHORT[weekdayIndex(iso)]; }
export function weekdayName(iso) { return DAYS[weekdayIndex(iso)]; }
export function dayNumber(iso) { return parseISO(iso).getUTCDate(); }
export function shortMonth(iso) { return MONTHS_SHORT[parseISO(iso).getUTCMonth()]; }

export function monthKey(iso) { return iso.slice(0, 7); }
export function monthLabelFromKey(key) {
  const [y, m] = key.split('-').map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}
export function monthLabel(year, month) { return `${MONTHS[month - 1]} ${year}`; }

export function isoOf(year, month, day) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export function daysInMonth(year, month) {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

export function todayISO() {
  // L'horloge du navigateur, suffisante pour griser le passé dans le
  // back-office ; le serveur reste seul juge de ce qui est réservable.
  const n = new Date();
  return isoOf(n.getFullYear(), n.getMonth() + 1, n.getDate());
}

// --- Montants -----------------------------------------------------------
// L'argent circule en centimes entiers de bout en bout, exactement comme
// côté serveur. La seule conversion en décimal se fait ici, à l'affichage.

const EUR = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' });

export function formatAmount(cents) {
  return EUR.format((Number(cents) || 0) / 100);
}

// Saisie humaine -> centimes. Renvoie null si ce n'est pas un montant, pour
// que l'appelant refuse au lieu d'envoyer un zéro silencieux au serveur.
export function parseAmount(text) {
  const clean = String(text ?? '').replace(/[\s  €]/g, '').replace(',', '.');
  if (!/^-?\d+(\.\d{1,2})?$/.test(clean)) return null;
  return Math.round(Number(clean) * 100);
}

// Centimes -> valeur d'un <input>, sans symbole ni séparateur de milliers :
// un champ pré-rempli avec « 1 234,50 € » ne se resaisit pas.
export function amountInput(cents) {
  return ((Number(cents) || 0) / 100).toFixed(2).replace('.', ',');
}

export const PAYMENT_KIND_LABEL = {
  acompte: 'Acompte', solde: 'Solde', remboursement: 'Remboursement',
};
export const PAYMENT_METHOD_LABEL = {
  virement: 'Virement', especes: 'Espèces', cheque: 'Chèque', cb: 'Carte', autre: 'Autre',
};
export const BILLING_STATE_LABEL = {
  unbilled: 'pas encore facturé', unpaid: 'en attente de paiement',
  partial: 'partiellement payé', paid: 'soldé', overpaid: 'trop-perçu',
  cancelled: 'annulée',
};
