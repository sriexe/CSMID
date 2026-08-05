"""
src/ui.py — Streamlit Frontend for CSMID Market Copilot
"""

import streamlit as st
import requests

API_BASE_URL = "http://localhost:8000"

st.set_page_config(
    page_title="CSMID Market Copilot",
    page_icon="🎯",
    layout="wide"
)

st.title("🎯 CSMID Market Copilot")
st.caption("AI Assistant backed by Supabase history, walk-forward forecasting, and patch-note intelligence.")

# Sidebar Configuration
st.sidebar.header("Agent Parameters")
budget_input = st.sidebar.slider("Investment Budget ($)", min_value=5.0, max_value=500.0, value=50.0, step=5.0)
min_accuracy_input = st.sidebar.slider("Min. Model Accuracy Threshold (%)", min_value=70, max_value=98, value=90, step=1)

# Health Check Indicator
try:
    health_resp = requests.get(f"{API_BASE_URL}/health", timeout=2)
    if health_resp.status_code == 200 and health_resp.json().get("agent_connected"):
        st.sidebar.success("Backend API: Connected 🟢")
    else:
        st.sidebar.warning("Backend API: Agent Uninitialized 🟡")
except Exception:
    st.sidebar.error("Backend API: Offline 🔴 (Run uvicorn src.app:app)")

st.sidebar.markdown("---")
st.sidebar.subheader("Quick Actions")

col_a, col_b = st.sidebar.columns(2)

# Initialize Session Chat History
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Welcome! Ask me to inspect any skin, scan for buy picks under your budget, or check 90%+ confidence sell alerts."}
    ]

# Render Existing Chat Messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Quick Action Buttons Logic
if col_a.button("🔍 Check Glock Block-18"):
    prompt = "Inspect Glock-18 Block-18"
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()

if col_b.button("🚨 Check Sells"):
    prompt = f"Check high confidence sell alerts above {min_accuracy_input}% accuracy"
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()

# Handle Chat Input
if prompt := st.chat_input("Ask Copilot (e.g., 'What should I buy with $40?')"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call FastAPI Endpoint
    with st.chat_message("assistant"):
        with st.spinner("Analyzing market data..."):
            try:
                payload = {
                    "message": prompt,
                    "budget": budget_input,
                    "min_accuracy": float(min_accuracy_input)
                }
                res = requests.post(f"{API_BASE_URL}/api/v1/chat", json=payload, timeout=10)
                
                if res.status_code == 200:
                    reply = res.json().get("reply", "No response received.")
                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                else:
                    err_msg = f"API Error ({res.status_code}): {res.text}"
                    st.error(err_msg)
            except Exception as e:
                st.error(f"Could not connect to FastAPI server at {API_BASE_URL}: {e}")