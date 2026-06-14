import streamlit as st
import os
import sys
import re
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

# Load env variables
load_dotenv()

# Initialize DB on startup
from database import init_db
init_db()

from agent import get_agent_executor
from tools import fetch_train_delay_history_detailed, fetch_train_schedule_detailed, fetch_train_fare


def sanitize_output(text):
    """Strip any leaked JSON blocks, tool names, or technical patterns from agent output."""
    if not text:
        return text
    # Remove JSON-like blocks: {"name": ..., "parameters": ...}
    text = re.sub(r'\{\s*"name"\s*:.*?\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\{\s*"type"\s*:\s*"function".*?\}', '', text, flags=re.DOTALL)
    # Remove tool/function name references
    text = re.sub(r'fetch_route_recommendations|fetch_train_delay_history|fetch_train_schedule|lookup_station_code|fetch_trains_between_stations', '', text)
    # Remove phrases like "call the tool" or "here's the JSON"
    text = re.sub(r"(?i)(here'?s? the (json|function call|tool call)[^.]*\.?)", '', text)
    text = re.sub(r"(?i)(I('ll| will| need to) (call|invoke|use) the [^.]*\.?)", '', text)
    # Clean up leftover whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# Setup page layout
st.set_page_config(
    page_title="AI Travel Concierge Agent",
    page_icon=None,
    layout="centered",
    initial_sidebar_state="expanded"
)

# Custom Premium Styling Injected via CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');

    /* Global styling */
    .stApp {
        background: linear-gradient(135deg, #0b0f19 0%, #1e1b4b 100%);
        color: #f1f5f9;
        font-family: 'Outfit', sans-serif;
    }
    
    /* Input area adjustments */
    div[data-testid="stChatInput"] {
        background-color: rgba(30, 41, 59, 0.4) !important;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.1);
    }
    
    /* Header Container styling */
    .header-card {
        background: rgba(30, 41, 59, 0.4);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 24px;
        margin-bottom: 24px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
        text-align: center;
    }
    
    .header-title {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #6366f1, #a855f7, #ec4899);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 8px;
    }
    
    .header-subtitle {
        color: #94a3b8;
        font-size: 1.0rem;
    }
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #090d16 !important;
        border-right: 1px solid rgba(255, 255, 255, 0.08);
    }
    
    /* Indicator status styling */
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        margin-top: 8px;
    }
    .status-active {
        background-color: rgba(16, 185, 129, 0.2);
        color: #10b981;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .status-inactive {
        background-color: rgba(239, 68, 68, 0.2);
        color: #ef4444;
        border: 1px solid rgba(239, 68, 68, 0.3);
    }
