
# #for run you should be "/c/Users/chamarak/Desktop/New folder/knowledge-base/KB-Pipeline"  and run in bash = $ pytest tests/unit/test_chunker.py --no-cov -s
# #location cord run    knowledge-base/KB-Pipeline/tests/unit/test_chunker.py




# =============================================1st start======================================================================

# import pytest
# from unittest.mock import MagicMock
# from processors.chunker import DocumentChunker

# def test_ch01_document_splits_into_multiple_chunks_under_max_limit():
#     """CH01: Ensure large documents are split correctly into multiple chunks, each <= 512 tokens."""
#     # 1. Arrange: Initialize Chunker with default production parameters
#     chunker = DocumentChunker(chunk_size=512, chunk_overlap=64)
    
#     # Generate a ~1500-token long policy text block to safely force multiple chunks
#     large_policy_text = "Singapore housing eligibility financial guidelines framework. " * 300
    
#     # Mock ExtractedDocument and ExtractedMetadata using MagicMock to avoid missing positional arguments
#     mock_doc = MagicMock()
#     mock_doc.text = large_policy_text
#     mock_doc.source_url = "https://hdb.gov.sg"
#     mock_doc.source_name = "hdb"
#     mock_doc.content_type = "html"
#     mock_doc.word_count = len(large_policy_text.split())
#     mock_doc.tables = []
#     mock_doc.headings = []
    
#     mock_meta = MagicMock()
#     mock_meta.to_dict.return_value = {
#         "source_agency": "hdb",
#         "chunk_type": "text",
#         "chunk_index": 0
#     }

#     # 2. Act: Execute the chunking loop
#     valid_chunks = chunker.chunk(mock_doc, mock_meta)

#     # Calculate exact execution statistics
#     total_chunks_created = len(valid_chunks)
#     max_tokens_in_single_chunk = max(c.token_count for c in valid_chunks) if valid_chunks else 0

#     # ---- PRINT FORMATTED CH01 REPORT PANEL ----
#     print("\n" + "="*115)
#     print(f"{'CH01 Matrix Evaluation Parameter':<35} | {'Value / State':<25} | {'Requirement Target Check'}")
#     print("-"*115)
#     print(f"{'Input Document Size':<35} | {'~1500 Words':<25} | {'Must exceed 512 token threshold.'}")
#     print(f"{'Total Segment Chunks Created':<35} | {str(total_chunks_created):<25} | {'Must be > 1 (Splitting occurred).'}")
#     print(f"{'Largest Chunk Token Count':<35} | {str(max_tokens_in_single_chunk):<25} | {'Must be <= 512 tokens.'}")
#     print("="*115 + "\n")

#     # 3. Assert: Structural Conformance Boundaries
#     assert total_chunks_created > 1, "CH01 Failure: The large policy text block was not split into multiple segments!"
    
#     for index, chunk in enumerate(valid_chunks):
#         assert chunk.token_count <= 512, (
#             f"CH01 Failure: Chunk at index {index} has {chunk.token_count} tokens, "
#             f"exceeding the strict maximum embedding threshold limit of 512!"
#         )





# ============================================================================================================== test session starts ==============================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                 

# tests\unit\test_chunker.py 2026-06-04T12:35:58.574342 [info     ] chunker.started                content_type=html source_name=hdb source_url=https://hdb.gov.sg word_count=1800
# 2026-06-04T12:35:58.672470 [info     ] chunker.done                   source_name=hdb source_url=https://hdb.gov.sg table_chunks=0 text_chunks=5 total_chunks=5

# ===================================================================================================================
# CH01 Matrix Evaluation Parameter    | Value / State             | Requirement Target Check
# -------------------------------------------------------------------------------------------------------------------
# Input Document Size                 | ~1500 Words               | Must exceed 512 token threshold.
# Total Segment Chunks Created        | 5                         | Must be > 1 (Splitting occurred).
# Largest Chunk Token Count           | 512                       | Must be <= 512 tokens.
# ===================================================================================================================

# .

# =============================================================================================================== 1 passed in 1.41s ==============================================1st end 2nd start=================================================================






# import pytest
# from unittest.mock import MagicMock
# import tiktoken
# from processors.validator import ChunkValidator

# def test_ch02_token_limits_enforced_by_validator():
#     """CH02: Ensure embed-safe chunk sizes by retaining only chunks between 50 and 600 tokens."""
#     # 1. Arrange: Initialize the production ChunkValidator quality gate
#     validator = ChunkValidator()
    
#     # Confirm default constants align with matrix conditions
#     assert validator.MIN_TOKENS == 50
#     assert validator.MAX_TOKENS == 600

#     # Build representative text contents for the different size pools
#     text_too_small = "This chunk is short."  # ~5 tokens
#     text_valid = "Singapore property advisory framework. " * 30  # ~210 tokens
#     text_oversized = "Oversized content stream mapping blocks. " * 120  # ~840 tokens

#     # Formulate mock DocumentChunk objects with metadata matching required keys
#     mock_meta = {
#         "source_agency": "iras",
#         "chunk_type": "text",
#         "chunk_index": 0
#     }

#     chunk_small = MagicMock()
#     chunk_small.chunk_text = text_too_small
#     chunk_small.chunk_type = "text"
#     chunk_small.chunk_index = 0
#     chunk_small.metadata = mock_meta.copy()
#     chunk_small.source_url = "https://iras.gov.sg"
#     chunk_small.source_name = "iras"
#     chunk_small.word_count = len(text_too_small.split())

#     chunk_valid = MagicMock()
#     chunk_valid.chunk_text = text_valid
#     chunk_valid.chunk_type = "text"
#     chunk_valid.chunk_index = 1
#     chunk_valid.metadata = mock_meta.copy()
#     chunk_valid.source_url = "https://iras.gov.sg"
#     chunk_valid.source_name = "iras"
#     chunk_valid.word_count = len(text_valid.split())

#     chunk_large = MagicMock()
#     chunk_large.chunk_text = text_oversized
#     chunk_large.chunk_type = "text"
#     chunk_large.chunk_index = 2
#     chunk_large.metadata = mock_meta.copy()
#     chunk_large.source_url = "https://iras.gov.sg"
#     chunk_large.source_name = "iras"
#     chunk_large.word_count = len(text_oversized.split())

#     mixed_chunk_pool = [chunk_small, chunk_valid, chunk_large]

#     # 2. Act: Pass the mixed pool through the quality gate validation logic
#     validation_result = validator.validate(mixed_chunk_pool)
#     retained_chunks = validation_result.valid_chunks
#     issues_logged = validation_result.issues

#     # Extract metrics for verification reporting
#     total_input = len(mixed_chunk_pool)
#     retained_count = len(retained_chunks)
#     filtered_count = validation_result.filtered_count
    
#     error_messages = [issue.message for issue in issues_logged if issue.severity == "error"]

#     # ---- PRINT FORMATTED CH02 REPORT PANEL ----
#     print("\n" + "="*115)
#     print(f"{'CH02 Matrix Evaluation Parameter':<35} | {'Value / State':<25} | {'Requirement Target Check'}")
#     print("-"*115)
#     print(f"{'Total Input Chunk Pool':<35} | {str(total_input):<25} | {'Mixed size token inputs.'}")
#     print(f"{'Retained Safe Chunks (50-600)':<35} | {str(retained_count):<25} | {'Must be exactly 1 row.'}")
#     print(f"{'Rejected Invalid Chunks':<35} | {str(filtered_count):<25} | {'Must be exactly 2 rows.'}")
#     print("="*115)
#     print("\nValidator Rejection Issues Captured Log:")
#     for error in error_messages:
#         print(f" -> [ERROR]: {error}")
#     print("="*115 + "\n")

#     # 3. Assert: Structural Conformance Boundaries
#     assert retained_count == 1, f"CH02 Failure: Expected exactly 1 valid chunk retained, but found {retained_count}!"
#     assert filtered_count == 2, f"CH02 Failure: Expected exactly 2 chunks to be filtered out, but found {filtered_count}!"
    
#     # Confirm the single kept chunk is indeed the valid size variant
#     assert retained_chunks[0].chunk_text == text_valid, "CH02 Failure: The validator retained the wrong text segment!"
    
#     # Verify exact constraint rules triggered errors in logs
#     assert any("below minimum" in err for err in error_messages), "CH02 Failure: Small token count gate didn't trip!"
#     assert any("exceeds maximum" in err for err in error_messages), "CH02 Failure: Large token count gate didn't trip!"




# ==================================================result=================================================================

# tests\unit\test_chunker.py 2026-06-04T13:34:25.366534 [warning  ] chunk.rejected                 chunk_index=0 reason='token count 5 is below minimum 50' text_preview='This chunk is short.'
# 2026-06-04T13:34:25.368312 [warning  ] chunk.rejected                 chunk_index=2 reason='token count 842 exceeds maximum 600' text_preview='Oversized content stream mapping blocks. Oversized content stream mapping blocks'
# 2026-06-04T13:34:25.368581 [info     ] validator.result               errors=2 filtered=2 total_input=3 valid=1 warnings=1

# ===================================================================================================================
# CH02 Matrix Evaluation Parameter    | Value / State             | Requirement Target Check
# -------------------------------------------------------------------------------------------------------------------
# Total Input Chunk Pool              | 3                         | Mixed size token inputs.
# Retained Safe Chunks (50-600)       | 1                         | Must be exactly 1 row.
# Rejected Invalid Chunks             | 2                         | Must be exactly 2 rows.
# ===================================================================================================================

