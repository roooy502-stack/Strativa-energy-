/* Strativa Energy shared behaviour: mobile menu, reveal-on-scroll, contact form confirmation. */
(function () {
  var menu = document.querySelector('.menu');
  var links = document.querySelector('.navlinks');
  if (menu && links) {
    var sync = function () {
      var open = links.classList.contains('open');
      menu.setAttribute('aria-expanded', open);
      menu.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    };
    menu.addEventListener('click', function () { links.classList.toggle('open'); sync(); });
    links.addEventListener('click', function (e) {
      if (e.target.closest('a')) { links.classList.remove('open'); sync(); }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && links.classList.contains('open')) { links.classList.remove('open'); sync(); menu.focus(); }
    });
  }

  var items = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('visible'); io.unobserve(e.target); } });
    }, { threshold: 0.08 });
    items.forEach(function (el) { io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add('visible'); });
  }

  var ok = document.querySelector('.contact-success');
  if (ok && /[?&]sent=1/.test(location.search)) {
    ok.classList.add('show');
    ok.setAttribute('tabindex', '-1');
    ok.focus();
  }
})();
