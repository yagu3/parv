"""Simple RAG — search knowledge/ folder, find relevant chunks, inject into prompt."""
import os, re
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
KNOWLEDGE_DIR = ROOT / "knowledge"

def _tokenize(text):
    """Simple word tokenizer."""
    return set(re.findall(r'\w{3,}', text.lower()))

def _load_chunks(max_chunk=300):
    """Load all text files from knowledge/ as chunks."""
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    chunks = []
    for ext in ['*.txt', '*.md']:
        for f in KNOWLEDGE_DIR.glob(ext):
            try:
                text = f.read_text('utf-8', errors='replace')
                # Split into paragraphs
                paras = [p.strip() for p in text.split('\n\n') if p.strip()]
                for p in paras:
                    if len(p) > 20:  # Skip tiny fragments
                        chunks.append({
                            "text": p[:max_chunk],
                            "source": f.name,
                            "tokens": _tokenize(p[:max_chunk])
                        })
            except: pass
    return chunks

def search(query, top_n=3, min_score=2):
    """Find top_n most relevant chunks for the query.
    Uses simple keyword overlap scoring (no external libs needed).
    Returns list of {text, source, score}."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    chunks = _load_chunks()
    if not chunks:
        return []

    scored = []
    for chunk in chunks:
        # Score = number of matching words
        overlap = query_tokens & chunk["tokens"]
        score = len(overlap)
        if score >= min_score:
            scored.append({
                "text": chunk["text"],
                "source": chunk["source"],
                "score": score
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]

def context_for(query, max_chars=500):
    """Build a context string from relevant knowledge chunks."""
    results = search(query, top_n=3)
    if not results:
        return ""
    parts = ["KNOWLEDGE (from your files):"]
    used = 0
    for r in results:
        snippet = r["text"][:200]
        if used + len(snippet) > max_chars:
            break
        parts.append(f"[{r['source']}] {snippet}")
        used += len(snippet)
    return "\n".join(parts)
