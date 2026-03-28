# Architecture Diagrams

This folder contains the source-of-truth and presentation-oriented architecture diagrams for the current LeninKart platform and deployment control plane.

## Files

- `leninkart-platform-architecture.puml`
- `leninkart-platform-architecture.png`
- `leninkart-platform-architecture-gui.drawio`
- `leninkart-platform-architecture-gui.svg`
- `leninkart-platform-architecture-gui.png`
- `leninkart-platform-runtime-deepdive-gui.drawio`
- `leninkart-platform-runtime-deepdive-gui.svg`
- `leninkart-platform-runtime-deepdive-gui.png`
- `deployment-flow.puml`
- `deployment-flow.png`
- `deployment-flow-gui.drawio`
- `deployment-flow-gui.svg`
- `deployment-flow-gui.png`
- `ARCHITECTURE_DIAGRAM_GUIDE.md`

## Diagram Scope

The diagrams intentionally reflect the currently implemented setup:

- Jira request input
- manual GitHub Actions dispatch
- Windows self-hosted runner
- `deployment-poc` orchestration and safety layer
- `leninkart-infra/dev` as the GitOps source of truth
- ArgoCD and the local `k3d-leninkart-dev` cluster
- LeninKart application services
- Kubernetes namespaces and support workloads
- Kafka and observability support
- `project-validation` as the proof layer

They do not depict unimplemented auto-trigger behavior from Jira.

## Source And Presentation Split

- The baseline `*.puml` and `*.png` files remain the architecture source of truth and original proof view.
- The `*-gui.*` files are polished presentation redraws based on those same baseline diagrams.
- The runtime deep-dive GUI diagram adds namespace- and workload-level detail from the live local runtime plus GitOps manifests.
- Use the baseline diagrams when you want the original documented structure.
- Use the GUI variants when you want recruiter-friendly, LinkedIn-ready, draw.io-style visuals.