</style>
""", unsafe_allow_html=True)

# Page navigation in sidebar
with st.sidebar:
    st.markdown("## Navigation")
    page = st.selectbox(
        "Go to Page:",
        ["AI Travel Concierge", "Train Delay History", "Train Details & Schedule"],
        key="navigation_page"
    )
    st.markdown("---")
    st.markdown("## Configuration Panel")
    
    # API Key Input
    env_key = os.getenv("NVIDIA_API_KEY")
    if env_key:
        st.session_state.nvidia_api_key = env_key
        st.markdown("""
        <div class="status-badge status-active">
            NVIDIA API Key Configured (.env)
        </div>
        """, unsafe_allow_html=True)
    else:
        user_key = st.text_input("Enter NVIDIA API Key:", type="password", key="sidebar_key")
        if user_key:
            st.session_state.nvidia_api_key = user_key
            os.environ["NVIDIA_API_KEY"] = user_key
            st.markdown("""
            <div class="status-badge status-active">
                API Key Configured (Session)
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="status-badge status-inactive">
                API Key Missing
            </div>
            """, unsafe_allow_html=True)
            
    st.markdown("---")
    st.markdown("### System Specs")
    st.markdown("- **Engine:** LangChain ReAct Agent")
    st.markdown("- **Model:** Llama 3.3 70B Instruct")
    st.markdown("- **Cache:** Local SQLite Cache enabled")
    st.markdown("- **DataSource:** etrain.info (blueprints loaded)")
    
    if st.button("Clear Cache Database"):
        try:
            import sqlite3
            from database import DB_PATH
            if os.path.exists(DB_PATH):
                os.remove(DB_PATH)
                st.success("Cache database deleted successfully.")
                init_db()
            else:
                st.info("No cache database found to clear.")
        except Exception as e:
            st.error(f"Error clearing cache: {str(e)}")

# Conditionally render pages based on navigation choice
if page == "AI Travel Concierge":
    # Render main header
    st.markdown("""
    <div class="header-card">
        <div class="header-title">AI Travel Concierge Agent</div>
        <div class="header-subtitle">Your expert, empathetic travel planner powered by Llama 3.3 and local SQLite caching</div>
    </div>
    """, unsafe_allow_html=True)

    # Welcome message init
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Hello! I am your empathetic AI Travel Concierge. I can help you fuzzy-match station names, search routes, check punctuality, and plan your journey. Where are you starting from, where is your destination, and when would you like to travel?"
            }
        ]

    # Render chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # User Chat Input
    if user_input := st.chat_input("Enter your request here (e.g., 'Trains from Visakhapatnam to Tirupathi on June 26, 2026')"):
        # Display user message
        with st.chat_message("user"):
            st.write(user_input)
        st.session_state.messages.append({"role": "user", "content": user_input})
        
        # Check if API Key is configured
        api_key_configured = st.session_state.get("nvidia_api_key") or os.environ.get("NVIDIA_API_KEY")
        
        if not api_key_configured:
            with st.chat_message("assistant"):
                warning_msg = "Please configure your NVIDIA API Key in the sidebar configuration panel to continue planning your trip."
                st.write(warning_msg)
                st.session_state.messages.append({"role": "assistant", "content": warning_msg})
        else:
            # Guarantee it's in the env variables for langchain to load
            os.environ["NVIDIA_API_KEY"] = api_key_configured
            
            # Display assistant thought/spinner
            with st.chat_message("assistant"):
                with st.spinner("Concierge is planning your route and verifying timetables..."):
                    try:
                        # Convert session state message list to LangChain format
                        chat_history = []
                        for msg in st.session_state.messages[:-1]: # exclude the latest user message
                            if msg["role"] == "user":
                                chat_history.append(HumanMessage(content=msg["content"]))
                            elif msg["role"] == "assistant":
                                chat_history.append(AIMessage(content=msg["content"]))
                                
                        # Get AgentExecutor
                        agent_executor = get_agent_executor()
                        
                        # Run agent
                        result = agent_executor.invoke({
                            "input": user_input,
                            "chat_history": chat_history
                        })
                        
                        ai_response = sanitize_output(result["output"])
                        st.write(ai_response)
                        st.session_state.messages.append({"role": "assistant", "content": ai_response})
                        
                    except Exception as e:
                        error_msg = f"An error occurred during agent planning: {str(e)}"
                        st.error(error_msg)
                        st.session_state.messages.append({"role": "assistant", "content": error_msg})

elif page == "Train Delay History":
    st.markdown("""
<div class="header-card">
    <div class="header-title">Train Delay History Tracker</div>
    <div class="header-subtitle">Analyze running delay statistics and average arrival times across stations</div>
</div>
""", unsafe_allow_html=True)

    # Input Form styles
    st.markdown("""
