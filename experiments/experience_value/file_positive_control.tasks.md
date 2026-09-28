# File positive control — pending task manifest

Status: **PENDING USER SIGNOFF; zero real provider requests.**

1. **PC-SOURCE** starts with empty memory. It is explicitly required to use
   actual SQLite tool feedback and save a record in `/memory`; neither the
   filename nor content format is prescribed.
2. **PC-MEMORY** starts in a fresh E* session from an independent clone of the
   PC-SOURCE frozen snapshot. It uses the common probe prompt, which asks it to
   discover files through `list_dir` before reading a relevant one if present.
3. **PC-EMPTY** uses the same new-session probe prompt, fixture, model
   configuration, and limits, but begins with empty memory.

The two probes never receive a source filename or content in their prompt.
They do not write back. If PC-SOURCE has no file, the positive control is
recorded as unmet; it is not repaired or rerun. These episodes are engineering
positive control only and cannot enter F/U research samples or primary analysis.
