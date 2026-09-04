"""Codigo de Google Apps Script para el dashboard "Malla de Aprendizaje - Oslo".

Replica en Google Sheets las vistas del reporte "Oslo - Malla de Aprendizaje 2026.pbix"
(paginas "Oslo" y "Detalle_Oslo") a partir del mismo Excel que ya sube procesar_drive.py
a la carpeta de salida de Oslo en Google Drive (Reporte_Malla_Oslo_YYYY-MM-DD.xlsx, hoja "Ciclos").
No modifica el pipeline de reporte_malla_pv.py / procesar_drive.py: solo consume su salida.

CONFIGURACION (una sola vez, en el editor de Apps Script):
  1. Crear un proyecto de Apps Script (script.google.com > Nuevo proyecto) y pegar
     el contenido de APPS_SCRIPT_SOURCE en Code.gs.
  2. Extensiones > Servicios > agregar "Drive API" (servicio avanzado, version v2).
     Se usa para convertir el .xlsx subido por el pipeline a Google Sheets.
  3. Proyecto > Configuracion > Propiedades del script > agregar:
       OSLO_OUTPUT_FOLDER_ID       = mismo ID que el secreto GDRIVE_OUTPUT_FOLDER_ID_OSLO
                                     de run_report_oslo.yml (carpeta de salida en Drive)
       OSLO_DASHBOARD_FOLDER_ID    = (opcional) carpeta de Drive donde guardar el dashboard
  4. Ejecutar manualmente runOslo() una vez (autoriza permisos) y revisar el resultado.
  5. Ejecutar crearTriggerOslo() una vez para dejar el refresco diario automatico
     (13:00 hora de Peru, igual que el cron de run_report_oslo.yml).

SUPUESTOS al traducir el .pbix (su modelo de datos esta comprimido/no legible directamente,
asi que estos puntos se infirieron de los nombres de campo en Report/Layout):
  - "Status": el pbix promedia un campo numerico "Status" que no existe en el Excel origen
    (el Excel solo trae "%": '100%'/'50%'/'0%'). Aqui se deriva "Status" = 100/50/0 parseando "%".
  - Tarjeta "Primera fecha": en el pbix es MIN(Column1) sin nombre claro. Se interpreta como la
    fecha del reporte (se extrae del propio nombre del archivo Reporte_Malla_Oslo_YYYY-MM-DD.xlsx).
  - "Base 25" en el grafico de Representante: es la tecnica de paginacion del pbix para no
    saturar el grafico. Aqui se replica limitando el grafico a los primeros 25 representantes.
  - Se dejo fuera, a proposito, la pagina "Detalle_Oslo" (tabla dinamica Escuela x Ciclo x Curso)
    y la pagina "Inducciones" (usa otra fuente de datos, no la hoja "Ciclos"); se agregan despues
    si el resultado de este primer avance sirve.
"""

