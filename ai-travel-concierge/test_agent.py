import os
import sys
from dotenv import load_dotenv

# Load env variables
load_dotenv()

from agent import get_agent_executor

user_input = "i want to travel from duvvada to tirupathi on friday after 6pm and reach on staurday by 8 am saturday suggest me the trains..."

print("Initializing agent executor...")
try:
    agent_executor = get_agent_executor()
except Exception as e:
    print(f"Failed to initialize agent executor: {str(e)}")
    sys.exit(1)

print(f"Running agent with input: {user_input}")
try:
    result = agent_executor.invoke({
        "input": user_input,
        "chat_history": []
    })
    
    print("\n--- AGENT RESULT ---")
    print(result.get("output"))
    print("--------------------")
    
except Exception as e:
    print(f"Error executing agent: {str(e)}")
    import traceback
    traceback.print_exc()
