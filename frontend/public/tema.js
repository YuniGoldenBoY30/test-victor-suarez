// Aplica el tema guardado antes de pintar para evitar un parpadeo.
// Archivo externo para que la CSP pueda prohibir scripts en línea.
try {
  var t = localStorage.getItem('tema')
  if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t
} catch (e) {}
