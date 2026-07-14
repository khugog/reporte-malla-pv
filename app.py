import streamlit as st
from reporte_malla_pv import generar_reporte_malla_pv

# --- Streamlit Interface ---
st.set_page_config(page_title="Reporte Malla Aprendizaje Plaza Vea", layout="wide")
st.title('Generador de Reporte Malla Aprendizaje - Plaza Vea')

st.write("Este reporte requiere que hayas cargado los archivos: Segmentación, Capacitación, 9.- Estructura y DataaConsiderar en el menú lateral.")

st.sidebar.header("Archivos de Entrada")
st.sidebar.write("Sube aquí todos los archivos necesarios para tu reporte.")
uploaded_files = st.sidebar.file_uploader(
    "Selecciona uno o más archivos", 
    type=["xlsx", "xls"], 
    accept_multiple_files=True
)

if st.button('Generar Reporte Malla PV', type="primary"):
    if uploaded_files:
        generar_reporte_malla_pv(uploaded_files)
    else:
        st.error("Por favor, sube los archivos requeridos en el panel lateral antes de generar el reporte.")
