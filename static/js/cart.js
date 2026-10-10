/* Cart-style entry screen used for both "New sale" and "Record purchase".
   Product names are inserted with textContent (never innerHTML) to avoid XSS. */
(function () {
  const root = document.getElementById('cart-app');
  if (!root) return;
  const mode = root.dataset.mode;                       // "sale" | "purchase"
  const searchUrl = root.dataset.searchUrl;
  const submitUrl = root.dataset.submitUrl;
  const recommendBase = root.dataset.recommendUrl || '';
  const taxRate = parseFloat(root.dataset.taxRate || '0');
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;

  const $ = (id) => document.getElementById(id);
  const searchBox = $('product-search'), results = $('search-results'), tbody = $('cart-body');
  const errorBox = $('cart-error'), hint = $('recommend-hint'), submitBtn = $('submit-cart');
  let cart = [];
  let timer = null;

  const num = (v) => { const n = parseFloat(v); return isNaN(n) ? 0 : n; };
  const fmt = (n) => n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function showError(msg) { errorBox.textContent = msg || ''; errorBox.classList.toggle('d-none', !msg); }

  function addProduct(p) {
    const existing = cart.find((c) => c.id === p.id);
    if (existing) { existing.qty += 1; }
    else {
      cart.push({ id: p.id, name: p.name, stock: p.stock, price: num(p.price), cost: num(p.cost || 0), qty: 1, discount: 0 });
    }
    render();
    if (mode === 'sale' && recommendBase) loadRecommendations(p.id);
  }

  function lineTotal(c) { return mode === 'sale' ? Math.max(c.price * c.qty - c.discount, 0) : c.cost * c.qty; }

  function render() {
    tbody.replaceChildren();
    cart.forEach((c, idx) => {
      const tr = document.createElement('tr');
      const td = (child) => { const t = document.createElement('td'); if (child instanceof Node) t.appendChild(child); else t.textContent = child; tr.appendChild(t); return t; };
      td(c.name);
      td(String(c.stock)).className = 'text-muted';
      const qty = input(c.qty, 1, (v) => { c.qty = Math.max(1, parseInt(v) || 1); render(); }); td(qty);
      if (mode === 'sale') {
        td(fmt(c.price)).className = 'text-end';
        td(input(c.discount, 0, (v) => { c.discount = Math.max(0, num(v)); render(); }, '0.01'));
      } else {
        td(input(c.cost, 0, (v) => { c.cost = Math.max(0, num(v)); render(); }, '0.01'));
      }
      td(fmt(lineTotal(c))).className = 'text-end';
      const rm = document.createElement('button'); rm.type = 'button'; rm.className = 'btn btn-sm btn-outline-danger py-0'; rm.textContent = '×';
      rm.onclick = () => { cart.splice(idx, 1); render(); }; td(rm);
      tbody.appendChild(tr);
    });
    if (!cart.length) { const tr = document.createElement('tr'); const t = document.createElement('td'); t.colSpan = 7; t.className = 'text-muted text-center py-3'; t.textContent = 'Search for a product to add it.'; tr.appendChild(t); tbody.appendChild(tr); }
    totals();
  }

  function input(value, min, onchange, step) {
    const i = document.createElement('input'); i.type = 'number'; i.className = 'form-control form-control-sm cart-input'; i.min = min; i.value = value; if (step) i.step = step;
    i.onchange = () => onchange(i.value); return i;
  }

  function totals() {
    const sub = cart.reduce((s, c) => s + lineTotal(c), 0);
    if (mode === 'sale') {
      const tax = Math.round(sub * taxRate) / 100;
      $('t-subtotal').textContent = fmt(sub); $('t-tax').textContent = fmt(tax); $('t-total').textContent = fmt(sub + tax);
    } else { $('t-total').textContent = fmt(sub); }
  }

  function loadRecommendations(productId) {
    fetch(recommendBase.replace('/0/', '/' + productId + '/')).then((r) => r.json()).then((d) => {
      hint.replaceChildren();
      if (!d.results.length) return;
      const label = document.createElement('span'); label.textContent = 'Often bought together: '; hint.appendChild(label);
      d.results.forEach((r) => {
        const b = document.createElement('button'); b.type = 'button'; b.className = 'btn btn-sm btn-outline-info me-1';
        b.textContent = '+ ' + r.name + ' (' + r.confidence + '%)';
        b.onclick = () => fetch(searchUrl + '?q=' + encodeURIComponent(r.name)).then((x) => x.json()).then((s) => { const m = s.results.find((p) => p.id === r.id); if (m) addProduct(m); });
        hint.appendChild(b);
      });
    }).catch(() => {});
  }

  searchBox.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const q = searchBox.value.trim();
      if (!q) { results.replaceChildren(); return; }
      fetch(searchUrl + '?q=' + encodeURIComponent(q)).then((r) => r.json()).then((d) => {
        results.replaceChildren();
        d.results.forEach((p) => {
          const a = document.createElement('button'); a.type = 'button'; a.className = 'list-group-item list-group-item-action d-flex justify-content-between';
          const l = document.createElement('span'); l.textContent = p.name + ' (' + p.sku + ')';
          const r = document.createElement('span'); r.className = 'text-muted small'; r.textContent = 'stock ' + p.stock + ' · ' + p.price;
          a.append(l, r);
          a.onclick = () => { addProduct(p); results.replaceChildren(); searchBox.value = ''; searchBox.focus(); };
          results.appendChild(a);
        });
      });
    }, 200);
  });
  searchBox.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); const first = results.querySelector('button'); if (first) first.click(); } });

  submitBtn.addEventListener('click', () => {
    showError('');
    if (!cart.length) { showError('Add at least one product.'); return; }
    let payload;
    if (mode === 'sale') {
      const paid = $('amount-paid').value.trim();
      payload = {
        customer_id: $('customer').value || null, payment_method: $('payment-method').value,
        amount_paid: paid === '' ? null : paid, note: $('note').value,
        items: cart.map((c) => ({ product_id: c.id, quantity: c.qty, discount: c.discount })),
      };
    } else {
      payload = {
        supplier_id: $('supplier').value, paid_amount: $('paid-amount').value || 0, note: $('note').value,
        items: cart.map((c) => ({ product_id: c.id, quantity: c.qty, unit_cost: c.cost })),
      };
    }
    submitBtn.disabled = true;
    fetch(submitUrl, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(payload) })
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => { if (ok && d.ok) { window.location = d.redirect; } else { showError(d.error || 'Could not save.'); submitBtn.disabled = false; } })
      .catch(() => { showError('Network error. Please try again.'); submitBtn.disabled = false; });
  });

  render();
})();
