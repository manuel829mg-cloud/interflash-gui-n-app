# GREEN-API

Administrador → WhatsApp → GREEN-API (`/whatsapp/greenapi`). Copiar apiUrl, idInstance y apiTokenInstance de la instancia autorizada por QR. El formulario comprueba getStateInstance, configura el webhook y verifica getSettings antes de activar el envío. Solo acepta hosts HTTPS numéricos *.api.greenapi.com, sin redirecciones. Las credenciales permanecen cifradas con la SECRET_KEY estable del servidor y no aparecen en errores.

Se conserva el proveedor actual si falla. No reemplaza un webhook de otro sistema. Los demás ajustes de la instancia permanecen intactos. Si los ajustes tardan en propagarse, repetir la conexión conserva la clave privada del callback. Los cambios entre Meta, UltraMsg, Whapi y GREEN-API son explícitos; no hay fallback ni reenvío automático tras respuestas ambiguas.

Recepción de texto individual por webhook con Authorization Bearer y validación de instancia. Deduplicación, transacción y estados monotónicos, incluidos los que llegan antes del registro del envío. Los grupos, mensajes propios y LID sin teléfono se ignoran. Los archivos aparecen como avisos, sin descargarse. No importa historial. Developer limita los chats; se debe verificar envío y respuesta reales antes de pagar un plan.

Pruebas en procesos independientes:

    python -m unittest discover -s tests -p test_greenapi.py -v
    python -m unittest discover -s tests -p test_whapi.py -v
    python -m unittest discover -s tests -p test_ultramsg.py -v
    python -m unittest discover -s tests -p test_whatsapp_reception.py -v

Documentación: https://green-api.com/en/docs/api/account/SetSettings/
