'use strict';

// ── Confirmation banner ────────────────────────────────────────────────────────
const BANNER_MESSAGES = {
  '1':       { cls: 'confirm-banner--success', text: '🎉 You\'re confirmed! Welcome to Cloudista.' },
  'already': { cls: 'confirm-banner--info',    text: '✓ You\'re already confirmed.' },
  'invalid': { cls: 'confirm-banner--error',   text: 'That confirmation link isn\'t valid. Please sign up again.' },
  'error':   { cls: 'confirm-banner--error',   text: 'Something went wrong confirming your email. Please try again.' },
};

const confirmedParam = new URLSearchParams(window.location.search).get('confirmed');
if (confirmedParam && BANNER_MESSAGES[confirmedParam]) {
  const { cls, text } = BANNER_MESSAGES[confirmedParam];
  const banner = document.getElementById('confirm-banner');
  if (banner) {
    banner.textContent = text;
    banner.classList.add(cls, 'visible');
    history.replaceState(null, '', window.location.pathname);
    setTimeout(() => banner.classList.remove('visible'), 8000);
  }
}

// ── Subscribe modal ────────────────────────────────────────────────────────────
const modal        = document.getElementById('subscribe-modal');
const modalBackdrop = document.getElementById('modal-backdrop');
const modalClose   = document.getElementById('modal-close');
const subscribeBtn = document.getElementById('subscribe-btn');

if (modal && subscribeBtn) {

  function openModal() {
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
    document.getElementById('subscribe-email')?.focus();
  }

  function closeModal() {
    modal.hidden = true;
    document.body.style.overflow = '';
    subscribeBtn.focus();
  }

  subscribeBtn.addEventListener('click', openModal);
  modalClose?.addEventListener('click', closeModal);
  modalBackdrop?.addEventListener('click', closeModal);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modal.hidden) closeModal();
  });

  // ── Bot heuristics ─────────────────────────────────────────────────────────
  const TURNSTILE_SITE_KEY = '0x4AAAAAACiMVM_vMYh7m0Bf';

  const _h = {
    pageLoad:   Date.now(),
    firstInput: null,
    hadPointer: false,
    hadKey:     false,
  };

  document.addEventListener('mousemove',  () => { _h.hadPointer = true; }, { once: true, passive: true });
  document.addEventListener('touchstart', () => { _h.hadPointer = true; }, { once: true, passive: true });

  const emailInput = document.getElementById('subscribe-email');
  if (emailInput) {
    emailInput.addEventListener('keydown', () => {
      _h.hadKey = true;
      if (!_h.firstInput) _h.firstInput = Date.now();
    }, { once: true });
    emailInput.addEventListener('paste', () => {
      _h.hadKey = true;
      if (!_h.firstInput) _h.firstInput = Date.now();
    }, { once: true });
  }

  function isSuspicious() {
    const hp = document.getElementById('subscribe-website');
    if (hp && hp.value) return true;
    const now = Date.now();
    if (now - _h.pageLoad < 3000) return true;
    if (_h.firstInput && now - _h.firstInput < 1500) return true;
    if (!_h.hadPointer && !_h.hadKey) return true;
    return false;
  }

  // ── Turnstile (lazy-loaded only when suspicious) ───────────────────────────
  let _captchaToken = null;
  let _captchaReady = false;

  window._onCaptchaSolve = (token) => {
    _captchaToken = token;
    _doSubmit();
  };

  function _showCaptcha() {
    const wrap = document.getElementById('subscribe-captcha-wrap');
    if (!wrap) return;
    wrap.style.display = 'block';
    if (_captchaReady) return;
    const s = document.createElement('script');
    s.src   = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    s.async = true;
    s.onload = () => {
      turnstile.render('#subscribe-captcha-wrap', {
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

  // ── Form submission ────────────────────────────────────────────────────────
  const form      = document.getElementById('subscribe-form');
  const submitBtn = document.getElementById('subscribe-submit');
  const errEl     = document.getElementById('subscribe-error');
  const successEl = document.getElementById('subscribe-success');

  function showError(msg) {
    if (!errEl || !emailInput) return;
    errEl.textContent = msg;
    errEl.style.display = 'block';
    emailInput.classList.add('signup-form__input--error');
    emailInput.setAttribute('aria-invalid', 'true');
    emailInput.focus();
  }

  if (emailInput) {
    emailInput.addEventListener('input', () => {
      if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
      emailInput.classList.remove('signup-form__input--error');
      emailInput.removeAttribute('aria-invalid');
    });
  }

  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();

      const val = emailInput?.value.trim();
      if (!val) { showError('Please enter your email address.'); return; }
      if (!emailInput?.checkValidity()) { showError('Please enter a valid email address.'); return; }

      if (isSuspicious() && !_captchaToken) { _showCaptcha(); return; }
      _doSubmit();
    });
  }

  async function _doSubmit() {
    if (!submitBtn || !emailInput) return;
    submitBtn.disabled    = true;
    submitBtn.textContent = 'Saving…';

    try {
      const payload = { email: emailInput.value.trim(), source: 'blog' };
      if (_captchaToken) payload.cf_turnstile_token = _captchaToken;

      const res  = await fetch('/api/subscribe', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Something went wrong. Please try again.');

      const msgEl = successEl?.querySelector('[data-msg]');
      if (msgEl) msgEl.textContent = data.message || 'Check your email — we\'ve sent you a confirmation link.';
      if (form) form.style.display = 'none';
      document.getElementById('subscribe-captcha-wrap')?.style.setProperty('display', 'none');
      successEl?.classList.add('visible');

    } catch (err) {
      submitBtn.disabled    = false;
      submitBtn.textContent = 'Subscribe';
      _captchaToken         = null;
      showError(err.message);
    }
  }
}