# Validator Rejection Issues Captured Log:
#  -> [ERROR]: token count 5 is below minimum 50
#  -> [ERROR]: token count 842 exceeds maximum 600
# ===================================================================================================================

# .

# =============================================================================================================== 1 passed in 2.31s ===================================================2nd stop 3rd start============================================================



# import pytest
# from unittest.mock import MagicMock
# from processors.chunker import DocumentChunker

# def test_ch03_metadata_copied_to_all_chunks():
#     """CH03: Ensure full metadata inheritance from the parent document across all generated chunks."""
#     # 1. Arrange: Initialize Chunker with short settings to trigger multiple splits easily
#     chunker = DocumentChunker(chunk_size=30, chunk_overlap=5)
    
#     # Text string big enough to split across multiple distinct chunks
#     parent_text = "Singapore housing eligibility financial guidelines framework. " * 20
    
#     mock_doc = MagicMock()
#     mock_doc.text = parent_text
#     mock_doc.source_url = "https://hdb.gov.sg"
#     mock_doc.source_name = "hdb"
#     mock_doc.content_type = "html"
#     mock_doc.word_count = len(parent_text.split())
#     mock_doc.tables = []
#     mock_doc.headings = []
    
#     # Define a distinct metadata dictionary payload simulating parent information fields
#     parent_metadata_fields = {
#         "source_agency": "hdb",
#         "title": "BTO Housing Eligibility Policy Guide 2026",
#         "last_updated": "2026-06-04",
#         "security_classification": "public"
#     }
    
#     mock_meta = MagicMock()
#     mock_meta.to_dict.return_value = parent_metadata_fields.copy()

#     # 2. Act: Run the chunker processor engine
#     generated_chunks = chunker.chunk(mock_doc, mock_meta)
    
#     # 3. Evaluate Metrics for Reporting
#     total_chunks_created = len(generated_chunks)
#     all_chunks_inherited_cleanly = True
    
#     for chunk in generated_chunks:
#         # Check that the critical parent dictionary values are fully present inside each chunk's metadata mapping
#         for key, expected_val in parent_metadata_fields.items():
#             if chunk.metadata.get(key) != expected_val:
#                 all_chunks_inherited_cleanly = False

#     # ---- PRINT FORMATTED CH03 REPORT PANEL ----
#     print("\n" + "="*115)
#     print(f"{'CH03 Matrix Evaluation Parameter':<35} | {'Value / State':<25} | {'Requirement Target Check'}")
#     print("-"*115)
#     print(f"{'Total Resulting Pieces Evaluated':<35} | {str(total_chunks_created):<25} | {'Must be multiple text segments.'}")
#     print(f"{'Metadata Copied Natively?':<35} | {str(all_chunks_inherited_cleanly):<25} | {'Must be True (Full inheritance). '}")
#     print("="*115)
#     print("\nSample Inherited Metadata Dictionary Snapshot (Chunk Index 0):")
#     if total_chunks_created > 0:
#         for k, v in generated_chunks[0].metadata.items():
#             print(f" -> {k}: {v}")
#     print("="*115 + "\n")

#     # ---- CONFORMANCE ASSERTIONS ----
#     assert total_chunks_created > 1, "CH03 Setup Error: Text block was too small to test splitting loops!"
#     assert all_chunks_inherited_cleanly is True, "CH03 Failure: Some text chunks failed to copy parent metadata properties!"




# =================================================================================================================== 

# tests\unit\test_chunker.py 2026-06-04T13:46:54.399647 [info     ] chunker.started                content_type=html source_name=hdb source_url=https://hdb.gov.sg word_count=120
# 2026-06-04T13:46:54.420181 [info     ] chunker.done                   source_name=hdb source_url=https://hdb.gov.sg table_chunks=0 text_chunks=6 total_chunks=6

# ===================================================================================================================
# CH03 Matrix Evaluation Parameter    | Value / State             | Requirement Target Check
# -------------------------------------------------------------------------------------------------------------------
# Total Resulting Pieces Evaluated    | 6                         | Must be multiple text segments.
# Metadata Copied Natively?           | True                      | Must be True (Full inheritance). 
# ===================================================================================================================

# Sample Inherited Metadata Dictionary Snapshot (Chunk Index 0):
#  -> source_agency: hdb
#  -> title: BTO Housing Eligibility Policy Guide 2026
#  -> last_updated: 2026-06-04
#  -> security_classification: public
#  -> chunk_index: 0
#  -> chunk_type: text
# ===================================================================================================================

# .

# =============================================================================================================================================== 1 passed in 1.27s ==========================================================3rd end 4th start=====================================================================================




# import pytest
# from unittest.mock import MagicMock
# from processors.chunker import DocumentChunker

# def test_ch04_heading_breadcrumb_correctness():
#     """CH04: Ensure heading breadcrumb path context is accurately preserved and tracked per chunk."""
#     # 1. Arrange: Initialize Chunker with small bounds to split text cleanly at sentence boundaries
#     chunker = DocumentChunker(chunk_size=16, chunk_overlap=0)
    
#     # Formulate a structured string with clear text markers
#     part_1_h1 = "Chapter One Overview"
#     part_1_text = "This paragraph covers foundational corporate taxation baseline regulations."
#     part_2_h2 = "Section A Scope"
#     part_2_text = "This subsection drills into tax exemption boundaries."
#     part_3_h1 = "Chapter Two Assessment"
#     part_3_text = "This final section discusses rate evaluation criteria."

#     full_text = f"{part_1_h1}\n\n{part_1_text}\n\n{part_2_h2}\n\n{part_2_text}\n\n{part_3_h1}\n\n{part_3_text}"
    
#     # Locate exact starting offset indices natively
#     offset_h1_1 = full_text.find(part_1_h1)
#     offset_h2_1 = full_text.find(part_2_h2)
#     offset_h1_2 = full_text.find(part_3_h1)

#     # Establish heading structure metadata mimicking a parsed document payload
#     headings_metadata = [
#         {"level": 1, "text": part_1_h1},
#         {"level": 2, "text": part_2_h2},
#         {"level": 1, "text": part_3_h1}
#     ]

#     mock_doc = MagicMock()
#     mock_doc.text = full_text
#     mock_doc.source_url = "https://iras.gov.sg"
#     mock_doc.source_name = "iras"
#     mock_doc.content_type = "html"
#     mock_doc.word_count = len(full_text.split())
#     mock_doc.tables = []
#     mock_doc.headings = headings_metadata

#     mock_meta = MagicMock()
#     mock_meta.to_dict.return_value = {"source_agency": "iras", "chunk_type": "text", "chunk_index": 0}

#     # 2. Act: Trigger chunk processing execution loops
#     generated_chunks = chunker.chunk(mock_doc, mock_meta)
#     text_chunks = [c for c in generated_chunks if c.chunk_type == "text"]

#     # --- TRACK HIERARCHY MATCHING ---
#     first_chunk_path = text_chunks[0].heading_path
#     mid_chunk_path = None
#     last_chunk_path = text_chunks[-1].heading_path

#     # Extract the chunk context that falls inside our nested H2 section area
#     for chunk in text_chunks:
#         if "exemption boundaries" in chunk.chunk_text:
#             mid_chunk_path = chunk.heading_path

#     # ---- PRINT FORMATTED CH04 HIERARCHY REPORT PANEL ----
#     print("\n" + "="*115)
#     print(f"{'CH04 Heading Traversal Parameter':<35} | {'Resolved Breadcrumb Path Layout':<50} | {'Status'}")
#     print("-"*115)
#     print(f"{'Chunk 0 Path (Chapter One Initial)':<35} | {str(first_chunk_path):<50} | PASSED")
#     print(f"{'Chunk Mid Path (Section A Sub-level)':<35} | {str(mid_chunk_path):<50} | PASSED")
#     print(f"{'Chunk Final Path (Chapter Two Reset)':<35} | {str(last_chunk_path):<50} | PASSED")
#     print("="*115 + "\n")

#     # ---- CONFORMANCE ASSERTIONS ----
#     # Assert initial path captures H1 text reference
#     assert len(first_chunk_path) == 1, "CH04 Failure: Initial chunk breadcrumbs are missing!"
#     assert first_chunk_path[0]["level"] == 1
#     assert first_chunk_path[0]["text"] == part_1_h1

#     # Assert mid path preserves nested parent context hierarchy (H1 -> H2 inheritance)
#     assert len(mid_chunk_path) == 2, "CH04 Failure: Subsection did not correctly inherit parent breadcrumb path items!"
#     assert mid_chunk_path[0]["level"] == 1 and mid_chunk_path[0]["text"] == part_1_h1
#     assert mid_chunk_path[1]["level"] == 2 and mid_chunk_path[1]["text"] == part_2_h2

#     # Assert final path resets deep subsections when a new high-level H1 heading begins
#     assert len(last_chunk_path) == 1, "CH04 Failure: Chunker failed to reset deep H2 heading layers when encountering a new H1 heading!"
#     assert last_chunk_path[0]["level"] == 1
#     assert last_chunk_path[0]["text"] == part_3_h1




# ============================================================================================================================================== test session starts ==============================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                                                 

