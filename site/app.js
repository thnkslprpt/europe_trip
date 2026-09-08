(() => {
  'use strict';

  const state = {
    data: null,
    photos: { version: 1, dates: {} },
    selectedDate: null,
    rawVisible: false,
    playTimer: null,
    playbackIndex: 0,
    photoFilmstripSyncing: false,
    photoFilmstripScrollRaf: 0,
  };

  const els = {
    sidebar: document.getElementById('sidebar'),
    dayList: document.getElementById('dayList'),
    tripMeta: document.getElementById('tripMeta'),
    selectedSummary: document.getElementById('selectedSummary'),
    currentTitle: document.getElementById('currentTitle'),
    overviewButton: document.getElementById('overviewButton'),
    previousDay: document.getElementById('previousDay'),
    nextDay: document.getElementById('nextDay'),
    rawToggle: document.getElementById('rawToggle'),
    photosButton: document.getElementById('photosButton'),
    photoFilmstrip: document.getElementById('photoFilmstrip'),
    photoFilmstripTrack: document.getElementById('photoFilmstripTrack'),
    photoFilmstripLabel: document.getElementById('photoFilmstripLabel'),
    photoFilmstripPrev: document.getElementById('photoFilmstripPrev'),
    photoFilmstripNext: document.getElementById('photoFilmstripNext'),
    photoFilmstripViewAll: document.getElementById('photoFilmstripViewAll'),
    timelinePlayer: document.getElementById('timelinePlayer'),
    timelineSlider: document.getElementById('timelineSlider'),
    timelineTime: document.getElementById('timelineTime'),
    timelineDate: document.getElementById('timelineDate'),
    timelineCountry: document.getElementById('timelineCountry'),
    playButton: document.getElementById('playButton'),
    overviewLegend: document.getElementById('overviewLegend'),
    mapNotice: document.getElementById('mapNotice'),
    photoDialog: document.getElementById('photoDialog'),
    photoDialogTitle: document.getElementById('photoDialogTitle'),
    photoGrid: document.getElementById('photoGrid'),
    photoEmpty: document.getElementById('photoEmpty'),
    photoEmptyGoogle: document.getElementById('photoEmptyGoogle'),
    closePhotoDialog: document.getElementById('closePhotoDialog'),
    openSidebar: document.getElementById('openSidebar'),
    closeSidebar: document.getElementById('closeSidebar'),
  };

  const map = L.map('map', { zoomControl: false, preferCanvas: true });
  L.control.zoom({ position: 'bottomright' }).addTo(map);
  // Standard OpenStreetMap tiles do not require an API key. Keep the required
  // attribution in the map corner, but avoid provider-specific key watermarks.
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);

  const backgroundLayer = L.layerGroup().addTo(map);
  const routeLayer = L.layerGroup().addTo(map);
  const markerLayer = L.layerGroup().addTo(map);
  const rawLayer = L.layerGroup().addTo(map);
  const playbackLayer = L.layerGroup().addTo(map);

  function basePath(path) {
    return new URL(path, document.baseURI).toString();
  }

  function formatDate(date, options = {}) {
    const d = new Date(`${date}T12:00:00Z`);
    return new Intl.DateTimeFormat('en-GB', {
      weekday: options.weekday ? 'short' : undefined,
      day: 'numeric',
      month: options.longMonth ? 'long' : 'short',
      year: options.year ? 'numeric' : undefined,
      timeZone: 'UTC',
    }).format(d);
  }

  function formatLongDate(date) {
    const d = new Date(`${date}T12:00:00Z`);
    return new Intl.DateTimeFormat('en-GB', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'
    }).format(d);
  }

  function formatKm(value) {
    if (!Number.isFinite(value)) return '0 km';
    if (value < 10) return `${value.toFixed(1)} km`;
    return `${Math.round(value)} km`;
  }

  function formatMinutes(minutes) {
    const value = Math.max(0, Math.round(minutes || 0));
    if (value < 60) return `${value} min`;
    const h = Math.floor(value / 60);
    const m = value % 60;
    return m ? `${h}h ${m}m` : `${h}h`;
  }

  function dayColor(index, count) {
    const denom = Math.max(1, count - 1);
    const hue = 220 - (index / denom) * 205;
    return `hsl(${hue.toFixed(0)} 72% 48%)`;
  }

  const modeIcon = {
    walking: 'W', car: 'C', riding: 'R', bus: 'B', train: 'T', tram: 'Tr', subway: 'M', flight: 'F', other: '•'
  };

  function flagEmoji(code) {
    if (!code || code.length !== 2) return '🌍';
    return [...code.toUpperCase()].map(char => String.fromCodePoint(127397 + char.charCodeAt(0))).join('');
  }

  function countriesText(countries, separator = ' · ') {
    if (!countries?.length) return 'Country unavailable';
    return countries.map(country => `${flagEmoji(country.code)} ${country.name}`).join(separator);
  }

  function countryChips(countries) {
    if (!countries?.length) return '';
    return `<div class="country-chip-row">${countries.map(country =>
      `<span class="country-chip"><span class="country-flag">${flagEmoji(country.code)}</span>${country.name}</span>`
    ).join('')}</div>`;
  }

  function activityCountryText(activity) {
    const start = activity.startCountry;
    const end = activity.endCountry;
    const startCode = activity.startCountryCode;
    const endCode = activity.endCountryCode;
    if (!start && !end) return '';
    if (!end || start === end) return `${flagEmoji(startCode || endCode)} ${start || end}`;
    return `${flagEmoji(startCode)} ${start} → ${flagEmoji(endCode)} ${end}`;
  }

  function createCountryTransitionIcon(country) {
    return L.divIcon({
      className: 'country-transition-icon',
      html: `<div class="country-transition-dot" title="${country.country}">${flagEmoji(country.code)}</div>`,
      iconSize: [30, 30], iconAnchor: [15, 15], popupAnchor: [0, -14],
    });
  }

  function selectedDay() {
    return state.selectedDate ? state.data.days.find(d => d.date === state.selectedDate) : null;
  }

  function photoItemsFor(date) {
    return state.photos?.dates?.[date] || [];
  }

  function photoTimeLabel(item) {
    const match = String(item?.src || '').match(/\d{4}-\d{2}-\d{2}_(\d{2})(\d{2})(\d{2})_/);
    return match ? `${match[1]}:${match[2]}` : '';
  }

  function renderPhotoFilmstrip(day) {
    if (!els.photoFilmstrip || !els.photoFilmstripTrack) return;

    const items = day ? photoItemsFor(day.date) : [];
    if (!day || !items.length) {
      els.photoFilmstrip.hidden = true;
      els.photoFilmstripTrack.innerHTML = '';
      return;
    }

    els.photoFilmstrip.hidden = false;
    // If a rare day has no playable GPS timeline, let the photo strip use the bottom slot.
    els.photoFilmstrip.classList.toggle('timeline-hidden', els.timelinePlayer.hidden);
    els.photoFilmstripLabel.textContent = `${items.length} ${items.length === 1 ? 'photo' : 'photos'} · ${formatDate(day.date, { weekday: true })}`;
    els.photoFilmstripTrack.innerHTML = '';

    items.forEach((item, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'photo-filmstrip-item';
      button.setAttribute('aria-label', `Open photo ${index + 1} of ${items.length}`);

      if (item.type === 'video') {
        const video = document.createElement('video');
        video.src = item.src;
        video.muted = true;
        video.preload = 'metadata';
        button.appendChild(video);
        const badge = document.createElement('span');
        badge.className = 'photo-filmstrip-video-badge';
        badge.textContent = '▶';
        button.appendChild(badge);
      } else {
        const img = document.createElement('img');
        img.src = item.src;
        img.alt = item.name || `Trip photo ${index + 1}`;
        img.loading = index < 8 ? 'eager' : 'lazy';
        img.decoding = 'async';
        button.appendChild(img);
      }

      const time = photoTimeLabel(item);
      if (time) {
        const timeBadge = document.createElement('span');
        timeBadge.className = 'photo-filmstrip-time';
        timeBadge.textContent = time;
        button.appendChild(timeBadge);
      }

      // The photos are visible without any click. Clicking a thumbnail remains a
      // convenient way to open the existing full gallery.
      button.addEventListener('click', openPhotoDialog);
      els.photoFilmstripTrack.appendChild(button);
    });

    // Each day starts at the first photo rather than inheriting the previous day's scroll.
    els.photoFilmstripTrack.scrollLeft = 0;
    window.requestAnimationFrame(updatePhotoFilmstripButtons);
  }

  function photoFilmstripStep() {
    if (!els.photoFilmstripTrack) return 360;
    return Math.max(260, Math.round(els.photoFilmstripTrack.clientWidth * 0.72));
  }

  function updatePhotoFilmstripButtons() {
    if (!els.photoFilmstripTrack || els.photoFilmstrip.hidden) return;
    const track = els.photoFilmstripTrack;
    const max = Math.max(0, track.scrollWidth - track.clientWidth);
    els.photoFilmstripPrev.disabled = track.scrollLeft <= 3;
    els.photoFilmstripNext.disabled = track.scrollLeft >= max - 3;
  }

  function photoFilmstripMaxScroll() {
    if (!els.photoFilmstripTrack) return 0;
    return Math.max(0, els.photoFilmstripTrack.scrollWidth - els.photoFilmstripTrack.clientWidth);
  }

  function syncPhotoFilmstripToTimeline(value) {
    if (!els.photoFilmstripTrack || els.photoFilmstrip.hidden) return;
    const maxScroll = photoFilmstripMaxScroll();
    if (maxScroll <= 0) return;

    // Deliberately map by relative position rather than photo timestamps:
    // first photo = start of day, last photo = end of day.
    const ratio = Math.max(0, Math.min(1, Number(value) / 1000));
    state.photoFilmstripSyncing = true;
    els.photoFilmstripTrack.scrollLeft = maxScroll * ratio;
    window.requestAnimationFrame(() => {
      state.photoFilmstripSyncing = false;
    });
  }

  function syncTimelineToPhotoFilmstrip() {
    if (state.photoFilmstripSyncing) return;
    const day = selectedDay();
    if (!day || day.rawPoints.length < 2 || els.photoFilmstrip.hidden) return;

    const maxScroll = photoFilmstripMaxScroll();
    if (maxScroll <= 0) return;

    const ratio = Math.max(0, Math.min(1, els.photoFilmstripTrack.scrollLeft / maxScroll));
    const value = Math.round(ratio * 1000);
    stopPlayback();
    els.timelineSlider.value = String(value);
    updatePlaybackMarker(value, { syncPhotos: false });
  }

  function googlePhotosUrl(date) {
    if (!date) return 'https://photos.google.com/u/0/';
    const query = formatLongDate(date).replace(/,/g, '');
    return `https://photos.google.com/u/0/search/${encodeURIComponent(query)}`;
  }

  function googleMapsUrl(visit) {
    const query = `${visit.lat},${visit.lon}`;
    if (visit.placeId) {
      return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}&query_place_id=${encodeURIComponent(visit.placeId)}`;
    }
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
  }

  function allRouteBounds() {
    const bounds = L.latLngBounds();
    state.data.days.forEach(day => day.routes.forEach(route => route.forEach(p => bounds.extend([p.lat, p.lon]))));
    return bounds;
  }

  function createStartEndIcon(label, kind) {
    return L.divIcon({
      className: 'start-end-marker',
      html: `<div class="start-end-dot ${kind === 'start' ? 'start-dot' : 'end-dot'}">${label}</div>`,
      iconSize: [24, 24], iconAnchor: [12, 12], popupAnchor: [0, -12],
    });
  }

  function renderOverview() {
    stopPlayback();
    state.selectedDate = null;
    backgroundLayer.clearLayers();
    routeLayer.clearLayers();
    markerLayer.clearLayers();
    rawLayer.clearLayers();
    playbackLayer.clearLayers();

    const bounds = L.latLngBounds();
    state.data.days.forEach((day, idx) => {
      const color = dayColor(idx, state.data.days.length);
      day.routes.forEach(route => {
        const latlngs = route.map(p => [p.lat, p.lon]);
        latlngs.forEach(p => bounds.extend(p));
        L.polyline(latlngs, { color, weight: 4, opacity: 0.78, lineCap: 'round', lineJoin: 'round' })
          .bindTooltip(`${formatDate(day.date, { weekday: true })} · ${countriesText(day.countries, ' → ')} · ${formatKm(day.stats.activityKm || day.stats.routeKm)}`, { sticky: true, direction: 'top' })
          .on('click', () => selectDate(day.date))
          .addTo(routeLayer);
      });
    });

    const first = state.data.days.find(d => d.start)?.start;
    const last = [...state.data.days].reverse().find(d => d.end)?.end;
    if (first) L.marker([first.lat, first.lon], { icon: createStartEndIcon('S', 'start') }).addTo(markerLayer).bindTooltip('Europe route start');
    if (last) L.marker([last.lat, last.lon], { icon: createStartEndIcon('E', 'end') }).addTo(markerLayer).bindTooltip('Europe route end');

    if (bounds.isValid()) map.fitBounds(bounds.pad(0.08), { animate: false });
    renderUI();
  }

  function stopPopupHtml(visit, index) {
    const country = visit.country ? `<div class="popup-country">${flagEmoji(visit.countryCode)} ${visit.country}</div>` : '';
    return `
      <div class="popup-title">Stop ${index + 1}</div>
      ${country}
      <div class="popup-meta">${visit.startLocal}–${visit.endLocal} · ${formatMinutes(visit.durationMinutes)}</div>
      <div class="popup-meta">${visit.lat.toFixed(5)}, ${visit.lon.toFixed(5)}</div>
      <a class="popup-link" href="${googleMapsUrl(visit)}" target="_blank" rel="noopener">Open in Google Maps ↗</a>
    `;
  }

  function renderDay(day) {
    stopPlayback();
    backgroundLayer.clearLayers();
    routeLayer.clearLayers();
    markerLayer.clearLayers();
    rawLayer.clearLayers();
    playbackLayer.clearLayers();

    // Context: the whole trip in a quiet background.
    state.data.days.forEach(other => {
      if (other.date === day.date) return;
      other.routes.forEach(route => {
        L.polyline(route.map(p => [p.lat, p.lon]), {
          color: '#9ba4b3', weight: 2, opacity: 0.16, interactive: false,
        }).addTo(backgroundLayer);
      });
    });

    const bounds = L.latLngBounds();
    day.routes.forEach(route => {
      const latlngs = route.map(p => [p.lat, p.lon]);
      latlngs.forEach(p => bounds.extend(p));
      L.polyline(latlngs, {
        color: '#1f5cff', weight: 5, opacity: 0.92, lineCap: 'round', lineJoin: 'round',
      }).addTo(routeLayer);
    });

    day.visits.forEach((visit, i) => {
      bounds.extend([visit.lat, visit.lon]);
      L.circleMarker([visit.lat, visit.lon], {
        radius: 5.5, color: '#ffffff', weight: 2.5, fillColor: '#1f5cff', fillOpacity: 1,
      }).bindPopup(stopPopupHtml(visit, i), { maxWidth: 260 }).addTo(markerLayer);
    });

    if (day.countryTimeline?.length > 1) {
      day.countryTimeline.forEach((country, index) => {
        L.marker([country.lat, country.lon], { icon: createCountryTransitionIcon(country), zIndexOffset: 600 })
          .bindTooltip(`${index === 0 ? 'Start in' : 'Enter'} ${country.country} · ${country.startTime}`, { direction: 'top' })
          .addTo(markerLayer);
      });
    }

    if (day.start) {
      const country = day.start.country ? ` · ${flagEmoji(day.start.countryCode)} ${day.start.country}` : '';
      L.marker([day.start.lat, day.start.lon], { icon: createStartEndIcon('S', 'start') })
        .bindTooltip(`Start · ${day.start.time.slice(11, 16)}${country}`).addTo(markerLayer);
    }
    if (day.end) {
      const country = day.end.country ? ` · ${flagEmoji(day.end.countryCode)} ${day.end.country}` : '';
      L.marker([day.end.lat, day.end.lon], { icon: createStartEndIcon('E', 'end') })
        .bindTooltip(`End · ${day.end.time.slice(11, 16)}${country}`).addTo(markerLayer);
    }

    els.timelineSlider.value = '0';
    renderRaw(day);
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.15), { maxZoom: 13, animate: false });
    renderUI();
    updatePlaybackMarker(0);
  }

  function renderRaw(day) {
    rawLayer.clearLayers();
    if (!state.rawVisible || !day) return;
    day.rawPoints.forEach(point => {
      L.circleMarker([point.lat, point.lon], {
        radius: 2, stroke: false, fillColor: '#242a35', fillOpacity: 0.42, interactive: false,
      }).addTo(rawLayer);
    });
  }

  function selectDate(date) {
    state.selectedDate = date;
    const day = selectedDay();
    if (!day) return renderOverview();
    renderDay(day);
    if (window.innerWidth <= 760) els.sidebar.classList.remove('open');
  }

  function renderTripMeta() {
    const meta = state.data.meta;
    els.tripMeta.innerHTML = `
      <strong>${formatDate(meta.europeStart, { longMonth: true })} – ${formatDate(meta.europeEnd, { longMonth: true, year: true })}</strong><br>
      ${meta.dayCount} days · ${meta.countryCount} countries · ${formatKm(meta.totalActivityKm)} recorded movement · ${meta.totalStops} stops
    `;
  }

  function renderDayList() {
    els.dayList.innerHTML = '';
    state.data.days.forEach((day, idx) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `day-item${day.date === state.selectedDate ? ' active' : ''}`;
      const modes = day.stats.modes.slice(0, 2).map(m => m.label).join(' · ') || 'Recorded route';
      button.innerHTML = `
        <span class="day-dot" style="background:${dayColor(idx, state.data.days.length)}"></span>
        <span class="day-main">
          <span class="day-title"><strong>${formatDate(day.date, { weekday: true })}</strong><span>Day ${day.index}</span></span>
          <span class="day-country">${countriesText(day.countries, ' → ')}</span>
          <span class="day-detail">${day.stats.stopCount} stops · ${modes}</span>
        </span>
        <span class="day-km">${formatKm(day.stats.activityKm || day.stats.routeKm)}</span>
      `;
      button.addEventListener('click', () => selectDate(day.date));
      els.dayList.appendChild(button);
    });
    const active = els.dayList.querySelector('.day-item.active');
    if (active) {
      // Keep the selected day visible by scrolling only the day-list pane.
      // scrollIntoView() can scroll the whole document, which used to move the
      // floating map toolbar off-screen when stepping through days.
      const listRect = els.dayList.getBoundingClientRect();
      const itemRect = active.getBoundingClientRect();
      const padding = 8;
      if (itemRect.top < listRect.top + padding) {
        els.dayList.scrollTop -= (listRect.top + padding) - itemRect.top;
      } else if (itemRect.bottom > listRect.bottom - padding) {
        els.dayList.scrollTop += itemRect.bottom - (listRect.bottom - padding);
      }
    }
  }

  function renderSelectedSummary(day) {
    if (!day) {
      const meta = state.data.meta;
      els.selectedSummary.innerHTML = `
        <div class="summary-card">
          <div class="summary-card-main">
            <p class="summary-date">The complete route</p>
            <div class="summary-subtitle">Select any day to inspect its route, countries, stops, movement modes and playback.</div>
            ${countryChips(meta.countries)}
            <div class="summary-stats">
              <div class="stat"><strong>${meta.dayCount}</strong><span>days</span></div>
              <div class="stat"><strong>${meta.countryCount}</strong><span>countries</span></div>
              <div class="stat"><strong>${formatKm(meta.totalActivityKm)}</strong><span>movement</span></div>
            </div>
          </div>
        </div>
      `;
      return;
    }

    const modes = day.stats.modes.map(mode => `
      <span class="mode-chip"><span>${modeIcon[mode.mode] || '•'}</span>${mode.label} · ${formatMinutes(mode.minutes)}</span>
    `).join('');

    const activityRows = day.activities.map(activity => {
      const country = activityCountryText(activity);
      return `
        <div class="activity-row">
          <span class="activity-icon">${modeIcon[activity.mode] || '•'}</span>
          <span class="activity-main"><strong>${activity.label}</strong><span>${activity.startLocal}–${activity.endLocal}${country ? ` · ${country}` : ''}</span></span>
          <span class="activity-distance">${formatKm(activity.distanceKm)}</span>
        </div>
      `;
    }).join('');

    const activityDetails = activityRows ? `
      <details class="activity-details">
        <summary>Movement timeline <span>${day.activities.length} segments</span></summary>
        <div class="activity-list">${activityRows}</div>
      </details>
    ` : '';

    const countryRows = (day.countryTimeline || []).map((country, index) => `
      <div class="country-timeline-row">
        <span class="country-timeline-flag">${flagEmoji(country.code)}</span>
        <span class="country-timeline-main"><strong>${country.country}</strong><span>${country.startTime}–${country.endTime}${index > 0 ? ' · border crossing' : ''}</span></span>
        <span class="country-code">${country.code}</span>
      </div>
    `).join('');

    const countryDetails = countryRows ? `
      <details class="activity-details country-details" ${day.countryTimeline.length > 1 ? 'open' : ''}>
        <summary>Country timeline <span>${day.countryTimeline.length} ${day.countryTimeline.length === 1 ? 'country period' : 'country periods'}</span></summary>
        <div class="country-timeline-list">${countryRows}</div>
      </details>
    ` : '';

    const photos = photoItemsFor(day.date);
    const photoPreview = photos.length ? `
      <div class="photo-preview">
        <div class="photo-preview-head"><strong>${photos.length} embedded ${photos.length === 1 ? 'photo' : 'photos'}</strong><button data-action="open-gallery">View all</button></div>
        <div class="photo-preview-grid">
          ${photos.slice(0, 4).map(item => item.type === 'video'
            ? `<video src="${encodeURI(item.src)}" muted preload="metadata"></video>`
            : `<img src="${encodeURI(item.src)}" alt="Trip photo" loading="lazy" />`).join('')}
        </div>
      </div>
    ` : '';

    els.selectedSummary.innerHTML = `
      <div class="summary-card">
        <div class="summary-card-main">
          <p class="summary-date">${formatLongDate(day.date)}</p>
          <div class="summary-subtitle">Day ${day.index} of ${state.data.meta.dayCount}</div>
          ${countryChips(day.countries)}
          <div class="summary-stats">
            <div class="stat"><strong>${formatKm(day.stats.activityKm || day.stats.routeKm)}</strong><span>movement</span></div>
            <div class="stat"><strong>${day.stats.stopCount}</strong><span>stops</span></div>
            <div class="stat"><strong>${day.stats.rawPointCount.toLocaleString()}</strong><span>GPS pts</span></div>
          </div>
          <div class="mode-row">${modes || '<span class="mode-chip">Recorded route</span>'}</div>
          <div class="summary-actions">
            <button class="primary-action" data-action="open-gallery">Photos</button>
            <button class="secondary-action" data-action="google-photos">Google Photos ↗</button>
          </div>
        </div>
        ${countryDetails}
        ${activityDetails}
        ${photoPreview}
      </div>
    `;

    els.selectedSummary.querySelectorAll('[data-action="open-gallery"]').forEach(btn => btn.addEventListener('click', openPhotoDialog));
    els.selectedSummary.querySelectorAll('[data-action="google-photos"]').forEach(btn => btn.addEventListener('click', () => window.open(googlePhotosUrl(day.date), '_blank', 'noopener')));
  }

  function renderToolbar(day) {
    if (!day) {
      els.currentTitle.innerHTML = `<span class="current-kicker">ENTIRE TRIP</span><strong>Europe 2017</strong><span class="current-countryline">${state.data.meta.countryCount} countries</span>`;
      els.previousDay.disabled = true;
      els.nextDay.disabled = false;
      els.photosButton.textContent = 'Photos';
      els.timelinePlayer.hidden = true;
      els.overviewLegend.classList.remove('hidden');
      els.overviewLegend.innerHTML = `<div class="legend-row"><span class="legend-line"></span><span>Each colour is a trip day · ${state.data.meta.countryCount} countries</span></div>`;
      return;
    }

    els.currentTitle.innerHTML = `<span class="current-kicker">DAY ${day.index} OF ${state.data.meta.dayCount}</span><strong>${formatLongDate(day.date)}</strong><span class="current-countryline">${countriesText(day.countries, ' → ')}</span>`;
    els.previousDay.disabled = day.index <= 1;
    els.nextDay.disabled = day.index >= state.data.meta.dayCount;
    const photoCount = photoItemsFor(day.date).length;
    els.photosButton.textContent = photoCount ? `Photos · ${photoCount}` : 'Photos';
    els.timelinePlayer.hidden = day.rawPoints.length < 2;
    els.timelineDate.textContent = formatDate(day.date, { weekday: true });
    els.overviewLegend.classList.add('hidden');
  }

  function renderUI() {
    const day = selectedDay();
    renderTripMeta();
    renderDayList();
    renderSelectedSummary(day);
    renderToolbar(day);
    renderPhotoFilmstrip(day);
    els.rawToggle.setAttribute('aria-pressed', String(state.rawVisible));
  }

  function updatePlaybackMarker(value, options = {}) {
    const day = selectedDay();
    playbackLayer.clearLayers();
    if (!day || !day.rawPoints.length) return;
    const maxIndex = day.rawPoints.length - 1;
    const idx = Math.max(0, Math.min(maxIndex, Math.round((Number(value) / 1000) * maxIndex)));
    state.playbackIndex = idx;
    const point = day.rawPoints[idx];
    els.timelineTime.textContent = point.time.slice(11, 16);
    els.timelineCountry.textContent = point.country ? `${flagEmoji(point.countryCode)} ${point.country}` : '';
    const icon = L.divIcon({ className: '', html: '<div class="playback-dot"></div>', iconSize: [18, 18], iconAnchor: [9, 9] });
    L.marker([point.lat, point.lon], { icon, interactive: false, zIndexOffset: 1000 }).addTo(playbackLayer);
    if (options.syncPhotos !== false) syncPhotoFilmstripToTimeline(value);
  }

  function startPlayback() {
    const day = selectedDay();
    if (!day || day.rawPoints.length < 2) return;
    if (Number(els.timelineSlider.value) >= 998) els.timelineSlider.value = '0';
    els.playButton.textContent = '❚❚';
    state.playTimer = window.setInterval(() => {
      const next = Number(els.timelineSlider.value) + 8;
      if (next >= 1000) {
        els.timelineSlider.value = '1000';
        updatePlaybackMarker(1000);
        stopPlayback();
      } else {
        els.timelineSlider.value = String(next);
        updatePlaybackMarker(next);
      }
    }, 120);
  }

  function stopPlayback() {
    if (state.playTimer) window.clearInterval(state.playTimer);
    state.playTimer = null;
    els.playButton.textContent = '▶';
  }

  function openPhotoDialog() {
    const day = selectedDay();
    if (!day) {
      showNotice('Choose a day first to view photos for that date.');
      return;
    }
    const items = photoItemsFor(day.date);
    els.photoDialogTitle.textContent = formatLongDate(day.date);
    els.photoGrid.innerHTML = '';
    els.photoEmpty.hidden = items.length > 0;
    els.photoGrid.hidden = items.length === 0;

    items.forEach(item => {
      if (item.type === 'video') {
        const video = document.createElement('video');
        video.src = item.src;
        video.controls = true;
        video.preload = 'metadata';
        video.title = item.name || 'Trip video';
        els.photoGrid.appendChild(video);
      } else {
        const link = document.createElement('a');
        link.href = item.src;
        link.target = '_blank';
        link.rel = 'noopener';
        const img = document.createElement('img');
        img.src = item.src;
        img.alt = item.name || 'Trip photo';
        img.loading = 'lazy';
        link.appendChild(img);
        els.photoGrid.appendChild(link);
      }
    });

    if (typeof els.photoDialog.showModal === 'function') els.photoDialog.showModal();
    else els.photoDialog.setAttribute('open', '');
  }

  function showNotice(text) {
    els.mapNotice.textContent = text;
    els.mapNotice.hidden = false;
    window.clearTimeout(showNotice.timer);
    showNotice.timer = window.setTimeout(() => { els.mapNotice.hidden = true; }, 2600);
  }

  els.overviewButton.addEventListener('click', renderOverview);
  els.previousDay.addEventListener('click', () => {
    const day = selectedDay();
    if (!day) return;
    const prev = state.data.days[day.index - 2];
    if (prev) selectDate(prev.date);
  });
  els.nextDay.addEventListener('click', () => {
    const day = selectedDay();
    if (!day) return selectDate(state.data.days[0].date);
    const next = state.data.days[day.index];
    if (next) selectDate(next.date);
  });
  els.rawToggle.addEventListener('click', () => {
    state.rawVisible = !state.rawVisible;
    els.rawToggle.setAttribute('aria-pressed', String(state.rawVisible));
    renderRaw(selectedDay());
    showNotice(state.rawVisible ? 'Raw Europe GPS points shown.' : 'Raw GPS points hidden.');
  });
  els.photosButton.addEventListener('click', openPhotoDialog);
  els.photoFilmstripPrev.addEventListener('click', () => {
    stopPlayback();
    els.photoFilmstripTrack.scrollBy({ left: -photoFilmstripStep(), behavior: 'smooth' });
  });
  els.photoFilmstripNext.addEventListener('click', () => {
    stopPlayback();
    els.photoFilmstripTrack.scrollBy({ left: photoFilmstripStep(), behavior: 'smooth' });
  });
  els.photoFilmstripViewAll.addEventListener('click', openPhotoDialog);
  els.photoFilmstripTrack.addEventListener('scroll', () => {
    updatePhotoFilmstripButtons();
    window.cancelAnimationFrame(state.photoFilmstripScrollRaf);
    state.photoFilmstripScrollRaf = window.requestAnimationFrame(syncTimelineToPhotoFilmstrip);
  }, { passive: true });
  els.photoFilmstripTrack.addEventListener('wheel', event => {
    // A normal mouse wheel moves the horizontal filmstrip; trackpads keep their
    // native horizontal gesture. Do not hijack scrolling when there is nowhere to go.
    if (els.photoFilmstripTrack.scrollWidth <= els.photoFilmstripTrack.clientWidth) return;
    if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
      stopPlayback();
      els.photoFilmstripTrack.scrollLeft += event.deltaY;
      event.preventDefault();
    }
  }, { passive: false });
  window.addEventListener('resize', updatePhotoFilmstripButtons);
  function refreshMobileVisualViewport() {
    // Mobile browser chrome changes the visual viewport while scrolling/rotating.
    // Re-measure Leaflet and the photo strip so bottom controls stay aligned.
    window.clearTimeout(refreshMobileVisualViewport.timer);
    refreshMobileVisualViewport.timer = window.setTimeout(() => {
      map.invalidateSize({ pan: false });
      updatePhotoFilmstripButtons();
      const day = selectedDay();
      if (day && !els.photoFilmstrip.hidden) {
        syncPhotoFilmstripToTimeline(els.timelineSlider.value);
      }
    }, 90);
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', refreshMobileVisualViewport, { passive: true });
  }
  window.addEventListener('orientationchange', refreshMobileVisualViewport, { passive: true });
  els.timelineSlider.addEventListener('input', event => { stopPlayback(); updatePlaybackMarker(event.target.value); });
  els.playButton.addEventListener('click', () => state.playTimer ? stopPlayback() : startPlayback());
  els.closePhotoDialog.addEventListener('click', () => els.photoDialog.close());
  els.photoEmptyGoogle.addEventListener('click', () => {
    const day = selectedDay();
    if (day) window.open(googlePhotosUrl(day.date), '_blank', 'noopener');
  });
  els.openSidebar.addEventListener('click', () => els.sidebar.classList.add('open'));
  els.closeSidebar.addEventListener('click', () => els.sidebar.classList.remove('open'));

  async function loadData() {
    const [tripResult, photoResult] = await Promise.allSettled([
      fetch(basePath('data/trip-data.json')).then(r => {
        if (!r.ok) throw new Error(`Trip data HTTP ${r.status}`);
        return r.json();
      }),
      fetch(basePath('photos/manifest.json'), { cache: 'no-store' }).then(r => r.ok ? r.json() : ({ version: 1, dates: {} })),
    ]);

    if (tripResult.status !== 'fulfilled') throw tripResult.reason;
    state.data = tripResult.value;
    if (photoResult.status === 'fulfilled') state.photos = photoResult.value;

    renderOverview();
  }

  loadData().catch(error => {
    console.error(error);
    document.body.innerHTML = `<main style="padding:40px;font-family:system-ui"><h1>Could not load trip data</h1><p>${String(error.message || error)}</p><p>Run this site through a local web server rather than opening index.html directly.</p></main>`;
  });
})();
