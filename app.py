#!/usr/bin/env python3
"""
INVIMA Actas Platform - Pilot Version
Full-text search across 1,750 regulatory actas (1996-2025)

Author: Claude
Date: 2025-11-28
Version: 2.5 Pilot (Streamlit Cloud)

Note: This is a pilot version without PDF download functionality.
Full version with PDF downloads available at production deployment.
"""

import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import pandas as pd
import altair as alt
from pathlib import Path
import re
from typing import List, Tuple, Dict, Optional, Any
import time

# --- Constants & Config ---
APP_DIR = Path(__file__).resolve().parent
PRIMARY_COLOR = "#6366f1"  # Indigo 500
ACCENT_COLOR = "#06b6d4"   # Cyan 500
BG_COLOR = "#0f172a"       # Slate 900

st.set_page_config(
    page_title="Explorador de Actas CR - INVIMA (Piloto)",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://www.andi.com.co',
        'About': "Sistema de Consulta de Actas de la Comisión Revisora del INVIMA - Versión Piloto."
    }
)

# --- Database & Data Loading ---

@st.cache_resource
def get_db_connection():
    """Get cached database connection"""
    db_path = APP_DIR / "data" / "actas_search.db"
    try:
        return sqlite3.connect(str(db_path), check_same_thread=False)
    except sqlite3.OperationalError as e:
        st.error(f"Error connecting to database: {e}")
        st.stop()

@st.cache_data(ttl=3600)
def get_statistics():
    """Get database statistics - Optimized"""
    conn = get_db_connection()
    cursor = conn.cursor()
    stats = {}

    cursor.execute("SELECT COUNT(*) FROM actas_metadata")
    stats['total'] = cursor.fetchone()[0]

    cursor.execute('SELECT MIN(year), MAX(year) FROM actas_metadata WHERE year IS NOT NULL')
    stats['year_range'] = cursor.fetchone()

    cursor.execute("SELECT DISTINCT sala FROM actas_metadata WHERE sala IS NOT NULL ORDER BY sala")
    stats['salas'] = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT year FROM actas_metadata WHERE year IS NOT NULL ORDER BY year DESC")
    stats['years'] = [str(row[0]) for row in cursor.fetchall()]

    stats['sala_names'] = {
        'CR': 'Comisión Revisora',
        'Conjunta': 'Sesión Conjunta',
        'SEM': 'Sala Especializada de Medicamentos',
        'SEMH': 'Sala Especializada de Medicamentos Homeopáticos',
        'SEMNNIMB': 'Sala Especializada de Medicamentos con Nuevas Moléculas',
        'SEMPB': 'Sala Especializada de Medicamentos y Productos Biológicos',
        'SEPFSD': 'Sala Especializada de Productos Fitoterapéuticos'
    }
    return stats

@st.cache_data
def load_text(fp: str) -> str:
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""