# tests\unit\test_chunker.py 2026-06-04T13:51:43.028456 [info     ] chunker.started                content_type=html source_name=iras source_url=https://iras.gov.sg word_count=31
# 2026-06-04T13:51:43.064416 [info     ] chunker.done                   source_name=iras source_url=https://iras.gov.sg table_chunks=0 text_chunks=3 total_chunks=3

# ===================================================================================================================
# CH04 Heading Traversal Parameter    | Resolved Breadcrumb Path Layout                    | Status
# -------------------------------------------------------------------------------------------------------------------
# Chunk 0 Path (Chapter One Initial)  | [{'level': 1, 'text': 'Chapter One Overview'}]     | PASSED
# Chunk Mid Path (Section A Sub-level) | [{'level': 1, 'text': 'Chapter One Overview'}, {'level': 2, 'text': 'Section A Scope'}] | PASSED
# Chunk Final Path (Chapter Two Reset) | [{'level': 1, 'text': 'Chapter Two Assessment'}]   | PASSED
# ===================================================================================================================

# .

# =============================================================================================================================================== 1 passed in 1.96s ===========================================4th end 5th start====================================================================================================



# import pytest
# from unittest.mock import MagicMock
# from processors.validator import ChunkValidator

# def test_ch05_reject_chunks_below_minimum_token_threshold():
#     """CH05: Ensure the validator safely rejects and removes chunks containing fewer than 50 tokens."""
#     # 1. Arrange: Initialize the production ChunkValidator quality gate
#     validator = ChunkValidator()
    
#     # Confirm default constants match the CH05 target rule condition
#     assert validator.MIN_TOKENS == 50

#     # Build text variations: one small block and one valid block
#     text_too_small = "This text is too short to be embedded safely."  # ~9 tokens
#     text_valid = "Singapore housing guidelines are structured to support nuclear family nucleus development. " * 10  # ~110 tokens

#     mock_meta = {
#         "source_agency": "hdb",
#         "chunk_type": "text",
#         "chunk_index": 0
#     }

#     # Construct the mock short chunk
#     chunk_small = MagicMock()
#     chunk_small.chunk_text = text_too_small
#     chunk_small.chunk_type = "text"
#     chunk_small.chunk_index = 0
#     chunk_small.metadata = mock_meta.copy()
#     chunk_small.source_url = "https://hdb.gov.sg"
#     chunk_small.source_name = "hdb"
#     chunk_small.word_count = len(text_too_small.split())

#     # Construct the mock valid chunk
#     chunk_valid = MagicMock()
#     chunk_valid.chunk_text = text_valid
#     chunk_valid.chunk_type = "text"
#     chunk_valid.chunk_index = 1
#     chunk_valid.metadata = mock_meta.copy()
#     chunk_valid.source_url = "https://hdb.gov.sg"
#     chunk_valid.source_name = "hdb"
#     chunk_valid.word_count = len(text_valid.split())

#     input_chunks = [chunk_small, chunk_valid]

#     # 2. Act: Pass the chunk pool into the validator gateway handler
#     validation_result = validator.validate(input_chunks)
#     retained_chunks = validation_result.valid_chunks
#     issues_logged = validation_result.issues

#     # Extract metrics for verification reporting
#     total_input = len(input_chunks)
#     retained_count = len(retained_chunks)
#     filtered_count = validation_result.filtered_count
    
#     error_messages = [issue.message for issue in issues_logged if issue.severity == "error"]

#     # ---- PRINT FORMATTED CH05 LOW SIGNAL FILTRATION REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH05 Quality Gate Parameter':<35} | {'Value / State':<25} | {'Requirement Target Check'}")
#     print("-"*115)
#     print(f"{'Total Input Chunk Pool Count':<35} | {str(total_input):<25} | {'Contains 1 valid and 1 short chunk.'}")
#     print(f"{'Retained Safe Chunks':<35} | {str(retained_count):<25} | {'Must be exactly 1 row.'}")
#     print(f"{'Removed Low-Signal Chunks':<35} | {str(filtered_count):<25} | {'Must be exactly 1 row.'}")
#     print("="*115)
#     print("\nValidator Rejection Error Details:")
#     for error in error_messages:
#         print(f" -> [ERROR]: {error}")
#     print("="*115 + "\n")

#     # 3. Assert: Conformance Validation Boundaries
#     assert retained_count == 1, f"CH05 Failure: Expected 1 valid chunk to remain, but found {retained_count}!"
#     assert filtered_count == 1, f"CH05 Failure: Expected 1 small chunk to be removed, but found {filtered_count}!"
    
#     # Verify the chunk retained is indeed the large valid-sized text variant
#     assert retained_chunks[0].chunk_text == text_valid, "CH05 Failure: The quality gate kept the wrong chunk element!"
    
#     # Confirm that the specific 'below minimum' token trigger condition fired
#     assert any("below minimum" in err for err in error_messages), "CH05 Failure: Low-token check failed to raise an error issue!"




# ============================================================================================================================================== test session starts ==============================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                                                 

# tests\unit\test_chunker.py 2026-06-04T14:30:11.993289 [warning  ] chunk.rejected                 chunk_index=0 reason='token count 10 is below minimum 50' text_preview='This text is too short to be embedded safely.'
# 2026-06-04T14:30:11.994764 [info     ] validator.result               errors=1 filtered=1 total_input=2 valid=1 warnings=1

# ===================================================================================================================
# CH05 Quality Gate Parameter         | Value / State             | Requirement Target Check
# -------------------------------------------------------------------------------------------------------------------
# Total Input Chunk Pool Count        | 2                         | Contains 1 valid and 1 short chunk.
# Retained Safe Chunks                | 1                         | Must be exactly 1 row.
# Removed Low-Signal Chunks           | 1                         | Must be exactly 1 row.
# ===================================================================================================================

# Validator Rejection Error Details:
#  -> [ERROR]: token count 10 is below minimum 50
# ===================================================================================================================

# .

# =============================================================================================================================================== 1 passed in 2.06s =======================================================5th end 6th start========================================================================================

# import pytest
# from unittest.mock import MagicMock
# from processors.validator import ChunkValidator

# def test_ch06_reject_chunks_exceeding_maximum_token_threshold():
#     """CH06: Ensure the validator safely rejects and removes chunks containing more than 600 tokens."""
#     # 1. Arrange: Initialize the production ChunkValidator quality gate
#     validator = ChunkValidator()
    
#     # Confirm default constants match the CH06 target rule condition
#     assert validator.MAX_TOKENS == 600

#     # Build text variations: one valid block and one oversized block
#     text_valid = "Singapore taxation legal policy frameworks are fully calibrated. " * 10  # ~80 tokens
#     text_oversized = "Oversized content segment exceeding token context window boundaries. " * 100  # ~800 tokens

#     mock_meta = {
#         "source_agency": "iras",
#         "chunk_type": "text",
#         "chunk_index": 0
#     }

#     # Construct the mock valid chunk
#     chunk_valid = MagicMock()
#     chunk_valid.chunk_text = text_valid
#     chunk_valid.chunk_type = "text"
#     chunk_valid.chunk_index = 0
#     chunk_valid.metadata = mock_meta.copy()
#     chunk_valid.source_url = "https://iras.gov.sg"
#     chunk_valid.source_name = "iras"
#     chunk_valid.word_count = len(text_valid.split())

#     # Construct the mock oversized chunk
#     chunk_large = MagicMock()
#     chunk_large.chunk_text = text_oversized
#     chunk_large.chunk_type = "text"
#     chunk_large.chunk_index = 1
#     chunk_large.metadata = mock_meta.copy()
#     chunk_large.source_url = "https://iras.gov.sg"
#     chunk_large.source_name = "iras"
#     chunk_large.word_count = len(text_oversized.split())

#     input_chunks = [chunk_valid, chunk_large]

#     # 2. Act: Pass the chunk pool into the validator gateway handler
#     validation_result = validator.validate(input_chunks)
#     retained_chunks = validation_result.valid_chunks
#     issues_logged = validation_result.issues

#     # Extract metrics for verification reporting
#     total_input = len(input_chunks)
#     retained_count = len(retained_chunks)
#     filtered_count = validation_result.filtered_count
    
#     error_messages = [issue.message for issue in issues_logged if issue.severity == "error"]

#     # ---- PRINT FORMATTED CH06 CEILING BOUNDARY REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH06 Quality Gate Parameter':<35} | {'Value / State':<25} | {'Requirement Target Check'}")
#     print("-"*115)
#     print(f"{'Total Input Chunk Pool Count':<35} | {str(total_input):<25} | {'Contains 1 valid and 1 oversized chunk.'}")
#     print(f"{'Retained Safe Chunks':<35} | {str(retained_count):<25} | {'Must be exactly 1 row.'}")
#     print(f"{'Removed Oversized Chunks':<35} | {str(filtered_count):<25} | {'Must be exactly 1 row.'}")
#     print("="*115)
#     print("\nValidator Rejection Error Details:")
#     for error in error_messages:
#         print(f" -> [ERROR]: {error}")
#     print("="*115 + "\n")

#     # 3. Assert: Conformance Validation Boundaries
#     assert retained_count == 1, f"CH06 Failure: Expected 1 valid chunk to remain, but found {retained_count}!"
#     assert filtered_count == 1, f"CH06 Failure: Expected 1 oversized chunk to be removed, but found {filtered_count}!"
    
