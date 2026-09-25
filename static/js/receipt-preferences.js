(() => {
  "use strict";
  const key = "gold9999.receipt.autoPrint";
  window.GoldReceiptPreferences = Object.freeze({
    isEnabled() {
      try {
        return window.localStorage.getItem(key) !== "off";
      } catch (_) {
        return true;
      }
    },
    save(enabled) {
      window.localStorage.setItem(key, enabled ? "on" : "off");
    }
  });
})();
