# ai/agents/agent.py
#
# LangChain agent — connects to the FastMCP server and uses Ollama as the LLM.
#
# The agent exposes a simple CLI loop where the user can ask natural language
# questions about the network. The LLM selects the appropriate MCP tool,
# interprets the result, and returns a human-readable answer.
#
# Prerequisites:
#   - MCP server running: python ai/mcp_server.py
#   - Ollama running with llama3.1:8b pulled
#
# Run:
#   python ai/agents/agent.py

from __future__ import annotations

import asyncio
from langchain_ollama import ChatOllama
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent


MCP_SERVER_URL = "http://127.0.0.1:8001/mcp"
OLLAMA_MODEL = "llama3.1:8b"

SYSTEM_PROMPT = """You are a network operations assistant for an enterprise network automation platform.

You have access to tools that query live network state. Use them to answer questions accurately.

Guidelines:
- Always use a tool to get current data before answering state questions
- Be concise and technical in your responses
- If a device is not reachable, report it clearly
- Never guess network state — always query it
"""


async def run_agent():
    client = MultiServerMCPClient(
        {
            "network": {
                "url": MCP_SERVER_URL,
                "transport": "streamable_http",
            }
        }
    )

    tools = await client.get_tools()
    llm = ChatOllama(model=OLLAMA_MODEL, temperature=0)
    agent = create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)

    print("\nNetwork Assistant ready. Type 'exit' to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if user_input.lower() in ("exit", "quit"):
            print("Exiting.")
            break

        if not user_input:
            continue

        response = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_input}]}
        )

        answer = response["messages"][-1].content
        print(f"\nAssistant: {answer}\n")


if __name__ == "__main__":
    asyncio.run(run_agent())