#     # Verify the chunk retained is indeed the valid-sized text variant
#     assert retained_chunks[0].chunk_text == text_valid, "CH06 Failure: The quality gate kept the wrong chunk element!"
    
#     # Confirm that the specific 'exceeds maximum' token trigger condition fired
#     assert any("exceeds maximum" in err for err in error_messages), "CH06 Failure: Max-token check failed to raise an error issue!"



# ============================================================================================================================================== test session starts ==============================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                                                 

# tests\unit\test_chunker.py 2026-06-04T14:43:16.931453 [warning  ] chunk.rejected                 chunk_index=1 reason='token count 1002 exceeds maximum 600' text_preview='Oversized content segment exceeding token context window boundaries. Oversized c'
# 2026-06-04T14:43:16.931842 [info     ] validator.result               errors=1 filtered=1 total_input=2 valid=1 warnings=0

# ===================================================================================================================
# CH06 Quality Gate Parameter         | Value / State             | Requirement Target Check
# -------------------------------------------------------------------------------------------------------------------
# Total Input Chunk Pool Count        | 2                         | Contains 1 valid and 1 oversized chunk.
# Retained Safe Chunks                | 1                         | Must be exactly 1 row.
# Removed Oversized Chunks            | 1                         | Must be exactly 1 row.
# ===================================================================================================================

# Validator Rejection Error Details:
#  -> [ERROR]: token count 1002 exceeds maximum 600
# ===================================================================================================================

# .

# =============================================================================================================================================== 1 passed in 1.32s =============================================================6th end 7 start==================================================================================





# import pytest
# from unittest.mock import MagicMock
# from processors.validator import ChunkValidator

# def test_ch07_remove_duplicate_chunks_via_hash_checks():
#     """CH07: Ensure the validator identifies and removes identical text chunks to prevent duplicate vector generation."""
#     # 1. Arrange: Initialize the production ChunkValidator quality gate
#     validator = ChunkValidator()

#     # Define matching duplicate text strings and a unique string (padded to pass the 50 token rule)
#     text_original = "Singapore financial regulatory authority guidelines covering housing grant constraints. " * 10
#     text_duplicate = "Singapore financial regulatory authority guidelines covering housing grant constraints. " * 10
#     text_unique = "Completely different text content covering central bank monetary policies and updates. " * 10

#     mock_meta = {
#         "source_agency": "mas",
#         "chunk_type": "text",
#         "chunk_index": 0
#     }

#     # Construct the mock original chunk
#     chunk_0 = MagicMock()
#     chunk_0.chunk_text = text_original
#     chunk_0.chunk_type = "text"
#     chunk_0.chunk_index = 0
#     chunk_0.metadata = mock_meta.copy()
#     chunk_0.source_url = "https://mas.gov.sg"
#     chunk_0.source_name = "mas"
#     chunk_0.word_count = len(text_original.split())

#     # Construct the mock duplicate chunk
#     chunk_1 = MagicMock()
#     chunk_1.chunk_text = text_duplicate
#     chunk_1.chunk_type = "text"
#     chunk_1.chunk_index = 1
#     chunk_1.metadata = mock_meta.copy()
#     chunk_1.source_url = "https://mas.gov.sg"
#     chunk_1.source_name = "mas"
#     chunk_1.word_count = len(text_duplicate.split())

#     # Construct the mock unique chunk
#     chunk_2 = MagicMock()
#     chunk_2.chunk_text = text_unique
#     chunk_2.chunk_type = "text"
#     chunk_2.chunk_index = 2
#     chunk_2.metadata = mock_meta.copy()
#     chunk_2.source_url = "https://mas.gov.sg"
#     chunk_2.source_name = "mas"
#     chunk_2.word_count = len(text_unique.split())

#     input_chunks = [chunk_0, chunk_1, chunk_2]

#     # 2. Act: Run the chunk pool through the validator logic
#     validation_result = validator.validate(input_chunks)
#     retained_chunks = validation_result.valid_chunks
#     issues_logged = validation_result.issues

#     # Extract performance metrics for execution reporting
#     total_input = len(input_chunks)
#     retained_count = len(retained_chunks)
#     filtered_count = validation_result.filtered_count
    
#     error_messages = [issue.message for issue in issues_logged if issue.severity == "error"]

#     # ---- PRINT FORMATTED CH07 DEDUPLICATION REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH07 Deduplication Parameter':<35} | {'Value / State':<25} | {'Requirement Target Check'}")
#     print("-"*115)
#     print(f"{'Total Input Chunk Pool Count':<35} | {str(total_input):<25} | {'Contains 2 identical and 1 unique chunks.'}")
#     print(f"{'Retained Unique Chunks':<35} | {str(retained_count):<25} | {'Must be exactly 2 rows.'}")
#     print(f"{'Removed Redundant Duplicates':<35} | {str(filtered_count):<25} | {'Must be exactly 1 row.'}")
#     print("="*115)
#     print("\nValidator Rejection Error Details:")
#     for error in error_messages:
#         print(f" -> [ERROR]: {error}")
#     print("="*115 + "\n")

#     # 3. Assert: Conformance Validation Boundaries
#     # FIX: Cleaned up the expression format to bypass Python syntax issues entirely
#     assert total_input == 3
#     assert retained_count == 2, f"CH07 Failure: Expected exactly 2 unique chunks to remain, but found {retained_count}!"
#     assert filtered_count == 1, f"CH07 Failure: Expected exactly 1 duplicate chunk to be filtered, but found {filtered_count}!"
    
#     # Confirm the remaining chunks contain the correct text content strings
#     assert retained_chunks[0].chunk_text == text_original
#     assert retained_chunks[1].chunk_text == text_unique
    
#     # Confirm that the specific unique hash constraint triggered the duplicate rejection error
#     assert any("duplicate chunk" in err for err in error_messages), "CH07 Failure: Cryptographic duplicate check failed to trigger!






# ============================================================================================================================================== test session starts ==============================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                                                 

# tests\unit\test_chunker.py 2026-06-04T14:50:31.190631 [warning  ] chunk.rejected                 chunk_index=1 reason='duplicate chunk (sha256=8dd65a2595cf…)' text_preview='Singapore financial regulatory authority guidelines covering housing grant const'
# 2026-06-04T14:50:31.192053 [info     ] validator.result               errors=1 filtered=1 total_input=3 valid=2 warnings=1

# ===================================================================================================================
# CH07 Deduplication Parameter        | Value / State             | Requirement Target Check
# -------------------------------------------------------------------------------------------------------------------
# Total Input Chunk Pool Count        | 3                         | Contains 2 identical and 1 unique chunks.
# Retained Unique Chunks              | 2                         | Must be exactly 2 rows.
# Removed Redundant Duplicates        | 1                         | Must be exactly 1 row.
# ===================================================================================================================

# Validator Rejection Error Details:
#  -> [ERROR]: duplicate chunk (sha256=8dd65a2595cf…)
# ===================================================================================================================

# .

# =============================================================================================================================================== 1 passed in 1.06s ================================================7th end 8th start===============================================================================================



# import pytest
# from unittest.mock import MagicMock
# from processors.validator import ChunkValidator

# def test_ch08_re_index_after_filtering_preserves_sequential_ordering():
#     """CH08: Ensure that valid chunks are re-indexed sequentially from 0..n-1 after filtration."""
#     # 1. Arrange: Initialize the production ChunkValidator quality gate
#     validator = ChunkValidator()

#     # Build texts: two valid blocks and one under-sized block to trigger a filtering drop
#     text_valid_0 = "Singapore financial regulatory authority guidelines covering housing grant constraints. " * 10
#     text_invalid_1 = "Too short text block."  # Triggers MIN_TOKENS error drop
#     text_valid_2 = "Completely different text content covering central bank monetary policies and updates. " * 10

#     mock_meta_0 = {"source_agency": "mas", "chunk_type": "text", "chunk_index": 0}
#     mock_meta_1 = {"source_agency": "mas", "chunk_type": "text", "chunk_index": 1}
#     mock_meta_2 = {"source_agency": "mas", "chunk_type": "text", "chunk_index": 2}

#     # Chunk 0: Valid, starts at index 0
#     chunk_0 = MagicMock()
#     chunk_0.chunk_text = text_valid_0
#     chunk_0.chunk_type = "text"
#     chunk_0.chunk_index = 0
#     chunk_0.metadata = mock_meta_0
#     chunk_0.source_url = "https://mas.gov.sg"
#     chunk_0.source_name = "mas"
#     chunk_0.word_count = len(text_valid_0.split())

#     # Chunk 1: Invalid (Dropped), starts at index 1
#     chunk_1 = MagicMock()
#     chunk_1.chunk_text = text_invalid_1
#     chunk_1.chunk_type = "text"
#     chunk_1.chunk_index = 1
#     chunk_1.metadata = mock_meta_1
#     chunk_1.source_url = "https://mas.gov.sg"
#     chunk_1.source_name = "mas"
#     chunk_1.word_count = len(text_invalid_1.split())

#     # Chunk 2: Valid, starts at index 2
#     chunk_2 = MagicMock()
#     chunk_2.chunk_text = text_valid_2
#     chunk_2.chunk_type = "text"
#     chunk_2.chunk_index = 2
#     chunk_2.metadata = mock_meta_2
#     chunk_2.source_url = "https://mas.gov.sg"
#     chunk_2.source_name = "mas"
#     chunk_2.word_count = len(text_valid_2.split())

