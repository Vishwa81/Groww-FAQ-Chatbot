"""
Groww Mutual Fund FAQ Assistant - Streamlit Application.
A facts-only mutual fund FAQ assistant prototype inspired by Groww's clean UI.
"""

import streamlit as st
from src.config import config
from src.response import response_service
from src.guardrails import GuardrailEngine

# --- Page Configuration ---
st.set_page_config(
    page_title="Groww | Mutual Fund FAQ Assistant",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom Groww-Inspired CSS Styling ---
st.markdown(
    f"""
    <style>
        /* Import clean Inter font */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        /* Root styling and backgrounds */
        html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            color: {config.COLOR_TEXT_MAIN};
            background-color: {config.COLOR_BG_PRIMARY};
        }}

        .main .block-container {{
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 900px;
        }}

        /* Groww Brand Accent Header Badge */
        .groww-badge {{
            display: inline-flex;
            align-items: center;
            background-color: {config.COLOR_ACCENT_LIGHT};
            color: #008765;
            font-size: 0.82rem;
            font-weight: 600;
            padding: 4px 12px;
            border-radius: 20px;
            margin-bottom: 0.8rem;
            border: 1px solid rgba(0, 208, 156, 0.25);
        }}

        /* Headings and Typography */
        .groww-heading {{
            font-size: 2.25rem;
            font-weight: 700;
            color: {config.COLOR_TEXT_MAIN};
            letter-spacing: -0.02em;
            margin-bottom: 0.5rem;
            line-height: 1.25;
        }}

        .groww-description {{
            font-size: 1.05rem;
            color: {config.COLOR_TEXT_MUTED};
            line-height: 1.6;
            margin-bottom: 1.5rem;
        }}

        /* Disclaimer Banner */
        .disclaimer-banner {{
            background-color: #F8FAFC;
            border-left: 4px solid {config.COLOR_PRIMARY};
            border-radius: 8px;
            padding: 12px 18px;
            margin-bottom: 1.8rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border: 1px solid {config.COLOR_BORDER};
            border-left: 4px solid {config.COLOR_PRIMARY};
        }}

        .disclaimer-title {{
            font-weight: 600;
            font-size: 0.92rem;
            color: {config.COLOR_TEXT_MAIN};
        }}

        .disclaimer-subtitle {{
            font-size: 0.82rem;
            color: {config.COLOR_TEXT_MUTED};
        }}

        /* Scheme Chip Cards */
        .scheme-card {{
            background: #FFFFFF;
            border: 1px solid {config.COLOR_BORDER};
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 8px;
            transition: all 0.15s ease-in-out;
        }}
        .scheme-card:hover {{
            border-color: {config.COLOR_PRIMARY};
            box-shadow: 0 4px 12px rgba(0, 208, 156, 0.08);
        }}
        .scheme-tag {{
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            color: {config.COLOR_PRIMARY};
            letter-spacing: 0.05em;
        }}
        .scheme-name {{
            font-weight: 600;
            font-size: 0.95rem;
            color: {config.COLOR_TEXT_MAIN};
            margin-top: 2px;
        }}

        /* Example Questions Container */
        .example-header {{
            font-size: 0.88rem;
            font-weight: 600;
            color: {config.COLOR_TEXT_MUTED};
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.6rem;
        }}

        /* Primary Button & Inputs styling */
        .stButton>button {{
            border-radius: 10px;
            font-weight: 500;
            font-size: 0.92rem;
            border: 1px solid {config.COLOR_BORDER};
            background-color: #FFFFFF;
            color: {config.COLOR_TEXT_MAIN};
            padding: 0.6rem 1rem;
            width: 100%;
            text-align: left;
            transition: all 0.15s ease;
        }}

        .stButton>button:hover {{
            border-color: {config.COLOR_PRIMARY};
            background-color: {config.COLOR_ACCENT_LIGHT};
            color: #007054;
        }}

        /* Source Card */
        .source-card {{
            background-color: #F9FAFB;
            border: 1px solid {config.COLOR_BORDER};
            border-radius: 8px;
            padding: 10px 14px;
            margin-top: 10px;
            font-size: 0.85rem;
        }}
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Sidebar Configuration ---
with st.sidebar:
    st.image(
        "https://groww.in/groww-logo-270.png",
        width=120,
        caption="Product Management Fellowship Milestone",
    )
    st.markdown("### 📌 Product Scope")
    st.markdown(
        """
        - **Product Concept**: Groww Mutual Fund FAQ Assistant
        - **AMC**: HDFC Mutual Fund
        - **Objective**: Assist users with verified facts from official SIDs/KIMs.
        """
    )

    st.markdown("---")
    st.markdown("### 🏛️ Initial Schemes")
    for scheme in config.SUPPORTED_SCHEMES:
        st.markdown(f"• **{scheme}**")

    st.markdown("---")
    st.markdown("### ⚖️ Regulatory Notice")
    st.info(
        f"**{config.DISCLAIMER_TEXT}**\n\n"
        "This tool is for informational verification only and does not offer financial advisory, "
        "ratings, return forecasts, or fund recommendations.",
        icon="ℹ️",
    )

    st.markdown("---")
    st.markdown("### ⚙️ System Status")
    status = config.get_status_summary()
    st.caption(f"**Environment**: `{status['environment']}`")
    st.caption(f"**Gemini API Key**: `{'Configured' if status['api_key_configured'] else 'Pending in .env'}`")
    st.caption(f"**Vector Store**: `ChromaDB (895 vectors indexed)`")
    st.caption(f"**RAG Status**: `Active (Grounded on 9 official documents)`")

# --- Hero Section ---
st.markdown('<div class="groww-badge">✦ Groww Milestone Prototype</div>', unsafe_allow_html=True)
st.markdown(f'<div class="groww-heading">{config.WELCOME_HEADING}</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="groww-description">'
    f'{config.WELCOME_SUBHEADING}'
    f'</div>',
    unsafe_allow_html=True,
)

# --- Disclaimer Banner ---
st.markdown(
    f"""
    <div class="disclaimer-banner">
        <div>
            <div class="disclaimer-title">🔒 {config.DISCLAIMER_TEXT}</div>
            <div class="disclaimer-subtitle">Official scheme information documents and service guides are used for factual grounding.</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# --- Initial Schemes Overview ---
st.markdown('<div class="example-header">Supported HDFC Schemes</div>', unsafe_allow_html=True)
cols = st.columns(3)
scheme_types = ["Index / Passive", "Equity / Flexi Cap", "ELSS / Tax Saver"]
for idx, (col, scheme, s_type) in enumerate(zip(cols, config.SUPPORTED_SCHEMES, scheme_types)):
    with col:
        st.markdown(
            f"""
            <div class="scheme-card">
                <div class="scheme-tag">{s_type}</div>
                <div class="scheme-name">{scheme}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

# --- Session State for Chat ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Quick Example Questions ---
st.markdown('<div class="example-header">Try Asking an Example Question</div>', unsafe_allow_html=True)
example_cols = st.columns(3)

clicked_question = None
for idx, (ex_col, question_text) in enumerate(zip(example_cols, config.EXAMPLE_QUESTIONS)):
    with ex_col:
        if st.button(f"💬 {question_text}", key=f"ex_btn_{idx}"):
            clicked_question = question_text

# If an example question button was clicked, handle response
if clicked_question:
    # Check for PII before storing
    if GuardrailEngine.detect_pii(clicked_question):
        st.warning(
            "🔒 For your privacy and security, sensitive identifiers (PAN, Aadhaar, account numbers, etc.) "
            "cannot be processed or saved. Please ask factual questions without personal information.",
            icon="⚠️"
        )
    else:
        st.session_state.messages.append({"role": "user", "content": clicked_question})
        with st.spinner("Retrieving verified facts from official documents..."):
            response_result = response_service.process_query(clicked_question)

        st.session_state.messages.append({
            "role": "assistant",
            "content": response_result["formatted_response"],
            "status": response_result["status"],
            "source_link": response_result.get("source_link"),
            "document_title": response_result.get("document_title"),
            "page_number": response_result.get("page_number"),
            "last_updated": response_result.get("last_updated"),
        })

# --- Chat Messages Display ---
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.write(msg["content"])
    else:
        with st.chat_message("assistant", avatar="📈"):
            st.markdown(msg["content"])

# --- Chat Input ---
user_input = st.chat_input("Ask a factual question about HDFC Mutual Fund schemes...")

if user_input:
    # 1. PII Safety Check: Never save user questions containing PII to session state
    if GuardrailEngine.detect_pii(user_input):
        st.warning(
            "🔒 **Privacy Notice**: For your security and privacy, this assistant does not process, "
            "collect, or store personal identifiers (such as PAN, Aadhaar, phone numbers, or OTPs). "
            "Please ask factual questions without sharing sensitive financial details.",
            icon="⚠️"
        )
    else:
        # Append user question to session state
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)

        # Process through RAG FAQ response service with loading indicator
        with st.chat_message("assistant", avatar="📈"):
            with st.spinner("Retrieving verified facts from official documents..."):
                response_result = response_service.process_query(user_input)
            st.markdown(response_result["formatted_response"])

        st.session_state.messages.append({
            "role": "assistant",
            "content": response_result["formatted_response"],
            "status": response_result["status"],
            "source_link": response_result.get("source_link"),
            "document_title": response_result.get("document_title"),
            "page_number": response_result.get("page_number"),
            "last_updated": response_result.get("last_updated"),
        })
