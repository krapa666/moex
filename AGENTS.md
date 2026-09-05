# Repository working rules

## Project location

- The production working copy of this project is located at `/home/krapa/moex`.
- When giving server-side commands for this repository, use `/home/krapa/moex` as the default project path unless the user explicitly says otherwise.

## Delivery cadence

- Make changes in small, reviewable iterations.
- Publish changes frequently instead of accumulating large batches.
- Keep each pull request focused on one coherent change or a very small related set of changes.
- Prefer a sequence of small merged PRs over one large refactor.
- Do not mix unrelated infrastructure, backend, frontend, and documentation changes in the same iteration unless they are required for one feature to work.
- Preserve the currently working production path while iterating; avoid broad rewrites when a smaller safe change is sufficient.
- After each iteration, run the checks relevant to the files changed and publish the result before starting the next larger step.

## Current deployment direction

- Docker Compose is the supported deployment path.
- Host Nginx terminates TLS and proxies to the loopback-published Compose services.
- Do not reintroduce Minikube or Kubernetes deployment support unless explicitly requested.