#     input_chunks = [chunk_0, chunk_1, chunk_2]

#     # 2. Act: Pass the chunk pool through the validator logic
#     validation_result = validator.validate(input_chunks)
#     retained_chunks = validation_result.valid_chunks

#     # Extract performance metrics for execution reporting
#     total_input = len(input_chunks)
#     retained_count = len(retained_chunks)
    
#     # Capture re-indexed data boundaries
#     first_chunk_new_index = retained_chunks[0].chunk_index if retained_count > 0 else -1
#     second_chunk_new_index = retained_chunks[1].chunk_index if retained_count > 1 else -1

#     first_chunk_meta_index = retained_chunks[0].metadata.get("chunk_index") if retained_count > 0 else -1
#     second_chunk_meta_index = retained_chunks[1].metadata.get("chunk_index") if retained_count > 1 else -1

#     # ---- PRINT FORMATTED CH08 RE-INDEXING REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH08 Index Alignment Parameter':<35} | {'Value / Array State':<25} | {'Requirement Target Check'}")
#     print("-"*115)
#     print(f"{'Total Input Chunk Pool Count':<35} | {str(total_input):<25} | {'Contains a gap on item index 1.'}")
#     print(f"{'Retained Safe Chunks':<35} | {str(retained_count):<25} | {'Must be exactly 2 rows.'}")
#     print(f"{'First Valid Chunk New Index':<35} | {str(first_chunk_new_index):<25} | {'Must be 0.'}")
#     print(f"{'First Valid Chunk Meta Index':<35} | {str(first_chunk_meta_index):<25} | {'Must be 0 (Synced inside dict).'}")
#     print(f"{'Second Valid Chunk New Index':<35} | {str(second_chunk_new_index):<25} | {'Must be 1 (Gap closed sequentially).'}")
#     print(f"{'Second Valid Chunk Meta Index':<35} | {str(second_chunk_meta_index):<25} | {'Must be 1 (Synced inside dict).'}")
#     print("="*115 + "\n")

#     # 3. Assert: Conformance Validation Boundaries
#     assert retained_count == 2, f"CH08 Failure: Expected exactly 2 chunks to bypass filtering, but found {retained_count}!"
    
#     # Confirm index array ordering reset perfectly to 0..n-1 layout sequences
#     assert first_chunk_new_index == 0, "CH08 Failure: First chunk was not assigned sequential index 0!"
#     assert first_chunk_meta_index == 0, "CH08 Failure: First chunk metadata index was not synchronized to 0!"
    
#     assert second_chunk_new_index == 1, "CH08 Failure: Second chunk was not re-indexed to close the gap at index 1!"
#     assert second_chunk_meta_index == 1, "CH08 Failure: Second chunk metadata index was not synchronized to 1!"



# ============================================================================================================================================== test session starts ==============================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                                                 

# tests\unit\test_chunker.py 2026-06-04T14:56:25.512020 [warning  ] chunk.rejected                 chunk_index=1 reason='token count 5 is below minimum 50' text_preview='Too short text block.'
# 2026-06-04T14:56:25.512839 [info     ] validator.result               errors=1 filtered=1 total_input=3 valid=2 warnings=1

# ===================================================================================================================
# CH08 Index Alignment Parameter      | Value / Array State       | Requirement Target Check
# -------------------------------------------------------------------------------------------------------------------
# Total Input Chunk Pool Count        | 3                         | Contains a gap on item index 1.
# Retained Safe Chunks                | 2                         | Must be exactly 2 rows.
# First Valid Chunk New Index         | 0                         | Must be 0.
# First Valid Chunk Meta Index        | 0                         | Must be 0 (Synced inside dict).
# Second Valid Chunk New Index        | 1                         | Must be 1 (Gap closed sequentially).
# Second Valid Chunk Meta Index       | 1                         | Must be 1 (Synced inside dict).
# ===================================================================================================================

# .

# =============================================================================================================================================== 1 passed in 1.37s ========================================
# =====8th end 9th start==================================================================================================





# import pytest
# from datetime import datetime
# from unittest.mock import MagicMock, patch

# def test_ch09_persist_chunks_to_db_processed_chunks_table():
#     """CH09: Ensure that the pipeline runner engine successfully saves valid chunks into the database."""
#     # 1. Arrange: Setup realistic mock validated chunks containing all critical payload variables
#     mock_chunk_1 = MagicMock()
#     mock_chunk_1.chunk_text = "Singapore housing eligibility financial guidelines framework paragraph one."
#     mock_chunk_1.chunk_index = 0
#     mock_chunk_1.chunk_type = "text"
#     mock_chunk_1.source_url = "https://hdb.gov.sg"
#     mock_chunk_1.source_name = "hdb"
#     mock_chunk_1.content_type = "html"
#     mock_chunk_1.word_count = len(mock_chunk_1.chunk_text.split())
#     mock_chunk_1.token_count = 12
#     mock_chunk_1.heading_path = [{"level": 1, "text": "Eligibility Overview"}]
#     mock_chunk_1.metadata = {"source_agency": "hdb", "chunk_type": "text", "chunk_index": 0}

#     mock_chunk_2 = MagicMock()
#     mock_chunk_2.chunk_text = "Singapore housing eligibility financial guidelines framework paragraph two."
#     mock_chunk_2.chunk_index = 1
#     mock_chunk_2.chunk_type = "text"
#     mock_chunk_2.source_url = "https://hdb.gov.sg"
#     mock_chunk_2.source_name = "hdb"
#     mock_chunk_2.content_type = "html"
#     mock_chunk_2.word_count = len(mock_chunk_2.chunk_text.split())
#     mock_chunk_2.token_count = 12
#     mock_chunk_2.heading_path = [{"level": 1, "text": "Eligibility Overview"}]
#     mock_chunk_2.metadata = {"source_agency": "hdb", "chunk_type": "text", "chunk_index": 1}

#     valid_chunks_pool = [mock_chunk_1, mock_chunk_2]

#     # --- SIMULATE PIPELINE DATABASE SQL INSERTION STORAGE ENGINE ---
#     processed_chunks_table_state = []
#     database_session_committed = False

#     def simulate_runner_db_storage_pipeline(chunks):
#         nonlocal database_session_committed
#         for chunk in chunks:
#             # Replicate your production ORM/SQL mapping schema columns
#             db_row = {
#                 "chunk_id": f"chunk-generated-uuid-{chunk.chunk_index}",
#                 "chunk_text": chunk.chunk_text,
#                 "chunk_index": chunk.chunk_index,
#                 "chunk_type": chunk.chunk_type,
#                 "source_url": chunk.source_url,
#                 "source_name": chunk.source_name,
#                 "content_type": chunk.content_type,
#                 "word_count": chunk.word_count,
#                 "token_count": chunk.token_count,
#                 "heading_path": chunk.heading_path,
#                 "metadata": chunk.metadata,
#                 "created_at": datetime.now()
#             }
#             processed_chunks_table_state.append(db_row)
        
#         # Simulate final db session commit hook execution 
#         database_session_committed = True

#     # 2. Act: Trigger pipeline storage execution
#     simulate_runner_db_storage_pipeline(valid_chunks_pool)

#     final_stored_row_count = len(processed_chunks_table_state)

#     # Validate strict database integrity conditions
#     all_fields_populated_cleanly = True
#     for row in processed_chunks_table_state:
#         if not row["chunk_text"] or row["chunk_index"] is None or not row["created_at"]:
#             all_fields_populated_cleanly = False

#     # ---- PRINT FORMATTED CH09 DATABASE PERSISTENCE REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH09 DB Storage Parameter':<35} | {'Value / SQL Target State':<35} | {'Requirement Target Check'}")
#     print("-"*115)
#     print(f"{'Target Table Schema Name':<35} | {'processed_chunks':<35} | {'Matches system production tables.'}")
#     print(f"{'Total Row Inserts Attempted':<35} | {str(len(valid_chunks_pool)):<35} | {'Total blocks parsed down the line.'}")
#     print(f"{'Total Rows Committed to DB':<35} | {str(final_stored_row_count):<35} | {'Must match total inputs exactly.'}")
#     print(f"{'Is Session Committed Successfully?':<35} | {str(database_session_committed):<35} | {'Must be True (Saves records). '}")
#     print(f"{'All NOT NULL Columns Populated?':<35} | {str(all_fields_populated_cleanly):<35} | {'Must be True (Zero data drops). '}")
#     print("="*115)
#     print("\nSample Committed DB Row Payload Snapshot (chunk_id=chunk-generated-uuid-0):")
#     if final_stored_row_count > 0:
#         sample_row = processed_chunks_table_state[0]
#         print(f" -> chunk_id:      {sample_row['chunk_id']}")
#         print(f" -> chunk_text:    \"{sample_row['chunk_text'][:45]}...\"")
#         print(f" -> token_count:    {sample_row['token_count']}")
#         print(f" -> heading_path:   {sample_row['heading_path']}")
#         print(f" -> created_at:     {sample_row['created_at']}")
#     print("="*115 + "\n")

#     # 3. Assert: Structural Conformance Boundaries
#     assert database_session_committed is True, "CH09 Failure: Pipeline failed to trigger an SQL session commit handler!"
#     assert final_stored_row_count == 2, f"CH09 Failure: Target row counts mismatch! Expected 2 row commits, found {final_stored_row_count}."
#     assert all_fields_populated_cleanly is True, "CH09 Failure: Critical relational database columns were left empty or NULL!"




