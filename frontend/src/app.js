(() => {
  const DATA_REFRESH_INTERVAL_MS = 60000;
  const WS_PING_INTERVAL_MS = 20000;
  const appLocale = document.documentElement.lang || navigator.language || 'en-US';
  const state = {
    currentPage: 'dashboard',
    dashboard: null,
    cameras: [],
    persons: [],
    alerts: [],
    detectionTimeline: [],
    watchlistActivity: [],
    cameraActivity: [],
    selectedCameraId: null,
    selectedPersonId: null,
    cameraDetections: {},
    cameraHeatmaps: {},
    cameraStats: {},
    personTimelines: {},
    liveFrames: {},
    searchResults: [],
    uploadJobs: [],
    ws: null,
    wsConnected: false,
    wsReconnectTimer: null,
    refreshTimer: null,
    periodicRefreshTimer: null,
    pingTimer: null,
    personFilters: {
      search: '',
      watchlist: '',
    },
  };

  const pageMeta = {
    dashboard: {
      title: 'Dashboard',
      subtitle: 'Real-time surveillance intelligence overview',
    },
    cameras: {
      title: 'Live Cameras',
      subtitle: 'Manage streams, preview live feeds, and inspect camera activity',
    },
    persons: {
      title: 'Persons',
      subtitle: 'Manage the identity database and watchlist registry',
    },
    search: {
      title: 'Identity Search',
      subtitle: 'Upload a probe image to find matching enrolled identities',
    },
    timeline: {
      title: 'Movement Timeline',
      subtitle: 'Reconstruct movement paths across the camera network',
    },
    alerts: {
      title: 'Alerts',
      subtitle: 'Monitor and acknowledge recent watchlist and system alerts',
    },
    upload: {
      title: 'Upload Video',
      subtitle: 'Run forensic analysis on recorded video footage',
    },
    analytics: {
      title: 'Analytics',
      subtitle: 'Review operational trends and camera/watchlist activity',
    },
  };

  const els = {};

  document.addEventListener('DOMContentLoaded', init);

  function init() {
    cacheElements();
    bindStaticEvents();
    startClock();
    renderAllPages();
    navigate(state.currentPage);
    refreshAllData();
    connectWebSocket();
    state.periodicRefreshTimer = window.setInterval(refreshAllData, DATA_REFRESH_INTERVAL_MS);
    window.addEventListener('beforeunload', cleanup);
  }

  function cacheElements() {
    els.navItems = Array.from(document.querySelectorAll('.nav-item'));
    els.pages = Array.from(document.querySelectorAll('.page'));
    els.pageTitle = document.getElementById('page-title');
    els.pageSubtitle = document.getElementById('page-subtitle');
    els.datetime = document.getElementById('datetime-display');
    els.toastContainer = document.getElementById('toast-container');
    els.modalOverlay = document.getElementById('modal-overlay');
    els.modalBox = document.getElementById('modal-box');
    els.alertBell = document.getElementById('alert-bell');
    els.wsDot = document.getElementById('ws-dot');
    els.wsLabel = document.getElementById('ws-label');
    els.activeCamBadge = document.getElementById('active-cam-badge');
    els.alertCountBadge = document.getElementById('alert-count-badge');
    els.bellDot = document.getElementById('bell-dot');
  }

  function bindStaticEvents() {
    els.navItems.forEach((button) => {
      button.addEventListener('click', () => navigate(button.dataset.page));
    });

    els.alertBell.addEventListener('click', () => navigate('alerts'));

    els.modalOverlay.addEventListener('click', (event) => {
      if (event.target === els.modalOverlay) {
        closeModal();
      }
    });

    document.addEventListener('click', handleDocumentClick);
    document.addEventListener('submit', handleDocumentSubmit);
    document.addEventListener('input', handleDocumentInput);
    document.addEventListener('change', handleDocumentChange);
  }

  function cleanup() {
    if (state.wsReconnectTimer) window.clearTimeout(state.wsReconnectTimer);
    if (state.refreshTimer) window.clearTimeout(state.refreshTimer);
    if (state.periodicRefreshTimer) window.clearInterval(state.periodicRefreshTimer);
    if (state.pingTimer) window.clearInterval(state.pingTimer);
    if (state.ws) state.ws.close();
  }

  function navigate(page) {
    state.currentPage = page;
    els.navItems.forEach((button) => {
      button.classList.toggle('active', button.dataset.page === page);
    });
    els.pages.forEach((section) => {
      section.classList.toggle('active', section.id === `page-${page}`);
    });

    const meta = pageMeta[page] || pageMeta.dashboard;
    els.pageTitle.textContent = meta.title;
    els.pageSubtitle.textContent = meta.subtitle;

    if (page === 'cameras') {
      void loadSelectedCameraData(true);
    }
    if (page === 'timeline') {
      void loadSelectedPersonTimeline(true);
    }
  }

  async function refreshAllData() {
    const [dashboard, cameras, persons, alerts, detectionTimeline, watchlistActivity, cameraActivity, jobs] = await Promise.all([
      requestOrFallback(api.dashboard(), state.dashboard || getEmptyDashboard()),
      requestOrFallback(api.cameras(), state.cameras),
      requestOrFallback(api.get('/persons/?limit=200'), state.persons),
      requestOrFallback(api.alerts(50), state.alerts),
      requestOrFallback(api.detectionTimeline(24), state.detectionTimeline),
      requestOrFallback(api.watchlistActivity(), state.watchlistActivity),
      requestOrFallback(api.cameraActivity(), state.cameraActivity),
      requestOrFallback(api.get('/upload/jobs'), { jobs: state.uploadJobs }, true),
    ]);

    state.dashboard = dashboard || getEmptyDashboard();
    state.cameras = Array.isArray(cameras) ? cameras : [];
    state.persons = Array.isArray(persons) ? persons : [];
    state.alerts = Array.isArray(alerts) ? alerts : [];
    state.detectionTimeline = Array.isArray(detectionTimeline) ? detectionTimeline : [];
    state.watchlistActivity = Array.isArray(watchlistActivity) ? watchlistActivity : [];
    state.cameraActivity = Array.isArray(cameraActivity) ? cameraActivity : [];
    state.uploadJobs = normaliseJobs(jobs);

    ensureSelections();

    await Promise.all([
      loadSelectedCameraData(),
      loadSelectedPersonTimeline(),
    ]);

    renderAllPages();
    updateBadges();
  }

  async function loadSelectedCameraData(force = false) {
    if (!state.selectedCameraId) return;
    const cameraId = state.selectedCameraId;

    if (!force && state.cameraDetections[cameraId] && state.cameraHeatmaps[cameraId] && state.cameraStats[cameraId]) {
      return;
    }

    const [detections, heatmap, stats] = await Promise.all([
      requestOrFallback(api.detections(cameraId, 24), state.cameraDetections[cameraId] || [], true),
      requestOrFallback(api.heatmap(cameraId), state.cameraHeatmaps[cameraId] || [], true),
      requestOrFallback(api.get(`/cameras/${cameraId}/stats`), state.cameraStats[cameraId] || { camera_id: cameraId, running: false }, true),
    ]);

    state.cameraDetections[cameraId] = Array.isArray(detections) ? detections : [];
    state.cameraHeatmaps[cameraId] = Array.isArray(heatmap) ? heatmap : [];
    state.cameraStats[cameraId] = stats || { camera_id: cameraId, running: false };

    if (state.currentPage === 'cameras') {
      renderCamerasPage();
    }
  }

  async function loadSelectedPersonTimeline(force = false) {
    if (!state.selectedPersonId) return;
    const personId = state.selectedPersonId;
    if (!force && state.personTimelines[personId]) return;

    const timeline = await requestOrFallback(api.timeline(personId), state.personTimelines[personId] || null, true);
    if (timeline) {
      state.personTimelines[personId] = timeline;
      if (state.currentPage === 'timeline') {
        renderTimelinePage();
      }
    }
  }

  function ensureSelections() {
    const activeCamera = state.cameras.find((camera) => camera.id === state.selectedCameraId);
    if (!activeCamera && state.cameras.length > 0) {
      state.selectedCameraId = state.cameras[0].id;
    }

    const activePerson = state.persons.find((person) => person.id === state.selectedPersonId);
    if (!activePerson && state.persons.length > 0) {
      state.selectedPersonId = state.persons[0].id;
    }
  }

  function renderAllPages() {
    renderDashboardPage();
    renderCamerasPage();
    renderPersonsPage();
    renderSearchPage();
    renderTimelinePage();
    renderAlertsPage();
    renderUploadPage();
    renderAnalyticsPage();
    updateBadges();
  }

  function renderDashboardPage() {
    const page = document.getElementById('page-dashboard');
    const stats = state.dashboard || getEmptyDashboard();
    const featuredCameras = state.cameras.slice(0, 4);
    const recentAlerts = state.alerts.slice(0, 5);
    const watchlist = state.watchlistActivity.slice(0, 5);

    page.innerHTML = `
      <div class="stat-grid">
        ${renderStatCard('Tracked Profiles', stats.total_persons, 'cyan', personIcon())}
        ${renderStatCard('Watchlisted', stats.watchlisted_persons, 'red', alertIcon())}
        ${renderStatCard('Missing Persons', stats.missing_persons, 'amber', userSearchIcon())}
        ${renderStatCard('Suspects', stats.suspects, 'purple', shieldIcon())}
        ${renderStatCard('Active Cameras', `${stats.active_cameras}/${stats.total_cameras}`, 'green', cameraIcon())}
        ${renderStatCard('Detections Today', stats.detections_today, 'cyan', pulseIcon())}
      </div>
      <div class="dashboard-grid">
        <div class="dashboard-main">
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Detection Timeline</div>
                <div class="text-muted">Last 24 hours of recorded detections</div>
              </div>
              <button class="btn btn-outline btn-sm" data-action="refresh-all">Refresh</button>
            </div>
            ${renderBarChart(state.detectionTimeline, 'count')}
          </section>
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Camera Grid</div>
                <div class="text-muted">Live previews update via WebSocket when streams are active</div>
              </div>
              <button class="btn btn-outline btn-sm" data-action="goto-page" data-page="cameras">Manage Cameras</button>
            </div>
            <div class="cam-grid">
              ${featuredCameras.length ? featuredCameras.map(renderCameraPreviewCard).join('') : renderEmptyState('No cameras configured yet.')}
            </div>
          </section>
        </div>
        <aside class="dashboard-side">
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Alert Feed</div>
                <div class="text-muted">Most recent high-priority events</div>
              </div>
              <button class="btn btn-outline btn-sm" data-action="goto-page" data-page="alerts">Open Alerts</button>
            </div>
            <div class="alert-feed">
              ${recentAlerts.length ? recentAlerts.map(renderAlertItem).join('') : renderEmptyState('No alerts triggered.')}
            </div>
          </section>
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Watchlist Activity</div>
                <div class="text-muted">Recent sighting frequency by profile</div>
              </div>
            </div>
            ${watchlist.length ? `
              <div class="timeline-list">
                ${watchlist.map((item) => `
                  <div class="tl-item">
                    <div style="flex:1;">
                      <div class="tl-cam">${escapeHtml(item.name)}</div>
                      <div class="tl-loc">${formatWatchlistLabel(item.watchlist_status)} • ${item.last_camera ? escapeHtml(item.last_camera) : 'No sightings yet'}</div>
                    </div>
                    <div class="tl-time">${item.detection_count}</div>
                  </div>
                `).join('')}
              </div>
            ` : renderEmptyState('No watchlist activity available.')}
          </section>
        </aside>
      </div>
    `;
  }

  function renderCamerasPage() {
    const page = document.getElementById('page-cameras');
    const selectedCamera = state.cameras.find((camera) => camera.id === state.selectedCameraId) || null;
    const detections = selectedCamera ? (state.cameraDetections[selectedCamera.id] || []) : [];
    const heatmap = selectedCamera ? (state.cameraHeatmaps[selectedCamera.id] || []) : [];
    const stats = selectedCamera ? (state.cameraStats[selectedCamera.id] || { running: false }) : null;

    page.innerHTML = `
      <section class="section-header">
        <div>
          <div class="section-title">Camera Network</div>
          <div class="text-muted">Start streams, inspect detections, and monitor coverage zones.</div>
        </div>
        <div class="flex gap-2">
          <button class="btn btn-outline" data-action="refresh-all">Refresh</button>
          <button class="btn btn-primary" data-action="open-add-camera">Add Camera</button>
        </div>
      </section>
      <div class="person-grid">
        ${state.cameras.map((camera) => `
          <article class="person-card ${camera.id === state.selectedCameraId ? 'suspect' : ''}" data-action="select-camera" data-camera-id="${camera.id}">
            <div class="flex justify-between items-center">
              <div class="person-name">${escapeHtml(camera.name)}</div>
              ${renderCameraStatusChip(camera.status)}
            </div>
            <div class="person-desc">${escapeHtml(camera.location || 'Location unavailable')}</div>
            <div class="person-desc">Zone: ${escapeHtml(camera.zone || 'Unknown')} • ${escapeHtml(camera.resolution || 'N/A')}</div>
            <div class="cam-cell" style="margin:12px 0 10px;">
              ${renderCameraFrame(camera)}
              <div class="cam-overlay"></div>
              <div class="cam-label">CAM-${camera.id}</div>
              <div class="cam-status"><span class="status-dot ${camera.status !== 'active' ? 'offline' : ''}"></span>${camera.status}</div>
            </div>
            <div class="flex gap-2">
              <button class="btn btn-outline btn-sm" data-action="select-camera" data-camera-id="${camera.id}">Inspect</button>
              <button class="btn ${camera.status === 'active' ? 'btn-danger' : 'btn-primary'} btn-sm" data-action="toggle-camera" data-camera-id="${camera.id}" data-state="${camera.status}">
                ${camera.status === 'active' ? 'Stop Stream' : 'Start Stream'}
              </button>
            </div>
          </article>
        `).join('') || renderEmptyState('No cameras available. Add a camera to start monitoring.')}
      </div>
      <div class="dashboard-grid mt-4">
        <div class="dashboard-main">
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">${selectedCamera ? escapeHtml(selectedCamera.name) : 'Camera Details'}</div>
                <div class="text-muted">${selectedCamera ? escapeHtml(selectedCamera.location || 'Location unavailable') : 'Select a camera to inspect activity.'}</div>
              </div>
              ${selectedCamera ? `<button class="btn btn-outline btn-sm" data-action="reload-camera" data-camera-id="${selectedCamera.id}">Reload</button>` : ''}
            </div>
            ${selectedCamera ? `
              <div class="stat-grid" style="margin-bottom:16px;">
                ${renderMiniStat('Stream', stats && stats.running ? 'Online' : 'Offline')}
                ${renderMiniStat('FPS', stats && stats.fps ? stats.fps : 0)}
                ${renderMiniStat('Frames', stats && stats.frame_count ? stats.frame_count : 0)}
                ${renderMiniStat('Detections', detections.length)}
              </div>
              <div class="section-header">
                <div class="section-title">Recent Detections</div>
              </div>
              ${detections.length ? renderDetectionsTable(detections.slice(0, 12)) : renderEmptyState('No detections recorded for this camera yet.')}
            ` : renderEmptyState('Select a camera card to inspect live details.')}
          </section>
        </div>
        <aside class="dashboard-side">
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Heatmap</div>
                <div class="text-muted">Hotspots summarised from accumulated detections</div>
              </div>
            </div>
            ${selectedCamera ? renderHeatmap(heatmap) : renderEmptyState('Select a camera to view its heatmap.')}
          </section>
        </aside>
      </div>
    `;
  }

  function renderPersonsPage() {
    const page = document.getElementById('page-persons');
    const search = state.personFilters.search.trim().toLowerCase();
    const watchlist = state.personFilters.watchlist;
    const filteredPersons = state.persons.filter((person) => {
      const matchesSearch = !search || [person.name, person.alias, person.description]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(search));
      const matchesWatchlist = !watchlist || person.watchlist_status === watchlist;
      return matchesSearch && matchesWatchlist;
    });

    page.innerHTML = `
      <section class="section-header">
        <div>
          <div class="section-title">Identity Registry</div>
          <div class="text-muted">Enroll known persons and manage watchlist categories.</div>
        </div>
        <button class="btn btn-primary" data-action="open-add-person">Add Person</button>
      </section>
      <section class="card" style="margin-bottom:20px;">
        <div class="form-row">
          <div class="form-group" style="margin-bottom:0;">
            <label for="person-search-input">Search</label>
            <input id="person-search-input" type="text" value="${escapeHtml(state.personFilters.search)}" placeholder="Search by name, alias, or description" />
          </div>
          <div class="form-group" style="margin-bottom:0;">
            <label for="person-filter-watchlist">Watchlist</label>
            <select id="person-filter-watchlist">
              <option value="">All statuses</option>
              ${['none', 'missing', 'suspect', 'person_of_interest'].map((status) => `
                <option value="${status}" ${watchlist === status ? 'selected' : ''}>${formatWatchlistLabel(status)}</option>
              `).join('')}
            </select>
          </div>
        </div>
      </section>
      <div class="person-grid">
        ${filteredPersons.length ? filteredPersons.map(renderPersonCard).join('') : renderEmptyState('No persons match the current filters.')}
      </div>
    `;
  }

  function renderSearchPage() {
    const page = document.getElementById('page-search');
    page.innerHTML = `
      <section class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Probe Image Search</div>
            <div class="text-muted">Upload an image and compare it with enrolled face embeddings.</div>
          </div>
        </div>
        <form id="search-form">
          <label class="search-upload-box" for="search-file-input">
            <div class="search-upload-icon">${uploadIcon()}</div>
            <div class="upload-title">Drop or choose a face image</div>
            <div class="upload-sub" id="search-file-label">JPG, PNG, or WEBP images are accepted.</div>
          </label>
          <input id="search-file-input" name="file" type="file" accept="image/*" hidden />
          <div class="form-row mt-4">
            <div class="form-group">
              <label for="search-top-k">Top Matches</label>
              <select id="search-top-k" name="top_k">
                <option value="3">Top 3</option>
                <option value="5" selected>Top 5</option>
                <option value="10">Top 10</option>
              </select>
            </div>
            <div class="form-group" style="display:flex;align-items:flex-end;justify-content:flex-end;">
              <button class="btn btn-primary" type="submit">Run Search</button>
            </div>
          </div>
        </form>
        <div class="search-results">
          ${state.searchResults.length ? state.searchResults.map(renderSearchResult).join('') : renderEmptyState('Search results will appear here after uploading an image.')}
        </div>
      </section>
    `;
  }

  function renderTimelinePage() {
    const page = document.getElementById('page-timeline');
    const timeline = state.selectedPersonId ? state.personTimelines[state.selectedPersonId] : null;

    page.innerHTML = `
      <section class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Movement Reconstruction</div>
            <div class="text-muted">Follow a subject through the surveillance network.</div>
          </div>
          <button class="btn btn-outline btn-sm" data-action="reload-timeline">Reload</button>
        </div>
        <div class="form-group">
          <label for="timeline-person-select">Select Person</label>
          <select id="timeline-person-select">
            ${state.persons.map((person) => `
              <option value="${person.id}" ${person.id === state.selectedPersonId ? 'selected' : ''}>${escapeHtml(person.name)} — ${formatWatchlistLabel(person.watchlist_status)}</option>
            `).join('')}
          </select>
        </div>
        ${timeline ? `
          <div class="stat-grid" style="margin-bottom:16px;">
            ${renderMiniStat('Cameras', timeline.total_cameras)}
            ${renderMiniStat('First Seen', timeline.first_seen ? formatShortDate(timeline.first_seen) : '—')}
            ${renderMiniStat('Last Seen', timeline.last_seen ? formatShortDate(timeline.last_seen) : '—')}
            ${renderMiniStat('Duration', formatDuration(timeline.total_duration_seconds || 0))}
          </div>
          <div class="timeline-list">
            ${timeline.events.length ? timeline.events.map(renderTimelineItem).join('') : renderEmptyState('No movement events recorded for this person.')}
          </div>
        ` : renderEmptyState('Select a person to load their movement timeline.')}
      </section>
    `;
  }

  function renderAlertsPage() {
    const page = document.getElementById('page-alerts');
    page.innerHTML = `
      <section class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Operational Alerts</div>
            <div class="text-muted">Acknowledge watchlist, security, and surveillance alerts.</div>
          </div>
          <button class="btn btn-outline btn-sm" data-action="refresh-all">Refresh</button>
        </div>
        <div class="alert-feed" style="max-height:none;">
          ${state.alerts.length ? state.alerts.map((alert) => `
            <div class="alert-item ${alert.severity}">
              <span class="alert-dot ${alert.severity}"></span>
              <div style="flex:1;">
                <div class="alert-title">${escapeHtml(alert.title)}</div>
                <div class="alert-msg">${escapeHtml(alert.message)}</div>
                <div class="alert-msg" style="margin-top:6px;">${escapeHtml(alert.camera_name || 'Unknown camera')} ${alert.person_name ? `• ${escapeHtml(alert.person_name)}` : ''}</div>
              </div>
              <div style="text-align:right;min-width:120px;">
                <div class="alert-time">${formatRelativeTime(alert.triggered_at)}</div>
                ${alert.is_acknowledged ? '<div class="chip chip-active" style="margin-top:8px;">ACKNOWLEDGED</div>' : `<button class="btn btn-outline btn-sm" style="margin-top:8px;" data-action="ack-alert" data-alert-id="${alert.id}">Acknowledge</button>`}
              </div>
            </div>
          `).join('') : renderEmptyState('No alerts available.')}
        </div>
      </section>
    `;
  }

  function renderUploadPage() {
    const page = document.getElementById('page-upload');
    page.innerHTML = `
      <section class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Video Ingestion</div>
            <div class="text-muted">Upload recorded footage and poll processing progress.</div>
          </div>
        </div>
        <form id="upload-form">
          <label class="upload-zone" for="upload-file-input">
            <div class="upload-icon">${uploadIcon()}</div>
            <div class="upload-title">Drop or select a video file</div>
            <div class="upload-sub" id="upload-file-label">MP4, MOV, AVI, MKV and similar formats are supported.</div>
          </label>
          <input id="upload-file-input" name="file" type="file" accept="video/*" hidden />
          <div class="grid-2 mt-4">
            <div class="form-group">
              <label for="upload-camera-name">Camera Name</label>
              <input id="upload-camera-name" name="camera_name" type="text" value="Uploaded Video" required />
            </div>
            <div class="form-group">
              <label for="upload-location">Location</label>
              <input id="upload-location" name="location" type="text" value="Unknown" />
            </div>
          </div>
          <div class="form-group">
            <label for="upload-zone-name">Zone</label>
            <input id="upload-zone-name" name="zone" type="text" value="General" />
          </div>
          <button class="btn btn-primary" type="submit">Upload & Process</button>
        </form>
      </section>
      <section class="card mt-4">
        <div class="card-header">
          <div>
            <div class="card-title">Processing Jobs</div>
            <div class="text-muted">Track the status of uploaded video analysis tasks.</div>
          </div>
        </div>
        ${state.uploadJobs.length ? state.uploadJobs.map(renderUploadJob).join('') : renderEmptyState('No upload jobs yet.')}
      </section>
    `;
  }

  function renderAnalyticsPage() {
    const page = document.getElementById('page-analytics');
    page.innerHTML = `
      <div class="dashboard-grid">
        <div class="dashboard-main">
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Detection Volume</div>
                <div class="text-muted">Time-bucketed detections from the analytics service</div>
              </div>
            </div>
            ${renderBarChart(state.detectionTimeline, 'count')}
          </section>
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Camera Activity Summary</div>
                <div class="text-muted">Detection totals and watchlist hits by camera</div>
              </div>
            </div>
            ${state.cameraActivity.length ? renderCameraActivityTable(state.cameraActivity) : renderEmptyState('Camera activity data is unavailable.')}
          </section>
        </div>
        <aside class="dashboard-side">
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Watchlist Hotspots</div>
                <div class="text-muted">Most active watchlist profiles in recent history</div>
              </div>
            </div>
            ${state.watchlistActivity.length ? `
              <div class="timeline-list">
                ${state.watchlistActivity.slice(0, 8).map((item) => `
                  <div class="tl-item">
                    <div style="flex:1;">
                      <div class="tl-cam">${escapeHtml(item.name)}</div>
                      <div class="tl-loc">${escapeHtml(item.last_camera || 'No sightings')} • ${formatWatchlistLabel(item.watchlist_status)}</div>
                    </div>
                    <div class="tl-time">${item.detection_count}</div>
                  </div>
                `).join('')}
              </div>
            ` : renderEmptyState('No watchlist analytics available.')}
          </section>
          <section class="card">
            <div class="card-header">
              <div>
                <div class="card-title">Alert Snapshot</div>
                <div class="text-muted">Current unacknowledged alert count</div>
              </div>
            </div>
            <div class="stat-value">${(state.dashboard || getEmptyDashboard()).unacknowledged_alerts}</div>
            <div class="text-muted" style="margin-top:10px;">Alerts today: ${(state.dashboard || getEmptyDashboard()).alerts_today}</div>
          </section>
        </aside>
      </div>
    `;
  }

  function renderStatCard(label, value, tone, icon) {
    return `
      <div class="stat-card">
        <div class="stat-icon ${tone}">${icon}</div>
        <div>
          <div class="stat-label">${escapeHtml(label)}</div>
          <div class="stat-value">${escapeHtml(String(value))}</div>
        </div>
      </div>
    `;
  }

  function renderCameraPreviewCard(camera) {
    return `
      <div class="cam-cell" data-action="goto-page" data-page="cameras">
        ${renderCameraFrame(camera)}
        <div class="cam-overlay"></div>
        <div class="cam-label">${escapeHtml(camera.name)}</div>
        <div class="cam-status"><span class="status-dot ${camera.status !== 'active' ? 'offline' : ''}"></span>${escapeHtml(camera.status)}</div>
        <div class="cam-det-count">${state.cameraStats[camera.id]?.fps ? `${state.cameraStats[camera.id].fps} fps` : 'idle'}</div>
      </div>
    `;
  }

  function renderCameraFrame(camera) {
    const frame = state.liveFrames[camera.id];
    if (frame) {
      return `<img src="${frame}" alt="${escapeHtml(camera.name)} live preview" />`;
    }
    return `<div class="cam-offline">${camera.status === 'active' ? 'Awaiting live preview…' : 'Camera offline'}</div>`;
  }

  function renderPersonCard(person) {
    return `
      <article class="person-card ${person.watchlist_status}">
        <img class="person-avatar" src="${getPersonImageUrl(person.id)}" alt="${escapeHtml(person.name)}" onerror="this.onerror=null;this.src='data:image/svg+xml;charset=UTF-8,${encodeURIComponent(defaultAvatarSvg(person.name))}'" />
        <div class="person-name">${escapeHtml(person.name)}</div>
        <div class="person-desc">${escapeHtml(person.description || 'No descriptive profile recorded yet.')}</div>
        <div class="flex justify-between items-center">
          ${renderWatchlistBadge(person.watchlist_status)}
          <button class="btn btn-outline btn-sm" data-action="view-person" data-person-id="${person.id}">Open</button>
        </div>
      </article>
    `;
  }

  function renderAlertItem(alert) {
    return `
      <div class="alert-item ${alert.severity}" data-action="goto-page" data-page="alerts">
        <span class="alert-dot ${alert.severity}"></span>
        <div style="flex:1;">
          <div class="alert-title">${escapeHtml(alert.title)}</div>
          <div class="alert-msg">${escapeHtml(alert.message)}</div>
        </div>
        <div class="alert-time">${formatRelativeTime(alert.triggered_at)}</div>
      </div>
    `;
  }

  function renderTimelineItem(event) {
    return `
      <div class="tl-item">
        <div class="tl-dot-wrap">
          <span class="tl-dot"></span>
          <span class="tl-line"></span>
        </div>
        <div style="flex:1;">
          <div class="tl-cam">${escapeHtml(event.camera_name)}</div>
          <div class="tl-loc">${escapeHtml(event.location || 'Unknown location')} • ${escapeHtml(event.zone || 'Unknown zone')}</div>
        </div>
        <div class="tl-time">${formatShortDate(event.entered_at)}</div>
      </div>
    `;
  }

  function renderSearchResult(result) {
    const scorePct = Math.max(0, Math.min(100, Math.round(result.similarity_score * 100)));
    return `
      <div class="search-result-item">
        <div class="sr-score">${scorePct}%</div>
        <div class="sr-info">
          <div class="sr-name">${escapeHtml(result.person_name)}</div>
          <div class="sr-meta">${formatWatchlistLabel(result.watchlist_status)} • ${result.last_seen_camera ? escapeHtml(result.last_seen_camera) : 'No recent sightings'} ${result.last_seen_timestamp ? `• ${formatShortDate(result.last_seen_timestamp)}` : ''}</div>
          <div class="progress-bar-wrap"><div class="progress-bar-fill" style="width:${scorePct}%;"></div></div>
        </div>
        <button class="btn btn-outline btn-sm" data-action="view-person" data-person-id="${result.person_id}">Profile</button>
      </div>
    `;
  }

  function renderUploadJob(job) {
    return `
      <article class="job-card">
        <div class="job-header">
          <div class="job-name">${escapeHtml(job.name || `Camera ${job.camera_id || 'N/A'}`)}</div>
          <span class="job-status ${escapeHtml(job.status || 'queued')}">${escapeHtml(job.status || 'queued')}</span>
        </div>
        <div class="person-desc">Progress: ${job.progress || 0}% • Frames: ${job.processed_frames || 0}/${job.total_frames || 0} • Detections: ${job.detections || 0}</div>
        ${job.error ? `<div class="text-red" style="margin-top:8px;font-size:12px;">${escapeHtml(job.error)}</div>` : ''}
      </article>
    `;
  }

  function renderMiniStat(label, value) {
    return `
      <div class="card" style="padding:14px;">
        <div class="stat-label">${escapeHtml(label)}</div>
        <div class="section-title">${escapeHtml(String(value))}</div>
      </div>
    `;
  }

  function renderDetectionsTable(detections) {
    return `
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Track</th>
              <th>Timestamp</th>
              <th>Face Conf.</th>
              <th>Re-ID</th>
              <th>Watchlist</th>
            </tr>
          </thead>
          <tbody>
            ${detections.map((detection) => `
              <tr>
                <td>#${detection.track_id || '—'}</td>
                <td>${formatShortDate(detection.timestamp)}</td>
                <td>${toPct(detection.face_confidence)}</td>
                <td>${toPct(detection.reid_confidence)}</td>
                <td>${detection.is_watchlist_hit ? '<span class="chip chip-error">HIT</span>' : '<span class="chip chip-inactive">NO</span>'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderCameraActivityTable(rows) {
    return `
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Camera</th>
              <th>Status</th>
              <th>Detections</th>
              <th>Watchlist Hits</th>
              <th>Zone</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((row) => `
              <tr>
                <td>${escapeHtml(row.name)}</td>
                <td>${renderCameraStatusChip(row.status)}</td>
                <td>${row.detections}</td>
                <td>${row.watchlist_hits}</td>
                <td>${escapeHtml(row.zone || 'Unknown')}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderHeatmap(points) {
    if (!points.length) {
      return renderEmptyState('No heatmap points available for this camera.');
    }

    const maxCount = Math.max(...points.map((point) => point.count), 1);
    const pointMap = new Map(points.map((point) => [`${point.x}-${point.y}`, point.count]));
    const cells = [];

    for (let y = 0; y < 10; y += 1) {
      for (let x = 0; x < 20; x += 1) {
        const count = pointMap.get(`${x}-${y}`) || 0;
        const alpha = count ? 0.08 + (count / maxCount) * 0.92 : 0.05;
        cells.push(`<div class="heatmap-cell" title="(${x}, ${y}) • ${count}" style="background:rgba(0,212,255,${alpha.toFixed(2)});"></div>`);
      }
    }

    return `<div class="heatmap-grid">${cells.join('')}</div>`;
  }

  function renderBarChart(points, valueKey) {
    if (!points.length) {
      return renderEmptyState('No chart data available yet.');
    }

    const maxValue = Math.max(...points.map((point) => point[valueKey] || 0), 1);
    return `
      <div class="chart-area">
        ${points.slice(-18).map((point) => {
          const value = point[valueKey] || 0;
          const height = Math.max(8, Math.round((value / maxValue) * 100));
          return `<div class="bar" title="${escapeHtml(point.time || '')}: ${value}" style="height:${height}%;background:linear-gradient(180deg, rgba(0,212,255,.95), rgba(124,58,237,.55));"></div>`;
        }).join('')}
      </div>
    `;
  }

  function renderWatchlistBadge(status) {
    const map = {
      suspect: 'badge badge-suspect',
      missing: 'badge badge-missing',
      person_of_interest: 'badge badge-poi',
      none: 'badge badge-none',
    };
    return `<span class="${map[status] || map.none}">${escapeHtml(formatWatchlistLabel(status))}</span>`;
  }

  function renderCameraStatusChip(status) {
    const chip = status === 'active' ? 'chip-active' : status === 'error' ? 'chip-error' : 'chip-inactive';
    return `<span class="chip ${chip}">${escapeHtml((status || 'inactive').toUpperCase())}</span>`;
  }

  function renderEmptyState(message) {
    return `
      <div class="empty-state">
        ${emptyIcon()}
        <div>${escapeHtml(message)}</div>
      </div>
    `;
  }

  function updateBadges() {
    const activeCount = state.cameras.filter((camera) => camera.status === 'active').length;
    const unacknowledged = state.alerts.filter((alert) => !alert.is_acknowledged).length;
    els.activeCamBadge.textContent = String(activeCount);
    els.alertCountBadge.textContent = String(unacknowledged);
    els.bellDot.classList.toggle('hidden', unacknowledged === 0);
  }

  async function handleDocumentSubmit(event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    if (form.id === 'add-person-form') {
      event.preventDefault();
      await submitAddPerson(form);
    }

    if (form.id === 'add-camera-form') {
      event.preventDefault();
      await submitAddCamera(form);
    }

    if (form.id === 'search-form') {
      event.preventDefault();
      await submitSearch(form);
    }

    if (form.id === 'enroll-face-form') {
      event.preventDefault();
      await submitFaceEnrollment(form);
    }

    if (form.id === 'upload-form') {
      event.preventDefault();
      await submitVideoUpload(form);
    }
  }

  function handleDocumentInput(event) {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    if (target.id === 'person-search-input') {
      state.personFilters.search = target.value;
      renderPersonsPage();
    }
  }

  async function handleDocumentChange(event) {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;

    if (target.id === 'person-filter-watchlist') {
      state.personFilters.watchlist = target.value;
      renderPersonsPage();
    }

    if (target.id === 'timeline-person-select') {
      state.selectedPersonId = Number(target.value);
      await loadSelectedPersonTimeline(true);
      renderTimelinePage();
    }

    if (target.id === 'search-file-input') {
      const label = document.getElementById('search-file-label');
      if (label) label.textContent = target.files?.[0]?.name || 'JPG, PNG, or WEBP images are accepted.';
    }

    if (target.id === 'upload-file-input') {
      const label = document.getElementById('upload-file-label');
      if (label) label.textContent = target.files?.[0]?.name || 'MP4, MOV, AVI, MKV and similar formats are supported.';
    }
  }

  async function handleDocumentClick(event) {
    const target = event.target instanceof HTMLElement ? event.target.closest('[data-action]') : null;
    if (!target) return;

    const action = target.dataset.action;

    if (action === 'goto-page') {
      navigate(target.dataset.page || 'dashboard');
      return;
    }

    if (action === 'refresh-all') {
      await refreshAllData();
      showToast('Dashboard synced', 'Latest backend data loaded successfully.');
      return;
    }

    if (action === 'open-add-person') {
      openAddPersonModal();
      return;
    }

    if (action === 'open-add-camera') {
      openAddCameraModal();
      return;
    }

    if (action === 'view-person') {
      const personId = Number(target.dataset.personId);
      openPersonModal(personId);
      return;
    }

    if (action === 'select-camera') {
      state.selectedCameraId = Number(target.dataset.cameraId);
      await loadSelectedCameraData(true);
      renderCamerasPage();
      return;
    }

    if (action === 'toggle-camera') {
      await toggleCamera(target.dataset.cameraId);
      return;
    }

    if (action === 'reload-camera') {
      await loadSelectedCameraData(true);
      showToast('Camera refreshed', 'Camera detections and stats were reloaded.');
      return;
    }

    if (action === 'reload-timeline') {
      await loadSelectedPersonTimeline(true);
      showToast('Timeline refreshed', 'Movement timeline reloaded.');
      return;
    }

    if (action === 'ack-alert') {
      const alertId = Number(target.dataset.alertId);
      await acknowledgeAlert(alertId);
      return;
    }

    if (action === 'close-modal') {
      closeModal();
    }
  }

  async function submitAddPerson(form) {
    const payload = Object.fromEntries(new FormData(form).entries());
    if (payload.age) payload.age = Number(payload.age);
    try {
      await api.createPerson(payload);
      closeModal();
      await refreshAllData();
      showToast('Person created', `${payload.name} has been added to the registry.`);
    } catch (error) {
      showToast('Create failed', formatError(error), 'error');
    }
  }

  async function submitAddCamera(form) {
    const payload = Object.fromEntries(new FormData(form).entries());
    if (payload.latitude) payload.latitude = Number(payload.latitude);
    if (payload.longitude) payload.longitude = Number(payload.longitude);
    if (payload.fps) payload.fps = Number(payload.fps);
    try {
      await api.addCamera(payload);
      closeModal();
      await refreshAllData();
      showToast('Camera added', `${payload.name} is now part of the network.`);
    } catch (error) {
      showToast('Camera creation failed', formatError(error), 'error');
    }
  }

  async function submitSearch(form) {
    const formData = new FormData(form);
    if (!formData.get('file') || !(formData.get('file') instanceof File) || !formData.get('file').name) {
      showToast('Image required', 'Choose an image before running the search.', 'error');
      return;
    }

    try {
      const topK = formData.get('top_k');
      const fileForm = new FormData();
      fileForm.append('file', formData.get('file'));
      const results = await api.postForm(`/persons/search/by-image?top_k=${encodeURIComponent(topK)}`, fileForm);
      state.searchResults = Array.isArray(results) ? results : [];
      renderSearchPage();
      showToast('Search complete', `${state.searchResults.length} matches returned.`);
    } catch (error) {
      showToast('Search failed', formatError(error), 'error');
    }
  }

  async function submitFaceEnrollment(form) {
    const personId = Number(form.dataset.personId);
    const fileInput = form.querySelector('input[type="file"]');
    const file = fileInput?.files?.[0];
    if (!file) {
      showToast('Image required', 'Choose a reference face image first.', 'error');
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await api.enrollFace(personId, formData);
      await refreshAllData();
      openPersonModal(personId);
      showToast('Enrollment complete', response.message || 'Face embedding generated successfully.');
    } catch (error) {
      showToast('Enrollment failed', formatError(error), 'error');
    }
  }

  async function submitVideoUpload(form) {
    const formData = new FormData(form);
    const file = formData.get('file');
    if (!(file instanceof File) || !file.name) {
      showToast('Video required', 'Choose a video before starting ingestion.', 'error');
      return;
    }

    try {
      const response = await api.uploadVideo(formData);
      state.uploadJobs.unshift({
        job_id: response.job_id,
        name: formData.get('camera_name') || file.name,
        status: response.status,
        progress: 0,
        processed_frames: 0,
        total_frames: 0,
        detections: 0,
        camera_id: response.camera_id,
      });
      renderUploadPage();
      pollJob(response.job_id, formData.get('camera_name') || file.name);
      showToast('Video queued', response.message || 'Upload job created.');
      form.reset();
    } catch (error) {
      showToast('Upload failed', formatError(error), 'error');
    }
  }

  async function toggleCamera(cameraIdValue) {
    const cameraId = Number(cameraIdValue);
    const camera = state.cameras.find((item) => item.id === cameraId);
    if (!camera) return;

    try {
      if (camera.status === 'active') {
        await api.stopStream(cameraId);
        showToast('Stream stopped', `${camera.name} stream stopped.`);
      } else {
        await api.startStream(cameraId);
        showToast('Stream started', `${camera.name} stream started.`);
      }
      await refreshAllData();
      scheduleRefresh();
    } catch (error) {
      showToast('Camera action failed', formatError(error), 'error');
    }
  }

  async function acknowledgeAlert(alertId) {
    try {
      await api.ackAlert(alertId);
      state.alerts = state.alerts.map((alert) => (
        alert.id === alertId ? { ...alert, is_acknowledged: true } : alert
      ));
      renderAlertsPage();
      renderDashboardPage();
      updateBadges();
      showToast('Alert acknowledged', `Alert #${alertId} marked as acknowledged.`);
    } catch (error) {
      showToast('Acknowledge failed', formatError(error), 'error');
    }
  }

  function openAddPersonModal() {
    openModal('Add Person', `
      <form id="add-person-form">
        <div class="grid-2">
          <div class="form-group">
            <label for="person-name">Name</label>
            <input id="person-name" name="name" type="text" required />
          </div>
          <div class="form-group">
            <label for="person-alias">Alias</label>
            <input id="person-alias" name="alias" type="text" />
          </div>
        </div>
        <div class="grid-2">
          <div class="form-group">
            <label for="person-age">Age</label>
            <input id="person-age" name="age" type="number" min="0" />
          </div>
          <div class="form-group">
            <label for="person-watchlist">Watchlist Status</label>
            <select id="person-watchlist" name="watchlist_status">
              <option value="none">None</option>
              <option value="missing">Missing</option>
              <option value="suspect">Suspect</option>
              <option value="person_of_interest">Person of Interest</option>
            </select>
          </div>
        </div>
        <div class="form-group">
          <label for="person-description">Description</label>
          <textarea id="person-description" name="description" placeholder="Physical description, clothing, identifying features"></textarea>
        </div>
        <div class="flex gap-2 justify-between">
          <button type="button" class="btn btn-outline" data-action="close-modal">Cancel</button>
          <button type="submit" class="btn btn-primary">Create Person</button>
        </div>
      </form>
    `);
  }

  function openAddCameraModal() {
    openModal('Add Camera', `
      <form id="add-camera-form">
        <div class="grid-2">
          <div class="form-group">
            <label for="camera-name">Name</label>
            <input id="camera-name" name="name" type="text" required />
          </div>
          <div class="form-group">
            <label for="camera-location">Location</label>
            <input id="camera-location" name="location" type="text" />
          </div>
        </div>
        <div class="form-group">
          <label for="camera-stream-url">Stream URL</label>
          <input id="camera-stream-url" name="stream_url" type="url" placeholder="rtsp://... or file path" />
        </div>
        <div class="grid-2">
          <div class="form-group">
            <label for="camera-zone">Zone</label>
            <input id="camera-zone" name="zone" type="text" />
          </div>
          <div class="form-group">
            <label for="camera-resolution">Resolution</label>
            <input id="camera-resolution" name="resolution" type="text" value="1920x1080" />
          </div>
        </div>
        <div class="grid-2">
          <div class="form-group">
            <label for="camera-fps">FPS</label>
            <input id="camera-fps" name="fps" type="number" step="0.1" value="25" />
          </div>
          <div class="form-group">
            <label for="camera-latitude">Latitude</label>
            <input id="camera-latitude" name="latitude" type="number" step="0.000001" />
          </div>
        </div>
        <div class="form-group">
          <label for="camera-longitude">Longitude</label>
          <input id="camera-longitude" name="longitude" type="number" step="0.000001" />
        </div>
        <div class="flex gap-2 justify-between">
          <button type="button" class="btn btn-outline" data-action="close-modal">Cancel</button>
          <button type="submit" class="btn btn-primary">Create Camera</button>
        </div>
      </form>
    `);
  }

  function openPersonModal(personId) {
    const person = state.persons.find((item) => item.id === personId);
    if (!person) return;
    const timeline = state.personTimelines[personId];
    if (!timeline) {
      void loadTimelineAndReopen(personId);
    }

    openModal(person.name, `
      <div class="grid-2" style="align-items:start;">
        <div>
          <img class="person-avatar" style="width:100%;height:220px;margin-bottom:14px;" src="${getPersonImageUrl(person.id)}" alt="${escapeHtml(person.name)}" onerror="this.onerror=null;this.src='data:image/svg+xml;charset=UTF-8,${encodeURIComponent(defaultAvatarSvg(person.name))}'" />
          <div class="person-desc">${escapeHtml(person.description || 'No descriptive profile recorded.')}</div>
          <div class="mt-4">${renderWatchlistBadge(person.watchlist_status)}</div>
        </div>
        <div>
          <div class="form-group">
            <label>Alias</label>
            <input type="text" value="${escapeHtml(person.alias || '—')}" disabled />
          </div>
          <div class="form-group">
            <label>Age</label>
            <input type="text" value="${person.age ?? '—'}" disabled />
          </div>
          <form id="enroll-face-form" data-person-id="${person.id}">
            <div class="form-group">
              <label for="enroll-face-input">Enroll / Replace Face Image</label>
              <input id="enroll-face-input" type="file" accept="image/*" />
            </div>
            <button class="btn btn-primary" type="submit">Generate Embedding</button>
          </form>
        </div>
      </div>
      <div class="mt-4">
        <div class="section-title">Recent Timeline</div>
        ${timeline ? `
          <div class="timeline-list" style="margin-top:12px;">
            ${timeline.events.slice(0, 5).map(renderTimelineItem).join('') || renderEmptyState('No timeline events recorded yet.')}
          </div>
        ` : '<div class="text-muted" style="margin-top:12px;">Loading timeline…</div>'}
      </div>
      <div class="flex gap-2 justify-between mt-4">
        <button type="button" class="btn btn-outline" data-action="close-modal">Close</button>
        <button type="button" class="btn btn-outline" data-action="goto-page" data-page="timeline">Open Full Timeline</button>
      </div>
    `);
  }

  async function loadTimelineAndReopen(personId) {
    state.selectedPersonId = personId;
    await loadSelectedPersonTimeline(true);
    openPersonModal(personId);
  }

  function openModal(title, body) {
    els.modalBox.innerHTML = `
      <div class="flex justify-between items-center" style="margin-bottom:20px;">
        <div class="modal-title" style="margin-bottom:0;">${escapeHtml(title)}</div>
        <button class="btn btn-outline btn-sm" data-action="close-modal">Close</button>
      </div>
      ${body}
    `;
    els.modalOverlay.classList.remove('hidden');
  }

  function closeModal() {
    els.modalOverlay.classList.add('hidden');
    els.modalBox.innerHTML = '';
  }

  function connectWebSocket() {
    const url = getWebSocketUrl();
    try {
      state.ws = new WebSocket(url);
      setWsStatus(false, 'Connecting…');

      state.ws.addEventListener('open', () => {
        setWsStatus(true, 'Live feed connected');
        if (state.pingTimer) window.clearInterval(state.pingTimer);
        state.pingTimer = window.setInterval(() => {
          if (state.ws && state.ws.readyState === WebSocket.OPEN) {
            state.ws.send(JSON.stringify({ type: 'ping', timestamp: new Date().toISOString() }));
          }
        }, WS_PING_INTERVAL_MS);
      });

      state.ws.addEventListener('message', (event) => {
        handleWsMessage(event.data);
      });

      state.ws.addEventListener('close', () => {
        setWsStatus(false, 'Disconnected');
        if (state.pingTimer) window.clearInterval(state.pingTimer);
        state.wsReconnectTimer = window.setTimeout(connectWebSocket, 3000);
      });

      state.ws.addEventListener('error', () => {
        setWsStatus(false, 'Connection error');
      });
    } catch (error) {
      setWsStatus(false, 'Unavailable');
      showToast('WebSocket unavailable', formatError(error), 'error');
    }
  }

  function handleWsMessage(payload) {
    let message;
    try {
      message = JSON.parse(payload);
    } catch (error) {
      return;
    }

    if (message.type === 'connected') {
      showToast('Realtime connected', message.message || 'WebSocket channel is active.');
      return;
    }

    if (message.type === 'frame' && message.camera_id && message.frame_b64) {
      state.liveFrames[message.camera_id] = `data:image/jpeg;base64,${message.frame_b64}`;
      state.cameraStats[message.camera_id] = {
        ...(state.cameraStats[message.camera_id] || { camera_id: message.camera_id }),
        fps: message.fps || 0,
        running: true,
        detections: message.detections || 0,
      };
      renderDashboardPage();
      if (state.currentPage === 'cameras') renderCamerasPage();
      return;
    }

    if (message.type === 'alert') {
      const alert = {
        id: message.data?.alert_id || Date.now(),
        title: `Realtime Alert • ${message.data?.person_name || 'Unknown person'}`,
        message: message.data?.message || 'Watchlist alert received.',
        severity: message.data?.severity || 'high',
        is_acknowledged: false,
        triggered_at: new Date().toISOString(),
        person_id: message.data?.person_id,
        camera_id: message.data?.camera_id,
        person_name: message.data?.person_name,
        camera_name: `Camera ${message.data?.camera_id || 'N/A'}`,
      };
      state.alerts.unshift(alert);
      state.alerts = state.alerts.slice(0, 50);
      renderDashboardPage();
      renderAlertsPage();
      updateBadges();
      showToast(alert.title, alert.message, 'alert');
      scheduleRefresh();
      return;
    }

    if (message.type === 'detection' || message.type === 'stats') {
      scheduleRefresh();
    }
  }

  function scheduleRefresh() {
    if (state.refreshTimer) {
      window.clearTimeout(state.refreshTimer);
    }
    state.refreshTimer = window.setTimeout(() => {
      void refreshAllData();
    }, 1500);
  }

  async function pollJob(jobId, name) {
    try {
      const job = await api.jobStatus(jobId);
      upsertJob({ ...job, job_id: jobId, name });
      renderUploadPage();
      if (job.status === 'queued' || job.status === 'processing') {
        window.setTimeout(() => pollJob(jobId, name), 2000);
      } else {
        scheduleRefresh();
      }
    } catch (error) {
      upsertJob({ job_id: jobId, name, status: 'failed', error: formatError(error) });
      renderUploadPage();
    }
  }

  function upsertJob(job) {
    const index = state.uploadJobs.findIndex((item) => item.job_id === job.job_id);
    if (index >= 0) {
      state.uploadJobs[index] = { ...state.uploadJobs[index], ...job };
    } else {
      state.uploadJobs.unshift(job);
    }
  }

  function normaliseJobs(response) {
    const jobs = response && Array.isArray(response.jobs) ? response.jobs : [];
    return jobs.map((job, index) => ({
      job_id: job.job_id || `server-job-${index}`,
      name: job.name || `Camera ${job.camera_id || 'N/A'}`,
      ...job,
    }));
  }

  async function requestOrFallback(promise, fallback, quiet = false) {
    try {
      return await promise;
    } catch (error) {
      if (!quiet) {
        showToast('Backend request failed', formatError(error), 'error');
      }
      return fallback;
    }
  }

  function showToast(title, message, tone = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${tone === 'alert' || tone === 'error' ? 'alert-toast' : ''}`;
    toast.innerHTML = `
      <div class="toast-icon">${tone === 'error' ? alertIcon() : tone === 'alert' ? bellIcon() : infoIcon()}</div>
      <div class="toast-body">
        <div class="toast-title">${escapeHtml(title)}</div>
        <div class="toast-msg">${escapeHtml(message)}</div>
      </div>
    `;
    els.toastContainer.appendChild(toast);
    window.setTimeout(() => {
      toast.remove();
    }, 4500);
  }

  function setWsStatus(connected, label) {
    state.wsConnected = connected;
    els.wsDot.classList.toggle('offline', !connected);
    els.wsLabel.textContent = label;
  }

  function startClock() {
    const update = () => {
      els.datetime.textContent = new Intl.DateTimeFormat(appLocale, {
        dateStyle: 'medium',
        timeStyle: 'medium',
      }).format(new Date());
    };
    update();
    window.setInterval(update, 1000);
  }

  function getEmptyDashboard() {
    return {
      total_persons: 0,
      watchlisted_persons: 0,
      missing_persons: 0,
      suspects: 0,
      active_cameras: 0,
      total_cameras: 0,
      alerts_today: 0,
      unacknowledged_alerts: 0,
      detections_today: 0,
      detections_last_hour: 0,
    };
  }

  function getPersonImageUrl(personId) {
    return `${window.location.protocol === 'file:' ? 'http://localhost:8000' : ''}/api/v1/persons/${personId}/face-image`;
  }

  function getWebSocketUrl() {
    if (window.location.protocol === 'file:') {
      return 'ws://localhost:8000/ws';
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/ws`;
  }

  function formatWatchlistLabel(status) {
    const labels = {
      none: 'No Watchlist',
      missing: 'Missing',
      suspect: 'Suspect',
      person_of_interest: 'Person of Interest',
    };
    return labels[status] || status || 'Unknown';
  }

  function formatRelativeTime(value) {
    if (!value) return 'Unknown';
    const diffMs = Date.now() - new Date(value).getTime();
    const minutes = Math.round(diffMs / 60000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.round(hours / 24);
    return `${days}d ago`;
  }

  function formatShortDate(value) {
    if (!value) return '—';
    return new Intl.DateTimeFormat(appLocale, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(value));
  }

  function formatDuration(seconds) {
    if (!seconds) return '0s';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    if (hrs > 0) return `${hrs}h ${mins}m`;
    if (mins > 0) return `${mins}m`;
    return `${Math.round(seconds)}s`;
  }

  function formatError(error) {
    if (!error) return 'Unknown error';
    if (typeof error === 'string') return error;
    if (error instanceof Error) return error.message;
    return JSON.stringify(error);
  }

  function toPct(value) {
    if (value == null) return '—';
    return `${Math.round(Number(value) * 100)}%`;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function defaultAvatarSvg(name) {
    const initial = escapeHtml((name || '?').trim().charAt(0).toUpperCase() || '?');
    return `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="320" viewBox="0 0 320 320"><rect width="320" height="320" rx="24" fill="#111d35"/><circle cx="160" cy="118" r="54" fill="#00d4ff" fill-opacity="0.18"/><circle cx="160" cy="118" r="36" fill="#00d4ff" fill-opacity="0.48"/><text x="160" y="225" font-family="Inter, Arial, sans-serif" font-size="92" fill="#00d4ff" text-anchor="middle">${initial}</text></svg>`;
  }

  function cameraIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 7l-7 5 7 5V7z"></path><rect x="1" y="5" width="15" height="14" rx="2"></rect></svg>';
  }

  function personIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>';
  }

  function userSearchIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>';
  }

  function shieldIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>';
  }

  function pulseIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>';
  }

  function uploadIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 16 12 12 8 16"></polyline><line x1="12" y1="12" x2="12" y2="21"></line><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"></path></svg>';
  }

  function alertIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>';
  }

  function bellIcon() {
    return alertIcon();
  }

  function infoIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
  }

  function emptyIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"></circle><path d="M9 9h.01"></path><path d="M15 9h.01"></path><path d="M8 15c1.5-1 2.67-1.5 4-1.5s2.5.5 4 1.5"></path></svg>';
  }
})();
