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
  // Use the platform's header menu as the only mobile navigation toggle.
  const style = document.createElement('style');
  style.textContent = '@media(max-width:700px){body.menu-open .app>.side{display:block!important}.if-menu-toggle{display:none!important}}';
  document.head.append(style);
})();
