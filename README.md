# Infinity SVG Research

Experimental tooling and research records for detecting, understanding, reconstructing, and validating
pathological SVG exports used by Infinity the Game assets.

This repository is deliberately separate from InfinityDB. InfinityDB consumes validated published
assets; this project owns the investigation methodology, experiments, provenance, and transformation
tooling used to decide whether an SVG can be safely simplified or reconstructed.

## Project principles

- **Clean, minimal, representative.** The target is a compact, maintainable SVG that preserves
  authorial intent, not every pixel produced by a pathological exporter.
- **Authorial intent before byte count.** Silhouette, composition, identifying marks, palette, and
  meaningful shading take priority over absolute minimal element count or file size.
- **Recover construction, not export irregularity.** When the source supports simple geometric
  construction, prefer exact circles, regular spacing, reflection/rotational symmetry, and constructed
  arcs over small alignment or path irregularities introduced by export or tracing.
- **Small fidelity gains can justify small structural costs.** Minimality means removing accidental
  complexity, not choosing the fewest possible elements regardless of appearance.
- **Exact and representative work stay separate.** Exact transforms require pixel-identical validation;
  representative reconstructions are explicitly review-required until accepted.
- **Provenance is explicit.** First-party Corvus Belli sources are primary evidence; second-party sources
  such as Human Sphere renders and high-quality fan vectors are supporting evidence and remain identified
  as such.
- **Raw assets stay outside Git.** Source SVG/PDF/wiki archives and generated candidates are external
  inputs. Git tracks hashes, source identities, methodology, code, and compact result summaries.
- **Hard findings and advisories are different.** A hard pathology classification is not equivalent to
  a review signal such as subpixel detail or palette fragmentation.
- **No manufactured history.** The repository starts from the recovered v8.9.4 harness baseline.
  Earlier experiments are documented in the research log rather than recreated as fake commits.

## Setup

Python 3.11+ and Inkscape are expected. On Windows, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
```

Most render-validation workflows invoke `inkscape.com`/`inkscape` from `PATH`; pass `--inkscape` to
select another executable.

The scripts under `tools/` are thin wrappers around the package modules. For example:

```powershell
python .\tools\scan.py "C:\path\to\SYMBOLS snapshot" --json .\scan.json --csv .\scan.csv
python .\tools\gradient_mask_batch.py "C:\path\to\SYMBOLS snapshot" .\scan.json --scour --output-dir .\run
python .\tools\gradient_mask_batch.py "C:\path\to\SYMBOLS snapshot" .\scan.json --model decomposed --fit-gray-shadow --scour --output-dir .\decomposed-run
```

The decomposed gradient-mask model is experimental and always review-required. `--fit-gray-shadow` uses
the source render only to fit materially strong gray-mask crescents; weak cases retain the shared compact
shadow rather than overfitting raster/export noise.

Installed console entry points such as `infinity-svg-scan` and `infinity-svg-gradient-mask-batch` are
also available after `pip install -e .`.

## Repository layout

```text
src/infinity_svg_research/   implementation
tools/                       script-compatible CLI wrappers
tests/                       focused regression tests and synthetic fixtures
docs/                        design goals, methodology, taxonomy, validation, provenance
research/cases/              durable case records and decisions
research/reports/            compact source-hash/result summaries safe for Git
examples/                    provenance and historical-probe examples
```

## Current research state

The Vyo-first continuation adds a profile-aware Vyo/Army identity ledger and a separate metadata-only
viewport normalizer. The first run produced 544 candidates, verified unchanged drawing renders at
128 px, and recorded 15 reviewed source identities. See [`docs/vyo-workflow.md`](docs/vyo-workflow.md)
for commands, evidence, unresolved coverage, and the distinction between source reuse and publication.
The v2 sizing pass removes fixed root dimensions, preserves each viewBox, and verifies proportional
scaling in Chrome at multiple sizes and container shapes.

The initial baseline is derived from scanner v8.6 and harness v8.9.4. The scanner covered 1,101 SVGs,
flagged 81 for at least one hard/advisory condition, found no parse errors, and identified 212 exact
duplicate groups.

Resolved/validated work includes the Trinitarians duplicate fill/stroke rewrite, Wolfgang micro-contour
pruning/simplification pipeline, and Ruby Monday blend-stack reconstruction. The flattened-gradient-mask
family has a compact three-gradient reconstruction that clears the hard classifier for all six unique
source hashes, but remains experimental because high-contrast inner-disc edge differences are still
being investigated.

See [`docs/design-goals.md`](docs/design-goals.md),
[`docs/geometric-reconstruction.md`](docs/geometric-reconstruction.md),
[`docs/provenance.md`](docs/provenance.md), [`research/README.md`](research/README.md), and
[`docs/research-log.md`](docs/research-log.md) for the project criteria, reconstruction principles,
evidence policy, current status, and research history.

## Licensing and asset scope

Repository code is MIT-licensed. Corvus Belli artwork and trademarks are not covered by that license and
are intentionally excluded from this repository. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
