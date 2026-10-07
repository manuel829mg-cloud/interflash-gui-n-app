# WhatsApp QR integration — pending activation

Adds `/whatsapp/qr` for administrator-only QR and pairing-code linking via WAHA.
Meta remains the default until `WHATSAPP_PROVIDER=waha` is explicitly configured.
The existing inbox and manual text queue use the chosen provider. This does not
add billing automation or a chatbot and does not send test messages automatically.

## Activation plan

1. Provision one separate WAHA Core container in Railway, using an explicitly
   pinned and reviewed `devlikeapro/waha` image version/digest and WEBJS engine.
   Do not use the main Flask service or its SQLite volume for WAHA.
2. Attach a persistent volume at `/app/.sessions`. Keep one replica and retain
   the volume across redeployments. This service adds metered hosting usage.
3. Configure a random `WAHA_API_KEY`; disable public dashboard and Swagger,
   disable QR logging (`WAHA_PRINT_QR=False`), and use private Railway networking.
   Validate the exact image's configuration names against its documentation.
4. On Flask set `WHATSAPP_QR_URL` to the private service URL, the matching
   `WHATSAPP_QR_API_KEY`, and an independent random `WHATSAPP_QR_WEBHOOK_KEY`.
   Set `WHATSAPP_QR_CALLBACK_URL` to
   `https://interflash-isp-manager.up.railway.app/webhooks/whatsapp-qr`.
   Secrets must be entered through Railway variables, never git.
5. Deploy this branch; visit `/whatsapp/qr`, generate QR and link on the phone.
   Fresh sessions receive the authenticated webhook configuration automatically.
   Existing sessions must have their webhook configuration verified separately.
6. Confirm the session is WORKING, then set `WHATSAPP_PROVIDER=waha` and redeploy.
   Ask the user to send and receive one real text and verify delivery events.
   Restart WAHA once to confirm the session survives and remains linked.
7. Rollback: set `WHATSAPP_PROVIDER=meta` and redeploy. No chats are deleted.

## Validation and limitations

Unit tests cover administrator access, CSRF, webhook authentication, duplicate
messages, hidden-ID isolation, malformed QR responses, pairing validation,
provider routing and transactional retry on database failure. Meta regression
tests remain separate to isolate their temporary databases.

No live WAHA service or linked-device test has been run yet. Hidden `@lid` IDs
are deliberately ignored instead of being treated as telephone numbers; a
provider-specific lookup is required before supporting those senders. Groups,
channels, history import and attachments are outside this first version; media
messages show a placeholder. Delivery callbacks arriving before the outgoing
record is saved are not buffered yet. Pairing-code availability depends on the
WhatsApp account and engine; QR is the primary flow. Non-official WhatsApp Web
integrations can disconnect or result in account restrictions; do not promise
Meta approval or guaranteed availability.

Sources:
- https://waha.devlike.pro/docs/how-to/sessions/
- https://waha.devlike.pro/docs/how-to/send-messages/
- https://waha.devlike.pro/docs/how-to/receive-messages/
- https://waha.devlike.pro/docs/how-to/security/
