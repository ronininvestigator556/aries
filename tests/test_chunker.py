from aries.core.tokenizer import TokenEstimator
from aries.rag.chunker import TextChunker


def test_chunker_respects_overlap():
    chunker = TextChunker(
        chunk_size=5,
        chunk_overlap=2,
        token_estimator=TokenEstimator(mode="approx", approx_chars_per_token=1),
    )
    chunks = chunker.chunk("abcdefghij")
    assert chunks
    # Expect overlapping chunks: "abcde", "defgh", "ghij"
    assert chunks[0].content.startswith("a")
    assert chunks[1].content.startswith("d")
    # Overlap of 2 characters ("de") between first and second
    assert chunks[0].content[-2:] == chunks[1].content[:2]
    assert len(chunks) >= 2
