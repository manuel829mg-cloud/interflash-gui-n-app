# Prueba controlada: Inter Flash TV + LibVLC (solo TV en vivo)

Fecha de preparación: 2026-11-21.
Rama: `experiment/libvlc-live-v063`.
Base: compilación nativa de Inter Flash TV v0.62 en `build/interflash-tv-v057-native` (commit `13de89f583132a5cf3e44c69cec07c74ed8d61f9`).
Estado actual: **plan y rama aislada; integración, compilación y prueba en televisor pendientes**.

## Objetivo
Evaluar LibVLC como motor adicional de TV en vivo, sin cambiar interfaz, controles de mando, diseño, numeración de canales, películas, series, catálogo, credenciales del proveedor ni servidores existentes. Comparar contra los motores actuales (Media3/ExoPlayer y libmpv).

## Implementación prevista
1. Restaurar el código Android nativo exacto que utilizó el flujo de compilación v0.62; no editar los archivos de publicación ni el entorno de producción.
2. Añadir una dependencia oficial `org.videolan.android:libvlc-all` en una versión estable compatible y fijar su versión; verificar las ABIs incluidas, tamaño y políticas de licencias LGPL.
3. Crear un adaptador nativo de reproducción LibVLC para TV en vivo que maneje superficie de video, audio, metadatos, volumen, eventos de buffering/error, conexiones, reconexiones y liberación al cambiar de canal o salir.
4. Encaminar de forma **opt-in** solo streams en vivo compatibles a LibVLC; mantener Media3/ExoPlayer + libmpv como opciones existentes. No usar VLC para VOD ni para DRM hasta verificar compatibilidad; conservar cabeceras, token, agente de usuario y parámetros permitidos, sin filtrarlos a logs.
5. Agregar un selector en configuración de prueba: `Actual` (predeterminado) / `VLC (prueba)`. Si VLC falla o no recibe imagen durante un umbral razonable, permitir volver al motor actual, sin bucles de reinicio. Registrar motivo y tiempos de primera imagen.
6. Crear compilación separada **InterFlashTV-v0.63-VLC-PRUEBA.apk**, validando paquete/firma e identificación de dispositivo. No instalar encima de la app del cliente a menos que la firma sea compatible; en su defecto usar un packageId de prueba y una vinculación de televisor de laboratorio para no consumir cupos del servicio.
7. Mantener la versión 0.62 existente intacta hasta aprobar pruebas reales.

## Prueba en dispositivos Android TV
Comparar ambos motores sobre los mismos canales y red, al menos: Digital 15 HD, Teleantillas 2, Telemicro 5, Color Visión 9, Telesistema 11, y otros canales HLS/TS representativos. En cada uno medir:
- Segundos desde OK hasta primera imagen y audio (cinco intentos por canal).
- Congelamientos y reconexiones durante sesiones prolongadas (idealmente 30 minutos).
- Cambio de canal, consumo de memoria, sincronía audio/video y retorno a la lista sin pantalla negra.
- Compatible con controles remotos, pantalla completa y versión de Android de los televisores de prueba.
- Al fallar la fuente del proveedor, dejar constancia de que el cambio de reproductor no puede corregir el origen.

## Criterios para recomendar la nueva versión
- APK compila y se puede instalar en televisor de prueba.
- Mismo comportamiento de navegación y controles que v0.62.
- Inicio y estabilidad no peores que los actuales, y mejoras verificables cuando las haya.
- Volver al motor original funciona.
- Ningún cambio de producción, de clientes o sincronización del panel sin autorización separada.

## Pendientes comprobables
- Integración real de LibVLC en los motores de reproducción.
- Compilación con Gradle/GitHub Actions y revisión de logs.
- Instalación y medición en equipo real.
- Resolver compatibilidad de firma/ID para distribución de prueba.

**No hay APK con LibVLC terminada aún.**
