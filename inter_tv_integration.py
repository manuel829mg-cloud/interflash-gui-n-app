from flask import redirect, url_for
import app as appmodule

INTER_TV_URL = 'https://inter-tv-prueba-production.up.railway.app'

def setup(flask_app):
    @flask_app.get('/inter-tv')
    def inter_tv():
        if not appmodule.auth():
            return redirect(url_for('login'))
        body = (
            '<div class="head"><div><h1>📺 Inter TV</h1>'
            '<p>Canales dominicanos · Acceso desde INTER Flash</p></div></div>'
            '<div class="panel" style="padding:16px">'
            '<p>Abre Inter TV desde tu panel de administración. '
            'El reproductor y los accesos a canales se alojan en un servicio separado.</p>'
            '<a class="btn blue" target="_blank" rel="noopener noreferrer" '
            'href="' + INTER_TV_URL + '">▶ Abrir Inter TV</a>'
            '<p style="margin-top:15px;color:#8ea2ba;font-size:12px">'
            'Versión de prueba. Sin pagos mensuales ni cuentas de suscripción.</p>'
            '</div>'
        )
        return appmodule.shell('Inter TV', body, 'inter_tv')
