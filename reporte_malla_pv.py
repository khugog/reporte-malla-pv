import streamlit as st
import pandas as pd
import numpy as np
import io
import os
from datetime import datetime

# ==========================================
# 0. CONFIGURACION POR MARCA/FORMATO
# ==========================================
# Cada marca tiene su propia hoja de cursos/ciclos y su propia hoja de
# responsables dentro de DataaConsiderar2026.xlsx, y su propio valor en la
# columna 'Formato' de esa hoja de responsables (usado para filtrar el
# reporte final a solo esa marca en procesamiento_ciclos).
FORMATOS_CONFIG = {
    'Makro': {
        'sheet_cursos': 'Makro',
        'sheet_jefes': 'Jefe- Makro',
        'valor_formato': 'Makro',
        'nombre_reporte': 'Makro',
        # Makro ya no entrega Estructura + Capacitación por separado: entrega un
        # solo archivo "employees.xlsx" que trae ambos datos combinados.
        'usa_employees': True,
    },
    'PlazaVea': {
        'sheet_cursos': 'plazaVea',
        'sheet_jefes': 'Jefes- plazavea',
        'valor_formato': 'Plaza Vea',
        'nombre_reporte': 'PlazaVea',
        # Igual que Makro: ya no entrega Estructura + Capacitación por separado,
        # entrega un solo archivo "employees.xlsx" con ambos datos combinados.
        'usa_employees': True,
    },
}

# ==========================================
# 1. FUNCIONES UTILITARIAS
# ==========================================

def Buscar_Archivos_Memoria_MallaPv(uploaded_files):
    file_segmentacion = None
    file_capacitacion = None
    file_estructura = None
    file_employees = None
    file_data = None

    for file in uploaded_files:
        name = file.name.lower()
        if name.startswith('segment'):
            file_segmentacion = file
        elif name.startswith('employees'):
            file_employees = file
        elif name.startswith('capacita'):
            file_capacitacion = file
        elif name.startswith('9.- estructura'):
            file_estructura = file
        elif name.startswith('dataaconsiderar'):
            file_data = file

    return file_segmentacion, file_capacitacion, file_estructura, file_employees, file_data

def corregir_palabras_area(df, columna='Área'):
    correcciones = {
        'Almacen': 'Almacén',
        'Administracion': 'Administración',
        'Panaderia': 'Panadería',
        'Pasteleria': 'Pastelería',
        'Recepcion': 'Recepción',
    }
    for palabra, correccion in correcciones.items():
        df[columna] = df[columna].str.replace(palabra, correccion, case=False, regex=True)
    return df

# ==========================================
# 2. FUNCIONES DE EXTRACCIÓN Y LIMPIEZA INICIAL
# ==========================================

def procesar_segmentacion(file_obj):
    file_obj.seek(0)
    df = pd.read_excel(file_obj, dtype={'Documento': str})
    df = df[df['ESTADO DEL CURSO'].astype(str).str.lower() == 'activo']
    # El export de Segmentación de Makro no trae 'FINALIZACIÓN DEL CURSO': trae
    # 'ULTIMA EVALUACIÓN' en su lugar. Se normaliza al nombre que usa el resto del
    # pipeline para no tener que ramificar la lógica más adelante.
    col_fecha_fin = 'FINALIZACIÓN DEL CURSO' if 'FINALIZACIÓN DEL CURSO' in df.columns else 'ULTIMA EVALUACIÓN'
    df['FINALIZACIÓN DEL CURSO'] = pd.to_datetime(df[col_fecha_fin], errors='coerce')
    return df

def procesar_capacitaciones(file_obj):
    file_obj.seek(0)
    # Detectar dinámicamente la fila de cabecera buscando una columna clave
    df_temp = pd.read_excel(file_obj, header=None, nrows=10)
    header_row = 0
    for idx, row in df_temp.iterrows():
        row_vals = [str(x).strip().lower() for x in row.dropna()]
        if any('fecha de cese' in val or 'cese' == val for val in row_vals) or \
           any('documento de identidad' in val for val in row_vals):
            header_row = idx
            break

    file_obj.seek(0)
    df = pd.read_excel(file_obj, 
                       dtype={'Número de documento de identidad principal': str, 'Número de persona': str}, 
                       skiprows=header_row)
    
    # Limpiar posibles filas vacías o de resumen al final
    df = df[df['Número de persona'].notna() & df['Número de documento de identidad principal'].notna()]
    
    df['type'] = np.where(df['Fecha de cese'].isna() | (df['Fecha de cese'] == ''), 0, 1)
    df = df.sort_values(by=["Número de persona", "type"]).drop_duplicates(subset=["Número de persona"], keep="first")

    for col in ['Fecha de nacimiento de persona', 'Fecha de inicio de relación laboral', 'Fecha de cese']:
        df[col] = pd.to_datetime(df[col], errors='coerce')

    return df

