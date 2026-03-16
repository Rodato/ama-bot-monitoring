import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import db
import user_report

st.set_page_config(
    page_title="AMA BOT · MONITOR",
    page_icon="▣",
    layout="wide",
)

# ── Bloomberg-style CSS ───────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&display=swap');

html, body, [class*="css"], .stApp {
    font-family: 'IBM Plex Mono', 'Courier New', monospace !important;
    background-color: #080808 !important;
    color: #C8C8C8 !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #050505 !important;
    border-right: 1px solid #1E1E1E !important;
}
[data-testid="stSidebar"] * {
    font-family: 'IBM Plex Mono', monospace !important;
    color: #888 !important;
}
[data-testid="stSidebar"] label {
    color: #FFB300 !important;
    font-size: 0.7rem !important;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

/* Title */
h1 {
    font-family: 'IBM Plex Mono', monospace !important;
    color: #FFB300 !important;
    font-size: 1.4rem !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    border-bottom: 1px solid #FFB300;
    padding-bottom: 8px;
    margin-bottom: 4px !important;
}

/* Subheaders */
h2, h3 {
    font-family: 'IBM Plex Mono', monospace !important;
    color: #FFB300 !important;
    font-size: 0.75rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.15em;
}

/* Caption */
[data-testid="stCaptionContainer"] p {
    color: #555 !important;
    font-size: 0.65rem !important;
    font-family: 'IBM Plex Mono', monospace !important;
}

/* Metric card */
[data-testid="metric-container"] {
    background: #0D0D0D;
    border: 1px solid #1E1E1E;
    border-left: 3px solid #FFB300;
    padding: 12px 20px !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.65rem !important;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #666 !important;
}
[data-testid="stMetricValue"] {
    font-size: 2.8rem !important;
    color: #FFB300 !important;
    font-weight: 700 !important;
}

/* Divider */
hr {
    border: none !important;
    border-top: 1px solid #1A1A1A !important;
    margin: 12px 0 !important;
}

/* Selectbox / date input */
[data-testid="stSelectbox"] > div > div,
[data-testid="stDateInput"] input {
    background: #0D0D0D !important;
    border: 1px solid #2A2A2A !important;
    color: #C8C8C8 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.75rem !important;
}

/* Info boxes */
[data-testid="stInfo"] {
    background: #0D0D0D !important;
    border: 1px solid #1E1E1E !important;
    color: #555 !important;
    font-size: 0.7rem !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #080808; }
::-webkit-scrollbar-thumb { background: #1E1E1E; }

/* Ocultar ícono keyboard_double_arrow de Streamlit 1.55 */
[data-testid="stSelectbox"] svg,
[data-testid="stDateInput"] svg,
button[data-testid="stBaseButton-minimal"] svg { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ── Plotly base layout ────────────────────────────────────────────────────────

_AMBER  = "#FFB300"
_CYAN   = "#00D4FF"
_GREEN  = "#00C853"
_RED    = "#FF1744"
_CHART_COLORS = [_AMBER, _CYAN, _GREEN, _RED, "#FF6D00", "#AA00FF"]

_FONT = dict(family="IBM Plex Mono, Courier New, monospace", color="#888888", size=11)

def _base_layout(**kwargs) -> dict:
    base = dict(
        paper_bgcolor="#0D0D0D",
        plot_bgcolor="#0D0D0D",
        font=_FONT,
        xaxis=dict(
            showgrid=True, gridcolor="#151515", gridwidth=1,
            zeroline=False, tickfont=_FONT,
            linecolor="#1E1E1E", linewidth=1,
        ),
        yaxis=dict(
            showgrid=True, gridcolor="#151515", gridwidth=1,
            zeroline=False, tickfont=_FONT,
            linecolor="#1E1E1E", linewidth=1,
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)", bordercolor="#1E1E1E", borderwidth=1,
            font=dict(family="IBM Plex Mono, monospace", color="#888", size=10),
        ),
        margin=dict(l=0, r=0, t=30, b=0),
        hoverlabel=dict(
            bgcolor="#111111", bordercolor="#333333",
            font=dict(family="IBM Plex Mono, monospace", color="#FFB300", size=11),
        ),
    )
    base.update(kwargs)
    return base

# ── Auto-refresh a medianoche (Bogotá) ────────────────────────────────────────

def _ms_until_midnight() -> int:
    tz = ZoneInfo("America/Bogota")
    now = datetime.now(tz)
    midnight = datetime(now.year, now.month, now.day, tzinfo=tz) + timedelta(days=1)
    return max(1000, int((midnight - now).total_seconds() * 1000))

components.html(
    f"<script>setTimeout(()=>window.parent.location.reload(),{_ms_until_midnight()})</script>",
    height=0,
)

# ── Cache ─────────────────────────────────────────────────────────────────────

_TODAY = date.today()

@st.cache_data(show_spinner=False)
def _get_cities(_d):
    return db.get_cities()

@st.cache_data(show_spinner=False)
def _get_users_count(city, date_from, date_to, _d, school=None):
    return db.get_users_count(city=city, date_from=str(date_from), date_to=str(date_to), school=school)

@st.cache_data(show_spinner=False)
def _get_gender_dist(city, date_from, date_to, _d, school=None):
    return db.get_gender_dist(city=city, date_from=str(date_from), date_to=str(date_to), school=school)

@st.cache_data(show_spinner=False)
def _get_school_dist(city, date_from, date_to, _d):
    return db.get_school_dist(city=city, date_from=str(date_from), date_to=str(date_to))

@st.cache_data(show_spinner=False)
def _get_daily_users_by_gender(city, date_from, date_to, _d, school=None):
    return db.get_daily_users_by_gender(city=city, date_from=str(date_from), date_to=str(date_to), school=school)

@st.cache_data(show_spinner=False)
def _get_users_by_session(city, date_from, date_to, _d):
    return db.get_users_by_session(city=city, date_from=str(date_from), date_to=str(date_to))

@st.cache_data(show_spinner=False)
def _get_schools(city, date_from, date_to, _d):
    return db.get_schools(city=city, date_from=str(date_from), date_to=str(date_to))

@st.cache_data(show_spinner=False)
def _get_daily_users_by_school_v2(schools_tuple, city, date_from, date_to, _d):
    return db.get_daily_users_by_school(
        schools=list(schools_tuple), city=city,
        date_from=str(date_from), date_to=str(date_to),
    )

@st.cache_data(show_spinner=False)
def _build_user_report_bytes(date_from_str, date_to_str):
    return user_report.generate_user_report_bytes(date_from_str, date_to_str)

@st.cache_data(show_spinner=False)
def _get_users_by_session_and_gender(city, date_from, date_to, _d, school=None):
    return db.get_users_by_session_and_gender(
        city=city, date_from=str(date_from), date_to=str(date_to), school=school,
    )

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ▣ FILTROS")

    cities = _get_cities(_TODAY)
    city_options = ["TODAS LAS CIUDADES"] + [c.upper() for c in cities]
    city_label = st.selectbox("CIUDAD", city_options)
    city_filter = None if city_label == "TODAS LAS CIUDADES" else city_label.title()

    st.divider()

    start_min = date.fromisoformat(db.START_DATE)
    today = date.today()
    date_from = start_min
    st.caption(f"DESDE · {start_min.strftime('%d/%m/%Y')}")
    date_to = st.date_input("HASTA", value=today, min_value=start_min, max_value=today,
                             label_visibility="visible")

    st.divider()
    tz = ZoneInfo("America/Bogota")
    now_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    st.caption(f"UPDATED · {now_str}")

# ── Header ────────────────────────────────────────────────────────────────────

tz = ZoneInfo("America/Bogota")
ciudad_str = (city_filter or "ALL CITIES").upper()
rango = f"{date_from.strftime('%d/%m/%Y')} → {date_to.strftime('%d/%m/%Y')}"

st.title("AMA BOT · MONITOR")
st.caption(f"{ciudad_str}  ·  {rango}  ·  {datetime.now(tz).strftime('%H:%M:%S')} COT")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["▣  INDICADORES GENERALES", "▣  POR COLEGIO", "▣  REPORTES"])

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — INDICADORES GENERALES
# ════════════════════════════════════════════════════════════════════════════════

with tab1:

    # KPI
    n_users = _get_users_count(city_filter, date_from, date_to, _TODAY)
    st.metric("USUARIOS DEL PROGRAMA", n_users)

    st.divider()

    # Género + Colegios
    col_gen, col_sch = st.columns(2)

    gender_df = _get_gender_dist(city_filter, date_from, date_to, _TODAY)
    school_df = _get_school_dist(city_filter, date_from, date_to, _TODAY)

    with col_gen:
        st.subheader("DISTRIBUCIÓN · GÉNERO")
        if not gender_df.empty:
            fig = go.Figure(go.Pie(
                labels=gender_df["gender"].tolist(),
                values=gender_df["cantidad"].tolist(),
                hole=0.5,
                marker=dict(
                    colors=_CHART_COLORS[:len(gender_df)],
                    line=dict(color="#080808", width=2),
                ),
                textfont=dict(family="IBM Plex Mono, monospace", color="#080808", size=11),
                hovertemplate="<b>%{label}</b><br>%{value} usuarios (%{percent})<extra></extra>",
            ))
            fig.update_layout(**_base_layout(
                showlegend=True,
                legend=dict(
                    orientation="h", x=0.5, xanchor="center", y=-0.05,
                    bgcolor="rgba(0,0,0,0)", font=dict(family="IBM Plex Mono, monospace", color="#888", size=10),
                ),
                margin=dict(l=0, r=0, t=10, b=10),
            ))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("NO DATA")

    with col_sch:
        st.subheader("USUARIOS · INSTITUCIÓN")
        if not school_df.empty:
            fig = go.Figure(go.Bar(
                x=school_df["cantidad"].tolist(),
                y=school_df["school"].tolist(),
                orientation="h",
                marker=dict(color=_AMBER, line=dict(color="#080808", width=0.5)),
                text=school_df["cantidad"].tolist(),
                textposition="outside",
                textfont=dict(family="IBM Plex Mono, monospace", color=_AMBER, size=11),
                hovertemplate="<b>%{y}</b><br>%{x} usuarios<extra></extra>",
            ))
            fig.update_layout(**_base_layout(
                yaxis=dict(
                    categoryorder="total ascending",
                    showgrid=False, tickfont=dict(family="IBM Plex Mono, monospace", color="#888", size=10),
                    linecolor="#1E1E1E",
                ),
                margin=dict(l=0, r=40, t=10, b=0),
            ))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("NO DATA")

    st.divider()

    # Actividad diaria por género
    st.subheader("ACTIVIDAD DIARIA · POR GÉNERO")
    daily_gender_df = _get_daily_users_by_gender(city_filter, date_from, date_to, _TODAY)

    if not daily_gender_df.empty:
        fig = go.Figure()
        for i, gender in enumerate(daily_gender_df["gender"].unique()):
            subset = daily_gender_df[daily_gender_df["gender"] == gender]
            color = _CHART_COLORS[i % len(_CHART_COLORS)]
            fig.add_trace(go.Scatter(
                x=subset["fecha"].tolist(),
                y=subset["usuarios"].tolist(),
                mode="lines+markers",
                name=gender.upper(),
                line=dict(color=color, width=2),
                marker=dict(color=color, size=6, symbol="circle",
                            line=dict(color="#080808", width=1)),
                hovertemplate=f"<b>{gender}</b><br>%{{x}}<br>%{{y}} usuarios<extra></extra>",
            ))
        fig.update_layout(**_base_layout(
            yaxis=dict(
                title="USUARIOS", rangemode="tozero",
                showgrid=True, gridcolor="#151515", tickfont=_FONT, linecolor="#1E1E1E",
            ),
            xaxis=dict(showgrid=False, tickfont=_FONT, linecolor="#1E1E1E"),
            margin=dict(l=0, r=0, t=10, b=0),
        ))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("NO DATA")

    st.divider()

    # Sesiones
    st.subheader("USUARIOS · POR SESIÓN")
    sessions_df = _get_users_by_session(city_filter, date_from, date_to, _TODAY)

    if not sessions_df.empty:
        labels = ["S" + str(int(s)) for s in sessions_df["sesion"]]
        values = sessions_df["usuarios"].tolist()
        fig = go.Figure(go.Bar(
            x=labels,
            y=values,
            marker=dict(color=[_CYAN] * len(values), line=dict(color="#080808", width=0.5)),
            text=values,
            textposition="outside",
            textfont=dict(family="IBM Plex Mono, monospace", color=_CYAN, size=12),
            hovertemplate="<b>SESIÓN %{x}</b><br>%{y} usuarios únicos<extra></extra>",
        ))
        fig.update_layout(**_base_layout(
            yaxis=dict(
                title="USUARIOS ÚNICOS", rangemode="tozero",
                showgrid=True, gridcolor="#151515", tickfont=_FONT, linecolor="#1E1E1E",
            ),
            xaxis=dict(
                showgrid=False,
                tickfont=dict(family="IBM Plex Mono, monospace", color="#888", size=12),
                linecolor="#1E1E1E",
            ),
            margin=dict(l=0, r=0, t=10, b=0),
        ))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("NO DATA")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — POR COLEGIO
# ════════════════════════════════════════════════════════════════════════════════

with tab2:

    available_schools = _get_schools(city_filter, date_from, date_to, _TODAY)

    if not available_schools:
        st.info("NO HAY COLEGIOS CON ACTIVIDAD EN EL PERÍODO SELECCIONADO")
    else:
        selected_school = st.selectbox(
            "COLEGIO",
            options=available_schools,
            index=0,
        )

        st.divider()

        # KPIs por género
        gender_school_df = _get_gender_dist(city_filter, date_from, date_to, _TODAY, school=selected_school)
        total_school = _get_users_count(city_filter, date_from, date_to, _TODAY, school=selected_school)

        kpi_cols = st.columns(1 + len(gender_school_df))
        with kpi_cols[0]:
            st.metric("TOTAL USUARIOS", total_school)
        for i, row in enumerate(gender_school_df.itertuples(), start=1):
            with kpi_cols[i]:
                st.metric(str(row.gender).upper(), int(row.cantidad))

        st.divider()

        # Actividad diaria por género para el colegio
        st.subheader("ACTIVIDAD DIARIA · POR GÉNERO")
        daily_school_df = _get_daily_users_by_gender(
            city_filter, date_from, date_to, _TODAY, school=selected_school
        )

        if not daily_school_df.empty:
            fig = go.Figure()
            for i, gender in enumerate(daily_school_df["gender"].unique()):
                subset = daily_school_df[daily_school_df["gender"] == gender]
                color = _CHART_COLORS[i % len(_CHART_COLORS)]
                fig.add_trace(go.Scatter(
                    x=subset["fecha"].tolist(),
                    y=subset["usuarios"].tolist(),
                    mode="lines+markers",
                    name=gender.upper(),
                    line=dict(color=color, width=2),
                    marker=dict(color=color, size=6, symbol="circle",
                                line=dict(color="#080808", width=1)),
                    hovertemplate=f"<b>{gender}</b><br>%{{x}}<br>%{{y}} usuarios<extra></extra>",
                ))
            fig.update_layout(**_base_layout(
                yaxis=dict(
                    title="USUARIOS", rangemode="tozero",
                    showgrid=True, gridcolor="#151515", tickfont=_FONT, linecolor="#1E1E1E",
                ),
                xaxis=dict(showgrid=False, tickfont=_FONT, linecolor="#1E1E1E"),
                margin=dict(l=0, r=0, t=10, b=0),
            ))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("NO DATA")

        st.divider()

        # Sesiones por género para el colegio
        st.subheader("USUARIOS · POR SESIÓN Y GÉNERO")
        sess_gender_df = _get_users_by_session_and_gender(
            city_filter, date_from, date_to, _TODAY, school=selected_school
        )

        if not sess_gender_df.empty:
            fig = go.Figure()
            for i, gender in enumerate(sess_gender_df["gender"].unique()):
                subset = sess_gender_df[sess_gender_df["gender"] == gender]
                color = _CHART_COLORS[i % len(_CHART_COLORS)]
                fig.add_trace(go.Bar(
                    x=["S" + str(int(s)) for s in subset["sesion"].tolist()],
                    y=subset["usuarios"].tolist(),
                    name=gender.upper(),
                    marker=dict(color=color, line=dict(color="#080808", width=0.5)),
                    text=subset["usuarios"].tolist(),
                    textposition="outside",
                    textfont=dict(family="IBM Plex Mono, monospace", color=color, size=11),
                    hovertemplate=f"<b>{gender}</b> · SESIÓN %{{x}}<br>%{{y}} usuarios<extra></extra>",
                ))
            fig.update_layout(**_base_layout(
                barmode="group",
                yaxis=dict(
                    title="USUARIOS ÚNICOS", rangemode="tozero",
                    showgrid=True, gridcolor="#151515", tickfont=_FONT, linecolor="#1E1E1E",
                ),
                xaxis=dict(
                    showgrid=False,
                    tickfont=dict(family="IBM Plex Mono, monospace", color="#888", size=12),
                    linecolor="#1E1E1E",
                ),
                margin=dict(l=0, r=0, t=10, b=0),
            ))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("NO DATA")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — REPORTES
# ════════════════════════════════════════════════════════════════════════════════

with tab3:
    st.subheader("REPORTE DE USUARIOS")
    st.caption("GENERA UN EXCEL POR CIUDAD CON EL DETALLE DE CADA USUARIO Y SUS SESIONES")

    st.divider()

    col_from, col_to = st.columns(2)
    with col_from:
        r_from = st.date_input(
            "DESDE",
            value=date.fromisoformat(db.START_DATE),
            min_value=date.fromisoformat(db.START_DATE),
            max_value=date.today(),
            key="report_from",
        )
    with col_to:
        r_to = st.date_input(
            "HASTA",
            value=date.today(),
            min_value=date.fromisoformat(db.START_DATE),
            max_value=date.today(),
            key="report_to",
        )

    st.divider()

    if r_from > r_to:
        st.warning("LA FECHA DE INICIO DEBE SER ANTERIOR A LA FECHA FIN")
    else:
        with st.spinner("GENERANDO REPORTE..."):
            excel_bytes = _build_user_report_bytes(str(r_from), str(r_to))

        fname = f"reporte_usuarios_{r_from}_{r_to}.xlsx"
        st.download_button(
            label="⬇  DESCARGAR EXCEL",
            data=excel_bytes,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.caption(f"ARCHIVO · {fname}")
