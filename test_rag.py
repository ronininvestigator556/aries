"""Test script for RAG indexing and retrieval."""
import asyncio
from pathlib import Path
from aries.config import load_config
from aries.core.ollama_client import OllamaClient
from aries.rag.indexer import Indexer
from aries.rag.retriever import Retriever


async def test_indexing():
    """Test RAG indexing."""
    print("=" * 60)
    print("TESTING RAG INDEXING")
    print("=" * 60)

    # Load config
    config_path = Path("config.yaml")
    config = load_config(config_path if config_path.exists() else None)

    # Create clients
    ollama = OllamaClient(config.ollama)
    indexer = Indexer(config.rag, ollama)

    # Check Ollama connection
    print("\n1. Checking Ollama connection...")
    if not await ollama.is_available():
        print("   ❌ FAILED: Cannot connect to Ollama")
        print("   Make sure Ollama is running: ollama serve")
        return False
    print("   ✓ Ollama is available")

    # Check if embedding model exists
    print(f"\n2. Checking embedding model '{config.ollama.embedding_model}'...")
    if not await ollama.model_exists(config.ollama.embedding_model):
        print(f"   ⚠️  Model not found. Attempting to pull...")
        print(f"   This may take a few minutes...")
        try:
            async for progress in ollama.pull_model(config.ollama.embedding_model):
                if "status" in progress:
                    print(f"   {progress['status']}", end="\r")
            print("\n   ✓ Model pulled successfully")
        except Exception as e:
            print(f"\n   ❌ FAILED to pull model: {e}")
            return False
    else:
        print("   ✓ Embedding model is available")

    # Index test documents
    print("\n3. Indexing test documents...")
    test_dir = Path("test_docs")
    if not test_dir.exists():
        print(f"   ❌ FAILED: Test directory '{test_dir}' not found")
        return False

    try:
        result = await indexer.index_directory(
            path=test_dir,
            name="test_index",
            force=True  # Overwrite if exists
        )
        print(f"   ✓ Indexed {result['documents_indexed']} documents")
        print(f"   ✓ Index name: {result['name']}")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    # List indices
    print("\n4. Listing available indices...")
    try:
        indices = indexer.list_indices()
        print(f"   ✓ Found {len(indices)} index(es):")
        for idx in indices:
            print(f"     - {idx}")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False

    return True


async def test_retrieval():
    """Test RAG retrieval."""
    print("\n" + "=" * 60)
    print("TESTING RAG RETRIEVAL")
    print("=" * 60)

    # Load config
    config_path = Path("config.yaml")
    config = load_config(config_path if config_path.exists() else None)

    # Create clients
    ollama = OllamaClient(config.ollama)
    retriever = Retriever(config.rag, ollama)

    # Load index
    print("\n1. Loading 'test_index'...")
    try:
        await retriever.load_index("test_index")
        print("   ✓ Index loaded successfully")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False

    # Test retrieval with different queries
    queries = [
        "What is machine learning?",
        "Tell me about Python programming",
        "What are the challenges with large language models?",
    ]

    print("\n2. Testing retrieval with sample queries...")
    for i, query in enumerate(queries, 1):
        print(f"\n   Query {i}: '{query}'")
        try:
            chunks = await retriever.retrieve(query, top_k=2)
            if chunks:
                print(f"   ✓ Retrieved {len(chunks)} chunk(s):")
                for j, chunk in enumerate(chunks, 1):
                    print(f"     [{j}] Score: {chunk.score:.3f} | Source: {chunk.source}")
                    preview = chunk.content[:100].replace('\n', ' ')
                    print(f"         Preview: {preview}...")
            else:
                print("   ⚠️  No chunks retrieved")
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            return False

    return True


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("ARIES PHASE 2 RAG TESTING")
    print("=" * 60)

    # Test indexing
    indexing_success = await test_indexing()

    if indexing_success:
        # Test retrieval
        retrieval_success = await test_retrieval()

        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Indexing: {'✓ PASSED' if indexing_success else '❌ FAILED'}")
        print(f"Retrieval: {'✓ PASSED' if retrieval_success else '❌ FAILED'}")
        print("=" * 60)

        if indexing_success and retrieval_success:
            print("\n✓ All RAG tests PASSED!")
            return 0

    print("\n❌ Some tests FAILED")
    return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
