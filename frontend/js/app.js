/* SnapCloud — shared JS utilities */

const API = window.API_BASE || '';

/* ── TOKEN / AUTH ── */
const Auth = {
  token: () => localStorage.getItem('sc_token'),
  user:  () => { try { return JSON.parse(localStorage.getItem('sc_user')); } catch { return null; } },
  save:  (token, user) => { localStorage.setItem('sc_token', token); localStorage.setItem('sc_user', JSON.stringify(user)); },
  clear: () => { localStorage.removeItem('sc_token'); localStorage.removeItem('sc_user'); },
  isLoggedIn: () => !!localStorage.getItem('sc_token'),
  isCreator:  () => { const u = Auth.user(); return u && u.role === 'creator'; },
  isConsumer: () => { const u = Auth.user(); return u && u.role === 'consumer'; },
  requireAuth: (role) => {
    if (!Auth.isLoggedIn()) { window.location.href = 'index.html'; return false; }
    if (role === 'creator' && !Auth.isCreator()) { window.location.href = 'consumer.html'; return false; }
    if (role === 'consumer' && !Auth.isConsumer()) { window.location.href = 'creator.html'; return false; }
    return true;
  }
};

/* ── HTTP helpers ── */
async function apiFetch(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (Auth.token()) headers['Authorization'] = 'Bearer ' + Auth.token();
  if (opts.body instanceof FormData) delete headers['Content-Type'];
  const res = await fetch(API + '/api' + path, { ...opts, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Request failed');
  return data;
}

/* ── TOAST ── */
function toast(msg, type = 'success', duration = 3000) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

/* ── NAVBAR init ── */
function initNavbar() {
  const user = Auth.user();
  if (!user) return;
  const initials = user.name ? user.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2) : 'U';
  const navUser = document.getElementById('nav-user-info');
  if (navUser) {
    navUser.innerHTML = `
      <div class="avatar ${user.role}">${initials}</div>
      <span>${user.name}</span>
      <span class="nav-role-badge ${user.role}">${user.role}</span>`;
  }
  const logoutBtn = document.getElementById('nav-logout');
  if (logoutBtn) logoutBtn.addEventListener('click', () => { Auth.clear(); window.location.href = 'index.html'; });
}

/* ── STAR rendering ── */
function renderStars(rating, max = 5) {
  let html = '<span class="stars">';
  for (let i = 1; i <= max; i++) {
    const cls = i <= Math.round(rating) ? 'full' : 'empty';
    html += `<svg class="star-icon ${cls}" viewBox="0 0 20 20"><path fill="currentColor" d="M10 1l2.39 4.84 5.34.78-3.86 3.77.91 5.32L10 13.27l-4.78 2.44.91-5.32L2.27 6.62l5.34-.78L10 1z"/></svg>`;
  }
  html += '</span>';
  return html;
}

/* ── TAG INPUT widget ── */
function initTagInput(wrapId, hiddenId) {
  const wrap = document.getElementById(wrapId);
  const hidden = document.getElementById(hiddenId);
  if (!wrap || !hidden) return;
  const input = wrap.querySelector('.tag-bare-input');
  let tags = [];

  function render() {
    wrap.querySelectorAll('.tag-chip').forEach(c => c.remove());
    tags.forEach((t, i) => {
      const chip = document.createElement('span');
      chip.className = 'tag-chip';
      chip.innerHTML = `${t}<button class="tag-chip-remove" data-i="${i}">✕</button>`;
      wrap.insertBefore(chip, input);
    });
    hidden.value = tags.join(',');
  }

  input.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) {
      e.preventDefault();
      tags.push(input.value.trim().replace(/,/g, ''));
      input.value = '';
      render();
    }
    if (e.key === 'Backspace' && !input.value && tags.length) {
      tags.pop(); render();
    }
  });

  wrap.addEventListener('click', e => {
    if (e.target.classList.contains('tag-chip-remove')) {
      tags.splice(+e.target.dataset.i, 1); render();
    }
    input.focus();
  });
}

/* ── DROP ZONE ── */
function initDropZone(zoneId, inputId, previewId) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  const preview = document.getElementById(previewId);
  if (!zone || !input) return;

  zone.addEventListener('click', () => input.click());
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('over');
    if (e.dataTransfer.files[0]) showPreview(e.dataTransfer.files[0]);
  });
  input.addEventListener('change', () => { if (input.files[0]) showPreview(input.files[0]); });

  function showPreview(file) {
    const reader = new FileReader();
    reader.onload = e => {
      if (preview) { preview.src = e.target.result; document.getElementById('preview-wrap').style.display = 'block'; }
    };
    reader.readAsDataURL(file);
  }
}

/* ── MODAL helpers ── */
function openModal(id) { document.getElementById(id).classList.add('open'); document.body.style.overflow = 'hidden'; }
function closeModal(id) { document.getElementById(id).classList.remove('open'); document.body.style.overflow = ''; }
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) closeModal(e.target.id);
});

/* ── TIME formatting ── */
function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr);
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

/* ── Photo placeholder colours ── */
const PHOTO_COLORS = [
  'linear-gradient(135deg,#667eea,#764ba2)',
  'linear-gradient(135deg,#f093fb,#f5576c)',
  'linear-gradient(135deg,#4facfe,#00f2fe)',
  'linear-gradient(135deg,#43e97b,#38f9d7)',
  'linear-gradient(135deg,#fa709a,#fee140)',
  'linear-gradient(135deg,#a18cd1,#fbc2eb)',
  'linear-gradient(135deg,#ffecd2,#fcb69f)',
  'linear-gradient(135deg,#84fab0,#8fd3f4)',
];
function photoColor(id) { return PHOTO_COLORS[(id || 0) % PHOTO_COLORS.length]; }

function imgOrGradient(url, id) {
  if (url) return `<img src="${url}" alt="" class="feed-card-img" loading="lazy">`;
  return `<div class="feed-card-img" style="background:${photoColor(id)}"></div>`;
}
