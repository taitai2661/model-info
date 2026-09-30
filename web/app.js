import { getLang, setLang, t } from "./i18n.js";

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const k in attrs) {
    if (k === "class") node.className = attrs[k];
    else if (k === "data") {
      for (const dk in attrs[k]) node.dataset[dk] = attrs[k][dk];
    } else if (["checked", "selected", "disabled", "hidden", "open"].includes(k)) {
      node[k] = Boolean(attrs[k]);
    } else if (k.startsWith("on") && typeof attrs[k] === "function") {
      node.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
    } else if (attrs[k] !== null && attrs[k] !== undefined) {
      node.setAttribute(k, attrs[k]);
    }
  }
  for (const c of children) {
    if (c === null || c === undefined) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
};

const state = {
  models: [],
  providers: [],
  modelDetailCache: new Map(),
  providerDetailCache: new Map(),
  query: "",
  filterProvider: "all",
  filterStatuses: new Set(),
  filterModalities: new Set(),
  filterCapabilities: new Set(),
  filterOpenWeights: false,
  showFavorites: false,
  favorites: new Set(JSON.parse(localStorage.getItem("model-info-favorites") || "[]")),
  visibleLimit: 24,
  providerQuery: "",
  sortBy: "name",
  provSort: "models",
};

function fmtNum(v) {
  if (v === null || v === undefined) return t("detail.null");
  if (v >= 1048576) return (v / 1048576).toFixed(1) + "M";
  if (v >= 1024) return (v / 1024).toFixed(0) + "K";
  return String(v);
}

function fmtPrice(v) {
  if (v === null || v === undefined) return "—";
  return "$" + v.toFixed(v < 0.01 ? 6 : v < 1 ? 4 : 2);
}

function priceUnit(pricing) {
  if (!pricing) return t("detail.null");
  const currency = pricing?.currency || "USD";
  const unit = (pricing?.unit || "1M_tokens").replaceAll("_", " ");
  return `${currency} / ${unit}`;
}

function reasoningSummary(config) {
  if (!config || !Array.isArray(config.effort_levels)) {
    return t("reasoning.unknown");
  }
  const parts = [t("reasoning.level_count", {
    count: config.effort_levels.length,
    levels: config.effort_levels.join(" / "),
  })];
  if (config.default_effort) {
    parts.push(t("reasoning.default", { effort: config.default_effort }));
  }
  if (config.supports_none === true) parts.push(t("reasoning.none_supported"));
  else if (config.supports_none === false) parts.push(t("reasoning.none_unsupported"));
  if (Array.isArray(config.modes)) {
    parts.push(t("reasoning.modes", { modes: config.modes.join(" / ") }));
  }
  if (config.default_mode) parts.push(t("reasoning.default_mode", { mode: config.default_mode }));
  if (config.parameter) parts.push(`${t("reasoning.effort_parameter")}: ${config.parameter}`);
  if (config.mode_parameter) parts.push(`${t("reasoning.mode_parameter")}: ${config.mode_parameter}`);
  return parts.join(" · ");
}

function serviceTierSummary(config) {
  if (!config || !Array.isArray(config.options)) return t("reasoning.unknown");
  return `${config.options.join(" / ")} · ${t("reasoning.mode_parameter")}: ${config.parameter || "service_tier"}`;
}

function sharedReasoningConfig(model, providers) {
  if (model.reasoning) return model.reasoning;
  if (!providers.length || providers.some((entry) => !entry.reasoning)) return null;
  const first = JSON.stringify(providers[0].reasoning);
  return providers.every((entry) => JSON.stringify(entry.reasoning) === first)
    ? providers[0].reasoning
    : null;
}

function escape(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`HTTP ${res.status} ${path}`);
  return res.json();
}

async function loadAll() {
  const root = ".";
  const [models, providers] = await Promise.all([
    fetchJSON(`${root}/v1/models.json`),
    fetchJSON(`${root}/v1/providers.json`),
  ]);
  state.models = models;
  state.providers = providers;
  state.providerMap = new Map(providers.map((p) => [p.id, p]));
  state.modelMap = new Map(models.map((m) => [m.model_id, m]));
}

function getProvider(id) {
  return state.providerMap.get(id);
}

async function getModelDetail(id) {
  if (state.modelDetailCache.has(id)) return state.modelDetailCache.get(id);
  const root = ".";
  const detail = await fetchJSON(`${root}/v1/models/${id}.json`);
  state.modelDetailCache.set(id, detail);
  return detail;
}

async function getProviderModels(id) {
  const cacheKey = `prov-${id}`;
  if (state.providerDetailCache.has(cacheKey)) return state.providerDetailCache.get(cacheKey);
  const root = ".";
  const list = await fetchJSON(`${root}/v1/providers/${id}/models.json`);
  state.providerDetailCache.set(cacheKey, list);
  return list;
}

function matchesFilters(m) {
  if (state.query) {
    const q = state.query.toLowerCase();
    const hay = [
      m.model_id, m.name, m.display_name, m.family, m.model_provider,
      m.description, state.providerMap.get(m.model_provider)?.name,
    ].filter(Boolean).join(" ").toLowerCase();
    if (!hay.includes(q)) return false;
  }
  if (state.filterProvider !== "all" && m.model_provider !== state.filterProvider) return false;
  if (state.filterStatuses.size > 0 && !state.filterStatuses.has(m.status)) return false;
  if (state.filterModalities.size > 0) {
    const inputs = (m.modalities && m.modalities.input) || [];
    for (const mod of state.filterModalities) {
      if (!inputs.includes(mod)) return false;
    }
  }
  if (state.filterCapabilities.size > 0) {
    const caps = m.capabilities || {};
    for (const cap of state.filterCapabilities) {
      if (caps[cap] !== true) return false;
    }
  }
  if (state.filterOpenWeights) {
    if (!m.availability || m.availability.open_weights !== true) return false;
  }
  if (state.showFavorites && !state.favorites.has(m.model_id)) return false;
  return true;
}

