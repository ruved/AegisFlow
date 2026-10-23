# Document Ingestion

The ingestion pipeline reads source documents, splits them into chunks,
generates embeddings, and stores vectors in a persistent vector database.
Each chunk retains its source filename and chunk identifier.
