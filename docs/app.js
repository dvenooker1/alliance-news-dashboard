/* Alliance News Dashboard — front-end logic (vanilla JS, no build step).
   Loads data.json (or a dated archive file), renders the stock ticker and the
   priority-grouped news roundup, and wires up keyword + company filtering. */

(function () {
  "use strict";

  var GROUPS = [
    { key: "high", label: "High priority", desc: "Press releases & oncology" },
    { key: "medium", label: "Medium priority", desc: "Major business news" },
    { key: "low", label: "Lower priority", desc: "Other company news" },
  ];

  var state = {
    data: null,
    activeCompanies: new Set(),
    query: "",
    userExpanded: new Set(), // low group expansion override
  };

  var el = {
    status: document.getElementById("status"),
    stocksSection: document.getElementById("stocks-section"),
    stocksGrid: document.getElementById("stocks-grid"),
    benchmarks: document.getElementById("benchmarks"),
    newsSection: document.getElementById("news-section"),
    newsGroups: document.getElementById("news-groups"),
    noResults: document.getElementById("no-results"),
    search: document.getElementById("search"),
    companyFilter: document.getElementById("company-filter"),
    updatedTime: document.getElementById("updated-time"),
    engineBadge: document.getElementById("engine-badge"),
    footerEngine: document.getElementById("footer-engine"),
    datePicker: document.getElementById("date-picker"),
  };

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function relTime(iso) {
    if (!iso) return "";
    var then = new Date(iso).getTime();
    if (isNaN(then)) return "";
    var mins = Math.round((Date.now() - then) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + "m ago";
    var hrs = Math.round(mins / 60);
    if (hrs < 24) return hrs + "h ago";
    var days = Math.round(hrs / 24);
    if (days === 1) return "yesterday";
    if (days < 7) return days + "d ago";
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function fmtChange(pct) {
    if (pct == null) return { cls: "flat", text: "—" };
    var cls = pct > 0 ? "pos" : pct < 0 ? "neg" : "flat";
    var arrow = pct > 0 ? "▲" : pct < 0 ? "▼" : "■";
    var sign = pct > 0 ? "+" : "";
    return { cls: cls, text: arrow + " " + sign + pct.toFixed(2) + "%" };
  }

  // ---------- stocks ----------
  function renderStocks(stocks) {
    el.stocksGrid.innerHTML = "";
    stocks.forEach(function (s) {
      var a = document.createElement("a");
      a.href = s.link;
      a.target = "_blank";
      a.rel = "noopener";

      var note = s.ticker_note ? ' <span class="note">· ' + esc(s.ticker_note) + "</span>" : "";

      if (!s.ticker) {
        a.className = "stock-card untraded";
        a.innerHTML =
          '<span class="stock-status-tag">' + esc(statusLabel(s.status)) + "</span>" +
          '<div class="stock-name">' + esc(s.name) + "</div>" +
          '<div class="stock-price">' + esc(shortNote(s.note)) + "</div>";
      } else if (s.price == null) {
        a.className = "stock-card";
        a.innerHTML =
          '<div class="stock-name">' + esc(s.name) + "</div>" +
          '<div class="stock-ticker">' + esc(s.ticker) + note + "</div>" +
          '<div class="stock-price stock-na">price unavailable</div>';
      } else {
        var ch = fmtChange(s.change_pct);
        a.className = "stock-card";
        a.innerHTML =
          '<div class="stock-name">' + esc(s.name) + "</div>" +
          '<div class="stock-ticker">' + esc(s.ticker) + note + "</div>" +
          '<div class="stock-price">$' + s.price.toFixed(2) + "</div>" +
          '<div class="stock-change ' + ch.cls + '">' + ch.text + "</div>";
      }
      el.stocksGrid.appendChild(a);
    });
  }

  function renderBenchmarks(list) {
    el.benchmarks.innerHTML = "";
    (list || []).forEach(function (b) {
      var a = document.createElement("a");
      a.href = b.link;
      a.target = "_blank";
      a.rel = "noopener";
      a.className = "benchmark-card";

      var priceText;
      if (b.price == null) priceText = '<span class="stock-na">n/a</span>';
      else if (b.kind === "index")
        priceText = b.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      else priceText = "$" + b.price.toFixed(2);

      var ch = fmtChange(b.change_pct);
      a.innerHTML =
        '<div class="benchmark-head">' +
          '<span class="benchmark-name">' + esc(b.name) + "</span>" +
          '<span class="benchmark-note">' + esc(b.note || "") + "</span>" +
        "</div>" +
        '<div class="benchmark-figs">' +
          '<span class="benchmark-price">' + priceText + "</span>" +
          '<span class="stock-change ' + ch.cls + '">' + ch.text + "</span>" +
        "</div>";
      el.benchmarks.appendChild(a);
    });
  }

  function statusLabel(status) {
    return { private: "Private", subsidiary: "Subsidiary", acquired: "Acquired" }[status] || "—";
  }
  function shortNote(note) {
    if (!note) return "Not publicly traded";
    return note.split(" — ")[0].split(" - ")[0];
  }

  // ---------- company filter chips ----------
  function buildChips(data) {
    var present = {};
    GROUPS.forEach(function (g) {
      (data.news[g.key] || []).forEach(function (it) {
        (it.companies || []).forEach(function (c) { present[c] = true; });
      });
    });
    var names = Object.keys(present).sort();
    el.companyFilter.innerHTML = "";

    var all = document.createElement("button");
    all.className = "chip clear active";
    all.textContent = "All companies";
    all.onclick = function () {
      state.activeCompanies.clear();
      syncChips();
      renderNews();
    };
    el.companyFilter.appendChild(all);

    names.forEach(function (name) {
      var b = document.createElement("button");
      b.className = "chip";
      b.textContent = name;
      b.dataset.company = name;
      b.onclick = function () {
        if (state.activeCompanies.has(name)) state.activeCompanies.delete(name);
        else state.activeCompanies.add(name);
        syncChips();
        renderNews();
      };
      el.companyFilter.appendChild(b);
    });
  }

  function syncChips() {
    var any = state.activeCompanies.size > 0;
    el.companyFilter.querySelectorAll(".chip").forEach(function (chip) {
      if (chip.classList.contains("clear")) {
        chip.classList.toggle("active", !any);
      } else {
        chip.classList.toggle("active", state.activeCompanies.has(chip.dataset.company));
      }
    });
  }

  // ---------- news ----------
  function matches(item) {
    if (state.activeCompanies.size) {
      var hit = (item.companies || []).some(function (c) { return state.activeCompanies.has(c); });
      if (!hit) return false;
    }
    if (state.query) {
      var hay = (item.title + " " + (item.summary || "") + " " + item.source + " " +
        (item.companies || []).join(" ")).toLowerCase();
      if (hay.indexOf(state.query) === -1) return false;
    }
    return true;
  }

  function newsItemHTML(item) {
    var tags = "";
    if (item.is_oncology) tags += '<span class="tag onc">Oncology</span>';
    if (item.is_press_release) tags += '<span class="tag pr">Press release</span>';
    (item.companies || []).slice(0, 4).forEach(function (c) {
      tags += '<span class="tag company">' + esc(c) + "</span>";
    });

    var meta =
      '<span class="news-source">' + esc(item.source || "") + "</span>";
    var rt = relTime(item.published);
    if (rt) meta += '<span class="sep">·</span><span>' + esc(rt) + "</span>";

    var summary = item.summary
      ? '<p class="news-summary">' + esc(item.summary) + "</p>"
      : "";

    return (
      '<div class="news-title"><a href="' + esc(item.link) + '" target="_blank" rel="noopener">' +
      esc(item.title) + "</a></div>" +
      summary +
      '<div class="news-meta">' + meta + " " + tags + "</div>"
    );
  }

  function isCollapsed(key, filterActive) {
    if (key !== "low") return false;
    if (filterActive) return false; // never hide matches behind a collapsed group
    return !state.userExpanded.has("low");
  }

  function renderNews() {
    var data = state.data;
    var filterActive = state.query !== "" || state.activeCompanies.size > 0;
    el.newsGroups.innerHTML = "";
    var totalShown = 0;

    GROUPS.forEach(function (g) {
      var items = (data.news[g.key] || []).filter(matches);
      if (!items.length) return;
      totalShown += items.length;

      var group = document.createElement("section");
      group.className = "news-group group-" + g.key;

      var collapsed = isCollapsed(g.key, filterActive);
      var head = document.createElement("div");
      head.className = "group-head";
      head.innerHTML =
        '<span class="dot"></span>' +
        "<h3>" + esc(g.label) + "</h3>" +
        '<span class="group-count">' + items.length + "</span>" +
        '<span class="group-desc">' + esc(g.desc) + "</span>" +
        (g.key === "low" && !filterActive
          ? '<span class="group-toggle">' + (collapsed ? "▸ show" : "▾ hide") + "</span>"
          : "");
      if (g.key === "low" && !filterActive) {
        head.style.cursor = "pointer";
        head.onclick = function () {
          if (state.userExpanded.has("low")) state.userExpanded.delete("low");
          else state.userExpanded.add("low");
          renderNews();
        };
      } else {
        head.style.cursor = "default";
      }
      group.appendChild(head);

      if (!collapsed) {
        var ul = document.createElement("ul");
        ul.className = "news-list";
        items.forEach(function (item) {
          var li = document.createElement("li");
          li.className = "news-item";
          li.innerHTML = newsItemHTML(item);
          ul.appendChild(li);
        });
        group.appendChild(ul);
      }
      el.newsGroups.appendChild(group);
    });

    el.noResults.classList.toggle("hidden", totalShown > 0);
  }

  // ---------- header / meta ----------
  function renderMeta(data) {
    el.updatedTime.textContent = data.generated_at_et || data.date || "—";
    var isAI = data.classifier === "claude";
    el.engineBadge.textContent = isAI ? "AI-sorted" : "Keyword-sorted";
    el.engineBadge.classList.toggle("is-ai", isAI);
    el.engineBadge.title = isAI
      ? "News prioritized by Claude (" + (data.model || "AI") + ")"
      : "News prioritized by keyword rules";
    if (el.footerEngine) {
      el.footerEngine.textContent = isAI
        ? "by Claude (" + (data.model || "AI") + ")"
        : "by keyword rules";
    }
  }

  // ---------- data loading ----------
  function show(data) {
    state.data = data;
    state.userExpanded.clear();
    renderMeta(data);
    renderBenchmarks(data.benchmarks || []);
    renderStocks(data.stocks || []);
    buildChips(data);
    syncChips();
    renderNews();
    el.status.classList.add("hidden");
    el.stocksSection.classList.remove("hidden");
    el.newsSection.classList.remove("hidden");
  }

  function loadData(url) {
    el.status.classList.remove("hidden");
    el.status.textContent = "Loading…";
    el.stocksSection.classList.add("hidden");
    el.newsSection.classList.add("hidden");
    return fetch(url, { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(show)
      .catch(function (e) {
        el.status.classList.remove("hidden");
        el.status.innerHTML =
          "Couldn't load the roundup (" + esc(e.message) + ").<br>" +
          "If this is a brand-new deployment, the first daily build may not have run yet.";
      });
  }

  function initDatePicker() {
    fetch("archive/index.json", { cache: "no-cache" })
      .then(function (r) { return r.ok ? r.json() : { dates: [] }; })
      .then(function (idx) {
        var dates = (idx.dates || []);
        el.datePicker.innerHTML = "";
        if (!dates.length) { el.datePicker.style.display = "none"; return; }
        dates.forEach(function (d, i) {
          var opt = document.createElement("option");
          opt.value = i === 0 ? "" : "archive/" + d.date + ".json";
          var nice = new Date(d.date + "T12:00:00").toLocaleDateString(undefined,
            { month: "short", day: "numeric", year: "numeric" });
          opt.textContent = (i === 0 ? "Latest · " : "") + nice;
          el.datePicker.appendChild(opt);
        });
        el.datePicker.onchange = function () {
          loadData(this.value || "data.json");
        };
      })
      .catch(function () { el.datePicker.style.display = "none"; });
  }

  // ---------- events ----------
  el.search.addEventListener("input", function () {
    state.query = this.value.trim().toLowerCase();
    renderNews();
  });

  // ---------- go ----------
  initDatePicker();
  loadData("data.json");
})();
