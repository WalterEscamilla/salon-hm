function actualizarFinanzasVisita() {
  const form = document.querySelector('[data-registro-servicio]');
  const salida = form?.querySelector('[data-resumen-importes]');
  if (!salida) return;
  const centavos = nombre => {
    const valor = form.elements.namedItem(nombre)?.value.trim();
    if (!valor || !/^\d{1,10}(\.\d{1,2})?$/.test(valor)) return null;
    const [pesos, fraccion = ''] = valor.split('.');
    return Number(pesos) * 100 + Number(fraccion.padEnd(2, '0'));
  };
  const [precio, materiales, otros] = ['precio_cobrado', 'costo_materiales', 'otros_gastos'].map(centavos);
  const dinero = valor => new Intl.NumberFormat('es-MX', {style: 'currency', currency: 'MXN'}).format(valor / 100);
  if (materiales === null || otros === null) {
    salida.textContent = 'Completa materiales y otros gastos para calcular el costo. Usa 0 si no hubo gasto; vacío significa desconocido.';
    return;
  }
  const total = materiales + otros;
  const pago = form.elements.namedItem('gastos_pagados_en_visita').checked;
  salida.textContent = `Costo de esta visita: ${dinero(total)}. ${precio === null ? 'Precio cobrado pendiente.' : 'Margen: ' + dinero(precio - total) + '.'} ${pago ? 'Se descontarán ' + dinero(total) + ' del saldo al guardar.' : 'Estos costos no se volverán a descontar del saldo.'}`;
}
document.addEventListener('DOMContentLoaded', actualizarFinanzasVisita);
document.addEventListener('input', event => {
  if (event.target.closest('[data-registro-servicio]')) actualizarFinanzasVisita();
});
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
    actualizarFinanzasVisita();
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
