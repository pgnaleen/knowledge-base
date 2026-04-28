"""
Validation Script - Reports quality statistics for processed chunks.
"""

from sqlalchemy import func
from config.database import SessionLocal
from config.models import ProcessedChunk, RawDocument, Source

def run_validation():
    db = SessionLocal()
    try:
        sources = db.query(Source).all()
        
        print("\n" + "="*60)
        print("  CHUNK QUALITY VALIDATION REPORT")
        print("="*60)
        
        for source in sources:
            print(f"\nSOURCE: {source.name} ({source.code})")
            
            # Count docs
            total_docs = db.query(RawDocument).filter(RawDocument.source_id == source.id).count()
            processed_docs = db.query(RawDocument).filter(RawDocument.source_id == source.id, RawDocument.status == 'processed').count()
            
            # Count chunks
            chunks = db.query(ProcessedChunk).join(RawDocument).filter(RawDocument.source_id == source.id).all()
            total_chunks = len(chunks)
            
            if total_chunks == 0:
                print(f"  Docs: {processed_docs}/{total_docs} processed")
                print("  Chunks: 0 (No data yet)")
                continue

            # Length stats
            lengths = [c.token_count for c in chunks]
            avg_len = sum(lengths) / total_chunks
            min_len = min(lengths)
            max_len = max(lengths)
            
            # Count invalid sizes (though pipeline now filters them, this checks existing data)
            too_small = sum(1 for l in lengths if l < 50)
            too_large = sum(1 for l in lengths if l > 600)

            print(f"  Docs: {processed_docs}/{total_docs} processed")
            print(f"  Total Chunks: {total_chunks}")
            print(f"  Avg Tokens:   {avg_len:.1f}")
            print(f"  Min/Max:      {min_len} / {max_len}")
            print(f"  Quality Flags:")
            print(f"    - Chunks < 50 tokens:  {too_small}")
            print(f"    - Chunks > 600 tokens: {too_large}")

        print("\n" + "="*60)
        
    finally:
        db.close()

if __name__ == "__main__":
    run_validation()
