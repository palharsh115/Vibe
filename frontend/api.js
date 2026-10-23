// This is the only frontend file that makes HTTP requests.
(function () {
  const base = window.VIBE_CONFIG.API_BASE_URL.replace(/\/$/, '');
  function token() { return sessionStorage.getItem('vibe_access_token'); }
  async function request(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (token()) headers.Authorization = `Bearer ${token()}`;
    let response;
    try {
      response = await fetch(`${base}${path}`, { ...options, headers });
    } catch (_) {
      throw new Error('Cannot reach the Vibe API. Start the backend and try again.');
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || 'Request failed. Please try again.');
    return body;
  }
  window.VibeAPI = {
    register: (payload) => request('/auth/register', { method: 'POST', body: JSON.stringify(payload) }),
    login: (payload) => request('/auth/login', { method: 'POST', body: JSON.stringify(payload) }),
    me: () => request('/me'),
    preferences: (payload) => request('/preferences', { method: 'PATCH', body: JSON.stringify(payload) }),
    location: (payload) => request('/location', { method: 'POST', body: JSON.stringify(payload) }),
    findMatch: () => request('/match', { method: 'POST' }),
    matchStatus: () => request('/match/status'),
    cancelMatch: () => request('/match/cancel', { method: 'POST' }),
    reportMatch: (payload) => request('/safety/report', { method: 'POST', body: JSON.stringify(payload) }),
    blockMatch: () => request('/safety/block', { method: 'POST' }),
    connectChat: (matchId, handlers = {}) => {
      const accessToken = token();
      if (!accessToken) throw new Error('Sign in to open chat.');
      const wsBase = base.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:');
      const socket = new WebSocket(`${wsBase}/ws/chat?token=${encodeURIComponent(accessToken)}&match_id=${encodeURIComponent(matchId)}`);
      socket.addEventListener('open', () => handlers.onOpen?.());
      socket.addEventListener('message', event => {
        try { handlers.onMessage?.(JSON.parse(event.data)); }
        catch (_) { handlers.onError?.('Received an unreadable chat message.'); }
      });
      socket.addEventListener('error', () => handlers.onError?.('Could not connect to chat. Check that the backend is running.'));
      socket.addEventListener('close', event => handlers.onClose?.(event));
      return socket;
    },
    logout: () => request('/auth/logout', { method: 'POST' }),
    setToken: (value) => value ? sessionStorage.setItem('vibe_access_token', value) : sessionStorage.removeItem('vibe_access_token'),
    hasToken: () => Boolean(token())
  };
})();