<style>
.legend-card {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 24px;
    font-size: 0.85rem;
    justify-content: center;
    background: rgba(30, 41, 59, 0.2);
    padding: 12px;
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.05);
}
.badge-rt {
    background-color: rgba(16, 185, 129, 0.15) !important;
    color: #10b981 !important;
    border: 1px solid rgba(16, 185, 129, 0.3) !important;
}
.badge-sd {
    background-color: rgba(245, 158, 11, 0.15) !important;
    color: #f59e0b !important;
    border: 1px solid rgba(245, 158, 11, 0.3) !important;
}
.badge-sigd {
    background-color: rgba(239, 68, 68, 0.15) !important;
    color: #ef4444 !important;
    border: 1px solid rgba(239, 68, 68, 0.3) !important;
}
.badge-unk {
    background-color: rgba(148, 163, 184, 0.15) !important;
    color: #94a3b8 !important;
    border: 1px solid rgba(148, 163, 184, 0.3) !important;
}
</style>
""", unsafe_allow_html=True)
    
    col1, col2 = st.columns([3, 2])
    with col1:
        train_no = st.text_input("Enter Train Number (e.g., 22603):", placeholder="e.g. 22603")
    with col2:
        timeline = st.selectbox(
            "Select Timeline:",
            ["Past Week", "1 Month", "3 Months", "6 Months", "1 Year"],
            index=4
        )
    
    # Map timeline to query parameter
    timeline_map = {
        "Past Week": "1w",
        "1 Month": "1m",
        "3 Months": "3m",
        "6 Months": "6m",
        "1 Year": "1y"
    }
    duration = timeline_map[timeline]
    
    if st.button("Fetch Delay History", use_container_width=True):
        if not train_no.strip():
            st.warning("Please enter a valid Train Number.")
        else:
            with st.spinner(f"Retrieving delay logs for train {train_no}..."):
                try:
                    result = fetch_train_delay_history_detailed(train_no, duration)
                    if not result:
                        st.error(f"No statistics available for Train {train_no}. Please verify the number.")
                    elif isinstance(result, dict) and "error" in result:
                        st.error(result["error"])
                    else:
                        train_name = result.get("train_name", f"Train {train_no}")
                        train_route = result.get("train_route", "")
                        stations = result.get("stations", [])
                        
                        if not stations:
                            st.warning("No station records parsed. This train might have modified routes or no running logs.")
                        else:
                            st.markdown(f"""
<div style="background: rgba(99, 102, 241, 0.1); border: 1px solid rgba(99, 102, 241, 0.25); border-radius: 12px; padding: 20px; margin-bottom: 24px; box-shadow: 0 4px 20px rgba(0,0,0,0.15);">
    <h3 style="margin: 0; color: #a5b4fc; font-weight: 600; font-size: 1.4rem;">{train_name}</h3>
    <p style="margin: 6px 0 0 0; color: #94a3b8; font-size: 1.0rem;">{train_route}</p>
    <div style="display: flex; gap: 20px; margin-top: 12px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 12px; font-size: 0.9rem; color: #cbd5e1;">
        <span>Timeline: <b>{timeline}</b></span>
        <span>Total Scheduled Stops: <b>{len(stations)}</b></span>
    </div>
</div>
""", unsafe_allow_html=True)
                            
                            # Legends
                            st.markdown("""
<div class="legend-card">
    <span class="badge-rt" style="border-radius: 6px; padding: 4px 8px; font-weight: 600;"><span style="color: #10b981;">●</span> Right Time (0-15 Min)</span>
    <span class="badge-sd" style="border-radius: 6px; padding: 4px 8px; font-weight: 600;"><span style="color: #f59e0b;">●</span> Slight Delay (15-60 Min)</span>
    <span class="badge-sigd" style="border-radius: 6px; padding: 4px 8px; font-weight: 600;"><span style="color: #ef4444;">●</span> Significant Delay (>1 Hour)</span>
    <span class="badge-unk" style="border-radius: 6px; padding: 4px 8px; font-weight: 600;"><span style="color: #94a3b8;">●</span> Cancelled/Unknown</span>
