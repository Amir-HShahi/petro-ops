// Applies the saved theme before the page paints, so a light choice does not flash dark.
// "system" removes the attribute and lets the browser's colour scheme decide.
"use strict";

(function () {
  const STORAGE_KEY = "pipeline-theme";
  const root = document.documentElement;

  // Storage can be blocked, for example in a private window; the page still works then.
  function savedTheme() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved === "light" || saved === "dark" ? saved : "system";
    } catch {
      return "system";
    }
  }

  function apply(theme) {
    if (theme === "system") root.removeAttribute("data-theme");
    else root.dataset.theme = theme;
  }

  apply(savedTheme());

  document.addEventListener("DOMContentLoaded", () => {
    const buttons = document.querySelectorAll("[data-theme-choice]");
    const mark = (theme) => {
      for (const button of buttons) {
        button.setAttribute("aria-pressed", String(button.dataset.themeChoice === theme));
      }
    };
    mark(savedTheme());
    for (const button of buttons) {
      button.addEventListener("click", () => {
        const theme = button.dataset.themeChoice;
        apply(theme);
        mark(theme);
        try {
          localStorage.setItem(STORAGE_KEY, theme);
        } catch {
          // The choice still applies until the page is reloaded.
        }
      });
    }
  });
})();
