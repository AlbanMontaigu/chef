// Every user-supplied string interpolated into HTML goes through escapeHtml.
// Names, messages and addresses are free text and are rendered in the
// back-office -- never interpolate one raw.
export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

const DAYS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'];
const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
  'août', 'septembre', 'octobre', 'novembre', 'décembre'];

export const SERVICE_LABEL = { midi: 'Déjeuner', soir: 'Dîner' };

// Dates are handled as plain YYYY-MM-DD strings throughout. Parsing them into
// Date objects invites a timezone shift that moves a booking by a day.
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

export function monthLabel(year, month) {
  return `${MONTHS[month - 1]} ${year}`;
}

export function isoOf(year, month, day) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export function daysInMonth(year, month) {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}