function syncSearchUrl() {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.filterProvider !== "all") params.set("provider", state.filterProvider);
  if (state.filterStatuses.size) params.set("status", [...state.filterStatuses].join(","));
  if (state.filterModalities.size) params.set("mod", [...state.filterModalities].join(","));
  if (state.filterCapabilities.size) params.set("cap", [...state.filterCapabilities].join(","));
  if (state.filterOpenWeights) params.set("open", "1");
  if (state.sortBy !== "name") params.set("sort", state.sortBy);
  const suffix = params.toString();
  const hash = `#/${suffix ? `?${suffix}` : ""}`;
  if ((window.location.hash || "#/").startsWith("#/")) {
    history.replaceState(null, "", `${location.pathname}${location.search}${hash}`);
  }
}

function restoreSearchUrl() {
  const hash = window.location.hash || "#/";
  if (!hash.startsWith("#/?")) return;
  const params = new URLSearchParams(hash.slice(3));
  state.query = params.get("q") || "";
  const provider = params.get("provider");
  state.filterProvider = provider && state.providerMap.has(provider) ? provider : "all";
  const allowedStatuses = new Set(["active", "preview", "experimental", "deprecated", "retired", "unknown"]);
  const allowedModalities = new Set(["text", "image", "audio", "video", "file"]);
  const allowedCapabilities = new Set(["tool_use", "vision", "reasoning", "function_calling", "structured_output", "json_mode", "streaming"]);
  state.filterStatuses = new Set((params.get("status") || "").split(",").filter((value) => allowedStatuses.has(value)));
  state.filterModalities = new Set((params.get("mod") || "").split(",").filter((value) => allowedModalities.has(value)));
  state.filterCapabilities = new Set((params.get("cap") || "").split(",").filter((value) => allowedCapabilities.has(value)));
  state.filterOpenWeights = params.get("open") === "1";
  const sorts = new Set(["name", "updated", "context", "input_price", "output_price"]);
  const sortBy = params.get("sort");
  state.sortBy = sorts.has(sortBy) ? sortBy : "name";
}

function sortModels(models) {
  const sortBy = state.sortBy;
  const sorted = [...models];
  const getPrice = (m, key) => {
    const p = m.pricing;
    return p && typeof p[key] === "number" ? p[key] : Infinity;
  };
  sorted.sort((a, b) => {
    const compareNullable = (av, bv, direction = 1) => {
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av < bv ? -1 : av > bv ? 1 : 0) * direction;
    };
    switch (sortBy) {
      case "name": return a.name.localeCompare(b.name);
      case "updated": return compareNullable(a.updated_at, b.updated_at, -1);
      case "context": return compareNullable(a.context?.window, b.context?.window, -1);
      case "input_price": return compareNullable(getPrice(a, "input"), getPrice(b, "input"));
      case "output_price": return compareNullable(getPrice(a, "output"), getPrice(b, "output"));
      default: return 0;
    }
  });
  return sorted;
}

const PROVIDER_SORTS = [
  ["models", "sort.models"],
  ["name", "sort.name"],
];

function sortProviders(providers) {
  const sorted = [...providers];
  const byName = (a, b) => a.name.localeCompare(b.name);
  if (state.provSort === "name") {
    sorted.sort(byName);
    return sorted;
  }
  const countOf = (p) => {
    const n = countProviderModels(p.id);
    return typeof n === "number" ? n : -1;
  };
  sorted.sort((a, b) => countOf(b) - countOf(a) || byName(a, b));
  return sorted;
}

function render() {
  const hash = window.location.hash || "#/";
  const main = $("#view");
  main.innerHTML = "";

  if (hash.startsWith("#/models/")) {
    const id = decodeURIComponent(hash.slice("#/models/".length));
    renderModelDetail(main, id);
  } else if (hash.startsWith("#/providers/")) {
    const id = decodeURIComponent(hash.slice("#/providers/".length));
    renderProviderDetail(main, id);
  } else if (hash === "#/providers") {
    renderProviderList(main);
  } else {
    renderHome(main);
  }

  const navModels = $('nav a[href="#/"]');
  const navProviders = $('nav a[href="#/providers"]');
  const route = hash.split("?")[0];
  navModels.classList.toggle("active", route === "#/" || route.startsWith("#/models/"));
  navProviders.classList.toggle("active", hash.startsWith("#/providers"));
}