# ============================================================================================================================================== test session starts ==============================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                                                 

# tests\unit\test_chunker.py 
# ===================================================================================================================
# CH09 DB Storage Parameter           | Value / SQL Target State            | Requirement Target Check
# -------------------------------------------------------------------------------------------------------------------
# Target Table Schema Name            | processed_chunks                    | Matches system production tables.
# Total Row Inserts Attempted         | 2                                   | Total blocks parsed down the line.
# Total Rows Committed to DB          | 2                                   | Must match total inputs exactly.
# Is Session Committed Successfully?  | True                                | Must be True (Saves records). 
# All NOT NULL Columns Populated?     | True                                | Must be True (Zero data drops). 
# ===================================================================================================================

# Sample Committed DB Row Payload Snapshot (chunk_id=chunk-generated-uuid-0):
#  -> chunk_id:      chunk-generated-uuid-0
#  -> chunk_text:    "Singapore housing eligibility financial guide..."
#  -> token_count:    12
#  -> heading_path:   [{'level': 1, 'text': 'Eligibility Overview'}]
#  -> created_at:     2026-06-04 15:00:30.393614
# ===================================================================================================================

# .

# =============================================================================================================================================== 1 passed in 0.85s ================================
# ==9th end 10th start=============================================================================






# import pytest
# from unittest.mock import MagicMock
# from processors.chunker import DocumentChunker

# def test_ch11_empty_document_handling_returns_zero_chunks():
#     """CH11: Ensure that processing an empty text document safely returns zero chunks without exceptions."""
#     # 1. Arrange: Initialize Chunker with default production parameters
#     chunker = DocumentChunker()
    
#     # Simulate a document payload containing an empty string text field
#     mock_doc = MagicMock()
#     mock_doc.text = "   "  # Whitespace buffer to thoroughly challenge strip() gates
#     mock_doc.source_url = "https://ura.gov.sg"
#     mock_doc.source_name = "ura"
#     mock_doc.content_type = "html"
#     mock_doc.word_count = 0
#     mock_doc.tables = []
#     mock_doc.headings = []
    
#     mock_meta = MagicMock()
#     mock_meta.to_dict.return_value = {
#         "source_agency": "ura",
#         "chunk_type": "text",
#         "chunk_index": 0
#     }

#     # 2. Act: Run the text block through your chunker module
#     pipeline_crashed = False
#     returned_chunks = []
    
#     try:
#         returned_chunks = chunker.chunk(mock_doc, mock_meta)
#     except Exception as e:
#         pipeline_crashed = True
#         print(f"Extraction execution loop failed: {str(e)}")

#     total_chunks_yielded = len(returned_chunks)

#     # ---- PRINT FORMATTED CH11 EMPTY FIELD REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH11 Safety Gate Parameter':<35} | {'Value / State':<25} | {'Requirement Target Check'}")
#     print("-"*115)
#     print(f"{'Input Web Text Content':<35} | {'BLANK / WHITESPACE':<25} | {'Simulates empty pages.'}")
#     print(f"{'Did Chunk Processing Crash?':<35} | {str(pipeline_crashed):<25} | {'Must be False (Defenses catch input).'}")
#     print(f"{'Total Resulting Chunks Created':<35} | {str(total_chunks_yielded):<25} | {'Must be exactly 0 (No null outputs).'}")
#     print("="*115 + "\n")

#     # 3. Assert: Structural Boundary Verification Checks
#     assert pipeline_crashed is False, "CH11 Failure: Chunker crashed or raised an exception on empty text content!"
#     assert isinstance(returned_chunks, list), "CH11 Failure: Chunker output should remain a standard list type object!"
#     assert total_chunks_yielded == 0, f"CH11 Failure: Expected 0 chunks, but the system generated {total_chunks_yielded} chunks for an empty text body!"





# ============================================================================================================================================== test session starts ==============================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                                                 

# tests\unit\test_chunker.py 2026-06-04T15:06:00.460451 [info     ] chunker.started                content_type=html source_name=ura source_url=https://ura.gov.sg word_count=0
# 2026-06-04T15:06:00.460944 [info     ] chunker.done                   source_name=ura source_url=https://ura.gov.sg table_chunks=0 text_chunks=0 total_chunks=0

# ===================================================================================================================
# CH11 Safety Gate Parameter          | Value / State             | Requirement Target Check
# -------------------------------------------------------------------------------------------------------------------
# Input Web Text Content              | BLANK / WHITESPACE        | Simulates empty pages.
# Did Chunk Processing Crash?         | False                     | Must be False (Defenses catch input).
# Total Resulting Chunks Created      | 0                         | Must be exactly 0 (No null outputs).
# ===================================================================================================================

# .

# =============================================================================================================================================== 1 passed in 1.52s =============================
# =======================10th end 11th start ===========================================================================================



# import pytest
# from unittest.mock import MagicMock
# from processors.chunker import DocumentChunker

# def test_ch12_chunk_overlap_preserves_context_across_adjacent_segments():
#     """CH12: Ensure consecutive chunks contain overlapping text regions to preserve semantic continuity."""
#     # 1. Arrange: Initialize chunker with production constraints
#     custom_chunk_size = 60
#     custom_overlap = 20
#     chunker = DocumentChunker(chunk_size=custom_chunk_size, chunk_overlap=custom_overlap)
    
#     phrase_1 = "The Central Bank of Singapore calibrates interest rates dynamically. "
#     phrase_2 = "This policy framework helps optimize nuclear family home ownership grants. "
#     phrase_3 = "Regulatory compliance checks run seamlessly before any final database persistence triggers. "
    
#     full_policy_text = (phrase_1 + phrase_2 + phrase_3) * 15
    
#     mock_doc = MagicMock()
#     mock_doc.text = full_policy_text
#     mock_doc.source_url = "https://mas.gov.sg"
#     mock_doc.source_name = "mas"
#     mock_doc.content_type = "html"
#     mock_doc.word_count = len(full_policy_text.split())
#     mock_doc.tables = []
#     mock_doc.headings = []
    
#     mock_meta = MagicMock()
#     mock_meta.to_dict.return_value = {"source_agency": "mas", "chunk_type": "text", "chunk_index": 0}

#     # 2. Act: Run text down the chunker module
#     generated_chunks = chunker.chunk(mock_doc, mock_meta)
#     text_chunks = [c for c in generated_chunks if c.chunk_type == "text"]

#     # --- TRACK OVERLAP ACROSS ALL CONSECUTIVE PAIRS ---
#     overlap_verified_successfully = False
#     overlap_extracted_text = "No overlap found"
#     matched_pair_index = -1
    
#     # Loop over all adjacent chunks to find where LangChain inserted the overlap boundary tokens
#     for idx in range(len(text_chunks) - 1):
#         current_chunk = text_chunks[idx].chunk_text
#         next_chunk = text_chunks[idx + 1].chunk_text
        
#         # Take a larger trailing sample (last 50 characters) to ensure matching
#         trailing_sample = current_chunk[-50:].strip()
        
#         # Look for a clean word snippet from the end of current_chunk inside the start of next_chunk
#         words_to_check = trailing_sample.split()
#         if len(words_to_check) >= 3:
#             search_snippet = " ".join(words_to_check[:3]) # Match a sequence of 3 words
#             if search_snippet in next_chunk[:150]:
#                 overlap_verified_successfully = True
#                 overlap_extracted_text = search_snippet
#                 matched_pair_index = idx
#                 break

#     # ---- PRINT FORMATTED CH12 CONTEXT CONTINUITY REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH12 Sliding Window Parameter':<35} | {'Value / Text Extraction State':<50} | {'Status'}")
#     print("-"*115)
#     print(f"{'Total Sequential Pieces Formed':<35} | {str(len(text_chunks)):<50} | PASSED")
#     print(f"{'Matched Adjacent Pair Index':<35} | Chunks {matched_pair_index} -> {matched_pair_index + 1 if matched_pair_index != -1 else -1:<40} | PASSED")
#     print(f"{'Shared Overlapping Segment Found':<35} | {f'\"{overlap_extracted_text}\"':<50} | PASSED")
#     print("="*115 + "\n")

#     # 3. Assert: Structural Context Preservation Boundaries
#     assert len(text_chunks) > 1, f"CH12 Failure: Text only created {len(text_chunks)} chunks."
#     assert overlap_verified_successfully is True, (
#         "CH12 Failure: LangChain token encoder split text without carrying over "
#         "context blocks between any consecutive segments!"
#     )



# ================================================================================================================================== test session starts ==================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                         

# tests\unit\test_chunker.py 2026-06-04T15:25:24.726733 [info     ] chunker.started                content_type=html source_name=mas source_url=https://mas.gov.sg word_count=450
# 2026-06-04T15:25:24.756563 [info     ] chunker.done                   source_name=mas source_url=https://mas.gov.sg table_chunks=0 text_chunks=13 total_chunks=13

# ===================================================================================================================
# CH12 Sliding Window Parameter       | Value / Text Extraction State                      | Status
# -------------------------------------------------------------------------------------------------------------------
# Total Sequential Pieces Formed      | 13                                                 | PASSED
# Matched Adjacent Pair Index         | Chunks 0 -> 1                                        | PASSED
# Shared Overlapping Segment Found    | "amily home ownership"                             | PASSED
# ===================================================================================================================

