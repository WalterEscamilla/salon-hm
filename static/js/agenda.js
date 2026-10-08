(() => {
  let ultimaVuelta = 0;
  function actualizarAlVolver() {
    if (document.hidden || Date.now() - ultimaVuelta < 10000) return;
    if (!document.querySelector('#agenda-eventos[hx-get], #citas-hoy[hx-get]')) return;
    ultimaVuelta = Date.now();
    document.body.dispatchEvent(new CustomEvent('actualizarAgenda'));
  }
  document.addEventListener('visibilitychange', actualizarAlVolver);
  window.addEventListener('focus', actualizarAlVolver);
  document.body.addEventListener('htmx:afterRequest', event => {
    if (!['agenda-eventos', 'citas-hoy'].includes(event.detail.target?.id)) return;
    const aviso = document.querySelector(`#${event.detail.target.id} [data-error-actualizacion]`);
    if (aviso) aviso.hidden = !event.detail.failed;
  });
})();
