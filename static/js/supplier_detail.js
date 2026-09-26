(() => {
  const $ = id => document.getElementById(id);

  const tabs = [...document.querySelectorAll('[data-supplier-tab]')];
  const panels = [...document.querySelectorAll('[data-supplier-panel]')];
  tabs.forEach(button => {
    button.addEventListener('click', () => {
      const name = button.dataset.supplierTab;
      tabs.forEach(tab => {
        const active = tab === button;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', String(active));
      });
      panels.forEach(panel => {
        panel.hidden = panel.dataset.supplierPanel !== name;
      });
    });
  });

  const dialog = $('supplier-pay-dialog');
  const open = $('supplier-pay-open');
  const close = $('supplier-pay-close');
  const cancel = $('supplier-pay-cancel');
  const form = $('supplier-pay-form');

  if (!dialog || !open || !form) return;

  const hideError = () => {
    const error = $('supplier-pay-error');
    if (!error) return;
    error.textContent = '';
    error.hidden = true;
  };
  const showError = message => {
    const error = $('supplier-pay-error');
    if (!error) return;
    error.textContent = message;
    error.hidden = false;
  };
  const closeDialog = () => {
    hideError();
    dialog.close();
  };

  open.addEventListener('click', () => {
    hideError();
    dialog.showModal();
    setTimeout(() => $('supplier-pay-amount')?.focus(), 0);
  });
  close?.addEventListener('click', closeDialog);
  cancel?.addEventListener('click', closeDialog);
  dialog.addEventListener('click', event => {
    if (event.target === dialog) closeDialog();
  });

  form.addEventListener('submit', event => {
    hideError();

    const date = $('supplier-pay-date');
    const amount = $('supplier-pay-amount');
    const value = Number(String(amount?.value || '').replace(/\s/g, ''));
    const debt = Number(dialog.dataset.debt || 0);

    let message = '';
    if (!date?.value) message = 'To‘lov sanasini kiriting.';
    else if (!Number.isFinite(value) || value <= 0) message = 'To‘lov summasini kiriting.';
    else if (value > debt + 0.005) message = 'To‘lov yetkazib beruvchi qarzidan oshmasligi kerak.';

    if (message) {
      event.preventDefault();
      showError(message);
      if (!date?.value) date?.focus();
      else amount?.focus();
    }
  });
})();
