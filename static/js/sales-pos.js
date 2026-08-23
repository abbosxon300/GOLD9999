(() => {
  "use strict";

  const root = document.getElementById("sales-pos");

  if (!root || !window.SALES_POS_INITIAL) {
    return;
  }

  const initial = window.SALES_POS_INITIAL;
  const productsNode = document.getElementById("pos-products");
  const productsEmpty = document.getElementById("pos-products-empty");
  const productCount = document.getElementById("pos-product-count");
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

  let products = Array.isArray(initial.products)
    ? initial.products
    : [];

  let cart = initial.cart || {
    items: [],
    item_count: 0,
    qty_total: 0,
    cart_total: 0,
  };

  let activeCategoryId = Number(initial.categoryId || 0);
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

  const setBusy = (busy) => {
    root.classList.toggle("is-busy", busy);
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
      throw new Error(`HTTP ${response.status}`);
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

  const stockClass = (qty) => {
    const numeric = Number(qty || 0);

    if (numeric <= 0) {
      return "is-out";
    }

    if (numeric <= 5) {
      return "is-low";
    }

    return "is-ready";
  };

  const stockLabel = (qty) => {
    const numeric = Number(qty || 0);

    if (numeric <= 0) {
      return "Tugagan";
    }

    return `${qtyText(numeric)} dona`;
  };

  const productTemplate = (product) => {
    const stock = Number(product.qty || 0);
    const disabled = stock <= 0;

    return `
      <article
        class="pos-product"
        data-product-id="${Number(product.id)}"
        data-product-name="${escapeHtml(
          String(product.name || "").toLocaleLowerCase("uz")
        )}"
      >
        <div class="pos-product-head">
          <div class="pos-product-name">
            <h3>${escapeHtml(product.name)}</h3>
            <span>ID: ${Number(product.id)}</span>
          </div>

          <span class="pos-stock ${stockClass(stock)}">
            ${stockLabel(stock)}
          </span>
        </div>

        <div class="pos-product-price">
          <span>Standart narx</span>
          <strong>
            ${money(product.sell_default)}
            <small>so‘m</small>
          </strong>
        </div>

        <form
          class="pos-product-form"
          action="${escapeHtml(initial.urls.add)}"
          method="post"
          data-add-form
        >
          <input
            type="hidden"
            name="category_id"
            value="${activeCategoryId}"
          >
          <input
            type="hidden"
            name="product_id"
            value="${Number(product.id)}"
          >

            <div class="pos-fields">
              <label class="pos-field">
                <span>Miqdor</span>
                <input
                  class="pos-qty-input"
                  name="qty"
                  type="number"
                  inputmode="decimal"
                  min="0.01"
                  step="any"
                  value="1"
                  required
                >
              </label>

              <label class="pos-field">
                <span>Sotuv narxi</span>
                <div class="pos-money">
                  <input
                    name="price_uzs"
                    inputmode="numeric"
                    value="${money(product.sell_default)}"
                    required
                    data-money-input
                  >
                  <small>so?m</small>
                </div>
              </label>
            </div>

            <input
              type="hidden"
              name="list_price_uzs"
              value="${Number(product.sell_default)}"
            >
            <input
              type="hidden"
              name="discount_type"
              value="none"
            >
            <input
              type="hidden"
              name="discount_value"
              value="0"
            >

          <button
            class="pos-add"
            type="submit"
            ${disabled ? "disabled" : ""}
          >
            <svg viewBox="0 0 24 24" fill="none">
              <circle cx="9" cy="20" r="1.5"></circle>
              <circle cx="18" cy="20" r="1.5"></circle>
              <path d="M3 4h2l2.4 10.2a2 2 0 0 0 2 1.5h7.7a2 2 0 0 0 2-1.6L21 8H7"></path>
            </svg>
            ${disabled ? "Qoldiq yo‘q" : "Savatga qo‘shish"}
          </button>
        </form>
      </article>
    `;
  };

  const applySearch = () => {
    const query = String(searchInput?.value || "")
      .trim()
      .toLocaleLowerCase("uz");

    const cards = Array.from(
      productsNode.querySelectorAll(".pos-product")
    );

    let visible = 0;

    cards.forEach((card) => {
      const match = (
        !query ||
        String(card.dataset.productName || "").includes(query)
      );

      card.hidden = !match;

      if (match) {
        visible += 1;
      }
    });

    productsEmpty.hidden = visible !== 0;
    productCount.textContent = `${visible} ta`;
  };

  const renderProducts = () => {
    productsNode.innerHTML = products
      .map(productTemplate)
      .join("");

    applySearch();
  };

  const cartItemTemplate = (item) => {
    const productId = Number(item.product_id);
    const qty = Number(item.qty || 0);
    const price = Number(item.price || 0);
    const lineTotal = Number(
      item.line_total ?? qty * price
    );
    const listPrice = Number(
      item.list_price ?? price
    );
    const discountType = String(
      item.discount_type || "none"
    );
    const discountValue = Number(
      item.discount_value || 0
    );
    const discountTotal = Number(
      item.discount_total || 0
    );

    return `
      <article class="pos-cart-item">
        <div class="pos-cart-item-head">
          <div>
            <h3>${escapeHtml(item.name)}</h3>
            <div class="pos-cart-item-price">
              ${money(price)} so‘m
            </div>
          </div>

          <button
            class="pos-cart-remove"
            type="button"
            data-cart-remove="${productId}"
            aria-label="Savatdan o‘chirish"
            title="O‘chirish"
          >
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M4 7h16"></path>
              <path d="M9 7V4h6v3"></path>
              <path d="m6 7 1 14h10l1-14"></path>
              <path d="M10 11v6M14 11v6"></path>
            </svg>
          </button>
        </div>

        <div class="pos-cart-item-bottom">
          <div class="pos-qty-control">
            <button
              type="button"
              data-cart-action="dec"
              data-product-id="${productId}"
              aria-label="Miqdorni kamaytirish"
            >−</button>

            <strong>${qtyText(qty)}</strong>

            <button
              type="button"
              data-cart-action="inc"
              data-product-id="${productId}"
              aria-label="Miqdorni oshirish"
            >+</button>
          </div>

          <div class="pos-line-total">
            <span>Jami</span>
            <strong>${money(lineTotal)} so‘m</strong>
          </div>
        </div>
      </article>
    `;
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
          <p>Chap tomondan mahsulot tanlang.</p>
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

    checkoutButton.disabled = empty;
    clearButton.disabled = empty;
  };

  const loadProducts = async (categoryId) => {
    const url = new URL(
      initial.urls.products,
      window.location.origin
    );

    url.searchParams.set(
      "category_id",
      String(categoryId)
    );

    setBusy(true);

    try {
      const response = await fetch(url, {
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
        credentials: "same-origin",
      });

      if (!response.ok) {
        throw new Error(`Products HTTP ${response.status}`);
      }

      const payload = await response.json();

      products = Array.isArray(payload.products)
        ? payload.products
        : [];

      activeCategoryId = Number(categoryId);
      renderProducts();

      const nextUrl = new URL(window.location.href);
      nextUrl.searchParams.set(
        "category_id",
        String(categoryId)
      );

      window.history.replaceState(
        {},
        "",
        nextUrl
      );
    } catch (error) {
      console.error(error);
      showToast(
        "Mahsulotlarni yuklab bo‘lmadi.",
        true
      );
    } finally {
      setBusy(false);
    }
  };

  document
    .getElementById("pos-categories")
    ?.addEventListener("click", async (event) => {
      const button = event.target.closest(
        "[data-category-id]"
      );

      if (!button) {
        return;
      }

      document
        .querySelectorAll("[data-category-id]")
        .forEach((node) => {
          node.classList.toggle(
            "is-active",
            node === button
          );
        });

      await loadProducts(
        Number(button.dataset.categoryId)
      );
    });

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

  productsNode.addEventListener(
    "input",
    (event) => {
      const input = event.target.closest(
        "[data-money-input]"
      );

      if (!input) {
        return;
      }

      const digits = String(input.value)
        .replace(/\D/g, "");

      input.value = digits
        ? Number(digits).toLocaleString("ru-RU")
        : "";
    }
  );

  productsNode.addEventListener(
    "submit",
    async (event) => {
      const form = event.target.closest(
        "[data-add-form]"
      );

      if (!form) {
        return;
      }

      event.preventDefault();

      const formData = new FormData(form);
      const values = Object.fromEntries(
        formData.entries()
      );

      values.price_uzs = String(
        values.price_uzs || ""
      ).replace(/\D/g, "");

      // Product cardda item-level skidka yo‘q.
      // Kiritilgan sotuv narxi global skidkagacha
      // bo‘lgan canonical narx hisoblanadi.
      values.list_price_uzs = values.price_uzs;
      values.discount_type = "none";
      values.discount_value = "0";

      setBusy(true);

      try {
        await postForm(form.action, values);
        await loadCart();

        const qtyInput = form.querySelector(
          "[name='qty']"
        );

        if (qtyInput) {
          qtyInput.value = "1";
        }

        showToast("Mahsulot savatga qo‘shildi.");
      } catch (error) {
        console.error(error);
        showToast(
          "Mahsulotni qo‘shib bo‘lmadi.",
          true
        );
      } finally {
        setBusy(false);
      }
    }
  );

  cartBody.addEventListener(
    "click",
    async (event) => {
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
        await postForm(url);
        await loadCart();
      } catch (error) {
        console.error(error);
        showToast(
          "Savatni yangilab bo‘lmadi.",
          true
        );
      } finally {
        setBusy(false);
      }
    }
  );

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

    if (paymentModal.hidden) {
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

        await Promise.all([
          loadCart(),
          activeCategoryId > 0
            ? loadProducts(activeCategoryId)
            : Promise.resolve(),
        ]);

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
      setBusy(true);

      try {
        await postForm(initial.urls.clear);
        await loadCart();

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

  renderProducts();
  renderCart();
})();