APPS_SCRIPT_SOURCE = r"""
function runOslo() {
  const props = PropertiesService.getScriptProperties();
  const outputFolderId = requireProp_(props, 'OSLO_OUTPUT_FOLDER_ID');

  const sourceFile = getLatestReportFile_(outputFolderId, 'Reporte_Malla_Oslo_');
  const convertedId = convertExcelToSheet_(sourceFile.getId());

  try {
    const sourceSs = SpreadsheetApp.openById(convertedId);
    const sourceSheet = sourceSs.getSheetByName('Ciclos');
    if (!sourceSheet) throw new Error('La hoja "Ciclos" no existe en ' + sourceFile.getName());

    const values = sourceSheet.getDataRange().getValues();
    const fechaReporte = extraerFechaDeNombre_(sourceFile.getName());

    const dash = getOrCreateDashboard_(props);
    const datosSheet = writeDatos_(dash, values);
    buildKpis_(dash, datosSheet, fechaReporte);
    buildPivots_(dash, datosSheet);
    buildChart_(dash, datosSheet);
    buildSlicers_(datosSheet);

    Logger.log('Dashboard Oslo actualizado: ' + dash.getUrl());
  } finally {
    // La copia convertida a Google Sheets es solo un paso intermedio de lectura.
    DriveApp.getFileById(convertedId).setTrashed(true);
  }
}

function crearTriggerOslo() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'runOslo'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });

  ScriptApp.newTrigger('runOslo')
    .timeBased()
    .everyDays(1)
    .atHour(13) // 1:00 PM hora de Peru, igual que el cron de run_report_oslo.yml
    .inTimezone('America/Lima')
    .create();
}

// ============================================================
// Lectura del Excel generado por el pipeline (procesar_drive.py)
// ============================================================

function requireProp_(props, key) {
  const value = props.getProperty(key);
  if (!value) throw new Error('Falta configurar la propiedad de script "' + key + '".');
  return value;
}

function getLatestReportFile_(folderId, prefix) {
  const folder = DriveApp.getFolderById(folderId);
  const it = folder.getFilesByType(MimeType.MICROSOFT_EXCEL);
  let latest = null;
  while (it.hasNext()) {
    const f = it.next();
    if (f.getName().indexOf(prefix) !== 0) continue;
    if (!latest || f.getDateCreated() > latest.getDateCreated()) latest = f;
  }
  if (!latest) throw new Error('No se encontro ningun "' + prefix + '*.xlsx" en la carpeta de salida.');
  return latest;
}

// Requiere el servicio avanzado "Drive API" (v2) habilitado en el proyecto.
function convertExcelToSheet_(fileId) {
  const copia = Drive.Files.copy({ mimeType: MimeType.GOOGLE_SHEETS }, fileId);
  return copia.id;
}

function extraerFechaDeNombre_(fileName) {
  const m = fileName.match(/(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : Utilities.formatDate(new Date(), 'America/Lima', 'yyyy-MM-dd');
}

// ============================================================
// Dashboard (hojas "Datos" y "Resumen")
// ============================================================

function getOrCreateDashboard_(props) {
  const existingId = props.getProperty('OSLO_DASHBOARD_SS_ID');
  if (existingId) {
    try {
      return SpreadsheetApp.openById(existingId);
    } catch (e) {
      // El archivo ya no existe (se borro manualmente): se crea uno nuevo abajo.
    }
  }

  const ss = SpreadsheetApp.create('Malla de Aprendizaje - Oslo (Dashboard)');
  props.setProperty('OSLO_DASHBOARD_SS_ID', ss.getId());

  const dashboardFolderId = props.getProperty('OSLO_DASHBOARD_FOLDER_ID');
  if (dashboardFolderId) {
    const file = DriveApp.getFileById(ss.getId());
    DriveApp.getFolderById(dashboardFolderId).addFile(file);
    DriveApp.getRootFolder().removeFile(file);
  }
  return ss;
}

function writeDatos_(dash, values) {
  let sheet = dash.getSheetByName('Datos');
  if (!sheet) {
    sheet = dash.insertSheet('Datos');
  } else {
    sheet.getSlicers().forEach(function (s) { s.remove(); });
    sheet.clear();
  }

  const header = values[0];
  const rows = values.slice(1);
  const pctIdx = header.indexOf('%');

  const headerConStatus = header.concat(['Status']);
  const rowsConStatus = rows.map(function (row) {
    const pct = pctIdx >= 0 ? (parseFloat(String(row[pctIdx]).replace('%', '')) || 0) : 0;
    return row.concat([pct]);
  });

  sheet.getRange(1, 1, 1, headerConStatus.length).setValues([headerConStatus]).setFontWeight('bold');
  if (rowsConStatus.length > 0) {
    sheet.getRange(2, 1, rowsConStatus.length, headerConStatus.length).setValues(rowsConStatus);
  }
  sheet.setFrozenRows(1);
  return sheet;
}

function columnaPorNombre_(header, nombre) {
  const idx = header.indexOf(nombre);
  if (idx === -1) throw new Error('No se encontro la columna "' + nombre + '" en la hoja Datos.');
  return idx;
}

function buildKpis_(dash, datosSheet, fechaReporte) {
  let sheet = dash.getSheetByName('Resumen');
  if (!sheet) {
    sheet = dash.insertSheet('Resumen');
  } else {
    sheet.getCharts().forEach(function (c) { sheet.removeChart(c); });
    sheet.getPivotTables().forEach(function (p) { p.remove(); });
    sheet.clear();
  }

  const header = datosSheet.getRange(1, 1, 1, datosSheet.getLastColumn()).getValues()[0];
  const lastRow = datosSheet.getLastRow();
  const numRows = Math.max(lastRow - 1, 0);

  const dniCol = columnaPorNombre_(header, 'DNI');
  const statusCol = columnaPorNombre_(header, 'Status');

  const dnis = numRows > 0 ? datosSheet.getRange(2, dniCol + 1, numRows, 1).getValues().flat() : [];
  const totalColaboradores = new Set(dnis.filter(function (v) { return v !== '' && v !== null; })).size;

  const statuses = numRows > 0 ? datosSheet.getRange(2, statusCol + 1, numRows, 1).getValues().flat() : [];
  const promedio = statuses.length > 0
    ? statuses.reduce(function (a, b) { return a + b; }, 0) / statuses.length
    : 0;

  sheet.getRange('A1').setValue('Cantidad de Colaboradores').setFontWeight('bold');
  sheet.getRange('A2').setValue(totalColaboradores).setFontSize(24);
  sheet.getRange('B1').setValue('Promedio de Avance').setFontWeight('bold');
  sheet.getRange('B2').setValue(promedio / 100).setNumberFormat('0%').setFontSize(24);
  sheet.getRange('C1').setValue('Fecha del Reporte').setFontWeight('bold');
  sheet.getRange('C2').setValue(fechaReporte).setFontSize(24);
}

function buildPivots_(dash, datosSheet) {
  const sheet = dash.getSheetByName('Resumen');
  const header = datosSheet.getRange(1, 1, 1, datosSheet.getLastColumn()).getValues()[0];
  const sourceRange = datosSheet.getRange(1, 1, datosSheet.getLastRow(), datosSheet.getLastColumn());

  const dniCol = columnaPorNombre_(header, 'DNI') + 1;
  const estadoCol = columnaPorNombre_(header, 'Estado') + 1;

  const pivotEscuela = sourceRange.createPivotTable(sheet.getRange('A5'));
  pivotEscuela.addRowGroup(columnaPorNombre_(header, 'Escuela') + 1);
  pivotEscuela.addColumnGroup(estadoCol);
  pivotEscuela.addPivotValue(dniCol, SpreadsheetApp.PivotTableSummarizeFunction.COUNTA);

  const pivotUbicacion = sourceRange.createPivotTable(sheet.getRange('A20'));
  pivotUbicacion.addRowGroup(columnaPorNombre_(header, 'Ubicación') + 1);
  pivotUbicacion.addColumnGroup(estadoCol);
  pivotUbicacion.addPivotValue(dniCol, SpreadsheetApp.PivotTableSummarizeFunction.COUNTA);
}

function buildChart_(dash, datosSheet) {
  const sheet = dash.getSheetByName('Resumen');
  const header = datosSheet.getRange(1, 1, 1, datosSheet.getLastColumn()).getValues()[0];
  const lastRow = datosSheet.getLastRow();
  const numRows = Math.max(lastRow - 1, 0);
  const data = numRows > 0 ? datosSheet.getRange(2, 1, numRows, datosSheet.getLastColumn()).getValues() : [];

  const repIdx = columnaPorNombre_(header, 'Representante');
  const estadoIdx = columnaPorNombre_(header, 'Estado');

  const estados = [];
  const porRepresentante = {};
  data.forEach(function (row) {
    const rep = row[repIdx] || 'Sin Representante';
    const estado = row[estadoIdx] || 'Sin Estado';
    if (estados.indexOf(estado) === -1) estados.push(estado);
    if (!porRepresentante[rep]) porRepresentante[rep] = {};
    porRepresentante[rep][estado] = (porRepresentante[rep][estado] || 0) + 1;
  });

  // Replica la paginacion "Base 25" del pbix: como mucho 25 representantes por grafico.
  const representantes = Object.keys(porRepresentante).slice(0, 25);

  const tabla = [['Representante'].concat(estados)];
  representantes.forEach(function (rep) {
    const fila = [rep];
    estados.forEach(function (estado) { fila.push(porRepresentante[rep][estado] || 0); });
    tabla.push(fila);
  });

  const startRow = 35;
  const range = sheet.getRange(startRow, 1, tabla.length, tabla[0].length);
  range.setValues(tabla);

  const chart = sheet.newChart()
    .setChartType(Charts.ChartType.COLUMN)
    .addRange(range)
    .setPosition(startRow, estados.length + 3, 0, 0)
    .setOption('title', 'Progreso por Representante')
    .setOption('isStacked', 'percent')
    .build();
  sheet.insertChart(chart);
}

function buildSlicers_(datosSheet) {
  const header = datosSheet.getRange(1, 1, 1, datosSheet.getLastColumn()).getValues()[0];
  const fullRange = datosSheet.getRange(1, 1, datosSheet.getLastRow(), datosSheet.getLastColumn());

  const campos = ['Estado', 'Escuela', 'Responsable', 'Ciclo', 'Nombre de Curso', 'Fecha de Ingreso'];
  campos.forEach(function (campo, i) {
    const col = header.indexOf(campo);
    if (col === -1) return;
    const slicer = datosSheet.insertSlicer(fullRange, 1, datosSheet.getLastColumn() + 2 + i * 3);
    slicer.setColumnFilterCriteria(col + 1, SpreadsheetApp.newFilterCriteria().build());
  });
}
"""

# Manifiesto de referencia: en el editor de Apps Script se genera solo al
# habilitar el servicio avanzado "Drive API" (paso 2 de la configuracion arriba).
# Se deja aqui solo para verificar que quedo declarado correctamente.
APPSSCRIPT_MANIFEST = r"""
{
  "timeZone": "America/Lima",
  "dependencies": {
    "enabledAdvancedServices": [
      {
        "userSymbol": "Drive",
        "serviceId": "drive",
        "version": "v2"
      }
    ]
  },
  "exceptionLogging": "STACKDRIVER",
  "runtimeVersion": "V8"
}
"""

if __name__ == '__main__':
    print(APPS_SCRIPT_SOURCE)
