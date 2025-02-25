import streamlit as st
import sqlite3
from main import process_message, init_db

# Initialize the database
init_db()

# Page configuration
st.set_page_config(page_title="Tool Agent Demo", layout="wide")
st.title("Tool Agent Demo")

# Create tabs
tab1, tab2, tab3, tab4 = st.tabs(["Chat", "List Items", "Emails", "Tool Logs"])

# Initialize chat history at the start of the script
if "messages" not in st.session_state:
    st.session_state["messages"] = []  # Use dict notation instead of attribute

# Add message history management
def clear_chat_history():
    st.session_state.messages = []

# Chat Tab
with tab1:
    st.header("Chat with Agent")
    
    # Display chat messages
    for message in st.session_state.messages:
        if message["role"] == "user":
            st.text_area("User:", message["content"], height=100, disabled=True)
        else:
            st.text_area("Assistant:", message["content"], height=100, disabled=True)

    # Chat input
    prompt = st.text_input("What would you like to do?")
    
    # Send button
    if st.button("Send") and prompt:
        # Add to chat history
        st.session_state["messages"].append({"role": "user", "content": prompt})
        
        # Convert session messages to BaseMessage format for the model
        history = []
        for msg in st.session_state.messages[:-1]:  # Exclude the last message as we'll add it separately
            role = "human" if msg["role"] == "user" else "ai"
            history.append((role, msg["content"]))
        
        # Get AI response
        response = process_message(prompt, history=history)
        st.session_state["messages"].append({"role": "assistant", "content": response.content})
        
        # Rerun to update display
        st.experimental_rerun()

    # Clear chat button
    if st.button("Clear Chat"):
        st.session_state.messages = []
        st.experimental_rerun()

# List Items Tab
with tab2:
    st.header("List Items")
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('SELECT id, item, created_at FROM list_items ORDER BY created_at DESC')
    items = c.fetchall()
    
    if items:
        st.table({
            'ID': [item[0] for item in items],
            'Item': [item[1] for item in items],
            'Created At': [item[2] for item in items]
        })
    else:
        st.info("No items in the list yet.")

# Emails Tab
with tab3:
    st.header("Queued Emails")
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('''SELECT id, recipient, subject, content, status, created_at 
                 FROM emails ORDER BY created_at DESC''')
    emails = c.fetchall()
    
    if emails:
        st.table({
            'ID': [email[0] for email in emails],
            'Recipient': [email[1] for email in emails],
            'Subject': [email[2] for email in emails],
            'Content': [email[3] for email in emails],
            'Status': [email[4] for email in emails],
            'Created At': [email[5] for email in emails]
        })
    else:
        st.info("No emails queued.")

# Tool Logs Tab
with tab4:
    st.header("Tool Execution Logs")
    
    # Add filters
    col1, col2 = st.columns(2)
    with col1:
        days = st.number_input("Show logs from last N days", min_value=1, value=7)
    with col2:
        tool_filter = st.text_input("Filter by tool name")
    
    # Add pagination
    items_per_page = st.selectbox("Items per page", [10, 25, 50, 100], index=1)
    page = st.number_input("Page", min_value=1, value=1)
    
    # Query with filters
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    query = '''SELECT tool_name, input_params, output_result, execution_time, timestamp 
               FROM tool_logs 
               WHERE timestamp >= datetime('now', ?) '''
    params = [f'-{days} days']
    
    if tool_filter:
        query += ' AND tool_name LIKE ?'
        params.append(f'%{tool_filter}%')
    
    query += ' ORDER BY timestamp DESC'
    
    # Modify query
    query += f' LIMIT {items_per_page} OFFSET {(page-1) * items_per_page}'
    
    c.execute(query, params)
    logs = c.fetchall()
    
    if logs:
        st.table({
            'Tool': [log[0] for log in logs],
            'Input': [log[1] for log in logs],
            'Output': [log[2] for log in logs],
            'Execution Time (s)': [f"{log[3]:.3f}" for log in logs],
            'Timestamp': [log[4] for log in logs]
        })
    else:
        st.info("No logs found matching the criteria.")

conn.close() 