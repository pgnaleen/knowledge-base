"""PropertyAgent: wraps KB-Pipeline with Claude for conversational property advice."""

import anthropic
import httpx

from client import Chunk, KBPipelineClient

SYSTEM = """You are a Singapore property expert. Answer questions using only the
provided context from official Singapore government sources (HDB, IRAS, URA, MAS, CPF).
If the context doesn't contain enough information, say so clearly.
Always mention which source your answer comes from."""


class PropertyAgent:
    """Conversational agent for Singapore property questions."""

    def __init__(self, kb_url: str, anthropic_api_key: str) -> None:
        self._kb = KBPipelineClient(kb_url)
        self._claude = anthropic.Anthropic(api_key=anthropic_api_key)
        self._history: list[dict] = []

    def chat(self, question: str) -> str:
        """Answer a property question, maintaining conversation history.

        Args:
            question: User's question

        Returns:
            Claude's answer grounded in KB-Pipeline context
        """
        try:
            chunks = self._kb.retrieve(question)
        except httpx.HTTPError as exc:
            return f"Could not connect to KB-Pipeline: {exc}. Is it running?"

        if not chunks:
            return "I couldn't find relevant information in the knowledge base for that question."

        context = self._format_context(chunks)
        user_message = f"{context}\n\nQuestion: {question}"

        self._history.append({"role": "user", "content": user_message})
        response = self._claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM,
            messages=self._history,
        )
        answer = response.content[0].text
        self._history.append({"role": "assistant", "content": answer})
        return answer

    def reset(self) -> None:
        """Clear conversation history."""
        self._history.clear()

    @staticmethod
    def _format_context(chunks: list[Chunk]) -> str:
        """Format retrieved chunks as context string."""
        lines = ["Context from official sources:"]
        for i, c in enumerate(chunks, 1):
            lines.append(f"\n[{i}] {c.title} ({c.source_url})\n{c.text}")
        return "\n".join(lines)
