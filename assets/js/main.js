/* ============================================================================
   Mango Pediatrics — interactions
   Sticky nav · mobile menu · scroll reveal · counters · scrollspy ·
   copy-to-clipboard · contact form · back-to-top
   ========================================================================== */
(function () {
  "use strict";
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, c) { return (c || document).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); };

  /* ---------- Sticky header state ---------- */
  var header = $("#site-header");
  var onScroll = function () {
    if (header) header.classList.toggle("scrolled", window.scrollY > 12);
    toggleToTop();
  };
  window.addEventListener("scroll", onScroll, { passive: true });

  /* ---------- Mobile menu ---------- */
  var menu = $("#mobile-menu");
  var openBtn = $("#nav-toggle");
  var closeBtn = $("#nav-close");
  var lastFocused = null;

  function openMenu() {
    if (!menu) return;
    lastFocused = document.activeElement;
    menu.hidden = false;
    // force reflow so the transition runs
    void menu.offsetWidth;
    menu.classList.add("open");
    if (openBtn) openBtn.setAttribute("aria-expanded", "true");
    document.body.style.overflow = "hidden";
    var first = $(".mobile-menu__list a", menu);
    if (first) first.focus();
    document.addEventListener("keydown", onKeydown);
  }
  function closeMenu() {
    if (!menu || menu.hidden) return;
    menu.classList.remove("open");
    if (openBtn) openBtn.setAttribute("aria-expanded", "false");
    document.body.style.overflow = "";
    document.removeEventListener("keydown", onKeydown);
    var done = function () { menu.hidden = true; menu.removeEventListener("transitionend", done); };
    if (reduceMotion) { menu.hidden = true; } else { menu.addEventListener("transitionend", done); }
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }
  function onKeydown(e) {
    if (e.key === "Escape") { closeMenu(); return; }
    if (e.key === "Tab" && menu && !menu.hidden) {
      var f = $$("a, button", menu).filter(function (el) { return el.offsetParent !== null; });
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }
  if (openBtn) openBtn.addEventListener("click", openMenu);
  if (closeBtn) closeBtn.addEventListener("click", closeMenu);
  if (menu) {
    menu.addEventListener("click", function (e) { if (e.target === menu) closeMenu(); });
    $$(".mobile-menu__list a, .mobile-menu__cta a", menu).forEach(function (a) {
      a.addEventListener("click", closeMenu);
    });
  }

  /* ---------- Scroll reveal + grid stagger ---------- */
  var revealEls = $$("[data-reveal]");
  // add stagger classes to grouped children
  $$(".card-grid, .why__grid, .tst-meta, .hero__badges").forEach(function (grid) {
    $$("[data-reveal]", grid).forEach(function (el, i) {
      el.classList.add("d" + Math.min(i % 6 + 1, 5));
    });
  });
  if ("IntersectionObserver" in window && !reduceMotion) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add("in"); });
  }

  /* ---------- Count-up stats ---------- */
  function animateCount(el) {
    var target = parseInt(el.getAttribute("data-count"), 10);
    if (isNaN(target)) return;
    var plain = el.getAttribute("data-plain") === "true"; // no thousands formatting
    var suffix = el.getAttribute("data-suffix") || "";
    if (reduceMotion) { el.textContent = (plain ? String(target) : target.toLocaleString()) + suffix; return; }
    var start = null, dur = 1400;
    function step(ts) {
      if (!start) start = ts;
      var p = Math.min((ts - start) / dur, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      var val = Math.round(eased * target);
      el.textContent = (plain ? String(val) : val.toLocaleString()) + suffix;
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  var counters = $$("[data-count]");
  if ("IntersectionObserver" in window) {
    var co = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { animateCount(en.target); co.unobserve(en.target); }
      });
    }, { threshold: 0.6 });
    counters.forEach(function (el) { co.observe(el); });
  }

  /* ---------- Scroll spy ---------- */
  var navLinks = $$("#nav-list a");
  var sections = navLinks.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); }).filter(Boolean);
  if ("IntersectionObserver" in window && sections.length) {
    var so = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          var id = en.target.id;
          navLinks.forEach(function (a) { a.classList.toggle("is-active", a.getAttribute("href") === "#" + id); });
        }
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    sections.forEach(function (s) { so.observe(s); });
  }

  /* ---------- Toast ---------- */
  var toast = $("#toast"), toastTimer;
  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.hidden = false;
    void toast.offsetWidth;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.classList.remove("show");
      setTimeout(function () { toast.hidden = true; }, 320);
    }, 2400);
  }

  /* ---------- Copy to clipboard ---------- */
  $$("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var text = btn.getAttribute("data-copy");
      var done = function () { showToast("Address copied to clipboard"); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(fallback);
      } else { fallback(); }
      function fallback() {
        var ta = document.createElement("textarea");
        ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); done(); } catch (e) {}
        document.body.removeChild(ta);
      }
    });
  });

  /* ---------- Contact form ---------- */
  var form = $("#contact-form");
  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var name = $("#cf-name"), email = $("#cf-email");
      var ok = true;
      [name, email].forEach(function (input) {
        if (!input.value.trim() || (input.type === "email" && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(input.value))) {
          ok = false; input.setAttribute("aria-invalid", "true");
          input.style.borderColor = "var(--coral-600)";
        } else { input.removeAttribute("aria-invalid"); input.style.borderColor = ""; }
      });
      if (!ok) { (name.value.trim() ? email : name).focus(); return; }
      var success = $("#form-success");
      var btn = $("button[type=submit]", form);
      if (btn) { btn.disabled = true; btn.textContent = "Sending…"; }
      setTimeout(function () {
        form.querySelectorAll(".field, .field-row, .contact-form__fine").forEach(function (el) { el.style.display = "none"; });
        if (btn) btn.style.display = "none";
        if (success) { success.hidden = false; success.focus && success.focus(); }
      }, 650);
    });
  }

  /* ---------- Back to top ---------- */
  var toTop = $("#to-top");
  function toggleToTop() { if (toTop) toTop.hidden = window.scrollY < 640; }
  if (toTop) {
    toTop.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
    });
  }

  /* ---------- Sticky mobile CTA visibility ---------- */
  var mcta = $("#mobile-cta");
  if (mcta && "IntersectionObserver" in window) {
    var zones = [$(".hero"), $("#contact"), $(".cta-band"), $("#site-footer")].filter(Boolean);
    var mo2 = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { e.target._v = e.isIntersecting; });
      var hide = zones.some(function (z) { return z._v; });
      mcta.classList.toggle("hide", hide);
    }, { threshold: 0 });
    zones.forEach(function (z) { mo2.observe(z); });
    mcta.classList.add("hide");
  }

  /* ---------- Year ---------- */
  var yearEl = $("#year");
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());

  /* init */
  onScroll();
})();
