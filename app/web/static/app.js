/* ==========================================================================
   Dashboard behaviour. No framework, no CDN — the portal has to work on a
   Droplet with no outbound internet access.
   ========================================================================== */

(function () {
  "use strict";

  /* --- Theme toggle ------------------------------------------------------
     Light is the default. Dark is opt-in through the sidebar toggle and is
     remembered per browser; the operating system's dark preference is
     deliberately not followed, so everyone sees the same portal unless they
     ask for something else. */

  var STORAGE_KEY = "reportbot-theme";

  function currentTheme() {
    var stored = null;
    try { stored = localStorage.getItem(STORAGE_KEY); } catch (e) { /* private mode */ }
    return stored === "dark" ? "dark" : "light";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(STORAGE_KEY, theme); } catch (e) { /* private mode */ }
    document.querySelectorAll("[data-theme-label]").forEach(function (el) {
      el.textContent = theme === "dark" ? "Light" : "Dark";
    });
  }

  applyTheme(currentTheme());

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-theme-toggle]");
    if (!toggle) return;
    applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });

  /* --- Confirm destructive actions --------------------------------------
     Any form carrying data-confirm asks before it submits. */

  document.addEventListener("submit", function (event) {
    var message = event.target.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });

  /* --- Reveal a stored secret's input -----------------------------------
     Secret fields render with a masked placeholder. Clicking "Replace" clears
     it so a new value can be typed, and makes clear it is being changed. */

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-reveal-for]");
    if (!button) return;
    var input = document.getElementById(button.getAttribute("data-reveal-for"));
    if (!input) return;
    input.value = "";
    input.removeAttribute("readonly");
    input.type = "text";
    input.placeholder = "Paste the new value";
    input.focus();
    button.remove();
  });

  /* --- Dependent selects on the settings page ---------------------------
     Choosing a provider swaps in that provider's model suggestions and shows
     whether a key is needed, without a round trip. */

  document.querySelectorAll("[data-provider-select]").forEach(function (select) {
    var role = select.getAttribute("data-provider-select");
    var catalogue = window.PROVIDER_MODELS || {};

    function sync() {
      var provider = select.value;
      var list = document.getElementById(role + "-model-options");
      if (list) {
        var models = (catalogue[provider] || []);
        list.innerHTML = "";
        models.forEach(function (model) {
          var option = document.createElement("option");
          option.value = model;
          list.appendChild(option);
        });
      }
      document.querySelectorAll("[data-provider-note='" + role + "']").forEach(function (note) {
        note.hidden = note.getAttribute("data-provider") !== provider;
      });
    }

    select.addEventListener("change", sync);
    sync();
  });

  /* --- Role picker in the login form -------------------------------------
     The WhatsApp number field only applies to the user role. */

  document.querySelectorAll("[data-role-select]").forEach(function (select) {
    var target = document.getElementById(select.getAttribute("data-role-select"));
    if (!target) return;
    function sync() {
      var isUser = select.value === "user";
      target.hidden = !isUser;
      var input = target.querySelector("input");
      if (input) input.required = isUser;
    }
    select.addEventListener("change", sync);
    sync();
  });

  /* --- Keep the transcript pinned to the newest message ------------------ */

  var thread = document.querySelector("[data-thread]");
  if (thread) thread.scrollTop = thread.scrollHeight;
})();
