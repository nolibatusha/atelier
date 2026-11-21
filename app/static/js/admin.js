/* Admin console behaviour (CSP-safe: no inline scripts). */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  document.addEventListener('click', function (e) {
    var d = e.target.closest('[data-dismiss]');
    if (d) { var box = d.closest('.flash'); if (box) box.remove(); return; }
    var t = e.target.closest('[data-sidebar-toggle]');
    if (t) { var o = $('#sidebar').classList.toggle('open'); document.body.classList.toggle('nav-open', o); return; }
    if (document.body.classList.contains('nav-open') && !e.target.closest('#sidebar')) { $('#sidebar').classList.remove('open'); document.body.classList.remove('nav-open'); }
    var rm = e.target.closest('[data-remove-row]');
    if (rm) { var row = rm.closest('tr'); if (row) row.remove(); return; }
    var add = e.target.closest('[data-add-variant]');
    if (add) {
      var tpl = $('#variant-template'), body = $('#variant-rows');
      if (tpl && body) { body.appendChild(tpl.content.cloneNode(true)); var last = body.lastElementChild; var i = last && $('input[name=v_size]', last); if (i) i.focus(); }
    }
  });

  document.addEventListener('submit', function (e) {
    var msg = e.target.getAttribute && e.target.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t.matches && t.matches('[data-autosubmit]') && t.form) t.form.requestSubmit ? t.form.requestSubmit() : t.form.submit();
    if (t.matches && t.matches('[data-image-preview]')) {
      var target = $('[data-preview-target]'); if (!target) return;
      target.textContent = '';
      Array.prototype.slice.call(t.files || []).slice(0, 12).forEach(function (f) {
        if (!/^image\//.test(f.type)) return;
        var im = document.createElement('img'); im.alt = ''; im.src = URL.createObjectURL(f);
        im.onload = function () { URL.revokeObjectURL(im.src); }; target.appendChild(im);
      });
    }
  });
})();