</div>
""", unsafe_allow_html=True)
                            
                            # Row creation
                            table_rows_html = ""
                            for idx, stn in enumerate(stations, 1):
                                code = stn.get("code", "")
                                name = stn.get("name", "")
                                avg_delay = stn.get("avg_delay")
                                pct = stn.get("percentages", {"green": 0.0, "yellow": 0.0, "red": 0.0, "grey": 0.0})
                                
                                if avg_delay is None:
                                    status_label = "Cancelled/Unknown"
                                    status_class = "badge-unk"
                                    delay_display = "-"
                                elif avg_delay <= 15:
                                    status_label = "Right Time"
                                    status_class = "badge-rt"
                                    delay_display = f"{int(avg_delay)} Min"
                                elif avg_delay <= 60:
                                    status_label = "Slight Delay"
                                    status_class = "badge-sd"
                                    delay_display = f"{int(avg_delay)} Min"
                                else:
                                    status_label = "Significant Delay"
                                    status_class = "badge-sigd"
                                    hours = int(avg_delay) // 60
                                    mins = int(avg_delay) % 60
                                    delay_display = f"{hours}h {mins}m" if mins > 0 else f"{hours}h"
                                    
                                # Stacked progress bar
                                has_percentage_data = any(v > 0 for v in pct.values())
                                if has_percentage_data:
                                    bar_html = f"""<div style="display: flex; width: 100%; height: 10px; border-radius: 5px; overflow: hidden; background-color: rgba(255,255,255,0.05); margin-top: 6px; border: 1px solid rgba(255,255,255,0.1);">
<div style="background-color: #10b981; width: {pct['green']}%;" title="Right Time: {pct['green']}%"></div>
<div style="background-color: #f59e0b; width: {pct['yellow']}%;" title="Slight Delay: {pct['yellow']}%"></div>
<div style="background-color: #ef4444; width: {pct['red']}%;" title="Significant Delay: {pct['red']}%"></div>
<div style="background-color: #94a3b8; width: {pct['grey']}%;" title="Cancelled/Unknown: {pct['grey']}%"></div>
</div>
<div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #64748b; margin-top: 4px; padding: 0 2px;">
<span><span style="color: #10b981;">●</span> {int(pct['green'])}%</span>
<span><span style="color: #f59e0b;">●</span> {int(pct['yellow'])}%</span>
<span><span style="color: #ef4444;">●</span> {int(pct['red'])}%</span>
<span><span style="color: #94a3b8;">●</span> {int(pct['grey'])}%</span>
</div>"""
                                else:
                                    bar_html = '<div style="color: #64748b; font-size: 0.75rem; text-align: center; font-style: italic;">No records</div>'
                                    
                                row_bg = "rgba(255, 255, 255, 0.02)" if idx % 2 == 0 else "transparent"
                                
                                table_rows_html += f"""<tr style="background-color: {row_bg}; border-bottom: 1px solid rgba(255, 255, 255, 0.05); transition: background-color 0.2s;">
<td style="padding: 14px 12px; text-align: left; color: #64748b; font-size: 0.85rem; font-weight: 500;">{idx}</td>
<td style="padding: 14px 12px; text-align: left; font-weight: 700; color: #818cf8; font-size: 0.9rem; letter-spacing: 0.5px;">{code}</td>
<td style="padding: 14px 12px; text-align: left; color: #e2e8f0; font-size: 0.9rem; font-weight: 500;">{name}</td>
<td style="padding: 14px 12px; text-align: center; font-weight: 600; color: #f8fafc; font-size: 0.9rem;">{delay_display}</td>
<td style="padding: 14px 12px; text-align: center;">
<div class="{status_class}" style="display: inline-block; font-size: 0.75rem; font-weight: 700; border-radius: 8px; padding: 4px 10px;">
{status_label}
</div>
</td>
<td style="padding: 14px 12px; width: 220px; vertical-align: middle;">{bar_html}</td>
</tr>"""
                            
                            st.markdown(f"""
