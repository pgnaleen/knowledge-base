"""Chunk validation — quality gate between DocumentChunker and the embedding pipeline."""

import hashlib
import re

import tiktoken

from config.logger import get_logger
from processors.models import (
    ChunkValidationIssue,
    DocumentChunk,
    ValidationResult,
)

logger = get_logger("validator")

_ENCODING = tiktoken.get_encoding("cl100k_base")

_BOILERPLATE_PATTERNS: list[re.Pattern] = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r"^(skip to (main )?content|jump to navigation)$",
        r"^(home\s*[>»|/]\s*){1,}",
        r"^(menu|nav(igation)?|sidebar|footer|header|cookie policy|privacy policy)$",
        r"^\s*©\s*\d{4}",
        r"^(last (updated|modified|reviewed):?\s*[\d/\-]+)$",
        r"^(share (this )?page|print this page|back to top|[↑▲]\s*top)$",
        r"^(subscribe|sign up|log in|register|contact us)$",
        r"^[\s\|\-•·,;:]+$",
        r"^\d+\s*$",
    ]
]

_SENTENCE_END = re.compile(r'[.!?…"\')\]]+\s*$')
_STARTS_LOWERCASE = re.compile(r"^[a-z]")


class ChunkValidator:
    """Quality gate that filters and audits a list of DocumentChunk objects.

    Error-level checks cause the chunk to be removed; warning-level checks
    are recorded but the chunk is kept. After filtering, valid chunks are
    re-indexed sequentially from 0.
    """

    MIN_TOKENS: int = 50
    MAX_TOKENS: int = 512
    VALID_CHUNK_TYPES: frozenset[str] = frozenset({"text", "table"})
    REQUIRED_METADATA_KEYS: frozenset[str] = frozenset(
        {"source_agency", "chunk_type", "chunk_index"}
    )

    def validate(self, chunks: list[DocumentChunk]) -> ValidationResult:
        issues: list[ChunkValidationIssue] = []
        valid: list[DocumentChunk] = []
        filtered = 0
        seen_hashes: set[str] = set()

        for chunk in chunks:
            keep, chunk_issues = self._validate_chunk(chunk, seen_hashes)
            issues.extend(chunk_issues)
            if keep:
                text_hash = hashlib.sha256(chunk.chunk_text.encode()).hexdigest()
                seen_hashes.add(text_hash)
                valid.append(chunk)
            else:
                filtered += 1

        issues.extend(self._check_sequential_indices(valid))

        for new_idx, chunk in enumerate(valid):
            chunk.chunk_index = new_idx
            chunk.metadata["chunk_index"] = new_idx

        logger.debug(
            "validator.result",
            total_input=len(chunks),
            valid=len(valid),
            filtered=filtered,
            errors=sum(1 for i in issues if i.severity == "error"),
            warnings=sum(1 for i in issues if i.severity == "warning"),
        )

        return ValidationResult(
            valid_chunks=valid,
            issues=issues,
            filtered_count=filtered,
        )

    def _validate_chunk(
        self,
        chunk: DocumentChunk,
        seen_hashes: set[str],
    ) -> tuple[bool, list[ChunkValidationIssue]]:
        issues: list[ChunkValidationIssue] = []
        keep = True

        if not chunk.chunk_text or not chunk.chunk_text.strip():
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="chunk_text",
                severity="error",
                message="chunk_text is empty or whitespace-only",
            ))
            return False, issues

        if "\x00" in chunk.chunk_text:
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="chunk_text",
                severity="error",
                message="chunk_text contains null bytes (possible binary corruption)",
            ))
            return False, issues

        if chunk.chunk_type not in self.VALID_CHUNK_TYPES:
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="chunk_type",
                severity="error",
                message=(
                    f"chunk_type '{chunk.chunk_type}' is not one of "
                    f"{sorted(self.VALID_CHUNK_TYPES)}"
                ),
            ))
            keep = False

        token_count = len(_ENCODING.encode(chunk.chunk_text))

        if token_count < self.MIN_TOKENS:
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="chunk_text",
                severity="error",
                message=f"token count {token_count} is below minimum {self.MIN_TOKENS}",
            ))
            keep = False

        if token_count > self.MAX_TOKENS:
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="chunk_text",
                severity="error",
                message=f"token count {token_count} exceeds maximum {self.MAX_TOKENS}",
            ))
            keep = False

        stripped = chunk.chunk_text.strip()
        if self._is_boilerplate(stripped):
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="chunk_text",
                severity="error",
                message="chunk contains only navigation or boilerplate content",
            ))
            keep = False

        text_hash = hashlib.sha256(chunk.chunk_text.encode()).hexdigest()
        if text_hash in seen_hashes:
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="chunk_text",
                severity="error",
                message=f"duplicate chunk (sha256={text_hash[:12]}…)",
            ))
            keep = False

        if not keep:
            return False, issues

        actual_wc = len(chunk.chunk_text.split())
        if chunk.word_count != actual_wc:
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="word_count",
                severity="warning",
                message=(
                    f"stored word_count {chunk.word_count} does not match "
                    f"actual {actual_wc}"
                ),
            ))

        if not chunk.source_url:
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="source_url",
                severity="warning",
                message="source_url is empty",
            ))

        if not chunk.source_name:
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="source_name",
                severity="warning",
                message="source_name is empty",
            ))

        for key in self.REQUIRED_METADATA_KEYS:
            if key not in chunk.metadata:
                issues.append(ChunkValidationIssue(
                    chunk_index=chunk.chunk_index,
                    field="metadata",
                    severity="warning",
                    message=f"required metadata key '{key}' is missing",
                ))

        if chunk.metadata.get("source_agency") == "":
            issues.append(ChunkValidationIssue(
                chunk_index=chunk.chunk_index,
                field="metadata.source_agency",
                severity="warning",
                message="metadata source_agency is an empty string",
            ))

        for entry in chunk.heading_path:
            if "level" not in entry or "text" not in entry:
                issues.append(ChunkValidationIssue(
                    chunk_index=chunk.chunk_index,
                    field="heading_path",
                    severity="warning",
                    message="heading_path entry is missing 'level' or 'text' key",
                ))
                break

        if chunk.chunk_type == "text":
            if _STARTS_LOWERCASE.match(stripped):
                issues.append(ChunkValidationIssue(
                    chunk_index=chunk.chunk_index,
                    field="chunk_text",
                    severity="warning",
                    message="chunk starts with a lowercase letter — possible mid-sentence split",
                ))

            if not _SENTENCE_END.search(stripped):
                issues.append(ChunkValidationIssue(
                    chunk_index=chunk.chunk_index,
                    field="chunk_text",
                    severity="warning",
                    message="chunk does not end with terminal punctuation — possible mid-sentence split",
                ))

        return True, issues

    @staticmethod
    def _is_boilerplate(text: str) -> bool:
        return any(p.search(text) for p in _BOILERPLATE_PATTERNS)

    @staticmethod
    def _check_sequential_indices(
        chunks: list[DocumentChunk],
    ) -> list[ChunkValidationIssue]:
        if not chunks:
            return []
        expected = list(range(len(chunks)))
        actual = [c.chunk_index for c in chunks]
        if actual == expected:
            return []
        return [
            ChunkValidationIssue(
                chunk_index=-1,
                field="chunk_index",
                severity="warning",
                message=(
                    f"chunk_index not sequential after filtering; "
                    f"re-indexing from {actual} to {expected}"
                ),
            )
        ]
