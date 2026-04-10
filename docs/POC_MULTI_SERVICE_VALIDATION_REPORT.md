# POC Multi-Service Validation Report

## Executive Summary

`deployment-poc` now has live, end-to-end validation coverage for all three LeninKart dev deployable services:

- `frontend`
- `product-service`
- `order-service`

All three services were validated through the real chain:

Jira ticket -> GitHub Actions -> self-hosted runner -> `deployment-poc` orchestration -> `leninkart-infra/main` -> ArgoCD -> `Synced` + `Healthy`

## Discovery Summary

### Already Supported Before This Validation

- `config/projects.yaml` already allowed all three LeninKart apps
- `config/app_mapping.yaml` already contained real GitOps values paths for:
  - `applications/frontend/helm/values-dev.yaml`
  - `applications/product-service/helm/values-dev.yaml`
  - `applications/order-service/helm/values-dev.yaml`
- ArgoCD application mappings were already correct:
  - `frontend-dev`
  - `dev-product-service`
  - `dev-order-service`
- target resolution, GitOps update logic, ArgoCD revision verification, locking, and state handling were already generic enough to support multiple apps

### Missing Pieces Added Safely

- Added Jira-friendly backend version aliases in [app_mapping.yaml](/D:/Projects/Services/deployment-poc/config/app_mapping.yaml):
  - `product-service`: `v1 -> 23599211809`, `v2 -> 23599512382`
  - `order-service`: `v1 -> 23599211965`, `v2 -> 23599512459`
- Enhanced the Jira test-ticket helper to write a reusable artifact:
  - `artifacts/jira-ticket.json`
  - `artifacts/jira-ticket.md`
- Updated the Jira ticket creation workflow to upload that artifact cleanly

No orchestrator redesign was required.

## Service-by-Service Results

| Service | Ticket(s) | Requested Version(s) | Resolved Version(s) | GitOps File | ArgoCD App | Final Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| frontend | `SCRUM-8` | `v2` | `23599512080` | `applications/frontend/helm/values-dev.yaml` | `frontend-dev` | `PASS` |
| product-service | `SCRUM-9`, `SCRUM-10` | `v1`, `v2` | `23599211809`, `23599512382` | `applications/product-service/helm/values-dev.yaml` | `dev-product-service` | `PASS` |
| order-service | `SCRUM-11`, `SCRUM-12` | `v1`, `v2` | `23599211965`, `23599512459` | `applications/order-service/helm/values-dev.yaml` | `dev-order-service` | `PASS` |

## Detailed Validation Evidence

### Frontend

