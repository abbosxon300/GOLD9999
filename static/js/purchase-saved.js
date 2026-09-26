(() => {
  const node = document.getElementById('pw-saved-document');
  if (!node) return;
  const data = JSON.parse(node.textContent);
  const keys = Array.isArray(data.keys) ? data.keys : [data.key].filter(Boolean);
  try {
    keys.forEach(key => {
      const draft = JSON.parse(localStorage.getItem(key) || 'null');
      if (draft && draft.entity_uuid === data.uuid) localStorage.removeItem(key);
      sessionStorage.removeItem(`${key}:submitted`);
    });
  } catch (_) {}
})();
