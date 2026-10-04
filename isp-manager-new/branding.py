from functools import wraps
import app as base

LOGO_URL = '/static/interflash-logo.svg'

_EXTRA_CSS = '''
<style>
.brandmark.brandmark-logo{background:transparent!important;width:64px;height:64px;border-radius:0;overflow:visible;display:flex;align-items:center;justify-content:center;flex:0 0 64px;box-shadow:none}
.brandmark.brandmark-logo img{width:64px;height:64px;object-fit:contain;display:block;border-radius:0}
.brand{align-items:center}
.loginbox .brandmark.brandmark-logo{width:120px;height:120px;flex-basis:120px;box-shadow:none}
.loginbox .brandmark.brandmark-logo img{width:120px;height:120px;object-fit:contain;border-radius:0}
@media(max-width:850px){.brandmark.brandmark-logo{width:58px;height:58px;flex-basis:58px}.brandmark.brandmark-logo img{width:58px;height:58px}.side .brand{padding-left:4px;padding-right:4px}}
</style>
'''


def _apply_branding(html):
    if not isinstance(html, str):
        return html
    logo = f'<div class="brandmark brandmark-logo"><img src="{LOGO_URL}" alt="Inter Flash"></div>'
    html = html.replace('<div class="brandmark">IF</div>', logo)
    if _EXTRA_CSS not in html:
        html = html.replace('</head>', _EXTRA_CSS + '</head>')
    return html


def setup(app):
    original_shell = base.shell

    @wraps(original_shell)
    def branded_shell(*args, **kwargs):
        return _apply_branding(original_shell(*args, **kwargs))

    base.shell = branded_shell

    original_login = app.view_functions.get('login')
    if original_login:
        @wraps(original_login)
        def branded_login(*args, **kwargs):
            result = original_login(*args, **kwargs)
            if isinstance(result, str):
                return _apply_branding(result)
            if isinstance(result, tuple) and result and isinstance(result[0], str):
                return (_apply_branding(result[0]),) + result[1:]
            try:
                if getattr(result, 'mimetype', '') == 'text/html':
                    text = result.get_data(as_text=True)
                    result.set_data(_apply_branding(text))
            except Exception:
                pass
            return result
        app.view_functions['login'] = branded_login
