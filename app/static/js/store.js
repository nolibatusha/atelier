/* Storefront behaviour. Progressive enhancement: every flow also works without JS (server-rendered forms). */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var csrf = function () { var m = $('meta[name=csrf-token]'); return m ? m.content : ''; };

  var toastEl = $('[data-toast]'), toastTimer;
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg; toastEl.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { toastEl.hidden = true; }, 3500);
  }
  function setCount(n) {
    $$('[data-cart-count]').forEach(function (el) { el.textContent = n; el.hidden = !n; });
  }

  // ---- generic hooks -------------------------------------------------------
  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t.matches && t.matches('[data-autosubmit]')) {
      var f = t.form || t.closest('form');
      if (t.name === 'sort') { var mirror = $('[data-sort-mirror]'); if (mirror) mirror.value = t.value; }
      if (f) f.requestSubmit ? f.requestSubmit() : f.submit();
    }
  });
  document.addEventListener('click', function (e) {
    var d = e.target.closest('[data-dismiss]');
    if (d) { var box = d.closest('.flash, .notice'); if (box) box.remove(); }
  });
  document.addEventListener('submit', function (e) {
    var msg = e.target.getAttribute && e.target.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // ---- header ----------------------------------------------------------------
  var menuBtn = $('[data-menu-toggle]'), nav = $('#primary-nav');
  if (menuBtn && nav) menuBtn.addEventListener('click', function () {
    var open = nav.classList.toggle('open'); menuBtn.setAttribute('aria-expanded', open);
  });
  function closeMenu() { if (nav && nav.classList.contains('open')) { nav.classList.remove('open'); menuBtn.setAttribute('aria-expanded', 'false'); } }
  document.addEventListener('click', function (e) {
    if (!nav || !nav.classList.contains('open')) return;
    if (e.target.closest('#primary-nav a') || !e.target.closest('.site-header')) closeMenu();
  });
  var sBtn = $('[data-search-toggle]'), sPanel = $('[data-search-panel]');
  if (sBtn && sPanel) sBtn.addEventListener('click', function () {
    sPanel.hidden = !sPanel.hidden;
    if (!sPanel.hidden) { var i = $('input', sPanel); if (i) i.focus(); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (sPanel && !sPanel.hidden) sPanel.hidden = true;
    closeFilters(); closeMenu();
    var lb = $('.lightbox'); if (lb) lb.remove();
  });

  // ---- mobile filters drawer -------------------------------------------------
  var filters = $('#filters');
  function closeFilters() { if (filters) { filters.classList.remove('open'); document.body.classList.remove('filters-lock'); } }
  var fo = $('[data-filters-open]'), fc = $('[data-filters-close]');
  if (fo && filters) fo.addEventListener('click', function () { filters.classList.add('open'); document.body.classList.add('filters-lock'); });
  if (fc) fc.addEventListener('click', closeFilters);
  document.addEventListener('click', function (e) { if (filters && filters.classList.contains('open') && !e.target.closest('#filters') && !e.target.closest('[data-filters-open]')) closeFilters(); });
  // desktop: apply filter changes immediately
  if (filters && window.matchMedia('(min-width:900px)').matches) {
    filters.addEventListener('change', function (e) {
      if (e.target.matches('input[type=number]')) return;
      filters.requestSubmit ? filters.requestSubmit() : filters.submit();
    });
  }

  // ---- newsletter (AJAX, falls back to normal post) ---------------------------
  $$('[data-newsletter]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!window.fetch) return;
      e.preventDefault();
      fetch(form.action, { method: 'POST', body: new FormData(form), headers: { Accept: 'application/json', 'X-CSRF-Token': csrf() }, credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (j) { toast(j.message || (j.ok ? 'Thank you for subscribing.' : 'Please check your email address.')); if (j.ok) form.reset(); })
        .catch(function () { toast('Something went wrong. Please try again.'); });
    });
  });

  // ---- product page ----------------------------------------------------------
  var buy = $('[data-buy]');
  if (buy) {
    var dataEl = $('#variant-data'), variants = [];
    try { variants = JSON.parse(dataEl ? dataEl.textContent : '[]'); } catch (_) {}
    var colorInputs = $$('input[name=color]', buy), sizeInputs = $$('input[name=size]', buy);
    var hidden = $('[data-variant-input]', buy), stockMsg = $('[data-stock]', buy), colorLabel = $('[data-color-label]', buy);
    var addBtn = $('[data-add]', buy), nowBtn = $('[data-buy-now]', buy);
    var qtyInput = $('[data-qty-input]', buy), maxLine = parseInt(buy.getAttribute('data-max-line'), 10) || 10;
    var hasColor = colorInputs.length > 0, hasSize = sizeInputs.length > 0;
    var checked = function (list) { var c = list.filter(function (i) { return i.checked; })[0]; return c ? c.value : null; };

    var current = null;
    function refresh() {
      var color = checked(colorInputs), size = checked(sizeInputs);
      if (colorLabel) colorLabel.textContent = color || '';
      // availability of each size for the chosen colour, and of each colour overall
      sizeInputs.forEach(function (i) {
        var ok = variants.some(function (v) { return v.size === i.value && (!hasColor || !color || v.color === color) && v.stock > 0; });
        i.disabled = !ok; if (!ok && i.checked) i.checked = false;
      });
      colorInputs.forEach(function (i) {
        var ok = variants.some(function (v) { return v.color === i.value && v.stock > 0; });
        i.disabled = !ok; if (!ok && i.checked) i.checked = false;
      });
      color = checked(colorInputs); size = checked(sizeInputs);
      current = null;
      if ((!hasColor || color) && (!hasSize || size)) {
        current = variants.filter(function (v) { return (!hasColor || v.color === color) && (!hasSize || v.size === size); })[0] || null;
      }
      hidden.value = current ? current.id : '';
      var out = !variants.some(function (v) { return v.stock > 0; });
      var msg = '', cls = 'stock-msg';
      if (out) { msg = 'Sold out'; cls += ' out'; }
      else if (!current) msg = 'Select ' + (hasColor && !color ? 'a colour' : hasSize ? 'a size' : 'an option');
      else if (current.stock <= 0) { msg = 'Sold out'; cls += ' out'; }
      else if (current.stock <= 3) { msg = 'Only ' + current.stock + ' left'; cls += ' low'; }
      else msg = 'In stock';
      stockMsg.textContent = msg; stockMsg.className = cls;
      var cap = current ? Math.min(current.stock, maxLine) : maxLine;
      qtyInput.max = cap; if (+qtyInput.value > cap) qtyInput.value = Math.max(1, cap);
      var can = !out && (!current || current.stock > 0);
      addBtn.disabled = nowBtn.disabled = !can;
    }
    buy.addEventListener('change', function (e) { if (e.target.matches('input[type=radio]')) refresh(); });
    // preselect when there is only one choice
    [colorInputs, sizeInputs].forEach(function (list) { if (list.length === 1) list[0].checked = true; });
    refresh();

    var step = function (d) { var v = (parseInt(qtyInput.value, 10) || 1) + d; qtyInput.value = Math.min(Math.max(1, v), parseInt(qtyInput.max, 10) || maxLine); };
    $('[data-qty-minus]', buy).addEventListener('click', function () { step(-1); });
    $('[data-qty-plus]', buy).addEventListener('click', function () { step(1); });

    var bar = $('[data-buybar]'), barBtn = $('[data-buybar-add]');
    if (bar && barBtn) {
      var sync2 = function () { barBtn.disabled = addBtn.disabled; };
      var origRefresh = refresh; refresh = function () { origRefresh(); sync2(); };
      refresh();
      barBtn.addEventListener('click', function () {
        if (!current) {   // guide the shopper to the missing option instead of failing silently
          var grp = $('.opt-group', buy); if (grp) grp.scrollIntoView({ behavior: 'smooth', block: 'center' });
          toast(stockMsg.textContent.indexOf('Select') === 0 ? stockMsg.textContent + ' first.' : 'This option is unavailable.');
          return;
        }
        buy.requestSubmit ? buy.requestSubmit(addBtn) : addBtn.click();
      });
      if ('IntersectionObserver' in window) {
        new IntersectionObserver(function (en) { bar.hidden = en[0].isIntersecting; }, { rootMargin: '0px 0px -10px 0px' }).observe(addBtn);
      } else { bar.hidden = false; }
    }
    var busy = false;
    buy.addEventListener('submit', function (e) {
      var viaNow = e.submitter && e.submitter.hasAttribute('data-buy-now');
      if (!current) { e.preventDefault(); toast(stockMsg.textContent.indexOf('Select') === 0 ? 'Please ' + stockMsg.textContent.toLowerCase().replace('select', 'select') + '.' : 'This option is unavailable.'); return; }
      if (viaNow || !window.fetch) return; // normal post → server redirects to checkout
      e.preventDefault(); if (busy) return; busy = true; addBtn.disabled = true;
      var fd = new FormData(buy);
      fetch(buy.action, { method: 'POST', body: fd, headers: { Accept: 'application/json', 'X-CSRF-Token': csrf() }, credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (j) { if (j.ok) setCount(j.cart_count); toast(j.message || (j.ok ? 'Added to your bag.' : 'Could not add to bag.')); })
        .catch(function () { toast('Something went wrong. Please try again.'); })
        .then(function () { busy = false; refresh(); });
    });

    // gallery + zoom
    var gallery = $('[data-gallery]'), stage = $('[data-zoom]'), stageImg = $('#stage-img');
    var thumbs = gallery ? $$('.thumb', gallery) : [], dots = gallery ? $$('.swipe-dots i', gallery) : [], idx = 0;
    function show(i) {
      if (!thumbs.length) return;
      idx = (i + thumbs.length) % thumbs.length;
      var t = thumbs[idx];
      thumbs.forEach(function (x) { x.classList.remove('active'); });
      dots.forEach(function (d, k) { d.classList.toggle('on', k === idx); });
      t.classList.add('active');
      stageImg.removeAttribute('srcset');
      stageImg.src = t.getAttribute('data-src');
      var ss = t.getAttribute('data-srcset'); if (ss) stageImg.setAttribute('srcset', ss);
      stageImg.setAttribute('data-full', t.getAttribute('data-full') || t.getAttribute('data-src'));
      if (t.scrollIntoView) { try { t.scrollIntoView({ block: 'nearest', inline: 'center' }); } catch (_) {} }
    }
    thumbs.forEach(function (t, i) { t.addEventListener('click', function () { show(i); }); });
    if (stage && thumbs.length > 1) {   // swipe on touch screens
      var sx = 0, sy = 0, moved = false;
      stage.addEventListener('touchstart', function (e) { sx = e.touches[0].clientX; sy = e.touches[0].clientY; moved = false; }, { passive: true });
      stage.addEventListener('touchend', function (e) {
        var dx = e.changedTouches[0].clientX - sx, dy = e.changedTouches[0].clientY - sy;
        if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy) * 1.5) { show(idx + (dx < 0 ? 1 : -1)); moved = true; }
      }, { passive: true });
      stage.addEventListener('click', function (e) { if (moved) { e.stopImmediatePropagation(); moved = false; } }, true);
    }
    if (stage) {
      stage.addEventListener('mousemove', function (e) {
        if (!window.matchMedia('(hover:hover)').matches) return;
        var r = stage.getBoundingClientRect();
        stageImg.style.setProperty('--zx', ((e.clientX - r.left) / r.width * 100) + '%');
        stageImg.style.setProperty('--zy', ((e.clientY - r.top) / r.height * 100) + '%');
        stage.classList.add('zooming');
      });
      stage.addEventListener('mouseleave', function () { stage.classList.remove('zooming'); });
      var open = function () {
        var lb = document.createElement('div'); lb.className = 'lightbox'; lb.setAttribute('role', 'dialog'); lb.setAttribute('aria-label', 'Enlarged image');
        var im = document.createElement('img'); im.src = stageImg.getAttribute('data-full') || stageImg.currentSrc || stageImg.src; im.alt = stageImg.alt; lb.appendChild(im);
        lb.addEventListener('click', function () { lb.remove(); }); document.body.appendChild(lb);
      };
      stage.addEventListener('click', open);
      stage.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
    }
  }

  // ---- checkout --------------------------------------------------------------
  var co = $('[data-checkout]');
  if (co) {
    var sync = function () {
      var r = $('input[name=shipping_method_id]:checked', co); if (!r) return;
      var set = function (sel, val) { $$(sel).forEach(function (el) { if (val) el.textContent = val; }); };
      set('[data-sum-shipping]', /(^|[^\d.,])0[.,]00$/.test(r.getAttribute('data-shipping')) ? 'Free' : r.getAttribute('data-shipping'));
      set('[data-sum-tax]', r.getAttribute('data-tax')); set('[data-sum-total]', r.getAttribute('data-total'));
    };
    co.addEventListener('change', function (e) { if (e.target.name === 'shipping_method_id') sync(); });
    sync();
    var pick = $('[data-address-picker]');
    if (pick) pick.addEventListener('change', function () {
      var o = pick.options[pick.selectedIndex]; if (!o.value) return;
      var map = { ship_name: 'name', ship_line1: 'line1', ship_line2: 'line2', ship_city: 'city', ship_region: 'region', ship_postal: 'postal', ship_country: 'country' };
      Object.keys(map).forEach(function (k) { var f = co.elements[k]; if (f) f.value = o.getAttribute('data-' + map[k]) || ''; });
      var ph = co.elements.phone; if (ph && !ph.value) ph.value = o.getAttribute('data-phone') || '';
    });
    var placing = false;
    co.addEventListener('submit', function (e) {
      if (placing) { e.preventDefault(); return; } // prevent double-submit (server is idempotent too)
      placing = true; $$('button[type=submit][form=checkout-form]').forEach(function (b) { b.disabled = true; b.textContent = 'Placing order…'; });
    });
    // the Place order button lives outside the form but references it
    $$('button[form=checkout-form]').forEach(function (b) { b.addEventListener('click', function () { /* native form attr submit */ }); });
  }
})();
