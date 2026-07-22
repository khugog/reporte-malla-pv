# Instructivo de Configuración de la Automatización con GitHub Actions y Google Drive

Este instructivo te guiará paso a paso para configurar las credenciales necesarias y hacer que la automatización funcione correctamente en GitHub.

---

## Paso 1: Crear una Cuenta de Servicio en Google Cloud

1. Entra a la consola de Google Cloud: [console.cloud.google.com](https://console.cloud.google.com/).
2. Crea un proyecto nuevo (o selecciona uno existente). Es totalmente gratuito para este nivel de uso.
3. Habilita la **Google Drive API**:
   - En la barra de búsqueda de arriba, busca **Google Drive API**.
   - Haz clic en ella y presiona el botón **Habilitar** (Enable).
4. Crea la Cuenta de Servicio (Service Account):
   - Ve al menú lateral izquierdo, selecciona **IAM y administración** > **Cuentas de servicio**.
   - Haz clic en **Crear cuenta de servicio** en la parte superior.
   - Asígnale un nombre (ej. `reportes-automatizados`) y haz clic en **Crear y continuar**.
   - Puedes omitir los pasos de Roles y Acceso de usuarios (haz clic en **Listo** / **Done**).
5. Crear y descargar la Clave JSON:
   - En la lista de cuentas de servicio, haz clic sobre el correo electrónico de la cuenta que acabas de crear.
   - Ve a la pestaña **Claves** (Keys) en la parte superior.
   - Haz clic en **Agregar clave** > **Crear clave nueva**.
   - Selecciona el formato **JSON** y haz clic en **Crear**.
   - Se descargará un archivo `.json` en tu computadora (ej. `mi-proyecto-xxxx.json`). **Guarda este archivo muy bien, contiene la llave de acceso.**

---

## Paso 2: Compartir las Carpetas de Google Drive

La Cuenta de Servicio actúa como si fuera un usuario más. Para que pueda leer, escribir, mover y borrar archivos, debes compartir tus carpetas de Google Drive con ella:

1. Abre el archivo `.json` que descargaste en el paso anterior y busca la línea que dice `"client_email"`. Verás un correo que termina en `@...gserviceaccount.com`. Copia esa dirección de correo.
2. Comparte cada carpeta con ese correo de cuenta de servicio con el permiso indicado:
   - Carpeta **Inputs**: permiso de **Editor** (ya no basta con Lector: la vigilancia cada 15 minutos escribe la bitácora y un archivo de estado dentro de Inputs, y el reporte mueve los insumos procesados fuera de esta carpeta).
   - Carpeta **Salidas**: permiso de **Editor** (para subir el reporte final).
   - Carpeta **Historial**: permiso de **Editor** (para crear las subcarpetas por fecha y archivar los insumos procesados).
3. Copia los **IDs de las carpetas** de la URL del navegador.
   - La URL de una carpeta de Drive se ve así: `https://drive.google.com/drive/folders/1A2B3C4D5E6F7G8H9I0J`
   - El ID de esa carpeta es: `1A2B3C4D5E6F7G8H9I0J` (la última parte de la URL).
   - Guarda el ID de las carpetas de Inputs, Salidas e Historial.

---

## Paso 3: Configurar los Secretos de GitHub (GitHub Secrets)

Para que GitHub Actions pueda usar estas credenciales sin exponerlas públicamente en el código:

1. Ve a tu repositorio en GitHub.
2. Haz clic en la pestaña **Settings** (Configuración).
3. En el menú lateral izquierdo, selecciona **Secrets and variables** > **Actions**.
4. Haz clic en **New repository secret** en la esquina superior derecha y añade los siguientes 4 secretos:

* **Nombre:** `GDRIVE_CREDENTIALS`
  * **Valor:** Copia y pega **todo el contenido** del archivo JSON de credenciales que descargaste en el Paso 1 (abre el archivo con cualquier editor de texto y copia todo desde `{` hasta `}`).
* **Nombre:** `GDRIVE_INPUT_FOLDER_ID`
  * **Valor:** `14IcQo4amCE6c39vT7lHT8_FAWoJjcbXX` (El ID de tu carpeta **Inputs**).
* **Nombre:** `GDRIVE_OUTPUT_FOLDER_ID`
  * **Valor:** `1VJWfPGJnjyLRv3cHJ-r5fWOOuGmJ6ykO` (El ID de tu carpeta **Salidas**).
* **Nombre:** `GDRIVE_HISTORIAL_FOLDER_ID`
  * **Valor:** `13447gLrW-3z_A9JophTpe0r4JknoWHhy` (El ID de tu carpeta **Historial**).

---

## Paso 4: Cómo funciona la automatización

Hay dos flujos de trabajo independientes en `.github/workflows/`:

### Módulo A — Vigilancia y bitácora (`vigilancia_bitacora.yml`)
- Se ejecuta automáticamente **cada 15 minutos** (`*/15 * * * *`).
- Revisa únicamente el contenido de la carpeta **Inputs**.
- Mantiene un único archivo `bitacora_revisiones.txt` **dentro de la propia carpeta Inputs** (el script lo excluye a sí mismo, así como al archivo de estado interno `.vigilancia_state.json`, de la detección de cambios y del procesamiento — solo mira los archivos de insumo reales).
- Si la fecha del primer encabezado del `.txt` es de un día anterior (hora de Perú), borra el contenido viejo y reinicia la bitácora con la fecha actual.
- En cada ejecución agrega una línea: `Sin cambios en Inputs` o `CAMBIOS DETECTADOS (Archivos listos para procesar)`, según si hay archivos nuevos/modificados respecto a la última revisión.
- Este módulo **no genera el reporte**, solo registra el estado.

### Módulo B — Procesamiento condicional (`run_report.yml`)
- Se ejecuta automáticamente todos los días a las **17:00 UTC (12:00 PM hora de Perú)**.
- `DataaConsiderar2026` es un **archivo base fijo**: debe estar siempre presente en Inputs, pero su sola presencia no dispara el procesamiento y **nunca se archiva** — permanece en Inputs hasta que tú avises explícitamente que hay que reemplazarlo.
- El disparador real son los 3 insumos "de ronda": Segmentación, Capacitación y 9.- Estructura. Si ninguno de los 3 está presente, el workflow termina sin error y sin generar nada. Si falta alguno de los 3 (pero no todos), o si falta `DataaConsiderar2026`, el workflow falla para que lo notes.
- Si los 3 insumos de ronda están completos, procesa, sube el reporte final a Salidas y luego **mueve** (no copia) esos 3 archivos a `Historial/YYYY-MM-DD/` (fecha de Perú), dejando Inputs limpia salvo por la bitácora y `DataaConsiderar2026`.
- También puede lanzarse manualmente: pestaña **Actions** > **Ejecutar Reporte Malla Automatizado** > **Run workflow**.

Puedes ajustar los horarios de ambos cron en sus respectivos archivos `.yml` dentro de `.github/workflows/`.
