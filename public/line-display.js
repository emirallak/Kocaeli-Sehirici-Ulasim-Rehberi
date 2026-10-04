/* Preserve service-day ordering in the API; format only the visible clock. */
const LineDisplay = {
  departure(time) {
    const match = /^(\d{1,2}):([0-5]\d)(?::([0-5]\d))?$/.exec(String(time));
    if (!match) return {label: '—', dayOffset: 0};
    const hour = Number(match[1]);
    const seconds = match[3] && match[3] !== '00' ? `:${match[3]}` : '';
    return {label: `${String(hour % 24).padStart(2, '0')}:${match[2]}${seconds}`,
      dayOffset: Math.floor(hour / 24)};
  },
  restrictions(stop) {
    const labels = [];
    if (stop.pickup_allowed === false) labels.push('Binilmez');
    if (stop.dropoff_allowed === false) labels.push('İnilmez');
    return labels;
  },
};
if (typeof module !== 'undefined' && module.exports) module.exports = LineDisplay;
