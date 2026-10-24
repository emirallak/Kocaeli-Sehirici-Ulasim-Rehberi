const descriptions = {
  fastest: 'Tahmini toplam süreye göre sıralandı',
  fewest_transfers: 'Önce aktarmasız, sonra en az aktarmalı',
  minimal_walking: 'Yürüyüş mesafesine güçlü öncelik verildi',
  prefer_tram: 'Tramvay içeren rotalara öncelik verildi',
};

const icons = {
  walk: '<circle cx="13" cy="4" r="2"/><path d="m7 21 3-7 4 3 1 4M6 11l4-4 4 1 3 5h3M10 7l-1 7m5-6-1 6"/>',
  bus: '<rect x="4" y="3" width="16" height="16" rx="3"/><path d="M4 11h16M8 19v2m8-2v2M8 15h1m6 0h1M8 6h8"/>',
  tram: '<rect x="5" y="5" width="14" height="13" rx="3"/><path d="M5 12h14M9 5l3-3h4M8 18l-2 4m10-4 2 4M9 15h.01M15 15h.01"/>',
};

const RECENT_KEY = 'kocaeli-rota:recent';

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function icon(mode) {
  return `<svg class="route-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[mode]}</svg>`;
}

function minutes(value) {
  return `${Number(value) || 0} dk`;
}

function legMode(leg) {
  return leg.is_walking ? 'walk' : leg.mode === 'Tramvay' ? 'tram' : 'bus';
}

function lineBadges(leg, limit = Infinity) {
  const options = leg.line_options?.length ? leg.line_options : [{route_code: leg.route_code, mode: leg.mode}];
  // Keep many interchangeable lines from crowding the summary row.
  const shown = options.length > limit ? options.slice(0, limit - 1) : options;
  const badges = shown.map(option => {
    const mode = option.mode === 'Tramvay' ? 'tram' : 'bus';
    const headsigns = [...new Set((option.patterns || []).flatMap(pattern => pattern.headsigns || []))].join(' / ');
    return `<span class="line-badge ${mode}" title="${escapeHtml([option.mode, headsigns].filter(Boolean).join(' · '))}">${icon(mode)} ${escapeHtml(option.route_code)}</span>`;
  });
  if (shown.length < options.length) {
    const rest = options.slice(shown.length).map(option => option.route_code).join(', ');
    badges.push(`<span class="line-more" title="${escapeHtml(rest)}">+${options.length - shown.length} hat</span>`);
  }
  return badges.join('<span class="line-choice-separator" aria-hidden="true">/</span>');
}