def procesar_estructura(file_obj):
    file_obj.seek(0)
    # Detectar dinámicamente la fila de cabecera buscando una columna clave
    df_temp = pd.read_excel(file_obj, header=None, nrows=10)
    header_row = 0
    for idx, row in df_temp.iterrows():
        row_vals = [str(x).strip().lower() for x in row.dropna()]
        if any('unidad de negocio' in val for val in row_vals) or \
           any('documento de identidad' in val for val in row_vals):
            header_row = idx
            break

    file_obj.seek(0)
    unidades_negocio = ["ADMINISTRACIÓN FOOD REGIONAL S.A.C.", "COMPAÑIA FOOD RETAIL S.A.C.", "PLAZA VEA ORIENTE S.A.C.", "MAKRO SUPERMAYORISTA S.A."]
    columnas = ["Número de documento de identidad principal", "Nombre de unidad de negocio", "Nombre del departamento", 
                "Posición_Nombre", "Número de persona", "Nombre Completo", "Fecha de inicio de relación laboral",
                "ID Ofiplan", "Fecha de nacimiento de persona", "Nombre de ubicación"]

    df = pd.read_excel(file_obj, 
                       dtype={'Número de documento de identidad principal': str, 'ID Ofiplan': str, "Número de persona": str}, 
                       skiprows=header_row)
    df = df.rename(columns={'Nombre': 'Nombre Completo'})
    
    # Limpiar posibles filas vacías o de resumen al final
    df = df[df['Número de documento de identidad principal'].notna()]
    
    df = df[df["Nombre de unidad de negocio"].isin(unidades_negocio)][columnas]

    for col in ["Nombre Completo", "Posición_Nombre", "Nombre de ubicación"]:
        df[col] = df[col].astype(str).str.title()

    for col in ['Fecha de nacimiento de persona', 'Fecha de inicio de relación laboral']:
        df[col] = pd.to_datetime(df[col], errors='coerce')

    return df

def combinar_estructura_y_capacitacion(df_estructura, df_capacitacion):
    """Combina Estructura + Capacitación en un solo DataFrame 'df_personal',
    replicando exactamente el cruce por DNI que antes hacía procesamiento_reporte
    (Fecha de cese viene de Capacitación, todo lo demás de Estructura). Solo se
    usa para las marcas que todavía entregan estos 2 archivos por separado."""
    df_cap_idx = df_capacitacion.drop_duplicates(
        subset=['Número de documento de identidad principal'], keep='last'
    ).set_index('Número de documento de identidad principal')

    df_personal = df_estructura.copy()
    df_personal['Fecha de cese'] = df_personal['Número de documento de identidad principal'].map(
        df_cap_idx['Fecha de cese']
    )
    return df_personal

