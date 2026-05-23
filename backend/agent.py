from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from models import DocumentRecord
from retrieval import hybrid_search
from schemas import SourceDocument
from services import generate_answer, generate_document_summary_and_topics, get_document_overview

Intent = Literal["greeting", "overview", "code", "search"]


class AgentState(TypedDict, total=False):
    db: Session
    query: str
    document_ids: list[str]
    documents_by_id: dict[str, DocumentRecord]
    history: list[tuple[str, str]]
    intent: Intent
    context: list[str]
    sources: list[SourceDocument]
    used_tools: list[str]
    answer: str


GREETING_TERMS = {"hi", "hello", "hey", "yo", "hii", "help"}
OVERVIEW_TERMS = (
    "what is in",
    "what's in",
    "what is this doc",
    "what is this document",
    "what are the main topics",
    "important topic",
    "important topics",
    "main topic",
    "main topics",
    "summarize",
    "summary",
    "overview",
    "context of",
    "what the book say",
    "what does the book say",
)
CODE_TERMS = (
    "code",
    "sample",
    "example",
    "implementation",
    "snippet",
    "python",
    "javascript",
)


def classify_intent(query: str) -> Intent:
    normalized = query.lower().strip()
    if normalized in GREETING_TERMS:
        return "greeting"
    if any(term in normalized for term in CODE_TERMS):
        return "code"
    if any(term in normalized for term in OVERVIEW_TERMS):
        return "overview"
    return "search"


def route_intent(state: AgentState) -> AgentState:
    return {
        **state,
        "intent": classify_intent(state["query"]),
        "context": state.get("context", []),
        "sources": state.get("sources", []),
        "used_tools": state.get("used_tools", []),
    }


def greeting_node(state: AgentState) -> AgentState:
    return {
        **state,
        "answer": (
            "Hi. Ask me for a book overview, important topics, a study plan, "
            "specific Q&A, or code examples from the uploaded documents."
        ),
        "sources": [],
        "used_tools": state.get("used_tools", []) + ["greeting"],
    }


def overview_node(state: AgentState) -> AgentState:
    db = state["db"]
    context = list(state.get("context", []))
    sources = list(state.get("sources", []))

    for doc_id in state["document_ids"]:
        document = state["documents_by_id"][doc_id]
        summary = document.summary
        topic_map = document.topic_map or {}
        if should_refresh_summary(summary, topic_map) and document.file_path:
            overview = get_document_overview(document.file_path, document.filename)
            summary, topic_map = generate_document_summary_and_topics(document.filename, overview)
            document.summary = summary or overview[:1200]
            document.topic_map = topic_map
            db.commit()

        if summary:
            topics = topic_map.get("topics", []) if isinstance(topic_map, dict) else []
            topic_lines = "\n".join(
                f"- {topic.get('name', 'Topic')}: {topic.get('description', '')}"
                for topic in topics
                if isinstance(topic, dict)
            )
            context.append(
                f"Document: {document.filename}\n"
                f"Summary:\n{summary}\n"
                f"Key topics:\n{topic_lines or 'No topic map available.'}"
            )
            sources.append(
                SourceDocument(
                    document_id=doc_id,
                    filename=document.filename,
                    chunk_text=summary[:500] + "..." if len(summary) > 500 else summary,
                    page=None,
                )
            )

    return {
        **state,
        "context": context,
        "sources": sources,
        "used_tools": state.get("used_tools", []) + ["document_overview"],
    }


def should_refresh_summary(summary: str | None, topic_map: dict) -> bool:
    if not summary:
        return True
    if summary.strip().startswith("Page "):
        return True
    topics = topic_map.get("topics", []) if isinstance(topic_map, dict) else []
    return not topics


def retrieval_node(state: AgentState) -> AgentState:
    db = state["db"]
    context = list(state.get("context", []))
    sources = list(state.get("sources", []))

    results = hybrid_search(
        db,
        document_ids=state["document_ids"],
        query=state["query"],
    )
    context.extend([result.text for result in results])
    for result in results:
        sources.append(
            SourceDocument(
                document_id=result.document_id,
                filename=result.filename,
                chunk_text=result.text[:500] + "..." if len(result.text) > 500 else result.text,
                page=result.page_start,
            )
        )

    return {
        **state,
        "context": context,
        "sources": sources,
        "used_tools": state.get("used_tools", []) + ["hybrid_search"],
    }


