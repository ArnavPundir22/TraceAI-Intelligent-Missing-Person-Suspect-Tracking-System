/* TraceAI API Client */
const API_BASE = 'http://localhost:8000/api/v1';

const api = {
  async get(path) {
    const r = await fetch(API_BASE + path);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(API_BASE + path, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async postForm(path, formData) {
    const r = await fetch(API_BASE + path, { method: 'POST', body: formData });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async put(path, body) {
    const r = await fetch(API_BASE + path, {
      method: 'PUT', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async del(path) {
    const r = await fetch(API_BASE + path, { method: 'DELETE' });
    return r.ok;
  },

  // Domain helpers
  dashboard: () => api.get('/analytics/dashboard'),
  persons: (params='') => api.get('/persons/' + params),
  person: (id) => api.get(`/persons/${id}`),
  createPerson: (data) => api.post('/persons/', data),
  updatePerson: (id, data) => api.put(`/persons/${id}`, data),
  enrollFace: (id, form) => api.postForm(`/persons/${id}/enroll-face`, form),
  searchByImage: (form) => api.postForm('/persons/search/by-image', form),
  timeline: (id) => api.get(`/persons/${id}/timeline`),
  cameras: () => api.get('/cameras/'),
  addCamera: (data) => api.post('/cameras/', data),
  startStream: (id) => api.post(`/cameras/${id}/start`, {}),
  stopStream: (id) => api.post(`/cameras/${id}/stop`, {}),
  detections: (camId, h=24) => api.get(`/cameras/${camId}/detections?hours=${h}`),
  heatmap: (camId) => api.get(`/cameras/${camId}/heatmap`),
  alerts: (limit=30) => api.get(`/analytics/alerts/recent?limit=${limit}`),
  ackAlert: (id) => api.post(`/analytics/alerts/${id}/acknowledge`, {}),
  detectionTimeline: (h=24) => api.get(`/analytics/detections/timeline?hours=${h}`),
  watchlistActivity: () => api.get('/analytics/watchlist/activity'),
  cameraActivity: () => api.get('/analytics/cameras/activity-summary'),
  uploadVideo: (form) => api.postForm('/upload/video', form),
  jobStatus: (id) => api.get(`/upload/jobs/${id}`),
};
