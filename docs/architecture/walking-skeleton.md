# Walking skeleton

PR 3 establishes one replaceable, credential-free vertical slice:

```text
React intake
  → POST /api/runs
  → typed procurement case and request revision
  → sequenced run events
  → resumable SSE representation
  → operator activity view
  → generated requirements artifact download
```

The `InMemoryRunStore` is deliberately an adapter, not the product's durable
store. PR 4 replaces it with PostgreSQL, a transactional event journal, outbox,
and projections while preserving the HTTP response contracts exercised here.

The slice completes synchronously because its purpose is integration proof. The
Temporal runtime later turns the same visible lifecycle into durable parent and
child workflows.
