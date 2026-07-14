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

La Cuenta de Servicio actúa como si fuera un usuario más. Para que pueda descargar y subir archivos, debes compartir tus carpetas de Google Drive con ella:

1. Abre el archivo `.json` que descargaste en el paso anterior y busca la línea que dice `"client_email"`. Verás un correo que termina en `@...gserviceaccount.com`. Copia esa dirección de correo.
2. Ve a Google Drive, busca la carpeta donde están tus archivos de entrada y **compártela con ese correo de cuenta de servicio** con permiso de **Lector**.
3. Busca la carpeta de Google Drive donde quieres que se guarde el reporte final generado y **compártela con ese mismo correo** con permiso de **Editor**.
4. Copia los **IDs de las carpetas** de la URL del navegador. 
   - La URL de una carpeta de Drive se ve así: `https://drive.google.com/drive/folders/1A2B3C4D5E6F7G8H9I0J`
   - El ID de esa carpeta es: `1A2B3C4D5E6F7G8H9I0J` (la última parte de la URL).
   - Guarda el ID de la carpeta de entrada y el ID de la carpeta de salida.

---

## Paso 3: Configurar los Secretos de GitHub (GitHub Secrets)

Para que GitHub Actions pueda usar estas credenciales sin exponerlas públicamente en el código:

1. Ve a tu repositorio en GitHub.
2. Haz clic en la pestaña **Settings** (Configuración).
3. En el menú lateral izquierdo, selecciona **Secrets and variables** > **Actions**.
4. Haz clic en **New repository secret** en la esquina superior derecha y añade los siguientes 3 secretos:

* **Nombre:** `GDRIVE_CREDENTIALS`
  * **Valor:** Copia y pega **todo el contenido** del archivo JSON de credenciales que descargaste en el Paso 1 (abre el archivo con cualquier editor de texto y copia todo desde `{` hasta `}`).
* **Nombre:** `GDRIVE_INPUT_FOLDER_ID`
  * **Valor:** `14IcQo4amCE6c39vT7lHT8_FAWoJjcbXX` (El ID de tu carpeta **Inputs**).
* **Nombre:** `GDRIVE_OUTPUT_FOLDER_ID`
  * **Valor:** `1VJWfPGJnjyLRv3cHJ-r5fWOOuGmJ6ykO` (El ID de tu carpeta **Outputs**).


---

## Paso 4: Cómo ejecutar la automatización

Una vez subidos los archivos al repositorio en GitHub:

1. Ve a la pestaña **Actions** en tu repositorio de GitHub.
2. En el menú izquierdo, selecciona **Ejecutar Reporte Malla Automatizado**.
3. Haz clic en el botón desplegable **Run workflow** a la derecha, selecciona la rama (usualmente `main`) y haz clic en el botón verde **Run workflow**.
4. El proceso iniciará de inmediato: se descargará los archivos de Drive, los cruzará y subirá el resultado Excel a la carpeta de salida que le indicaste.
5. También se ejecutará automáticamente a las 6:00 AM UTC todos los días de forma programada (puedes ajustar el cron en el archivo [.github/workflows/run_report.yml](file:///Users/rriveroa/Documents/Yeka/Kerly/input%20malla/.github/workflows/run_report.yml)).