<div style="overflow-x: auto; background: rgba(30, 41, 59, 0.2); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 16px; padding: 10px; box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);">
<table style="width: 100%; border-collapse: collapse; font-family: 'Outfit', sans-serif;">
<thead>
<tr style="background-color: rgba(255, 255, 255, 0.03); border-bottom: 2px solid rgba(255, 255, 255, 0.08);">
<th style="padding: 14px 12px; text-align: left; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">#</th>
<th style="padding: 14px 12px; text-align: left; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">Code</th>
<th style="padding: 14px 12px; text-align: left; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">Station Name</th>
<th style="padding: 14px 12px; text-align: center; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">Avg Delay</th>
<th style="padding: 14px 12px; text-align: center; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">Status Badge</th>
<th style="padding: 14px 12px; text-align: left; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; width: 220px;">Punctuality Ratio</th>
</tr>
</thead>
<tbody>
{table_rows_html}
</tbody>
</table>
</div>
""", unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Error fetching delay history: {str(e)}")

elif page == "Train Details & Schedule":
    st.markdown("""
<div class="header-card">
    <div class="header-title">Train Details & Schedule</div>
    <div class="header-subtitle">Analyze complete schedule, timings, coach composition, and interactive fares</div>
</div>
""", unsafe_allow_html=True)

    col1, col2 = st.columns([3, 1])
    with col1:
        train_no = st.text_input("Enter Train Number (e.g., 22603):", placeholder="e.g. 22603", key="sch_train_input")
    with col2:
        st.write("")
        st.write("")
        fetch_btn = st.button("Fetch Train Info", use_container_width=True, key="sch_fetch_btn")

    if fetch_btn or train_no.strip():
        if not train_no.strip():
            st.warning("Please enter a valid Train Number.")
        else:
            with st.spinner(f"Retrieving details for train {train_no}..."):
                try:
                    result = fetch_train_schedule_detailed(train_no)
                    if not result:
                        st.error(f"No timetable details available for Train {train_no}. Please verify the number.")
                    elif isinstance(result, dict) and "error" in result:
                        st.error(result["error"])
                    else:
                        train_name = result.get("train_name", f"Train {train_no}")
                        route = result.get("route", "")
                        running_days = result.get("running_days", [])
                        classes = result.get("classes", [])
                        train_type = result.get("type", "")
                        zone = result.get("zone", "")
                        arp = result.get("arp", "")
                        rake_composition = result.get("rake_composition", [])
                        stops = result.get("stops", [])

                        if not stops:
                            st.warning("No stops found in timetable.")
                        else:
                            # 1. Premium Metadata Card
                            st.markdown(f"""
<div style="background: rgba(99, 102, 241, 0.08); border: 1px solid rgba(99, 102, 241, 0.2); border-radius: 16px; padding: 22px; margin-bottom: 24px; box-shadow: 0 8px 32px rgba(0,0,0,0.15);">
    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px;">
        <div>
            <h3 style="margin: 0; color: #a5b4fc; font-weight: 700; font-size: 1.6rem; letter-spacing: 0.5px;">{train_name}</h3>
            <p style="margin: 6px 0 0 0; color: #cbd5e1; font-size: 1.05rem; font-weight: 500;">{route}</p>
        </div>
        <div style="background: rgba(255,255,255,0.06); padding: 6px 14px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.08); text-align: center; min-width: 80px;">
            <span style="font-size: 0.72rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; display: block; font-weight: 600; margin-bottom: 2px;">Zone</span>
            <strong style="font-size: 1.1rem; color: #f8fafc;">{zone}</strong>
        </div>
    </div>
    <div style="display: flex; gap: 24px; margin-top: 16px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 16px; font-size: 0.92rem; color: #cbd5e1; flex-wrap: wrap;">
        <div>Type: <b style="color: #f8fafc;">{train_type}</b></div>
        <div>ARP: <b style="color: #f8fafc;">{arp}</b></div>
        <div>Available Classes: <b style="color: #818cf8;">{", ".join(classes)}</b></div>
    </div>
