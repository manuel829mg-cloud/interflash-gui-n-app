# UltraMsg integration

Visit `/whatsapp/ultramsg` as ADMIN. Enter the instance ID and token after scanning
UltraMsg's QR. The form verifies authentication, preserves send delays, configures
incoming/ack callbacks, verifies the callback URL, then activates UltraMsg.
No message is sent during setup. Meta credentials remain unchanged.

Tokens are Fernet encrypted using a key derived from the application's stable
SECRET_KEY (minimum 24 characters); do not rotate SECRET_KEY without re-entering
UltraMsg credentials. The UI never redisplays credentials. Optional environment
fallbacks are ULTRAMSG_INSTANCE_ID and ULTRAMSG_TOKEN. CSRF checks protect setup.

Callbacks validate an independent random URL secret and instance ID, and are
transactional and deduplicated. Callback URLs contain a secret: do not expose
raw access-log query strings. Outbound UUID referenceId correlates delivery events;
early acknowledgements are buffered and later statuses do not regress.

Scope: manual text messages and existing text queue, inbound individual messages.
Attachments show their text/placeholder. No media downloads, chatbot, historical
import or new billing automation. Group/channel and unresolved hidden @lid IDs
are ignored rather than misidentified as customer numbers. API acceptance is
shown as ACEPTADO until an acknowledgement arrives. Real send/receive validation
requires a linked phone and working provider credentials.

Rollback: use the administrator button 'Usar Meta para enviar'. No history is
removed. Railway needs no new service for this hosted provider.

Validation: six UltraMsg tests (auth/CSRF/encryption, inactive session, callback
authentication/deduplication, early acknowledgements, transaction rollback,
sending/provider isolation); four existing Meta webhook regression tests.

Provider reference:
https://docs.ultramsg.com/api/post/messages/chat
https://docs.ultramsg.com/api/get/instance/status
https://docs.ultramsg.com/api/post/instance/settings
https://blog.ultramsg.com/receive-whatsapp-api-messages-use-webhook-nodejs/
https://blog.ultramsg.com/whatsapp-message-delivery-read-status-ack/