def procesar_employees(file_obj):
    """Reemplaza a Estructura + Capacitación para las marcas cuyo sistema de
    origen ya entrega un solo archivo "employees.xlsx" (hoja 'Empleados') con
    los datos de personal y la fecha de cese combinados."""
    file_obj.seek(0)
    df = pd.read_excel(file_obj, sheet_name='Empleados',
                       dtype={'DNI': str, 'Número de persona': str, 'Número de empleado': str})

    # Limpiar posibles filas vacías o de resumen al final
    df = df[df['DNI'].notna()]

    # El nombre viene partido en 4 columnas en vez de una sola "Nombre" como en
    # Estructura. Estructura entregaba "Apellidos, Nombres" (formato que ya usa
    # el resto del reporte); se arma aqui igual para no cambiar lo que ve el
    # usuario en la columna "Nombre del colaborador".
    for col in ['Primer nombre', 'Segundo nombre', 'Primer apellido', 'Segundo apellido']:
        df[col] = df[col].fillna('').astype(str).str.strip()
    apellidos = (df['Primer apellido'] + ' ' + df['Segundo apellido']).str.replace(r'\s+', ' ', regex=True).str.strip()
    nombres = (df['Primer nombre'] + ' ' + df['Segundo nombre']).str.replace(r'\s+', ' ', regex=True).str.strip()
    df['Nombre Completo'] = (apellidos + ', ' + nombres).str.strip(', ').str.strip()

    df = df.rename(columns={
        'DNI': 'Número de documento de identidad principal',
        'Unidad de negocio': 'Nombre de unidad de negocio',
        'Ubicación': 'Nombre de ubicación',
        'Departamento': 'Nombre del departamento',
        'Puesto': 'Posición_Nombre',
        'Fecha de ingreso': 'Fecha de inicio de relación laboral',
    })

    unidades_negocio = ["ADMINISTRACIÓN FOOD REGIONAL S.A.C.", "COMPAÑIA FOOD RETAIL S.A.C.", "PLAZA VEA ORIENTE S.A.C.", "MAKRO SUPERMAYORISTA S.A."]
    df = df[df["Nombre de unidad de negocio"].isin(unidades_negocio)]

    for col in ["Nombre Completo", "Posición_Nombre", "Nombre de ubicación"]:
        df[col] = df[col].astype(str).str.title()

    df['Fecha de inicio de relación laboral'] = pd.to_datetime(df['Fecha de inicio de relación laboral'], errors='coerce')
    df['Fecha de cese'] = pd.to_datetime(df['Fecha de cese'], errors='coerce')

    # Igual que hacía Capacitación: si una persona aparece dos veces (ej. reingreso),
    # se prioriza el registro activo (sin fecha de cese) sobre el cesado.
    df['type'] = np.where(df['Fecha de cese'].isna(), 0, 1)
    df = df.sort_values(by=['Número de documento de identidad principal', 'type']) \
           .drop_duplicates(subset=['Número de documento de identidad principal'], keep='first') \
           .drop(columns=['type'])

    columnas = ["Número de documento de identidad principal", "Nombre de unidad de negocio", "Nombre del departamento",
                "Posición_Nombre", "Número de persona", "Nombre Completo", "Fecha de inicio de relación laboral",
                "Nombre de ubicación", "Fecha de cese"]

    return df[columnas]

# ==========================================
# 3. PROCESAMIENTO CENTRAL
# ==========================================

