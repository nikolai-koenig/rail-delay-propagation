"""Unattended collectors for Network Rail TRUST and Darwin Push Port feeds.

Design principles:

- Raw first: messages are stored as received (wrapped in a small envelope),
  parsing happens later in the pipeline.
- Write before acknowledge: a message is flushed to disk before the broker is
  told it was received, so a crash causes duplicates rather than gaps.
  Duplicates are removed at compaction.
- Gaps are logged, never hidden.
"""
