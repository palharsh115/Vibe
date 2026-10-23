(function () {
  const screens = [...document.querySelectorAll('.screen')];
  const $ = (id) => document.getElementById(id);
  let intent = 'Just talk';
  let locationEnabled = false;
  let selectedVibes = new Set(['Funny']);
  let authMode = 'register';
  let searching = false;
  let matched = false;
  let pollTimer = null;
  let chatSocket = null;
  let currentMatchId = null;

  function showScreen(id) {
    screens.forEach(s => s.classList.toggle('active', s.id === id));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  function toast(message) {
    const t = $('toast'); t.textContent = message; t.classList.add('show');
    clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove('show'), 3000);
  }
  function setAuthError(message = '') { $('authError').textContent = message; }
  function setAuthMode(mode) {
    authMode = mode;
    const registering = mode === 'register';
    $('authModeLabel').textContent = registering ? 'GET STARTED' : 'WELCOME BACK';
    $('authTitle').textContent = registering ? 'Create your account' : 'Sign in to Vibe';
    $('authSubmitLabel').textContent = registering ? 'Create account' : 'Sign in';
    $('birthDateWrap').hidden = !registering;
    $('birthDate').required = registering;
    $('authPassword').autocomplete = registering ? 'new-password' : 'current-password';
    $('toggleAuthMode').textContent = registering ? 'Already have an account? Sign in' : 'New to Vibe? Create an account';
    setAuthError('');
  }
  function showSignedIn() {
    $('logoutBtn').hidden = false;
    showScreen('homeScreen');
  }
  async function savePreferences() {
    return VibeAPI.preferences({ intent, vibes: [...selectedVibes], radius_km: Number($('radius').value) });
  }
  function clearPoll() { if (pollTimer) clearTimeout(pollTimer); pollTimer = null; }
  function appendChatMessage(message) {
    const content = $('chatContent');
    const row = document.createElement('div');
    row.className = `message-row ${message.sender_label === 'You' ? 'mine' : 'other'}`;
    if (message.sender_label !== 'You') {
      const avatar = document.createElement('span'); avatar.className = 'mini-avatar'; avatar.textContent = '?'; row.appendChild(avatar);
    }
    const wrapper = document.createElement('div');
    if (message.sender_label !== 'You') {
      const sender = document.createElement('span'); sender.className = 'sender'; sender.textContent = 'Stranger'; wrapper.appendChild(sender);
    }
    const bubble = document.createElement('div'); bubble.className = 'bubble'; bubble.textContent = message.content;
    wrapper.appendChild(bubble); row.appendChild(wrapper); content.appendChild(row);
    content.scrollTop = content.scrollHeight;
  }
  function closeChatSocket() {
    if (chatSocket) { chatSocket.close(); chatSocket = null; }
  }
  function openRealChat(status) {
    currentMatchId = status.match_id;
    closeChatSocket();
    $('chatContent').replaceChildren();
    const divider = document.createElement('div'); divider.className = 'time-divider'; divider.textContent = 'LIVE ANONYMOUS CHAT'; $('chatContent').appendChild(divider);
    const system = document.createElement('div'); system.className = 'system-message'; system.textContent = 'You are connected anonymously. Keep personal details private.'; $('chatContent').appendChild(system);
    const statusLine = document.querySelector('#chatScreen .room-info small');
    statusLine.textContent = 'Connecting securely…';
    $('chatInput').disabled = true;
    $('chatScreen').querySelector('.chat-footnote').textContent = 'Live chat is active. Never share your home address, passwords, or financial information.';
    showScreen('chatScreen');
    try {
      chatSocket = VibeAPI.connectChat(status.match_id, {
        onOpen: () => { statusLine.textContent = 'Live · Anonymous'; $('chatInput').disabled = false; $('chatInput').focus(); },
        onMessage: data => {
          if (data.type === 'history') data.messages.forEach(appendChatMessage);
          else if (data.type === 'message') appendChatMessage(data);
          else if (data.type === 'error' || data.type === 'ended') toast(data.message || 'This chat has ended.');
        },
        onError: message => { statusLine.textContent = 'Connection problem'; toast(message); },
        onClose: () => { $('chatInput').disabled = true; if (currentMatchId) statusLine.textContent = 'Chat disconnected'; }
      });
    } catch (error) { toast(error.message); }
  }
  function displayMatch(status) {
    searching = false; matched = true; clearPoll();
    $('matchingDescription').textContent = 'You have been matched with an anonymous nearby person whose preferences are compatible with yours.';
    $('matchingStatusText').textContent = 'Match found! Opening your anonymous chat…';
    $('matchNotice').textContent = 'Match found. Opening your live anonymous conversation.';
    $('cancelMatch').innerHTML = '<span>End match and return</span><span class="arrow">↗</span>';
    toast('Match found. Opening live chat.');
    openRealChat(status);
  }
  async function pollMatch() {
    if (!searching) return;
    try {
      const result = await VibeAPI.matchStatus();
      if (result.status === 'matched') { displayMatch(result); return; }
      $('matchingStatusText').textContent = 'Still looking for an available compatible person nearby…';
    } catch (error) {
      $('matchingStatusText').textContent = error.message;
    }
    if (searching) pollTimer = setTimeout(pollMatch, 3000);
  }
  async function startMatching() {
    if (!locationEnabled) { toast('Enable location sharing first to find nearby people.'); return; }
    try {
      await savePreferences();
      const result = await VibeAPI.findMatch();
      showScreen('matchingScreen');
      matched = false;
      if (result.status === 'matched') { displayMatch(result); return; }
      searching = true;
      $('matchingDescription').textContent = `Looking for a ${intent.toLowerCase()} conversation${selectedVibes.size ? ` with a ${[...selectedVibes].join(', ').toLowerCase()} vibe` : ''} within ${$('radius').value} km.`;
      $('matchSummary').textContent = [intent, ...selectedVibes].join(' · ');
      $('matchingStatusText').textContent = 'You are in the matching queue. We will keep checking for compatible people.';
      $('matchNotice').innerHTML = '<strong>Searching for real users</strong><br>Only accounts that are available, compatible, and within both selected radii can match. Exact coordinates are not displayed.';
      $('cancelMatch').innerHTML = '<span>Cancel search</span><span class="arrow">×</span>';
      pollTimer = setTimeout(pollMatch, 3000);
    } catch (error) { toast(error.message); }
  }

  $('toggleAuthMode').addEventListener('click', () => setAuthMode(authMode === 'register' ? 'login' : 'register'));
  $('authForm').addEventListener('submit', async (event) => {
    event.preventDefault(); setAuthError('');
    const payload = { email: $('authEmail').value.trim(), password: $('authPassword').value };
    try {
      const result = authMode === 'register'
        ? await VibeAPI.register({ ...payload, birth_date: $('birthDate').value })
        : await VibeAPI.login(payload);
      VibeAPI.setToken(result.access_token);
      showSignedIn();
      toast(authMode === 'register' ? 'Account created. Welcome to Vibe.' : 'You are signed in.');
    } catch (error) { setAuthError(error.message); }
  });
  $('logoutBtn').addEventListener('click', async () => {
    closeChatSocket(); currentMatchId = null; clearPoll(); searching = false; matched = false;
    try { if (VibeAPI.hasToken()) await VibeAPI.logout(); } catch (_) { /* Expired sessions can still be cleared locally. */ }
    VibeAPI.setToken(null); locationEnabled = false; $('locationStatus').textContent = 'Location is off until you choose to share it.';
    $('logoutBtn').hidden = true; setAuthMode('login'); showScreen('authScreen'); toast('Signed out.');
  });

  document.querySelectorAll('#intentChoices .choice').forEach(button => button.addEventListener('click', () => {
    intent = button.dataset.value;
    document.querySelectorAll('#intentChoices .choice').forEach(b => b.classList.toggle('selected', b === button));
  }));
  document.querySelectorAll('#vibeChoices .chip').forEach(button => button.addEventListener('click', () => {
    const value = button.dataset.value;
    if (selectedVibes.has(value)) { selectedVibes.delete(value); button.classList.remove('selected'); }
    else { selectedVibes.add(value); button.classList.add('selected'); }
  }));
  $('radius').addEventListener('input', e => $('radiusValue').textContent = e.target.value);

  $('locationBtn').addEventListener('click', async () => {
    if (!VibeAPI.hasToken()) { toast('Sign in first.'); return; }
    if (locationEnabled) {
      try {
        await VibeAPI.location({ latitude: 0, longitude: 0, consent: false });
        locationEnabled = false;
        $('locationStatus').textContent = 'Location sharing is off. Your saved coordinates were removed.';
        $('locationBtn').textContent = 'Enable';
        toast('Location sharing disabled and coordinates removed.');
      } catch (error) { toast(error.message); }
      return;
    }
    if (!navigator.geolocation) { toast('This browser does not support location.'); return; }
    $('locationStatus').textContent = 'Waiting for your permission…';
    navigator.geolocation.getCurrentPosition(async (position) => {
      try {
        await VibeAPI.location({ latitude: position.coords.latitude, longitude: position.coords.longitude, consent: true });
        locationEnabled = true;
        $('locationStatus').textContent = 'Enabled — used privately for matching, never shown to other users.';
        $('locationBtn').textContent = 'Disable';
        toast('Location sharing enabled for nearby matching.');
      } catch (error) {
        $('locationStatus').textContent = 'Could not save location. Please try again.'; toast(error.message);
      }
    }, () => {
      locationEnabled = false; $('locationStatus').textContent = 'Permission not granted. Nearby matching needs location consent.';
      toast('Location was not shared. You can enable it whenever you are ready.');
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 });
  });

  $('findBtn').addEventListener('click', startMatching);
  $('cancelMatch').addEventListener('click', async () => {
    closeChatSocket(); currentMatchId = null; clearPoll(); searching = false;
    try { await VibeAPI.cancelMatch(); } catch (error) { toast(error.message); }
    matched = false; showScreen('homeScreen'); toast('Search or match ended.');
  });
  document.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', () => showScreen(button.dataset.go)));
  $('openDemoChat')?.addEventListener('click', () => toast('Live chat is not available until Stage 3.'));
  $('chatForm').addEventListener('submit', event => {
    event.preventDefault();
    const input = $('chatInput'); const content = input.value.trim();
    if (!content) return;
    if (!chatSocket || chatSocket.readyState !== WebSocket.OPEN) { toast('Chat is not connected yet. Please wait or reconnect.'); return; }
    chatSocket.send(JSON.stringify({ type: 'message', content })); input.value = '';
  });
  $('meetBtn').addEventListener('click', () => showScreen('meetScreen'));
  $('backToChat').addEventListener('click', () => showScreen('chatScreen'));
  $('endChatBtn').addEventListener('click', async () => {
    closeChatSocket(); currentMatchId = null;
    try { await VibeAPI.cancelMatch(); } catch (error) { toast(error.message); }
    showScreen('homeScreen'); toast('Chat ended.');
  });
  $('blockBtn').addEventListener('click', async () => {
    if (!currentMatchId) { toast('There is no active match to block.'); return; }
    if (!window.confirm('Block this person? The chat will end and you will not be matched with them again.')) return;
    try {
      const result = await VibeAPI.blockMatch();
      closeChatSocket(); currentMatchId = null; clearPoll(); searching = false; matched = false;
      showScreen('homeScreen'); toast(result.message || 'User blocked.');
    } catch (error) { toast(error.message); }
  });
  async function submitReport() {
    if (!currentMatchId) { toast('There is no active match to report.'); return; }
    const reason = window.prompt('Choose a reason: harassment, hate_or_threats, sexual_content, spam_or_scam, underage_concern, other');
    if (!reason) return;
    const normalized = reason.trim().toLowerCase().replace(/[ -]+/g, '_');
    const allowed = ['harassment','hate_or_threats','sexual_content','spam_or_scam','underage_concern','other'];
    if (!allowed.includes(normalized)) { toast('Please enter one of the listed report reasons.'); return; }
    const details = window.prompt('Optional details (up to 500 characters):') || '';
    try {
      const result = await VibeAPI.reportMatch({ reason: normalized, details: details.slice(0, 500) });
      toast(result.message || 'Report submitted.');
    } catch (error) { toast(error.message); }
  }
  $('reportBtn').addEventListener('click', submitReport);
  $('blockBtn').addEventListener('contextmenu', event => { event.preventDefault(); submitReport(); });
  const dialog = $('infoDialog');
  $('safetyBtn').addEventListener('click', () => dialog.showModal());
  $('closeDialog').addEventListener('click', () => dialog.close());
  $('dialogDone').addEventListener('click', () => dialog.close());

  // Restore only the temporary browser session; the API validates it before showing the app.
  (async function init() {
    setAuthMode('register');
    if (!VibeAPI.hasToken()) return showScreen('authScreen');
    try {
      const state = await VibeAPI.me();
      locationEnabled = state.location_enabled;
      if (locationEnabled) { $('locationStatus').textContent = 'Enabled — used privately for matching, never shown to other users.'; $('locationBtn').textContent = 'Disable'; }
      showSignedIn();
    } catch (_) { VibeAPI.setToken(null); showScreen('authScreen'); }
  })();
})();
