# Pecko

<!-- impeccable:product-schema 1 -->

## Platform
web

## Purpose and audience
Pecko is an offline, CPU-only conversational-stack project by Team Plumbers for HackNEX 2026, HNX26EPS08. This local frontend lets an evaluator try existing text routing, listen to committed voice samples, inspect component measurements, and understand the pipeline.

## Stack
The existing application is Python. The presentation uses HTML, CSS, JavaScript and a local standard-library Python server; this implementation choice follows the user's instruction to make do with the repository. No JavaScript build step or runtime CDN is required.

## Evidence and constraints
- Brain has an implemented intent router and a llama.cpp client. Freeform answers require a separately running local model server.
- Four committed Brain bake-offs measure components in an Ubuntu VM under a 2 CPU / 2 GB cgroup. Network was not disabled; quality scores remain pending.
- Voice has real Windows component measurements and seven recorded WAV samples.
- Spine has portable runtime and synthetic fixture evidence. Its placeholder runs are not end-to-end voice measurements.
- Ears and mobile are specifications. No microphone transcription or completed voice loop is claimed here.
- Models are absent from the checkout. Resource budgets are targets, not live telemetry.
- Every measurement needs a source and environment label. No invented improvement, accuracy, or resource use.

## Brand
Pecko. A voice assistant that thinks while you talk. Design guidance requested by the user: pbakaus/impeccable.
