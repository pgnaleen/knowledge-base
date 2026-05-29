"""
Middleware stack for the SG Property Advisor API.

Registration order in server.py (LIFO — last added executes first):
    app.add_middleware(RequestLoggingMiddleware)     # executes 3rd
    app.add_middleware(SecurityHeadersMiddleware)    # executes 2nd
    app.add_middleware(InputSanitizationMiddleware)  # executes 1st (closest to request)
"""

import json
import re
import time
import unicodedata
import uuid
from typing import Callable

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger(__name__)

MAX_INPUT_LENGTH = 2000
CHAT_PATHS = ("/chat",)


# ── Prompt Injection Filter ───────────────────────────────────────────────────

class PromptInjectionFilter:
    """
    Detects prompt injection attempts using three layers:
      1. Regex patterns  — known injection phrases
      2. Fuzzy matching  — typo/scramble variants (Levenshtein ≤ 1)
      3. Unicode normalization — homoglyph attacks (Cyrillic lookalikes etc.)
    """

    PATTERNS = re.compile(
        r"ignore\s+(all\s+)?(previous\s+|above\s+)?instructions?"
        r"|you\s+are\s+now"
        r"|act\s+as\s+(a\s+)?"
        r"|forget\s+(everything|all|your)"
        r"|disregard\s+(all\s+)?previous"
        r"|system\s+override"
        r"|reveal\s+(the\s+)?prompt"
        r"|jailbreak"
        r"|\[SYSTEM\]"
        r"|<\|im_start\|>"
        r"|---\s*\n\s*(assistant|system)",
        re.IGNORECASE,
    )

    # High-risk words only — avoids false positives on legitimate property questions
    # e.g. "system" excluded because "What is the HDB system?" is legitimate
    FUZZY_TARGETS = ["ignore", "bypass", "override"]

    def _normalize(self, text: str) -> str:
        """Unicode normalize → collapse whitespace → collapse char repetition."""
        text = unicodedata.normalize("NFKC", text)   # maps Cyrillic/homoglyphs → Latin
        text = re.sub(r"\s+", " ", text)             # collapse all whitespace to single space
        text = re.sub(r"(.)\1{3,}", r"\1\1", text)  # "iiiignore" → "iignore"
        return text.strip()

    def _levenshtein(self, a: str, b: str) -> int:
        """Compute edit distance between two strings."""
        dp = list(range(len(b) + 1))
        for ch in a:
            prev, dp[0] = dp[0], dp[0] + 1
            for j in range(1, len(b) + 1):
                prev, dp[j] = dp[j], min(
                    dp[j] + 1,          # deletion
                    dp[j - 1] + 1,      # insertion
                    prev + (ch != b[j - 1]),  # substitution
                )
        return dp[-1]

    def _fuzzy_match(self, text: str) -> bool:
        """Detect typoglycemia/scramble variants of high-risk words."""
        words = re.findall(r"\b\w+\b", text.lower())
        for word in words:
            if len(word) < 4:
                continue
            for target in self.FUZZY_TARGETS:
                if (abs(len(word) - len(target)) <= 1
                        and self._levenshtein(word, target) <= 1):
                    return True
        return False

    def is_injection(self, text: str) -> bool:
        normalized = self._normalize(text)
        return (
            bool(self.PATTERNS.search(normalized))
            or self._fuzzy_match(normalized)
        )


_injection_filter = PromptInjectionFilter()


# ── Middleware Classes ────────────────────────────────────────────────────────

class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """
    Runs first on every incoming request — before any LLM call is made.
    Only inspects POST requests to /chat routes.

    Steps:
      1. Parse JSON body
      2. Enforce max input length (2000 chars) → 400
      3. Strip null bytes and non-printable control characters
      4. Detect injection attempts → 400 (never sanitize-and-pass)
      5. Rebuild request with cleaned body
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method == "POST" and any(
            request.url.path.startswith(p) for p in CHAT_PATHS
        ):
            try:
                raw = await request.body()
                data = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JSONResponse(
                    {"detail": "Invalid request body."},
                    status_code=400,
                )

            question: str = data.get("question", "")

            # Step 1 — length limit
            if len(question) > MAX_INPUT_LENGTH:
                return JSONResponse(
                    {"detail": f"Input exceeds {MAX_INPUT_LENGTH} character limit."},
                    status_code=400,
                )

            # Step 2 — strip null bytes and non-printable control characters
            # Preserves \t (0x09), \n (0x0a), \r (0x0d) as legitimate whitespace
            question = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", question)

            # Step 3 — injection detection → reject outright, never pass modified text
            if _injection_filter.is_injection(question):
                log.warning(
                    "injection_blocked",
                    path=request.url.path,
                    preview=question[:60],
                )
                return JSONResponse({"detail": "Invalid input."}, status_code=400)

            # Step 4 — rebuild request with cleaned body
            data["question"] = question
            cleaned_body = json.dumps(data).encode()

            async def _receive():
                return {"type": "http.request", "body": cleaned_body, "more_body": False}

            request = Request(request.scope, _receive)

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to every outgoing response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'"
        )
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured request/response logging with unique request IDs."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())[:8]
        t0 = time.monotonic()

        log.info(
            "request_start",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)

        log.info(
            "request_end",
            request_id=request_id,
            status_code=response.status_code,
            duration_ms=round((time.monotonic() - t0) * 1000),
        )
        return response