- Jira ticket: `SCRUM-8`
- Create-ticket workflow: [#3](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23655047868)
- Deploy workflow: [#19](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23655093827)
- Requested version: `v2`
- Resolved deployable version: `23599512080`
- GitOps file: `applications/frontend/helm/values-dev.yaml`
- GitOps commit used: `a5530ce5dccff30803b262516d8e66edc0022040`
- ArgoCD app: `frontend-dev`
- Final Sync: `Synced`
- Final Health: `Healthy`
- Final action: `already_deployed`
- Notes:
  - Frontend remained on the already-live version
  - The rerun-safe/idempotent path is confirmed

### Product-Service

#### Validation Deploy To v1

- Jira ticket: `SCRUM-9`
- Create-ticket workflow: [#4](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23655151081)
- Deploy workflow: [#20](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23655198776)
- Requested version: `v1`
- Resolved deployable version: `23599211809`
- GitOps commit: `9eb1cbb728c5506ecd53915d5b12cbec343a0aa6`
- ArgoCD app: `dev-product-service`
- Final Sync: `Synced`
- Final Health: `Healthy`
- Final action: `deployed`

#### Duplicate / Rerun Check

- Jira ticket reused: `SCRUM-9`
- Deploy workflow: [#21](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23655477850)
- Final action: `already_deployed`
- Result: duplicate rerun exited cleanly without creating another GitOps change

#### Restore To Current v2

- Jira ticket: `SCRUM-10`
- Create-ticket workflow: [#5](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23655533836)
- Deploy workflow: [#22](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23655579078)
- Requested version: `v2`
- Resolved deployable version: `23599512382`
- GitOps commit: `77ebf70074222437bbb5bfce8e58bc443f1494b4`
- ArgoCD app: `dev-product-service`
- Final Sync: `Synced`
- Final Health: `Healthy`
- Final action: `deployed`

### Order-Service

#### Validation Deploy To v1

- Jira ticket: `SCRUM-11`
- Create-ticket workflow: [#6](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23655724581)
- Deploy workflow: [#23](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23655768863)
- Requested version: `v1`
- Resolved deployable version: `23599211965`
- GitOps commit: `f76465690599c855bff48de07f79f9b05e23e3e8`
- ArgoCD app: `dev-order-service`
- Final Sync: `Synced`
- Final Health: `Healthy`
- Final action: `deployed`

#### Duplicate / Rerun Check

- Jira ticket reused: `SCRUM-11`
- Deploy workflow: [#24](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23655993773)
- Final action: `already_deployed`
- Result: duplicate rerun exited cleanly without creating another GitOps change

#### Restore To Current v2

- Jira ticket: `SCRUM-12`
- Create-ticket workflow: [#7](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23656049755)
- Deploy workflow: [#25](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23656090777)
- Requested version: `v2`
- Resolved deployable version: `23599512459`
- GitOps commit: `4442f25bbd7de543abf59ca9e32c7f358232f938`
- ArgoCD app: `dev-order-service`
- Final Sync: `Synced`
- Final Health: `Healthy`
- Final action: `deployed`

## Hardening Layer Validation

The production-hardening layer remained intact during multi-service testing:

- state tracking now contains isolated entries for:
  - `leninkart/frontend`
  - `leninkart/product-service`
  - `leninkart/order-service`
- deployment locks were acquired and released independently per service/environment
- rerunning a ticket for an already deployed backend version returned `already_deployed`
- exact ArgoCD revision verification succeeded for every service run
- rollback scaffolding remains available, while this validation used explicit restore tickets instead of forcing rollback mode

## Final Live State After Validation

- frontend
  - version: `23599512080`
  - ArgoCD app: `frontend-dev`
- product-service
  - version: `23599512382`
  - ArgoCD app: `dev-product-service`
- order-service
  - version: `23599512459`
  - ArgoCD app: `dev-order-service`

All three apps are currently `Synced` and `Healthy`.

Important GitOps nuance:

- exact revision verification was performed successfully at the time of each individual deployment run
- after later `leninkart-infra/main` commits for other services, ArgoCD naturally advanced each app's reported branch-head
  revision to the latest repo commit
- at the end of this validation window, the current live ArgoCD `status.sync.revision` for all three apps is:
  `4442f25bbd7de543abf59ca9e32c7f358232f938`

That final shared revision does not mean all three services were redeployed to the same image tag. The actual service image
tags above remained correct and were rechecked directly from the live GitOps values files.

## Final Verdict

1. Is frontend fully working end-to-end? `YES`
2. Is order-service fully working end-to-end? `YES`
3. Is product-service fully working end-to-end? `YES`
4. What exact fixes were needed?
   - backend `v1`/`v2` version aliases in config
   - Jira test-ticket artifact output for cleaner validation
5. What remains unsupported?
   - No service-specific deployment gap remains for the current LeninKart dev scope

## Optional Project-Validation Handoff

The next GUI proof extension for `project-validation` should later add deployment screenshots for:

- frontend ticket `SCRUM-8` / deploy run `#19`
- product-service tickets `SCRUM-9` and `SCRUM-10` / deploy runs `#20`, `#21`, `#22`
- order-service tickets `SCRUM-11` and `SCRUM-12` / deploy runs `#23`, `#24`, `#25`

Recommended proof pages:

- Jira ticket page
- GitHub Actions run summary
- GitOps commit page in `leninkart-infra`
- ArgoCD application detail page with final revision

