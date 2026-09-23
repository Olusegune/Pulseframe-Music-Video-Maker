# PULSEFRAME — Build Plan

Direct music into motion. Full PRD lives in `docs/PRD.md` (to be added).

## Locked decisions

| Area | Decision |
|---|---|
| Platforms | Windows + macOS desktop |
| Shell | Tauri 2 (Rust core) + React/TypeScript UI |
| Music intelligence | Python sidecar (PyInstaller per platform); heavy models downloaded on first use |
| Director Engine | OpenAI, Structured Outputs (strict JSON schema); model names in config, never code |
| Renderers | fal.ai (OpenAPI schemas auto-imported) + Kie.ai (curated manifests) |
| Analysis | Hybrid: `Auto / On this computer / Cloud`. Beats, sections, energy always local; separation + transcription local if hardware allows, else cloud. Consent before first upload |
| Project format | `.pulseframe` folder: `project.db` (SQLite WAL) + `assets/ proxies/ generations/ thumbnails/ cache/ exports/` |
| Secrets | OS keychain only; never in project files |
| Release | GitHub Actions matrix builds (.msi / universal .dmg); Apple notarization + Windows code signing |

## Three-layer render model

1. **Shot Contract** — provider-agnostic intent (Simple Mode edits this).
2. **Compiled Render Request** — `adapter.compile(contract, manifest)`: exact prompt, every param, reference bindings.
3. **Director Overrides** — per-field user pins; survive recompiles; conflicts flagged.

### Model Capability Manifests
Every model (video, image, lip-sync, upscale) has a versioned manifest: all inputs (types, limits,
defaults), typed reference slots (image/video/audio refs, first/last frame, subject/element refs,
in-prompt `@tag` syntax), capabilities, pricing formula, and semantic annotations mapping raw fields
to PULSEFRAME concepts. Director Mode renders its Renderer panel **entirely** from the manifest, so
every parameter of every model (Seedance, Kling, Veo, Happy Horse, …) is exposed. A signed remote
manifest feed adds new models without an app release. Raw JSON request view as escape hatch.

## Job persistence rules
- Job row committed **before** the provider call; provider request ID committed immediately after.
- Crash while `submitting` → state "may have been submitted": look up, else ask. Never auto-resubmit.
- On reopen: poll all in-flight jobs, download results, verify checksums.
- No billable retry without a user action.

## Milestones
- **M0 Spikes** — analysis accuracy on 20 songs; one fal + one Kie render with character ref; ffmpeg sync ≤ 1 frame; keychain round-trip.
- **M1 Foundation** — bundle, SQLite schema, assets, job model, provider interface, audio playback, timeline skeleton.
- **M2 Music Intelligence** — Song Map, lyric alignment, analysis reveal.
- **M3 Director Engine** — 3 concepts + hero frames, treatment, sequences, beat-snapped Shot Contracts.
- **M4 Generation** — manifests, fal + Kie adapters, router, queue, persistence, cost caps.
- **M5 Studio** — viewer, timeline, inspector, shot cards, Simple controls, regen, Ctrl+K Director Command.
- **M5b Director Mode** — workspaces, full Renderer panel + reference rack, pins.
- **M6 Review** — face-embedding consistency, vision checks, accent timing, Fix All.
- **M7 Export** — 16:9, 9:16, 1:1, Cinema.
- **M8 Hardening** — automated PRD §61 acceptance test incl. kill-mid-render and reboot.