function renderHome(container) {
  const providers = [...new Set(state.models.map((m) => m.model_provider))].sort();
  const statuses = ["active", "preview", "experimental", "deprecated", "retired", "unknown"];
  const modalities = ["text", "image", "audio", "video", "file"];
  const capabilities = ["tool_use", "vision", "reasoning", "function_calling", "structured_output", "json_mode", "streaming"];

  const searchInput = el("input", {
    class: "search-input",
    type: "search",
    placeholder: t("search.placeholder"),
    value: state.query,
    "aria-label": t("search.placeholder"),
    oninput: (e) => { state.query = e.target.value; state.visibleLimit = 24; renderResults(); },
  });
  const clearSearch = el("button", { class: "search-clear", type: "button", title: t("search.clear"), "aria-label": t("search.clear"), onclick: () => {
    state.query = "";
    searchInput.value = "";
    searchInput.focus();
    renderResults();
  } }, "×");

  const providerSelect = el("select", {
    class: "filter-select",
    onchange: (e) => { state.filterProvider = e.target.value; state.visibleLimit = 24; renderResults(); },
  },
    el("option", { value: "all" }, `${t("filter.all")} (${providers.length})`),
    ...providers.map((pid) => {
      const p = getProvider(pid);
      const count = state.models.filter((m) => m.model_provider === pid).length;
      return el("option", { value: pid, selected: state.filterProvider === pid },
        `${p?.name || pid} (${count})`);
    }),
  );

  const sortSelect = el("select", {
    class: "sort-select",
    onchange: (e) => { state.sortBy = e.target.value; renderResults(); },
  },
    ...[
      ["name", "sort.name"], ["updated", "sort.updated"], ["context", "sort.context"],
      ["input_price", "sort.input_price"], ["output_price", "sort.output_price"],
    ].map(([v, label]) => el("option", { value: v, selected: state.sortBy === v }, t(label))),
  );

  const statusChips = statuses.map((s) =>
    el("span", {
      class: "chip" + (state.filterStatuses.has(s) ? " active" : ""),
      role: "button",
      tabindex: "0",
      "aria-pressed": state.filterStatuses.has(s),
      onclick: () => {
        state.filterStatuses.has(s) ? state.filterStatuses.delete(s) : state.filterStatuses.add(s);
        render();
      },
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.currentTarget.click(); } },
    }, t(`status.${s}`))
  );

  const modChips = modalities.map((m) =>
    el("span", {
      class: "chip" + (state.filterModalities.has(m) ? " active" : ""),
      role: "button",
      tabindex: "0",
      "aria-pressed": state.filterModalities.has(m),
      onclick: () => {
        state.filterModalities.has(m) ? state.filterModalities.delete(m) : state.filterModalities.add(m);
        render();
      },
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.currentTarget.click(); } },
    }, t(`modality.${m}`))
  );

  const capChips = capabilities.map((c) =>
    el("span", {
      class: "chip" + (state.filterCapabilities.has(c) ? " active" : ""),
      role: "button",
      tabindex: "0",
      "aria-pressed": state.filterCapabilities.has(c),
      onclick: () => {
        state.filterCapabilities.has(c) ? state.filterCapabilities.delete(c) : state.filterCapabilities.add(c);
        render();
      },
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.currentTarget.click(); } },
    }, t(`cap.${c}`))
  );

  const owToggle = el("label", { class: "toggle-row" },
    el("input", {
      type: "checkbox",
      checked: state.filterOpenWeights,
      onchange: (e) => { state.filterOpenWeights = e.target.checked; state.visibleLimit = 24; renderResults(); },
    }),
    document.createTextNode(t("filter.open_weights")),
  );

  const resultsDiv = el("div", { id: "model-results" });
  const filterDetails = el("details", { class: "filter-panel" },
    el("summary", {}, el("span", { class: "filter-summary-icon" }, "⌄"), t("filter.more"), el("span", { class: "filter-summary-count" })),
    el("div", { class: "filter-panel-content" },
      el("div", { class: "filter-block" }, el("h3", {}, t("filter.status")), el("div", { class: "chips" }, ...statusChips)),
      el("div", { class: "filter-block" }, el("h3", {}, t("filter.modalities")), el("div", { class: "chips" }, ...modChips)),
      el("div", { class: "filter-block" }, el("h3", {}, t("filter.capabilities")), el("div", { class: "chips" }, ...capChips)),
      el("div", { class: "filter-block filter-block-inline" }, owToggle),
    ),
  );
  const favoritesButton = el("button", { class: "favorites-toggle" + (state.showFavorites ? " active" : ""), type: "button", "aria-pressed": state.showFavorites, onclick: () => {
    state.showFavorites = !state.showFavorites;
    state.visibleLimit = 24;
    render();
  } }, `♡ ${t("filter.favorites")}`);
  const searchBox = el("div", { class: "search-box" }, searchInput, clearSearch, el("kbd", { class: "search-shortcut" }, "/"));
  container.append(
    el("section", { class: "search-hero" },
      el("div", { class: "eyebrow" }, t("home.eyebrow")),
      el("h1", {}, t("home.title")),
      el("p", { class: "hero-copy" }, t("home.subtitle")),
      searchBox,
      el("div", { class: "hero-stats" },
        el("span", {}, el("strong", {}, String(state.models.length)), ` ${t("home.models")}`),
        el("span", {}, el("strong", {}, String(state.providers.length)), ` ${t("home.providers")}`),
        el("span", {}, t("home.data_note")),
      ),
    ),
    el("section", { class: "search-workspace" },
      el("div", { class: "toolbar" },
        el("label", { class: "select-wrap" }, el("span", {}, t("filter.provider")), providerSelect),
        el("label", { class: "select-wrap sort-wrap" }, el("span", {}, t("sort.label")), sortSelect),
        favoritesButton,
      ),
      filterDetails,
      el("div", { class: "active-filters", id: "active-filters" }),
    ),
    resultsDiv,
  );

  function renderResults() {
    const host = resultsDiv;
    syncSearchUrl();
    const matched = state.models.filter(matchesFilters);
    const sorted = sortModels(matched);
    host.innerHTML = "";
    host.append(el("div", { class: "results-header" },
      el("div", { class: "result-count" }, el("strong", {}, String(sorted.length)), ` ${t("result.of")} ${state.models.length} ${t("result.models")}`),
      el("span", { class: "results-hint" }, t("result.hint")),
    ));
    updateActiveFilters();

    if (sorted.length === 0) {
      host.append(el("div", { class: "empty-state" },
        el("div", { class: "empty-icon" }, "⌕"),
        el("h2", {}, t("result.empty")),
        el("p", {}, t("result.empty_hint")),
        el("button", { class: "button-primary", onclick: resetFilters }, t("filter.reset")),
      ));
      return;
    }

    const grid = el("div", { class: "grid" });
    for (const m of sorted.slice(0, state.visibleLimit)) {
      grid.append(renderModelCard(m));
    }
    host.append(grid);
    if (sorted.length > state.visibleLimit) {
      host.append(el("div", { class: "load-more-wrap" },
        el("button", { class: "button-secondary", onclick: () => { state.visibleLimit += 24; renderResults(); } },
          t("result.load_more", { count: Math.min(24, sorted.length - state.visibleLimit) })),
      ));
    }
  }

  function updateActiveFilters() {
    const active = $("#active-filters");
    if (!active) return;
    active.innerHTML = "";
    const count = state.filterStatuses.size + state.filterModalities.size + state.filterCapabilities.size + Number(state.filterProvider !== "all") + Number(state.filterOpenWeights) + Number(state.showFavorites);
    filterDetails.querySelector(".filter-summary-count").textContent = count ? `${count}` : "";
    const tokens = [];
    if (state.filterProvider !== "all") tokens.push(getProvider(state.filterProvider)?.name || state.filterProvider);
    for (const s of state.filterStatuses) tokens.push(t(`status.${s}`));
    for (const m of state.filterModalities) tokens.push(t(`modality.${m}`));
    for (const c of state.filterCapabilities) tokens.push(t(`cap.${c}`));
    if (state.filterOpenWeights) tokens.push(t("filter.open_weights"));
    if (state.showFavorites) tokens.push(t("filter.favorites"));
    if (tokens.length) {
      active.append(el("span", { class: "active-filter-label" }, t("filter.active")));
      for (const token of tokens) active.append(el("span", { class: "active-filter-chip" }, token));
      active.append(el("button", { class: "text-button", onclick: resetFilters }, t("filter.reset")));
    }
  }

  providerSelect.value = state.filterProvider;
  sortSelect.value = state.sortBy;
  renderResults();
}

