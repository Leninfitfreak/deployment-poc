# Architecture Diagram Guide

The baseline source-of-truth diagrams remain:

- `leninkart-platform-architecture.puml` / `leninkart-platform-architecture.png`
- `deployment-flow.puml` / `deployment-flow.png`

The polished GUI variants are presentation-focused redraws of the same architecture:

- `leninkart-platform-architecture-gui.drawio` / `.svg` / `.png`
- `deployment-flow-gui.drawio` / `.svg` / `.png`

The deeper runtime companion view extends the current GUI style with namespace- and workload-level detail discovered from the live local runtime plus GitOps manifests:

- `leninkart-platform-runtime-deepdive-gui.drawio` / `.svg` / `.png`

Use the files this way:

- baseline diagrams: original proof view and canonical high-level content
- GUI overview diagrams: recruiter-friendly, portfolio-friendly platform story
- runtime deep-dive diagram: senior-engineer walkthrough of namespaces, workloads, support services, and external runtime boundaries
