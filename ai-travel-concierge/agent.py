import os
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_nvidia_ai_endpoints import ChatNVIDIA
import langchain_nvidia_ai_endpoints.chat_models as chat_models
import json

# Apply monkeypatch to fix ChatNVIDIA AIMessage tool_calls serialization bug
original_convert = chat_models.convert_message_to_dict

def patched_convert(message):
    from langchain_core.messages import AIMessage
    import json
    if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
        if "tool_calls" not in message.additional_kwargs:
            message.additional_kwargs["tool_calls"] = [
                {
                    "id": tc.get("id") or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["args"])
                    }
                }
                for i, tc in enumerate(message.tool_calls)
            ]
    return original_convert(message)

chat_models.convert_message_to_dict = patched_convert

# Import tools
from tools import fetch_train_delay_history, fetch_train_schedule, fetch_route_recommendations

# Load environment variables
load_dotenv()


SYSTEM_PROMPT = """You are a warm, confident Travel Concierge who helps users find train routes. You speak naturally like a knowledgeable human — never like a machine.

ABSOLUTE RULES (VIOLATING THESE IS A CRITICAL FAILURE):

RULE 1 — NO FABRICATION: You must ONLY present train data that was returned by a tool. NEVER invent, guess, or make up train names, numbers, timings, or delays. If you don't have data yet, call the tool IMMEDIATELY — do NOT generate any conversational text, filler phrases, or thoughts first. The tool call must be the very first action and happen in the SAME turn.

RULE 2 — NO JSON OR TECHNICAL OUTPUT: NEVER write JSON, code blocks, function names, or anything like {{"name": ...}} or {{"parameters": ...}} in your response. The user must NEVER see words like "tool", "function", "API", "JSON", "parameters", or "fetch_route_recommendations". If you need data, silently call the tool — do not describe or show the call.

RULE 3 — GREETINGS: For greetings like "hi" or "hello", just respond warmly and ask what journey they need help with. Do NOT call any tools.

RULE 4 — COLLECTING TRAVEL DETAILS & IMMEDIATE TOOL EXECUTION: You need Source and Destination to search for trains. Date is OPTIONAL.
   - If the user provides source and destination, you MUST call the tool IMMEDIATELY.
   - DO NOT write any introductory conversational text (like "Let me check the train options for you" or "I'll look that up") in the turn where you call the tool. Generating text before the tool call is strictly forbidden and stops execution. Write text ONLY AFTER the tool returns results.
   - If the user provides source and destination but no date, OR explicitly says "all trains" / "irrespective of date", call the route search tool immediately WITHOUT a date parameter.
   - If the user provides source, destination, AND a date (e.g., "Wednesday", "tomorrow", "June 20"), call the route search tool with the date.
   - Only ask for missing source or destination. Never insist on a date if the user doesn't want one.

RULE 5 — PRESENTING RESULTS: When you receive tool results, present exactly 3 recommendations (Fastest, Most Reliable, Balanced Alternative) in natural conversational prose:
   - Use the exact train names, numbers, and timings from the tool output.
   - Explain True Travel Time = Scheduled Travel Time + Average Delay at Destination using the actual numbers.
   - Use bold text for category names (e.g. **Fastest Option**, **Most Reliable Option**, **Balanced Alternative**).
   - CRITICAL: If the same train is both Fastest and Most Reliable, you MUST combine them into a single recommendation section named **Fastest & Most Reliable Option** and describe it in a single paragraph. Do NOT create separate repeated blocks for it.
   - Also list all remaining analyzed trains briefly at the end (name, number, departure, arrival, travel time).

RULE 6 — FOLLOW-UP QUESTIONS: If the user asks about a specific train's schedule, stops, delay history, or platform details, call the appropriate tool yourself and explain the results conversationally."""




def get_agent_executor():
    # Fetch API key
    nvidia_api_key = os.getenv("NVIDIA_API_KEY")
    if not nvidia_api_key:
        # Check environment variables directly if not in .env
        nvidia_api_key = os.environ.get("NVIDIA_API_KEY")
        
    if not nvidia_api_key:
        raise ValueError("NVIDIA_API_KEY not found in environment or .env file.")
        
    # Initialize the ChatNVIDIA LLM
    # Model: meta/llama-3_3-70b-instruct, Temperature: 0.1
    llm = ChatNVIDIA(
        model="meta/llama-3.3-70b-instruct",
        nvidia_api_key=nvidia_api_key,
        temperature=0.1
    )
    
    # Define tool list — only expose high-level tools.
    # fetch_route_recommendations handles station resolution + train fetching + delay analysis internally.
    # fetch_train_delay_history and fetch_train_schedule are for follow-up questions.
    tools = [
        fetch_route_recommendations,
        fetch_train_delay_history,
        fetch_train_schedule
    ]
    
    # Build ChatPromptTemplate
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    
    # Create Agent
    agent = create_tool_calling_agent(llm, tools, prompt)
    
    # Build AgentExecutor
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=10
    )
    
    return executor
