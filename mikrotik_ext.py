import os
import socket
from datetime import datetime
from html import escape

import routeros_api
from cryptography.fernet import Fernet, InvalidToken
from flask import request, redirect, url_for

from app import con, auth, shell

ROUTER_SECRET_KEY = os.getenv("ROUTER_SECRET_KEY", "")


def _cipher():
    if not ROUTER_SECRET_KEY:
        raise RuntimeError("Falta la clave de cifrado del módulo MikroTik.")
    return Fernet(ROUTER_SECRET_KEY.encode())


def _encrypt(value):
    return _cipher().encrypt(value.encode()).decode()


def _decrypt(value):
    try:
        return _cipher().decrypt((value or "").encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("No se pudo descifrar la contraseña guardada del MikroTik.") from exc


def _migrate():
    c = con()
    cols = {r["name"] for r in c.execute("PRAGMA table_info(routers)").fetchall()}
    additions = {
        "username": "username TEXT",
        "password_enc": "password_enc TEXT",
        "use_ssl": "use_ssl INTEGER DEFAULT 0",
        "identity": "identity TEXT",
        "version": "version TEXT",
        "board_name": "board_name TEXT",
        "last_seen": "last_seen TEXT",
        "last_error": "last_error TEXT",
        "pppoe_active": "pppoe_active INTEGER DEFAULT 0",
    }
    for name, ddl in additions.items():
        if name not in cols:
            c.execute(f"ALTER TABLE routers ADD COLUMN {ddl}")
    c.commit()
    c.close()


def _connect(row, extended=False):
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(7)
    pool = None
    try:
        ssl_on = bool(row["use_ssl"])
        pool = routeros_api.RouterOsApiPool(
            row["host"],
            username=row["username"],
            password=_decrypt(row["password_enc"]),
            port=int(row["port"] or (8729 if ssl_on else 8728)),
            plaintext_login=True,
            use_ssl=ssl_on,
            ssl_verify=False,
            ssl_verify_hostname=False,
        )
        api = pool.get_api()
        ident_rows = api.get_resource("/system/identity").get()
        resource_rows = api.get_resource("/system/resource").get()
        active_rows = api.get_resource("/ppp/active").get()

        ident = ident_rows[0].get("name", "") if ident_rows else ""
        resource = resource_rows[0] if resource_rows else {}
        info = {
            "identity": ident,
            "version": resource.get("version", ""),
            "board_name": resource.get("board-name", ""),
            "uptime": resource.get("uptime", ""),
            "cpu_load": resource.get("cpu-load", ""),
            "pppoe_active": len(active_rows),
            "active": [],
            "secrets": [],
            "profiles": [],
        }

        if extended:
            for a in active_rows:
                info["active"].append({
                    "name": a.get("name", ""),
                    "address": a.get("address", ""),
                    "caller_id": a.get("caller-id", ""),
                    "uptime": a.get("uptime", ""),
                })
            for s in api.get_resource("/ppp/secret").get():
                info["secrets"].append({
                    "name": s.get("name", ""),
                    "profile": s.get("profile", ""),
                    "service": s.get("service", ""),
                    "disabled": s.get("disabled", "false"),
                })
            for p in api.get_resource("/ppp/profile").get():
                info["profiles"].append({
                    "name": p.get("name", ""),
                    "remote_address": p.get("remote-address", ""),
                    "rate_limit": p.get("rate-limit", ""),
                })
        return info
    finally:
        if pool:
            try:
                pool.disconnect()
            except Exception:
                pass
        socket.setdefaulttimeout(old_timeout)


def _status(router_id, info=None, error=None):
    c = con()
    if info:
        c.execute(
            """UPDATE routers SET status='ONLINE', identity=?, version=?, board_name=?,
               last_seen=?, last_error=NULL, pppoe_active=? WHERE id=?""",
            (
                info["identity"],
                info["version"],
                info["board_name"],
                datetime.now().isoformat(timespec="seconds"),
                info["pppoe_active"],
                router_id,
            ),
        )
    else:
        c.execute(
            "UPDATE routers SET status='ERROR', last_error=?, last_seen=? WHERE id=?",
            (str(error)[:500], datetime.now().isoformat(timespec="seconds"), router_id),
        )
    c.commit()
    c.close()


def routers_view():
    if not auth():
        return redirect(url_for("login"))

    c = con()
    if request.method == "POST":
        try:
            password_enc = _encrypt(request.form["password"])
            port = int(request.form.get("port") or 8728)
            use_ssl = 1 if request.form.get("use_ssl") == "1" else 0
            c.execute(
                """INSERT INTO routers(name,host,port,status,username,password_enc,use_ssl)
                   VALUES(?,?,?,'PENDIENTE',?,?,?)""",
                (
                    request.form["name"].strip(),
                    request.form["host"].strip(),
                    port,
                    request.form["username"].strip(),
                    password_enc,
                    use_ssl,
                ),
            )
            c.commit()
            router_id = c.execute("SELECT last_insert_rowid() id").fetchone()["id"]
            c.close()
            return redirect(url_for("router_test", id=router_id))
        except Exception as exc:
            c.close()
            return redirect(url_for("routers", msg=f"Error al guardar: {exc}", kind="bad"))

    rows = c.execute("SELECT * FROM routers ORDER BY id DESC").fetchall()
    c.close()

    trs = ""
    for r in rows:
        state_cls = "ok" if r["status"] == "ONLINE" else ("bad" if r["status"] == "ERROR" else "pending")
        detail = (f"{escape(r['identity'] or '')} {escape(r['version'] or '')}").strip() or "Sin probar"
        err = f"<br><small style='color:#a62f20'>{escape(r['last_error'] or '')}</small>" if r["last_error"] else ""
        if r["username"] and r["password_enc"]:
            actions = (
                f"<a class='btn blue' href='{url_for('router_test', id=r['id'])}'>Probar</a> "
                f"<a class='btn' href='{url_for('router_detail', id=r['id'])}'>Ver PPPoE</a>"
            )
        else:
            actions = "<span class='tag pending'>FALTAN CREDENCIALES</span>"
        trs += (
            f"<tr><td><b>{escape(r['name'])}</b><br><small>{detail}</small></td>"
            f"<td>{escape(r['host'])}:{r['port']}</td><td>{escape(r['username'] or '-')}</td>"
            f"<td><span class='tag {state_cls}'>{escape(r['status'])}</span>{err}</td>"
            f"<td>{r['pppoe_active'] or 0}</td><td>{actions}</td></tr>"
        )

    body = f"""
    <div class="head"><div><h1>Routers</h1><p>Conexión real con MikroTik RouterOS</p></div></div>
    <div class="panel">
      <h3>Agregar MikroTik</h3>
      <form class="grid" method="post">
        <div class="field"><label>Nombre</label><input name="name" placeholder="CCR2116" required></div>
        <div class="field"><label>Host / IP accesible</label><input name="host" placeholder="IP pública, VPN o WireGuard" required></div>
        <div class="field"><label>Puerto API</label><input name="port" type="number" value="8728" required></div>
        <div class="field"><label>Usuario RouterOS</label><input name="username" autocomplete="off" required></div>
        <div class="field"><label>Contraseña RouterOS</label><input name="password" type="password" autocomplete="new-password" required></div>
        <div class="field"><label>Conexión</label>
          <select name="use_ssl"><option value="0">API 8728 / VPN</option><option value="1">API-SSL</option></select>
        </div>
        <div class="full"><button class="btn green">Guardar y probar conexión</button></div>
      </form>
      <p class="muted"><b>Seguridad:</b> la contraseña se cifra antes de guardarse. No se vuelve a mostrar.</p>
    </div>
    <div class="panel">
      <table><tr><th>Router</th><th>Host</th><th>Usuario</th><th>Estado</th><th>PPPoE activos</th><th>Acciones</th></tr>
      {trs or '<tr><td colspan="6" class="empty">No hay routers todavía.</td></tr>'}
      </table>
    </div>
    """
    return shell("Routers", body, "routers")


def router_test(id):
    if not auth():
        return redirect(url_for("login"))
    c = con()
    row = c.execute("SELECT * FROM routers WHERE id=?", (id,)).fetchone()
    c.close()
    if not row:
        return redirect(url_for("routers", msg="Router no encontrado.", kind="bad"))
    if not row["username"] or not row["password_enc"]:
        return redirect(url_for("routers", msg="A ese router le faltan usuario y contraseña.", kind="bad"))
    try:
        info = _connect(row, extended=False)
        _status(id, info=info)
        return redirect(
            url_for(
                "routers",
                msg=f"Conectado a {info['identity'] or row['name']}. RouterOS {info['version']}. PPP activos: {info['pppoe_active']}.",
            )
        )
    except Exception as exc:
        _status(id, error=exc)
        return redirect(url_for("routers", msg=f"No se pudo conectar: {exc}", kind="bad"))


def router_detail(id):
    if not auth():
        return redirect(url_for("login"))
    c = con()
    row = c.execute("SELECT * FROM routers WHERE id=?", (id,)).fetchone()
    c.close()
    if not row:
        return redirect(url_for("routers", msg="Router no encontrado.", kind="bad"))

    try:
        info = _connect(row, extended=True)
        _status(id, info=info)
    except Exception as exc:
        _status(id, error=exc)
        return redirect(url_for("routers", msg=f"No se pudo leer el MikroTik: {exc}", kind="bad"))

    active_names = {x["name"] for x in info["active"]}
    secrets = ""
    for s in info["secrets"]:
        status = "CONECTADO" if s["name"] in active_names else (
            "DESHABILITADO" if str(s["disabled"]).lower() in ("true", "yes") else "OFFLINE"
        )
        cls = "ok" if status == "CONECTADO" else ("bad" if status == "DESHABILITADO" else "pending")
        secrets += (
            f"<tr><td>{escape(s['name'])}</td><td>{escape(s['profile'] or '-')}</td>"
            f"<td>{escape(s['service'] or '-')}</td><td><span class='tag {cls}'>{status}</span></td></tr>"
        )

    active_rows = "".join(
        f"<tr><td>{escape(a['name'])}</td><td>{escape(a['address'] or '-')}</td>"
        f"<td>{escape(a['caller_id'] or '-')}</td><td>{escape(a['uptime'] or '-')}</td></tr>"
        for a in info["active"]
    )
    profiles = "".join(
        f"<tr><td>{escape(p['name'])}</td><td>{escape(p['remote_address'] or '-')}</td>"
        f"<td>{escape(p['rate_limit'] or '-')}</td></tr>"
        for p in info["profiles"]
    )

    body = f"""
    <div class="head"><div><h1>{escape(info['identity'] or row['name'])}</h1>
      <p>{escape(info['board_name'] or '')} · RouterOS {escape(info['version'] or '')} · Uptime {escape(info['uptime'] or '')}</p>
      </div><a class="btn blue" href="{url_for('router_test', id=id)}">Actualizar estado</a></div>
    <div class="cards">
      <div class="card"><div class="label">PPPoE activos</div><div class="num">{info['pppoe_active']}</div></div>
      <div class="card"><div class="label">CPU</div><div class="num">{escape(str(info['cpu_load']))}%</div></div>
      <div class="card"><div class="label">RouterOS</div><div class="num" style="font-size:20px">{escape(info['version'] or '-')}</div></div>
      <div class="card"><div class="label">Estado</div><div class="num" style="font-size:20px;color:#087646">ONLINE</div></div>
    </div>
    <div class="panel"><h3>Clientes PPPoE</h3><table>
      <tr><th>Usuario</th><th>Perfil</th><th>Servicio</th><th>Estado</th></tr>
      {secrets or '<tr><td colspan="4" class="empty">No hay secretos PPPoE.</td></tr>'}
    </table></div>
    <div class="panel"><h3>Sesiones activas</h3><table>
      <tr><th>Usuario</th><th>IP</th><th>Caller ID</th><th>Uptime</th></tr>
      {active_rows or '<tr><td colspan="4" class="empty">No hay sesiones activas.</td></tr>'}
    </table></div>
    <div class="panel"><h3>Perfiles PPP</h3><table>
      <tr><th>Perfil</th><th>Pool / Remote</th><th>Rate limit</th></tr>
      {profiles or '<tr><td colspan="3" class="empty">No hay perfiles.</td></tr>'}
    </table></div>
    """
    return shell("MikroTik", body, "routers")


def setup(app):
    _migrate()
    app.view_functions["routers"] = routers_view
    app.add_url_rule("/routers/<int:id>/test", endpoint="router_test", view_func=router_test, methods=["GET"])
    app.add_url_rule("/routers/<int:id>", endpoint="router_detail", view_func=router_detail, methods=["GET"])
