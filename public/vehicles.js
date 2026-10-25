/* Simulated vehicles on a Leaflet map. /api/vehicles assumes on-time
 * departures and an average speed (no live feed exists); markers glide
 * between polls through a CSS transition of the same length. */
const VEHICLE_POLL_MS = 10000;

/* Apply pending marker moves without a transition, then re-enable it. */
function settleVehicles(container) {
  void container.offsetWidth; // Commit the moved positions first.
  container.classList.remove('vehicles-still');
}

const VEHICLE_ICONS = {
  bus: '<rect x="4" y="3" width="16" height="16" rx="3"/><path d="M4 11h16M8 19v2m8-2v2M8 15h1m6 0h1M8 6h8"/>',
  tram: '<rect x="5" y="5" width="14" height="13" rx="3"/><path d="M5 12h14M9 5l3-3h4M8 18l-2 4m10-4 2 4M9 15h.01M15 15h.01"/>',
};

function vehicleIcon(kind) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${VEHICLE_ICONS[kind]}</svg>`;
}

/* ``target`` names the stop the minutes refer to (the boarding stop by default). */
function vehicleSummary(vehicle) {
  const target = vehicle.target || 'Biniş durağına';
  const lines = [[vehicle.route_code, vehicle.headsign].filter(Boolean).join(' · ')];
  if (vehicle.passed_board) lines.push('Biniş durağını geçti');
  else if (vehicle.minutes_to_board != null) {
    const stops = vehicle.remaining_stops ? ` · ${vehicle.remaining_stops} durak` : '';
    lines.push(vehicle.minutes_to_board < 1 ? `${target} geliyor${stops}` : `${target} ~${vehicle.minutes_to_board} dk${stops}`);
  }
  if (vehicle.next_stop) {
    const minutes = Number(vehicle.minutes_to_next_stop) || 0;
    lines.push(`Sonraki durak: ${vehicle.next_stop}${minutes ? ` · ~${minutes} dk` : ''}`);
  }
  lines.push(`Simülasyon · ortalama ${Math.round(vehicle.speed_kmh)} km/sa`);
  return lines;
}

class VehicleLayer {
  constructor(map, {onUpdate} = {}) {
    this.map = map;
    this.onUpdate = onUpdate;
    this.group = L.layerGroup().addTo(map);
    this.markers = new Map();
    this.query = null;
    const container = map.getContainer();
    // Leaflet repositions markers while zooming; those moves must not glide.
    map.on('zoomstart', () => container.classList.add('vehicles-still'));
    map.on('zoomend', () => settleVehicles(container));
    document.addEventListener('visibilitychange', () => {
      if (!this.query) return;
      if (document.hidden) { clearTimeout(this.timer); this.controller?.abort(); return; }
      this.jump = true; // Vehicles moved far while hidden; do not animate it.
      this.poll();
    });
  }

  /* ``specs`` is the /api/vehicles ``patterns`` parameter. */
  watch(specs) {
    if (!specs) return this.stop();
    if (specs !== this.query) { this.stop(); this.query = specs; }
    this.poll();
  }

  stop() {
    clearTimeout(this.timer);
    this.controller?.abort();
    this.query = null;
    this.group.clearLayers();
    this.markers.clear();
  }

  async poll() {
    clearTimeout(this.timer);
    if (!this.query || document.hidden) return;
    const query = this.query;
    this.controller?.abort();
    const controller = this.controller = new AbortController();
    try {
      const payload = await fetchJSON(`/api/vehicles?patterns=${encodeURIComponent(query)}`, {},
        {timeout: 8000, retries: 1, signal: controller.signal});
      if (query !== this.query) return;
      this.render(payload.vehicles || []);
      this.onUpdate?.(payload.vehicles || []);
    } catch {
      if (controller.signal.aborted || query !== this.query) return;
      this.onUpdate?.(null);
    }
    if (query === this.query) this.timer = setTimeout(() => this.poll(), VEHICLE_POLL_MS);
  }

  render(vehicles) {
    const container = this.map.getContainer();
    if (this.jump) container.classList.add('vehicles-still');
    const seen = new Set();
    for (const vehicle of vehicles) {
      if (!Number.isFinite(vehicle.latitude) || !Number.isFinite(vehicle.longitude)) continue;
      seen.add(vehicle.id);
      const position = [vehicle.latitude, vehicle.longitude];
      const content = document.createElement('div');
      vehicleSummary(vehicle).forEach((text, index) => {
        const line = document.createElement(index ? 'div' : 'strong');
        line.textContent = text;
        content.append(line);
      });
      let marker = this.markers.get(vehicle.id);
      if (marker) {
        marker.getElement()?.classList.toggle('passed', !!vehicle.passed_board);
        marker.setLatLng(position);
        marker.setPopupContent(content);
        continue;
      }
      const kind = vehicle.mode === 'Tramvay' ? 'tram' : 'bus';
      const icon = L.divIcon({className: `vehicle-marker ${kind}${vehicle.passed_board ? ' passed' : ''}`,
        html: `<span>${vehicleIcon(kind)}</span>`, iconSize: [0, 0]});
      marker = L.marker(position, {icon, keyboard: false, alt: `${vehicle.route_code} (simülasyon)`})
        .bindTooltip(String(vehicle.route_code), {direction: 'top', offset: [0, -12]})
        .bindPopup(content).addTo(this.group);
      this.markers.set(vehicle.id, marker);
    }
    for (const [id, marker] of this.markers) {
      if (!seen.has(id)) { this.group.removeLayer(marker); this.markers.delete(id); }
    }
    if (this.jump) {
      this.jump = false;
      settleVehicles(container);
    }
  }
}

if (typeof module !== 'undefined') module.exports = {vehicleSummary, vehicleIcon};
