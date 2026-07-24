#!/usr/bin/env python3
"""
0.6.0 ingestion for the RAG chatbot.

The repo's ingestion-service targets the old llama-stack 0.2.x `vector_dbs` +
`rag-tool/insert` API, which the 0.6.0 frontend does not read. This script does
the equivalent using the 0.6.0 OpenAI-compatible Files + Vector Stores API, so
documents show up in the UI (which lists `client.vector_stores`). Chunking and
embedding happen server-side (pypdf file_processor + sentence-transformers).

Usage:
    .client06-venv/bin/python ingest-0.6.0.py [BASE_URL] [DOCS_DIR]
Defaults: BASE_URL=http://localhost:8321, DOCS_DIR=RAG/notebooks
Each immediate sub-directory of DOCS_DIR becomes one vector store.
"""
import os
import sys
import time
from pathlib import Path
from llama_stack_client import LlamaStackClient

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8321"
DOCS_DIR = Path(sys.argv[2] if len(sys.argv) > 2 else
                Path(__file__).parent / "RAG" / "notebooks")
EMBEDDING_MODEL = "sentence-transformers/sentence-transformers/all-MiniLM-L6-v2"

client = LlamaStackClient(base_url=BASE_URL, timeout=600)


def ingest_category(name: str, pdfs: list[Path]) -> None:
    vs = client.vector_stores.create(
        name=name, extra_body={"embedding_model": EMBEDDING_MODEL})
    print(f"\n[{name}] vector_store {vs.id}  ({len(pdfs)} files)")
    for pdf in pdfs:
        # Filenames are sent as-is, diacritics included: the server-side
        # Content-Disposition bug that used to break non-latin-1 names is fixed
        # in the image (llamastack-local-image/patch-content-disposition.py).
        f = client.files.create(file=open(pdf, "rb"), purpose="assistants")
        client.vector_stores.files.create(vector_store_id=vs.id, file_id=f.id)
        # wait for chunking+embedding to finish
        for _ in range(120):
            st = client.vector_stores.files.retrieve(
                vector_store_id=vs.id, file_id=f.id)
            if st.status in ("completed", "failed"):
                break
            time.sleep(1)
        print(f"    {st.status:>9}  {pdf.name}")


def main() -> None:
    cats = sorted(d for d in DOCS_DIR.iterdir()
                  if d.is_dir() and any(d.glob("**/*.pdf")))
    if not cats:
        print(f"No PDF sub-directories under {DOCS_DIR}")
        sys.exit(1)
    for d in cats:
        ingest_category(d.name, sorted(d.glob("**/*.pdf")))
    stores = client.vector_stores.list()
    print("\nDone. Vector stores now available:")
    for s in stores.data:
        print(f"  - {s.name}  ({s.id})  files={s.file_counts.total}")


if __name__ == "__main__":
    main()
