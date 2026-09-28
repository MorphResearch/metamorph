# Tool-only interface contract

This common interface applies equally to F, U, and E* sessions in the local
experience-value harness. It describes capabilities, not a task solution.

- The current task is supplied in the task message. A task file is not
  guaranteed to exist.
- Use `list_dir` to discover direct names and types in `/memory` or `/work`.
  It never reads file contents. Empty directories report an empty list; a
  missing path, non-directory, path escape, or symlink is reported as an error.
- Use `read_file` only for a known logical file path. Use `write_file` only to
  create an optional artifact under `/memory` or `/work`.
- `query_sql` targets the local SQLite fixture. It accepts one read-only
  `SELECT` statement; semicolons and non-read-only statements are rejected.
  Normal schema discovery can use SQLite metadata queries.
- All file and SQL operations count as tool calls. Python, shell, eval,
  import, network, and arbitrary-code tools are unavailable.
- Saving an artifact is optional except in an explicitly labeled positive
  control. When a condition permits inheritance, the runner clones a frozen
  `/memory` snapshot into a fresh session; it never carries chat history.

This document deliberately contains no fixture table names, field mappings,
answer keys, or fixed solution sequence.
