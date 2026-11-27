# Avisos de Sidecompras

GitHub Actions revisa el catálogo público de Sidecompras cada hora, alrededor del minuto 17. Por cada grupo de productos nuevos crea una incidencia y la asigna a **@gabyboan**. Cada aviso incluye nombre, comercio, precio y enlace. GitHub puede retrasar ejecuciones programadas.

La referencia inicial está guardada en `estado.json`; los productos existentes en ese momento no se avisan como nuevos. Se guardan todos los códigos vistos para evitar avisos duplicados, incluso si un producto desaparece y luego vuelve con el mismo código. También se vigilan bajas de precios y ofertas externas como se describe abajo. Si falla la consulta, no se actualiza el estado. Las incidencias incluyen un marcador para evitar repetir avisos si falla el guardado posterior.

## Recibir avisos por correo

En [la configuración de notificaciones de GitHub](https://github.com/settings/notifications), activá las notificaciones por email para actividad en la que participás y elegí **gabrielboan14@gmail.com** como dirección de notificación (debe estar agregada y verificada en tu cuenta de GitHub). Las notificaciones de GitHub dependen de esa configuración; el workflow no usa ni necesita una contraseña de Gmail.

Para probarlo desde la pestaña **Actions**, elegí **Avisos de Sidecompras**, pulsá **Run workflow**, activá **Crear una incidencia de prueba** y ejecutalo. Para una revisión real sin esperar el horario, ejecutalo sin esa opción. El repositorio es público: los avisos y los códigos conocidos también serán públicos.

GitHub puede deshabilitar los workflows programados en un repositorio público después de 60 días sin actividad. Si sucede, volvé a habilitarlo en la pestaña Actions.

## Precios y ofertas

Para todos los productos del catálogo se guarda el precio anunciado y se avisa cuando baja al menos un 20 % respecto de la observación anterior. Este aviso compara precios dentro de Sidecompras y por sí solo no demuestra que sea la mejor oferta del mercado. La primera observación sirve de referencia y no genera avisos.

Además, se comparan externamente cinco publicaciones verificadas de celulares con ofertas recientes de SoloPrecio: Galaxy S26 Ultra 12/256, A17 4G 4/128, A36 5G 8/256 y Motorola G15 y G17 4/128. Solo se usan referencias con la RAM indicada, stock y una lectura de hasta 48 horas, y se avisa si Sidecompras publica un precio al menos 20 % menor. Estas comparaciones no cubren todos los artículos; el [listado de comparaciones](OFERTAS.md) se actualiza con cada revisión. Si falla la fuente externa, se reintenta sin cerrar la alerta previa.

El precio de promoción se usa solamente cuando la tienda indica un descuento vigente; no se usa como precio actual el valor tachado. Algunas promociones aplican una bonificación posterior en el resumen, con requisitos de tarjeta y cuotas. Revisá el precio final, vigencia, stock y condiciones antes de comprar. SoloPrecio no incluye todos los comercios; también es posible que alguna ficha externa agrupe variantes equivocadas, por eso hay que verificar los detalles en la tienda.
