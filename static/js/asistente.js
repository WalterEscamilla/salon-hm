document.querySelectorAll('[data-chat-form]').forEach(form => {
  form.addEventListener('submit', () => {
    form.querySelector('button[type="submit"]').disabled = true;
    form.querySelector('[data-chat-status]').textContent = 'El asistente está preparando la respuesta…';
    form.setAttribute('aria-busy', 'true');
  });
});