</div>
""", unsafe_allow_html=True)

                            # 2. Running Days Badge Layout
                            all_weekdays = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
                            active_days_set = {d.upper()[:3] for d in running_days}
                            
                            badges_html = ""
                            for day in all_weekdays:
                                is_active = day in active_days_set
                                if is_active:
                                    badges_html += f'<span style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 6px 14px; border-radius: 8px; font-weight: 700; font-size: 0.85rem; letter-spacing: 0.5px;">{day}</span>'
                                else:
                                    badges_html += f'<span style="background: rgba(255, 255, 255, 0.02); color: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.04); padding: 6px 14px; border-radius: 8px; font-weight: 600; font-size: 0.85rem; letter-spacing: 0.5px;">{day}</span>'
                                    
                            st.markdown(f"""
<div style="display: flex; gap: 8px; margin-bottom: 24px; align-items: center; flex-wrap: wrap;">
    <span style="font-weight: 600; color: #94a3b8; font-size: 0.9rem; text-transform: uppercase; margin-right: 8px; letter-spacing: 0.5px;">Running Days:</span>
    {badges_html}
</div>
""", unsafe_allow_html=True)

                            # 3. Visual Rake Layout
                            if rake_composition:
                                coaches_html = ""
                                for coach in rake_composition:
                                    ccode = coach["code"].upper()
                                    cclass = coach["class"].lower()
                                    cname = coach["name"]
                                    cidx = coach["index"]
                                    
                                    if "eng" in cclass or ccode == "ENG":
                                        bg = "linear-gradient(180deg, #475569 0%, #1e293b 100%)"
                                        border_color = "rgba(71, 85, 105, 0.5)"
                                        text_color = "#f1f5f9"
                                    elif "pwr" in cclass or ccode == "PWR":
                                        bg = "linear-gradient(180deg, #334155 0%, #0f172a 100%)"
                                        border_color = "rgba(51, 65, 85, 0.5)"
                                        text_color = "#cbd5e1"
                                    elif "ac" in cclass or any(ac in ccode for ac in ["A1", "A2", "B1", "B2", "B3", "B4", "B5", "B6", "2A", "3A"]):
                                        bg = "linear-gradient(180deg, #6366f1 0%, #4338ca 100%)"
                                        border_color = "rgba(99, 102, 241, 0.5)"
                                        text_color = "#ffffff"
                                    elif "sl" in cclass or (ccode.startswith("S") and ccode[1:].isdigit()):
                                        bg = "linear-gradient(180deg, #0d9488 0%, #0f766e 100%)"
                                        border_color = "rgba(13, 148, 136, 0.5)"
                                        text_color = "#ffffff"
                                    elif "gen" in cclass or ccode in ("GN", "GS"):
                                        bg = "linear-gradient(180deg, #f59e0b 0%, #b45309 100%)"
                                        border_color = "rgba(245, 158, 11, 0.5)"
                                        text_color = "#ffffff"
                                    elif "grd" in cclass or ccode == "GRD":
                                        bg = "linear-gradient(180deg, #78716c 0%, #44403c 100%)"
                                        border_color = "rgba(120, 113, 108, 0.5)"
                                        text_color = "#cbd5e1"
                                    else:
                                        bg = "linear-gradient(180deg, #475569 0%, #334155 100%)"
                                        border_color = "rgba(255,255,255,0.08)"
                                        text_color = "#cbd5e1"
                                        
                                    coaches_html += f"""
<div title="{cname}" style="flex: 0 0 auto; display: flex; flex-direction: column; justify-content: space-between; align-items: center; width: 62px; height: 50px; background: {bg}; border: 1px solid {border_color}; border-radius: 8px; color: {text_color}; position: relative; box-shadow: 0 4px 12px rgba(0,0,0,0.25); padding: 4px 0;">
    <span style="font-size: 0.62rem; font-weight: 600; opacity: 0.8; line-height: 1;">{cidx or '&nbsp;'}</span>
    <span style="font-size: 0.82rem; font-weight: 700; line-height: 1; letter-spacing: 0.5px; margin-bottom: 2px;">{ccode}</span>
</div>"""
                                    
                                st.markdown(f"""
