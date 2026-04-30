"""LangGraph graph definition with stub node implementations."""
from langgraph.graph import END, StateGraph

from state import AgentState


def parse_prompt(state: AgentState) -> AgentState:
    """Parse and normalise the incoming prompt."""
    return state


def resolve_domain_and_params(state: AgentState) -> AgentState:
    """Resolve domain slug and query parameters from the prompt."""
    return state


def _route_after_resolve(state: AgentState) -> str:
    """Route to clarification or main pipeline based on confidence."""
    if state.get("clarification_message"):
        return "return_clarification"
    return "call_news_retrieval"


def call_news_retrieval(state: AgentState) -> AgentState:
    """Fetch articles from the news-retrieval service."""
    return state


def categorise(state: AgentState) -> AgentState:
    """Assign vertical categories to each article."""
    return state


def summarise(state: AgentState) -> AgentState:
    """Summarise articles per category and produce a roll-up summary."""
    return state


def return_result(state: AgentState) -> AgentState:
    """Package the final result for the caller."""
    return state


def return_clarification(state: AgentState) -> AgentState:
    """Return a clarification request to the caller."""
    return state


builder: StateGraph = StateGraph(AgentState)

builder.add_node("parse_prompt", parse_prompt)
builder.add_node("resolve_domain_and_params", resolve_domain_and_params)
builder.add_node("call_news_retrieval", call_news_retrieval)
builder.add_node("categorise", categorise)
builder.add_node("summarise", summarise)
builder.add_node("return_result", return_result)
builder.add_node("return_clarification", return_clarification)

builder.set_entry_point("parse_prompt")
builder.add_edge("parse_prompt", "resolve_domain_and_params")
builder.add_conditional_edges(
    "resolve_domain_and_params",
    _route_after_resolve,
    {
        "call_news_retrieval": "call_news_retrieval",
        "return_clarification": "return_clarification",
    },
)
builder.add_edge("call_news_retrieval", "categorise")
builder.add_edge("categorise", "summarise")
builder.add_edge("summarise", "return_result")
builder.add_edge("return_result", END)
builder.add_edge("return_clarification", END)

graph = builder.compile()
