// Objet d'état unique, mutable : state → render() → DOM.
export const state = {
  content: null,
  slots: [],            // [{id, date, service, note}] — uniquement les créneaux libres
  selectedDate: null,   // YYYY-MM-DD choisi dans la liste
  selectedSlot: null,   // le créneau retenu (date + service)
  form: { name: '', email: '', phone: '', address: '', guests: '', formula: '', message: '' },
  submitting: false,
  error: '',
  confirmation: null,   // {ref, date, service, mail_sent}
  loadError: '',
};

export const EMPTY_FORM = { name: '', email: '', phone: '', address: '', guests: '', formula: '', message: '' };

export function slotsByDate() {
  const map = new Map();
  for (const slot of [...state.slots].sort((a, b) => a.date.localeCompare(b.date))) {
    if (!map.has(slot.date)) map.set(slot.date, []);
    map.get(slot.date).push(slot);
  }
  return map;
}
