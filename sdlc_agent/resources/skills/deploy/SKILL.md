---
name: deploy-release
description: Release a tested commit with health verification and rollback.
---

# deploy-release

Use the runtime deployment path, not an agent-invented shell command. Confirm the immutable workflow defines command, healthcheck and rollback. Execute only after test and review dependencies succeed and the operator enables deployment. Bind approval to the recorded commit and configuration digest. Persist intent before side effects. On failure execute rollback; on an uncertain outcome stop for reconciliation. Never silently retry an indeterminate deployment.