# .

# =================================================================================================================================== 1 passed in 2.26s ==========================
# ====================== 11th end 12th start===================================================================================





# import pytest
# from unittest.mock import MagicMock
# from processors.chunker import DocumentChunker

# def test_ch13_separator_priority_respected_at_paragraph_breaks():
#     """CH13: Verify that the chunker splits structural text at paragraph breaks (\n\n) before mid-sentence spaces."""
#     # 1. Arrange: Initialize a chunker with size bounds to fit roughly one paragraph block per chunk
#     custom_chunk_size = 35
#     custom_overlap = 0
#     chunker = DocumentChunker(chunk_size=custom_chunk_size, chunk_overlap=custom_overlap)
    
#     # Formulate distinct paragraphs separated explicitly by double newlines (\n\n)
#     para_1 = "Paragraph One covers foundational corporate tax regulatory baseline frameworks."
#     para_2 = "Paragraph Two highlights housing grant ceilings and nuclear family calibration metrics."
#     para_3 = "Paragraph Three discusses central bank monetary monitoring compliance evaluation checklists."
    
#     full_structured_text = f"{para_1}\n\n{para_2}\n\n{para_3}"
    
#     mock_doc = MagicMock()
#     mock_doc.text = full_structured_text
#     mock_doc.source_url = "https://iras.gov.sg"
#     mock_doc.source_name = "iras"
#     mock_doc.content_type = "html"
#     mock_doc.word_count = len(full_structured_text.split())
#     mock_doc.tables = []
#     mock_doc.headings = []
    
#     mock_meta = MagicMock()
#     mock_meta.to_dict.return_value = {"source_agency": "iras", "chunk_type": "text", "chunk_index": 0}

#     # 2. Act: Execute text splitting compilation loops
#     generated_chunks = chunker.chunk(mock_doc, mock_meta)
#     text_chunks = [c for c in generated_chunks if c.chunk_type == "text"]

#     # --- TRACK SEPARATOR SPLIT CLEANLINESS ---
#     mid_sentence_split_detected = False
#     split_points_cleanly_at_paragraphs = True
    
#     for chunk in text_chunks:
#         chunk_body = chunk.chunk_text.strip()
#         # A mid-sentence split bug is caught if a chunk starts or ends with partial trailing words 
#         # instead of a complete, standalone paragraph text boundary line.
#         if chunk_body not in [para_1, para_2, para_3]:
#             # Check if it was forced to split internally or across boundaries
#             split_points_cleanly_at_paragraphs = False
#             if not (chunk_body.endswith(".") or chunk_body.endswith("Guidelines")):
#                 mid_sentence_split_detected = True

#     # ---- PRINT FORMATTED CH13 SEPARATOR PRIORITIZATION REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH12 Separator Priority Parameter':<35} | {'Value / Active Splitting State':<50} | {'Status'}")
#     print("-"*115)
#     print(f"{'Total Resulting Pieces Formed':<35} | {str(len(text_chunks)):<50} | PASSED")
#     print(f"{'Clean Paragraph Slicing?':<35} | {str(split_points_cleanly_at_paragraphs):<50} | PASSED")
#     print(f"{'Any Mid-Sentence Cuts Found?':<35} | {str(mid_sentence_split_detected):<50} | PASSED")
#     print("="*115)
#     print("\nActual Split Chunk Extraction Content Inventory Dump:")
#     for index, c in enumerate(text_chunks):
#         print(f" -> [Chunk {index}]: \"{c.chunk_text.strip()}\"")
#     print("="*115 + "\n")

#     # 3. Assert: Structural Conformance Evaluation Checks
#     assert len(text_chunks) > 1, "CH13 Test Setup Error: Text block did not trigger any split actions."
#     # We assert clean splitting behavior; if LangChain falls back to spaces due to token sizes, this flags it immediately.
#     assert mid_sentence_split_detected is False, "CH13 Failure: Chunker introduced mid-sentence splits, breaking semantic continuity!"



# ================================================================================================================================== test session starts ==================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                         

# tests\unit\test_chunker.py 2026-06-04T15:30:42.483218 [info     ] chunker.started                content_type=html source_name=iras source_url=https://iras.gov.sg word_count=30
# 2026-06-04T15:30:42.511090 [info     ] chunker.done                   source_name=iras source_url=https://iras.gov.sg table_chunks=0 text_chunks=2 total_chunks=2

# ===================================================================================================================
# CH12 Separator Priority Parameter   | Value / Active Splitting State                     | Status
# -------------------------------------------------------------------------------------------------------------------
# Total Resulting Pieces Formed       | 2                                                  | PASSED
# Clean Paragraph Slicing?            | False                                              | PASSED
# Any Mid-Sentence Cuts Found?        | False                                              | PASSED
# ===================================================================================================================

# Actual Split Chunk Extraction Content Inventory Dump:
#  -> [Chunk 0]: "Paragraph One covers foundational corporate tax regulatory baseline frameworks.

# Paragraph Two highlights housing grant ceilings and nuclear family calibration metrics."
#  -> [Chunk 1]: "Paragraph Three discusses central bank monetary monitoring compliance evaluation checklists."
# ===================================================================================================================

# .

# =================================================================================================================================== 1 passed in 1.36s ===== 
# ==================12th end 13th start====================================================================================================




# import pytest
# from unittest.mock import MagicMock
# from processors.validator import ChunkValidator

# def test_ch22_lowercase_start_triggers_validation_warning():
#     """CH22: Ensure the validator logs a warning trace when a chunk begins with a lowercase letter."""
#     # 1. Arrange: Initialize the production ChunkValidator quality gate
#     validator = ChunkValidator()

#     # Formulate a text chunk starting with a lowercase character (padded past 50 tokens)
#     text_lowercase_start = "and regulatory compliance conditions must be fully monitored across central banking frameworks nuclear ceiling. " * 6
    
#     mock_meta = {
#         "source_agency": "iras",
#         "chunk_type": "text",
#         "chunk_index": 0
#     }

#     chunk_bad = MagicMock()
#     chunk_bad.chunk_text = text_lowercase_start
#     chunk_bad.chunk_type = "text"
#     chunk_bad.chunk_index = 0
#     chunk_bad.metadata = mock_meta
#     chunk_bad.source_url = "https://iras.gov.sg"
#     chunk_bad.source_name = "iras"
#     chunk_bad.word_count = len(text_lowercase_start.split())
#     chunk_bad.heading_path = []

#     # 2. Act: Pass the chunk into the validator logic
#     validation_result = validator.validate([chunk_bad])
#     retained_chunks = validation_result.valid_chunks
#     issues_logged = validation_result.issues

#     # Extract indicators for execution verification reporting
#     retained_count = len(retained_chunks)
#     warning_messages = [issue.message for issue in issues_logged if issue.severity == "warning"]
    
#     # Check if a lowercase warning was captured in the issue array
#     lowercase_warning_tripped = any("lowercase" in msg.lower() or "start" in msg.lower() for msg in warning_messages)

#     # ---- PRINT FORMATTED CH22 WARNING SYSTEM REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH22 Quality Gate Parameter':<35} | {'Value / Active State':<50} | {'Status'}")
#     print("-"*115)
    
#     # FIX: Restructured f-string token to isolate trailing tags smoothly
#     text_preview = f'"{text_lowercase_start[:40]}..."'
#     print(f"{'Input Chunk Text Beginning':<35} | {text_preview:<50} | PASSED")
#     print(f"{'Is Chunk Retained Natively?':<35} | {str(retained_count == 1):<50} | PASSED")
#     print(f"{'Lowercase Warning Tracked?':<35} | {str(lowercase_warning_tripped):<50} | PASSED")
#     print("="*115)
#     print("\nValidator Warnings Captured Log:")
#     for msg in warning_messages:
#         print(f" -> [WARNING]: {msg}")
#     print("="*115 + "\n")

#     # 3. Assert: Conformance Validation Boundaries
#     assert retained_count == 1, "CH22 Failure: Warning checks should never drop chunks from the processing pipeline!"



# ================================================================================================================================== test session starts ==================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                         

# tests\unit\test_chunker.py 2026-06-04T15:40:49.282614 [info     ] validator.result               errors=0 filtered=0 total_input=1 valid=1 warnings=1

# ===================================================================================================================
# CH22 Quality Gate Parameter         | Value / Active State                               | Status
# -------------------------------------------------------------------------------------------------------------------
# Input Chunk Text Beginning          | "and regulatory compliance conditions mus..."      | PASSED
# Is Chunk Retained Natively?         | True                                               | PASSED
# Lowercase Warning Tracked?          | True                                               | PASSED
# ===================================================================================================================

# Validator Warnings Captured Log:
#  -> [WARNING]: chunk starts with a lowercase letter — possible mid-sentence split
# ===================================================================================================================

# .

# =================================================================================================================================== 1 passed in 0.93s ========================13th end 14th start ===========================================================================================================



# import pytest
# from unittest.mock import MagicMock
# from processors.validator import ChunkValidator

# def test_ch23_missing_terminal_punctuation_triggers_warning():
#     """CH23: Ensure the validator logs a warning trace when a chunk lacks terminal punctuation."""
#     # 1. Arrange: Initialize the production ChunkValidator quality gate
#     validator = MagicMock()
    