def procesamiento_reporte(df_personal, df_segmentacion, file_data, formato='Makro'):
    config = FORMATOS_CONFIG[formato]

    file_data.seek(0)
    # Cursos: mapeo de cursos/ciclos propio de cada marca (hoja distinta por marca)
    df_cursos = pd.read_excel(file_data, sheet_name=config['sheet_cursos'])
    df_cursos = df_cursos.drop_duplicates(subset=['Nombre de Curso'], keep='last').set_index('Nombre de Curso')
    niveles_interes = df_cursos['Ciclo'].dropna().unique().tolist()

    file_data.seek(0)
    # Retiros (Base histórica)
    df_retiros = pd.read_excel(file_data, sheet_name='Retiros', dtype={'DNI': str})
    df_retiros = df_retiros.drop_duplicates(subset=['DNI'], keep='last').set_index('DNI')

    file_data.seek(0)
    # Jefes: responsables por ubicación, hoja distinta por marca. La hoja de
    # Makro no trae columna 'Lima/provincia' (a diferencia de plazaVea), se
    # maneja mas abajo.
    df_jefes = pd.read_excel(file_data, sheet_name=config['sheet_jefes'])
    df_jefes['Ubicación Estructura'] = df_jefes['Ubicación Estructura'].astype(str).str.upper()
    df_jefes = df_jefes.drop_duplicates(subset=['Ubicación Estructura'], keep='last').set_index('Ubicación Estructura')

    # Personal (antes "Estructura" + "Capacitación" cruzadas por DNI; ahora puede
    # venir ya combinado de procesar_employees(), o combinado a mano con
    # combinar_estructura_y_capacitacion() para las marcas que aún usan 2 archivos)
    df_personal['Nombre de ubicación'] = df_personal['Nombre de ubicación'].astype(str).str.upper()
    df_personal = df_personal.drop_duplicates(subset=['Número de documento de identidad principal'], keep='last')
    df_personal = df_personal.set_index('Número de documento de identidad principal')

    # Construcción de base nueva
    df_nuevo = pd.DataFrame()
    df_nuevo['DNI'] = df_segmentacion['Documento']
    df_nuevo['Escuela'] = df_segmentacion['ESCUELA']
    df_nuevo['Nombre del Curso'] = df_segmentacion['CURSO']
    df_nuevo['Estado'] = df_segmentacion['RESULTADO CURSO']
    df_nuevo['Nota'] = df_segmentacion['PROMEDIO']
    df_nuevo['Fecha de Finalización'] = df_segmentacion['FINALIZACIÓN DEL CURSO'] 
    df_nuevo['Modalidad'] = 'online'

    df_nuevo['Nuevo Nombre de curso'] = df_nuevo['Nombre del Curso'].map(df_cursos['Nuevo Nombre de curso'])
    df_nuevo['Tipo de Curso'] = df_nuevo['Nombre del Curso'].map(df_cursos['Escuela'])
    df_nuevo['Nivel'] = df_nuevo['Nombre del Curso'].map(df_cursos['Ciclo'])

    df_nuevo['Ubicación'] = df_nuevo['DNI'].map(df_personal['Nombre de ubicación']).fillna('NA')
    df_nuevo['Número de la persona'] = df_nuevo['DNI'].map(df_personal['Número de persona']).fillna('NA')
    df_nuevo['Nombre del Colaborador'] = df_nuevo['DNI'].map(df_personal['Nombre Completo']).fillna('NA')
    df_nuevo['Departamento'] = df_nuevo['DNI'].map(df_personal['Nombre del departamento']).fillna('NA')
    df_nuevo['Posición'] = df_nuevo['DNI'].map(df_personal['Posición_Nombre']).fillna('NA')
    df_nuevo['Empresa'] = df_nuevo['DNI'].map(df_personal['Nombre de unidad de negocio']).fillna('NA')
    df_nuevo['Fecha de ingreso'] = df_nuevo['DNI'].map(df_personal['Fecha de inicio de relación laboral'])
    # 'Fecha de nacimiento de persona' solo existe cuando el personal viene de
    # Estructura (no la trae employees.xlsx); no se usa en el reporte final
    # (se descarta antes de armar la hoja "Ciclos"), así que es seguro omitirla.
    if 'Fecha de nacimiento de persona' in df_personal.columns:
        df_nuevo['Fecha De nacimiento'] = df_nuevo['DNI'].map(df_personal['Fecha de nacimiento de persona'])
    df_nuevo['Fecha de cese'] = df_nuevo['DNI'].map(df_personal['Fecha de cese'])

    # Asignación inicial de Retiros desde el maestro
    df_nuevo['Retiros'] = df_nuevo['DNI'].map(df_retiros['Código']).fillna(0).astype(int)
    
    if 'Lima/provincia' in df_jefes.columns:
        df_nuevo['Lima/provincia'] = df_nuevo['Ubicación'].map(df_jefes['Lima/provincia']).fillna('NA')
    else:
        df_nuevo['Lima/provincia'] = 'NA'
    df_nuevo['Ubicación_1'] = df_nuevo['Ubicación'].map(df_jefes['Ubicación formato indicado'])
    df_nuevo['Formato'] = df_nuevo['Ubicación'].map(df_jefes['Formato']).fillna('NA')
    df_nuevo['L/P'] = df_nuevo['Ubicación'].map(df_jefes['Lugar']).fillna('NA')
    df_nuevo['Responsable'] = df_nuevo['Ubicación'].map(df_jefes['Responsable']).fillna('NA')
    df_nuevo['Representante'] = df_nuevo['Ubicación'].map(df_jefes['Representante']).fillna('NA')

    # Limpieza de fechas
    for col in ['Fecha de Inicio', 'Fecha de Finalización', 'Fecha de ingreso', 'Fecha de cese', 'Fecha De nacimiento']:
        if col in df_nuevo.columns:
            df_nuevo[col] = pd.to_datetime(df_nuevo[col], errors='coerce')

    # Reordenar columnas
    columnas_orden = ['DNI', 'Nivel', 'Formato', 'Ubicación', 'Ubicación_1', 'Escuela', 'Nombre del Curso', 
                      'Nuevo Nombre de curso', 'Tipo de Curso', 'Modalidad', 'Fecha de Finalización', 
                      'Número de la persona', 'Nombre del Colaborador', 'Departamento', 'Posición', 'Estado', 
                      'Nota', 'Lima/provincia', 'L/P', 'Responsable', 'Representante', 'Empresa', 
                      'Fecha de ingreso', 'Fecha de cese', 'Fecha De nacimiento', 'Retiros']
    
    columnas_finales = [c for c in columnas_orden if c in df_nuevo.columns]
    
    return df_nuevo[columnas_finales], niveles_interes

