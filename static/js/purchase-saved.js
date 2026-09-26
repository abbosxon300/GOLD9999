(() => {
  const node = document.getElementById('pw-saved-document');
  if (!node) return;
  const data = JSON.parse(node.textContent);
  try {
    const draft = JSON.parse(localStorage.getItem(data.key) || 'null');
    if (draft && draft.entity_uuid === data.uuid) localStorage.removeItem(data.key);
    sessionStorage.removeItem(`${data.key}:submitted`);
  } catch (_) {}
})();
