/* Small progressive-enhancement script for api.html.
   Shares the theme and language preference keys with the SPA (web/i18n.js),
   so the choice carries over between the search site and this page. */

const THEME_KEY = "model-info-theme";
const LANG_KEY = "model-info-lang";

function detectLang() {
  const saved = localStorage.getItem(LANG_KEY);
  if (saved === "ja" || saved === "en") return saved;
  return (navigator.language || "en").toLowerCase().startsWith("ja") ? "ja" : "en";
}

function applyLang(lang) {
  document.documentElement.dataset.lang = lang;
  document.documentElement.lang = lang;
  localStorage.setItem(LANG_KEY, lang);
  const button = document.getElementById("lang-toggle");
  if (button) button.textContent = lang === "ja" ? "EN" : "JA";
}

function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || "light";
}

function applyTheme(theme, persist) {
  document.documentElement.setAttribute("data-theme", theme);
  if (persist) localStorage.setItem(THEME_KEY, theme);
  const button = document.getElementById("theme-toggle");
  if (button) {
    button.textContent = theme === "dark" ? "☀" : "☾";
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#11151b" : "#f7f8fa");
  }
}

function setup() {
  applyLang(detectLang());

  const savedTheme = localStorage.getItem(THEME_KEY);
  if (savedTheme) applyTheme(savedTheme, false);
  else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) applyTheme("dark", false);
  else applyTheme("light", false);

  document.getElementById("lang-toggle")?.addEventListener("click", () => {
    applyLang(document.documentElement.dataset.lang === "ja" ? "en" : "ja");
  });
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
  });

  for (const button of document.querySelectorAll(".code-copy")) {
    button.addEventListener("click", async () => {
      const code = button.closest(".code-wrap")?.querySelector("code");
      if (!code) return;
      try {
        await navigator.clipboard.writeText(code.textContent);
        button.classList.add("copied");
        const previous = button.innerHTML;
        button.textContent = document.documentElement.dataset.lang === "ja" ? "コピー済み" : "Copied";
        setTimeout(() => { button.innerHTML = previous; button.classList.remove("copied"); }, 1400);
      } catch (e) {}
    });
  }
}

setup();