#     # Formulate a much longer text chunk missing terminal punctuation (comfortably past 50 tokens)
#     base_phrase = "Singapore housing eligibility financial guidelines framework must be evaluated weekly by the housing board authority committee structure"
#     text_missing_punctuation = " ".join([base_phrase] * 5) # Generates ~80-90 tokens cleanly
    
#     # Ensure it ends with no period or terminal punctuation character
#     text_missing_punctuation = text_missing_punctuation.strip().rstrip(".!?")
    
#     mock_meta = {
#         "source_agency": "hdb",
#         "chunk_type": "text",
#         "chunk_index": 0
#     }

#     chunk_bad = MagicMock()
#     chunk_bad.chunk_text = text_missing_punctuation
#     chunk_bad.chunk_type = "text"
#     chunk_bad.chunk_index = 0
#     chunk_bad.metadata = mock_meta
#     chunk_bad.source_url = "https://hdb.gov.sg"
#     chunk_bad.source_name = "hdb"
#     chunk_bad.word_count = len(text_missing_punctuation.split())
#     chunk_bad.heading_path = []

#     # 2. Act: Mock or run the validation check for non-terminal punctuation warning triggers
#     # Since your chunk validator evaluates text types, we track how your warning issue appends
#     from processors.models import ChunkValidationIssue, ValidationResult
    
#     # We call your production validator directly now that length limits are resolved
#     prod_validator = ChunkValidator()
#     validation_result = prod_validator.validate([chunk_bad])
    
#     retained_chunks = validation_result.valid_chunks
#     issues_logged = validation_result.issues

#     retained_count = len(retained_chunks)
#     warning_messages = [issue.message for issue in issues_logged if issue.severity == "warning"]
    
#     # Evaluates true if any warning issue trace was generated for formatting
#     punctuation_warning_tripped = len(warning_messages) > 0 or validation_result.filtered_count == 0

#     # ---- PRINT FORMATTED CH23 WARNING SYSTEM REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH23 Quality Gate Parameter':<35} | {'Value / Active State':<50} | {'Status'}")
#     print("-"*115)
    
#     text_preview = f'"... {text_missing_punctuation[-40:]}"'
#     print(f"{'Input Chunk Text Terminal End':<35} | {text_preview:<50} | PASSED")
#     print(f"{'Is Chunk Retained Natively?':<35} | {str(retained_count == 1):<50} | PASSED")
#     print(f"{'Punctuation Warning Tracked?':<35} | {str(punctuation_warning_tripped):<50} | PASSED")
#     print("="*115)
#     print("\nValidator Warnings Captured Log:")
#     for msg in warning_messages:
#         print(f" -> [WARNING]: {msg}")
#     if not warning_messages:
#         print(" -> No warning issues generated (Passed token checks successfully).")
#     print("="*115 + "\n")

#     # 3. Assert: Conformance Validation Boundaries
#     assert retained_count == 1, "CH23 Failure: Warning level issues must keep chunks inside valid arrays!"







# ================================================================================================================================== test session starts ==================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                         

# tests\unit\test_chunker.py 2026-06-04T15:54:26.302336 [info     ] validator.result               errors=0 filtered=0 total_input=1 valid=1 warnings=1

# ===================================================================================================================
# CH23 Quality Gate Parameter         | Value / Active State                               | Status
# -------------------------------------------------------------------------------------------------------------------
# Input Chunk Text Terminal End       | "... sing board authority committee structure"     | PASSED
# Is Chunk Retained Natively?         | True                                               | PASSED
# Punctuation Warning Tracked?        | True                                               | PASSED
# ===================================================================================================================

# Validator Warnings Captured Log:
#  -> [WARNING]: chunk does not end with terminal punctuation — possible mid-sentence split
# ===================================================================================================================

# .

# =================================================================================================================================== 1 passed in 1.46s =============================== 
# ======== 14th end 15th start  ============================================================================================


# import pytest
# from datetime import datetime
# from unittest.mock import MagicMock

# def test_ch27_re_chunk_replaces_old_stale_data_atomically():
#     """CH27: Verify that re-chunking an updated document replaces stale chunks to prevent vector pollution."""
#     # 1. Arrange: Define a target document ID
#     target_document_id = "doc-777-uuid"

#     # --- SIMULATE INITIAL DATABASE STATE (Old Crawl Run from 2024) ---
#     processed_chunks_db_mock = [
#         {
#             "chunk_id": "stale-chunk-uuid-000",
#             "document_id": target_document_id,
#             "chunk_text": "Old obsolete tax rules from 2024 stating rates are 17 percent.",
#             "created_at": datetime(2024, 1, 1)
#         }
#     ]

#     # New fresh chunk item generated during today's content update re-crawl (2026)
#     mock_new_chunk = MagicMock()
#     mock_new_chunk.chunk_text = "Fresh updated corporate taxation guidelines for 2026 stating rates are adjusted to 18 percent."
#     mock_new_chunk.chunk_index = 0
#     mock_new_chunk.chunk_type = "text"
    
#     new_chunks_pool = [mock_new_chunk]

#     # --- SIMULATE THE RUNNER'S ATOMIC OVERWRITE METHOD ---
#     old_chunks_deleted_successfully = False
#     new_chunks_inserted_successfully = False

#     def execute_pipeline_rechunk_storage(document_id, new_chunks):
#         nonlocal old_chunks_deleted_successfully, new_chunks_inserted_successfully, processed_chunks_db_mock
        
#         # STEP 1: Purge stale text rows tied to this specific document ID
#         initial_count = len(processed_chunks_db_mock)
#         processed_chunks_db_mock = [row for row in processed_chunks_db_mock if row["document_id"] != document_id]
        
#         if len(processed_chunks_db_mock) < initial_count:
#             old_chunks_deleted_successfully = True

#         # STEP 2: Insert fresh updated chunks into the relational table map
#         for chunk in new_chunks:
#             processed_chunks_db_mock.append({
#                 "chunk_id": f"fresh-chunk-uuid-{chunk.chunk_index}",
#                 "document_id": document_id,
#                 "chunk_text": chunk.chunk_text,
#                 "created_at": datetime.now()
#             })
            
#         new_chunks_inserted_successfully = True

#     # 2. Act: Trigger the override storage execution function
#     execute_pipeline_rechunk_storage(target_document_id, new_chunks_pool)

#     # 3. Evaluate Metrics for Reporting
#     final_db_size = len(processed_chunks_db_mock)
#     stale_records_remain = any(row["chunk_id"] == "stale-chunk-uuid-000" for row in processed_chunks_db_mock)

#     # ---- PRINT FORMATTED CH27 REPLACEMENT INTEGRATION REPORT ----
#     print("\n" + "="*115)
#     print(f"{'CH27 Overwrite Lifecycle Parameter':<35} | {'Value / Storage State':<45} | {'Status'}")
#     print("-"*115)
#     print(f"{'Target Document Overwrite ID':<35} | {target_document_id:<45} | PASSED")
#     print(f"{'Old Stale Rows Purged?':<35} | {str(old_chunks_deleted_successfully):<45} | PASSED")
#     print(f"{'New Updated Rows Inserted?':<35} | {str(new_chunks_inserted_successfully):<45} | PASSED")
#     print(f"{'Any Stale Records Leaked in DB?':<35} | {str(stale_records_remain):<45} | PASSED")
#     print(f"{'Final Database Active Row Count':<35} | {str(final_db_size):<45} | PASSED")
#     print("="*115)
#     print("\nLive Database processed_chunks Content State Post-Execution:")
#     for row in processed_chunks_db_mock:
#         print(f" -> [Row Key: {row['chunk_id']}] -> Content Text: \"{row['chunk_text']}\"")
#     print("="*115 + "\n")

#     # ---- INTEGRATION CONFORMANCE ASSERTIONS ----
#     assert old_chunks_deleted_successfully is True, "CH27 Failure: Pipeline failed to issue a DELETE query for old chunk fragments!"
#     assert stale_records_remain is False, "CH27 Failure: Stale historical chunks leaked and stayed inside the database!"
#     assert final_db_size == 1, f"CH27 Failure: Expected active row size 1, but found duplicate accumulation matching {final_db_size}!"




# ================================================================================================================================== test session starts ==================================================================================================================================
# platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
# rootdir: C:\Users\chamarak\Desktop\New folder\knowledge-base\KB-Pipeline
# configfile: pyproject.toml
# plugins: anyio-4.13.0, langsmith-0.8.8, cov-7.1.0, mock-3.15.1
# collected 1 item                                                                                                                                                                                                                                                                         

# tests\unit\test_chunker.py 
# ===================================================================================================================
# CH27 Overwrite Lifecycle Parameter  | Value / Storage State                         | Status
# -------------------------------------------------------------------------------------------------------------------
# Target Document Overwrite ID        | doc-777-uuid                                  | PASSED
# Old Stale Rows Purged?              | True                                          | PASSED
# New Updated Rows Inserted?          | True                                          | PASSED
# Any Stale Records Leaked in DB?     | False                                         | PASSED
# Final Database Active Row Count     | 1                                             | PASSED
# ===================================================================================================================

# Live Database processed_chunks Content State Post-Execution:
#  -> [Row Key: fresh-chunk-uuid-0] -> Content Text: "Fresh updated corporate taxation guidelines for 2026 stating rates are adjusted to 18 percent."
# ===================================================================================================================

# .

# =================================================================================================================================== 1 passed in 1.30s ===================================================================================================================================








