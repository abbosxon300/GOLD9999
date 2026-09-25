(() => {
  "use strict";

  const root = document.getElementById("sales-pos");

  if (!root || !window.SALES_POS_INITIAL) {
    return;
  }

  const initial = window.SALES_POS_INITIAL;
  const searchPanel = document.getElementById("pos-search-panel");
  const searchResults = document.getElementById("pos-search-results");
  const searchMessage = document.getElementById("pos-search-message");
  const editModal = document.getElementById("pos-edit-modal");
  const editForm = document.getElementById("pos-edit-form");
  const editQty = document.getElementById("pos-edit-qty");
  const editPrice = document.getElementById("pos-edit-price");
  let editProductId = null;
  let mutationBusy = false;
  let searchMatches = [];
  let selectedMatch = -1;
  let searchTimer = null;
  let searchAbort = null;
  let searchVersion = 0;
  const cartBody = document.getElementById("pos-cart-body");
  const cartCount = document.getElementById("pos-cart-count");
  const cartQty = document.getElementById("pos-cart-qty");
  const cartTotal = document.getElementById("pos-cart-total");
  const globalDiscountType = document.getElementById(
    "pos-global-discount-type"
  );
  const globalDiscountValue = document.getElementById(
    "pos-global-discount-value"
  );
  const globalDiscountTotal = document.getElementById(
    "pos-global-discount-total"
  );
  const globalPayable = document.getElementById(
    "pos-global-payable"
  );
  const checkoutButton = document.getElementById("pos-checkout");
  const checkoutForm = document.getElementById("pos-checkout-form");
  const paymentModal = document.getElementById("pos-payment-modal");
  const paymentTotal = document.getElementById("pos-payment-total");
  const paymentMixed = document.getElementById("pos-payment-mixed");
  const paymentCash = document.getElementById("pos-payment-cash");
  const paymentClick = document.getElementById("pos-payment-click");
  const paymentRemaining = document.getElementById(
    "pos-payment-remaining"
  );
  const paymentBalanceLabel = document.getElementById(
    "pos-payment-balance-label"
  );
  const paymentError = document.getElementById("pos-payment-error");
  const paymentSubmit = document.getElementById("pos-payment-submit");
  const clearButton = document.getElementById("pos-clear");
  const searchInput = document.getElementById("pos-search");
  const kassaToggle = document.getElementById(
    "pos-kassa-toggle"
  );
  const toast = document.getElementById("pos-toast");
  const confirmModal = document.getElementById("pos-clear-confirm");
  const confirmClear = document.getElementById(
    "pos-clear-confirm-button"
  );

  let cart = initial.cart || {
    items: [],
    item_count: 0,
    qty_total: 0,
    cart_total: 0,
  };

  let toastTimer = null;
  let kassaModeActive = false;

  const applyKassaMode = (active) => {
    kassaModeActive = Boolean(active);

    document.body.classList.toggle(
      "pos-kassa-mode",
      kassaModeActive
    );

    if (kassaToggle) {
      kassaToggle.classList.toggle(
        "is-active",
        kassaModeActive
      );

      const label = kassaToggle.querySelector("span");

      if (label) {
        label.textContent = kassaModeActive
          ? "Chiqish"
          : "Kassa rejimi";
      }
    }
  };

  const enterKassaMode = async () => {
    applyKassaMode(true);

    try {
      if (
        !document.fullscreenElement &&
        document.documentElement.requestFullscreen
      ) {
        await document.documentElement.requestFullscreen();
      }
    } catch (error) {
      console.info(
        "Fullscreen API mavjud emas, shell-only mode ishlaydi.",
        error
      );
    }
  };

  const exitKassaMode = async () => {
    try {
      if (
        document.fullscreenElement &&
        document.exitFullscreen
      ) {
        await document.exitFullscreen();
      }
    } catch (error) {
      console.info("Fullscreen exit failed.", error);
    }

    applyKassaMode(false);
  };

  const money = (value) => {
    const numeric = Number(value || 0);

    return Math.round(numeric).toLocaleString("ru-RU");
  };

  const parseMoneyInput = (value) => {
    const digits = String(value || "")
      .replace(/\D/g, "");

    return digits ? Number(digits) : 0;
  };

  const formatMoneyInput = (value) => {
    const numeric = Math.max(0, Number(value || 0));

    return Math.round(numeric)
      .toLocaleString("ru-RU");
  };

  const globalDiscountState = {
    type: "none",
    value: 0,
  };

  const calculateGlobalDiscount = (total) => {
    const base = Math.max(0, Number(total || 0));
    const value = Math.max(
      0,
      Number(globalDiscountState.value || 0)
    );

    let discount = 0;

    if (globalDiscountState.type === "percent") {
      discount = base * Math.min(100, value) / 100;
    } else if (globalDiscountState.type === "amount") {
      discount = Math.min(base, value);
    }

    return {
      discount,
      payable: Math.max(0, base - discount),
    };
  };

  const renderGlobalDiscount = (total) => {
    const result = calculateGlobalDiscount(total);

    if (globalDiscountTotal) {
      globalDiscountTotal.textContent =
        `− ${money(result.discount)} so‘m`;
    }

    if (globalPayable) {
      globalPayable.textContent = money(result.payable);
    }

    if (globalDiscountValue) {
      globalDiscountValue.disabled =
        globalDiscountState.type === "none";
    }
  };

  const qtyText = (value) => {
    const numeric = Number(value || 0);

    if (Number.isInteger(numeric)) {
      return String(numeric);
    }

    return numeric
      .toLocaleString("ru-RU", {
        maximumFractionDigits: 2,
      });
  };

  const escapeHtml = (value) => {
    const node = document.createElement("div");
    node.textContent = String(value ?? "");
    return node.innerHTML;
  };

  const showToast = (message, isError = false) => {
    if (!toast) {
      return;
    }

    clearTimeout(toastTimer);

    toast.textContent = message;
    toast.classList.toggle("is-error", isError);
    toast.hidden = false;

    toastTimer = window.setTimeout(() => {
      toast.hidden = true;
    }, 2200);
  };

  const printSaleReceipt = (saleId) => {
    if (window.GoldReceiptPreferences?.isEnabled() === false) return;

    document
      .getElementById("pos-receipt-print-frame")
      ?.remove();

    const frame = document.createElement("iframe");

    frame.id = "pos-receipt-print-frame";
    frame.src =
      `/sales/receipt/${encodeURIComponent(saleId)}?autoprint=1`;

    Object.assign(frame.style, {
      position: "fixed",
      left: "-10000px",
      top: "0",
      width: "400px",
      height: "700px",
      border: "0",
    });

    frame.setAttribute("aria-hidden", "true");

    document.body.appendChild(frame);

    window.setTimeout(
      () => frame.remove(),
      60000
    );
  };

  const setBusy = (busy) => {
    mutationBusy = busy;
    root.classList.toggle("is-busy", busy);
    root.setAttribute("aria-busy", String(busy));
    checkoutButton.disabled = busy || !cart.items?.length;
    clearButton.disabled = busy || !cart.items?.length;
  };

  const postForm = async (url, values = {}) => {
    const body = new URLSearchParams();

    Object.entries(values).forEach(([key, value]) => {
      body.set(key, String(value));
    });

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type":
          "application/x-www-form-urlencoded;charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
      },
      body,
      redirect: "follow",
      credentials: "same-origin",
    });

    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      if ((response.headers.get("content-type") || "").includes("application/json")) {
        const payload = await response.json().catch(() => null);
        if (payload?.error) message = String(payload.error);
      }
      throw new Error(message);
    }

    return response;
  };

  const loadCart = async () => {
    const response = await fetch(initial.urls.cart, {
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
    });

    if (!response.ok) {
      throw new Error(`Cart HTTP ${response.status}`);
    }

    cart = await response.json();
    renderCart();
  };

  const closeSearch = () => {
    clearTimeout(searchTimer);
    searchAbort?.abort();
    searchVersion++;
    searchPanel.hidden = true;
    searchMatches = [];
    selectedMatch = -1;
    searchInput.setAttribute("aria-expanded", "false");
    searchInput.removeAttribute("aria-activedescendant");
  };

  const selectMatch = (index) => {
    selectedMatch = index;
    searchResults.querySelectorAll("[data-search-index]").forEach((row, i) => {
      row.classList.toggle("is-selected", i === index);
      row.setAttribute("aria-selected", String(i === index));
      if (i === index) row.scrollIntoView({block: "nearest"});
    });
    if (index >= 0) searchInput.setAttribute("aria-activedescendant", `pos-result-${index}`);
    else searchInput.removeAttribute("aria-activedescendant");
  };

  const searchProducts = async (query) => {
    searchAbort?.abort();
    const version = ++searchVersion;
    searchAbort = new AbortController();
    searchMatches = [];
    selectedMatch = -1;
    searchResults.innerHTML = "";
    searchPanel.hidden = false;
    searchInput.setAttribute("aria-expanded", "true");
    searchMessage.textContent = "Qidirilmoqda…";
    try {
      const url = new URL(initial.urls.products, window.location.origin);
      url.searchParams.set("q", query);
      const response = await fetch(url, {credentials: "same-origin", signal: searchAbort.signal});
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Qidiruv bajarilmadi");
      if (version !== searchVersion || query !== searchInput.value.trim()) return;
      searchMatches = Array.isArray(payload.products) ? payload.products : [];
      searchMessage.textContent = searchMatches.length
        ? `${searchMatches.length} ta natija · Tanlash uchun bosing${searchMatches.length === 30 ? " · Nomini aniqroq yozing" : ""}`
        : "Mahsulot topilmadi. Boshqa nom yoki shtrix-kod kiriting.";
      searchResults.innerHTML = searchMatches.map((product, i) => `
        <button type="button" role="option" aria-selected="false" id="pos-result-${i}" class="pos-search-result" data-search-index="${i}">
          <span class="pos-result-icon" aria-hidden="true">＋</span>
          <span class="pos-result-name"><strong>${escapeHtml(product.name)}</strong><small>ID: ${Number(product.id)} · <span class="${Number(product.qty) <= 0 ? 'is-out' : ''}">${qtyText(product.qty)} dona qoldiq</span></small></span>
          <span class="pos-result-price">${money(product.sell_default)} <small>so‘m</small></span>
        </button>`).join("");
    } catch (error) {
      if (error.name !== "AbortError" && version === searchVersion) searchMessage.textContent = "Qidiruv yuklanmadi. Qayta urinib ko‘ring.";
    }
  };

  const applySearch = () => {
    closeSearch();
    const query = searchInput.value.trim();
    if (!query) return;
    // Scanner Enter cancels this timer and adds with a single POST.
    searchTimer = window.setTimeout(() => searchProducts(query), 220);
  };

  const addSearchProduct = async (product) => {
    if (mutationBusy) return;
    if (Number(product.qty) <= 0) return showToast("Mahsulot qoldig‘i yo‘q", true);
    setBusy(true);
    closeSearch();
    try {
      const response = await postForm(initial.urls.add, {_pos_cart_json: "1", _pos_product_id: String(product.id)});
      const payload = await response.json();
      if (!payload.ok) throw new Error(payload.error || "Mahsulot qo‘shilmadi");
      cart = payload;
      renderCart();
      searchInput.value = "";
      showToast(`${payload.added_product_name || product.name} savatga qo‘shildi.`);
    } catch (error) { showToast(error.message, true); }
    finally { setBusy(false); searchInput.focus(); }
  };

  const cartItemTemplate = (item, index) => {
    const productId = Number(item.product_id);
    const qty = Number(item.qty || 0);
    const price = Number(item.price || 0);
    return `
      <article class="pos-cart-item">
        <div class="pos-item-name"><span class="pos-row-number">${index + 1}</span><div><h3>${escapeHtml(item.name)}</h3><small>ID: ${productId}</small></div></div>
        <button class="pos-price-edit" type="button" data-cart-edit="${productId}" aria-label="${escapeHtml(item.name)} narxi va miqdorini o‘zgartirish">${money(price)}<small>so‘m <span aria-hidden="true">✎</span></small></button>
        <div class="pos-qty-control"><button type="button" data-cart-action="dec" data-product-id="${productId}" aria-label="Miqdorni kamaytirish">−</button><button class="pos-qty-value" type="button" data-cart-edit="${productId}" aria-label="Miqdorni kiritish">${qtyText(qty)}</button><button type="button" data-cart-action="inc" data-product-id="${productId}" aria-label="Miqdorni oshirish">+</button></div>
        <strong class="pos-line-total">${money(item.line_total ?? qty * price)}<small>so‘m</small></strong>
        <button class="pos-cart-remove" type="button" data-cart-remove="${productId}" aria-label="${escapeHtml(item.name)}ni savatdan o‘chirish" title="O‘chirish"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6"/></svg></button>
      </article>`;
  };

  const renderCart = () => {
    const items = Array.isArray(cart.items)
      ? cart.items
      : [];

    if (items.length === 0) {
      cartBody.innerHTML = `
        <div class="pos-cart-empty">
          <div class="pos-cart-empty-mark">＋</div>
          <h3>Savat bo‘sh</h3>
          <p>Mahsulotni skanerlang yoki yuqorida nomini yozing.</p>
        </div>
      `;
    } else {
      cartBody.innerHTML = items
        .map(cartItemTemplate)
        .join("");
    }

    const itemCount = Number(
      cart.item_count ?? items.length
    );

    const totalQty = Number(
      cart.qty_total ??
      items.reduce(
        (sum, item) => sum + Number(item.qty || 0),
        0
      )
    );

    const total = Number(
      cart.cart_total ??
      items.reduce(
        (sum, item) => {
          return sum + Number(
            item.line_total ??
            Number(item.qty || 0) *
            Number(item.price || 0)
          );
        },
        0
      )
    );

    cartCount.textContent = `${itemCount} ta`;
    cartQty.textContent = `${qtyText(totalQty)} dona`;
    cartTotal.textContent = money(total);
    renderGlobalDiscount(total);

    const empty = itemCount === 0;

    checkoutButton.disabled = empty || mutationBusy;
    clearButton.disabled = empty || mutationBusy;
  };

  let barcodeScanBusy = false;


  const addScannedBarcode = async (barcode) => {
    const response = await postForm(
      initial.urls.add,
      {
        _pos_cart_json: "1",
        barcode,
      }
    );

    const payload = await response.json();
    if (!payload.ok || !Array.isArray(payload.items)) {
      throw new Error(payload.error || "Savat javobi noto‘g‘ri.");
    }
    cart = payload;
    renderCart();

    showToast(
      `${payload.added_product_name || "Mahsulot"} savatga qo‘shildi.`
    );

    return true;
  };


  const scanBarcode = async (
    rawBarcode
  ) => {
    if (barcodeScanBusy || mutationBusy) {
      return;
    }

    const barcode = String(
      rawBarcode || ""
    ).trim();

    if (!barcode) {
      return;
    }

    closeSearch();
    barcodeScanBusy = true;
    setBusy(true);

    try {
      await addScannedBarcode(barcode);
    } catch (error) {
      console.error(error);

      showToast(
        error?.message ||
        "Shtrix-kodni o‘qib bo‘lmadi.",
        true
      );
    } finally {
      if (searchInput) {
        searchInput.value = "";
        applySearch();
        searchInput.focus();
      }

      setBusy(false);
      barcodeScanBusy = false;
    }
  };


  globalDiscountType?.addEventListener(
    "change",
    () => {
      globalDiscountState.type =
        globalDiscountType.value || "none";

      if (globalDiscountState.type === "none") {
        globalDiscountState.value = 0;

        if (globalDiscountValue) {
          globalDiscountValue.value = "0";
        }
      }

      renderCart();
    }
  );

  globalDiscountValue?.addEventListener(
    "input",
    () => {
      globalDiscountState.value = Math.max(
        0,
        Number(globalDiscountValue.value || 0)
      );

      renderCart();
    }
  );

  kassaToggle?.addEventListener(
    "click",
    async () => {
      if (kassaModeActive) {
        await exitKassaMode();
      } else {
        await enterKassaMode();
      }
    }
  );

  document.addEventListener(
    "fullscreenchange",
    () => {
      if (
        kassaModeActive &&
        !document.fullscreenElement
      ) {
        applyKassaMode(false);
      }
    }
  );

  searchInput?.addEventListener(
    "input",
    applySearch
  );

  searchInput.addEventListener("keydown", async (event) => {
    if (event.isComposing) return;
    if (event.key === "Escape") { closeSearch(); return; }
    if (["ArrowDown", "ArrowUp"].includes(event.key) && searchMatches.length) {
      event.preventDefault();
      const next = selectedMatch < 0
        ? (event.key === "ArrowDown" ? 0 : searchMatches.length - 1)
        : (selectedMatch + (event.key === "ArrowDown" ? 1 : -1) + searchMatches.length) % searchMatches.length;
      selectMatch(next);
      return;
    }
    if (event.key !== "Enter") return;
    event.preventDefault();
    const query = searchInput.value.trim();
    if (!query || mutationBusy) return;
    if (selectedMatch >= 0 && searchMatches[selectedMatch]) return addSearchProduct(searchMatches[selectedMatch]);
    if (/^[0-9]{8,128}$/.test(query)) return scanBarcode(query);
    // An exact alphanumeric barcode is also resolved by the search API.
    clearTimeout(searchTimer);
    await searchProducts(query);
  });

  searchResults.addEventListener("click", (event) => {
    const row = event.target.closest("[data-search-index]");
    if (row && searchMatches[Number(row.dataset.searchIndex)]) addSearchProduct(searchMatches[Number(row.dataset.searchIndex)]);
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".pos-search-area")) closeSearch();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "F2" && paymentModal.hidden && confirmModal.hidden && editModal.hidden) {
      event.preventDefault(); searchInput.focus(); searchInput.select();
    }
    if (event.key === "Escape") {
      if (!paymentModal.hidden) closePaymentModal();
      if (!confirmModal.hidden && !mutationBusy) confirmModal.hidden = true;
      if (!editModal.hidden && !mutationBusy) { editModal.hidden = true; searchInput.focus(); }
    }
  });

  document.addEventListener(
    "keydown",
    (event) => {
      if (
        !searchInput ||
        barcodeScanBusy || mutationBusy || !paymentModal.hidden || !confirmModal.hidden || !editModal.hidden ||
        event.defaultPrevented ||
        event.ctrlKey ||
        event.altKey ||
        event.metaKey
      ) {
        return;
      }

      const target = event.target;

      const editable = Boolean(
        target &&
        (
          target.matches?.(
            "input, textarea, select"
          ) ||
          target.isContentEditable
        )
      );

      if (editable) {
        return;
      }

      if (
        typeof event.key !== "string" ||
        event.key.length !== 1
      ) {
        return;
      }

      searchInput.focus();
      searchInput.value += event.key;
      applySearch();

      event.preventDefault();
    }
  );

  cartBody.addEventListener(
    "click",
    async (event) => {
      if (mutationBusy) return;
      const edit = event.target.closest("[data-cart-edit]");
      if (edit) {
        const item = cart.items.find(item => Number(item.product_id) === Number(edit.dataset.cartEdit));
        if (!item) return;
        editProductId = Number(item.product_id);
        document.getElementById("pos-edit-name").textContent = item.name;
        editQty.value = item.qty;
        editPrice.value = item.price;
        document.getElementById("pos-edit-error").hidden = true;
        editModal.hidden = false;
        editQty.focus(); editQty.select();
        return;
      }
      const remove = event.target.closest(
        "[data-cart-remove]"
      );

      const actionButton = event.target.closest(
        "[data-cart-action]"
      );

      let url = null;

      if (remove) {
        const productId = Number(
          remove.dataset.cartRemove
        );

        url = `/sales/remove/${productId}`;
      }

      if (actionButton) {
        const productId = Number(
          actionButton.dataset.productId
        );

        const action = String(
          actionButton.dataset.cartAction
        );

        url = `/sales/qty/${productId}/${action}`;
      }

      if (!url) {
        return;
      }

      setBusy(true);

      try {
        const response = await postForm(url, {_pos_cart_json: "1"});
        cart = await response.json();
        renderCart();
      } catch (error) {
        console.error(error);
        showToast(
          error.message || "Savatni yangilab bo‘lmadi.",
          true
        );
      } finally {
        setBusy(false);
      }
    }
  );

  document.querySelectorAll("[data-edit-cancel]").forEach(button => button.addEventListener("click", () => {
    if (!mutationBusy) { editModal.hidden = true; searchInput.focus(); }
  }));
  editForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (mutationBusy || !editForm.reportValidity()) return;
    setBusy(true);
    try {
      const response = await postForm(`/sales/cart/${editProductId}/update`, {qty: editQty.value, price_uzs: editPrice.value});
      cart = await response.json(); renderCart();
      editModal.hidden = true; searchInput.focus();
    } catch(error) {
      const node = document.getElementById("pos-edit-error");
      node.textContent = error.message; node.hidden = false;
    } finally { setBusy(false); }
  });

  let paymentMethod = "CASH";

  const currentPayable = () => {
    const total = Number(cart.cart_total || 0);
    return calculateGlobalDiscount(total).payable;
  };

  const setCheckoutField = (name, value) => {
    let input = checkoutForm.querySelector(
      `input[name="${name}"]`
    );

    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      checkoutForm.appendChild(input);
    }

    input.value = String(value);
  };

  const renderPaymentModal = () => {
    const payable = currentPayable();

    paymentTotal.textContent = money(payable);

    document
      .querySelectorAll("[data-payment-method]")
      .forEach((button) => {
        button.classList.toggle(
          "is-active",
          button.dataset.paymentMethod === paymentMethod
        );
      });

    paymentMixed.hidden = paymentMethod !== "MIXED";
    paymentError.hidden = true;

    let cash = 0;
    let click = 0;

    if (paymentMethod === "CASH") {
      cash = payable;
    } else if (paymentMethod === "CLICK") {
      click = payable;
    } else {
      cash = parseMoneyInput(paymentCash.value);
      click = parseMoneyInput(paymentClick.value);
    }

    const paid = cash + click;
    const difference = payable - paid;
    const mismatch = Math.abs(difference) > 0.01;

    if (paymentBalanceLabel) {
      paymentBalanceLabel.textContent =
        difference < -0.01
          ? "Ortiqcha"
          : "Qoldi";
    }

    if (paymentRemaining) {
      paymentRemaining.textContent =
        `${money(Math.abs(difference))} so‘m`;
    }

    paymentSubmit.disabled =
      paymentMethod === "MIXED" &&
      mismatch;
  };

  const openPaymentModal = () => {
    const payable = currentPayable();

    paymentMethod = "CASH";
    paymentCash.value = formatMoneyInput(payable);
    paymentClick.value = "0";

    renderPaymentModal();
    paymentModal.hidden = false;
  };

  const closePaymentModal = () => {
    paymentModal.hidden = true;
  };

  checkoutForm.addEventListener("submit", (event) => {
    event.preventDefault();

    if (paymentModal.hidden && !mutationBusy && cart.items?.length) {
      closeSearch();
      openPaymentModal();
    }
  });

  document
    .querySelectorAll("[data-payment-method]")
    .forEach((button) => {
      button.addEventListener("click", () => {
        paymentMethod = button.dataset.paymentMethod;

        const payable = currentPayable();

        if (paymentMethod === "MIXED") {
          paymentCash.value = formatMoneyInput(payable);
          paymentClick.value = "0";
        }

        renderPaymentModal();
      });
    });

  paymentCash.addEventListener("input", () => {
    if (paymentMethod !== "MIXED") {
      return;
    }

    const payable = currentPayable();
    const cash = Math.min(
      payable,
      parseMoneyInput(paymentCash.value)
    );

    const click = Math.max(
      0,
      payable - cash
    );

    paymentCash.value = formatMoneyInput(cash);
    paymentClick.value = formatMoneyInput(click);

    renderPaymentModal();
  });

  paymentClick.addEventListener("input", () => {
    if (paymentMethod !== "MIXED") {
      return;
    }

    const payable = currentPayable();
    const click = Math.min(
      payable,
      parseMoneyInput(paymentClick.value)
    );

    const cash = Math.max(
      0,
      payable - click
    );

    paymentClick.value = formatMoneyInput(click);
    paymentCash.value = formatMoneyInput(cash);

    renderPaymentModal();
  });

  paymentModal
    .querySelectorAll("[data-payment-cancel]")
    .forEach((button) => {
      button.addEventListener("click", closePaymentModal);
    });

  paymentSubmit.addEventListener("click", () => {
    if (mutationBusy || !cart.items?.length) return;
    const payable = currentPayable();

    let cash = 0;
    let click = 0;

    if (paymentMethod === "CASH") {
      cash = payable;
    } else if (paymentMethod === "CLICK") {
      click = payable;
    } else {
      cash = parseMoneyInput(paymentCash.value);
      click = parseMoneyInput(paymentClick.value);
    }

    if (Math.abs((cash + click) - payable) > 0.01) {
      paymentError.textContent =
        "Naqd + Click summasi to‘lanadigan summaga teng bo‘lishi kerak.";
      paymentError.hidden = false;
      return;
    }

    setCheckoutField(
      "payment_method",
      paymentMethod
    );
    setCheckoutField(
      "cash_uzs",
      cash
    );
    setCheckoutField(
      "click_uzs",
      click
    );

    paymentModal.hidden = true;
    setBusy(true);

    const checkoutValues = Object.fromEntries(
      new FormData(checkoutForm).entries()
    );

    postForm(initial.urls.checkout, checkoutValues)
      .then(async (response) => {
        const result = await response.json();

        if (!result.ok) {
          throw new Error(
            result.error || "Sotuvni yakunlab bo‘lmadi."
          );
        }

        globalDiscountState.type = "none";
        globalDiscountState.value = 0;

        if (globalDiscountType) {
          globalDiscountType.value = "none";
        }

        if (globalDiscountValue) {
          globalDiscountValue.value = "0";
          globalDiscountValue.disabled = true;
        }

        await loadCart();
        searchInput.value = "";
        closeSearch();
        searchInput.focus();

        printSaleReceipt(result.sale_id);

        showToast(
          `Sotuv #${result.sale_id} yakunlandi.`
        );
      })
      .catch((error) => {
        console.error(error);

        showToast(
          error.message || "Sotuvni yakunlab bo‘lmadi.",
          true
        );
      })
      .finally(() => {
        setBusy(false);
      });
  });

  clearButton.addEventListener(
    "click",
    () => {
      confirmModal.hidden = false;
    }
  );

  confirmModal
    .querySelectorAll("[data-confirm-cancel]")
    .forEach((button) => {
      button.addEventListener("click", () => {
        confirmModal.hidden = true;
      });
    });

  confirmClear.addEventListener(
    "click",
    async () => {
      if (mutationBusy) return;
      setBusy(true);

      try {
        const response = await postForm(initial.urls.clear, {_pos_cart_json: "1"});
        cart = await response.json();
        renderCart();

        confirmModal.hidden = true;
        showToast("Savat tozalandi.");
      } catch (error) {
        console.error(error);
        showToast(
          "Savatni tozalab bo‘lmadi.",
          true
        );
      } finally {
        setBusy(false);
      }
    }
  );

  renderCart();
  searchInput.focus();
})();