function resetFilters() {
  state.query = "";
  state.filterProvider = "all";
  state.filterStatuses.clear();
  state.filterModalities.clear();
  state.filterCapabilities.clear();
  state.filterOpenWeights = false;
  state.showFavorites = false;
  state.visibleLimit = 24;
  render();
}

function renderModelCard(m) {
  const prov = getProvider(m.model_provider);
  const badges = el("div", { class: "badges" },
    el("span", { class: "badge badge-status", data: { s: m.status } }, t(`status.${m.status}` || "status.unknown")),
    el("span", { class: "badge badge-provider" }, prov?.name || m.model_provider),
  );

  if (m.modalities?.input) {
    for (const mod of m.modalities.input) {
      badges.append(el("span", { class: "badge badge-modality" }, t(`modality.${mod}`)));
    }
  }

  const meta = el("div", { class: "card-meta" });
  if (m.context && typeof m.context.window === "number") {
    meta.append(el("span", {}, `${t("card.context")}: `, el("strong", {}, fmtNum(m.context.window))));
  }
  if (m.pricing && typeof m.pricing.input === "number") {
    meta.append(el("span", {}, `${t("card.input")}: `, el("strong", {}, fmtPrice(m.pricing.input))));
  }
  if (m.pricing && typeof m.pricing.output === "number") {
    meta.append(el("span", {}, `${t("card.output")}: `, el("strong", {}, fmtPrice(m.pricing.output))));
  }
  if (m.pricing && (typeof m.pricing.input === "number" || typeof m.pricing.output === "number")) {
    meta.append(el("span", { class: "card-price-unit" }, priceUnit(m.pricing)));
  }
  if (m.availability?.open_weights === true) {
    meta.append(el("span", {}, `● ${t("card.open_weights")}`));
  }

  const desc = m.description ? el("div", { class: "card-desc" }, m.description) : null;

  const favorite = state.favorites.has(m.model_id);
  const favoriteButton = el("button", {
    class: "favorite-button" + (favorite ? " active" : ""),
    type: "button",
    title: favorite ? t("favorite.remove") : t("favorite.add"),
    "aria-label": favorite ? t("favorite.remove") : t("favorite.add"),
    "aria-pressed": favorite,
    onclick: (e) => {
      e.stopPropagation();
      if (state.favorites.has(m.model_id)) state.favorites.delete(m.model_id);
      else state.favorites.add(m.model_id);
      localStorage.setItem("model-info-favorites", JSON.stringify([...state.favorites]));
      render();
    },
  }, favorite ? "♥" : "♡");
  return el("article", { class: "card", tabindex: "0", role: "link", onclick: () => navigate(`#/models/${m.model_id}`), onkeydown: (e) => {
      if ((e.key === "Enter" || e.key === " ") && !e.target.closest("button")) { e.preventDefault(); navigate(`#/models/${m.model_id}`); }
    } },
    el("div", { class: "card-header" },
      el("div", {}, el("div", { class: "card-name" }, m.display_name || m.name), el("div", { class: "card-id" }, m.model_id)),
      favoriteButton,
    ),
    badges,
    meta,
    desc,
  );
}

async function renderModelDetail(container, id) {
  container.append(el("div", { class: "loading" }, t("loading")));
  let detail;
  try {
    detail = await getModelDetail(id);
  } catch (e) {
    if (!window.location.hash.startsWith("#/models/") || decodeURIComponent(window.location.hash.slice("#/models/".length)) !== id) return;
    container.innerHTML = "";
    container.append(
      el("a", { class: "back-link", href: "#/" }, `← ${t("breadcrumb.home")}`),
      el("div", { class: "error-msg" }, `${t("error.not_found")}: ${escape(id)}`),
    );
    return;
  }

  if (!window.location.hash.startsWith("#/models/") || decodeURIComponent(window.location.hash.slice("#/models/".length)) !== id) return;
  const { model: m, providers: plist } = detail;
  container.innerHTML = "";

  container.append(el("a", { class: "back-link", href: "#/" }, `← ${t("breadcrumb.home")}`));

  const prov = getProvider(m.model_provider);
  container.append(
    el("h1", { class: "detail-title" }, m.display_name || m.name),
    el("div", { class: "detail-subtitle" }, `${m.model_id} · ${prov?.name || m.model_provider}`),
    el("div", { class: "detail-badges" },
      el("span", { class: "badge badge-status", data: { s: m.status } }, t(`status.${m.status}`)),
      m.family ? el("span", { class: "badge badge-provider" }, m.family) : null,
      m.version ? el("span", { class: "badge badge-provider" }, `${t("detail.version")}: ${m.version}`) : null,
      m.release_date ? el("span", { class: "detail-date" }, `${t("detail.release_date")}: ${m.release_date}`) : null,
    ),
    m.description ? el("p", { class: "detail-description" }, m.description) : null,
  );

  container.append(buildSpecsSection(m, plist));
  container.append(buildPricingSection(m));
  container.append(buildProvidersSection(plist, m));

  if (m.sources && m.sources.length > 0) {
    container.append(buildSourcesSection(m.sources));
  }

  container.append(
    el("div", { class: "detail-section" },
      el("a", { href: `./v1/models/${encodeURIComponent(m.model_id)}.json`, target: "_blank", rel: "noopener" }, t("detail.json_link")),
    ),
  );
}

