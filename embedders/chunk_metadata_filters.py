"""Shared helpers for pre-retrieval metadata filtering (chunk metadata_json shape)."""


def chunk_matches_tag_filters(
    metadata: dict | None,
    property_type_filter: list[str] | None,
    citizenship_filter: list[str] | None,
) -> bool:
    """Return True if chunk metadata passes optional property / citizenship filters.

    Chunk rows store tags under metadata_json['tags'] with lists keyed as
    ``property_type`` and ``citizenship`` (see processors.models.ExtractedMetadata).
    """
    if not property_type_filter and not citizenship_filter:
        return True

    meta = metadata or {}
    tags = meta.get("tags") or {}
    prop_types = tags.get("property_type") or []
    cit_types = tags.get("citizenship") or []

    if property_type_filter:
        if not any(pt in property_type_filter for pt in prop_types):
            return False
    if citizenship_filter:
        if not any(ct in citizenship_filter for ct in cit_types):
            return False
    return True