def get_acta_content(acta_id: str) -> Tuple[Optional[str], Dict]:
    """Get full content of an acta"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT file_path, sala, year, acta_number
        FROM actas_metadata
        WHERE acta_id = ?
    ''', (acta_id,))
    result = cursor.fetchone()

    if not result:
        return None, {}

    file_path, sala, year, acta_number = result

    metadata = {
        'sala': sala,
        'year': year,
        'acta_number': acta_number,
        'file_path': str(APP_DIR / file_path) if not Path(file_path).is_absolute() else file_path
    }

    content = load_text(metadata['file_path'])
    return content, metadata

def get_query_params() -> Dict[str, Any]:
    """Compatibility helper for Streamlit query params."""
    try:
        return dict(st.query_params)
    except AttributeError:
        return st.experimental_get_query_params()

def set_query_params(params: Dict[str, Any]):
    """Compatibility helper to update query params."""
    try:
        st.query_params = params
    except AttributeError:
        st.experimental_set_query_params(**params)

# --- Search Logic ---

def build_fts_query(user_input: str) -> str:
    """Build a robust FTS5 query."""
    q = (user_input or "").strip()
    if not q:
        return ""

    if any(tok in q for tok in ["\"", " NEAR ", " AND ", " OR "]):
        return q

    tokens = [t for t in re.split(r"\s+", q) if t]
    return " AND ".join(f'"{t}"*' for t in tokens)

def get_trend_data(query: str, filters: Dict) -> pd.DataFrame:
    """Get count of matches per year for the trend chart."""
    conn = get_db_connection()

    where_clauses = []
    params = []

    if query:
        fts_query = build_fts_query(query)
        if fts_query:
            where_clauses.append("actas_fts MATCH ?")
            params.append(fts_query)

    if filters.get('sala') and filters['sala'] != "Todas":
        where_clauses.append("m.sala = ?")
        params.append(filters['sala'])

    if filters.get('year_from') and filters['year_from'] != "Todos":
        where_clauses.append("m.year >= ?")
        params.append(int(filters['year_from']))

    if filters.get('year_to') and filters['year_to'] != "Todos":
        where_clauses.append("m.year <= ?")
        params.append(int(filters['year_to']))

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    sql = f"""
        SELECT m.year, COUNT(*) as count
        FROM actas_fts
        JOIN actas_metadata m ON actas_fts.acta_id = m.acta_id
        WHERE {where_sql}
        GROUP BY m.year
        ORDER BY m.year
    """

    try:
        return pd.read_sql_query(sql, conn, params=params)
    except Exception:
        return pd.DataFrame(columns=['year', 'count'])

def search_actas(query: str, filters: Dict, limit: int = 10, offset: int = 0) -> Tuple[List[Tuple], int]:
    """Search actas using FTS5."""
    conn = get_db_connection()
    cursor = conn.cursor()

    where_clauses = []
    params = []

    if query:
        fts_query = build_fts_query(query)
        if fts_query:
            where_clauses.append("actas_fts MATCH ?")
            params.append(fts_query)

    if filters.get('sala') and filters['sala'] != "Todas":
        where_clauses.append("m.sala = ?")
        params.append(filters['sala'])

    if filters.get('year_from') and filters['year_from'] != "Todos":
        where_clauses.append("m.year >= ?")
        params.append(int(filters['year_from']))

    if filters.get('year_to') and filters['year_to'] != "Todos":
        where_clauses.append("m.year <= ?")
        params.append(int(filters['year_to']))

    if filters.get('acta_number'):
        where_clauses.append("m.acta_number = ?")
        params.append(filters['acta_number'])

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Count
    count_sql = f"""
        SELECT COUNT(*)
        FROM actas_fts
        JOIN actas_metadata m ON actas_fts.acta_id = m.acta_id
        WHERE {where_sql}
    """

    # Sort
    sort_map = {
        "rank": "bm25(actas_fts)",
        "year_desc": "m.year DESC, m.acta_number DESC",
        "year_asc": "m.year ASC, m.acta_number ASC",
        "sala": "m.sala, m.year DESC"
    }
    order_by = sort_map.get(filters.get('sort_by', 'rank'), "bm25(actas_fts)")

    if not query:
        order_by = "m.year DESC, m.acta_number DESC"

    # List
    list_sql = f"""
        SELECT m.acta_id, snippet(actas_fts, -1, '<mark>', '</mark>', '...', 60),
               m.file_path, m.sala, m.year, m.acta_number
        FROM actas_fts
        JOIN actas_metadata m ON actas_fts.acta_id = m.acta_id
        WHERE {where_sql}
        ORDER BY {order_by} LIMIT ? OFFSET ?
    """

    try:
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        cursor.execute(list_sql, params + [limit, offset])
        results = cursor.fetchall()
        return results, total
    except sqlite3.OperationalError:
        return [], 0

def search_decisions(query: str, filters: Dict, limit: int = 50, offset: int = 0) -> Tuple[List[Dict], int]:
    """Search decisions."""
    conn = get_db_connection()
    cursor = conn.cursor()

    if query and query.strip():
        base_sql = """
            FROM decisions_fts f
            JOIN decisions d ON f.rowid = d.rowid
            LEFT JOIN actas_metadata a ON d.acta_id = a.acta_id
            WHERE decisions_fts MATCH ?
        """
        params = [query.strip()]
    else:
        base_sql = """
            FROM decisions d
            LEFT JOIN actas_metadata a ON d.acta_id = a.acta_id
            WHERE 1=1
        """
        params = []

    if filters.get('outcome') and filters['outcome'] != "Todos":
        outcome_map = {
            "Aprobada": "aprobada", "No Recomendada": "no_recomendada",
            "Aplazada": "aplazada", "No Aplica": "no_aplica", "Otro": "otro"
        }
        base_sql += " AND d.decision_outcome = ?"
        params.append(outcome_map.get(filters['outcome'], "otro"))

    if filters.get('year') and filters['year'] != "Todos":
        base_sql += " AND d.year = ?"
        params.append(int(filters['year']))

    if filters.get('request_type') and filters['request_type'] != "Todos":
        type_map = {"Exclusión": "exclusion", "Inclusión": "inclusion", "Otro": "otro"}
        base_sql += " AND d.request_type = ?"
        params.append(type_map.get(filters['request_type'], "otro"))

    if filters.get('sala') and filters['sala'] != "Todos":
        base_sql += " AND d.sala = ?"
        params.append(filters['sala'])

    cursor.execute(f"SELECT COUNT(*) {base_sql}", params)
    total = cursor.fetchone()[0]

    select_sql = f"""
        SELECT d.decision_id, d.acta_id, d.sala, d.year, d.agenda_path,
               d.product_name, d.radicados, d.decision_date, d.company,
               d.request_type, d.request_summary, d.decision_outcome,
               d.decision_summary, d.normas_farmacologicas, a.acta_number
        {base_sql}
        LIMIT ? OFFSET ?
    """
    cursor.execute(select_sql, params + [limit, offset])

    results = []
    for row in cursor.fetchall():
        results.append({
            'decision_id': row[0], 'acta_id': row[1], 'sala': row[2], 'year': row[3],
            'agenda_path': row[4], 'product_name': row[5], 'radicados': row[6],
            'decision_date': row[7], 'company': row[8], 'request_type': row[9],
            'request_summary': row[10], 'decision_outcome': row[11],
            'decision_summary': row[12], 'normas_farmacologicas': row[13],
            'acta_number': row[14]
        })

    return results, total

# --- Styling ---

def get_app_css():
    return f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

        :root {{
            --primary: {PRIMARY_COLOR};
            --accent: {ACCENT_COLOR};
            --bg-dark: {BG_COLOR};
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --card-bg: rgba(30, 41, 59, 0.7);
            --border: rgba(148, 163, 184, 0.1);

            /* Typography Variables - Adjusted for 700px embed */
            --font-size-h1: 2rem;
            --font-size-h2: 1.5rem;
            --font-size-h3: 1.2rem;
            --font-size-body: 0.95rem;
            --font-size-small: 0.8rem;
        }}

        /* Global Reset */
        * {{
            font-family: 'Inter', sans-serif;
        }}

        .stApp {{
            background-color: var(--bg-dark);
            background-image:
                radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.10) 0px, transparent 50%),
                radial-gradient(at 100% 0%, rgba(6, 182, 212, 0.10) 0px, transparent 50%);
        }}

        /* Transparent Header */
        header[data-testid="stHeader"] {{
            background-color: transparent !important;
            border-bottom: none !important;
        }}

        /* Typography */
        h1 {{ font-size: var(--font-size-h1); color: var(--text-main); font-weight: 700; letter-spacing: -0.02em; }}
        h2 {{ font-size: var(--font-size-h2); color: var(--text-main); font-weight: 600; }}
        h3 {{ font-size: var(--font-size-h3); color: var(--text-main); font-weight: 600; }}
        p, li {{ font-size: var(--font-size-body); color: var(--text-main); line-height: 1.6; }}

        /* Cards */
        .custom-card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1rem;
            margin-bottom: 0.8rem;
            backdrop-filter: blur(10px);
            transition: transform 0.2s, border-color 0.2s;
        }}

        .custom-card:hover {{
            border-color: var(--primary);
            transform: translateY(-2px);
        }}

        /* Chips */
        .chip {{
            display: inline-flex;
            align-items: center;
            padding: 2px 10px;
            border-radius: 99px;
            font-size: 0.7rem;
            font-weight: 600;
            margin-right: 6px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: var(--text-muted);
        }}

        .chip.primary {{ background: rgba(99, 102, 241, 0.2); border-color: rgba(99, 102, 241, 0.3); color: #c7d2fe; }}
        .chip.accent {{ background: rgba(6, 182, 212, 0.2); border-color: rgba(6, 182, 212, 0.3); color: #a5f3fc; }}

        /* Highlights */
        mark {{
            background: rgba(253, 224, 71, 0.2);
            color: #fef08a;
            padding: 0 4px;
            border-radius: 4px;
            border: 1px solid rgba(253, 224, 71, 0.4);
        }}

        mark.active {{
            background: rgba(253, 224, 71, 0.4);
            border-color: #fde047;
            box-shadow: 0 0 0 2px rgba(253, 224, 71, 0.2);
        }}

        /* Sidebar */
        [data-testid="stSidebar"] {{
            background-color: rgba(15, 23, 42, 0.98);
            border-right: 1px solid var(--border);
        }}

        [data-testid="stSidebar"] h1 {{
            font-size: 1.2rem;
            margin-bottom: 1rem;
        }}

        /* Remove default streamlit padding */
        .block-container {{
            padding-top: 3rem;
            padding-bottom: 4rem;
            max-width: 100%; /* Use full width for embed */
        }}

        /* Hide footer */
        footer {{display: none;}}

        /* Input fields */
        .stTextInput > div > div > input {{
            background-color: rgba(30, 41, 59, 0.5);
            color: var(--text-main);
            border-color: var(--border);
        }}

        /* Hide heading anchor icons */
        [data-testid="stHeaderActionElements"] {{
            display: none !important;
        }}

        .result-card {{
            position: relative;
            cursor: pointer;
            margin-bottom: 1rem;
        }}

        .result-card:hover {{
            border-color: var(--accent);
        }}

        .result-card-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            margin-bottom: 0.75rem;
        }}

        .view-button {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.4rem 1rem;
            border-radius: 999px;
            background: rgba(99, 102, 241, 0.2);
            border: 1px solid rgba(99, 102, 241, 0.4);
            color: #e0e7ff;
            font-weight: 600;
            font-size: 0.85rem;
            cursor: pointer;
            width: auto;
            text-decoration: none;
        }}

        .result-card-title {{
            color: #f1f5f9;
            text-decoration: none;
            display: inline-block;
            width: 100%;
        }}

        .result-card-title:hover {{
            color: var(--accent);
        }}

        /* Trial Banner */
        .trial-banner {{
            background: linear-gradient(135deg, rgba(251, 191, 36, 0.15) 0%, rgba(245, 158, 11, 0.15) 100%);
            border: 1px solid rgba(251, 191, 36, 0.3);
            border-radius: 8px;
            padding: 0.75rem 1rem;
            margin-bottom: 1.5rem;
            text-align: center;
        }}

        .trial-banner p {{
            color: #fcd34d;
            font-size: 0.85rem;
            margin: 0;
        }}
    </style>
    """