function clock(value) {
  return value
    ? new Intl.DateTimeFormat('tr-TR', {timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit'}).format(new Date(value))
    : '—';
}

function routeCard(route, index) {
  const legs = route.legs || [];
  const rides = legs.filter(leg => !leg.is_walking);
  const transfers = Math.max(0, rides.length - 1);
  const status = !rides.length ? 'Yalnız yürüyüş' : transfers ? `${transfers} aktarma` : 'Doğrudan · aktarmasız';
  const statusClass = !rides.length ? 'walking' : transfers ? '' : 'direct';
  const total = Math.max(1, legs.reduce((sum, leg) => sum + (Number(leg.estimated_duration_minutes) || 0), 0));
  // Proportional bar: each step's share of the trip, walking in grey.
  const bar = legs.map(leg => {
    const share = Math.max(6, (Number(leg.estimated_duration_minutes) || 0) / total * 100);
    return `<span class="trip-bar-part ${legMode(leg)}" style="flex-grow:${share.toFixed(1)}"></span>`;
  }).join('');
  const segments = legs.map(leg => {
    const duration = minutes(leg.estimated_duration_minutes);
    if (leg.is_walking) return `<span class="segment walk" aria-label="Yürüyüş ${duration}">${icon('walk')} ${duration}</span>`;
    return `<span class="segment"><span class="line-choices" aria-label="Bu adımda kullanılabilecek hatlar">${lineBadges(leg, 5)}</span> <span class="segment-time">${duration}</span></span>`;
  }).join('<span class="segment-arrow" aria-hidden="true">›</span>');
  const origin = legs[0]?.board_stop?.name ?? '';
  const destination = legs.at(-1)?.alight_stop?.name ?? '';
  const detailLegs = legs.map(leg => {
    const mode = legMode(leg);
    const title = leg.is_walking
      ? `${Number(leg.walking_metres) || 0} m yürü`
      : `<span class="line-choices">${lineBadges(leg)}</span>`;
    const hops = leg.is_walking ? '' : ` · ${Math.max(1, (leg.alight_index ?? 1) - (leg.board_index ?? 0))} durak`;
    const headsign = !leg.is_walking && leg.headsigns?.length ? `<div class="leg-headsign">Yön: ${escapeHtml(leg.headsigns.join(' / '))}</div>` : '';
    return `<li class="leg ${mode}"><span class="leg-icon">${icon(mode)}</span><div class="leg-body"><div class="leg-title">${title}</div><div class="leg-meta">${escapeHtml(leg.board_stop?.name)} → ${escapeHtml(leg.alight_stop?.name)}</div><div class="leg-meta">${minutes(leg.estimated_duration_minutes)}${hops}</div>${headsign}</div></li>`;
  }).join('');
  const distance = (Number(route.total_distance_metres || 0) / 1000).toLocaleString('tr-TR', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  return `<article class="journey-card ${index === 0 ? 'recommended' : ''}" aria-label="Rota ${index + 1}">
    <div class="journey-top">
      <div>
        <div class="journey-label">${index === 0 ? 'Önerilen rota' : `Alternatif ${index + 1}`}</div>
        <div class="journey-duration">${minutes(route.estimated_duration_minutes).replace(' dk', ' <small>dk</small>')}</div>
      </div>
      <div class="journey-times"><span class="journey-status ${statusClass}">${status}</span><span class="journey-arrival">${clock(route.estimated_departure_at)} → <strong>${clock(route.estimated_arrival_at)}</strong></span></div>
    </div>
    <div class="trip-bar" aria-hidden="true">${bar}</div>
    <div class="journey-segments">${segments}</div>
    <div class="journey-bottom"><span>${escapeHtml(origin)} → ${escapeHtml(destination)}</span><span>${Number(route.walking_metres) || 0} m yürüyüş · ${distance} km</span></div>
    <details class="route-details" data-route="${index}"><summary>Adımlar ve harita</summary><div class="details-grid"><ol class="leg-list">${detailLegs}</ol><div class="map" id="map-${index}" aria-label="Rota ${index + 1} haritası"></div></div></details>
  </article>`;
}

function skeletonCards(count = 3) {
  return Array.from({length: count}, () => `<div class="journey-card skeleton" aria-hidden="true"><span class="sk sk-title"></span><span class="sk sk-bar"></span><span class="sk sk-line"></span><span class="sk sk-line short"></span></div>`).join('');
}

function renderMap(route, index) {
  const element = document.getElementById(`map-${index}`);
  if (!element || element.dataset.ready) return;
  element.dataset.ready = 'true';
  if (!window.L) {
    element.classList.add('map-fallback');
    element.textContent = 'Harita yüklenemedi. Adımları solda görebilirsin.';
    return;
  }
  const map = L.map(element, {scrollWheelZoom: false});
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);
  const bounds = [];
  let rideIndex = 0;
  const colours = ['#2563eb', '#7c3aed', '#ea580c', '#0891b2'];
  for (const leg of route.legs || []) {
    const points = (leg.geometry || [])
      .map(point => [Number(point.latitude), Number(point.longitude)])
      .filter(point => point.every(Number.isFinite));
    if (points.length < 2) continue;
    const colour = leg.is_walking ? '#64748b' : leg.mode === 'Tramvay' ? '#16a34a' : colours[rideIndex++ % colours.length];
    L.polyline(points, {color: colour, weight: leg.is_walking ? 4 : 6, opacity: .9, dashArray: leg.is_walking ? '7 8' : undefined}).addTo(map);
    bounds.push(...points);
  }
  const legs = route.legs || [];
  const marker = (stop, colour) => {
    if (Number.isFinite(stop?.latitude) && Number.isFinite(stop?.longitude)) {
      L.circleMarker([stop.latitude, stop.longitude], {radius: 7, color: '#fff', weight: 3, fillColor: colour, fillOpacity: 1})
        .bindTooltip(escapeHtml(stop.name)).addTo(map);
    }
  };
  marker(legs[0]?.board_stop, '#16a34a');
  marker(legs.at(-1)?.alight_stop, '#dc2626');
  if (bounds.length > 1) map.fitBounds(bounds, {padding: [24, 24], maxZoom: 15});
  else if (bounds.length) map.setView(bounds[0], 14);
  else map.setView([40.76, 29.94], 11);
  setTimeout(() => map.invalidateSize(), 0);
}

function showResults(payload) {
  const section = document.getElementById('results-section');
  const list = document.getElementById('results-list');
  const routes = payload.itineraries || [];
  section.hidden = false;
  if (!routes.length) {
    document.getElementById('results-title').textContent = 'Rota bulunamadı';
    document.getElementById('results-description').textContent = 'Yakın bir durak adıyla yeniden deneyebilirsin.';
    list.innerHTML = '<div class="empty-panel">Bu iki durak arasında en fazla üç aktarmayla uygun bir rota bulunamadı.</div>';
  } else {
    document.getElementById('results-title').textContent = `${payload.origin?.name || ''} → ${payload.destination?.name || ''}`;
    document.getElementById('results-description').textContent = `${routes.length} rota seçeneği · ${descriptions[payload.routing_mode] || ''}`;
    list.innerHTML = routes.slice(0, 3).map(routeCard).join('');
    list.querySelectorAll('details[data-route]').forEach(details => {
      details.addEventListener('toggle', () => {
        if (details.open) renderMap(routes[Number(details.dataset.route)], Number(details.dataset.route));
      });
    });
    const first = list.querySelector('details[data-route="0"]');
    if (first && window.matchMedia?.('(min-width: 900px)').matches) first.open = true;
  }
}

function selectedMode() {
  return document.querySelector('input[name="routing_mode"]:checked')?.value || 'fewest_transfers';
}

let searchController;
async function search(message, {remember} = {}) {
  const section = document.getElementById('results-section');
  const list = document.getElementById('results-list');
  const button = document.getElementById('search-button');
  searchController?.abort();
  const controller = searchController = new AbortController();
  section.hidden = false;
  section.setAttribute('aria-busy', 'true');
  document.getElementById('results-title').textContent = 'Rotalar hesaplanıyor…';
  document.getElementById('results-description').textContent = '';
  list.innerHTML = skeletonCards();
  section.scrollIntoView({behavior: 'smooth', block: 'start'});
  button.disabled = true;
  button.textContent = 'Hesaplanıyor…';
  try {
    const payload = await fetchJSON('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message, limit: 3, routing_mode: selectedMode()}),
    }, {
      timeout: 25000,
      signal: controller.signal,
      onRetry: () => {
        document.getElementById('results-description').textContent = 'Sunucu uyanıyor, yeniden deneniyor…';
      },
    });
    if (controller !== searchController) return;
    showResults(payload);
    if (remember) remember();
  } catch (error) {
    if (controller !== searchController) return;
    document.getElementById('results-title').textContent = 'Rota hesaplanamadı';
    document.getElementById('results-description').textContent = '';
    list.innerHTML = `<div class="empty-panel" role="alert">${escapeHtml(error.message)}</div>`;
  } finally {
    if (controller === searchController) {
      section.setAttribute('aria-busy', 'false');
      button.disabled = false;
      button.innerHTML = 'Rotaları bul <span aria-hidden="true">→</span>';
    }
  }
}

function readRecent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch { return []; }
}

