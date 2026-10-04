/* Dedicated line browser; it never changes the routing page's state. */
(() => {
  const $ = id => document.getElementById(id);
  const input = $('line-search'), options = $('line-options'), status = $('line-status');
  const days = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar'];
  let catalog, matches = [], active = -1, line, map, layers, controller, requestId = 0, lastId;
  const normalize = value => String(value).toLocaleLowerCase('tr-TR').replace(/ı/g, 'i')
    .normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  function close() {
    options.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  }
  async function loadCatalog() {
    if (catalog) return;
    $('line-search-status').textContent = 'Hatlar yükleniyor…';
    try {
      const response = await fetch('/api/lines');
      if (!response.ok) throw new Error();
      catalog = (await response.json()).lines;
      $('line-search-status').textContent = `${catalog.length} hat · numara veya adla ara`;
      $('line-retry').hidden = true;
      if (document.activeElement === input) renderOptions();
    } catch {
      $('line-search-status').textContent = 'Hat listesi yüklenemedi.';
      $('line-retry').hidden = false;
    }
  }
  function renderOptions() {
    close(); options.replaceChildren();
    if (!catalog) return;
    const query = normalize(input.value.trim());
    matches = catalog.filter(item => normalize(`${item.code} ${item.name}`).includes(query))
      .sort((a, b) => Number(!normalize(a.code).startsWith(query)) - Number(!normalize(b.code).startsWith(query)))
      .slice(0, 40);
    $('line-search-status').textContent = matches.length ? `${matches.length} hat önerisi` : 'Eşleşen hat bulunamadı';
    matches.forEach((item, index) => {
      const option = element('li'); option.id = `line-option-${index}`;
      option.setAttribute('role', 'option'); option.setAttribute('aria-selected', 'false');
      option.append(element('strong', `${item.code} · ${item.mode}`), element('small', item.name));
      option.addEventListener('mousedown', event => event.preventDefault());
      option.addEventListener('click', () => selectLine(item)); options.append(option);
    });
    options.hidden = !matches.length; input.setAttribute('aria-expanded', String(!!matches.length));
  }
  async function selectLine(item) {
    input.value = `${item.code} · ${item.name}`; close();
    lastId = item.id;
    controller?.abort(); controller = new AbortController(); const current = ++requestId;
    $('line-details').hidden = true; status.hidden = false; status.textContent = 'Hat bilgileri yükleniyor…';
    $('line-details').setAttribute('aria-busy', 'true'); $('line-retry').hidden = true;
    try {
      const response = await fetch(`/api/lines/${encodeURIComponent(item.id)}`, {signal: controller.signal});
      if (!response.ok) throw new Error();
      const payload = await response.json(); if (current !== requestId) return;
      line = payload;
      $('line-title').textContent = `${line.code} · ${line.name}`;
      $('line-description').textContent = `${line.mode} · ${line.variants.length} yön / güzergâh seçeneği`;
      $('line-variant').replaceChildren();
      line.variants.forEach((variant, index) => {
        const option = element('option', `${variant.direction_id == null ? 'Güzergâh' : `Yön ${variant.direction_id}`} · ${variant.origin} → ${variant.destination} · ${variant.stops.length} durak (seçenek ${index + 1})`);
        option.value = String(index); $('line-variant').append(option);
      });
      if (!line.variants.length) { status.textContent = 'Bu hat için güzergâh bilgisi bulunamadı.'; return; }
      status.hidden = true; $('line-details').hidden = false; renderVariant();
    } catch (error) {
      if (error.name === 'AbortError' || current !== requestId) return;
      status.textContent = 'Hat bilgileri yüklenemedi. Yeniden deneyebilirsin.'; $('line-retry').hidden = false;
    } finally { if (current === requestId) $('line-details').setAttribute('aria-busy', 'false'); }
  }
  function renderVariant() {
    const variant = line.variants[Number($('line-variant').value)];
    const tables = $('line-timetables'); tables.replaceChildren();
    const direction = (line.direction_timetables || []).find(group => group.variant_ids.includes(variant.id));
    const schedules = direction?.timetables || variant.timetables;
    const conditions = new Map((line.conditions || []).map((condition, index) => [condition.id,
      {...condition, ...LineDisplay.conditionStyle(index)}]));
    const usedConditions = new Set();
    const categories = [
      {name: 'Hafta İçi', days: [0, 1, 2, 3, 4]},
      {name: 'Cumartesi', days: [5]},
      {name: 'Pazar', days: [6]},
    ];
    for (const category of categories) {
      const section = element('section', undefined, 'line-schedule');
      section.append(element('h4', category.name));
      const matching = schedules.filter(table => table.operating_days.some(day => category.days.includes(day)));
      if (!matching.length) section.append(element('p', 'Bu gün için veride sefer tarifesi bulunmuyor.', 'line-note'));
      for (const table of matching) {
        const actualDays = table.operating_days.filter(day => category.days.includes(day));
        if (actualDays.length !== category.days.length) section.append(element('p', actualDays.map(day => days[day]).join(' · '), 'line-note'));
        const format = value => value ? new Intl.DateTimeFormat('tr-TR').format(new Date(`${value}T12:00:00+03:00`)) : 'Belirtilmemiş';
        section.append(element('p', `Tarife geçerliliği: ${format(table.start_date)} – ${format(table.end_date)}`, 'line-note'));
        const times = element('div', undefined, 'line-times');
        const departures = table.trips?.length ? table.trips : table.departures.map(time => ({time}));
        departures.forEach(trip => {
          const display = LineDisplay.departure(trip.time);
          const condition = conditions.get(trip.condition_id);
          const entry = element(condition ? 'button' : 'span', display.label, 'trip-time');
          const description = [display.label];
          if (display.dayOffset) description.push(`Tarife gününden ${display.dayOffset} gün sonra`);
          if (condition) {
            usedConditions.add(condition.id);
            entry.type = 'button';
            entry.style.backgroundColor = condition.background;
            entry.style.color = condition.foreground;
            entry.append(element('sup', condition.number, 'trip-key'));
            description.push(`${condition.number}. ${condition.explanation}`, 'Seferin güzergâhını haritada göster');
            entry.setAttribute('aria-describedby', `legend-${condition.id}`);
            entry.addEventListener('click', () => {
              const index = line.variants.findIndex(path => path.id === trip.variant_id);
              if (index < 0) return;
              $('line-variant').value = String(index);
              renderVariant();
              $('line-map').scrollIntoView({behavior: 'smooth', block: 'nearest'});
            });
          }
          entry.title = description.join(' · ');
          entry.setAttribute('aria-label', entry.title);
          times.append(entry);
        });
        section.append(times);
        if (!table.departures.length) section.append(element('p', 'Bu güzergâh için kalkış saatleri veride bulunmuyor.', 'line-note'));
      }
      tables.append(section);
    }
    const legend = $('line-legend'); legend.replaceChildren();
    legend.hidden = usedConditions.size === 0;
    if (usedConditions.size) {
      legend.append(element('h4', 'Açıklama'));
      const list = element('ul', undefined, 'trip-legend-list');
      for (const condition of conditions.values()) {
        if (!usedConditions.has(condition.id)) continue;
        const item = element('li'); item.id = `legend-${condition.id}`;
        const key = element('span', condition.number, 'trip-legend-key');
        key.style.backgroundColor = condition.background;
        key.style.color = condition.foreground;
        key.setAttribute('aria-hidden', 'true');
        item.append(key, element('span', condition.explanation)); list.append(item);
      }
      legend.append(list, element('p', 'Numaralı saatlere dokunarak o seferin duraklarını ve güzergâhını görüntüle.', 'line-note'));
    }
    $('line-stop-heading').textContent = `Duraklar · ${variant.stops.length}`;
    $('line-stops').replaceChildren();
    variant.stops.forEach((stop, index) => {
      const item = element('li');
      const button = element('button', stop.name); button.type = 'button';
      button.addEventListener('click', () => {
        if (!map || stop.latitude == null || stop.longitude == null) return;
        map.setView([stop.latitude, stop.longitude], 16);
        const popup = stopPopup(stop, index);
        L.popup().setLatLng([stop.latitude, stop.longitude]).setContent(popup).openOn(map);
        $('line-map').scrollIntoView({behavior: 'smooth', block: 'nearest'});
      });
      const row = element('div', undefined, 'line-stop-row');
      row.append(button);
      LineDisplay.restrictions(stop).forEach(label => row.append(element('span', label, 'stop-restriction')));
      item.append(row, element('small', [stop.code, stop.district].filter(Boolean).join(' · ')));
      $('line-stops').append(item);
    });
    renderMap(variant);
  }
  function stopPopup(stop, index) {
    return element('span', [`${index + 1}. ${stop.name}`, ...LineDisplay.restrictions(stop)].join(' · '));
  }
  function renderMap(variant) {
    $('line-map-note').textContent = variant.geometry_source === 'shape'
      ? 'Tam güzergâh ve sıralı duraklar. Durak adına dokunarak haritada bul.'
      : 'Güzergâh çizgisi bulunmuyor; duraklar arası bağlantı yaklaşık olarak gösterilir.';
    if (!window.L) { $('line-map').textContent = 'Harita yüklenemedi. Duraklar ve saatler yukarıda görüntülenebilir.'; return; }
    if (!map) {
      map = L.map($('line-map'), {scrollWheelZoom: false});
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
      layers = L.layerGroup().addTo(map);
    }
    map.closePopup(); layers.clearLayers();
    const valid = point => point.latitude != null && point.longitude != null && Number.isFinite(point.latitude) && Number.isFinite(point.longitude);
    const points = variant.geometry.filter(valid).map(point => [point.latitude, point.longitude]);
    if (points.length > 1) L.polyline(points, {color: line.mode === 'Tramvay' ? '#15934b' : '#2563eb', weight: 5}).addTo(layers);
    const bounds = [...points];
    variant.stops.forEach((stop, index) => {
      if (!valid(stop)) return;
      const point = [stop.latitude, stop.longitude]; bounds.push(point);
      L.circleMarker(point, {radius: 6, color: '#163d7c', fillColor: '#fff', fillOpacity: 1, weight: 2})
        .bindPopup(stopPopup(stop, index)).addTo(layers);
    });
    map.invalidateSize();
    if (bounds.length) map.fitBounds(bounds, {padding: [24, 24], maxZoom: 15});
    else { map.setView([40.76, 29.94], 11); $('line-map-note').textContent = 'Bu güzergâh için koordinatlar bulunmuyor.'; }
  }
  input.addEventListener('focus', () => { if (catalog) renderOptions(); else loadCatalog(); });
  input.addEventListener('input', renderOptions);
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') { close(); return; }
    if (event.key === 'Enter' && !options.hidden && active >= 0) { event.preventDefault(); selectLine(matches[active]); return; }
    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
    event.preventDefault(); if (options.hidden) renderOptions(); if (!matches.length) return;
    active = (active + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length;
    [...options.children].forEach((option, index) => option.setAttribute('aria-selected', String(index === active)));
    input.setAttribute('aria-activedescendant', `line-option-${active}`); options.children[active].scrollIntoView({block: 'nearest'});
  });
  input.addEventListener('blur', close);
  $('line-variant').addEventListener('change', renderVariant);
  $('line-retry').addEventListener('click', () => lastId ? selectLine(catalog.find(item => item.id === lastId)) : loadCatalog());
  loadCatalog();
})();
