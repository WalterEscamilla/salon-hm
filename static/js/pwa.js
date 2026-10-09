(() => {
  const workerUrl = document.currentScript?.dataset.serviceWorker;
  const card = document.getElementById('pwa-install');
  const button = document.getElementById('pwa-install-button');
  const status = document.getElementById('pwa-install-status');
  const connectionNotice = document.getElementById('pwa-connection');
  const display = window.matchMedia('(display-mode: standalone)');
  let installPrompt = null;

  function hideInstall() {
    installPrompt = null;
    if (card) card.hidden = true;
  }
  window.addEventListener('beforeinstallprompt', event => {
    if (!card || !button || display.matches) return;
    event.preventDefault();
    installPrompt = event;
    button.disabled = false;
    if (status) status.textContent = '';
    card.hidden = false;
  });
  window.addEventListener('appinstalled', hideInstall);
  display.addEventListener('change', event => {if (event.matches) hideInstall();});
  button?.addEventListener('click', async () => {
    if (!installPrompt) return;
    const prompt = installPrompt;
    installPrompt = null;
    button.disabled = true;
    try {
      await prompt.prompt();
      await prompt.userChoice;
      card.hidden = true;
    } catch {
      if (status) status.textContent = 'Para instalarla, abre el menú de Chrome y elige «Instalar app» o «Añadir a pantalla de inicio».';
    }
  });

  function updateConnection() {
    if (connectionNotice) connectionNotice.hidden = navigator.onLine;
  }
  updateConnection();
  window.addEventListener('online', updateConnection);
  window.addEventListener('offline', updateConnection);
  document.addEventListener('submit', event => {
    if (navigator.onLine || !(event.target instanceof HTMLFormElement) || event.target.method.toLowerCase() !== 'post') return;
    event.preventDefault();
    event.stopImmediatePropagation();
    updateConnection();
    connectionNotice?.scrollIntoView({block: 'center'});
  }, true);

  if ('serviceWorker' in navigator && window.isSecureContext && workerUrl) {
    const register = () => {
      navigator.serviceWorker.register(workerUrl, {scope: '/', updateViaCache: 'none'}).catch(() => {
        // La aplicación en línea sigue funcionando si no se registra el worker.
        console.warn('No se pudo preparar la pantalla sin conexión de Salón HM.');
      });
    };
    if (document.readyState === 'complete') register();
    else window.addEventListener('load', register, {once: true});
  }
})();
