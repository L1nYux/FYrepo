(() => {
  const button = document.querySelector('[data-copy-temporary]');
  if (!button) return;
  button.addEventListener('click', async () => {
    const input = document.querySelector('#temporary-password');
    const status = document.querySelector('[data-copy-status]');
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(input.value);
      else { input.focus(); input.select(); if (!document.execCommand('copy')) throw Error(); }
      status.textContent = '已复制，请私下交给该成员。';
    } catch (_) { input.focus(); input.select(); status.textContent = '请复制选中的临时密码。'; }
  });
})();
