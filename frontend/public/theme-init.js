// Runs synchronously before first paint to avoid a light/dark flash.
// Mirrors THEME_STORAGE_KEY and the resolution logic in src/stores/theme.ts.
;(function () {
  var preference = null
  try {
    preference = window.localStorage.getItem('altimate-fx.theme')
  } catch {
    // Storage can be unavailable (privacy mode, blocked cookies): fall back to system.
  }
  var dark
  if (preference === 'dark' || preference === 'light') {
    dark = preference === 'dark'
  } else if (typeof window.matchMedia === 'function') {
    dark = window.matchMedia('(prefers-color-scheme: dark)').matches
  } else {
    dark = true
  }
  var root = document.documentElement
  root.classList.toggle('dark', dark)
  root.style.colorScheme = dark ? 'dark' : 'light'
})()
