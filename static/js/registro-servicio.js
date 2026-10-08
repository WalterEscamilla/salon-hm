document.addEventListener('submit', async event => {
  const form = event.target;
  if (!form.matches('[data-registro-servicio]') || event.submitter?.value !== 'interpretar') return;
  event.preventDefault();
  if (form.getAttribute('aria-busy') === 'true') return;
  const datos = new FormData(form);
  datos.set('accion', 'interpretar');
  const controles = Array.from(form.elements).map(control => [control, control.disabled]);
  controles.forEach(([control]) => { control.disabled = true; });
  form.setAttribute('aria-busy', 'true');
  const status = form.querySelector('[data-registro-status]');
  status.hidden = false;
  status.textContent = 'Estoy completando el formulario…';
  try {
    const response = await fetch(window.location.href, {
      method: 'POST', body: datos, credentials: 'same-origin',
      headers: { 'HX-Request': 'true', 'HX-Target': 'registro-servicio' }
    });
    const acceso = response.headers.get('HX-Redirect');
    if (acceso) { window.location.assign(acceso); return; }
    if (!response.ok) throw new Error('respuesta');
    const documento = new DOMParser().parseFromString(await response.text(), 'text/html');
    const registro = documento.getElementById('registro-servicio');
    if (!registro) throw new Error('formulario');
    document.getElementById('registro-servicio').replaceWith(registro);
    if (registro.dataset.borrador) {
      const url = new URL(window.location.href);
      url.searchParams.set('borrador', registro.dataset.borrador);
      history.replaceState(null, '', url);
    }
    (registro.querySelector('[role="alert"]') || registro.querySelector('section:last-child'))?.scrollIntoView({behavior:'smooth', block:'start'});
  } catch {
    status.textContent = 'No se pudo completar el formulario. Conservamos lo que escribiste; puedes intentar de nuevo o llenarlo manualmente.';
  } finally {
    controles.forEach(([control, deshabilitado]) => { control.disabled = deshabilitado; });
    form.removeAttribute('aria-busy');
  }
});
