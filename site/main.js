'use strict';

// ── Confirmation banner — reads ?confirmed= param after email link click ──
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
  banner.textContent = text;
  banner.classList.add(cls, 'visible');
  history.replaceState(null, '', window.location.pathname);
  setTimeout(() => banner.classList.remove('visible'), 8000);
}
