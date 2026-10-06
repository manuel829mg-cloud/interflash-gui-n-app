# Aplicación móvil INTER Flash

Aplicación web instalable, integrada con la plataforma Flask existente. Después de desplegar, abrir `/app` por HTTPS. En Android usar «Instalar aplicación» cuando el navegador lo ofrezca; en iPhone usar Safari → Compartir → Añadir a pantalla de inicio. No es un APK ni una publicación en las tiendas.

El administrador utiliza su usuario habitual y conserva las funciones existentes. En el perfil de cada cliente, «Portal cliente» genera su enlace privado. El cliente abre ese enlace para consultar sus facturas y pagos, reportar transferencias y solicitar soporte. Revocar o regenerar el enlace revoca también las sesiones móviles anteriores. Tratar ese enlace como una contraseña.

Los reportes de transferencias aparecen en `/app/solicitudes` para ADMIN y CAJA. Marcar como revisado no paga facturas: verificar el depósito y registrarlo con el flujo habitual de cobros. Las solicitudes de soporte también crean tickets en el módulo existente.

El arranque crea únicamente la tabla adicional `mobile_requests`. Los datos privados se sirven sin caché y el modo sin conexión muestra un aviso; hace falta conexión para consultar o enviar datos. Se conserva la autenticación existente y se añade protección CSRF a los nuevos formularios.

Validación: `python -m unittest discover -s tests -p test_mobile_app.py -v`. Cubre aislamiento entre clientes, revocación, permisos, CSRF, montos, reportes sin liquidación automática y soporte. Probado también importando `wsgi` con una base de datos temporal.

Para revertir: revertir el commit de esta aplicación y redesplegar; la tabla nueva puede conservarse sin afectar al código anterior.
