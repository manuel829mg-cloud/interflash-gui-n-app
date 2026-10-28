"""Opt-in TV-only administrator actions. NOT mounted by production WSGI.

Security: existing Flask login plus fresh TV-password verification and per-session
CSRF. No MikroTik, ISP billing, WhatsApp or streaming/provider side effects.
Mount this module only in a dedicated staging app for integration tests.
"""
import hmac
import secrets
import sqlite3
import time
from datetime import date, datetime, timezone
from flask import jsonify, request, session
from tv_subscriptions_isolated import (
    TV_PRICE_DOP, create_schema, record_payment, start_one_time_trial, status,
)


def setup(app, connection_factory, admin_authorized, tv_verified=None):
    """Register separate TV administration endpoints, opt-in.

    connection_factory returns a NEW SQLite connection with tuple or Row support.
    admin_authorized verifies the existing administrator login (not just a token).
    tv_verified checks successful recent TV-password verification.
    """
    tv_verified = tv_verified or (lambda: False)

    def gate():
        if not admin_authorized():
            return jsonify(error="Administrador no autorizado"), 401
        if not tv_verified():
            return jsonify(error="Verifica la contraseña de Inter Flash TV"), 403
        if not hmac.compare_digest(str(request.headers.get("X-TV-CSRF", "")),
                                   str(session.get("tv_csrf", "!"))):
            return jsonify(error="CSRF inválido"), 403
        return None

    def db():
        c = connection_factory()
        c.row_factory = sqlite3.Row
        create_schema(c)
        return c

    @app.post("/api/tv-subscriptions/create")
    def tv_subscription_create():
        error = gate()
        if error:
            return error
        data = request.get_json(silent=True) or {}
        try:
            customer_id = int(data.get("customer_id", 0))
            billing_day = int(data.get("billing_day", 0))
            if customer_id <= 0 or not 1 <= billing_day <= 31:
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            return jsonify(error="Cliente y día de corte inválidos"), 400
        with db() as c:
            try:
                c.execute("""INSERT INTO tv_subscriptions
                  (customer_id, billing_day, created_at) VALUES(?,?,?)""",
                  (customer_id, billing_day, datetime.now(timezone.utc).isoformat()))
                c.commit()
                sid = c.execute("SELECT id FROM tv_subscriptions WHERE customer_id=?",
                                (customer_id,)).fetchone()[0]
            except sqlite3.IntegrityError:
                return jsonify(error="El cliente ya tiene una suscripción TV"), 409
        return jsonify(subscription_id=sid, amount_dop=TV_PRICE_DOP), 201

    @app.post("/api/tv-subscriptions/<int:sid>/bind")
    def tv_subscription_bind(sid):
        error = gate()
        if error:
            return error
        data = request.get_json(silent=True) or {}
        code = str(data.get("device_code", "")).strip().upper()
        if len(code) != 8 or any(ch not in "0123456789ABCDEF" for ch in code):
            return jsonify(error="Código de televisor inválido"), 400
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                sub = c.execute("SELECT id,device_token_hash FROM tv_subscriptions WHERE id=?",
                                (sid,)).fetchone()
                if not sub:
                    c.rollback()
                    return jsonify(error="Suscripción TV no encontrada"), 404
                device = c.execute("""SELECT token_hash FROM tv_native_devices
                    WHERE code=? AND approved=1""", (code,)).fetchone()
                if not device:
                    c.rollback()
                    return jsonify(error="El televisor debe aprobarse antes de vincularse"), 409
                if sub["device_token_hash"] and sub["device_token_hash"] != device["token_hash"]:
                    c.rollback()
                    return jsonify(error="Desvincula primero el televisor anterior"), 409
                assigned = c.execute("""SELECT id FROM tv_subscriptions
                    WHERE device_token_hash=? AND id<>?""", (device["token_hash"], sid)).fetchone()
                if assigned:
                    c.rollback()
                    return jsonify(error="Este televisor ya pertenece a otra cuenta TV"), 409
                c.execute("UPDATE tv_subscriptions SET device_token_hash=?,unlinked_at=NULL WHERE id=?",
                          (device["token_hash"], sid))
                c.commit()
            except Exception:
                c.rollback()
                raise
        return jsonify(bound=True, subscription_id=sid)

    @app.post("/api/tv-subscriptions/<int:sid>/pay")
    def tv_subscription_pay(sid):
        error = gate()
        if error:
            return error
        data = request.get_json(silent=True) or {}
        reference = str(data.get("receipt_reference", "")).strip()
        if not reference or len(reference) > 128:
            return jsonify(error="Referencia única de pago obligatoria"), 400
        # A receipt is confirmed by an authenticated administrator, NOT by a
        # customer-submitted WhatsApp screenshot or unverified payment claim.
        with db() as c:
            try:
                due = record_payment(c, sid, reference, date.today())
            except LookupError:
                return jsonify(error="Suscripción no encontrada"), 404
        return jsonify(paid=True, amount_dop=TV_PRICE_DOP,
                       next_due=due.isoformat(),
                       notice="Un televisor desvinculado requiere vincularse otra vez.")

    @app.post("/api/tv-subscriptions/<int:sid>/trial")
    def tv_subscription_trial(sid):
        error = gate()
        if error:
            return error
        with db() as c:
            try:
                until = start_one_time_trial(c, sid)
            except ValueError:
                return jsonify(error="Prueba utilizada o suscripción no elegible"), 409
        return jsonify(trial=True, expires_at_utc=until.isoformat())

    @app.get("/api/tv-subscriptions/<int:sid>")
    def tv_subscription_view(sid):
        if not admin_authorized() or not tv_verified():
            return jsonify(error="No autorizado"), 403
        with db() as c:
            state = status(c, sid, date.today())
        if state == "NOT_FOUND":
            return jsonify(error="No encontrada"), 404
        return jsonify(subscription_id=sid, status=state,
                       amount_dop=TV_PRICE_DOP)
