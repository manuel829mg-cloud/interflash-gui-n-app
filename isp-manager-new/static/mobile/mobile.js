(() => {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
  let prompt;
  const buttons = document.querySelectorAll('.mobile-install');
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); prompt = event;
    buttons.forEach(b => b.hidden = false);
  });
  buttons.forEach(b => b.addEventListener('click', async () => {
    if (!prompt) return;
    await prompt.prompt(); prompt = null;
    buttons.forEach(x => x.hidden = true);
  }));
  window.addEventListener('appinstalled', () => buttons.forEach(b => b.hidden = true));
  const side = document.querySelector('.app > .side');
  if (side) {
    const button = document.createElement('button');
    button.className = 'if-menu-toggle'; button.textContent = '☰ Menú';
    button.setAttribute('aria-expanded', 'false');
    button.addEventListener('click', () => {
      const open = document.body.classList.toggle('if-menu-open');
      button.setAttribute('aria-expanded', String(open));
      button.textContent = open ? '✕ Cerrar' : '☰ Menú';
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') {document.body.classList.remove('if-menu-open');button.setAttribute('aria-expanded','false');button.textContent='☰ Menú';} });
    document.body.append(button);
  }
})();