# ==========================================
# 4. PIPELINE DE FILTROS MODULARES
# ==========================================

def marcar_formato_invalido(df):
    df.loc[df['Formato'] == 'NA', 'Retiros'] = 1
    return df

def marcar_posicion_retiro(df):
    posiciones_retiro = [ 'Cajero 5x2 D', 'Cajero D', 'Representante De Servicio 5x2 D', 'Representante De Servicio D',
                         'Cajero 5X2 Campaña', 'Multifuncional 5X2 Campaña', 'Multifuncional Campaña', 
                         'Multifuncional 5X2 1Er Turno Campaña', 'Multifuncional 5X2 2Do Turno Campaña', 
                         'Multifuncional 5x2 Campaña', 'Cajero 5x2 Campaña', 'Multifuncional 5x2 1er Turno Campaña', 
                         'Multifuncional 5x2 2do Turno Campaña', 'Multifuncional Peak Campaña']
    if 'Posición' in df.columns:
        df.loc[df['Posición'].astype(str).str.title().isin([p.title() for p in posiciones_retiro]), 'Retiros'] = 1
    return df

def marcar_personal_inactivo(df):
    if 'Fecha de cese' in df.columns:
        df['Fecha de cese'] = pd.to_datetime(df['Fecha de cese'], errors='coerce')
        df.loc[pd.notna(df['Fecha de cese']), 'Retiros'] = 1
    return df

def marcar_ubicacion_central(df):
    df.loc[df['Ubicación'] == 'Fret Administracion Central', 'Retiros'] = 1
    return df

def ejecutar_limpieza_final_retiros(df):
    return df[df['Retiros'] == 0].copy()

def aplicar_filtros(df, lista_filtros):
    for filtro in lista_filtros:
        df = filtro(df)
    return df

# ==========================================
# 5. CREACIÓN DE BASES FINALES
# ==========================================

def procesar_base_limpia(df_original, filtros):
    df_filtrado = aplicar_filtros(df_original, filtros)
    
    deptos = df_filtrado['Departamento'].fillna('').astype(str)
    partes = deptos.str.split('-')
    ultima_parte = partes.str[-1].str.strip()
    cantidad_guiones = deptos.str.count('-')

    cond_virtual = ultima_parte.str.lower().str.contains('commerce virtual', na=False)
    cond_commerce = ultima_parte.str.lower().str.contains('commerce', na=False) & ~cond_virtual

    condiciones = [
        (cantidad_guiones > 1) & cond_virtual,
        (cantidad_guiones > 1) & cond_commerce,
        (cantidad_guiones > 1)
    ]
    opciones = ['E-Commerce Virtual', 'E-Commerce', ultima_parte]
    df_filtrado['Área'] = np.select(condiciones, opciones, default='Mantenimiento')
    
    df_filtrado['Área'] = df_filtrado['Área'].str.title()
    df_filtrado = corregir_palabras_area(df_filtrado, 'Área')

    df_filtrado.insert(0, 'Key', df_filtrado['DNI'].astype(str) + df_filtrado['Nombre del Curso'].astype(str))
    
    return df_filtrado