def code_node(state: AgentState) -> AgentState:
    code_query = (
        f"code example implementation snippet practical sample for: {state['query']}"
    )
    next_state = {**state, "query": code_query}
    retrieved = retrieval_node(next_state)
    return {
        **retrieved,
        "query": state["query"],
        "used_tools": state.get("used_tools", []) + ["code_example_search", "hybrid_search"],
    }


def synthesize_node(state: AgentState) -> AgentState:
    if not state.get("context"):
        return {
            **state,
            "answer": (
                "I could not find enough relevant context in the uploaded documents. "
                "Try asking about a specific chapter, concept, or document."
            ),
        }

    query = state["query"]
    if state.get("intent") == "overview":
        query = (
            f"{query}\n\nWrite a detailed overview separated by document. "
            "For each document include: what the book is about, major themes, "
            "who it is useful for, and what a reader should learn. Use only the "
            "document summaries and topic maps provided."
        )
    if state.get("intent") == "code":
        query = (
            f"{query}\n\nExplain the relevant book concept first, then provide an "
            "original runnable code example. Do not reproduce long copyrighted code."
        )

    answer = generate_answer(query, state["context"], state.get("history", []))
    if not answer.strip():
        answer = build_fallback_answer(state)
    return {**state, "answer": answer}


def build_fallback_answer(state: AgentState) -> str:
    if state.get("intent") != "overview":
        return (
            "I found relevant context, but the model returned an empty answer. "
            "Try asking again with a more specific question."
        )

    sections = []
    for doc_id in state["document_ids"]:
        document = state["documents_by_id"][doc_id]
        topic_map = document.topic_map or {}
        topics = topic_map.get("topics", []) if isinstance(topic_map, dict) else []
        topic_text = "\n".join(
            f"- {topic.get('name', 'Topic')}: {topic.get('description', '')}"
            for topic in topics
            if isinstance(topic, dict)
        )
        sections.append(
            f"## {document.filename}\n\n"
            f"{truncate(document.summary or 'No stored summary is available yet.', 1400)}\n\n"
            f"Key topics:\n{topic_text or '- No topic map is available yet.'}"
        )
    return "\n\n".join(sections)


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0] + "..."


def citation_guard_node(state: AgentState) -> AgentState:
    if state.get("intent") == "greeting":
        return state
    if state.get("sources"):
        return state
    return {
        **state,
        "answer": (
            f"{state.get('answer', '')}\n\nNo citations were found for this answer, "
            "so treat it as a low-confidence response."
        ).strip(),
    }


def route_after_intent(state: AgentState) -> str:
    intent = state["intent"]
    if intent == "greeting":
        return "greeting"
    if intent == "overview":
        return "overview"
    if intent == "code":
        return "code"
    return "retrieve"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("route", route_intent)
    graph.add_node("greeting", greeting_node)
    graph.add_node("overview", overview_node)
    graph.add_node("retrieve", retrieval_node)
    graph.add_node("code", code_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("citation_guard", citation_guard_node)

    graph.set_entry_point("route")
    graph.add_conditional_edges(
        "route",
        route_after_intent,
        {
            "greeting": "greeting",
            "overview": "overview",
            "code": "code",
            "retrieve": "retrieve",
        },
    )
    graph.add_edge("greeting", "citation_guard")
    graph.add_edge("overview", "synthesize")
    graph.add_edge("retrieve", "synthesize")
    graph.add_edge("code", "synthesize")
    graph.add_edge("synthesize", "citation_guard")
    graph.add_edge("citation_guard", END)
    return graph.compile()


study_graph = build_graph()


def run_study_agent(
    *,
    db: Session,
    query: str,
    document_ids: list[str],
    documents_by_id: dict[str, DocumentRecord],
    history: list[tuple[str, str]],
) -> dict[str, Any]:
    return study_graph.invoke(
        {
            "db": db,
            "query": query,
            "document_ids": document_ids,
            "documents_by_id": documents_by_id,
            "history": history,
            "context": [],
            "sources": [],
            "used_tools": [],
        }
    )