function buildSpecsSection(m, providers = []) {
  const sec = el("div", { class: "detail-section" });
  sec.append(el("h2", {}, t("detail.specs")));

  const grid = el("div", { class: "spec-grid" });

  const addSpec = (label, value) => {
    grid.append(el("div", { class: "spec-item" },
      el("div", { class: "spec-label" }, label),
      el("div", { class: "spec-value" }, value),
    ));
  };

  addSpec(t("detail.context"), m.context ? fmtNum(m.context.window) : "—");
  if (m.context && typeof m.context.max_input_tokens === "number") {
    addSpec(t("detail.max_input"), fmtNum(m.context.max_input_tokens));
  }
  if (m.context && typeof m.context.max_output_tokens === "number") {
    addSpec(t("detail.max_output"), fmtNum(m.context.max_output_tokens));
  }
  if (m.context && typeof m.context.reasoning_tokens === "number") {
    addSpec(t("detail.reasoning"), fmtNum(m.context.reasoning_tokens));
  }
  const reasoning = sharedReasoningConfig(m, providers);
  if (reasoning || (m.family === "GPT-6" && m.capabilities?.reasoning === true)) {
    addSpec(t("detail.reasoning_effort"), reasoningSummary(reasoning));
  }
  if (m.service_tier) {
    addSpec(t("detail.service_tier"), serviceTierSummary(m.service_tier));
  }
  if (m.context?.tokenizer) addSpec(t("detail.tokenizer"), m.context.tokenizer);

  if (m.modalities) {
    const input = m.modalities.input.map((mod) => t(`modality.${mod}`)).join(" / ");
    const output = m.modalities.output.map((mod) => t(`modality.${mod}`)).join(" / ");
    addSpec(t("detail.modalities"), `${input} → ${output}`);
  }

  const capList = el("div", { class: "cap-list" });
  const capKeys = ["tool_use", "vision", "reasoning", "function_calling", "structured_output", "json_mode", "streaming"];
  for (const k of capKeys) {
    const v = m.capabilities?.[k];
    const cls = v === true ? "cap-yes" : v === false ? "cap-no" : "cap-unknown";
    const label = v === true ? "✓" : v === false ? "✗" : "?";
    capList.append(el("span", { class: `cap-item ${cls}` }, `${label} ${t(`cap.${k}`)}`));
  }
  const capWrap = el("div", { class: "spec-item" });
  capWrap.append(el("div", { class: "spec-label" }, t("detail.capabilities")), capList);
  grid.append(capWrap);

  if (m.availability) {
    const availKeys = ["api", "cloud", "open_weights", "self_hostable"];
    const parts = [];
    for (const k of availKeys) {
      if (m.availability[k] === true || m.availability[k] === false) {
        parts.push(`${t(`availability.${k}`)}: ${t(m.availability[k] ? "common.yes" : "common.no")}`);
      }
    }
    addSpec(t("detail.availability"), parts.length > 0 ? parts.join(" · ") : t("detail.null"));
  }

  if (m.runtime) {
    const rt = Object.entries(m.runtime).filter(([, v]) => v === true).map(([k]) => k);
    if (rt.length > 0) addSpec(t("detail.runtime"), rt.join(", "));
  }

  sec.append(grid);
  return sec;
}

function buildPricingSection(m) {
  if (!m.pricing) return el("span");
  const sec = el("div", { class: "detail-section" });
  sec.append(el("h2", {}, t("detail.pricing")));
  const grid = el("div", { class: "spec-grid" });
  const p = m.pricing;
  const addSpec = (label, value) => {
    grid.append(el("div", { class: "spec-item" },
      el("div", { class: "spec-label" }, label),
      el("div", { class: "spec-value" }, value),
    ));
  };
  addSpec(t("pricing.unit"), priceUnit(p));
  if (typeof p.input === "number") addSpec(t("card.input"), fmtPrice(p.input));
  if (typeof p.output === "number") addSpec(t("card.output"), fmtPrice(p.output));
  if (typeof p.cached_input === "number") addSpec(t("card.cached_input"), fmtPrice(p.cached_input));
  if (typeof p.cached_write === "number") addSpec(t("card.cached_write"), fmtPrice(p.cached_write));
  sec.append(grid);
  return sec;
}