def procesamiento_ciclos(df_limpia, niveles_interes, formato='Makro'):
    valor_formato = FORMATOS_CONFIG[formato]['valor_formato']
    df_marca = df_limpia[df_limpia['Formato'] == valor_formato]
    df_ciclos = df_marca[df_marca['Nivel'].isin(niveles_interes)].copy()

    columnas_map = {
        'Nivel': 'Ciclo', 'Nuevo Nombre de curso': 'Nombre de Curso', 'Tipo de Curso': 'Tipo de curso',
        'Fecha de ingreso': 'Fecha de Ingreso', 'Nombre del Colaborador': 'Nombre del colaborador',
        'Fecha de Finalización': 'Fecha de Cumplimiento'
    }
    df_ciclos = df_ciclos.rename(columns=columnas_map)
    df_ciclos['%'] = np.select(
        [df_ciclos['Estado'] == 'Aprobado', df_ciclos['Estado'] == 'Desarrollo'],
        ['100%', '50%'],
        default='0%'
    )

    cabecera_final = ['Ciclo', 'Nombre de Curso', 'Tipo de curso', 'Fecha de Ingreso', 'DNI', 'Nombre del colaborador',
                      'Fecha de Cumplimiento', 'Nota', 'Estado', '%', 'Ubicación', 'Formato', 'Lima/provincia', 'Área', 'Posición',
                      'Responsable', 'Representante']
    
    columnas_existentes = [c for c in cabecera_final if c in df_ciclos.columns]
    df_ciclos = df_ciclos[columnas_existentes]

    return df_ciclos


# ==========================================
# 6. FUNCIÓN DE ENRUTAMIENTO (STREAMLIT)
# ==========================================

def generar_reporte_malla_pv(uploaded_files, formato='Makro'):
    config = FORMATOS_CONFIG[formato]
    usa_employees = config.get('usa_employees', False)
    nombre_reporte = config['nombre_reporte']
    st.info(f"Iniciando procesamiento de datos para el Reporte Malla Aprendizaje {nombre_reporte}...")
    with st.status("Procesando Reporte Malla Aprendizaje...", expanded=True) as status:
        st.write("Buscando Archivos Cargados...")
        file_segmentacion, file_capacitacion, file_estructura, file_employees, file_data = Buscar_Archivos_Memoria_MallaPv(uploaded_files)

        if usa_employees:
            requeridos = [file_segmentacion, file_employees, file_data]
        else:
            requeridos = [file_segmentacion, file_capacitacion, file_estructura, file_data]

        if not all(requeridos):
            faltantes = []
            if not file_segmentacion: faltantes.append("Segmentación")
            if usa_employees:
                if not file_employees: faltantes.append("Employees")
            else:
                if not file_capacitacion: faltantes.append("Capacitación")
                if not file_estructura: faltantes.append("9.- Estructura")
            if not file_data: faltantes.append("Data a Considerar")

            status.update(label="Faltan archivos esenciales", state="error", expanded=True)
            st.error(f"Por favor asegúrate de haber cargado los archivos base. Faltan: {', '.join(faltantes)}")
            return

        try:
            if usa_employees:
                st.write("Cargando Employees...")
                df_personal = procesar_employees(file_employees)
            else:
                st.write("Cargando Estructura...")
                df_est = procesar_estructura(file_estructura)

                st.write("Cargando Capacitación...")
                df_cap = procesar_capacitaciones(file_capacitacion)
                df_personal = combinar_estructura_y_capacitacion(df_est, df_cap)

            st.write("Cargando Segmentación...")
            df_seg = procesar_segmentacion(file_segmentacion)

            st.write("Procesando cruce de información...")
            df_reporte, niveles_interes = procesamiento_reporte(df_personal, df_seg, file_data, formato=formato)

            st.write("Aplicando limpieza y filtros...")
            filtros_a_aplicar = [
                marcar_formato_invalido,
                marcar_posicion_retiro,
                marcar_personal_inactivo,
                marcar_ubicacion_central,
                ejecutar_limpieza_final_retiros
            ]
            df_base_limpia = procesar_base_limpia(df_reporte, filtros_a_aplicar)

            st.write("Procesando formato Ciclos...")
            df_ciclos = procesamiento_ciclos(df_base_limpia, niveles_interes, formato=formato)

            st.write("Generando archivo Excel en memoria...")
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # El usuario requirió generar solo la hoja Ciclos
                df_ciclos.to_excel(writer, index=False, sheet_name='Ciclos')
            
            excel_data = output.getvalue()
            status.update(label="Proceso Malla Aprendizaje Completado", state="complete", expanded=False)
            
            today = datetime.today().strftime('%Y-%m-%d')
            st.download_button(
                label=f"Descargar Reporte Malla Aprendizaje {nombre_reporte}",
                data=excel_data,
                file_name=f"Reporte_Malla_{nombre_reporte}_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
            
        except Exception as e:
            status.update(label="Error durante el procesamiento", state="error", expanded=True)
            st.error(f"Ocurrió un error en la ejecución: {str(e)}")