def highlight_text(content: str, query: str, add_ids: bool = False) -> str:
    """Highlight search terms in content."""
    if not query:
        return content

    words = [w for w in re.split(r"\s+", query) if len(w) > 2]
    if not words:
        return content

    pattern_str = '|'.join(re.escape(w) for w in words)
    pattern = re.compile(f"({pattern_str})", re.IGNORECASE)

    match_count = 0

    def replace_func(match):
        nonlocal match_count
        match_count += 1
        text = match.group(1)
        if add_ids:
            return f'<mark id="match-{match_count}" class="active">{text}</mark>'
        return f'<mark>{text}</mark>'

    return pattern.sub(replace_func, content)

# --- UI Components ---

def render_sidebar(stats: Dict) -> Tuple[str, Dict]:
    """Render sidebar and return filter values."""
    with st.sidebar:
        st.title("🎛️ Filtros")

        # Clear Filters Button
        if st.button("🔄 Limpiar Filtros", use_container_width=True):
            st.session_state.query = ""
            st.session_state.page = 1
            # Clear specific keys
            for key in ['sb_sala', 'sb_year_from', 'sb_year_to', 'sb_acta_num', 'landing_sala', 'landing_year', 'landing_acta_num']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

        mode = st.radio(
            "Modo de Búsqueda",
            ["General", "Decisiones"],
            captions=["Texto completo en actas", "Base de datos estructurada"]
        )

        st.divider()

        filters = {}

        if mode == "General":
            st.subheader("Filtros Generales")

            # Sala
            sala_opts = ["Todas"] + [f"{s} - {stats['sala_names'].get(s, s)}" for s in stats['salas']]
            sala_sel = st.selectbox("Sala", sala_opts, key="sb_sala")
            filters['sala'] = sala_sel.split(" - ")[0] if sala_sel != "Todas" else "Todas"

            # Years
            c1, c2 = st.columns(2)
            filters['year_from'] = c1.selectbox("Desde", ["Todos"] + stats['years'], index=0, key="sb_year_from")
            filters['year_to'] = c2.selectbox("Hasta", ["Todos"] + stats['years'], index=0, key="sb_year_to")

            # Acta Number - Direct Lookup
            filters['acta_number'] = st.text_input("Número de Acta", placeholder="Ej. 12", key="sb_acta_num")

            st.divider()

            # Sort
            filters['sort_by'] = st.selectbox(
                "Ordenar por",
                options=["rank", "year_desc", "year_asc", "sala"],
                format_func=lambda x: {
                    "rank": "⭐ Relevancia",
                    "year_desc": "📅 Más recientes",
                    "year_asc": "📅 Más antiguos",
                    "sala": "🏛️ Por Sala"
                }[x]
            )

        else: # Decision Mode
            st.subheader("Filtros de Decisiones")

            # Info about structured search mode
            st.info(
                "**Modo Decisiones:** Busca en ~56,000 decisiones estructuradas extraídas "
                "de las 1,770 actas (1996-2025). Permite filtrar por resultado y tipo de solicitud."
            )

            filters['sala'] = st.selectbox("Comité", ["Todos", "SEM", "SEMPB", "SEMNNIMB", "CR", "SEMH", "SEPFSD"])
            filters['outcome'] = st.selectbox("Resultado", ["Todos", "Aprobada", "No Recomendada", "Aplazada", "No Aplica", "Otro"])
            filters['request_type'] = st.selectbox("Tipo Solicitud", ["Todos", "Exclusión", "Inclusión", "Otro"])
            filters['year'] = st.selectbox("Año", ["Todos"] + [str(y) for y in range(2025, 1995, -1)])

        st.divider()

        # Stats in sidebar
        st.caption("📊 Estadísticas del Sistema")
        c1, c2 = st.columns(2)
        c1.metric("Actas", f"{stats['total']:,}")
        c2.metric("Años", f"{len(stats['years'])}")

        return mode, filters

