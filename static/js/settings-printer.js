(() => {
  "use strict";
  const form = document.getElementById("receiptSettingsForm");
  if (!form) return;
  const enabled = document.getElementById("printerAutoPrint");
  const result = document.getElementById("printerResult");
  const preferences = window.GoldReceiptPreferences;
  enabled.checked = preferences.isEnabled();
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      preferences.save(enabled.checked);
      result.textContent = enabled.checked
        ? "Saqlandi. Sotuv yakunlanganda chek chop qilish oynasi ochiladi."
        : "Saqlandi. Sotuv chek chop qilish oynasisiz yakunlanadi.";
      result.setAttribute("role", "status");
    } catch (_) {
      result.textContent = "Saqlanmadi. Brauzerda sayt ma’lumotlarini saqlashga ruxsat bering va qayta urinib ko‘ring.";
      result.setAttribute("role", "alert");
    }
    result.hidden = false;
  });
})();
