'use strict';

// ── Mobile nav hamburger ────────────────────────────────────────────────────────
(function () {
  const toggle = document.getElementById('nav-toggle');
  if (!toggle) return;
  const header = toggle.closest('.site-header');

  toggle.addEventListener('click', function (e) {
    e.stopPropagation();
    const open = header.classList.toggle('nav-open');
    toggle.setAttribute('aria-expanded', open);
    toggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  });

  document.addEventListener('click', function (e) {
    if (!header.contains(e.target) && header.classList.contains('nav-open')) {
      header.classList.remove('nav-open');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Open navigation');
    }
  });
}());

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

// ── Contact / work-with-me form ────────────────────────────────────────────────
const contactForm = document.getElementById('contact-form');

if (contactForm) {
  const TURNSTILE_SITE_KEY = '0x4AAAAAACiMVM_vMYh7m0Bf';

  const nameInput      = document.getElementById('contact-name');
  const emailInput     = document.getElementById('contact-email');
  const companyInput   = document.getElementById('contact-company');
  const engagementSel  = document.getElementById('contact-engagement');
  const situationInput = document.getElementById('contact-situation');
  const submitBtn      = document.getElementById('contact-submit');
  const errorEl        = document.getElementById('contact-error');
  const successEl      = document.getElementById('contact-success');

  // Bot heuristics (same approach as subscribe form)
  const _ch = { pageLoad: Date.now(), firstInput: null, hadPointer: false, hadKey: false };
  document.addEventListener('mousemove',  () => { _ch.hadPointer = true; }, { once: true, passive: true });
  document.addEventListener('touchstart', () => { _ch.hadPointer = true; }, { once: true, passive: true });
  [nameInput, emailInput, situationInput].forEach(el => {
    if (!el) return;
    el.addEventListener('keydown', () => { _ch.hadKey = true; if (!_ch.firstInput) _ch.firstInput = Date.now(); }, { once: true });
    el.addEventListener('paste',   () => { _ch.hadKey = true; if (!_ch.firstInput) _ch.firstInput = Date.now(); }, { once: true });
  });

  function isContactSuspicious() {
    const hp = document.getElementById('contact-website');
    if (hp && hp.value) return true;
    const now = Date.now();
    if (now - _ch.pageLoad < 3000) return true;
    if (_ch.firstInput && now - _ch.firstInput < 1500) return true;
    if (!_ch.hadPointer && !_ch.hadKey) return true;
    return false;
  }

  // Turnstile (lazy — only when suspicious)
  let _cToken = null;
  let _cReady = false;

  window._onContactCaptchaSolve = (token) => { _cToken = token; _doContactSubmit(); };

  function _showContactCaptcha() {
    const wrap = document.getElementById('contact-captcha-wrap');
    if (!wrap) return;
    wrap.style.display = 'block';
    if (_cReady) return;
    const s = document.createElement('script');
    s.src   = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    s.async = true;
    s.onload = () => {
      turnstile.render('#contact-captcha-wrap', {
        sitekey:            TURNSTILE_SITE_KEY,
        theme:              'light',
        callback:           window._onContactCaptchaSolve,
        'expired-callback': () => { _cToken = null; },
        'error-callback':   () => { _cToken = null; },
      });
      _cReady = true;
    };
    document.head.appendChild(s);
  }

  function showContactError(msg) {
    if (!errorEl) return;
    errorEl.textContent = msg;
    errorEl.style.display = 'block';
  }

  contactForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (errorEl) { errorEl.style.display = 'none'; errorEl.textContent = ''; }

    if (!nameInput?.value.trim())     { showContactError('Please enter your name.'); nameInput?.focus(); return; }
    if (!emailInput?.checkValidity()) { showContactError('Please enter a valid email address.'); emailInput?.focus(); return; }
    if (!situationInput?.value.trim() || situationInput.value.trim().length < 10) {
      showContactError('Please describe your situation (at least 10 characters).'); situationInput?.focus(); return;
    }

    if (isContactSuspicious() && !_cToken) { _showContactCaptcha(); return; }
    _doContactSubmit();
  });

  async function _doContactSubmit() {
    submitBtn.disabled    = true;
    submitBtn.textContent = 'Sending…';

    try {
      const payload = {
        name:      nameInput.value.trim(),
        email:     emailInput.value.trim(),
        company:   companyInput?.value.trim() || '',
        engagement: engagementSel?.value || '',
        situation: situationInput.value.trim(),
      };
      if (_cToken) payload.cf_turnstile_token = _cToken;

      const res  = await fetch('/api/contact', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Something went wrong. Please try again.');

      contactForm.style.display = 'none';
      document.getElementById('contact-captcha-wrap')?.style.setProperty('display', 'none');
      if (successEl) successEl.classList.add('visible');

    } catch (err) {
      submitBtn.disabled    = false;
      submitBtn.textContent = 'Send message →';
      _cToken = null;
      showContactError(err.message);
    }
  }
}
