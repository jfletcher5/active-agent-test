import os
import sqlite3
import time
from datetime import datetime
from typing import Dict, List
import streamlit as st
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from tenacity import retry, stop_after_attempt, wait_exponential

# Database setup
def init_db():
    """Initialize SQLite database with required tables"""
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    
    # Create list items table
    c.execute('''CREATE TABLE IF NOT EXISTS list_items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  item TEXT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create emails table
    c.execute('''CREATE TABLE IF NOT EXISTS emails
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  recipient TEXT NOT NULL,
                  subject TEXT NOT NULL,
                  content TEXT NOT NULL,
                  status TEXT DEFAULT 'pending',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create tool logs table
    c.execute('''CREATE TABLE IF NOT EXISTS tool_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tool_name TEXT NOT NULL,
                  input_params TEXT,
                  output_result TEXT,
                  execution_time FLOAT,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()

# Tool logging decorator
def log_tool_execution(func):
    """Decorator to log tool execution details"""
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            # Log to database
            conn = sqlite3.connect('app.db')
            c = conn.cursor()
            c.execute('''INSERT INTO tool_logs 
                        (tool_name, input_params, output_result, execution_time)
                        VALUES (?, ?, ?, ?)''',
                     (func.__name__, str(args), str(result), execution_time))
            conn.commit()
            conn.close()
            
            return result
        except Exception as e:
            # Log error if tool fails
            conn = sqlite3.connect('app.db')
            c = conn.cursor()
            c.execute('''INSERT INTO tool_logs 
                        (tool_name, input_params, output_result, execution_time)
                        VALUES (?, ?, ?, ?)''',
                     (func.__name__, str(args), f"ERROR: {str(e)}", time.time() - start_time))
            conn.commit()
            conn.close()
            raise e
    return wrapper

# Tool definitions
@tool
def get_weather(location: str):
    """Get the current weather for a location."""
    if location.lower() in ["sf", "san francisco"]:
        return "It's 60 degrees and foggy."
    elif location.lower() in ["bal", "baltimore"]:
        return "It's 50 degrees and rainy."
    else:
        return "It's 90 degrees and sunny."

@tool
def get_coolest_cities():
    """Get a list of coolest cities"""
    return "nyc, sf"

@tool
def add_list_item(item: str, state: MessagesState):
    """Add an item to the list and persist to database"""
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('INSERT INTO list_items (item) VALUES (?)', (item,))
    conn.commit()
    
    # Get all current items
    c.execute('SELECT item FROM list_items')
    items = [row[0] for row in c.fetchall()]
    conn.close()
    
    if "list" not in state:
        state["list"] = []
    state["list"] = items
    return f"Added {item} to the list. Current list: {', '.join(items)}"

@tool
def get_list_items(state: MessagesState):
    """Get all items from the database"""
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('SELECT item FROM list_items')
    items = [row[0] for row in c.fetchall()]
    conn.close()
    
    if not items:
        return "The list is empty"
    return f"Current list items: {', '.join(items)}"

@tool
def send_email(recipient: str, subject: str, content: str):
    """Queue an email to be sent"""
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('''INSERT INTO emails (recipient, subject, content)
                 VALUES (?, ?, ?)''', (recipient, subject, content))
    conn.commit()
    conn.close()
    return f"Email queued for {recipient}"

@tool
def all_tools():
    """Lists all available tools and their descriptions"""
    tool_descriptions = [
        {"name": "get_weather", "description": "Get the current weather for a location"},
        {"name": "get_coolest_cities", "description": "Get a list of coolest cities"},
        {"name": "add_list_item", "description": "Add an item to the persistent list"},
        {"name": "get_list_items", "description": "Get all items from the list"},
        {"name": "send_email", "description": "Queue an email to be sent"},
        {"name": "all_tools", "description": "Lists all available tools and their descriptions"},
    ]
    return "\n".join([f"- {t['name']}: {t['description']}" for t in tool_descriptions])

# LangGraph setup
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_model_with_retry(model, messages):
    """Call model with retry logic for rate limits"""
    return model.invoke(messages)

def setup_graph():
    """Set up and return the LangGraph workflow"""
    tools = [get_weather, get_coolest_cities, all_tools, add_list_item, get_list_items, send_email]
    tool_node = ToolNode(tools)
    
    model = ChatAnthropic(
        model="claude-3-5-sonnet-20241022",
        temperature=0
    ).bind_tools(tools)
    
    def should_continue(state: MessagesState):
        """Determine if we should continue to tools or end"""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools"
        return END
    
    def call_model(state: MessagesState):
        """Process messages through the model"""
        messages = state["messages"]
        response = call_model_with_retry(model, messages)
        return {"messages": [response]}
    
    # Setup workflow graph
    workflow = StateGraph(MessagesState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, ["tools", END])
    workflow.add_edge("tools", "agent")
    
    return workflow.compile()

# Initialize everything
init_db()
app = setup_graph()

def process_message(message: str, history: List[BaseMessage] = None) -> AIMessage:
    """Process a single message through the workflow"""
    # Initialize messages list with history if provided
    messages = []
    if history:
        messages.extend(history)
    
    # Add the new human message
    messages.append(("human", message))
    
    results = []
    for chunk in app.stream(
        {"messages": messages},
        stream_mode="values"
    ):
        results.append(chunk["messages"][-1])
    
    last_message = results[-1]
    
    # If the model is asking for more information, return that message
    if isinstance(last_message.content, str) and any(phrase in last_message.content.lower() for phrase in [
        "could you please provide", "could you clarify", "i need more information",
        "can you specify", "please provide", "could you tell me"
    ]):
        return last_message
        
    return last_message

