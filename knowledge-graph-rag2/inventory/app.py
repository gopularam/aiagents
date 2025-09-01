import streamlit as st
import sqlite3
import pandas as pd
import os
import json
import matplotlib.pyplot as plt
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate

# -----------------------------
# DB Setup
# -----------------------------
DB_FILE = "inventory.db"
CSV_FILE = "products.csv"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            stock INTEGER,
            reorder_point INTEGER,
            price REAL,
            supplier TEXT
        )
    """)
    conn.commit()
    return conn

def load_csv_to_db(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM products")
    count = cursor.fetchone()[0]
    if count == 0:
        df = pd.read_csv(CSV_FILE)
        for _, row in df.iterrows():
            cursor.execute("""
                INSERT INTO products (name, stock, reorder_point, price, supplier)
                VALUES (?, ?, ?, ?, ?)
            """, (row["name"], row["stock"], row["reorder_point"], row["price"], row["supplier"]))
        conn.commit()

# -----------------------------
# AI Setup
# -----------------------------


OPENAI_API_KEY ="sk-proj"

# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


llm = ChatOpenAI(api_key=OPENAI_API_KEY, model="gpt-4o-mini", temperature=0)

prompt = ChatPromptTemplate.from_template("""
You are an Inventory Assistant connected to a database.
User query: {query}

Classify into intent:
- "list_products"
- "low_stock"
- "suppliers"
- "product_details"
- "stock_chart"

If intent=product_details, also extract product name.

Return JSON ONLY:
{{
  "intent": "...",
  "product_name": "..." (if applicable)
}}
""")

def interpret_query(user_query):
    response = llm.invoke(prompt.format(query=user_query))
    try:
        return json.loads(response.content)
    except:
        return {"intent": "unknown"}

# -----------------------------
# Query DB + Visualization
# -----------------------------
def handle_intent(intent_data, conn):
    intent = intent_data.get("intent")
    product_name = intent_data.get("product_name")
    cursor = conn.cursor()

    if intent == "list_products":
        df = pd.read_sql("SELECT name, stock FROM products", conn)
        return f"Found {len(df)} products:\n" + ", ".join(df["name"].tolist()), None

    elif intent == "low_stock":
        df = pd.read_sql("SELECT name, stock, reorder_point FROM products WHERE stock <= reorder_point", conn)
        if df.empty:
            return "All products are sufficiently stocked ✅", None

        # Plot chart
        fig, ax = plt.subplots()
        ax.bar(df["name"], df["stock"], color="red")
        ax.axhline(y=df["reorder_point"].mean(), color="gray", linestyle="--", label="Avg Reorder Point")
        ax.set_title("Low Stock Products")
        ax.set_ylabel("Stock")
        ax.legend()
        return "⚠️ Low stock products:\n" + df.to_string(index=False), fig

    elif intent == "suppliers":
        df = pd.read_sql("SELECT DISTINCT supplier FROM products", conn)
        return "Suppliers:\n" + "\n".join(df["supplier"].tolist()), None

    elif intent == "product_details" and product_name:
        df = pd.read_sql("SELECT * FROM products WHERE name LIKE ?", conn, params=(f"%{product_name}%",))
        if df.empty:
            return f"No product found matching '{product_name}'.", None
        row = df.iloc[0]
        return (
            f"📦 {row['name']}\nStock: {row['stock']}\nReorder Point: {row['reorder_point']}\n"
            f"Price: ₹{row['price']}\nSupplier: {row['supplier']}",
            None
        )

    elif intent == "stock_chart":
        df = pd.read_sql("SELECT name, stock FROM products", conn)
        fig, ax = plt.subplots()
        ax.bar(df["name"], df["stock"], color="skyblue")
        ax.set_title("Inventory Stock Levels")
        ax.set_ylabel("Stock")
        ax.set_xticklabels(df["name"], rotation=30, ha="right")
        return "📊 Current stock levels:", fig

    return "❓ Sorry, I didn't understand your request.", None

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Inventory Planner Chat", layout="centered")
st.title("📦 Inventory Planner Chatbot")

# DB Init
conn = init_db()
load_csv_to_db(conn)

# Session State
if "messages" not in st.session_state:
    st.session_state["messages"] = []

# Chat history
for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "chart" in msg and msg["chart"] is not None:
            st.pyplot(msg["chart"])

# User input
if user_query := st.chat_input("Ask about inventory..."):
    st.session_state["messages"].append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    # Process query
    intent_data = interpret_query(user_query)
    answer, chart = handle_intent(intent_data, conn)

    st.session_state["messages"].append({"role": "assistant", "content": answer, "chart": chart})
    with st.chat_message("assistant"):
        st.markdown(answer)
        if chart is not None:
            st.pyplot(chart)

# Reload button
if st.button("🔄 Reload Inventory from CSV"):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products")
    conn.commit()
    load_csv_to_db(conn)
    st.success("Inventory reloaded from CSV ✅")
