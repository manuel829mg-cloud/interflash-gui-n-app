"""Local, accessible menu illustrations; no fonts or external requests."""

ART = {
 'dashboard': ('#60a5fa', '<rect x="4" y="4" width="6" height="7" rx="1.5"/><rect x="14" y="4" width="6" height="4" rx="1.5"/><rect x="4" y="15" width="6" height="5" rx="1.5"/><rect x="14" y="12" width="6" height="8" rx="1.5"/>'),
 'clientes': ('#38bdf8', '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2Z"/><path d="M16 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 5" fill="none"/>'),
 'finanzas': ('#4ade80', '<rect x="3" y="5" width="18" height="15" rx="3"/><path d="M3 9h18M16 12h5v5h-5a2.5 2.5 0 0 1 0-5Z" fill="none"/><circle cx="17" cy="14.5" r=".6"/>'),
 'admin': ('#c084fc', '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6" fill="none"/>'),
 'soporte': ('#fb923c', '<path d="M4 14v-3a8 8 0 0 1 16 0v3M20 16v2a3 3 0 0 1-3 3h-4" fill="none"/><rect x="3" y="11" width="4" height="7" rx="2"/><rect x="17" y="11" width="4" height="7" rx="2"/><path d="M11 21h3" fill="none"/>'),
 'routers': ('#22d3ee', '<rect x="3" y="12" width="18" height="8" rx="2"/><path d="M6 12V5m12 7V5M9 6a5 5 0 0 1 6 0m-4 3a2 2 0 0 1 2 0" fill="none"/><circle cx="7" cy="16" r=".6"/><path d="M11 16h2m3 0h1" fill="none"/>'),
 'wan_lines': ('#60a5fa', '<rect x="8" y="3" width="8" height="6" rx="1.5"/><path d="M12 9v5M5 17v-3h14v3" fill="none"/><rect x="2" y="17" width="6" height="4" rx="1"/><rect x="16" y="17" width="6" height="4" rx="1"/>'),
 'plans': ('#fbbf24', '<path d="M3 16a9 9 0 0 1 18 0v4H3Z"/><path d="m12 16 5-6M6 13l1 1m5-7v2m6 5 1-1" fill="none"/><circle cx="12" cy="16" r="1.5"/>'),
 'zones_page': ('#2dd4bf', '<path d="m3 7 5-2 8 3 5-2v14l-5 2-8-3-5 2Z"/><path d="M8 12v7m8-5v8" fill="none"/><path d="M16 6c0 3-4 6-4 6S8 9 8 6a4 4 0 0 1 8 0Z"/><circle cx="12" cy="6" r="1" fill="currentColor"/>'),
 'whatsapp_inbox': ('#25d366', '<path d="M21 11.5a9 9 0 0 1-13.3 7.9L3 21l1.5-4.6A9 9 0 1 1 21 11.5Z"/><path d="M8 7c-2 2 0 6 3 8 2 1 5 2 6-1l-3-2-1 2c-2-1-3-2-4-4l1-1Z" fill="currentColor" stroke="none"/>'),
 'olt': ('#a78bfa', '<rect x="3" y="3" width="18" height="8" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 7h1m3 0h1m3 0h2M7 17.5h1m3 0h1m3 0h2" fill="none"/>'),
 'almacen': ('#fb923c', '<path d="m12 3 9 5v10l-9 4-9-4V8Z"/><path d="m3 8 9 5 9-5m-9 5v9M7 5l10 6" fill="none"/>'),
 'requests': ('#f472b6', '<rect x="5" y="4" width="14" height="18" rx="2"/><rect x="9" y="2" width="6" height="4" rx="1"/><path d="M9 11h6m-6 4h6m-6 4h3" fill="none"/>'),
 'mobile': ('#38bdf8', '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 5h4m-3 14h2" fill="none"/>'),
 'health': ('#34d399', '<path d="M3 12h4l3-8 4 16 3-8h4" fill="none"/>'),
 'logout': ('#fb7185', '<path d="M10 4H4v16h6m3-8h8m-4-4 4 4-4 4" fill="none"/>'),
 'automation': ('#c084fc', '<rect x="4" y="7" width="16" height="13" rx="4"/><path d="M12 3v4M2 12v4m20-4v4m-13 0h6" fill="none"/><circle cx="8" cy="12" r="1"/><circle cx="16" cy="12" r="1"/>'),
}
ALIASES = {'customers':'clientes','customer_trash':'clientes','router_push_view':'routers','whatsapp_chat':'whatsapp_inbox','whatsapp_chatbot':'automation','invoices':'requests','payments':'finanzas','expenses_page':'finanzas','banks_page':'finanzas','users_page':'clientes','settings_page':'admin','onu_page':'olt','onu_overview':'olt','tickets_page':'soporte','installations_page':'soporte','monitoring_page':'health','mikrotik_commands':'routers'}

def icon(key, label=''):
    key = ALIASES.get(key,key)
    if key not in ART:
        name = label.lower()
        key = 'requests' if 'solicitud' in name else 'mobile' if 'móvil' in name else 'health' if 'estado' in name else 'automation' if 'automat' in name else 'requests'
    color, art = ART[key]
    return f'<span class="menu-icon menu-picture" style="--icon-color:{color}" aria-hidden="true"><svg viewBox="0 0 24 24" fill="currentColor" fill-opacity=".17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" focusable="false">{art}</svg></span>'

CSS = '''
.side .nav .menu-picture{display:inline-flex;align-items:center;justify-content:center;width:36px;min-width:36px;height:36px;flex:0 0 36px;border-radius:11px;color:var(--icon-color);background:color-mix(in srgb,var(--icon-color) 12%,transparent);border:1px solid color-mix(in srgb,var(--icon-color) 24%,transparent);box-shadow:inset 0 1px 0 #ffffff0d}
.side .nav .menu-picture svg{display:block;width:25px;height:25px;overflow:visible;fill-opacity:.17}
.side .nav a{display:flex;align-items:center;gap:12px}
.side .nav a:hover .menu-picture,.side .nav a.on .menu-picture{background:color-mix(in srgb,var(--icon-color) 22%,transparent);border-color:var(--icon-color)}
.side .nav .nav-subitem .menu-picture{width:27px;min-width:27px;height:27px;flex-basis:27px;border-radius:8px}
.side .nav .nav-subitem .menu-picture svg{width:19px;height:19px}
@media(max-width:850px){.side .nav a{gap:8px}.side .nav .menu-picture{width:32px;min-width:32px;height:32px;flex-basis:32px}}
'''
