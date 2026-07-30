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
  const checkoutButton = document.getElementById("pos-checkout");
  const clearButton = document.getElementById("pos-clear");
  const searchInput = document.getElementById("pos-search");
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

  const money = (value) => {
    const numeric = Number(value || 0);

    return Math.round(numeric).toLocaleString("ru-RU");
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
                <small>so‘m</small>
              </div>
            </label>
          </div>

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
