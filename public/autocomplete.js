/* The active-stop catalog is shared by both fields and fetched only once. */
function normalizeStopText(value) {
  return value.toLocaleLowerCase('tr-TR')
    .replace(/ı/g, 'i').replace(/ğ/g, 'g').replace(/ş/g, 's')
    .normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, ' ').trim().replace(/\s+/g, ' ');
}

function filterStops(catalog, query, limit = 12) {
  const text = normalizeStopText(query);
  if (!text) return [];
  const matches = catalog.filter(stop => stop.key.includes(text));
  // The catalog is alphabetically sorted; prefix matches lead substring matches.
  return [...matches.filter(stop => stop.key.startsWith(text)),
    ...matches.filter(stop => !stop.key.startsWith(text))].slice(0, limit);
}

let stopCatalogPromise;
function loadStopCatalog() {
  if (!stopCatalogPromise) {
    stopCatalogPromise = fetch('/api/stops').then(async response => {
      if (!response.ok) throw new Error('Durak listesi yüklenemedi');
      const payload = await response.json();
      return payload.stops.map(stop => ({...stop, key: normalizeStopText(stop.name)}));
    }).catch(error => {
      stopCatalogPromise = undefined; // A later focus can retry a failed request.
      throw error;
    });
  }
  return stopCatalogPromise;
}

function attachStopAutocomplete(id) {
  const input = document.getElementById(id);
  const list = document.getElementById(`${id}-options`);
  const status = document.getElementById(`${id}-status`);
  const field = input.closest('.stop-field');
  let catalog, matches = [], active = -1, dismissed = false;
  let loading;

  function close(dismiss = false) {
    if (dismiss) dismissed = true;
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  }

  function select(index) {
    const stop = matches[index];
    if (!stop) return;
    input.value = stop.name;
    status.textContent = `${stop.name} seçildi`;
    close(true);
    input.focus();
  }

  function highlight(index) {
    active = index;
    Array.from(list.children).forEach((option, i) => {
      option.setAttribute('aria-selected', String(i === active));
    });
    if (active < 0) input.removeAttribute('aria-activedescendant');
    else {
      input.setAttribute('aria-activedescendant', `${id}-option-${active}`);
      list.children[active].scrollIntoView({block: 'nearest'});
    }
  }

  function render() {
    close();
    list.replaceChildren();
    if (dismissed || !input.value.trim() || document.activeElement !== input) {
      status.textContent = '';
      return;
    }
    if (!catalog) return;
    matches = filterStops(catalog, input.value);
    status.textContent = matches.length ? `${matches.length} durak önerisi` : 'Eşleşen durak bulunamadı';
    if (!matches.length) return;
    matches.forEach((stop, index) => {
      const option = document.createElement('li');
      option.id = `${id}-option-${index}`;
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', 'false');
      const name = document.createElement('span');
      name.textContent = stop.name;
      option.append(name);
      if (stop.district) {
        const district = document.createElement('small');
        district.textContent = stop.district;
        option.append(district);
      }
      // Keep focus in the combobox when selecting with mouse or touch.
      option.addEventListener('pointerdown', event => event.preventDefault());
      option.addEventListener('click', () => select(index));
      list.append(option);
    });
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }

  async function ensureCatalog() {
    if (catalog || loading) return;
    status.textContent = 'Duraklar yükleniyor…';
    loading = true;
    try {
      catalog = await loadStopCatalog();
      render(); // Read the latest text; never render a stale typed query.
    } catch {
      if (document.activeElement === input) {
        status.textContent = 'Durak önerileri yüklenemedi. Durak adını yazarak arayabilirsin.';
      }
    } finally {
      loading = false;
    }
  }

  input.addEventListener('input', () => {
    dismissed = false;
    render();
    if (input.value.trim()) ensureCatalog();
  });
  input.addEventListener('focus', () => { dismissed = false; render(); ensureCatalog(); });
  input.addEventListener('blur', () => { close(true); status.textContent = ''; });
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') { close(true); return; }
    if (event.key === 'Tab') { close(true); return; }
    if (event.key === 'Enter' && !list.hidden && active >= 0) {
      event.preventDefault();
      select(active);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      dismissed = false;
      if (list.hidden) render();
      if (!matches.length || list.hidden) return;
      event.preventDefault();
      highlight(event.key === 'ArrowDown' ? (active + 1) % matches.length
        : (active <= 0 ? matches.length - 1 : active - 1));
    }
  });
  document.addEventListener('pointerdown', event => {
    if (!field.contains(event.target)) close(true);
  });
}

if (typeof document !== 'undefined') {
  loadStopCatalog().catch(() => {});
  attachStopAutocomplete('origin');
  attachStopAutocomplete('destination');
}
if (typeof module !== 'undefined') module.exports = {normalizeStopText, filterStops};
