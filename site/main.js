'use strict';

// ── Countdown timer ─────────────────────────────────────────────────
// Set your launch date here (ISO 8601)
const LAUNCH_DATE = new Date('2026-04-01T00:00:00');

const cdDays  = document.getElementById('cd-days');
const cdHours = document.getElementById('cd-hours');
const cdMins  = document.getElementById('cd-mins');
const cdSecs  = document.getElementById('cd-secs');

function pad(n) { return String(n).padStart(2, '0'); }

function tick() {
  const diff = LAUNCH_DATE - Date.now();
  if (diff <= 0) {
    cdDays.textContent = cdHours.textContent =
    cdMins.textContent = cdSecs.textContent = '00';
    return;
  }
  const days  = Math.floor(diff / 864e5);
  const hours = Math.floor((diff % 864e5) / 36e5);
  const mins  = Math.floor((diff % 36e5)  / 6e4);
  const secs  = Math.floor((diff % 6e4)   / 1e3);

  cdDays.textContent  = pad(days);
  cdHours.textContent = pad(hours);
  cdMins.textContent  = pad(mins);
  cdSecs.textContent  = pad(secs);
}

tick();
setInterval(tick, 1000);

// ── Email signup ─────────────────────────────────────────────────────
const form    = document.getElementById('signup-form');
const btn     = document.getElementById('signup-btn');
const input   = document.getElementById('email-input');
const success = document.getElementById('signup-success');
const note    = document.getElementById('signup-note');
const errEl   = document.getElementById('signup-error');

function showInputError(msg) {
  errEl.textContent = msg;
  errEl.style.display = 'block';
  input.classList.add('signup-form__input--error');
  input.setAttribute('aria-invalid', 'true');
  input.focus();
}

function clearInputError() {
  errEl.style.display = 'none';
  errEl.textContent = '';
  input.classList.remove('signup-form__input--error');
  input.removeAttribute('aria-invalid');
}

// Clear error state as soon as the user edits the field
input.addEventListener('input', clearInputError);

// ── Bot heuristics ────────────────────────────────────────────────────
// Replace with your Cloudflare Turnstile site key (cloudflare.com/products/turnstile)
const TURNSTILE_SITE_KEY = '0x4AAAAAACiMVM_vMYh7m0Bf';

const _h = {
  pageLoad:   Date.now(),
  firstInput: null,
  hadPointer: false,
  hadKey:     false,
};

document.addEventListener('mousemove',  () => { _h.hadPointer = true; }, { once: true, passive: true });
document.addEventListener('touchstart', () => { _h.hadPointer = true; }, { once: true, passive: true });

input.addEventListener('keydown', () => {
  _h.hadKey = true;
  if (!_h.firstInput) _h.firstInput = Date.now();
}, { once: true });

input.addEventListener('paste', () => {
  _h.hadKey = true;
  if (!_h.firstInput) _h.firstInput = Date.now();
}, { once: true });

function isSuspicious() {
  // Honeypot filled
  if (document.getElementById('website').value) return true;
  const now = Date.now();
  // Page submitted < 3 s after load
  if (now - _h.pageLoad < 3000) return true;
  // Email typed in < 1.5 s
  if (_h.firstInput && now - _h.firstInput < 1500) return true;
  // No pointer or keyboard interaction at all
  if (!_h.hadPointer && !_h.hadKey) return true;
  return false;
}

// ── Turnstile (lazy-loaded only when suspicious) ──────────────────────
let _captchaToken = null;
let _captchaReady = false;

window._onCaptchaSolve = (token) => {
  _captchaToken = token;
  _doSubmit();
};

function _showCaptcha() {
  const wrap = document.getElementById('captcha-wrap');
  wrap.style.display = 'block';
  if (_captchaReady) return;
  const s = document.createElement('script');
  s.src   = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
  s.async = true;
  s.onload = () => {
    turnstile.render('#captcha-wrap', {
      sitekey:            TURNSTILE_SITE_KEY,
      theme:              'light',
      callback:           window._onCaptchaSolve,
      'expired-callback': () => { _captchaToken = null; },
      'error-callback':   () => { _captchaToken = null; },
    });
    _captchaReady = true;
  };
  document.head.appendChild(s);
}

// ── Form submission ───────────────────────────────────────────────────
form.addEventListener('submit', (e) => {
  e.preventDefault();
  clearInputError();

  const val = input.value.trim();
  if (!val) {
    showInputError('Please enter your email address.');
    return;
  }
  if (!input.checkValidity()) {
    showInputError('Please enter a valid email address.');
    return;
  }

  if (isSuspicious() && !_captchaToken) {
    _showCaptcha();
    return;
  }

  _doSubmit();
});

async function _doSubmit() {
  btn.disabled    = true;
  btn.textContent = 'Saving…';

  try {
    const payload = { email: input.value.trim(), source: 'coming_soon' };
    if (_captchaToken) payload.cf_turnstile_token = _captchaToken;

    const res  = await fetch('/api/subscribe', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || 'Something went wrong. Please try again.');
    }

    const msgEl = success.querySelector('[data-msg]');
    if (msgEl) msgEl.textContent = data.message;

    form.style.display = 'none';
    note.style.display = 'none';
    document.getElementById('captcha-wrap').style.display = 'none';
    success.classList.add('visible');

  } catch (err) {
    btn.disabled    = false;
    btn.textContent = 'Notify Me';
    _captchaToken   = null;
    errEl.textContent   = err.message;
    errEl.style.display = 'block';
  }
}

// ── Confirmation banner — reads ?confirmed= param after email link click ──
const BANNER_MESSAGES = {
  '1':       { cls: 'confirm-banner--success', text: '🎉 You\'re confirmed! We\'ll notify you when Cloudista launches.' },
  'already': { cls: 'confirm-banner--info',    text: '✓ You\'re already confirmed — we\'ll let you know at launch.' },
  'invalid': { cls: 'confirm-banner--error',   text: 'That confirmation link isn\'t valid. Please sign up again.' },
  'error':   { cls: 'confirm-banner--error',   text: 'Something went wrong confirming your email. Please try again.' },
};

const confirmedParam = new URLSearchParams(window.location.search).get('confirmed');
if (confirmedParam && BANNER_MESSAGES[confirmedParam]) {
  const { cls, text } = BANNER_MESSAGES[confirmedParam];
  const banner = document.getElementById('confirm-banner');
  banner.textContent = text;
  banner.classList.add(cls, 'visible');
  // Clean the URL without reloading
  history.replaceState(null, '', window.location.pathname);
  // Auto-dismiss after 8 s
  setTimeout(() => banner.classList.remove('visible'), 8000);
}
