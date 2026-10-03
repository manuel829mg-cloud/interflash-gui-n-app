from flask import redirect, url_for


def setup(app):
    # Preserve the old direct-API configuration page under /routers/manual.
    old_routers = app.view_functions.get('routers')
    if old_routers is not None and 'routers_manual' not in app.view_functions:
        app.add_url_rule('/routers/manual', endpoint='routers_manual', view_func=old_routers, methods=['GET', 'POST'])

    # The main Routers menu should show the live push-sync status page,
    # because this installation uses CCR -> INTER Flash HTTPS synchronization.
    def routers_sync_entry():
        return redirect(url_for('agent_view'))

    app.view_functions['routers'] = routers_sync_entry