function buildProvidersSection(plist, model) {
  const sec = el("section", { class: "detail-section" });
  sec.append(el("h2", {}, `${t("detail.providers_title")} (${plist.length})`));

  if (plist.length === 0) {
    sec.append(el("p", { class: "empty-inline" }, t("detail.no_providers")));
    return sec;
  }

  for (const entry of plist) {
    const prov = entry.provider || getProvider(entry.provider_id);
    const priceIsOverridden = Object.prototype.hasOwnProperty.call(entry, "pricing");
    const pricing = priceIsOverridden ? entry.pricing : model.pricing;
    const header = el("div", { class: "connection-heading" },
      el("div", {},
        el("a", { class: "connection-provider", href: `#/providers/${entry.provider_id}` }, prov?.name || entry.provider_id),
        el("span", { class: "connection-api-style" }, prov?.api?.api_style || t("detail.unknown_api")),
      ),
      entry.status ? el("span", { class: "badge badge-status", data: { s: entry.status } }, t(`status.${entry.status}`)) : null,
    );
    const idRow = el("div", { class: "connection-model-id" },
      el("span", { class: "spec-label" }, t("detail.provider_model_id")),
      el("code", { class: "mono" }, entry.model_id),
    );
    const copyBtn = el("button", {
      class: "btn-copy",
      type: "button",
      title: t("detail.copy"),
      "aria-label": t("detail.copy_model_id"),
      onclick: (e) => { e.stopPropagation(); copyText(entry.model_id); },
    }, "⧉");
    idRow.append(copyBtn);

    const detailsGrid = el("div", { class: "connection-details-grid" });
    const addInfo = (label, value, mono = false) => {
      detailsGrid.append(el("div", { class: "spec-item" },
        el("div", { class: "spec-label" }, label),
        el("div", { class: `spec-value${mono ? " mono" : ""}` }, value || "—"),
      ));
    };
    addInfo(t("detail.base_url"), prov?.api?.base_url, true);
    addInfo(t("detail.auth"), prov?.api?.authentication?.type);
    if (entry.reasoning) {
      addInfo(t("detail.reasoning_effort"), reasoningSummary(entry.reasoning));
    }
    if (entry.api_variant?.reasoning_mode) {
      addInfo(t("detail.reasoning_mode"), entry.api_variant.reasoning_mode);
    }
    if (entry.api_variant?.reasoning_effort) {
      addInfo(t("detail.reasoning_effort"), entry.api_variant.reasoning_effort);
    }
    if (entry.api_variant?.service_tier) {
      addInfo(t("detail.service_tier"), entry.api_variant.service_tier);
    }
    if (entry.api_variant?.performance_variant) {
      addInfo(t("detail.performance_variant"), entry.api_variant.performance_variant);
    }

    const priceGrid = el("div", { class: "connection-prices" });
    const priceValue = (key) => typeof pricing?.[key] === "number" ? fmtPrice(pricing[key]) : t("detail.null");
    priceGrid.append(
      el("div", {}, el("span", { class: "spec-label" }, t("card.input")), el("strong", {}, priceValue("input"))),
      el("div", {}, el("span", { class: "spec-label" }, t("card.output")), el("strong", {}, priceValue("output"))),
      el("div", { class: "connection-price-unit" }, priceUnit(pricing)),
    );
    if (!priceIsOverridden && pricing) priceGrid.append(el("div", { class: "price-inherited" }, t("detail.inherit")));

    const moreContent = el("div", { class: "connection-more-content" });

    // What this provider actually offers, when the provider states it and it
    // differs from the model document (which is the default it inherits).
    const contextOverride = entry.context || null;
    if (contextOverride) {
      const parts = [];
      if (typeof contextOverride.window === "number") {
        parts.push(`${t("detail.context")}: ${fmtNum(contextOverride.window)}`);
      }
      if (typeof contextOverride.max_output_tokens === "number") {
        parts.push(`${t("detail.max_output")}: ${fmtNum(contextOverride.max_output_tokens)}`);
      }
      if (parts.length > 0) {
        moreContent.append(el("p", { class: "connection-note" },
          `${t("detail.at_provider")} ${parts.join(" · ")}`));
      }
    }

    const entryCaps = [
      ["capabilities", t("detail.capabilities"), ["tool_use", "vision", "reasoning", "structured_output"]],
      ["api_capabilities", t("detail.api_capabilities"), ["streaming", "tool_calling", "structured_output", "json_mode", "prompt_caching", "batch"]],
    ];
    for (const [field, heading, keys] of entryCaps) {
      const stated = entry[field];
      if (!stated) continue;
      const items = [];
      for (const k of keys) {
        const v = stated[k];
        if (v !== true && v !== false) continue;
        const cls = v ? "cap-yes" : "cap-no";
        const label = v ? "✓" : "✗";
        const name = field === "capabilities" ? t(`cap.${k}`) : t(`api.${k}`);
        items.push(el("span", { class: `cap-item ${cls}` }, `${label} ${name}`));
      }
      if (items.length === 0) continue;
      const wrap = el("div", { class: "spec-item" });
      wrap.append(el("div", { class: "spec-label" }, `${t("detail.at_provider")} ${heading}`),
        el("div", { class: "cap-list" }, ...items));
      moreContent.append(wrap);
    }

    if (prov?.api?.endpoints) {
      const endpoints = el("div", { class: "endpoint-list" });
      for (const [name, path] of Object.entries(prov.api.endpoints)) {
        endpoints.append(el("div", {}, el("span", {}, name), el("code", {}, path)));
      }
      moreContent.append(el("div", { class: "spec-label" }, t("detail.endpoints")), endpoints);
    }
    if (prov?.api?.authentication?.notes) {
      moreContent.append(el("p", { class: "connection-note" }, prov.api.authentication.notes));
    }
    if (entry.notes) moreContent.append(el("p", { class: "connection-note" }, entry.notes));
    if (entry.sources?.length) {
      const sourceLinks = el("div", { class: "connection-sources" });
      for (const source of entry.sources) {
        sourceLinks.append(el("a", { href: source.url, target: "_blank", rel: "noopener" }, source.title || source.url));
      }
      moreContent.append(el("div", { class: "spec-label" }, t("detail.sources")), sourceLinks);
    }
    const more = el("details", { class: "connection-more" },
      el("summary", {}, t("detail.connection_details")),
      moreContent,
    );

    sec.append(el("article", { class: "provider-connection" }, header, idRow, detailsGrid, priceGrid, more));
  }
  return sec;
}

function buildSourcesSection(sources) {
  const sec = el("div", { class: "detail-section" });
  sec.append(el("h2", {}, t("detail.sources")));
  const list = el("ul", { class: "source-list" });
  for (const s of sources) {
    const title = s.title || s.url;
    list.append(el("li", {},
      el("span", { class: "source-type", data: { type: s.type } }, t(`common.${s.type}`)),
      el("a", { href: s.url, target: "_blank", rel: "noopener" }, title),
      document.createTextNode(` · ${s.retrieved_at}`),
      s.notes ? el("div", { style: "font-size:0.78rem;color:var(--text-muted);margin-top:0.2rem" }, s.notes) : null,
    ));
  }
  sec.append(list);
  return sec;
}

function renderProviderCard(p) {
  const count = countProviderModels(p.id);

  const typeBadges = el("div", { class: "badges" });
  if (p.types) {
    for (const tp of p.types) {
      typeBadges.append(el("span", { class: "badge badge-modality" }, t(`common.${tp}`)));
    }
  }

  return el("article", { class: "prov-card", tabindex: "0", role: "link", data: { search: `${p.name} ${p.id} ${p.description || ""} ${(p.types || []).join(" ")}`.toLowerCase() }, onclick: () => navigate(`#/providers/${p.id}`), onkeydown: (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navigate(`#/providers/${p.id}`); }
    } },
    el("div", { class: "prov-card-name" }, p.name),
    typeBadges,
    el("div", { class: "card-meta" }, el("strong", {}, count !== null ? `${count}` : "…"), document.createTextNode(` ${t("prov.model_count_label")}`)),
    p.description ? el("div", { class: "prov-card-desc" }, p.description) : null,
  );
}

