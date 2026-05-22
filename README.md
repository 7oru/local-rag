# local-rag

`local-rag` is a local-first reference implementation for Field Deployment Engineers
building enterprise knowledge-base RAG demos and proofs of concept.

The project is designed around a simple loop:

```text
Markdown / Obsidian vault
  -> ingestion
  -> chunking
  -> embeddings
  -> Postgres + pgvector
  -> retrieval
  -> cited answers
  -> agent tools
```

## Documents

- [MVP Scope](docs/mvp.md)
- [MVP Subtasks](docs/mvp-subtasks.md)
- [Roadmap to Full Release](docs/roadmap-to-full-release.md)
