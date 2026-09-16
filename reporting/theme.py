import streamlit as st
from html import escape
from base64 import b64encode
from pathlib import Path


SOLVIT_RED = "#ff353e"
SOLVIT_LOGO_URI = "data:image/jpeg;base64," + b64encode(
    (Path(__file__).resolve().parents[1] / "assets" / "solvit-logo.jpg").read_bytes()
).decode("ascii")


def apply_solvit_theme():
    st.markdown(
        """
        <style>
        :root {
            --solvit-red: #ff353e;
            --solvit-bg: #F8FAFC;
            --solvit-text: #0F172A;
            --solvit-muted: #64748B;
            --solvit-border: #E2E8F0;
        }
        .stApp { background: var(--solvit-bg); color: var(--solvit-text); }
        [data-testid="stHeader"] { background: rgba(248,250,252,.92); }
        [data-testid="stSidebar"] {
            background: #FFFFFF;
            border-right: 1px solid var(--solvit-border);
        }
        [data-testid="stSidebar"] > div:first-child { padding: 1.2rem 1rem 5.5rem; }
        [data-testid="stSidebar"] [data-baseweb="select"] > div { background:#F8FAFC; min-height:42px; }
        [data-testid="stSidebar"] label { font-size:.72rem !important;font-weight:750 !important;color:#475569 !important; }
        .st-key-sidebar_logout { position:fixed;left:18px;bottom:18px;z-index:9999;width:auto !important; }
        .st-key-sidebar_logout button { width:auto !important;min-height:34px !important;padding:.35rem .75rem !important;background:#FFF !important;font-size:.7rem !important;box-shadow:0 4px 14px rgba(15,23,42,.08) !important; }
        [data-testid="stSidebar"] hr { border-color: var(--solvit-border); }
        .block-container { max-width: 1280px; padding-top: 2rem; padding-bottom: 4rem; }
        h1, h2, h3 { color: var(--solvit-text); letter-spacing: -0.025em; }
        h1 { font-weight: 800 !important; }
        h2, h3 { font-weight: 700 !important; }
        p, label, [data-testid="stCaptionContainer"] { color: var(--solvit-muted); }
        div[data-testid="stMetric"] {
            background: linear-gradient(180deg, #FFFFFF 0%, #FAFAFA 100%);
            border: 1px solid var(--solvit-border);
            border-radius: 16px;
            padding: 18px 20px;
            box-shadow: 0 1px 2px rgba(15,23,42,.04);
        }
        div[data-testid="stMetric"] label {
            color: var(--solvit-muted) !important;
            font-size: .75rem !important;
            font-weight: 700 !important;
            text-transform: uppercase;
            letter-spacing: .045em;
        }
        div[data-testid="stMetricValue"] { color: var(--solvit-text); font-weight: 800; }
        .stButton > button, .stDownloadButton > button, .stLinkButton > a {
            border-radius: 12px !important;
            border-color: var(--solvit-border) !important;
            font-weight: 700 !important;
            min-height: 2.55rem;
            box-shadow: 0 1px 2px rgba(15,23,42,.04);
        }
        .stButton > button[kind="primary"] {
            background: var(--solvit-red) !important;
            border-color: var(--solvit-red) !important;
            color: #FFFFFF !important;
        }
        .stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover {
            border-color: var(--solvit-red) !important;
            color: var(--solvit-red) !important;
        }
        .stButton > button[kind="primary"]:hover { color: #FFFFFF !important; filter: brightness(.94); }
        [data-baseweb="input"] > div, [data-baseweb="select"] > div,
        textarea, [data-testid="stFileUploaderDropzone"] {
            border-radius: 12px !important;
            border-color: var(--solvit-border) !important;
        }
        [data-baseweb="input"] > div:focus-within, [data-baseweb="select"] > div:focus-within {
            border-color: var(--solvit-red) !important;
            box-shadow: 0 0 0 2px rgba(255,53,62,.12) !important;
        }
        [data-testid="stExpander"], [data-testid="stDataFrame"] {
            background: #FFFFFF;
            border: 1px solid var(--solvit-border);
            border-radius: 16px;
            overflow: hidden;
        }
        [data-baseweb="tab-list"] { gap: .35rem; background: #F1F5F9; padding: .3rem; border-radius: 12px; }
        [data-baseweb="tab"] { border-radius: 9px; font-weight: 700; }
        [aria-selected="true"][role="tab"] { background: #FFFFFF; color: var(--solvit-text); }
        [data-baseweb="tab-highlight"] { background-color: var(--solvit-red) !important; }
        hr { border-color: var(--solvit-border) !important; }
        .solvit-brand {
            display: flex; align-items: center; gap: 12px; margin: 0 0 1.4rem 0;
            padding-bottom: 1rem; border-bottom: 1px solid var(--solvit-border);
        }
        .dashboard-hero {
            position: relative; overflow: hidden; padding: 30px 34px; margin: 0 0 24px;
            border-radius: 22px; color: white;
            background: linear-gradient(125deg, #111827 0%, #1E293B 70%, #3A2025 100%);
            box-shadow: 0 18px 45px rgba(15,23,42,.13);
        }
        .dashboard-hero:after {
            content: ""; position: absolute; width: 260px; height: 260px; right: -70px; top: -120px;
            border-radius: 999px; background: rgba(255,53,62,.2); filter: blur(2px);
        }
        .hero-eyebrow { color: #FDA4AF; font-size: .7rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
        .hero-title { color: white; font-size: 2rem; font-weight: 850; letter-spacing: -.035em; margin: 7px 0 6px; }
        .hero-copy { color: #CBD5E1; max-width: 650px; font-size: .9rem; }
        .kpi-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin: 0 0 24px; }
        .kpi-card {
            position:relative; overflow:hidden; background:#FFF; border:1px solid var(--solvit-border);
            border-radius:17px; padding:18px 19px; box-shadow:0 3px 12px rgba(15,23,42,.045);
        }
        .kpi-card:before { content:""; position:absolute; inset:0 auto 0 0; width:4px; background:var(--accent); }
        .kpi-label { color:#64748B; font-size:.69rem; line-height:1.25; font-weight:800; letter-spacing:.055em; text-transform:uppercase; }
        .kpi-value { color:#0F172A; font-size:1.75rem; line-height:1; font-weight:850; letter-spacing:-.035em; margin:13px 0 8px; }
        .kpi-note { color:#94A3B8; font-size:.71rem; font-weight:550; }
        .section-card { background:#FFF; border:1px solid var(--solvit-border); border-radius:18px; padding:4px 18px 16px; }
        .login-wrap { max-width:470px; margin:8vh auto 0; text-align:center; }
        .solvit-logo { display:block;height:auto;object-fit:contain;max-width:100%; }
        .login-logo { width:220px;margin:0 auto 20px; }
        .header-logo { width:160px;flex-shrink:0; }
        .sidebar-logo { width:170px; }
        .login-title { color:#0F172A;font-size:2rem;font-weight:850;letter-spacing:-.04em;margin-bottom:8px; }
        .login-copy { color:#64748B;font-size:.88rem;line-height:1.55;margin:0 auto 28px;max-width:380px; }
        .sidebar-brand { display:flex;flex-direction:column;align-items:flex-start;gap:10px;padding:5px 2px 18px;border-bottom:1px solid #E2E8F0;margin-bottom:18px; }
        .sidebar-product { color:#94A3B8;font-size:.64rem;font-weight:700;text-transform:uppercase;letter-spacing:.055em;margin-top:4px; }
        .workspace-card { background:linear-gradient(145deg,#111827,#1E293B);border:1px solid #334155;border-radius:14px;padding:14px;margin:0 0 22px;box-shadow:0 8px 20px rgba(15,23,42,.10); }
        .workspace-label { color:#94A3B8;font-size:.61rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em; }
        .workspace-name { color:#F8FAFC;font-size:.8rem;font-weight:750;margin-top:6px;display:flex;align-items:center;justify-content:space-between; }
        .live-dot { display:inline-flex;align-items:center;gap:5px;color:#047857;font-size:.63rem;font-weight:800; }
        .live-dot:before { content:"";width:7px;height:7px;border-radius:50%;background:#10B981;box-shadow:0 0 0 3px #D1FAE5; }
        .sidebar-section { color:#94A3B8;font-size:.62rem;font-weight:850;text-transform:uppercase;letter-spacing:.09em;margin:7px 0 3px; }
        .sidebar-footer { margin-top:22px;padding:11px 12px;border-radius:12px;background:#F8FAFC;border:1px solid #E2E8F0;color:#64748B;font-size:.65rem;line-height:1.45; }
        .sidebar-footer strong { color:#334155; }
        @media (max-width: 900px) { .kpi-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
        @media (max-width: 560px) { .kpi-grid { grid-template-columns:1fr; } .dashboard-hero{padding:24px;} }
        @media (max-width: 560px) { .solvit-brand { flex-wrap:wrap; } }
        .solvit-title { color: var(--solvit-text); font-size: 1.25rem; line-height: 1.1; font-weight: 800; }
        .solvit-subtitle { color: var(--solvit-muted); font-size: .76rem; font-weight: 500; margin-top: 4px; }
        .solvit-pill {
            display: inline-block; margin-left: 8px; padding: 3px 8px; border-radius: 999px;
            color: var(--solvit-red); background: rgba(255,53,62,.09);
            font-size: .62rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_brand_header():
    st.markdown(
        f"""
        <div class="solvit-brand">
          <img class="solvit-logo header-logo" src="{SOLVIT_LOGO_URI}" alt="Solvit" width="289" height="98">
          <div>
            <div class="solvit-title">Reporting &amp; SLA Portal</div>
            <div class="solvit-subtitle">Operational performance, ticket health and service accountability</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_login_header():
    st.markdown(
        f"""
        <div class="login-wrap">
          <img class="solvit-logo login-logo" src="{SOLVIT_LOGO_URI}" alt="Solvit" width="289" height="98">
          <div class="login-title">Reporting Portal</div>
          <div class="login-copy">A private workspace for operational performance, ticket health and SLA accountability.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard_hero():
    st.markdown(
        """
        <div class="dashboard-hero">
          <div class="hero-eyebrow">Solvit · Operations intelligence</div>
          <div class="hero-title">Service performance at a glance</div>
          <div class="hero-copy">Track ticket flow, surface SLA risk early and keep every operational handoff accountable.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_cards(cards):
    html = '<div class="kpi-grid">'
    for label, value, note, color in cards:
        html += (
            f'<div class="kpi-card" style="--accent:{escape(color)}">'
            f'<div class="kpi-label">{escape(str(label))}</div>'
            f'<div class="kpi-value">{escape(str(value))}</div>'
            f'<div class="kpi-note">{escape(str(note))}</div></div>'
        )
    st.markdown(html + "</div>", unsafe_allow_html=True)


def render_sidebar_header():
    st.sidebar.markdown(
        f"""
        <div class="sidebar-brand">
          <img class="solvit-logo sidebar-logo" src="{SOLVIT_LOGO_URI}" alt="Solvit" width="289" height="98">
          <div class="sidebar-product">Reporting Portal</div>
        </div>
        <div class="workspace-card">
          <div class="workspace-label">Internal workspace</div>
          <div class="workspace-name"><span>IT Support</span><span class="live-dot">LIVE</span></div>
        </div>
        <div class="sidebar-section">Report controls</div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_footer():
    st.sidebar.markdown(
        """
        <div class="sidebar-footer"><strong>PostgreSQL connected</strong><br>Operational request data is live and secured.</div>
        """,
        unsafe_allow_html=True,
    )