function renderProviderList(container) {
  const types = ["model_provider", "api_provider", "aggregator", "gateway", "platform"];
  let activeType = state.provTypeFilter || "all";

  const typeChips = el("div", { class: "filter-group", style: "margin-bottom:1rem" },
    el("button", {
      class: "chip" + (activeType === "all" ? " active" : ""),
      type: "button",
      "aria-pressed": activeType === "all",
      onclick: () => { state.provTypeFilter = "all"; render(container); },
    }, t("prov.filter_all")),
    ...types.map((tp) =>
      el("button", {
        class: "chip" + (activeType === tp ? " active" : ""),
        type: "button",
        "aria-pressed": activeType === tp,
        onclick: () => { state.provTypeFilter = tp; render(container); },
      }, t(`common.${tp}`)),
    ),
  );

  const matchesFilters = (p) => {
    const matchesType = activeType === "all" || (p.types && p.types.includes(activeType));
    const term = (state.providerQuery || "").trim().toLowerCase();
    const matchesQuery = !term || [p.name, p.id, p.description, ...(p.types || [])].filter(Boolean).join(" ").toLowerCase().includes(term);
    return matchesType && matchesQuery;
  };

  const emptyState = () => el("div", { class: "empty-state provider-search-empty" },
    el("h2", {}, t("result.empty")),
    el("p", {}, t("result.empty_hint")),
  );

  const gridHost = el("div", { id: "provider-grid" });

  const paintGrid = () => {
    const filtered = state.providers.filter(matchesFilters);
    const grid = el("div", { class: "grid" });
    for (const p of sortProviders(filtered)) {
      grid.append(renderProviderCard(p));
    }
    if (filtered.length === 0) grid.append(emptyState());
    gridHost.replaceChildren(grid);
  };

  const sortSelect = el("select", {
    class: "sort-select",
    "aria-label": t("sort.label"),
    onchange: (e) => { state.provSort = e.target.value; paintGrid(); },
  },
    ...PROVIDER_SORTS.map(([v, label]) => el("option", { value: v, selected: state.provSort === v }, t(label))),
  );
  sortSelect.value = state.provSort;

  const providerSearch = el("input", { class: "search-input provider-search-input", type: "search", placeholder: t("prov.search"), value: state.providerQuery, "aria-label": t("prov.search"), oninput: (e) => {
    state.providerQuery = e.target.value;
    const term = state.providerQuery.trim().toLowerCase();
    for (const card of gridHost.querySelectorAll(".prov-card")) {
      card.hidden = Boolean(term) && !card.dataset.search.includes(term);
    }
    const empty = gridHost.querySelector(".provider-search-empty");
    const visible = [...gridHost.querySelectorAll(".prov-card")].some((card) => !card.hidden);
    if (!visible && !empty) gridHost.append(emptyState());
    if (visible && empty) empty.remove();
  } });
  container.append(
    el("h1", { style: "margin-bottom:1rem" }, t("nav.providers")),
    el("p", { class: "hero-copy provider-intro" }, t("prov.subtitle")),
    el("div", { class: "provider-controls" },
      el("div", { class: "provider-search-wrap" }, providerSearch),
      el("label", { class: "select-wrap sort-wrap" }, el("span", {}, t("sort.label")), sortSelect),
    ),
    typeChips,
    gridHost,
  );
  paintGrid();
  loadProviderCounts();
}

const providerCountCache = new Map();

async function loadProviderCounts() {
  if (state.providerCountsLoaded) return;
  state.providerCountsLoaded = true;
  const root = ".";
  const results = await Promise.allSettled(
    state.providers.map(async (p) => {
      const data = await fetchJSON(`${root}/v1/providers/${p.id}.json`);
      providerCountCache.set(p.id, data.model_ids ? data.model_ids.length : 0);
    }),
  );
  if (window.location.hash === "#/providers") render();
}

function countProviderModels(providerId) {
  return providerCountCache.has(providerId) ? providerCountCache.get(providerId) : null;
}

async function renderProviderDetail(container, id) {
  container.append(el("div", { class: "loading" }, t("loading")));
  const prov = getProvider(id);
  if (!prov) {
    container.innerHTML = "";
    container.append(
      el("a", { class: "back-link", href: "#/providers" }, `← ${t("nav.providers")}`),
      el("div", { class: "error-msg" }, `${t("error.not_found")}: ${escape(id)}`),
    );
    return;
  }

  let modelList;
  try {
    modelList = await getProviderModels(id);
  } catch (e) {
    modelList = [];
  }

  if (!window.location.hash.startsWith("#/providers/") || decodeURIComponent(window.location.hash.slice("#/providers/".length)) !== id) return;
  container.innerHTML = "";
  container.append(el("a", { class: "back-link", href: "#/providers" }, `← ${t("nav.providers")}`));

  container.append(
    el("h1", { class: "detail-title" }, prov.name),
    el("div", { class: "detail-subtitle" }, prov.id),
    el("div", { class: "detail-badges" },
      ...(prov.types || []).map((type) => el("span", { class: "badge badge-provider" }, t(`common.${type}`))),
      el("span", { class: "badge badge-status", data: { s: prov.status || "unknown" } }, t(`status.${prov.status || "unknown"}`)),
    ),
    prov.description ? el("p", { class: "detail-description" }, prov.description) : null,
  );

  const sec = el("div", { class: "detail-section" });
  sec.append(el("h2", {}, t("prov.api_info")));

  const grid = el("div", { class: "spec-grid" });
  if (prov.website) grid.append(el("div", { class: "spec-item" },
    el("div", { class: "spec-label" }, t("prov.website")),
    el("div", { class: "spec-value" }, el("a", { href: prov.website, target: "_blank", rel: "noopener" }, prov.website)),
  ));
  if (prov.documentation_url) grid.append(el("div", { class: "spec-item" },
    el("div", { class: "spec-label" }, t("prov.docs")),
    el("div", { class: "spec-value" }, el("a", { href: prov.documentation_url, target: "_blank", rel: "noopener" }, prov.documentation_url)),
  ));
  if (prov.api) {
    const a = prov.api;
    grid.append(el("div", { class: "spec-item" },
      el("div", { class: "spec-label" }, t("detail.base_url")),
      el("div", { class: "spec-value mono" }, a.base_url),
    ));
    grid.append(el("div", { class: "spec-item" },
      el("div", { class: "spec-label" }, t("detail.api_style")),
      el("div", { class: "spec-value" }, a.api_style || "—"),
    ));
    if (a.authentication) {
      grid.append(el("div", { class: "spec-item" },
        el("div", { class: "spec-label" }, t("prov.auth")),
        el("div", { class: "spec-value" }, `${a.authentication.type || "—"}${a.authentication.header ? ` · ${a.authentication.header}` : ""}`),
      ));
      if (a.authentication.notes) {
        const authNotes = el("div", { class: "spec-item", style: "grid-column: 1 / -1" });
        authNotes.append(el("div", { class: "spec-label" }, t("detail.notes")), el("div", { class: "spec-value" }, a.authentication.notes));
        grid.append(authNotes);
      }
    }
    if (a.endpoints) {
      const epList = el("div");
      for (const [name, path] of Object.entries(a.endpoints)) {
        epList.append(el("div", { class: "mono" }, `${name}: ${path}`));
      }
      const epItem = el("div", { class: "spec-item", style: "grid-column: 1 / -1" });
      epItem.append(el("div", { class: "spec-label" }, t("prov.endpoints")), epList);
      grid.append(epItem);
    }
  }
  sec.append(grid);
  container.append(sec);

  if (prov.api_capabilities) {
    const capSec = el("div", { class: "detail-section" });
    capSec.append(el("h2", {}, t("detail.capabilities")));
    const capList = el("div", { class: "cap-list" });
    for (const [k, v] of Object.entries(prov.api_capabilities)) {
      const cls = v === true ? "cap-yes" : v === false ? "cap-no" : "cap-unknown";
      const label = v === true ? "✓" : v === false ? "✗" : "?";
      capList.append(el("span", { class: `cap-item ${cls}` }, `${label} ${t(`api.${k}`) || k}`));
    }
    capSec.append(capList);
    container.append(capSec);
  }

  const modelsSec = el("div", { class: "detail-section" });
  modelsSec.append(el("h2", {}, `${t("prov.models_title")} (${modelList.length})`));

  if (modelList.length === 0) {
    modelsSec.append(el("p", { class: "error-msg" }, "—"));
  } else {
    const table = el("table");
    table.append(el("thead", {},
      el("tr", {},
        ...["Model", t("detail.provider_model_id"), t("detail.status")].map((h) => el("th", {}, h)),
      ),
    ));
    const tbody = el("tbody");
    for (const item of modelList) {
      const model = item.model || state.modelMap.get(item.relationship?.model_id);
      if (!model) continue;
      const rel = item.relationship;
      tbody.append(el("tr", { class: "provider-row", onclick: () => navigate(`#/models/${model.model_id}`) },
        el("td", {}, model.display_name || model.name),
        el("td", { class: "mono" }, rel?.model_id || model.model_id),
        el("td", {}, rel?.status ? t(`status.${rel.status}`) : t(`status.${model.status}`)),
      ));
    }
    table.append(tbody);
    modelsSec.append(table);
  }
  container.append(modelsSec);
}

