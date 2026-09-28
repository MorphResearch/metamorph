# Atomic file-I/O control — pending task manifest

This two-episode engineering control is instruction-driven and is not an
autonomous-learning or F/U research sample.

1. **PC-WRITE** receives a fresh SQLite fixture with only `io_probe(payload)`.
   The fixture generates a fresh random, non-sensitive marker per run. The marker is
   absent from the prompt and workspace. The model must run the stated SQL and itself
   use `write_file` to save the returned marker under `/memory`.
2. **PC-READ** starts a fresh session from an independent clone only when the source
   actually saved that exact marker. It receives no database-query tool and no source
   filename, marker, or source conversation; it must discover via `list_dir`, read via
   `read_file`, and return the marker.

If the write condition fails, PC-READ is `BLOCKED_SOURCE_ARTIFACT`; no retry,
replacement file, or empty-read episode is permitted.