def render_tutorial():
    """Render the tutorial page."""
    st.markdown("## 📘 Cómo usar el Buscador")

    if st.button("← Volver al Inicio"):
        st.session_state.show_tutorial = False
        st.rerun()

    st.markdown("""
    <div class="custom-card">
        <h3>1. Búsqueda por Palabras</h3>
        <p>El buscador utiliza tecnología de texto completo (FTS5) para encontrar palabras en el contenido de las actas.</p>
        <ul>
            <li><strong>Búsqueda simple:</strong> Escribe palabras clave como <code>Acetaminofen</code>.</li>
            <li><strong>Múltiples palabras:</strong> Si escribes <code>vitales no disponibles</code>, el sistema buscará documentos que contengan <strong>TODAS</strong> esas palabras (lógica AND).</li>
            <li><strong>Frases exactas:</strong> Usa comillas para buscar frases exactas, por ejemplo: <code>"medicamento vital"</code>.</li>
            <li><strong>Comodines:</strong> El sistema añade automáticamente comodines, así que <code>medic</code> encontrará <code>medicamento</code>, <code>medicina</code>, etc.</li>
        </ul>
    </div>

    <div class="custom-card">
        <h3>2. Búsqueda de Acta Específica</h3>
        <p>Si ya conoces el número del acta, usa la sección "Busca una acta específica" en la página de inicio.</p>
        <ul>
            <li>Selecciona el <strong>Año</strong> y la <strong>Sala</strong>.</li>
            <li>Escribe el <strong>Número</strong> del acta.</li>
            <li>Haz clic en "Buscar Acta".</li>
        </ul>
    </div>

    <div class="custom-card">
        <h3>3. Navegación en el Documento</h3>
        <p>Cuando abras un acta:</p>
        <ul>
            <li>Las palabras encontradas estarán resaltadas en amarillo.</li>
            <li>Usa los controles de navegación para moverte entre coincidencias.</li>
        </ul>
        <p style="color: #fcd34d; font-size: 0.85rem; margin-top: 0.5rem;">
            Nota: La descarga de PDFs estará disponible en la versión completa.
        </p>
    </div>
    """, unsafe_allow_html=True)

