Interfaz y UX — Grupo Oro

Resumen de cambios:
- Integrado Tailwind CSS vía CDN (rápido y sencillo) en `templates/base.html`.
- Añadida configuración mínima de `tailwind.config` en línea para la paleta y la fuente.
- Mensajes de Django mostrados en `base.html` con un pequeño botón para cerrar.
- Página principal (`myapp/templates/myapp/home.html`):
  - Formulario modernizado con diseño limpio (blanco/gris/oro).
  - `select` de nichos con opciones comunes y una opción "Otro" que muestra un campo de texto.
  - Validaciones en cliente: CP (5 dígitos + prefijo 01-52), categoría obligatoria.
  - Mensajes claros: errores de validación, falta de API key, procesando, sin resultados, enlace de descarga.
- Perfil (`templates/auth/profile.html`):
  - Formulario estilizado con clases Tailwind.
  - Uso de `messages` tras guardar el perfil.
- `myapp/views.py`: se añadieron widgets para los formularios y llamadas a `messages.success` en registro y perfil.

Cómo integrar Tailwind (opciones):
1) CDN (implementado):
   - Ventajas: sin build, rápido para prototipos y proyectos pequeños. Insertamos `<script src="https://cdn.tailwindcss.com"></script>` y definimos `tailwind.config` en `base.html`.
   - Limitaciones: mayor tamaño en producción y menos control sobre purga de clases. Basta para este proyecto si no se requiere optimización extrema.

2) Build (recomendado para producción):
   - Crear `package.json`, instalar `tailwindcss`, `postcss` y `autoprefixer`.
   - Configurar `tailwind.config.js` y `postcss.config.js`.
   - Compilar CSS con `npx tailwindcss -i ./src/input.css -o ./static/css/tailwind.css --minify` y servir `static/css/tailwind.css` desde Django.
   - Ventaja: purga de clases y CSS optimizado.

Buenas prácticas UX aplicadas:
- Paleta: blanco/gris/oro (variables definidas en `static/css/brand.css`).
- Tipografía: Inter (Google Fonts) para lectura moderna.
- Botones con suficiente contraste y foco visible.
- Mensajes claros para éxito/error y pasos siguientes (por ejemplo: "Debes configurar tu API Key en el perfil").
- Responsividad: uso de utilidades Tailwind (p. ej. `sm:`, `lg:`) y contenedores max-width.

Siguientes mejoras sugeridas (opcionales):
- Compilar Tailwind para producción y reemplazar CDN.
- Agregar tests de integración para endpoints `/scrape/`, `/status/<job>/` y `/download/<job>/`.
- Localizar textos con `gettext` si la app crecerá a varios idiomas.

Notas de verificación:
- `python manage.py check` ejecutado: sin problemas.

Si quieres, puedo:
- Convertir la integración de Tailwind a una configuración con `npm` y generar los archivos necesarios.
- Añadir animaciones sutiles en botones y estados de carga.
- Implementar un layout para la página de resultados con tablas paginadas.

Cambios recientes de autenticación:
- El sistema de login y registro se ha simplificado para usar únicamente Email y Contraseña. Los campos "Nombre" y "Apellidos" han sido eliminados del formulario de registro para agilizar la creación de cuentas. Los campos de perfil (nombre/apellidos) siguen existiendo en el modelo y pueden editarse desde el perfil si es necesario.

Cambios en el buscador:
- Se han eliminado las categorías predefinidas y el selector de nichos. Ahora el campo `Categoría / Tipo de negocio` es un input de texto libre donde el usuario puede escribir cualquier tipo de negocio (por ejemplo: "peluquería", "taller mecánico", "panadería").
- La búsqueda acepta cualquier texto arbitrario y se envía tal cual al backend para maximizar la flexibilidad de consultas.
- Validaciones: el CP sigue siendo obligatorio y debe ser un código postal español válido de 5 dígitos (prefijo 01–52).
