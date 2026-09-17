(() => {
  "use strict";

  const printerName =
    document.getElementById("printerName");

  const status =
    document.getElementById("printerDesktopStatus");

  const refreshButton =
    document.getElementById("printerRefreshButton");

  const saveButton =
    document.getElementById("printerSaveButton");

  const testButton =
    document.getElementById("printerTestButton");

  const resultBox =
    document.getElementById("printerResult");

  const paperWidth =
    document.getElementById("printerPaperWidth");

  const copies =
    document.getElementById("printerCopies");

  const enabled =
    document.getElementById("printerEnabled");

  const autoPrint =
    document.getElementById("printerAutoPrint");

  if (!printerName || !status || !refreshButton) {
    return;
  }

  function getDesktopApi() {
    if (
      window.pywebview &&
      window.pywebview.api &&
      typeof window.pywebview.api.get_printers
        === "function" &&
      typeof window.pywebview.api.get_printer_settings
        === "function" &&
      typeof window.pywebview.api.save_printer_settings
        === "function" &&
      typeof window.pywebview.api.print_test_receipt
        === "function"
    ) {
      return window.pywebview.api;
    }

    return null;
  }

  function renderPrinters(result) {
    printerName.innerHTML = "";

    const printers = Array.isArray(result.printers)
      ? result.printers
      : [];

    if (!printers.length) {
      const option =
        document.createElement("option");

      option.value = "";
      option.textContent =
        "Windows printer topilmadi";

      printerName.appendChild(option);
      printerName.disabled = true;

      status.textContent =
        "Windows printer topilmadi.";

      return;
    }

    const emptyOption =
      document.createElement("option");

    emptyOption.value = "";
    emptyOption.textContent =
      "Printerni tanlang";

    printerName.appendChild(emptyOption);

    for (const name of printers) {
      const option =
        document.createElement("option");

      option.value = name;
      option.textContent = name;

      printerName.appendChild(option);
    }

    if (
      result.default_printer &&
      printers.includes(result.default_printer)
    ) {
      printerName.value =
        result.default_printer;
    }

    printerName.disabled = false;

    status.textContent =
      `${printers.length} ta Windows printer topildi.`;
  }

  function applySavedSettings(settings) {
    const value =
      settings && typeof settings === "object"
        ? settings
        : {};

    paperWidth.value = String(
      value.paper_width_mm === 58 ? 58 : 80
    );

    const copyCount = Number(
      value.copies || 1
    );

    copies.value = String(
      copyCount >= 1 && copyCount <= 5
        ? copyCount
        : 1
    );

    enabled.checked =
      Boolean(value.enabled);

    autoPrint.checked =
      Boolean(value.auto_print);

    if (
      value.printer_name &&
      Array.from(printerName.options).some(
        (option) =>
          option.value === value.printer_name
      )
    ) {
      printerName.value =
        value.printer_name;
    }
  }

  async function loadPrinters() {
    const api = getDesktopApi();

    if (!api) {
      status.textContent =
        "Printer sozlamasi faqat Gold9999 Desktop ichida ishlaydi.";

      return;
    }

    refreshButton.disabled = true;
    printerName.disabled = true;

    status.textContent =
      "Windows printerlari yuklanmoqda...";

    try {
      const [
        result,
        settingsResult
      ] = await Promise.all([
        api.get_printers(),
        api.get_printer_settings()
      ]);

      if (!result || result.success !== true) {
        throw new Error(
          result?.message ||
          "Printer ro‘yxatini olib bo‘lmadi."
        );
      }

      if (
        !settingsResult ||
        settingsResult.success !== true
      ) {
        throw new Error(
          settingsResult?.message ||
          "Printer sozlamasini olib bo‘lmadi."
        );
      }

      renderPrinters(result);

      applySavedSettings(
        settingsResult.settings
      );

      paperWidth.disabled = false;
      copies.disabled = false;
      enabled.disabled = false;
      autoPrint.disabled = false;
      saveButton.disabled = false;
      testButton.disabled = false;

    } catch (error) {
      console.error(
        "Printer list error:",
        error
      );

      status.textContent =
        error.message ||
        "Printer ro‘yxatini olib bo‘lmadi.";

    } finally {
      refreshButton.disabled = false;
    }
  }

  function collectSettings() {
    return {
      enabled: enabled.checked,
      printer_name:
        printerName.value.trim(),
      paper_width_mm:
        Number(paperWidth.value),
      auto_print:
        autoPrint.checked,
      copies:
        Number(copies.value)
    };
  }

  async function saveCurrentSettings(api) {
    const result =
      await api.save_printer_settings(
        collectSettings()
      );

    if (!result || result.success !== true) {
      throw new Error(
        result?.message ||
        "Sozlamani saqlab bo‘lmadi."
      );
    }

    return result;
  }

  saveButton.addEventListener(
    "click",
    async () => {
      const api = getDesktopApi();

      if (!api) {
        return;
      }

      saveButton.disabled = true;
      resultBox.hidden = true;

      try {
        await saveCurrentSettings(api);

        resultBox.textContent =
          "Printer sozlamasi saqlandi.";

        resultBox.hidden = false;

      } catch (error) {
        console.error(
          "Printer save error:",
          error
        );

        resultBox.textContent =
          error.message ||
          "Sozlamani saqlab bo‘lmadi.";

        resultBox.hidden = false;

      } finally {
        saveButton.disabled = false;
      }
    }
  );

  testButton.addEventListener(
    "click",
    async () => {
      const api = getDesktopApi();

      if (!api) {
        return;
      }

      if (!printerName.value.trim()) {
        resultBox.textContent =
          "Avval printerni tanlang.";

        resultBox.hidden = false;
        return;
      }

      testButton.disabled = true;
      resultBox.hidden = true;

      try {
        await saveCurrentSettings(api);

        const result =
          await api.print_test_receipt();

        if (!result || result.success !== true) {
          throw new Error(
            result?.message ||
            "Test chekni chiqarib bo‘lmadi."
          );
        }

        resultBox.textContent =
          "Test chek printerga yuborildi.";

        resultBox.hidden = false;

      } catch (error) {
        console.error(
          "Printer test error:",
          error
        );

        resultBox.textContent =
          error.message ||
          "Test chekni chiqarib bo‘lmadi.";

        resultBox.hidden = false;

      } finally {
        testButton.disabled = false;
      }
    }
  );

  refreshButton.addEventListener(
    "click",
    loadPrinters
  );

  document.addEventListener(
    "pywebviewready",
    loadPrinters
  );

  window.setTimeout(
    loadPrinters,
    300
  );
})();
