# Avisos de Sidecompras

GitHub Actions revisa el catálogo público de Sidecompras cada hora, alrededor del minuto 17. Por cada grupo de productos nuevos crea una incidencia y la asigna a **@gabyboan**. Cada aviso incluye nombre, comercio, precio y enlace. GitHub puede retrasar ejecuciones programadas.

La referencia inicial está guardada en `estado.json`; los productos existentes en ese momento no se avisan como nuevos. Se guardan todos los códigos vistos para evitar avisos duplicados, incluso si un producto desaparece y luego vuelve con el mismo código. No se avisa por cambios de precio. Si falla la consulta, no se actualiza el estado. Las incidencias incluyen un marcador para evitar repetir avisos si falla el guardado posterior.

## Recibir avisos por correo

En [la configuración de notificaciones de GitHub](https://github.com/settings/notifications), activá las notificaciones por email para actividad en la que participás y elegí **gabrielboan14@gmail.com** como dirección de notificación (debe estar agregada y verificada en tu cuenta de GitHub). Las notificaciones de GitHub dependen de esa configuración; el workflow no usa ni necesita una contraseña de Gmail.

Para probarlo desde la pestaña **Actions**, elegí **Avisos de Sidecompras**, pulsá **Run workflow**, activá **Crear una incidencia de prueba** y ejecutalo. Para una revisión real sin esperar el horario, ejecutalo sin esa opción. El repositorio es público: los avisos y los códigos conocidos también serán públicos.

GitHub puede deshabilitar los workflows programados en un repositorio público después de 60 días sin actividad. Si sucede, volvé a habilitarlo en la pestaña Actions.
