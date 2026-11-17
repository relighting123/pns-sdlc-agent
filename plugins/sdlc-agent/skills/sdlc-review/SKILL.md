---
name: sdlc-review
description: Inspect a delivery run's independent review, acceptance-criteria evidence and verification logs before accepting the change.
---

Run `scripts/sdlc.mjs status --workspace <checkout> --run <id>` using the plugin path. Inspect `artifacts.review`, `checks`, and `verified`. Cite actual review evidence at file and line, preserve high-severity findings and coverage gaps, and report which commands actually ran. Use `resume` after a source change to rerun gates against the updated tree.