def render_app_header():
    """Render the shared hero header with branding."""
    st.markdown(
        """
        <div style="text-align: center; padding: 1rem 0;">
            <h1 style="margin-bottom: 0.5rem;">
                <span style="background: linear-gradient(to right, #6366f1, #06b6d4); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                    Explorador de Actas
                </span>
            </h1>
            <p style="font-size: 1rem; color: #94a3b8; max-width: 600px; margin: 0 auto;">
                Búsqueda y análisis de decisiones regulatorias (1996-2025).
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

def render_trial_banner():
    """Render the trial version banner."""
    st.markdown(
        """
        <div class="trial-banner">
            <p>🧪 <strong>Versión de Prueba</strong> — La descarga de documentos PDF estará disponible en la versión completa.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

def render_welcome(stats: Dict):
    """Render the landing page."""
    render_app_header()
    render_trial_banner()

    # Quick stats cards
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f"""
            <div class="custom-card" style="text-align: center; padding: 1rem;">
                <div style="font-size: 1.5rem;">📚</div>
                <div style="font-weight: 700; font-size: 1.2rem; color: #f1f5f9;">{stats['total']:,}</div>
                <div style="color: #94a3b8; font-size: 0.75rem;">Actas</div>
            </div>
            """, unsafe_allow_html=True
        )
    with c2:
        st.markdown(
            """
            <div class="custom-card" style="text-align: center; padding: 1rem;">
                <div style="font-size: 1.5rem;">⚡</div>
                <div style="font-weight: 700; font-size: 1.2rem; color: #f1f5f9;">Rápido</div>
                <div style="color: #94a3b8; font-size: 0.75rem;">Búsqueda</div>
            </div>
            """, unsafe_allow_html=True
        )
    with c3:
        st.markdown(
            f"""
            <div class="custom-card" style="text-align: center; padding: 1rem;">
                <div style="font-size: 1.5rem;">🏛️</div>
                <div style="font-weight: 700; font-size: 1.2rem; color: #f1f5f9;">{len(stats['salas'])}</div>
                <div style="color: #94a3b8; font-size: 0.75rem;">Salas</div>
            </div>
            """, unsafe_allow_html=True
        )

    st.divider()

    # --- Section 1: General Search ---
    st.markdown("### 🔎 Busca por palabras en todas las actas")

    query = st.text_input(
        "Búsqueda General",
        key="landing_search",
        placeholder="Ej. Acetaminofen, Pfizer, Vitales no disponibles...",
        label_visibility="collapsed"
    )
    if query:
        st.session_state.query = query
        st.session_state.page = 1
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # --- Section 2: Specific Search ---
    st.markdown("### 📄 Busca una acta específica")
    c1, c2, c3 = st.columns(3)

    with c1:
        sala_opts = ["Todas"] + [f"{s} - {stats['sala_names'].get(s, s)}" for s in stats['salas']]
        st.selectbox("Sala", sala_opts, key="landing_sala")

    with c2:
        st.selectbox("Año", ["Todos"] + stats['years'], index=0, key="landing_year")

    with c3:
        st.text_input("Número de Acta", placeholder="Ej. 12", key="landing_acta_num")

    if st.button("Buscar Acta", type="primary", use_container_width=True):
        # Set filters and trigger search
        st.session_state.query = ""  # Clear text query
        st.session_state.trigger_specific_search = True
        st.rerun()

    st.divider()

    if st.button("📘 ¿Cómo usar este buscador?"):
        st.session_state.show_tutorial = True
        st.rerun()

