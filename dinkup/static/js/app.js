/* DinkUp — small helpers. No frameworks, works in Safari and Chrome. */
(function () {
  "use strict";

  function getCookie(name) {
    var m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return m ? decodeURIComponent(m.pop()) : "";
  }

  // Codes are not case sensitive — show them in caps as people type.
  document.querySelectorAll(".code-input").forEach(function (el) {
    el.addEventListener("input", function () {
      var pos = el.selectionStart;
      el.value = el.value.toUpperCase();
      try { el.setSelectionRange(pos, pos); } catch (e) {}
    });
  });

  // Show/hide score forms
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-toggle]");
    if (t) {
      var target = document.querySelector(t.getAttribute("data-toggle"));
      if (target) {
        target.hidden = !target.hidden;
        if (!target.hidden) { var i = target.querySelector("input[type=number]"); if (i) i.focus(); }
      }
    }
    // Quick-fill buttons: "We won (11)" / "They won (11)"
    var q = e.target.closest("[data-win],[data-lose]");
    if (q) {
      var form = q.closest("form");
      var us = form.querySelector("[name=score_a]");
      var them = form.querySelector("[name=score_b]");
      if (q.hasAttribute("data-win")) { us.value = q.getAttribute("data-win"); them.focus(); them.select(); }
      else { them.value = q.getAttribute("data-lose"); us.focus(); us.select(); }
    }
    // Home page feature boxes: jump to the code box with a helpful hint
    var f = e.target.closest("[data-code-hint]");
    if (f) {
      e.preventDefault();
      var box = document.querySelector(".code-form input");
      if (box) {
        box.placeholder = f.getAttribute("data-code-hint");
        box.scrollIntoView({ behavior: "smooth", block: "center" });
        box.focus();
        var card = document.getElementById("code");
        card.classList.remove("pulse"); void card.offsetWidth; card.classList.add("pulse");
      }
    }
    // Copy links
    var c = e.target.closest("[data-copy]");
    if (c) {
      var text = c.getAttribute("data-copy");
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(function () { c.textContent = "Copied!"; });
      } else { window.prompt("Copy this link:", text); }
    }
    // Week tabs on schedules
    var wk = e.target.closest("[data-weektabs] button");
    if (wk) {
      var week = wk.getAttribute("data-week");
      wk.parentNode.querySelectorAll("button").forEach(function (b) { b.classList.toggle("on", b === wk); });
      document.querySelectorAll(".round[data-week]").forEach(function (r) { r.hidden = r.getAttribute("data-week") !== week; });
    }
  });

  // Fade out toasts
  setTimeout(function () {
    document.querySelectorAll(".toast").forEach(function (t) { t.classList.add("fade"); });
  }, 5000);

  window.DinkUp = {
    // Live "how long will this take?" estimate on the league form.
    leagueForm: function () {
      var form = document.getElementById("leagueForm");
      var out = document.getElementById("estimate");
      if (!form || !out) return;
      function val(name) { var el = form.querySelector("[name=" + name + "]"); return el ? parseInt(el.value, 10) : NaN; }
      function checked(name) { var el = form.querySelector("[name=" + name + "]:checked"); return el ? el.value : ""; }
      function update() {
        var players = val("max_players"), courts = Math.min(val("num_courts") || 1, 8);
        var minutes = val("game_minutes") || 15, games = val("games_per_player");
        var division = checked("division"), mode = division === "SCR" ? "rotate" : checked("partner_mode");
        var partnerField = document.getElementById("partnerField");
        if (partnerField) partnerField.classList.toggle("dim", division === "SCR");
        if (!players || players < 4) { out.innerHTML = ""; return; }
        var rounds, sitting = 0, g;
        if (mode === "fixed") {
          var teams = Math.floor(players / 2);
          var circle = teams % 2 === 0 ? teams - 1 : teams;
          g = games ? Math.min(games, circle) : circle;
          rounds = g * Math.ceil(Math.floor(teams / 2) / courts);
          if (!games && teams % 2) g = teams - 1;
        } else {
          var perRound = Math.min(courts, Math.floor(players / 4));
          g = games || Math.max(1, Math.min(players - 1, 8));
          rounds = Math.ceil(players * g / (4 * perRound));
          sitting = players - perRound * 4;
        }
        var total = rounds * minutes, h = Math.floor(total / 60), m = total % 60;
        out.innerHTML = "<strong>Estimate:</strong> " + rounds + " rounds · " + g + " games each · about " +
          (h ? h + "h " : "") + m + "m per night" + (sitting ? " · " + sitting + " sit out each round" : "");
      }
      form.addEventListener("input", update);
      form.addEventListener("change", update);
      update();
    },

    // Coach Dink chat
    chat: function () {
      var form = document.getElementById("chatForm");
      var input = document.getElementById("chatInput");
      var log = document.getElementById("chatLog");
      var url = form.getAttribute("data-url");

      function add(text, who, source) {
        var div = document.createElement("div");
        div.className = "msg " + who;
        div.textContent = text;
        if (source === "ai") { var s = document.createElement("small"); s.textContent = "AI"; div.appendChild(s); }
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
        div.scrollIntoView({ block: "end", behavior: "smooth" });
        return div;
      }

      function send(text) {
        text = (text || "").trim();
        if (!text) return;
        add(text, "me");
        input.value = "";
        var typing = add("…", "bot typing");
        fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
          body: JSON.stringify({ message: text }),
          credentials: "same-origin"
        }).then(function (r) { return r.json(); })
          .then(function (data) { typing.remove(); add(data.reply || data.error || "Hmm, try again.", "bot", data.source); })
          .catch(function () { typing.remove(); add("I couldn't connect. Check your signal and try again.", "bot"); });
      }

      form.addEventListener("submit", function (e) { e.preventDefault(); send(input.value); });
      document.querySelectorAll("#suggestions button").forEach(function (b) {
        b.addEventListener("click", function () { send(b.textContent); });
      });
    }
  };
})();
