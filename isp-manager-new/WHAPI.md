# Whapi.Cloud en INTER Flash

Administrador: WhatsApp → Whapi.Cloud (`/whatsapp/whapi`). Vincula primero el teléfono por QR en Whapi.Cloud y pega su token en el formulario. El servidor verifica `/health`, configura y verifica un webhook privado y activa Whapi solo al completar esos pasos. Conserva otros webhooks existentes. No necesitas pegar una URL manualmente.

Se requiere la SECRET_KEY estable de la aplicación (mínimo 24 caracteres). El token queda cifrado en SQLite y no se devuelve al navegador. No añadas tokens al repositorio. La API usa Bearer y HTTPS con validación TLS; no sigue redirecciones.

Admite texto individual, avisos de archivos entrantes y estados de entrega. No importa el historial ni descarga archivos. Ignora grupos y mensajes propios. Los identificadores LID solo se aceptan cuando Whapi facilita el teléfono explícito. Los callbacks se autentican mediante X-Interflash-Key y canal, se deduplican y se guardan en una transacción. Los estados se almacenan también antes de registrar el envío para resolver carreras.

No hay fallback automático a Meta ni reenvío tras respuestas ambiguas. Revisa el panel del proveedor antes de reintentar un envío cuyo resultado no se pudo confirmar. Los límites y facturación de Whapi son externos. La conexión no demuestra entrega: comprueba un envío a otro teléfono y una respuesta real en la bandeja.

Para regresar a Meta utiliza «Usar Meta para enviar». Conectar UltraMsg desactiva Whapi para los envíos y viceversa; los callbacks anteriores pueden seguir actualizando sus propios mensajes.

Validación: ejecutar cada módulo de pruebas en proceso independiente, pues cada uno inicia la aplicación con una base temporal:

    python -m unittest discover -s tests -p test_whapi.py -v
    python -m unittest discover -s tests -p test_ultramsg.py -v
    python -m unittest discover -s tests -p test_whatsapp_reception.py -v

Documentación oficial: https://panel.whapi.cloud/yaml/openapi.yaml
