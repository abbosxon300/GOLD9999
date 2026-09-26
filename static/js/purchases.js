(() => {
  'use strict';
  const dataNode = document.getElementById('pw-data');
  if (!dataNode) return;
  const data = JSON.parse(dataNode.textContent);
  const form = document.getElementById('purchase-form');
  const $ = id => document.getElementById(id);
  const products = new Map(data.products.map(p => [String(p.id), p]));
  const money = v => new Intl.NumberFormat('uz-UZ', {maximumFractionDigits: 2}).format(v || 0);
  const num = v => Number(String(v).replace(/\s/g, '').replace(',', '.'));
  const round = v => Math.round((v + Number.EPSILON) * 100) / 100;
  let cart = [], results = [], selected = -1, draftTimer, submitting = false, changed = false;
  const draftKey = data.draftKey;
  const successKey = `${draftKey}:submitted`;
  function setFieldError(id, message) {
    const node = $(id);
    if (!node) return;
    node.textContent = message || '';
    node.hidden = !message;
  }
  function clearEntryErrors() {
    setFieldError('pw-supplier-select-error', '');
    setFieldError('pw-date-error', '');
    $('pw-supplier').removeAttribute('aria-invalid');
    $('pw-purchase-date').removeAttribute('aria-invalid');
  }
  function element(tag, text, cls) {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }
  function normalizedItems(items) {
    return (Array.isArray(items) ? items : []).filter(i => i && products.has(String(i.product_id))).map(i => ({
      product_id: String(i.product_id), qty: String(i.qty ?? 1), unit_cost_uzs: String(i.unit_cost_uzs ?? 0)
    }));
  }
  function total() { return round(cart.reduce((sum, i) => sum + round((num(i.qty) || 0) * (num(i.unit_cost_uzs) || 0)), 0)); }
  function totals() {
    const amount = total(), paid = num($('pw-paid').value) || 0;
    $('pw-total').textContent = money(amount);
    $('pw-debt').textContent = money(amount - paid);
    $('pw-item-count').textContent = `${cart.length} tur`;
    $('pw-items').value = JSON.stringify(cart);
    $('pw-cart-empty').hidden = cart.length > 0;
  }
  function saveDraft() {
    if (submitting) return;
    const draft = {};
    ['supplier_id', 'purchase_date', 'reference', 'note', 'paid', 'method', 'entity_uuid', 'expected_version'].forEach(k => {
      if (form.elements[k]) draft[k] = form.elements[k].value;
    });
    draft.items = cart;
    try {
      localStorage.setItem(draftKey, JSON.stringify(draft));
      $('pw-draft-status').textContent = 'Qoralama shu brauzerda saqlandi';
    } catch (_) { $('pw-draft-status').textContent = 'Brauzer qoralamani saqlay olmadi'; }
  }
  function edited() {
    changed = true;
    clearTimeout(draftTimer);
    draftTimer = setTimeout(saveDraft, 450);
  }
  function renderCart() {
    const body = $('pw-cart'); body.replaceChildren();
    cart.forEach((item, index) => {
      const p = products.get(item.product_id), row = element('tr');
      const name = element('td'); name.append(element('strong', p.name), element('small', `${p.category} · Qoldiq: ${money(p.stock_qty)}`)); row.append(name);
      const sum = element('td', money(num(item.qty) * num(item.unit_cost_uzs)), 'num');
      ['qty', 'unit_cost_uzs'].forEach(field => {
        const td = element('td'), input = element('input');
        input.value = item[field]; input.inputMode = 'decimal'; input.required = true; input.dataset.field = field;
        input.setAttribute('aria-label', `${p.name}: ${field === 'qty' ? 'miqdor' : 'kirim narxi'}`);
        input.addEventListener('input', () => { item[field] = input.value; sum.textContent = money(round(num(item.qty) * num(item.unit_cost_uzs))); totals(); edited(); });
        input.addEventListener('blur', () => { const n = num(input.value); if (Number.isFinite(n) && n > 0) { item[field] = String(field === 'qty' ? Math.round(n * 1000) / 1000 : round(n)); input.value = item[field]; totals(); edited(); } });
        td.append(input); row.append(td);
      });
      row.append(sum);
      const remove = element('button', '×', 'pw-icon-button'); remove.type = 'button'; remove.setAttribute('aria-label', `${p.name}ni olib tashlash`);
      remove.addEventListener('click', () => { cart.splice(index, 1); renderCart(); edited(); });
      const action = element('td'); action.append(remove); row.append(action); body.append(row);
    });
    totals();
  }
  function closeResults() { $('pw-results').hidden = true; $('pw-search').setAttribute('aria-expanded','false'); $('pw-search').removeAttribute('aria-activedescendant'); }
  function addProduct(p) {
    const existing = cart.find(i => i.product_id === String(p.id));
    if (existing) existing.qty = String(round((num(existing.qty) || 0) + 1));
    else if (cart.length < 200) cart.push({product_id: String(p.id), qty:'1', unit_cost_uzs:String(p.last_cost || '')});
    else { alert('Bir hujjatda 200 tagacha mahsulot qo‘shish mumkin.'); return; }
    renderCart(); edited(); $('pw-search').value = ''; $('pw-search').focus(); closeResults();
  }
  function showResults() {
    const query = $('pw-search').value.trim().toLocaleLowerCase();
    const target = $('pw-results'); target.replaceChildren();
    results = data.products.filter(p => !query || `${p.name} ${p.category} ${p.barcodes}`.toLocaleLowerCase().includes(query)).slice(0,30);
    selected = -1;
    if (!results.length) target.append(element('div', 'Mahsulot topilmadi. Mahsulotlar sozlamasida qo‘shilganini tekshiring.', 'pw-result-note'));
    results.forEach((p, index) => {
      const button = element('button', undefined, 'pw-result');
      button.type='button';
      button.id=`pw-result-${index}`;
      button.setAttribute('role','option');
      button.setAttribute('aria-selected','false');

      const main = element('span', undefined, 'pw-result-main');
      const name = element('span', undefined, 'pw-result-name');
      name.append(element('strong', p.name));
      main.append(name, element('span', p.category, 'pw-result-category'));

      const meta = element('span', undefined, 'pw-result-meta');
      const price = element('span', undefined, 'pw-result-price');
      price.append(
        element('small', 'Kirim narxi'),
        element('strong', money(p.last_cost))
      );
      const stock = element('span', undefined, 'pw-result-stock');
      stock.append(
        element('small', 'Qoldiq'),
        element('strong', money(p.stock_qty))
      );
      meta.append(price, stock);

      button.append(main, meta);
      button.addEventListener('click',() => addProduct(p));
      target.append(button);
    });
    target.hidden=false; $('pw-search').setAttribute('aria-expanded','true');
  }
  $('pw-search').addEventListener('input',showResults);
  $('pw-search').addEventListener('focus',showResults);
  $('pw-search').addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeResults(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); if ($('pw-results').hidden) showResults();
      selected = Math.max(0,Math.min(results.length-1,selected + (e.key==='ArrowDown' ? 1 : -1)));
      [...$('pw-results').querySelectorAll('[role=option]')].forEach((b,i)=>b.setAttribute('aria-selected',String(i===selected)));
      if (selected>=0) { const current=$(`pw-result-${selected}`); $('pw-search').setAttribute('aria-activedescendant',current.id); current.scrollIntoView({block:'nearest'}); }
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      const exact = data.products.find(p=>p.barcodes.split(' ').includes($('pw-search').value.trim()));
      if (exact) addProduct(exact); else if(results.length) addProduct(results[selected>=0 ? selected : 0]);
    }
  });
  document.addEventListener('click',e=>{ if (!e.target.closest('.pw-product-search')) closeResults(); });
  const addMore = $('pw-add-more');
  if (addMore) addMore.addEventListener('click',()=>{$('pw-search').focus();showResults();});
  $('pw-paid').addEventListener('input',totals);
  const payAll = $('pw-pay-all');
  if (payAll) payAll.addEventListener('click',()=>{$('pw-paid').value=String(total());totals();edited();});
  form.addEventListener('input',edited); form.addEventListener('change',edited);
  $('pw-supplier').addEventListener('change',()=>{
    setFieldError('pw-supplier-select-error','');
    $('pw-supplier').removeAttribute('aria-invalid');
  });
  $('pw-purchase-date').addEventListener('input',()=>{
    setFieldError('pw-date-error','');
    $('pw-purchase-date').removeAttribute('aria-invalid');
  });
  form.addEventListener('submit',e=>{
    clearEntryErrors();
    const supplierMissing = !$('pw-supplier').value;
    const dateMissing = !$('pw-purchase-date').value;
    const bad = cart.find(i => !Number.isFinite(num(i.qty)) || num(i.qty)<=0 || !Number.isFinite(num(i.unit_cost_uzs)) || num(i.unit_cost_uzs)<=0);
    const paid = num($('pw-paid').value || '0');
    const paymentError = data.editMode
      ? 'Jami summa oldin to‘langan summadan kam bo‘lishi mumkin emas.'
      : 'To‘lov 0 dan jami summagacha bo‘lishi kerak.';

    if (supplierMissing) {
      setFieldError('pw-supplier-select-error', 'Yetkazib beruvchini tanlang.');
      $('pw-supplier').setAttribute('aria-invalid', 'true');
    }
    if (dateMissing) {
      setFieldError('pw-date-error', 'Kirim sanasini kiriting.');
      $('pw-purchase-date').setAttribute('aria-invalid', 'true');
    }

    const message = !cart.length
      ? 'Kamida bitta mahsulot qo‘shing.'
      : bad
        ? 'Miqdor va kirim narxini musbat son bilan kiriting.'
        : !Number.isFinite(paid)||paid<0||paid>total()
          ? paymentError
          : '';

    if (supplierMissing || dateMissing || message || submitting) {
      e.preventDefault();
      $('pw-form-error').textContent=message;
      $('pw-form-error').hidden=!message;
      if (supplierMissing) $('pw-supplier').focus();
      else if (dateMissing) $('pw-purchase-date').focus();
      return;
    }

    totals(); saveDraft(); submitting=true; clearTimeout(draftTimer);
    // Only the success page removes the draft; a failed save keeps every entered value.
    try { sessionStorage.setItem(successKey,form.elements.entity_uuid.value); } catch (_) {}
    $('pw-save').disabled=true; $('pw-save').textContent='Saqlanmoqda…';
  });
  window.addEventListener('pageshow',()=>{submitting=false;$('pw-save').disabled=false;$('pw-save').textContent=data.saveLabel||'Kirimni saqlash';});
  window.addEventListener('beforeunload',e=>{if(changed&&!submitting){saveDraft();e.preventDefault();e.returnValue='';}});
  cart=normalizedItems(data.initial.items); renderCart();
  try {
    const raw=localStorage.getItem(draftKey);
    if(raw && !data.hasError) {
      const draft=JSON.parse(raw);
      if(draft && Array.isArray(draft.items)) {
        $('pw-draft').hidden=false;
        $('pw-restore').addEventListener('click',()=>{
          ['supplier_id','purchase_date','reference','note','paid','method','entity_uuid','expected_version'].forEach(k=>{
            if(typeof draft[k]==='string' && form.elements[k]) form.elements[k].value=draft[k];
          });
          cart=normalizedItems(draft.items);renderCart();$('pw-draft').hidden=true;edited();
        });
      }
    }
  } catch (_) {}
  $('pw-discard').addEventListener('click',()=>{try{localStorage.removeItem(draftKey);}catch(_){}$('pw-draft').hidden=true;});
  const dialog=$('pw-supplier-dialog');
  $('pw-open-supplier').addEventListener('click',()=>dialog.showModal());
  $('pw-close-supplier').addEventListener('click',()=>dialog.close());
  $('pw-supplier-form').addEventListener('submit',async e=>{
    e.preventDefault();
    const supplierForm=e.currentTarget,button=supplierForm.querySelector('[type=submit]');
    const supplierName=String(supplierForm.elements.name.value||'').trim();
    $('pw-supplier-error').textContent='';
    if(!supplierName){
      $('pw-supplier-error').textContent='Yetkazib beruvchi nomini kiriting.';
      supplierForm.elements.name.focus();
      return;
    }
    button.disabled=true;
    try {
      const response=await fetch(supplierForm.action,{method:'POST',body:new FormData(supplierForm),headers:{Accept:'application/json'},credentials:'same-origin'});
      const result=await response.json();if(!response.ok)throw new Error(result.error||'Yetkazuvchi qo‘shilmadi');
      let option=[...$('pw-supplier').options].find(o=>o.value===String(result.id));
      if(!option){option=element('option',`${result.name}${result.phone?' · '+result.phone:''}`);option.value=String(result.id);$('pw-supplier').append(option);}
      $('pw-supplier').value=String(result.id);dialog.close();edited();
      // Keep the same idempotency key for retries; a new supplier gets a fresh key.
      supplierForm.reset(); supplierForm.elements.entity_uuid.value=result.next_uuid;
    } catch(error){$('pw-supplier-error').textContent=error instanceof SyntaxError?'Ulanish yoki sessiyani tekshiring.':error.message;}
    finally{button.disabled=false;}
  });
})();
