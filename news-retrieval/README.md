# Agent Template

This is a template for building [A2A (Agent-to-Agent)](https://github.com/ashishsharma/nasiko) compatible agents.

It implements the A2A JSON-RPC 2.0 protocol using FastAPI, giving you complete control over your stack.

## Frameworks
- **Server**: FastAPI
- **Agent Logic**: LangChain (Pre-configured)

## Structure

- `src/main.py`: **Protocol Implementation**. A FastAPI server that handles the A2A JSON-RPC `message/send` requests.
- `src/models.py`: **Data Models**. A2A protocol Pydantic models (Message, Task, etc.).
- `src/tools.py`: **Tools Definition**. Define your agent's tools here. **Edit this file.**
- `src/agent.py`: **Core Logic**. Configures the LangChain agent and tools. **Edit this file.**
- `AgentCard.json`: Agent metadata (auto-generated).
- `Dockerfile`: Standard Python Dockerfile.

## How to Use

1.  **Copy this directory** to create a new agent.
2.  **Edit `src/tools.py`**:
    *   Define your tools using the `@tool` decorator.
3.  **Edit `src/agent.py`**:
    *   Customize the LangChain `prompt` and `llm`.
    *   Import your tools from `src.tools` and register them.
4.  **Build and Run**:
    ```bash
    docker build -t my-agent .
    docker run -p 8000:8000 -e OPENAI_API_KEY=your_key my-agent
    ```

## Protocol Details

This template implements:
- `POST /`: JSON-RPC 2.0 endpoint.
  - Method: `message/send`
  - Params: A2A Message format