<div style="margin-bottom: 30px;">
    <div style="font-size: 0.9rem; font-weight: 600; color: #94a3b8; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">Coach Rake Layout:</div>
    <div style="display: flex; flex-wrap: nowrap; overflow-x: auto; padding: 16px 12px; background: rgba(30, 41, 59, 0.2); border-radius: 14px; border: 1px solid rgba(255, 255, 255, 0.04); gap: 8px;">
        {coaches_html}
    </div>
</div>
""", unsafe_allow_html=True)

                            # 4. Interactive Expandable Fare Calculator
                            station_options = [f"{s['station_name']} ({s['station_code']})" for s in stops]
                            
                            with st.expander("Interactive Fare Calculator", expanded=False):
                                col_f1, col_f2 = st.columns(2)
                                with col_f1:
                                    src_label = st.selectbox("Get Fare From:", station_options, index=0, key="f_calc_src")
                                with col_f2:
                                    dest_label = st.selectbox("To Destination:", station_options, index=len(station_options)-1, key="f_calc_dest")
                                    
                                src_code = src_label.split("(")[-1].replace(")", "").strip()
                                dest_code = dest_label.split("(")[-1].replace(")", "").strip()
                                
                                # Validate stop indices
                                try:
                                    src_idx = next(idx for idx, s in enumerate(stops) if s["station_code"] == src_code)
                                    dest_idx = next(idx for idx, s in enumerate(stops) if s["station_code"] == dest_code)
                                except StopIteration:
                                    src_idx, dest_idx = 0, 0
                                    
                                if src_idx >= dest_idx:
                                    st.warning("Destination station must be after the boarding station.")
                                else:
                                    col_c1, col_c2, col_c3, col_c4, col_c5 = st.columns(5)
                                    with col_c1:
                                        adults = st.selectbox("Adults", list(range(7)), index=1, key="f_calc_ad")
                                    with col_c2:
                                        children = st.selectbox("Children", list(range(7)), index=0, key="f_calc_ch")
                                    with col_c3:
                                        sr_males = st.selectbox("Sr. Male", list(range(7)), index=0, key="f_calc_srm")
                                    with col_c4:
                                        sr_females = st.selectbox("Sr. Female", list(range(7)), index=0, key="f_calc_srf")
                                    with col_c5:
                                        quota = st.selectbox("Quota", ["General", "Tatkal"], index=0, key="f_calc_quota")
                                        
                                    q_suffix = "1" if quota == "Tatkal" else "0"
                                    
                                    # Fetch dynamic fare
                                    with st.spinner("Calculating fare..."):
                                        fare_data = fetch_train_fare(train_no, src_code, dest_code)
                                        
                                    if fare_data and "fares" in fare_data:
                                        distance = fare_data.get("distance", 0)
                                        fares = fare_data.get("fares", {})
                                        
                                        st.markdown(f"""
<div style="font-size: 0.88rem; color: #94a3b8; font-weight: 500; margin-bottom: 14px;">
    Distance: <b style="color: #cbd5e1;">{distance} Kms</b> &nbsp;|&nbsp; Quota: <b style="color: #cbd5e1;">{quota}</b>
</div>
""", unsafe_allow_html=True)
                                        
                                        # Render pricing cards in columns
                                        cls_keys = [c for c in classes if c in fares]
                                        if not cls_keys:
                                            cls_keys = list(fares.keys())
                                            
                                        cls_cols = st.columns(max(1, len(cls_keys)))
                                        for c_idx, cls in enumerate(cls_keys):
                                            weights = fares[cls]
                                            price = (
                                                adults * weights["ad" + q_suffix] +
                                                children * weights["ch" + q_suffix] +
                                                sr_males * weights["srm" + q_suffix] +
                                                sr_females * weights["srf" + q_suffix]
                                            )
                                            with cls_cols[c_idx]:
                                                st.markdown(f"""
<div style="background: rgba(30, 41, 59, 0.4); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 14px 10px; text-align: center; box-shadow: 0 4px 20px rgba(0,0,0,0.15);">
    <div style="font-size: 1.05rem; font-weight: 700; color: #a5b4fc; margin-bottom: 2px;">{cls}</div>
    <div style="font-size: 1.35rem; font-weight: 800; color: #f8fafc; font-family: 'Outfit', sans-serif;">₹ {price}</div>
