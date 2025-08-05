# Project Flowchart

This diagram summarises the main runtime path when a user asks a question or requests a chart.

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend (app.js)
    participant A as Flask API
    participant Q as QueryEngine
    participant DB as Database
    participant LLM as OpenRouter LLM
    participant C as Chart Generator
    U->>F: enter DB URI & question
    F->>A: POST /api/query or /api/chart
    A->>Q: ask(question)
    Q->>LLM: generate SQL
    LLM-->>Q: SQL text
    Q->>DB: execute SQL
    DB-->>Q: rows
    Q-->>A: answer, sql, data
    A->>F: JSON response
    F-->>U: display answer/data/chart
    Note over A,C: If /api/chart\nA calls generate_chart_spec\nto create Vega-Lite JSON
```

The API also uses a `DBEmbedder` to suggest relevant tables
based on the question. These suggestions are included in the `/api/query` response.

