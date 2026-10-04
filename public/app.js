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

function lineBadges(leg) {
  const options = leg.line_options?.length ? leg.line_options : [{route_code: leg.route_code, mode: leg.mode}];
  return options.map(option => {
    const mode = option.mode === 'Tramvay' ? 'tram' : 'bus';
    const headsigns = [...new Set((option.patterns || []).flatMap(pattern => pattern.headsigns || []))].join(' / ');
    return `<span class="line-badge ${mode}" title="${escapeHtml([option.mode, headsigns].filter(Boolean).join(' · '))}">${icon(mode)} ${escapeHtml(option.route_code)}</span>`;
  }).join('<span class="line-choice-separator" aria-hidden="true">/</span>');
}

function routeCard(route, index) {
  const legs = route.legs || [];
  const rides = legs.filter(leg => !leg.is_walking);
  const transfers = Math.max(0, rides.length - 1);
  const status = !rides.length ? 'Yalnız yürüyüş' : transfers ? `${transfers} aktarma` : 'Doğrudan · aktarmasız';
  const statusClass = !rides.length ? 'walking' : transfers ? '' : 'direct';
  const arrival = route.estimated_arrival_at
    ? new Intl.DateTimeFormat('tr-TR', {timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit'}).format(new Date(route.estimated_arrival_at))
    : '—';
  const segments = legs.map(leg => {
    const duration = minutes(leg.estimated_duration_minutes);
    if (leg.is_walking) return `<span class="segment" aria-label="Yürüyüş">${icon('walk')} ${duration}</span>`;
    return `<span class="segment"><span class="line-choices" aria-label="Bu adımda kullanılabilecek hatlar">${lineBadges(leg)}</span> ${duration}</span>`;
  }).join('<span class="segment-arrow" aria-hidden="true">›</span>');
  const origin = legs[0]?.board_stop?.name ?? '';
  const destination = legs.at(-1)?.alight_stop?.name ?? '';
  const transferStops = rides.slice(1).map(leg => `<br>Aktarma: ${escapeHtml(leg.board_stop?.name)}`).join('');
  const detailLegs = legs.map(leg => {
    const mode = leg.is_walking ? 'walk' : leg.mode === 'Tramvay' ? 'tram' : 'bus';
    const title = leg.is_walking ? `${Number(leg.walking_metres) || 0} m yürüyüş` : `<span class="line-choices">${lineBadges(leg)}</span>`;
    return `<div class="leg"><span class="leg-icon">${icon(mode)}</span><div><div class="leg-title">${title}</div><div class="leg-meta">${escapeHtml(leg.board_stop?.name)} → ${escapeHtml(leg.alight_stop?.name)}<br>${minutes(leg.estimated_duration_minutes)}</div></div></div>`;
  }).join('');
  const distance = (Number(route.total_distance_metres || 0) / 1000).toLocaleString('tr-TR', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  return `<article class="journey-card ${index === 0 ? 'recommended' : ''}" aria-label="Rota ${index + 1}">
    <div class="journey-label">${index === 0 ? 'ÖNERİLEN ROTA' : `ALTERNATİF ${index + 1}`}</div>
    <div class="journey-top"><div><div class="journey-duration">${minutes(route.estimated_duration_minutes).replace(' dk', ' <small>dk</small>')}</div><div class="journey-arrival">Tahmini varış ${arrival}</div></div><span class="journey-status ${statusClass}">${status}</span></div>
    <div class="journey-segments">${segments}</div>
    <div class="journey-stops">Başlangıç: ${escapeHtml(origin)}${transferStops}<br>Varış: ${escapeHtml(destination)}</div>
    <div class="journey-bottom"><span>${Number(route.walking_metres) || 0} m yürüyüş · ${distance} km</span><span>Tahmini süre · bekleme dahil</span></div>
    <details class="route-details" data-route="${index}"><summary>Duraklar ve harita</summary><div class="details-grid"><div>${detailLegs}</div><div class="map" id="map-${index}" aria-label="Rota ${index + 1} haritası"></div></div></details>
  </article>`;
}

function renderMap(route, index) {
  const element = document.getElementById(`map-${index}`);
  if (!element || element.dataset.ready) return;
  element.dataset.ready = 'true';
  if (!window.L) {
    element.classList.add('map-fallback');
    element.textContent = 'Harita yüklenemedi. Durak ayrıntılarını solda görebilirsin.';
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
    list.innerHTML = '<div class="empty-panel">Bu iki durak arasında uygun bir rota bulunamadı.</div>';
  } else {
    document.getElementById('results-title').textContent = `${payload.origin?.name || ''} → ${payload.destination?.name || ''}`;
    document.getElementById('results-description').textContent = `${routes.length} rota seçeneği · ${descriptions[payload.routing_mode] || ''}`;
    list.innerHTML = routes.slice(0, 3).map(routeCard).join('');
    list.querySelectorAll('details[data-route]').forEach(details => {
      details.addEventListener('toggle', () => {
        if (details.open) renderMap(routes[Number(details.dataset.route)], Number(details.dataset.route));
      });
    });
  }
  section.scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function search(message) {
  const section = document.getElementById('results-section');
  const button = document.getElementById('search-button');
  section.setAttribute('aria-busy', 'true');
  button.disabled = true;
  button.textContent = 'Rotalar hesaplanıyor…';
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message, limit: 3, routing_mode: document.getElementById('routing-mode').value}),
    });
    const payload = await response.json();
    if (!response.ok) {
      const detail = payload.detail;
      throw new Error(typeof detail === 'string' ? detail : detail?.message || `Rota servisi hata verdi (${response.status}).`);
    }
    showResults(payload);
  } catch (error) {
    section.hidden = false;
    document.getElementById('results-title').textContent = 'Rota hesaplanamadı';
    document.getElementById('results-description').textContent = '';
    document.getElementById('results-list').innerHTML = `<div class="empty-panel" role="alert">${escapeHtml(error.message)}</div>`;
  } finally {
    section.setAttribute('aria-busy', 'false');
    button.disabled = false;
    button.innerHTML = 'Rotaları bul <span aria-hidden="true">→</span>';
  }
}

document.getElementById('route-form').addEventListener('submit', event => {
  event.preventDefault();
  const origin = document.getElementById('origin').value.trim();
  const destination = document.getElementById('destination').value.trim();
  if (origin && destination) search(`${origin} durağından ${destination} durağına`);
});
document.getElementById('chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const message = document.getElementById('chat-message').value.trim();
  if (message) search(message);
});