</div>
""", unsafe_allow_html=True)
                                    else:
                                        st.error("Could not calculate fare for the selected stations.")

                            st.write("")
                            # 5. Timetable Schedule Table
                            table_rows_html = ""
                            for idx, stop in enumerate(stops, 1):
                                s_no = stop.get("stop_number", "")
                                code = stop.get("station_code", "")
                                name = stop.get("station_name", "")
                                dist = stop.get("distance", "")
                                plat = stop.get("platform", "")
                                arr = stop.get("arrival_time", "")
                                dep = stop.get("departure_time", "")
                                
                                is_highlight = (code == src_code or code == dest_code)
                                row_bg = "rgba(99, 102, 241, 0.15)" if is_highlight else ("rgba(255, 255, 255, 0.01)" if idx % 2 == 0 else "transparent")
                                border_color = "rgba(99, 102, 241, 0.4)" if is_highlight else "rgba(255, 255, 255, 0.04)"
                                text_weight = "700" if is_highlight else "500"
                                code_color = "#c7d2fe" if is_highlight else "#818cf8"
                                name_color = "#ffffff" if is_highlight else "#cbd5e1"
                                
                                plat_display = plat if plat else "-"
                                
                                table_rows_html += f"""<tr style="background-color: {row_bg}; border-bottom: 1px solid {border_color}; font-weight: {text_weight}; transition: background-color 0.2s;">
<td style="padding: 12px 10px; text-align: left; color: #64748b; font-size: 0.85rem; font-weight: 500;">{s_no}</td>
<td style="padding: 12px 10px; text-align: left; font-weight: 700; color: {code_color}; font-size: 0.9rem; letter-spacing: 0.5px;">{code}</td>
<td style="padding: 12px 10px; text-align: left; color: {name_color}; font-size: 0.9rem;">{name}</td>
<td style="padding: 12px 10px; text-align: center; color: #94a3b8; font-size: 0.88rem;">{dist}</td>
<td style="padding: 12px 10px; text-align: center; color: #94a3b8; font-size: 0.88rem;">{plat_display}</td>
<td style="padding: 12px 10px; text-align: center; color: #10b981; font-size: 0.88rem; font-weight: 600;">{arr}</td>
<td style="padding: 12px 10px; text-align: center; color: #ec4899; font-size: 0.88rem; font-weight: 600;">{dep}</td>
</tr>"""

                            st.markdown(f"""
<div style="font-size: 0.9rem; font-weight: 600; color: #94a3b8; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">Train Timetable & Route Map:</div>
<div style="overflow-x: auto; background: rgba(30, 41, 59, 0.15); border: 1px solid rgba(255, 255, 255, 0.04); border-radius: 16px; padding: 8px; box-shadow: 0 4px 30px rgba(0, 0, 0, 0.15);">
<table style="width: 100%; border-collapse: collapse; font-family: 'Outfit', sans-serif;">
<thead>
<tr style="background-color: rgba(255, 255, 255, 0.02); border-bottom: 2px solid rgba(255, 255, 255, 0.06);">
<th style="padding: 12px 10px; text-align: left; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">#</th>
<th style="padding: 12px 10px; text-align: left; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">Code</th>
<th style="padding: 12px 10px; text-align: left; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">Station Name</th>
<th style="padding: 12px 10px; text-align: center; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">Distance</th>
<th style="padding: 12px 10px; text-align: center; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">Platform</th>
<th style="padding: 12px 10px; text-align: center; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">Arr. Time</th>
<th style="padding: 12px 10px; text-align: center; color: #94a3b8; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px;">Dep. Time</th>
</tr>
</thead>
<tbody>
{table_rows_html}
</tbody>
</table>
</div>
""", unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Error fetching detailed schedule: {str(e)}")