function saveRecent(origin, destination) {
  const entries = [{origin, destination}, ...readRecent()
    .filter(entry => entry.origin !== origin || entry.destination !== destination)].slice(0, 4);
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(entries)); } catch { /* Private mode. */ }
  renderRecent();
}

function renderRecent() {
  const container = document.getElementById('recent-searches');
  const entries = readRecent();
  container.hidden = !entries.length;
  container.replaceChildren();
  if (!entries.length) return;
  const label = document.createElement('span');
  label.className = 'recent-label';
  label.textContent = 'Son aramalar';
  container.append(label);
  for (const entry of entries) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'recent-chip';
    chip.textContent = `${entry.origin} → ${entry.destination}`;
    chip.addEventListener('click', () => {
      document.getElementById('origin').value = entry.origin;
      document.getElementById('destination').value = entry.destination;
      submitRoute();
    });
    container.append(chip);
  }
}

function submitRoute() {
  const origin = document.getElementById('origin').value.trim();
  const destination = document.getElementById('destination').value.trim();
  if (!origin || !destination) return;
  const params = new URLSearchParams({from: origin, to: destination, mode: selectedMode()});
  history.replaceState(null, '', `?${params}`);
  search(`${origin} durağından ${destination} durağına`, {remember: () => saveRecent(origin, destination)});
}

function initRoutePage() {
  document.getElementById('route-form').addEventListener('submit', event => {
    event.preventDefault();
    submitRoute();
  });
  document.getElementById('chat-form').addEventListener('submit', event => {
    event.preventDefault();
    const message = document.getElementById('chat-message').value.trim();
    if (message) search(message);
  });
  document.getElementById('swap-stops').addEventListener('click', () => {
    const origin = document.getElementById('origin');
    const destination = document.getElementById('destination');
    [origin.value, destination.value] = [destination.value, origin.value];
  });
  // Re-run an existing search when the priority changes.
  document.querySelectorAll('input[name="routing_mode"]').forEach(input => {
    input.addEventListener('change', () => {
      if (!document.getElementById('results-section').hidden) submitRoute();
    });
  });
  renderRecent();
  // Shareable links: ?from=…&to=…&mode=…
  const params = new URLSearchParams(location.search);
  const mode = document.querySelector(`input[name="routing_mode"][value="${CSS.escape(params.get('mode') || '')}"]`);
  if (mode) mode.checked = true;
  if (params.get('from') && params.get('to')) {
    document.getElementById('origin').value = params.get('from');
    document.getElementById('destination').value = params.get('to');
    submitRoute();
  }
}

if (typeof window !== 'undefined') initRoutePage();