function navigate(hash) {
  if (window.location.hash === hash) {
    render();
  } else {
    window.location.hash = hash;
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    const toast = el("div", {
      style: "position:fixed;bottom:1rem;left:50%;transform:translateX(-50%);background:var(--text);color:var(--bg);padding:0.5rem 1rem;border-radius:8px;font-size:0.82rem;z-index:999;transition:opacity 0.3s",
    }, t("detail.copied"));
    document.body.append(toast);
    setTimeout(() => { toast.style.opacity = "0"; setTimeout(() => toast.remove(), 300); }, 1500);
  } catch (e) {}
}

function buildHeader() {
  const langBtn = el("button", { class: "btn-icon", title: t("lang.label"), onclick: () => {
    setLang(getLang() === "ja" ? "en" : "ja");
  }}, getLang() === "ja" ? "EN" : "JA");

  const themeBtn = el("button", { class: "btn-icon", id: "theme-toggle", type: "button", title: t(getTheme() === "dark" ? "theme.light" : "theme.dark"), "aria-label": t(getTheme() === "dark" ? "theme.light" : "theme.dark"), onclick: toggleTheme }, getTheme() === "dark" ? "☀" : "☾");

  const header = el("header", {},
    el("div", { class: "header-inner" },
      el("a", { class: "logo", href: "#/" }, t("app.title")),
      el("nav", {},
        el("a", { href: "#/" }, t("nav.models")),
        el("a", { href: "#/providers" }, t("nav.providers")),
      ),
      el("div", { class: "spacer" }),
      el("div", { class: "header-controls" }, themeBtn, langBtn),
    ),
  );
  return header;
}

function getTheme() {
  return document.documentElement.getAttribute("data-theme") || "light";
}

function toggleTheme() {
  const current = getTheme();
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("model-info-theme", next);
  const button = $("#theme-toggle");
  if (button) {
    button.textContent = next === "dark" ? "☀" : "☾";
    button.title = t(next === "dark" ? "theme.light" : "theme.dark");
    button.setAttribute("aria-label", button.title);
  }
}

function buildFooter() {
  return el("footer", { id: "site-footer" },
    el("div", {}, el("a", { id: "footer-repo", href: "https://github.com/daichikato/model-info", target: "_blank", rel: "noopener" }, t("footer.repo"))),
    el("div", {}, el("span", { id: "footer-data" }, t("footer.data")), " · ", el("span", { id: "footer-license" }, `${t("footer.license")}: MIT`)),
  );
}

function updateStaticText() {
  const logo = document.querySelector(".logo");
  if (logo) logo.textContent = t("app.title");
  const navModels = $('nav a[href="#/"]');
  const navProviders = $('nav a[href="#/providers"]');
  if (navModels) navModels.textContent = t("nav.models");
  if (navProviders) navProviders.textContent = t("nav.providers");
  const langBtn = document.querySelector(".header-controls .btn-icon:last-child");
  if (langBtn) langBtn.textContent = getLang() === "ja" ? "EN" : "JA";
  const footerRepo = $("#footer-repo");
  const footerData = $("#footer-data");
  const footerLicense = $("#footer-license");
  if (footerRepo) footerRepo.textContent = t("footer.repo");
  if (footerData) footerData.textContent = t("footer.data");
  if (footerLicense) footerLicense.textContent = `${t("footer.license")}: MIT`;
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register(new URL("../sw.js", import.meta.url)).catch(() => {});
  });
}

async function init() {
  const root = document.getElementById("root");

  registerServiceWorker();

  const savedTheme = localStorage.getItem("model-info-theme");
  if (savedTheme) {
    document.documentElement.setAttribute("data-theme", savedTheme);
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    document.documentElement.setAttribute("data-theme", "dark");
  }
  document.documentElement.lang = getLang() === "ja" ? "ja" : "en";

  root.append(buildHeader());

  const loadingEl = el("main", { id: "view" }, el("div", { class: "loading" }, t("loading")));
  root.append(loadingEl);
  root.append(buildFooter());

  try {
    await loadAll();
    restoreSearchUrl();
    window.addEventListener("hashchange", render);
    window.addEventListener("langchange", () => { updateStaticText(); render(); });
    window.addEventListener("keydown", (event) => {
      if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName) && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault();
        $(".search-input")?.focus();
      }
      if (event.key === "Escape" && document.activeElement?.classList.contains("search-input")) {
        const input = document.activeElement;
        if (input.value) {
          state.query = "";
          input.value = "";
          $("#model-results")?.replaceChildren();
          render();
        }
      }
    });
    render();
  } catch (e) {
    loadingEl.innerHTML = "";
    loadingEl.append(el("div", { class: "error-msg" }, `${t("error.load")}: ${escape(e.message)}`));
  }
}

init();
