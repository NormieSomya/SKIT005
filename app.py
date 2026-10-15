from __future__ import annotations
# Original PressAI backend functions preserved from the existing project.
import os
import re
import difflib
import sqlite3
import requests
import streamlit as st
from pathlib import Path
from datetime import datetime
from html import escape as html_escape
from weasyprint import HTML

OLLAMA_API_URL = "http://localhost:11434/api/chat"
LOCAL_MODEL = "gemma4:12b"
DB_PATH = Path(__file__).resolve().parent / "press_note_history.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_history_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS press_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            institution_name TEXT NOT NULL DEFAULT '',
            press_note_no TEXT NOT NULL DEFAULT '',
            event_name TEXT NOT NULL DEFAULT '',
            draft_length TEXT NOT NULL DEFAULT 'Detailed',
            language TEXT NOT NULL DEFAULT 'Hindi',
            input_json TEXT NOT NULL DEFAULT '{}',
            original_draft TEXT NOT NULL DEFAULT '',
            current_draft TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Draft'
        );
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL,
            captured_at TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_text TEXT NOT NULL,
            FOREIGN KEY(note_id) REFERENCES press_notes(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL,
            saved_at TEXT NOT NULL,
            revision_type TEXT NOT NULL,
            draft_text TEXT NOT NULL,
            change_summary TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(note_id) REFERENCES press_notes(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL,
            occurred_at TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(note_id) REFERENCES press_notes(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_notes_updated ON press_notes(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_revisions_note ON revisions(note_id, saved_at DESC);
        """)

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def log_history_action(note_id, action, details=""):
    if not note_id:
        return
    with get_db() as conn:
        conn.execute(
            "INSERT INTO audit_log(note_id, occurred_at, action, details) VALUES (?, ?, ?, ?)",
            (int(note_id), now_iso(), action, details),
        )

def create_history_record(data, language, draft_length, original_draft):
    stamp = now_iso()
    with get_db() as conn:
        cur = conn.execute("""INSERT INTO press_notes
            (created_at, updated_at, institution_name, press_note_no, event_name,
             draft_length, language, input_json, original_draft, current_draft, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft')""",
            (stamp, stamp, data.get("institution_name", ""), data.get("press_note_no", ""),
             data.get("event_name", ""), st.session_state.get("last_length", draft_length), language,
             json.dumps(data, ensure_ascii=False), original_draft, original_draft))
        note_id = cur.lastrowid
        conn.execute("INSERT INTO revisions(note_id, saved_at, revision_type, draft_text, change_summary) VALUES (?, ?, ?, ?, ?)",
                     (note_id, stamp, "AI generated", original_draft, "Initial AI-generated draft"))
        conn.execute("INSERT INTO audit_log(note_id, occurred_at, action, details) VALUES (?, ?, ?, ?)",
                     (note_id, stamp, "Generated", f"Language={language}; format={draft_length}"))
        # Preserve a source snapshot of the structured inputs used for this note.
        source_fields = {
            "Verified facts": data.get("facts", ""),
            "Verified quotation": data.get("quotes", ""),
            "Additional context / instructions": data.get("background", ""),
            "Structured input snapshot": json.dumps(data, ensure_ascii=False, indent=2),
        }
        for source_type, source_text in source_fields.items():
            if source_text:
                conn.execute("INSERT INTO sources(note_id, captured_at, source_type, source_text) VALUES (?, ?, ?, ?)",
                             (note_id, stamp, source_type, source_text))
    return note_id

def save_history_revision(note_id, draft_text, revision_type="Manual save", summary="Saved current draft"):
    if not note_id:
        return
    stamp = now_iso()
    with get_db() as conn:
        conn.execute("UPDATE press_notes SET current_draft=?, updated_at=? WHERE id=?", (draft_text, stamp, int(note_id)))
        conn.execute("INSERT INTO revisions(note_id, saved_at, revision_type, draft_text, change_summary) VALUES (?, ?, ?, ?, ?)",
                     (int(note_id), stamp, revision_type, draft_text, summary))
        conn.execute("INSERT INTO audit_log(note_id, occurred_at, action, details) VALUES (?, ?, ?, ?)",
                     (int(note_id), stamp, revision_type, summary))

def load_history_record(note_id):
    with get_db() as conn:
        note = conn.execute("SELECT * FROM press_notes WHERE id=?", (int(note_id),)).fetchone()
    if not note:
        return False
    st.session_state["current_note_id"] = int(note["id"])
    st.session_state["draft"] = note["current_draft"]
    st.session_state["original_draft"] = note["original_draft"]
    st.session_state["editable_draft"] = note["current_draft"]
    st.session_state["last_data"] = json.loads(note["input_json"] or "{}")
    st.session_state["last_language"] = note["language"]
    st.session_state["last_length"] = note["draft_length"]
    st.session_state["last_headline"] = split_press_note(note["current_draft"])[0] or "Press_Note"
    st.session_state["show_draft_diff"] = False
    log_history_action(note["id"], "Loaded from history", "Loaded saved draft into Review Desk")
    return True

def make_prompt(data, language_choice, length_choice):
    lang_rule = {
        "Hindi": (
            "OUTPUT LANGUAGE IS HINDI ONLY. Write all headings and sentences in formal, clear Hindi using Devanagari script. "
            "Translate English input into Hindi. Do not include an English version."
        ),
        "English": (
            "OUTPUT LANGUAGE IS ENGLISH ONLY. Use formal, clear English in Latin script. Translate Hindi input into English. "
            "Do not output Devanagari text. Use [REQUIRES CONFIRMATION] for missing facts."
        ),
        "Bilingual": (
            "OUTPUT LANGUAGE IS BILINGUAL. First provide the complete Hindi version in Devanagari, then the complete English translation "
            "under an ENGLISH VERSION heading. Keep facts identical between versions."
        ),
    }[language_choice]
    if length_choice == "Headlines":
        length_rule = (
            "STRICT HEADLINES-ONLY MODE: Output exactly 5 alternative headlines, numbered 1–5. "
            "Each item must be one short headline only. Absolutely nothing else: no introduction, no press-note title, "
            "no summary, no body text, no explanation, no metadata, no labels, and no closing sentence. "
            "Do not write paragraphs. Every headline must be factual and based only on the supplied verified facts."
        )
    elif length_choice == "Summarised":
        length_rule = (
            "STRICT SUMMARISED MODE: Output a short press note in ONLY 3–4 content lines total per language. "
            "Line 1 must be the headline. The remaining 2–3 lines must summarise the key verified facts. "
            "Keep each line concise. Do not add an introduction, bullet list, extra headings, background paragraphs, "
            "metadata blocks, explanations, or a conclusion. Do not exceed 4 content lines per language."
        )
    else:
        length_rule = (
            "STRICT DETAILED MODE: Output a detailed, structured press note with a minimum of 8 content lines "
            "per language (aim for 8–12 lines). Start with a factual headline, then provide at least 7 further "
            "meaningful lines covering the supplied facts and relevant supplied context. Use separate readable lines; "
            "do not put the entire note into one paragraph. Use short paragraphs or clear factual sections only when useful. "
            "Never invent details or pad the note with repetition. If the supplied facts are limited, use at least 8 concise "
            "lines by separating supported facts clearly, without repeating or fabricating information."
        )
    status_rule = {
        "Completed": "Describe events in past tense only where supported by the supplied facts.",
        "Ongoing": "Clearly state the activity is ongoing; do not imply completion.",
        "Upcoming": "Use planned/future wording; do not describe the event as already completed.",
    }[data["event_status"]]
    type_rules = {
        "Government department": "Use neutral public-sector communication. Do not imply legal authority or policy approval not provided.",
        "Police / law enforcement": "Use careful factual language. Do not present allegations as proven, or invent arrests, seizures, case numbers or legal sections.",
        "Education": "Use appropriate academic/institutional language. Do not invent rankings, awards, results or achievements.",
        "Healthcare": "Use responsible health communication. Do not invent medical claims, outcomes, advice or statistics.",
        "Corporate / business": "Use professional corporate communication. Do not invent performance, financial, product or customer claims.",
        "NGO / non-profit": "Use clear community/programme communication. Do not invent impact figures or beneficiary counts.",
        "Municipal / public authority": "Use clear civic/public-service communication. Do not invent service commitments or project milestones.",
        "Other": "Use neutral, professional institutional communication appropriate to the supplied facts.",
    }[data["institution_type"]]

    # Automatically select a structure based on Institution Type; no extra template dropdown.
    template_rules = {
        "Government department": (
            "AUTOMATIC TEMPLATE — GOVERNMENT DEPARTMENT. For Summarised/Detailed, structure supported content in this order: "
            "factual headline; announcement/action or programme; responsible department/authority if supplied; key verified details; "
            "public impact or next steps only if supplied; approved public contact/advisory if supplied. Do not invent policy, orders or commitments."
        ),
        "Police / law enforcement": (
            "AUTOMATIC TEMPLATE — POLICE / LAW ENFORCEMENT. For Summarised/Detailed, structure supported content in this order: "
            "factual headline; verified incident/action overview; date and location if supplied; verified actions taken; "
            "case/legal details only if explicitly supplied; public advisory only if supplied; authorised contact if supplied. "
            "Distinguish allegations from established facts and omit unsupported investigative details."
        ),
        "Education": (
            "AUTOMATIC TEMPLATE — EDUCATION. For Summarised/Detailed, structure supported content in this order: "
            "factual headline; event/programme overview; organising department or participants if supplied; key verified activities; "
            "outcome/achievement only if explicitly supported; educational or community relevance only when supported; contact if supplied. "
            "Do not invent attendance, awards, results or quotes."
        ),
        "Healthcare": (
            "AUTOMATIC TEMPLATE — HEALTHCARE. For Summarised/Detailed, structure supported content in this order: "
            "factual headline; programme/service overview; responsible unit or qualified personnel if supplied; verified activities; "
            "health information only when provided by an approved source; outcomes/statistics only if supplied; contact/advisory if supplied. "
            "Do not add medical advice or imply clinical outcomes without evidence."
        ),
        "Corporate / business": (
            "AUTOMATIC TEMPLATE — CORPORATE / BUSINESS. For Summarised/Detailed, structure supported content in this order: "
            "factual headline; announcement overview; relevant product/service/initiative details if supplied; verified organisational action; "
            "business or customer impact only if supported; next steps/contact if supplied. Do not invent financial, performance or customer claims."
        ),
        "NGO / non-profit": (
            "AUTOMATIC TEMPLATE — NGO / NON-PROFIT. For Summarised/Detailed, structure supported content in this order: "
            "factual headline; initiative/programme overview; organising team/partners if supplied; verified activities; "
            "beneficiaries or impact only if figures/details are supplied; community purpose only if supported; contact/donation details only if supplied. "
            "Do not invent impact or beneficiary counts."
        ),
        "Municipal / public authority": (
            "AUTOMATIC TEMPLATE — MUNICIPAL / PUBLIC AUTHORITY. For Summarised/Detailed, structure supported content in this order: "
            "factual headline; civic service/issue overview; area and responsible unit if supplied; verified action/status; "
            "public-facing instructions or next steps only if supplied; timeline/contact only if supplied. Do not invent service commitments or deadlines."
        ),
        "Other": (
            "AUTOMATIC TEMPLATE — GENERAL INSTITUTION. For Summarised/Detailed, structure supported content in this order: "
            "factual headline; announcement/event overview; responsible unit if supplied; key verified details; "
            "supported relevance or next steps; approved contact if supplied. Use only sections supported by the source facts."
        ),
    }[data["institution_type"]]

    name_rule = (
        "An event/operation name was explicitly supplied. Use this exact name only where relevant; do not modify it into a new official name."
        if data["event_name"].strip()
        else "No event/operation name was supplied. Do NOT invent, guess, infer, or mention any event/operation/campaign name. Generate the headline from the facts alone, without treating it as an official name."
    )
    return f"""
You are a careful institutional press-note drafting assistant for a local AI prototype.
Return ONLY the final press note, ready for human editing. Do not return analysis, planning, a checklist, code fences or an executive summary.
{lang_rule}
{length_rule}
{status_rule}
INSTITUTION TYPE RULES: {type_rules}
{template_rules}
Apply the selected institution template automatically from the Institution Type field. Do not ask the user to choose a second template. The template controls structure only; it never supplies missing facts. If a section has no supporting information, omit it rather than inventing details. Headlines mode must still output only the 5 headlines; Summarised mode must still obey the 3–4 content-line limit; Detailed mode must still obey the minimum 8 content lines.
EVENT/OPERATION NAME RULE: {name_rule}

FORMAT AND SAFEGUARDS:
- For Summarised and Detailed modes, generate a concise, factual headline yourself from verified facts. The user does not need to provide a headline.
- In Headlines mode, output only the 5 requested headline options and absolutely no other content.
- Never treat a generated headline as an official event or operation name.
- Use the institution name, department and location only when provided.
- Do not invent names, ranks, quotations, case numbers, legal sections, arrests, seizures, statistics, motives, outcomes, achievements, medical claims, financial claims or official statements.
- If a critical fact is missing, flag it with [पुष्टि आवश्यक] in Hindi or [REQUIRES CONFIRMATION] in English rather than guessing.
- Do not state allegations as established guilt. Avoid unnecessary personal data and sensitive information.
- Use supplied quotations exactly; never create a quote. Omit quotations if none were supplied.
- Preserve supplied numbers and dates accurately.
- Include a public advisory only when supported by the supplied information.
- Do not include internal drafting notes or the review checklist in the press-note body.

SUPPLIED INFORMATION:
Institution name: {data["institution_name"] or "[Not provided]"}
Institution type: {data["institution_type"]}
Department/unit: {data["department"] or "[Not provided]"}
City/district/region: {data["location"] or "[Not provided]"}
Event/operation name (use only if explicitly supplied): {data["event_name"] or "[Not provided — do not invent or mention a name]"}
Event date: {data["event_date"]}
Release date: {data["release_date"]}
Press note number: {data["press_note_no"] or "[Not provided]"}
Status: {data["event_status"]}
Verified facts:
{data["facts"]}
Verified quotation:
{data["quotes"] or "[No verified quotation supplied]"}
Additional context/instructions:
{data["background"] or "[None supplied]"}
Authorised issuing person: {data["issuing_officer"] or "[Not provided]"}
Approved public contact: {data["contact_line"] or "[Not provided]"}
Optional footer: {data["footer_text"] or "[Not provided]"}

Return only the press note in the requested language format.
""".strip()

def devanagari_count(value):
    return len(re.findall(r"[\u0900-\u097F]", value or ""))

def enforce_output_language(draft, language_choice, source_prompt):
    """Check generated output and retry via Ollama when it violates the selected language."""
    if language_choice == "Bilingual":
        return draft
    for attempt in range(2):
        hindi_chars = devanagari_count(draft)
        latin_words = len(re.findall(r"[A-Za-z]{2,}", draft))
        if language_choice == "English":
            compliant = hindi_chars == 0
            target = "English only, using Latin characters; no Devanagari characters anywhere"
        else:
            # Proper nouns, abbreviations and numbers may legitimately remain in Latin.
            compliant = hindi_chars >= 15 or (latin_words < 10 and hindi_chars > 0)
            target = "formal Hindi in Devanagari script, not English paragraphs"
        if compliant:
            return draft
        correction_prompt = (
            f"Rewrite the following press note in {target}. "
            "Preserve every supplied fact, date, number and qualifier. "
            "Do not invent any new details. Return ONLY the rewritten press note. "
            "The language requirement overrides the input language.\n\n"
            f"PRESS NOTE TO REWRITE:\n{draft}\n\n"
            f"ORIGINAL REQUIREMENTS:\n{source_prompt}"
        )
        draft = generate_local(correction_prompt)
    if language_choice == "English" and devanagari_count(draft):
        raise ValueError("The local model kept returning Hindi despite English being selected. Please regenerate or choose a different Ollama model; the incorrect-language draft was not exported.")
    return draft

def generate_local(prompt):
    payload = {
        "model": LOCAL_MODEL,
        "think": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Draft the final official-style press note directly. Do not output analysis or internal reasoning. "
                    "The user's selected output language is mandatory and overrides the language of the input text. "
                    "Translate input into the selected language; never mix languages unless Bilingual is selected. "
                    "Use only supplied facts and obey the formatting and factual safeguards."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 2200},
    }
    response = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
    response.raise_for_status()
    result = response.json()
    message = result.get("message") or {}
    content = (message.get("content") or "").strip()
    if not content:
        reason = result.get("done_reason", "unknown")
        raise ValueError(
            f"Ollama returned no final text (done_reason={reason}). "
            "The model may have used its token budget for thinking. Update Ollama or use a non-thinking model tag."
        )
    return content

def split_press_note(text):
    """Extract a short leading headline when present; preserve the remaining body."""
    lines = [line.rstrip() for line in (text or "").strip().splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    headline = ""
    if lines:
        first = lines[0].strip().strip("#* ")
        if len(first) <= 180 and not first.endswith((".", "।")) and not first.lower().startswith(("institution:", "दिनांक", "प्रेस नोट क्रमांक")):
            headline = first
            lines = lines[1:]
    body = "\n".join(lines).strip()
    body = re.sub(r"(?m)^\s*#{1,6}\s*", "", body)
    body = re.sub(r"\*{1,2}([^*]+?)\*{1,2}", r"\1", body)
    return headline, body or (text or "").strip()

def run_fact_check(draft, data):
    """Rule-based consistency scan against supplied inputs; flags risks, not truth."""
    draft = draft or ""
    source_parts = [
        data.get("institution_name", ""), data.get("institution_type", ""),
        data.get("department", ""), data.get("location", ""),
        data.get("event_date", ""), data.get("release_date", ""),
        data.get("press_note_no", ""), data.get("event_name", ""),
        data.get("event_status", ""), data.get("facts", ""),
        data.get("quotes", ""), data.get("background", ""),
        data.get("issuing_officer", ""), data.get("contact_line", ""),
        data.get("footer_text", ""),
    ]
    source_text = "\n".join(str(part) for part in source_parts if part)

    def norm(value):
        value = str(value or "").casefold()
        value = value.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        return re.sub(r"\s+", " ", value).strip()

    # Compare numeric/date-like tokens with all supplied input text.
    def numeric_tokens(value):
        # Compare number components separately so 14/10/2026 and 14 October 2026
        # do not create false flags merely because date formatting differs.
        raw = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", str(value or ""))
        return {token.replace(",", "").lstrip("0") or "0" for token in raw}

    source_numbers = numeric_tokens(source_text)
    draft_numbers = numeric_tokens(draft)
    unsupported_numbers = sorted(draft_numbers - source_numbers, key=lambda token: (not token.isdigit(), int(token) if token.isdigit() else token))

    # Quotes are flagged when the quoted phrase does not appear in the exact approved quote.
    quote_candidates = re.findall(r'["“”](.+?)["“”]', draft)
    approved_quote = norm(data.get("quotes", ""))
    unsupported_quotes = [q.strip() for q in quote_candidates if q.strip() and norm(q) not in approved_quote]

    placeholder_matches = re.findall(
        r"\[(?:पुष्टि आवश्यक|REQUIRES CONFIRMATION|Not provided|not provided)[^\]]*\]",
        draft, flags=re.IGNORECASE,
    )

    # Sensitive/high-impact assertions are reminders for human verification, not automatic errors.
    review_terms = {
        "English": ["arrested", "seized", "convicted", "injured", "killed", "died", "recovered", "won", "first ever", "largest", "record-breaking"],
        "Hindi": ["गिरफ्तार", "जब्त", "दोषी", "घायल", "मृत्यु", "बरामद", "पहली बार", "सबसे बड़ा", "रिकॉर्ड"],
    }
    language = data.get("_language", "English")
    terms = review_terms["Hindi"] if language == "Hindi" else review_terms["English"]
    lower_draft = draft.casefold()
    flagged_terms = [term for term in terms if term.casefold() in lower_draft]

    findings = []
    if unsupported_numbers:
        findings.append({"level": "warning", "title": "Numbers or date-like values not found in supplied inputs", "detail": ", ".join(unsupported_numbers)})
    if unsupported_quotes:
        findings.append({"level": "warning", "title": "Quoted text may not match the approved quotation", "detail": " | ".join(unsupported_quotes)})
    if placeholder_matches:
        findings.append({"level": "warning", "title": "Unresolved placeholders remain", "detail": ", ".join(dict.fromkeys(placeholder_matches))})
    if flagged_terms:
        findings.append({"level": "review", "title": "High-impact claims need a human source check", "detail": ", ".join(flagged_terms)})
    if not findings:
        findings.append({"level": "success", "title": "No rule-based red flags found", "detail": "This is not proof that the draft is accurate. Verify names, context, claims and wording against original records."})
    return findings

def create_press_note_pdf(text, data, language_choice, is_draft=True):
    """Render an A4 PDF with WeasyPrint/Pango text shaping for Hindi."""
    project_dir = Path(__file__).resolve().parent
    font_dir = project_dir / "fonts"
    regular_font = font_dir / "NotoSansDevanagari-Regular.ttf"
    bold_font = font_dir / "NotoSansDevanagari-Bold.ttf"
    if not regular_font.exists():
        regular_font = font_dir / "NotoSansDevanagariUI-Regular.ttf"
    if not bold_font.exists():
        bold_font = font_dir / "NotoSansDevanagariUI-Bold.ttf"

    def file_url(p):
        return p.resolve().as_uri()

    headline, body = split_press_note(text)
    body_paragraphs = []
    for block in re.split(r"\n\s*\n", body):
        block = block.strip()
        if not block:
            continue
        safe = html_escape(block).replace("\n", "<br>")
        body_paragraphs.append(f'<p class="body">{safe}</p>')

    institution = html_escape(data.get("institution_name", ""))
    department = html_escape(data.get("department", ""))
    location = html_escape(data.get("location", ""))
    press_no = html_escape(data.get("press_note_no", ""))
    release_date = html_escape(data.get("release_date", ""))
    event_date = html_escape(data.get("event_date", ""))
    officer = html_escape(data.get("issuing_officer", ""))
    contact = html_escape(data.get("contact_line", ""))
    footer = html_escape(data.get("footer_text", ""))
    title = html_escape(headline or "Press Note")
    lang = "en" if language_choice == "English" else "hi"
    watermark = '<div class="watermark">DRAFT</div>' if is_draft else ""
    meta_items = []
    if press_no:
        meta_items.append(f'<span><b>Reference:</b> {press_no}</span>')
    if location:
        meta_items.append(f'<span><b>Location:</b> {location}</span>')
    if release_date:
        meta_items.append(f'<span><b>Release date:</b> {release_date}</span>')
    if event_date:
        meta_items.append(f'<span><b>Event date:</b> {event_date}</span>')
    metadata = "".join(meta_items)
    subline = " · ".join(x for x in [department, location] if x)
    sign_parts = [x for x in [officer, institution, contact] if x]
    signature = "<br>".join(sign_parts)
    font_css = ""
    if regular_font.exists():
        font_css += f"@font-face {{ font-family: NotoDevanagari; src: url('{file_url(regular_font)}'); font-weight: 400; }}"
    if bold_font.exists():
        font_css += f"@font-face {{ font-family: NotoDevanagari; src: url('{file_url(bold_font)}'); font-weight: 700; }}"
    html_doc = f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><style>
{font_css}
@page {{ size: A4; margin: 18mm 20mm 20mm; @bottom-center {{ content: "Generated by local AI prototype · Human review required · Page " counter(page); font: 8pt sans-serif; color: #687386; }} }}
* {{ box-sizing: border-box; }}
body {{ font-family: NotoDevanagari, "Nirmala UI", "Mangal", sans-serif; color: #202938; font-size: 10.5pt; line-height: 1.7; }}
.top {{ border-bottom: 2px solid #31557e; padding-bottom: 12px; margin-bottom: 18px; }}
.institution {{ font-size: 18pt; font-weight: 700; color: #18365c; text-align: center; }}
.subline {{ text-align: center; font-size: 9pt; color: #58677c; margin-top: 5px; }}
.watermark {{ position: fixed; top: 37%; left: 7%; width: 86%; text-align: center; transform: rotate(-45deg); transform-origin: center center; font-family: sans-serif; font-size: 88pt; font-weight: 700; letter-spacing: 5px; color: #777777; opacity: 0.12; z-index: -1; pointer-events: none; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 7px 18px; border-bottom: 1px solid #e1e6ee; padding: 0 0 10px; margin-bottom: 18px; font-size: 9pt; }}
h1 {{ font-size: 15pt; text-align: center; line-height: 1.5; margin: 12px 0 20px; color: #172d52; }}
.body {{ text-align: justify; margin: 0 0 12px; white-space: normal; overflow-wrap: anywhere; }}
.signature {{ text-align: right; margin-top: 30px; font-size: 9.5pt; }}
.footer {{ text-align: center; margin-top: 22px; padding-top: 8px; border-top: 1px solid #e1e6ee; font-size: 9pt; color: #58677c; }}
</style></head><body>
{watermark}
<header class="top"><div class="institution">{institution or "Institution"}</div>
{f'<div class="subline">{html_escape(subline)}</div>' if subline else ""}
</header>
<div class="meta">{metadata}</div>
<h1>{title}</h1>
{''.join(body_paragraphs)}
<div class="signature">{signature}</div>
{f'<div class="footer">{footer}</div>' if footer else ""}
</body></html>"""
    return HTML(string=html_doc, base_url=str(project_dir)).write_pdf()

def _reset_manual_edits():
    original = st.session_state.get("original_draft", "")
    st.session_state["editable_draft"] = original
    st.session_state["draft"] = original
    st.session_state["show_draft_diff"] = False
    if st.session_state.get("current_note_id"):
        save_history_revision(st.session_state.current_note_id, original, "Reset to AI draft", "Restored original AI-generated draft")

def _clear_current_draft():
    st.session_state["draft"] = ""
    st.session_state["original_draft"] = ""
    st.session_state["editable_draft"] = ""
    st.session_state["show_draft_diff"] = False
    st.session_state["last_data"] = {}
    st.session_state["last_headline"] = ""
    st.session_state["current_note_id"] = None


# Initialize the original project's history database in-place. Existing records are retained.
init_history_db()

def generate_press_note(data, language_choice=None):
    """Bridge the new UI to the original local Ollama prompt/generation pipeline."""
    language_choice = language_choice or data.get("language", "Hindi")
    if language_choice == "Bilingual (Hindi + English)":
        language_choice = "Bilingual"
    original_data = {
        "institution_name": data.get("institution", data.get("institution_name", "")),
        "institution_type": data.get("institution_type", "Education"),
        "department": data.get("department", ""),
        "location": data.get("venue", data.get("location", "")),
        "event_date": data.get("date", data.get("event_date", "")),
        "release_date": data.get("release_date", ""),
        "press_note_no": data.get("note_number", data.get("press_note_no", "")),
        "event_name": data.get("event_title", data.get("event_name", "")),
        "event_status": data.get("event_status", "Completed"),
        "facts": data.get("facts", ""),
        "quotes": data.get("quotes", ""),
        "background": "\n".join(filter(None, [
            data.get("context", ""),
            ("Participants: " + data["participants"]) if data.get("participants") else "",
            ("Key outcomes: " + data["outcomes"]) if data.get("outcomes") else "",
            ("Source references: " + data["sources"]) if data.get("sources") else "",
        ])),
        "issuing_officer": data.get("issuing_person", data.get("issuing_officer", "")),
        "contact_line": data.get("contact_line", ""),
        "footer_text": data.get("footer_text", ""),
    }
    try:
        length_choice = data.get("length", "Detailed")
        if length_choice == "Concise":
            length_choice = "Summarised"
        elif length_choice == "Standard":
            length_choice = "Summarised"
        prompt = make_prompt(original_data, language_choice, length_choice)
        generated_text = enforce_output_language(generate_local(prompt), language_choice, prompt)
        st.session_state["last_data"] = original_data
        st.session_state["last_language"] = language_choice
        st.session_state["last_length"] = length_choice
        st.session_state["draft"] = generated_text
        st.session_state["original_draft"] = generated_text
        st.session_state["editable_draft"] = generated_text
        st.session_state["current_note_id"] = None
    except Exception as exc:
        # The UI has a clearly labelled fallback path if local Ollama is unavailable.
        raise RuntimeError(str(exc)) from exc

    headline, body = split_press_note(generated_text)
    if not headline:
        headline = data.get("event_title", data.get("event_name", "Institutional update"))
    # Keep the original project's persistent press_note_history.db history.
    note_id = create_history_record(original_data, language_choice, length_choice, generated_text)
    st.session_state["legacy_note_id"] = note_id
    st.session_state["legacy_generated_text"] = generated_text
    return {
        "headline": headline,
        "summary": body[:280] if body else generated_text[:280],
        "body": body or generated_text,
        "review_flags": ["Verify every name, date, figure and factual claim against supplied source records.",
                         "Confirm quotations and attributions are explicitly authorized."],
        "generation_mode": "Original local Ollama pipeline",
        "model": LOCAL_MODEL,
    }



import json
from datetime import date
import streamlit as st
from ui.theme import apply_theme
from ui.components import page_header, metric_card, status_pill, empty_state, preview_document
# Embedded local workflow store: avoids ModuleNotFoundError when services/demo_store.py is not copied.
import uuid
from typing import Any
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", LOCAL_MODEL)

"""Local SQLite store for PressAI prototype. Swap this module for the team's DB adapter later."""
STORE_DB_PATH = Path(__file__).resolve().parent / "data" / "pressai_local.db"
STORE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _conn():
    c = sqlite3.connect(STORE_DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data_json TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, note_id TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL)")
        c.commit()

def _audit(note_id: str, actor: str, action: str, details: str = ""):
    with _conn() as c:
        c.execute("INSERT INTO audit(note_id,actor,action,details,created_at) VALUES(?,?,?,?,?)", (note_id, actor, action, details, now()))
        c.commit()

def list_drafts() -> list[dict[str, Any]]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT data_json FROM notes ORDER BY updated_at DESC").fetchall()
    return [json.loads(r[0]) for r in rows]

def get_draft(note_id: str) -> dict[str, Any] | None:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT data_json FROM notes WHERE id=?", (note_id,)).fetchone()
    return json.loads(row[0]) if row else None

def save_draft(d: dict[str, Any], actor: str = "System", action: str = "Saved") -> dict[str, Any]:
    init_db()
    d = dict(d)
    stamp = now()
    d.setdefault("created", stamp)
    d["updated"] = stamp
    d.setdefault("versions", [])
    d.setdefault("comments", [])
    d.setdefault("review_log", [])
    with _conn() as c:
        c.execute("INSERT INTO notes(id,status,created_at,updated_at,data_json) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, data_json=excluded.data_json", (d["id"], d.get("status", "Draft"), d["created"], stamp, json.dumps(d, ensure_ascii=False)))
        c.commit()
    _audit(d["id"], actor, action)
    return d

def create_demo_draft(data: dict[str, Any]) -> dict[str, Any]:
    note_id = "PA-" + uuid.uuid4().hex[:6].upper()
    d = {**data, "id": note_id, "status": "Draft", "headline": data.get("event_title") or "Institutional update", "summary": data.get("facts", "")[:280], "body": "", "created": now(), "updated": now(), "versions": [], "comments": [], "review_log": [], "sources_list": data.get("sources_list", [])}
    return save_draft(d, data.get("created_by", "Content Officer"), "Draft created")

def snapshot(d: dict[str, Any], actor: str, action: str, note: str = "") -> dict[str, Any]:
    d = dict(d)
    versions = list(d.get("versions", []))
    versions.append({"version": len(versions) + 1, "timestamp": now(), "actor": actor, "action": action, "headline": d.get("headline", ""), "summary": d.get("summary", ""), "body": d.get("body", ""), "note": note})
    d["versions"] = versions
    d["updated"] = now()
    return d

def update_draft(note_id: str, changes: dict[str, Any], actor: str = "Content Officer", action: str = "Draft edited") -> dict[str, Any] | None:
    d = get_draft(note_id)
    if not d: return None
    d.update(changes)
    d = snapshot(d, actor, action)
    return save_draft(d, actor, action)

def add_comment(note_id: str, author: str, comment: str) -> dict[str, Any] | None:
    d = get_draft(note_id)
    if not d: return None
    d.setdefault("comments", []).append({"author": author, "comment": comment, "timestamp": now()})
    return save_draft(d, author, "Reviewer comment added")

def decide(note_id: str, actor: str, decision: str, comment: str = "") -> dict[str, Any] | None:
    d = get_draft(note_id)
    if not d: return None
    d = snapshot(d, actor, decision, comment)
    d["status"] = decision
    d.setdefault("review_log", []).append({"actor": actor, "decision": decision, "comment": comment, "timestamp": now()})
    if comment:
        d.setdefault("comments", []).append({"author": actor, "comment": f"[{decision}] {comment}", "timestamp": now()})
    return save_draft(d, actor, decision)

def audit_for(note_id: str | None = None) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c:
        if note_id:
            rows = c.execute("SELECT * FROM audit WHERE note_id=? ORDER BY id DESC", (note_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 500").fetchall()
    return [dict(r) for r in rows]


st.set_page_config(page_title="PressAI | Official Communications", page_icon="✦", layout="wide", initial_sidebar_state="expanded")
apply_theme(st.session_state.get("appearance", "Government Slate")); init_db()
NAV = {"Overview":"⌂", "Create Press Note":"＋", "Draft Workspace":"▤", "Human Review":"✓", "Published Notes":"↗", "History & Analytics":"◷"}
if "page" not in st.session_state or st.session_state.page == "Sources & Verification": st.session_state.page = "Overview"
if "active_draft_id" not in st.session_state: st.session_state.active_draft_id = None
if "flash" not in st.session_state: st.session_state.flash = ""

def go(page):
    st.session_state.page = page
    st.rerun()

def safe_status(d): return d.get("status", "Draft")
def find_note(note_id): return get_draft(note_id) if note_id else None

def parse_sources(raw):
    items=[]
    for line in raw.splitlines():
        line=line.strip()
        if not line: continue
        parts=[p.strip() for p in line.split("|",2)]
        items.append({"title":parts[0],"reference":parts[1] if len(parts)>1 else "Reference not supplied","note":parts[2] if len(parts)>2 else "","status":"Needs verification"})
    return items

def make_fallback(data):
    headline=data.get("event_title", "Institutional update").strip()
    facts=data.get("facts", "").strip()
    pieces=[facts]
    if data.get("outcomes"): pieces.append("Key outcomes: " + data["outcomes"])
    if data.get("participants"): pieces.append("Participants: " + data["participants"])
    if data.get("quotes"): pieces.append("Approved quotation: " + data["quotes"])
    if data.get("context"): pieces.append(data["context"])
    return {"headline":headline,"summary":facts[:280],"body":"\n\n".join(x for x in pieces if x),"review_flags":["Verify every name, date, figure and factual claim against the source record.","Confirm that any quotation and attribution are explicitly authorized."],"generation_mode":"Structured template (Ollama unavailable)","model":"Not connected"}

with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-mark">SK</div><div><div class="brand-name">PressAI</div><div class="brand-sub">OFFICIAL COMMUNICATION DESK</div></div></div>', unsafe_allow_html=True)
    st.markdown('<div class="side-label">APPEARANCE</div>', unsafe_allow_html=True)
    st.selectbox("Choose theme", ["Government Slate", "Official Light", "Dark Office"], key="appearance", label_visibility="collapsed", help="Change the workspace appearance. Your press-note records are not affected.")
    st.markdown('<div class="side-label" style="margin-top:16px">WORKSPACE</div>', unsafe_allow_html=True)
    for label, symbol in NAV.items():
        if st.button(f"{symbol}   {label}", key=f"nav_{label}", use_container_width=True, type="primary" if st.session_state.page==label else "secondary"):
            go(label)
    st.markdown('<div class="side-note"><b>SKIT005 · Local workspace</b><br>AI drafts. Humans verify.<br>Authorized officers approve.<br><span style="color:#e9bd68">APPROVAL AND PUBLICATION ARE SEPARATE</span></div>', unsafe_allow_html=True)
    st.caption(f"Model endpoint: {OLLAMA_BASE_URL}\nModel configured: {OLLAMA_MODEL}")
if st.session_state.flash:
    st.toast(st.session_state.flash); st.session_state.flash=""

drafts=list_drafts()
pending=sum(safe_status(d) in ("In Review","Pending Review") for d in drafts)
approved=sum(safe_status(d)=="Approved" for d in drafts)
published=sum(safe_status(d)=="Published" for d in drafts)
needs_changes=sum(safe_status(d)=="Changes Requested" for d in drafts)

# 01 — COMMAND CENTER
if st.session_state.page == "Overview":
    page_header("COMMAND CENTER", "Official communications", "A source-aware workspace for creating, reviewing and publishing institutional press notes.", "LOCAL WORKSPACE · HUMAN APPROVAL REQUIRED")
    cols=st.columns(4,gap="medium")
    for col,args in zip(cols,[("Total press notes",len(drafts),"Saved records","▤"),("Awaiting review",pending,"Needs an authorized decision","◷"),("Approved",approved,"Ready for publishing","✓"),("Published",published,"In the local archive","↗")]):
        with col: metric_card(*args)
    st.write("")
    left,right=st.columns([1.55,1],gap="large")
    with left:
        st.markdown('<div class="section-title">Recent press notes</div><div class="section-subtitle">Latest records and their current workflow status</div>',unsafe_allow_html=True)
        if not drafts: empty_state("Your workspace is ready","Create the first press note to begin the workflow.")
        for d in sorted(drafts,key=lambda x:x.get("updated",""),reverse=True)[:6]:
            with st.container(border=True):
                a,b=st.columns([4,1.2])
                with a:
                    st.markdown(f'<div class="doc-id">{d["id"]} · {d.get("language","English")}</div><div class="doc-title">{d.get("headline","Untitled press note")}</div><div class="muted">{d.get("department") or "Issuing authority not specified"} · {d.get("date","Date not set")}</div>',unsafe_allow_html=True)
                with b:
                    status_pill(safe_status(d))
                    if st.button("Open →",key=f"overview_open_{d['id']}",use_container_width=True): st.session_state.active_draft_id=d["id"]; go("Draft Workspace")
    with right:
        st.markdown('<div class="section-title">Workflow shortcuts</div><div class="section-subtitle">Continue from the next required step</div>',unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("**＋ Create a press note**\n\nStart with structured event details and source references.")
            if st.button("Create new note",type="primary",use_container_width=True): go("Create Press Note")
        with st.container(border=True):
            st.markdown(f"**✓ Human review queue**\n\n{pending} note(s) awaiting a decision.")
            if st.button("Open review queue",use_container_width=True): go("Human Review")
        st.markdown('<div class="callout"><b>Governance control</b><br>AI output is a draft, not evidence. Source checks and an authorized human decision are required before release.</div>',unsafe_allow_html=True)
    st.write("")
    st.markdown('<div class="section-title">Controlled workflow</div>',unsafe_allow_html=True)
    for col,(n,title,desc) in zip(st.columns(5),[("01","Capture","Structured facts"),("02","Draft","Local AI assistance"),("03","Verify","Evidence and claims"),("04","Approve","Authorized reviewer"),("05","Publish","Separate release action")]):
        with col: st.markdown(f'<div class="metric" style="min-height:100px"><div class="metric-label">STEP {n}</div><div class="doc-title">{title}</div><div class="metric-note">{desc}</div></div>',unsafe_allow_html=True)

# 02 — CREATE
elif st.session_state.page == "Create Press Note":
    page_header("DOCUMENT INTAKE", "Create a press note", "Enter source-backed information. The model may improve wording, but must not invent missing facts.", "STEP 01 / INPUT")
    st.markdown('<div class="callout"><b>Source-first drafting</b><br>Only include claims supported by official input. Source references entered here are not automatically verified.</div>',unsafe_allow_html=True)
    with st.form("create_press_note_form"):
        st.markdown('<div class="section-title">01 · Institution and release details</div>',unsafe_allow_html=True)
        c1,c2=st.columns(2)
        with c1:
            institution=st.text_input("Institution name *",placeholder="Official institution / authority")
            institution_type=st.selectbox("Institution type",["Government department","Police / law enforcement","Education","Healthcare","Corporate / business","NGO / non-profit","Municipal / public authority","Other"])
            department=st.text_input("Department / unit",placeholder="Issuing department")
            venue=st.text_input("City / venue *",placeholder="Jaipur, Rajasthan")
            event_date=st.date_input("Event date",value=date.today())
            event_title=st.text_input("Event / operation name (optional)",placeholder="Leave blank if there is no official event name")
        with c2:
            note_number=st.text_input("Press note number (optional)",placeholder="PIET/2026/PR-001")
            language=st.selectbox("Output language",["Hindi","English","Bilingual (Hindi + English)"])
            length=st.selectbox("Draft length",["Headlines","Summarised","Detailed"],index=2)
            event_status=st.selectbox("Event status",["Completed","Ongoing","Upcoming"])
            release_date=st.date_input("Proposed release date",value=date.today())
            issuing_person=st.text_input("Authorized issuing person (optional)",placeholder="Name and designation")
        st.markdown('<div class="section-title">02 · Verified facts and approved details</div>',unsafe_allow_html=True)
        facts=st.text_area("Verified facts and approved details *",height=145,placeholder="Describe only details supported by the supplied official material.")
        a,b=st.columns(2)
        with a: participants=st.text_area("Participants / designations (optional)",height=90,placeholder="Include names only when confirmed")
        with b: outcomes=st.text_area("Key outcomes / figures (optional)",height=90,placeholder="Confirmed results, quantities, next steps")
        quotes=st.text_area("Verified quotation (optional)",height=75,placeholder="Exact approved quotation and speaker attribution, or leave blank")
        context=st.text_area("Additional context / writing instructions (optional)",height=75,placeholder="Audience, neutral tone, approved terminology, details to exclude")
        source_text = ""
        created_by=st.text_input("Prepared by",value="Content Officer")
        submit=st.form_submit_button("Generate draft workspace  →",type="primary",use_container_width=True)
    if submit:
        if not all([institution.strip(),venue.strip(),facts.strip()]): st.error("Complete all required fields: institution, location and verified facts. Event / operation name is optional.")
        else:
            data={"institution":institution.strip(),"institution_type":institution_type,"department":department.strip() or institution.strip(),"venue":venue.strip(),"date":str(event_date),"release_date":str(release_date),"event_title":event_title.strip(),"note_number":note_number.strip(),"language":language,"length":length,"event_status":event_status,"issuing_person":issuing_person.strip(),"facts":facts.strip(),"participants":participants.strip(),"outcomes":outcomes.strip(),"quotes":quotes.strip(),"context":context.strip(),"sources":source_text.strip(),"sources_list":parse_sources(source_text),"created_by":created_by.strip() or "Content Officer","status":"Draft"}
            # Visible, professional progress panel. Step 2 remains active while the model responds.
            with st.status("Generating your press note…", expanded=True) as generation_status:
                progress_bar = st.progress(0, text="Step 1 of 3 — Validating your input")
                step_one = st.empty()
                step_one.markdown("✅ **Step 1 — Input validation**\n\nRequired details checked. Preparing the generation request.")
                progress_bar.progress(20, text="Step 2 of 3 — Drafting with AI")
                st.markdown("**Step 2 — AI drafting**\n\nPressAI is analyzing the supplied information and preparing a structured press note. This may take a few moments.")
                try:
                    generated=generate_press_note(data,language)
                    ai_used = True
                except Exception as exc:
                    generated=make_fallback(data)
                    ai_used = False
                    st.warning("The AI model did not respond successfully. PressAI prepared a structured fallback draft instead.")
                    st.caption(f"Technical detail: {exc}")
                progress_bar.progress(75, text="Step 3 of 3 — Saving your draft")
                st.markdown("**Step 3 — Finalizing draft**\n\nFormatting the result and saving it to your Draft Workspace.")
                d=create_demo_draft(data)
                d.update({"headline":generated.get("headline") or event_title.strip() or "Institutional update","summary":generated.get("summary",facts[:280]),"body":generated.get("body",facts),"review_flags":generated.get("review_flags",[]),"generation_mode":generated.get("generation_mode","Unknown"),"model":generated.get("model","Unknown"),"legacy_note_id":st.session_state.get("legacy_note_id"),"source_status":"Needs verification","status":"Draft","versions":[],"comments":[],"review_log":[]})
                d=save_draft(d,created_by or "Content Officer","Draft generated")
                progress_bar.progress(100, text="Complete — draft saved")
                if ai_used:
                    generation_status.update(label="Press note generated successfully", state="complete", expanded=True)
                    st.success("Your press note is ready. Opening Draft Workspace…")
                else:
                    generation_status.update(label="Draft prepared using fallback template", state="complete", expanded=True)
            st.session_state.active_draft_id=d["id"]; st.session_state.flash=f"Draft {d['id']} saved. Review all facts before submission."; go("Draft Workspace")

# 03 — DRAFT WORKSPACE
elif st.session_state.page == "Draft Workspace":
    d=find_note(st.session_state.active_draft_id)
    page_header("DOCUMENT WORKSPACE", "Draft editor", "Edit the note, inspect source context, compare revisions and submit it for human review.", "STEP 02 / EDIT")
    if not d:
        empty_state("No press note selected","Create a note or open one from the dashboard.")
        if st.button("Create press note",type="primary"): go("Create Press Note")
    else:
        a,b,c=st.columns([1,1,2])
        with a: st.markdown(f'<div class="metric"><div class="metric-label">DOCUMENT ID</div><div class="doc-title">{d["id"]}</div></div>',unsafe_allow_html=True)
        with b: st.markdown(f'<div class="metric"><div class="metric-label">STATUS</div><div style="margin-top:13px">{d.get("status","Draft")}</div></div>',unsafe_allow_html=True)
        with c: st.markdown(f'<div class="metric"><div class="metric-label">GENERATION SOURCE</div><div class="doc-title">{d.get("generation_mode","Legacy / imported draft")}</div><div class="metric-note">Model: {d.get("model","Not recorded")}</div></div>',unsafe_allow_html=True)
        st.markdown('<div class="callout warn"><b>Draft — not approved for release</b><br>Review dates, figures, names, quotations and every factual assertion against the source material. A generated draft is not automatically verified.</div>',unsafe_allow_html=True)
        edit,evidence=st.columns([1.55,1],gap="large")
        with edit:
            with st.form(f"editor_{d['id']}"):
                headline=st.text_input("Headline",value=d.get("headline",""))
                summary=st.text_area("Summary",value=d.get("summary",""),height=90)
                body=st.text_area("Detailed press note",value=d.get("body",""),height=350)
                saved=st.form_submit_button("Save new revision",type="primary",use_container_width=True)
            if saved:
                update_draft(d["id"],{"headline":headline,"summary":summary,"body":body},actor="Content Officer",action="Edited draft")
                legacy_id = d.get("legacy_note_id")
                if legacy_id:
                    save_history_revision(
                        legacy_id,
                        f"{headline}\n\n{summary}\n\n{body}",
                        "Manual save",
                        "Edited from the PressAI Draft Workspace",
                    )
                st.session_state.flash="Saved as a new revision."; st.rerun()
            st.markdown("#### Mandatory pre-download checklist")
            st.caption("Tick all five items before either TXT or PDF can be downloaded.")
            download_checks = [
                st.checkbox("Names, dates and locations checked", key=f"dl_check_1_{d['id']}"),
                st.checkbox("Figures and factual claims checked", key=f"dl_check_2_{d['id']}"),
                st.checkbox("Quotes and attributions authorized", key=f"dl_check_3_{d['id']}"),
                st.checkbox("Neutral language and privacy checked", key=f"dl_check_4_{d['id']}"),
                st.checkbox("Language, spelling and both language versions reviewed", key=f"dl_check_5_{d['id']}"),
            ]
            download_ready = all(download_checks)
            if not download_ready:
                st.warning(f"Download locked: complete all five checks ({sum(download_checks)}/5).")
            x,y=st.columns(2)
            with x:
                txt=f"{d.get('headline','')}\n\n{d.get('summary','')}\n\n{d.get('body','')}\n\nSources:\n{d.get('sources','')}"
                st.download_button("↓ Download TXT draft",txt,file_name=f"{d['id']}_DRAFT.txt",mime="text/plain",use_container_width=True,disabled=not download_ready)
            with y:
                # Original project's A4 PDF export, including its draft watermark and Hindi font handling.
                pdf_data = dict(d.get("input_data", {}) or {})
                pdf_data.update(st.session_state.get("last_data") or {})
                try:
                    pdf_bytes = create_press_note_pdf(
                        f"{d.get('headline','')}\n\n{d.get('summary','')}\n\n{d.get('body','')}",
                        pdf_data,
                        st.session_state.get("last_language", d.get("language", "Hindi")),
                        is_draft=d.get("status") not in ("Approved", "Published"),
                    )
                    st.download_button("↓ Download PDF", pdf_bytes, file_name=f"{d['id']}_press_note.pdf",
                                       mime="application/pdf", use_container_width=True, disabled=not download_ready)
                except Exception as pdf_exc:
                    st.caption(f"PDF export unavailable: {pdf_exc}")
                if st.button("Submit for human review →",type="primary",use_container_width=True,disabled=d.get("status") in ("In Review","Approved","Published","Rejected")):
                    update_draft(d["id"],{"status":"In Review"},actor="Content Officer",action="Submitted for review")
                    st.session_state.flash="Submitted to Human Review. No publication has occurred."; go("Human Review")
        with evidence:
            st.markdown('<div class="panel-title">Source and review context</div><div class="panel-note">References supplied with the draft; check claims before approval.</div>',unsafe_allow_html=True)
            for src in d.get("sources_list",[]):
                st.markdown(f'<div class="source-row"><div class="source-title">{src.get("title", "Source")}</div><div class="source-meta">{src.get("reference", "No reference")}</div><div class="muted">Status: {src.get("status", "Needs verification")}</div></div>',unsafe_allow_html=True)
            if not d.get("sources_list"): st.info(d.get("sources") or "No sources supplied.")
            st.write("")
            st.markdown('<div class="panel-title">Draft health check</div>',unsafe_allow_html=True)
            st.metric("Approx. word count",len(d.get("body","").split()))
            st.metric("Version snapshots",len(d.get("versions",[])))
            flags=d.get("review_flags",d.get("flags",["Cross-check each claim against authorized sources."]))
            for flag in flags: st.markdown(f'<div class="flag">! &nbsp; {flag}</div>',unsafe_allow_html=True)
            with st.expander("Original rule-based fact checker"):
                st.caption("Checks are advisory and cannot prove factual accuracy.")
                if st.button("Run source-consistency scan", key=f"legacy_fact_check_{d['id']}"):
                    source_data = dict(st.session_state.get("last_data") or {})
                    source_data["_language"] = st.session_state.get("last_language", d.get("language", "English"))
                    st.session_state[f"legacy_fact_results_{d['id']}"] = run_fact_check(d.get("body", ""), source_data)
                for result in st.session_state.get(f"legacy_fact_results_{d['id']}", []):
                    msg = f"**{result['title']}** — {result['detail']}"
                    if result["level"] == "warning": st.warning(msg)
                    elif result["level"] == "review": st.info(msg)
                    else: st.success(msg)
        with st.expander("Compare saved versions"):
            versions=d.get("versions",[])
            if len(versions)<2: st.caption("Save at least two revisions to compare versions.")
            else:
                opts={f"v{v['version']} · {v['timestamp']} · {v['action']}":v for v in versions}
                chosen=st.selectbox("Choose a saved revision",list(opts.keys()),key=f"version_compare_{d['id']}")
                current=opts[chosen]
                old,new=st.columns(2)
                with old: st.markdown("**Selected version**"); st.text_area("Previous body",value=current.get("body",""),height=220,disabled=True,key=f"oldbody_{d['id']}")
                with new: st.markdown("**Current version**"); st.text_area("Current body",value=d.get("body",""),height=220,disabled=True,key=f"newbody_{d['id']}")

# 04 — HUMAN REVIEW
elif st.session_state.page == "Human Review":
    page_header("QUALITY & GOVERNANCE", "Human review queue", "Review evidence, comments and version history before deciding whether a note is ready for approval.", "STEP 04 / AUTHORIZE")
    all_notes=list_drafts()
    filter_status=st.segmented_control("Queue filter",["All actionable","In Review","Changes Requested"],default="All actionable")
    queue=[d for d in all_notes if d.get("status") in ("In Review","Changes Requested")]
    if filter_status!="All actionable": queue=[d for d in queue if d.get("status")==filter_status]
    left,main,right=st.columns([1.02,1.65,1.05],gap="medium")
    with left:
        st.markdown('<div class="section-title">Review queue</div><div class="section-subtitle">Select a document</div>',unsafe_allow_html=True)
        if not queue: empty_state("Queue is clear","Submit a draft for human review to see it here.")
        else:
            for item in queue:
                with st.container(border=True):
                    st.markdown(f'<div class="doc-id">{item["id"]}</div><div class="doc-title">{item.get("headline","Untitled")}</div><div class="muted">{item.get("department","Authority not set")}</div>',unsafe_allow_html=True)
                    status_pill(item.get("status","In Review"))
                    if st.button("Review this note →",key=f"review_select_{item['id']}",use_container_width=True): st.session_state.active_draft_id=item["id"]; st.rerun()
    active=st.session_state.active_draft_id
    selected_d=get_draft(active) if active else None
    if selected_d and selected_d not in queue and selected_d.get("status") in ("In Review","Changes Requested"):
        selected_d=None
    if not selected_d and queue:
        selected_d=queue[0]; st.session_state.active_draft_id=selected_d["id"]
    with main:
        if not selected_d: empty_state("Select a review item","The document preview will appear here.")
        else:
            st.markdown(f'<div class="doc-id">{selected_d["id"]} · VERSION {len(selected_d.get("versions",[]))+1}</div><div class="section-title">{selected_d.get("headline","Untitled press note")}</div>',unsafe_allow_html=True)
            status_pill(selected_d.get("status","In Review"))
            st.write("")
            tab1,tab2=st.tabs(["Document preview","Version comparison"])
            with tab1: preview_document(selected_d)
            with tab2:
                versions=selected_d.get("versions",[])
                if versions:
                    opts={f"v{v['version']} · {v['timestamp']} · {v['action']}":v for v in versions}
                    version_key=st.selectbox("Compare with saved revision",list(opts.keys()),key=f"review_ver_{selected_d['id']}")
                    prev=opts[version_key]
                    old,new=st.columns(2)
                    with old: st.markdown("**Saved revision**"); st.text_area("Previous text",value=prev.get("body",""),height=240,disabled=True,key=f"review_old_{selected_d['id']}")
                    with new: st.markdown("**Current draft**"); st.text_area("Current text",value=selected_d.get("body",""),height=240,disabled=True,key=f"review_new_{selected_d['id']}")
                else: st.info("No saved revision snapshots yet. The current draft can still be reviewed against source evidence.")
            st.markdown("**Source evidence**")
            if selected_d.get("sources_list"):
                for src in selected_d["sources_list"]:
                    status="Verified by reviewer" if src.get("status")=="Verified by reviewer" else "Needs verification"
                    st.markdown(f'<div class="source-row"><div class="source-title">{src.get("title","Source")}</div><div class="source-meta">{src.get("reference","No reference")}</div><span class="pill {"approved" if status=="Verified by reviewer" else "pending"}">{status}</span></div>',unsafe_allow_html=True)
            else: st.warning("No structured source evidence. Verify the source references before approving.")
    with right:
        if selected_d:
            st.markdown('<div class="section-title">Reviewer notes</div><div class="section-subtitle">Comments are retained in the record</div>',unsafe_allow_html=True)
            comments=selected_d.get("comments",[])
            if comments:
                for item in comments[-5:]:
                    st.markdown(f'<div class="doc-card"><div class="doc-id">{item.get("author","Reviewer")} · {item.get("timestamp","")[:16]}</div><div class="muted" style="margin-top:6px">{item.get("comment","")}</div></div>',unsafe_allow_html=True)
            else: st.caption("No comments yet.")
            reviewer=st.text_input("Reviewer name / role",placeholder="Authorized reviewer",key=f"reviewer_name_{selected_d['id']}")
            with st.form(f"review_comment_form_{selected_d['id']}"):
                comment=st.text_area("Add review comment",height=90,placeholder="Mention the exact claim, source or edit required.")
                add=st.form_submit_button("Add comment",use_container_width=True)
            if add:
                if reviewer.strip() and comment.strip(): add_comment(selected_d["id"],reviewer.strip(),comment.strip()); st.session_state.flash="Comment added to the record."; st.rerun()
                else: st.error("Enter reviewer name above and add a comment.")
            st.divider()
            st.markdown('<div class="section-title">Verification checklist</div><div class="section-subtitle">Complete only after checking evidence</div>',unsafe_allow_html=True)
            checks=[st.checkbox("Names, dates and locations checked",key=f"rv1_{selected_d['id']}"),st.checkbox("Figures and claims match sources",key=f"rv2_{selected_d['id']}"),st.checkbox("Quotes and attributions authorized",key=f"rv3_{selected_d['id']}"),st.checkbox("Neutral language and privacy checked",key=f"rv4_{selected_d['id']}"),st.checkbox("Hindi / English version reviewed",key=f"rv5_{selected_d['id']}")]
            reason=st.text_area("Decision note / reason",height=75,key=f"decision_reason_{selected_d['id']}",placeholder="Required for changes or rejection")
            ready=all(checks) and bool(reviewer.strip())
            if st.button("✓  Approve final version",type="primary",use_container_width=True,disabled=not ready,key=f"approve_{selected_d['id']}"):
                decide(selected_d["id"],reviewer.strip(),"Approved",reason.strip()); st.session_state.flash="Approval recorded. The note is not yet published."; st.rerun()
            if st.button("↻  Request changes",use_container_width=True,key=f"changes_{selected_d['id']}"):
                if not reviewer.strip() or not reason.strip(): st.error("Enter reviewer identity and specific changes required.")
                else: decide(selected_d["id"],reviewer.strip(),"Changes Requested",reason.strip()); st.session_state.flash="Returned to the author for changes."; st.rerun()
            if st.button("✕  Reject submission",use_container_width=True,key=f"reject_{selected_d['id']}"):
                if not reviewer.strip() or not reason.strip(): st.error("Enter reviewer identity and a rejection reason.")
                else: decide(selected_d["id"],reviewer.strip(),"Rejected",reason.strip()); st.session_state.flash="Rejection recorded with a reason."; st.rerun()
            st.caption("Approval requires all five checks and the single reviewer name entered above. These are prototype workflow controls, not production authentication.")

# 06 — PUBLISHING
elif st.session_state.page == "Published Notes":
    page_header("RELEASE MANAGEMENT", "Approved & published notes", "Publication is separate from approval. This prototype can publish to its local archive; external website publishing requires a configured CMS/API.", "STEP 05 / RELEASE")
    all_notes=list_drafts()
    ready=[d for d in all_notes if d.get("status")=="Approved"]
    live=[d for d in all_notes if d.get("status")=="Published"]
    a,b=st.columns(2)
    with a: metric_card("Ready to publish",len(ready),"Approved but not released","↗")
    with b: metric_card("Published to local archive",len(live),"Publication records","✓")
    st.write("")
    st.markdown('<div class="section-title">Ready to publish</div><div class="section-subtitle">Only approved notes appear in this queue</div>',unsafe_allow_html=True)
    if not ready: empty_state("No approved notes waiting","An authorized reviewer must approve a note before it appears here.")
    for d in ready:
        with st.container(border=True):
            l,r=st.columns([3,1])
            with l:
                st.markdown(f'<div class="doc-id">{d["id"]}</div><div class="doc-title">{d.get("headline","Untitled")}</div><div class="muted">Approved by {d.get("review_log", [{}])[-1].get("actor","authorized reviewer")} · {d.get("updated","")[:16]}</div>',unsafe_allow_html=True)
            with r:
                if st.button("Publish to local archive",type="primary",key=f"publish_{d['id']}",use_container_width=True):
                    decide(d["id"],"Publishing Officer","Published","Published to the PressAI local archive; no external website was contacted.")
                    st.session_state.flash="Published to the local archive. No public website was contacted."; st.rerun()
    st.write("")
    st.markdown('<div class="section-title">Published records</div>',unsafe_allow_html=True)
    if not live: st.caption("No notes published yet.")
    for d in live:
        with st.expander(f'{d["id"]} · {d.get("headline","Untitled")}'):
            status_pill(d["status"])
            st.write(d.get("summary", ""))
            st.caption(f"Archive record updated: {d.get('updated','')}")
            content=f"{d.get('headline','')}\n\n{d.get('summary','')}\n\n{d.get('body','')}\n\nPublication status: Published to local archive\nDocument ID: {d['id']}"
            st.download_button("Download final TXT",content,file_name=f"{d['id']}_FINAL.txt",mime="text/plain",key=f"published_export_{d['id']}")

# 07 — HISTORY
elif st.session_state.page == "History & Analytics":
    page_header("RECORDS & AUDIT", "History & analytics", "Search press notes and inspect revision, review and publication events.", "AUDIT / TRACEABILITY")
    all_notes=list_drafts()
    query=st.text_input("Search records",placeholder="Headline, document ID, institution or department")
    status_filter=st.selectbox("Filter by status",["All statuses","Draft","In Review","Changes Requested","Approved","Rejected","Published"])
    filtered=[d for d in all_notes if query.lower() in (d.get("headline","")+d.get("id","")+d.get("department","")+d.get("institution","")).lower() and (status_filter=="All statuses" or d.get("status")==status_filter)]
    c1,c2,c3=st.columns(3)
    with c1: metric_card("Records found",len(filtered),"Current filters","▤")
    with c2: metric_card("Review decisions",sum(len(d.get("review_log",[])) for d in filtered),"Approval / return / rejection","✓")
    with c3: metric_card("Revision snapshots",sum(len(d.get("versions",[])) for d in filtered),"Saved versions","◷")
    for d in sorted(filtered,key=lambda x:x.get("updated",""),reverse=True):
        with st.expander(f'{d["id"]} · {d.get("headline","Untitled")} · {d.get("status","Draft")}'):
            a,b=st.columns(2)
            with a:
                st.write(f"**Created:** {d.get('created','—')}")
                st.write(f"**Department:** {d.get('department') or 'Not specified'}")
                st.write(f"**Language:** {d.get('language','Not specified')}")
            with b:
                st.write(f"**Updated:** {d.get('updated','—')}")
                st.write(f"**Source status:** {d.get('source_status','Not assessed')}")
                st.write(f"**Comments:** {len(d.get('comments',[]))}")
            st.markdown("**Audit events**")
            for ev in audit_for(d["id"])[:15]: st.caption(f"{ev['created_at'][:19]} · {ev['actor']} · {ev['action']} {('— ' + ev['details']) if ev.get('details') else ''}")
            export_json, export_pdf = st.columns(2)
            with export_json:
                st.download_button(
                    "Export record JSON",
                    json.dumps(d, ensure_ascii=False, indent=2),
                    file_name=f"{d['id']}_record.json",
                    mime="application/json",
                    key=f"record_export_{d['id']}",
                    use_container_width=True,
                )
            with export_pdf:
                # Export a readable press-note PDF directly from the saved history record.
                pdf_data = dict(d.get("input_data", {}) or {})
                pdf_data.update({
                    "institution_name": d.get("institution") or pdf_data.get("institution_name", ""),
                    "department": d.get("department") or pdf_data.get("department", ""),
                    "location": d.get("venue") or pdf_data.get("location", ""),
                    "press_note_no": d.get("note_number") or pdf_data.get("press_note_no", ""),
                    "release_date": d.get("release_date") or pdf_data.get("release_date", ""),
                    "event_date": d.get("date") or pdf_data.get("event_date", ""),
                    "issuing_officer": d.get("issuing_person") or pdf_data.get("issuing_officer", ""),
                })
                pdf_text = (
                    f"{d.get('headline', 'Press Note')}\n\n"
                    f"{d.get('summary', '')}\n\n"
                    f"{d.get('body', '')}"
                )
                try:
                    pdf_bytes = create_press_note_pdf(
                        pdf_text,
                        pdf_data,
                        d.get("language", "English"),
                        is_draft=d.get("status") not in ("Approved", "Published"),
                    )
                    st.download_button(
                        "Export record PDF",
                        pdf_bytes,
                        file_name=f"{d['id']}_press_note.pdf",
                        mime="application/pdf",
                        key=f"record_pdf_export_{d['id']}",
                        use_container_width=True,
                    )
                except Exception as pdf_exc:
                    st.caption(f"PDF export unavailable: {pdf_exc}")
    st.caption("Records persist in data/pressai_local.db on this machine. This local prototype is not a substitute for authenticated access control, encrypted storage, backups or a production audit service.")
