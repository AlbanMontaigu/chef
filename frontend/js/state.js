// Single mutable state object, same shape as flip7: state -> render() -> DOM.
export const state = {
  content: null,
  slots: [],            // [{id, date, service, note}]
  firstBookable: null,
  month: null,          // {year, month} currently shown in the calendar
  selectedDate: null,   // YYYY-MM-DD clicked in the calendar
  selectedSlot: null,   // slot object
  form: { name: '', email: '', phone: '', address: '', guests: '', formula: '', message: '' },
  submitting: false,
  error: '',
  confirmation: null,   // {ref, date, service}
  loadError: '',
};

export function slotsByDate() {
  const map = new Map();
  for (const slot of state.slots) {
    if (!map.has(slot.date)) map.set(slot.date, []);
    map.get(slot.date).push(slot);
  }
  return map;
}