def render_acta_viewer(acta_id: str, query: str):
    """Render the detailed acta view."""
    content, metadata = get_acta_content(acta_id)

    if not content:
        st.error("No se pudo cargar el acta.")
        if st.button("Volver"):
            st.session_state.selected_acta = None
            st.rerun()
        return

    render_app_header()

    # Header
    if st.button("🏠 Volver a Resultados", type="secondary"):
        st.session_state.selected_acta = None
        st.rerun()

    st.markdown(f"""
    <div class="custom-card">
        <div style="display: flex; justify-content: space-between; align-items: start;">
            <div>
                <h2 style="margin:0;">Acta {metadata['acta_number']} de {metadata['year']}</h2>
                <p style="color: var(--text-muted); margin-top: 0.5rem;">{metadata['sala']}</p>
            </div>
            <div style="text-align: right;">
                <span class="chip primary">{metadata['year']}</span>
                <span class="chip accent">{metadata['sala']}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Content
    st.divider()

    # Highlight
    display_content = highlight_text(content, query, add_ids=True)

    # Navigation for matches
    matches = len(re.findall(r'<mark', display_content))
    if matches > 0:
        st.info(f"🔍 {matches} coincidencias encontradas para '{query}'")

    st.markdown(display_content, unsafe_allow_html=True)

def render_trend_chart(data: pd.DataFrame, query: str):
    """Render a trend chart using Altair."""
    if data.empty:
        return

    st.markdown(f"### 📈 Tendencia: '{query}'")

    # Create Altair chart
    chart = alt.Chart(data).mark_bar(
        cornerRadiusTopLeft=4,
        cornerRadiusTopRight=4
    ).encode(
        x=alt.X('year:O', title='Año', axis=alt.Axis(labelAngle=-45)),
        y=alt.Y('count:Q', title='Menciones'),
        color=alt.value(PRIMARY_COLOR),
        tooltip=['year', 'count']
    ).properties(
        height=200,
        width='container'
    ).configure_axis(
        grid=False,
        labelColor='#94a3b8',
        titleColor='#94a3b8'
    ).configure_view(
        strokeWidth=0
    )

    st.altair_chart(chart, use_container_width=True)

def render_search_results(results: List, total: int, query: str, mode: str, page: int, per_page: int, filters: Dict):
    """Render the list of search results."""
    render_app_header()

    # Small Title & Search Bar
    c1, c2, c3 = st.columns([1, 3, 1])
    with c1:
        if st.button("🏠 Inicio", key="home_btn"):
            st.session_state.query = ""
            st.session_state.page = 1
            st.session_state.trigger_specific_search = False
            st.rerun()
    with c2:
        new_query = st.text_input("Búsqueda", value=query, label_visibility="collapsed", key="results_search")
        if new_query != query:
            st.session_state.query = new_query
            st.session_state.page = 1
            st.rerun()

    # Trend Chart (Only in General Mode with a query)
    if mode == "General" and query:
        trend_data = get_trend_data(query, filters)
        if not trend_data.empty:
            render_trend_chart(trend_data, query)
            st.divider()

    st.markdown(f"### 🔍 Resultados ({total})")

    # Pagination logic
    total_pages = (total + per_page - 1) // per_page

    # Results list
    for item in results:
        if mode == "General":
            acta_id, snippet, _, sala, year, num = item

            st.markdown(f"""
            <div class="custom-card result-card">
                    <div class="result-card-meta">
                        <span class="chip primary">{year}</span>
                        <span class="chip accent">{sala}</span>
                        <span class="chip">Acta {num}</span>
                    </div>
                    <h3 style="font-size: 1.1rem; margin-bottom: 0.5rem;">
                        <a class="result-card-title" href="?acta={acta_id}">📄 {acta_id}</a>
                    </h3>
                    <div style="color: #cbd5e1; font-size: 0.9rem; margin-bottom: 1rem; padding-left: 1rem; border-left: 3px solid var(--primary);">
                        ...{snippet}...
                    </div>
                    <a class="view-button" href="?acta={acta_id}">Ver Documento</a>
                </div>
            """, unsafe_allow_html=True)

        else: # Decision Mode
            d = item
            with st.expander(f"💊 {d['product_name']} | {d['decision_outcome'].upper()}", expanded=False):
                st.markdown(f"""
                **Empresa:** {d['company']}
                **Radicado:** {d['radicados']}
                **Fecha:** {d['decision_date']}
                """)

                if d['request_summary']:
                    st.info(f"**Solicitud:** {d['request_summary']}")

                if d['decision_summary']:
                    st.success(f"**Concepto:** {d['decision_summary']}")

                if st.button("Ver Acta", key=f"dec_{d['decision_id']}"):
                    st.session_state.selected_acta = d['acta_id']
                    st.rerun()

    # Pagination Controls
    if total_pages > 1:
        st.divider()
        c1, c2, c3, c4, c5 = st.columns([1,1,2,1,1])

        with c2:
            if st.button("◀ Anterior", disabled=page==1):
                st.session_state.page -= 1
                st.rerun()

        with c3:
            st.markdown(f"<div style='text-align: center; padding-top: 5px;'>Página {page} de {total_pages}</div>", unsafe_allow_html=True)

        with c4:
            if st.button("Siguiente ▶", disabled=page==total_pages):
                st.session_state.page += 1
                st.rerun()

# --- Main ---

def main():
    # Inject CSS
    st.markdown(get_app_css(), unsafe_allow_html=True)

    # Initialize Session State
    if 'selected_acta' not in st.session_state:
        st.session_state.selected_acta = None
    if 'page' not in st.session_state:
        st.session_state.page = 1
    if 'query' not in st.session_state:
        st.session_state.query = ""
    if 'show_tutorial' not in st.session_state:
        st.session_state.show_tutorial = False
    if 'trigger_specific_search' not in st.session_state:
        st.session_state.trigger_specific_search = False

    query_params = get_query_params()
    target_acta = query_params.get('acta')
    if target_acta:
        if isinstance(target_acta, list):
            target_acta = target_acta[0]
        st.session_state.selected_acta = target_acta
        query_params.pop('acta', None)
        set_query_params(query_params)

    # Load Data
    stats = get_statistics()

    # Main Layout Logic
    if st.session_state.show_tutorial:
        render_tutorial()

    elif st.session_state.selected_acta:
        # Viewer Mode
        render_acta_viewer(st.session_state.selected_acta, st.session_state.query)

    else:
        # Render Sidebar first to get filters
        mode, filters = render_sidebar(stats)

        # Determine if we should show results
        # 1. Text Query exists
        # 2. Specific Search Triggered from Landing Page
        # 3. We are already viewing results (implied by query or trigger)

        # If specific search was triggered, override filters with landing page values
        if st.session_state.trigger_specific_search:
            # Override filters with landing page values if they exist in session state
            if 'landing_sala' in st.session_state and st.session_state.landing_sala != "Todas":
                filters['sala'] = st.session_state.landing_sala.split(" - ")[0]
            if 'landing_year' in st.session_state and st.session_state.landing_year != "Todos":
                filters['year_from'] = int(st.session_state.landing_year)
                filters['year_to'] = int(st.session_state.landing_year)
            if 'landing_acta_num' in st.session_state and st.session_state.landing_acta_num:
                filters['acta_number'] = st.session_state.landing_acta_num

        # Show results if query exists OR specific search triggered
        if st.session_state.query or st.session_state.trigger_specific_search:
            # Results Mode
            limit = 10
            offset = (st.session_state.page - 1) * limit

            if mode == "General":
                results, total = search_actas(st.session_state.query, filters, limit, offset)
            else:
                results, total = search_decisions(st.session_state.query, filters, limit, offset)

            render_search_results(results, total, st.session_state.query, mode, st.session_state.page, limit, filters)

        else:
            # Landing Page Mode
            render_welcome(stats)

if __name__ == "__main__":
    main()
