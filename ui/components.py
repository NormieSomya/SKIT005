import html
import streamlit as st

def page_header(kicker, title, subtitle, status="SKIT005 · HUMAN REVIEW REQUIRED"):
    st.markdown(f'<div class="eyebrow">{html.escape(kicker)}</div><div class="page-title">{html.escape(title)}</div><div class="page-subtitle">{html.escape(subtitle)}</div><div class="pill">{html.escape(status)}</div>', unsafe_allow_html=True)
    st.write("")

def metric_card(label, value, note, icon="◈"):
    st.markdown(f'<div class="metric"><span class="metric-icon">{icon}</span><div class="metric-label">{html.escape(str(label))}</div><div class="metric-value">{html.escape(str(value))}</div><div class="metric-note">{html.escape(str(note))}</div></div>', unsafe_allow_html=True)

def status_pill(status):
    s = status.lower()
    cls = "approved" if status == "Approved" else "published" if status == "Published" else "changes" if status in ("Changes Requested", "Rejected") else "pending" if status in ("In Review", "Pending Review", "Verification Required") else "draft"
    st.markdown(f'<span class="pill {cls}">{html.escape(status)}</span>', unsafe_allow_html=True)

def empty_state(title, body):
    st.markdown(f'<div class="panel" style="text-align:center;padding:35px"><div class="panel-title">{html.escape(title)}</div><div class="panel-note">{html.escape(body)}</div></div>', unsafe_allow_html=True)

def preview_document(d):
    headline=html.escape(d.get("headline", "Untitled press note"))
    department=html.escape(d.get("department") or "OFFICIAL COMMUNICATION")
    date=html.escape(d.get("date", "Date not supplied"))
    summary=html.escape(d.get("summary", ""))
    body=html.escape(d.get("body", "")).replace("\n", "<br><br>")
    st.markdown(f'<div class="preview-document"><div class="preview-kicker">{department} &nbsp; / &nbsp; {date}</div><div class="preview-title">{headline}</div><div class="preview-summary">{summary}</div><div class="preview-body">{body}</div></div>', unsafe_allow_html=True)
