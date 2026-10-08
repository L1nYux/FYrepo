document.querySelectorAll('[data-funding-claim]').forEach(form => {
  const kind = form.querySelector('[name="settlement_kind"]');
  const receipts = form.querySelector('[data-usage-receipts]');
  const label = form.querySelector('[data-receipt-required]');
  const update = () => {
    const required = kind.value === 'api_quota';
    label.textContent = required ? '（必选）' : '（可选）';
    if (required) receipts.open = true;
  };
  kind.addEventListener('change', update);
  update();
});
