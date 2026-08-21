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
