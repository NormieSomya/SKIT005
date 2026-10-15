import streamlit as st


def apply_theme(theme_name="Government Slate"):
    """Apply a selectable, restrained government-portal theme.

    The design intentionally avoids neon accents, gradients, glass effects and
    decorative AI imagery. It uses an editorial layout, accessible contrast,
    official navy, a restrained saffron accent and a subtle green status color.
    """
    st.markdown(r"""
    <style>
    :root {
      --page: #F3F5F7;
      --surface: #FFFFFF;
      --surface-muted: #F8F9FB;
      --navy: #183653;
      --navy-deep: #112A43;
      --navy-soft: #EAF0F6;
      --ink: #202B36;
      --muted: #5E6B78;
      --line: #D7DEE5;
      --saffron: #B66B22;
      --saffron-soft: #FBF2E8;
      --green: #276749;
      --green-soft: #EAF5EE;
      --red: #9F3434;
      --red-soft: #FBECEC;
      --amber: #875A12;
      --amber-soft: #FFF5DD;
    }

    html, body, [class*="css"] {
      font-family: "Segoe UI", "Noto Sans", Arial, sans-serif;
      color: var(--ink);
    }
    .stApp { background: var(--page); color: var(--ink); }
    [data-testid="stHeader"] { background: rgba(243,245,247,.96); }
    .block-container { max-width: 1600px; padding-top: 1.55rem; padding-bottom: 3rem; }

    /* Sidebar: formal, quiet, high-contrast navigation */
    [data-testid="stSidebar"] {
      background: var(--surface);
      border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }
    [data-testid="stSidebar"] .stButton button {
      text-align: left; justify-content: flex-start; min-height: 42px;
      border-radius: 6px; border: 1px solid transparent;
      background: transparent; color: #425365; font-weight: 500;
      box-shadow: none;
    }
    [data-testid="stSidebar"] .stButton button[kind="primary"] {
      background: var(--navy-soft); color: var(--navy-deep);
      border-color: #CBD7E3; border-left: 3px solid var(--saffron);
      font-weight: 700;
    }
    [data-testid="stSidebar"] .stButton button:hover {
      background: #F0F3F6; border-color: #D7DEE5; color: var(--navy-deep);
    }
    .brand { display:flex; gap:11px; align-items:center; padding:6px 3px 22px; border-bottom:1px solid var(--line); margin-bottom:20px; }
    .brand-mark { width:42px; height:42px; border-radius:5px; background:var(--navy); display:grid; place-items:center; color:white; font-size:14px; font-weight:800; letter-spacing:.5px; border-bottom:3px solid var(--saffron); }
    .brand-name { font-size:22px; font-weight:750; color:var(--navy-deep); letter-spacing:-.45px; line-height:1.2; }
    .brand-sub { font-size:9px; letter-spacing:1.15px; color:#647486; font-weight:700; margin-top:4px; }
    .side-label { font-size:10px; color:#68798A; letter-spacing:1.25px; font-weight:750; margin:0 0 8px 8px; }
    .side-note { margin-top:24px; padding:13px; border:1px solid var(--line); border-top:3px solid var(--saffron); border-radius:5px; background:#FAFBFC; font-size:11px; color:var(--muted); line-height:1.75; }
    .side-note b { color:var(--navy); }

    /* Page hierarchy */
    .eyebrow { font-size:10px; letter-spacing:1.45px; color:var(--saffron); font-weight:800; margin-bottom:7px; }
    .page-title { font-size:29px; font-weight:750; color:var(--navy-deep); letter-spacing:-.55px; line-height:1.22; }
    .page-subtitle { font-size:13px; color:var(--muted); margin-top:7px; margin-bottom:16px; max-width:950px; line-height:1.6; }
    .section-title { font-size:16px; font-weight:750; color:var(--navy); }
    .section-subtitle { font-size:11px; color:var(--muted); margin-top:4px; margin-bottom:13px; }

    /* Cards: square-ish edges and no decorative gradients */
    .metric { background:var(--surface); border:1px solid var(--line); border-top:3px solid var(--navy); border-radius:5px; padding:16px 17px; min-height:112px; box-shadow:0 1px 2px rgba(24,54,83,.035); }
    .metric-label { font-size:10px; text-transform:uppercase; letter-spacing:.7px; color:#5B6977; font-weight:750; }
    .metric-value { font-size:29px; font-weight:750; color:var(--navy-deep); margin-top:9px; line-height:1.1; }
    .metric-note { font-size:10px; color:#687787; margin-top:5px; }
    .metric-icon { float:right; color:var(--saffron); font-size:18px; }
    .panel { background:var(--surface); border:1px solid var(--line); border-radius:5px; padding:16px; }
    .panel-title { font-size:14px; font-weight:750; color:var(--navy); }
    .panel-note { font-size:11px; color:var(--muted); margin-top:4px; margin-bottom:12px; }
    .callout { padding:12px 14px; border:1px solid #CAD7E4; border-left:4px solid var(--navy); border-radius:4px; background:#F1F5F9; color:#344B61; margin-bottom:14px; font-size:12px; line-height:1.65; }
    .callout.warn { background:var(--amber-soft); border-color:#E8D4A6; border-left-color:#B17A1E; color:#684A17; }
    .callout.success { background:var(--green-soft); border-color:#C5E0CF; border-left-color:var(--green); color:#24583D; }

    /* Workflow labels */
    .pill { display:inline-block; border-radius:3px; padding:4px 8px; font-size:10px; font-weight:750; border:1px solid #D1D9E1; background:#F0F3F6; color:#425365; }
    .pill.pending { background:var(--amber-soft); border-color:#E7D3A1; color:var(--amber); }
    .pill.approved, .pill.published { background:var(--green-soft); border-color:#C6E1D0; color:var(--green); }
    .pill.changes, .pill.rejected { background:var(--red-soft); border-color:#E9C7C7; color:var(--red); }
    .pill.draft { background:#EEF1F4; color:#566574; }
    .doc-card { background:var(--surface); border:1px solid var(--line); border-radius:5px; padding:14px; margin-bottom:10px; }
    .doc-id { font-size:9px; letter-spacing:1px; color:var(--saffron); font-weight:800; }
    .doc-title { font-size:14px; font-weight:750; color:var(--navy); margin-top:5px; }
    .muted { font-size:11px; color:var(--muted); }
    .preview-document { background:#FFFFFF; color:#252D35; border:1px solid #D7DDE3; border-top:5px solid var(--navy); border-radius:2px; padding:30px 34px; min-height:390px; box-shadow:0 2px 8px rgba(17,42,67,.06); }
    .preview-kicker { font-size:9px; letter-spacing:.8px; color:#657484; font-weight:750; margin-bottom:17px; text-transform:uppercase; }
    .preview-title { font-family:Georgia, "Times New Roman", serif; font-size:24px; font-weight:700; line-height:1.3; color:#183653; margin-bottom:14px; }
    .preview-summary { border-left:3px solid var(--saffron); padding-left:12px; color:#4B5B6A; font-weight:600; font-size:13px; line-height:1.7; margin-bottom:16px; }
    .preview-body { font-family:Georgia, "Times New Roman", serif; font-size:13px; line-height:1.9; color:#303943; white-space:pre-wrap; }
    .detail-row { display:flex; justify-content:space-between; gap:10px; padding:9px 0; border-bottom:1px solid var(--line); font-size:11px; }
    .detail-row span { color:var(--muted); }
    .detail-row b { color:var(--navy); text-align:right; }
    .flag { padding:10px 11px; margin:7px 0; background:var(--amber-soft); border:1px solid #E7D3A1; border-radius:4px; color:#684A17; font-size:11px; }
    .source-row { padding:11px 0; border-bottom:1px solid #E5E9ED; }
    .source-title { font-size:12px; font-weight:750; color:var(--navy); }
    .source-meta { font-size:10px; color:#687787; margin-top:4px; }
    .timeline { border-left:1px solid #CCD5DE; margin-left:7px; padding-left:16px; }
    .timeline-item { margin:0 0 15px; }
    .timeline-item b { font-size:11px; color:var(--navy); }
    .timeline-item p { font-size:10px; color:var(--muted); margin:3px 0; }

    /* Inputs and native Streamlit controls */
    .stMarkdown p, .stMarkdown li { color:#344250; }
    label { color:#405162 !important; font-size:12px !important; font-weight:600 !important; }
    input, textarea { background:#FFFFFF !important; color:var(--ink) !important; border-color:#C8D1DA !important; border-radius:4px !important; }
    input:focus, textarea:focus { border-color:#426B91 !important; box-shadow:0 0 0 1px #426B91 !important; }
    [data-baseweb="select"] > div { background:#FFFFFF; border-color:#C8D1DA; border-radius:4px; color:var(--ink); }
    [data-testid="stForm"] { background:var(--surface); border:1px solid var(--line); border-radius:5px; padding:18px; }
    div.stButton > button, div.stDownloadButton > button, div.stFormSubmitButton > button { border-radius:4px; min-height:39px; font-weight:650; box-shadow:none; }
    div.stButton > button[kind="primary"], div.stFormSubmitButton > button[kind="primary"] { background:var(--navy); border:1px solid var(--navy); color:#FFFFFF; }
    div.stButton > button[kind="primary"]:hover, div.stFormSubmitButton > button[kind="primary"]:hover { background:#234C70; border-color:#234C70; }
    div.stButton > button[kind="secondary"], div.stDownloadButton > button[kind="secondary"] { background:#FFFFFF; border:1px solid #C8D1DA; color:#2F4357; }
    div.stButton > button[kind="secondary"]:hover, div.stDownloadButton > button[kind="secondary"]:hover { background:#F1F4F7; border-color:#9EADBB; color:var(--navy-deep); }
    [data-testid="stMetric"] { background:#FFFFFF; border:1px solid var(--line); border-radius:5px; padding:12px; }
    [data-testid="stMetricLabel"] { color:#5B6977; }
    [data-testid="stMetricValue"] { color:var(--navy); }
    hr { border-color:var(--line); }
    [data-testid="stTabs"] button { color:#526272; }
    [data-testid="stTabs"] button[aria-selected="true"] { color:var(--navy); border-bottom-color:var(--saffron); }
    [data-testid="stExpander"] { background:#FFFFFF; border:1px solid var(--line); border-radius:4px; }
    [data-testid="stAlert"] { border-radius:4px; }
    a { color:#235A85; }
    footer { visibility:hidden; }
    @media (max-width: 900px) {
      .block-container { padding-top:1rem; }
      .page-title { font-size:24px; }
      .preview-document { padding:20px; }
    }
    </style>
    """, unsafe_allow_html=True)

    # Theme variants are intentionally administrative rather than decorative.
    # Government Slate is the default: lower glare without losing document clarity.
    if theme_name == "Official Light":
        st.markdown("""<style>:root { --page:#F3F5F7; --surface:#FFFFFF; --surface-muted:#F8F9FB; --navy:#183653; --navy-deep:#112A43; --navy-soft:#EAF0F6; --ink:#202B36; --muted:#5E6B78; --line:#D7DEE5; --saffron:#B66B22; }</style>""", unsafe_allow_html=True)
    elif theme_name == "Government Slate":
        st.markdown("""<style>
        :root { --page:#E9EDF1; --surface:#F8FAFC; --surface-muted:#F0F3F6; --navy:#203D59; --navy-deep:#142C43; --navy-soft:#E0E8F0; --ink:#253341; --muted:#596A79; --line:#CDD5DD; --saffron:#A96525; }
        .stApp { background:var(--page); }
        [data-testid="stHeader"] { background:rgba(233,237,241,.97); }
        .metric, .panel, .doc-card, [data-testid="stMetric"], [data-testid="stForm"], [data-testid="stExpander"] { background:var(--surface); }
        .side-note { background:#F0F3F6; }
        input, textarea, [data-baseweb="select"] > div { background:#FBFCFD !important; }
        </style>""", unsafe_allow_html=True)
    else:  # Dark Office
        st.markdown("""<style>
        :root { --page:#17222E; --surface:#202E3C; --surface-muted:#263645; --navy:#AFC7DF; --navy-deep:#E3ECF5; --navy-soft:#2A4054; --ink:#E5EBF1; --muted:#B2BFCC; --line:#3B4C5C; --saffron:#D6A15F; --green:#7FC59B; --green-soft:#203E32; --red:#E59A9A; --red-soft:#472D32; --amber:#E8C37C; --amber-soft:#433A28; }
        .stApp { background:var(--page); color:var(--ink); }
        [data-testid="stHeader"] { background:rgba(23,34,46,.97); }
        [data-testid="stSidebar"] { background:#111B25; border-right:1px solid var(--line); }
        [data-testid="stSidebar"] .stButton button { color:#D6E0E9; }
        [data-testid="stSidebar"] .stButton button:hover { background:#263645; border-color:#46596B; color:#FFFFFF; }
        [data-testid="stSidebar"] .stButton button[kind="primary"] { background:#2A4054; color:#FFFFFF; border-color:#526A80; }
        .brand-name,.page-title,.section-title,.panel-title,.doc-title,.detail-row b,.timeline-item b,.source-title,.metric-value { color:var(--navy-deep); }
        .brand-sub,.side-label,.muted,.metric-label,.metric-note,.panel-note,.section-subtitle,.page-subtitle,.source-meta,.detail-row span,.timeline-item p { color:var(--muted); }
        .metric,.panel,.doc-card,[data-testid="stMetric"],[data-testid="stForm"],[data-testid="stExpander"], [data-testid="stAlert"] { background:var(--surface); border-color:var(--line); color:var(--ink); }
        .side-note { background:#202E3C; border-color:var(--line); color:var(--muted); }
        .callout { background:#263645; border-color:#40576B; color:#D7E3EE; }
        .callout.warn,.flag { background:var(--amber-soft); border-color:#6A5935; color:#F0D7A1; }
        .callout.success { background:var(--green-soft); border-color:#355D48; color:#B8E4C8; }
        .pill { background:#2B3947; border-color:#4A5B6B; color:#D9E2EA; }
        .pill.pending { background:var(--amber-soft); border-color:#6A5935; color:#F0D7A1; }
        .pill.approved,.pill.published { background:var(--green-soft); border-color:#355D48; color:#B8E4C8; }
        .pill.changes,.pill.rejected { background:var(--red-soft); border-color:#70434A; color:#F1BABA; }
        .pill.draft { background:#2B3947; color:#C4D0DB; }
        .preview-document { background:#FDFDFB; color:#252D35; border-color:#526171; }
        .preview-title { color:#183653; }
        .preview-summary { color:#4B5B6A; }
        .preview-body { color:#303943; }
        .stMarkdown p,.stMarkdown li { color:var(--ink); }
        label { color:#D1DCE6 !important; }
        input,textarea { background:#182531 !important; color:#EDF3F8 !important; border-color:#4A5C6D !important; }
        input::placeholder,textarea::placeholder { color:#9EADBA !important; }
        [data-baseweb="select"] > div { background:#182531 !important; border-color:#4A5C6D !important; color:#EDF3F8 !important; }
        div.stButton > button[kind="secondary"],div.stDownloadButton > button[kind="secondary"] { background:#263645; border-color:#4A5C6D; color:#E2EAF1; }
        div.stButton > button[kind="secondary"]:hover,div.stDownloadButton > button[kind="secondary"]:hover { background:#31485C; color:#FFFFFF; }
        div.stButton > button[kind="primary"],div.stFormSubmitButton > button[kind="primary"] { background:#355875; border-color:#52728E; color:#FFFFFF; }
        [data-testid="stMetricLabel"] { color:var(--muted); }
        [data-testid="stMetricValue"] { color:var(--navy-deep); }
        [data-testid="stTabs"] button { color:#C1CDD8; }
        [data-testid="stTabs"] button[aria-selected="true"] { color:#FFFFFF; border-bottom-color:var(--saffron); }
        [data-testid="stExpander"] summary { color:var(--ink); }
        hr { border-color:var(--line); }
        a { color:#9BC9F2; }
        </style>""", unsafe_allow_html=True)
