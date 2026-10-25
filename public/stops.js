/* Stop board: simulated arrivals at every platform of one stop name. */
const STOP_POLL_MS = 10000;

function stopClock(value) {
  return value
    ? new Intl.DateTimeFormat('tr-TR', {timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit'}).format(new Date(value))
    : '—';
}

/* The big minute label and the detail line of one arrival row. */
function arrivalParts(arrival) {
  const when = arrival.minutes < 1 ? 'Geliyor' : `${arrival.minutes} dk`;
  const detail = arrival.remaining_stops != null
    ? `${arrival.remaining_stops} durak uzakta · ${stopClock(arrival.at)}`
    : `İlk duraktan ${stopClock(arrival.departs_at)} kalkış · ${stopClock(arrival.at)}`;
  return {when, detail};
}

/* Vehicles for the map: one marker per vehicle, at its soonest arrival. */
function nearbyVehicles(arrivals) {
  const vehicles = new Map();
  for (const arrival of arrivals) {
    if (!arrival.vehicle || vehicles.has(arrival.vehicle.id)) continue;
    vehicles.set(arrival.vehicle.id, {
      ...arrival.vehicle, route_code: arrival.route_code, mode: arrival.mode,
      headsign: arrival.destination, target: 'Durağa',
      minutes_to_board: arrival.minutes, remaining_stops: arrival.remaining_stops,
    });
  }
  return [...vehicles.values()];
}

function initStopPage() {
  const $ = id => document.getElementById(id);
  const input = $('stop-search'), status = $('stop-status');
  let current = null, timer, controller, map, platforms, vehicles, failures = 0;
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const badge = (code, mode) => {
    const kind = mode === 'Tramvay' ? 'tram' : 'bus';
    const node = element('span', undefined, `line-badge ${kind}`);
    node.innerHTML = vehicleIcon(kind);
    node.append(` ${code}`);
    return node;
  };

  function stopPolling() {
    clearTimeout(timer);
    controller?.abort();
  }

  function show(name) {
    if (!name) return;
    stopPolling();
    current = {name, fresh: true};
    failures = 0;
    history.replaceState(null, '', `?${new URLSearchParams({name})}`);
    $('stop-details').hidden = true;
    $('stop-retry').hidden = true;
    status.hidden = false;
    status.textContent = 'Durak bilgileri yükleniyor…';
    poll();
  }

  async function poll() {
    clearTimeout(timer);
    if (!current || document.hidden) return;
    const request = current;
    controller?.abort();
    const ownController = controller = new AbortController();
    try {
      const payload = await fetchJSON(`/api/stop-arrivals?name=${encodeURIComponent(request.name)}`, {}, {
        retries: request.fresh ? 3 : 1, signal: ownController.signal,
        onRetry: () => { if (request.fresh) status.textContent = 'Sunucu uyanıyor, yeniden deneniyor…'; },
      });
      if (request !== current) return;
      failures = 0;
      render(payload, request.fresh);
      request.fresh = false;
    } catch (error) {
      if (ownController.signal.aborted || request !== current) return;
      if (request.fresh) {
        status.textContent = error.status === 404
          ? 'Bu adla bir durak bulunamadı. Önerilerden birini seç.'
          : 'Durak bilgileri yüklenemedi. Yeniden deneyebilirsin.';
        $('stop-retry').hidden = error.status === 404;
        return;
      }
      // Keep the last board on a transient failure, but say it is stale.
      if (++failures === 1) $('stop-map-note').textContent = 'Güncelleme alınamadı; son bilgiler gösteriliyor.';
    }
    if (request === current) timer = setTimeout(poll, STOP_POLL_MS);
  }

  function render(payload, fresh) {
    const {stop, lines, arrivals} = payload;
    status.hidden = true;
    $('stop-details').hidden = false;
    $('stop-title').textContent = stop.name;
    $('stop-description').textContent = `${stop.platforms.length} peron · ${lines.length} hat`;
    $('stop-lines').replaceChildren(...lines.map(line => badge(line.route_code, line.mode)));

    const list = $('stop-arrivals');
    list.replaceChildren();
    if (!arrivals.length) list.append(element('li', 'Önümüzdeki 60 dakikada bu duraktan geçecek araç beklenmiyor.', 'arrival-empty'));
    for (const arrival of arrivals) {
      const {when, detail} = arrivalParts(arrival);
      const row = element(arrival.vehicle ? 'button' : 'div', undefined, 'arrival-row');
      if (arrival.vehicle) {
        row.type = 'button';
        row.title = 'Aracı haritada göster';
        row.addEventListener('click', () => focusVehicle(arrival.vehicle.id));
      }
      const body = element('span', undefined, 'arrival-body');
      body.append(element('strong', `→ ${arrival.destination}`), element('small', detail));
      const minutes = element('span', when, `arrival-minutes${arrival.minutes < 1 ? ' now' : ''}`);
      row.append(badge(arrival.route_code, arrival.mode), body, minutes);
      const item = element('li');
      item.append(row);
      list.append(item);
    }
    renderMap(stop, nearbyVehicles(arrivals), fresh);
  }

  function renderMap(stop, nearby, fresh) {
    if (!window.L) { $('stop-map').textContent = 'Harita yüklenemedi. Yaklaşan araçlar listede görüntülenebilir.'; return; }
    if (!map) {
      map = L.map($('stop-map'), {scrollWheelZoom: false});
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
      platforms = L.layerGroup().addTo(map);
      vehicles = new VehicleLayer(map);
    }
    vehicles.render(nearby);
    $('stop-map-note').textContent = nearby.length
      ? `10 dakika içinde bu durağa gelecek ${nearby.length} araç gösteriliyor. Araca dokunarak kalan durak ve süreyi gör.`
      : 'Önümüzdeki 10 dakikada yaklaşan araç yok.';
    if (!fresh) return;
    platforms.clearLayers();
    const bounds = [];
    for (const platform of stop.platforms) {
      if (!Number.isFinite(platform.latitude) || !Number.isFinite(platform.longitude)) continue;
      const point = [platform.latitude, platform.longitude];
      bounds.push(point);
      L.circleMarker(point, {radius: 8, color: '#fff', weight: 3, fillColor: '#dc2626', fillOpacity: 1})
        .bindTooltip([stop.name, platform.code].filter(Boolean).join(' · ')).addTo(platforms);
    }
    bounds.push(...nearby.map(vehicle => [vehicle.latitude, vehicle.longitude]));
    map.invalidateSize();
    if (bounds.length) map.fitBounds(bounds, {padding: [32, 32], maxZoom: 16});
    else map.setView([40.76, 29.94], 11);
  }

  function focusVehicle(id) {
    const marker = vehicles?.markers.get(id);
    if (!marker) return;
    map.panTo(marker.getLatLng());
    marker.openPopup();
    $('stop-map').scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  attachStopAutocomplete('stop-search', {onSelect: stop => show(stop.name)});
  $('stop-form').addEventListener('submit', event => {
    event.preventDefault();
    show(input.value.trim());
  });
  $('stop-retry').addEventListener('click', () => current && show(current.name));
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { stopPolling(); return; }
    if (vehicles) vehicles.jump = true; // Vehicles moved far while hidden.
    poll();
  });
  const name = new URLSearchParams(location.search).get('name');
  if (name) { input.value = name; show(name); }
}

if (typeof window !== 'undefined') initStopPage();
if (typeof module !== 'undefined') module.exports = {arrivalParts, nearbyVehicles};
