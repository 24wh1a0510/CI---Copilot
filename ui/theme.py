"""Design tokens and injected CSS for the premium dark dashboard theme.

Palette: "Signal Intelligence" — obsidian + burnt copper + verdigris teal.
Deliberately avoids the generic blue/purple SaaS-AI gradient in favor of a
warmer, radar-room / espionage-briefing aesthetic.

IMPORTANT: this CSS assumes .streamlit/config.toml sets [theme] base="dark".
Without that, Streamlit's own light-theme defaults win on many native widgets
(checkboxes, selects, expanders, tabs) because they're rendered with inline
styles Streamlit computes from the active theme, not just classes this CSS can
override. Ship both files together.
"""

CSS = """
<style>
:root {
  --bg-0: #0c0a08;
  --bg-1: #16110c;
  --panel: rgba(255,244,230,0.05);
  --panel-2: rgba(255,244,230,0.08);
  --panel-border: rgba(255,200,140,0.14);
  --accent-copper: #d9822b;
  --accent-copper-hi: #ffab5c;
  --accent-teal: #2fb8a6;
  --accent-gradient: linear-gradient(135deg, #d9822b 0%, #b5541f 100%);
  --text-hi: #f6ede1;
  --text-mid: #d4c4ae;
  --text-dim: #93826d;
  --success: #2fb8a6;
  --warn: #e0a63a;
  --danger: #e5573f;
  --radius: 16px;
}

/* ---- Base app shell ---- */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
  background:
    radial-gradient(1100px 550px at 12% -8%, rgba(217,130,43,0.14), transparent 60%),
    radial-gradient(950px 650px at 108% 8%, rgba(47,184,166,0.10), transparent 60%),
    repeating-linear-gradient(115deg, rgba(255,200,140,0.015) 0px, rgba(255,200,140,0.015) 1px, transparent 1px, transparent 42px),
    var(--bg-0) !important;
  color: var(--text-hi);
}
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stToolbar"] { background: transparent !important; }
.main .block-container { padding-top: 2rem; }

/* ---- Sidebar ---- */
section[data-testid="stSidebar"], section[data-testid="stSidebar"] > div {
  background: #110d09 !important;
  border-right: 1px solid var(--panel-border);
}
section[data-testid="stSidebar"] * { color: var(--text-mid) !important; font-size: 17px !important; }
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color: var(--text-hi) !important; }

/* ---- Typography ---- */
h1, h2, h3, h4, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
  color: var(--text-hi) !important; letter-spacing: -0.01em;
}
h1 { font-size: 36px !important; font-weight: 800 !important; }
h2 { font-size: 23px !important; font-weight: 700 !important; margin-top: 0.7em !important; }
h3 { font-size: 19px !important; font-weight: 650 !important; }
p, li, span, label, .stMarkdown, .stCaption, [data-testid="stMarkdownContainer"] {
  color: var(--text-mid) !important;
}
[data-testid="stCaptionContainer"] { color: var(--text-dim) !important; }

/* ---- Text inputs / number inputs / textareas ---- */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
[data-baseweb="input"] input, [data-baseweb="base-input"] {
  background: var(--panel-2) !important;
  color: var(--text-hi) !important;
  border: 1px solid var(--panel-border) !important;
  border-radius: 10px !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {
  color: var(--text-dim) !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
  border-color: var(--accent-copper) !important;
  box-shadow: 0 0 0 1px var(--accent-copper) !important;
}
[data-baseweb="input"] { background: transparent !important; }

/* Number input +/- steppers */
.stNumberInput button {
  background: var(--panel-2) !important;
  border: 1px solid var(--panel-border) !important;
  color: var(--text-hi) !important;
}

/* ---- Selectbox / dropdowns ---- */
[data-baseweb="select"] > div {
  background: var(--panel-2) !important;
  border-color: var(--panel-border) !important;
  color: var(--text-hi) !important;
}
[data-baseweb="popover"] ul, [data-baseweb="menu"] {
  background: #17120c !important;
  border: 1px solid var(--panel-border) !important;
}
[data-baseweb="menu"] li { color: var(--text-mid) !important; }
[data-baseweb="menu"] li:hover { background: rgba(217,130,43,0.15) !important; }

/* ---- Checkboxes ---- */
.stCheckbox label span { color: var(--text-mid) !important; }
.stCheckbox [data-baseweb="checkbox"] > div:first-child {
  background: var(--panel-2) !important;
  border-color: var(--panel-border) !important;
}
.stCheckbox [aria-checked="true"] > div:first-child {
  background: var(--accent-copper) !important;
  border-color: var(--accent-copper) !important;
}

/* ---- Buttons ---- */
.stButton>button, .stFormSubmitButton>button {
  background: var(--accent-gradient) !important;
  color: #1a0f04 !important;
  border: none !important;
  border-radius: 12px !important;
  font-weight: 750 !important;
  font-size: 17px !important;
  padding: 0.55em 1.2em !important;
  box-shadow: 0 6px 20px rgba(217,130,43,0.28) !important;
  transition: filter 0.15s ease, transform 0.15s ease;
}
.stButton>button:hover { filter: brightness(1.1); transform: translateY(-1px); }
.stButton>button:active { transform: translateY(0); }
.stButton>button[kind="secondary"] {
  background: var(--panel-2) !important;
  color: var(--text-hi) !important;
  border: 1px solid var(--panel-border) !important;
  box-shadow: none !important;
}

.stDownloadButton>button {
  background: var(--panel-2) !important;
  color: var(--text-hi) !important;
  border: 1px solid var(--panel-border) !important;
  border-radius: 12px !important;
  font-size: 16px !important;
}
.stDownloadButton>button:hover { border-color: var(--accent-copper) !important; }

/* ---- Expanders ---- */
[data-testid="stExpander"] {
  background: var(--panel) !important;
  border: 1px solid var(--panel-border) !important;
  border-radius: var(--radius) !important;
  overflow: hidden;
}
[data-testid="stExpander"] summary {
  color: var(--text-hi) !important;
  background: var(--panel-2) !important;
}
[data-testid="stExpander"] svg { fill: var(--text-mid) !important; }

/* ---- Tabs ---- */
[data-baseweb="tab-list"] {
  background: transparent !important;
  border-bottom: 1px solid var(--panel-border) !important;
  gap: 4px;
}
[data-baseweb="tab"] {
  color: var(--text-dim) !important;
  font-size: 16px !important;
  font-weight: 600 !important;
  background: transparent !important;
  border-radius: 10px 10px 0 0 !important;
}
[data-baseweb="tab"]:hover { color: var(--text-hi) !important; background: var(--panel) !important; }
[data-baseweb="tab"][aria-selected="true"] {
  color: var(--accent-copper-hi) !important;
  border-bottom: 2px solid var(--accent-copper) !important;
}
[data-baseweb="tab-highlight"] { background: var(--accent-copper) !important; }

/* ---- Metrics ---- */
[data-testid="stMetric"] {
  background: var(--panel); border: 1px solid var(--panel-border);
  border-radius: 14px; padding: 12px 16px;
}
[data-testid="stMetricLabel"] { color: var(--text-dim) !important; }
[data-testid="stMetricValue"] { color: var(--text-hi) !important; font-weight: 800 !important; }

/* ---- Alerts (info/success/warning/error) ---- */
[data-testid="stAlert"] {
  border-radius: 12px !important;
  border: 1px solid var(--panel-border) !important;
  background: var(--panel) !important;
}
[data-testid="stAlertContentInfo"] { color: var(--text-mid) !important; }
div[data-baseweb="notification"] { background: var(--panel) !important; }

/* ---- Progress bar ---- */
.stProgress > div > div { background: var(--accent-gradient) !important; }
.stProgress > div { background: var(--panel-2) !important; }

/* ---- Dividers ---- */
hr { border-color: var(--panel-border) !important; }

/* ---- Custom components used across the app ---- */
.glass-card {
  background: var(--panel);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  padding: 20px 22px;
  backdrop-filter: blur(14px);
  box-shadow: 0 8px 30px rgba(0,0,0,0.45);
  margin-bottom: 16px;
}

.app-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 22px 26px; border-radius: var(--radius);
  background: linear-gradient(120deg, rgba(217,130,43,0.18), rgba(47,184,166,0.09));
  border: 1px solid var(--panel-border);
  margin-bottom: 22px;
  position: relative;
  overflow: hidden;
}
.app-header::after {
  content: ""; position: absolute; top: -50%; right: -8%; width: 340px; height: 340px;
  border-radius: 50%; border: 1px solid rgba(255,200,140,0.14);
  box-shadow: 0 0 0 40px rgba(255,200,140,0.03), 0 0 0 80px rgba(255,200,140,0.02);
  pointer-events: none;
}
.app-header .title { font-size: 30px; font-weight: 800; color: var(--text-hi); }
.app-header .subtitle { font-size: 15px; color: var(--text-dim); margin-top: 4px; }

.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 20px; }
.kpi-card {
  background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px;
  padding: 16px 18px;
}
.kpi-label { font-size: 13px; color: var(--text-dim) !important; text-transform: uppercase; letter-spacing: 0.06em; }
.kpi-value { font-size: 28px; font-weight: 800; color: var(--text-hi) !important; margin-top: 4px; }
.kpi-value.accent { background: var(--accent-gradient); -webkit-background-clip: text; background-clip: text; color: transparent !important; }

.badge {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 11px; border-radius: 999px;
  font-size: 13px; font-weight: 650; border: 1px solid transparent;
}
.badge-ok { background: rgba(47,184,166,0.16); color: var(--success) !important; border-color: rgba(47,184,166,0.4); }
.badge-warn { background: rgba(224,166,58,0.16); color: var(--warn) !important; border-color: rgba(224,166,58,0.4); }
.badge-danger { background: rgba(229,87,63,0.16); color: var(--danger) !important; border-color: rgba(229,87,63,0.4); }
.badge-run { background: rgba(217,130,43,0.18); color: var(--accent-copper-hi) !important; border-color: rgba(217,130,43,0.45); }

.timeline-item { display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px dashed var(--panel-border); }
.timeline-dot { width: 10px; height: 10px; border-radius: 50%; margin-top: 6px; flex: none; }
.timeline-time { font-size: 12px; color: var(--text-dim) !important; min-width: 90px; }
.timeline-text { font-size: 14px; color: var(--text-mid) !important; }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: rgba(255,200,140,0.14); border-radius: 8px; }
::-webkit-scrollbar-track { background: transparent; }
</style>
"""
