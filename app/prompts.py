from __future__ import annotations


RAG_SYSTEM_PROMPT = (
    "You are a local knowledge-base assistant. Answer only from the provided "
    "context. If the context does not contain enough information, say that the "
    "local knowledge base does not contain the answer."
)

FALLBACK_SYSTEM_PROMPT = (
    "You are a general assistant. The response is not from the local knowledge "
    "base. Be clear about that before answering."
)


def build_rag_user_prompt(*, question: str, context: str) -> str:
    return "\n\n".join(
        [
            "Context:",
            context,
            "Question:",
            question,
            "Answer with concise citations such as [1] when the context supports it.",
        ]
    )


def build_fallback_user_prompt(*, question: str) -> str:
    return "\n\n".join(
        [
            "This answer is not from the local knowledge base.",
            "Question:",
            question,
        ]
    )
