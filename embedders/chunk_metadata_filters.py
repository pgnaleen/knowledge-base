"""Shared helpers for pre-retrieval metadata filtering (chunk metadata_json shape)."""


def chunk_matches_tag_filters(
    metadata: dict | None,
    property_type_filter: list[str] | None,
    citizenship_filter: list[str] | None,
    topic_filter: list[str] | None = None,
) -> bool:
    """Return True if chunk metadata passes optional property / citizenship / topic filters.

    Chunk rows store tags under metadata_json['tags'] with lists keyed as
    ``property_type``, ``citizenship`` and ``topic`` (see processors.models.ExtractedMetadata).
    """
    if not property_type_filter and not citizenship_filter and not topic_filter:
        return True

    meta = metadata or {}
    tags = meta.get("tags") or {}
    prop_types = tags.get("property_type") or []
    cit_types = tags.get("citizenship") or []
    topics = tags.get("topic") or []

    if property_type_filter and not any(pt in property_type_filter for pt in prop_types):
        return False
    if citizenship_filter and not any(ct in citizenship_filter for ct in cit_types):
        return False
    if topic_filter and not any(t in topic_filter for t in topics):
        return False
    return True
