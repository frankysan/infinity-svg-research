# Infinity SVG Research

Experimental tooling and research records for detecting, understanding, reconstructing, and validating
pathological SVG exports used by Infinity the Game assets.

This repository is deliberately separate from InfinityDB. InfinityDB consumes validated published
assets; this project owns the investigation methodology, experiments, provenance, and transformation
tooling used to decide whether an SVG can be safely simplified or reconstructed.

## Project principles

- **Fidelity first.** Byte reduction is useful only when the visual result is understood and reviewed.
- **Exact and approximate work stay separate.** Exact transforms require pixel-identical validation;
  approximate/restorative experiments are explicitly review-required.
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
```

Installed console entry points such as `infinity-svg-scan` and `infinity-svg-gradient-mask-batch` are
also available after `pip install -e .`.

## Repository layout

```text
src/infinity_svg_research/   implementation
tools/                       script-compatible CLI wrappers
tests/                       focused regression tests and synthetic fixtures
docs/                        methodology, taxonomy, validation, provenance
research/cases/              durable case records and decisions
research/reports/            compact source-hash/result summaries safe for Git
examples/                    provenance and historical-probe examples
```

## Current research state

The initial baseline is derived from scanner v8.6 and harness v8.9.4. The scanner covered 1,101 SVGs,
flagged 81 for at least one hard/advisory condition, found no parse errors, and identified 212 exact
duplicate groups.

Resolved/validated work includes the Trinitarians duplicate fill/stroke rewrite, Wolfgang micro-contour
pruning/simplification pipeline, and Ruby Monday blend-stack reconstruction. The flattened-gradient-mask
family has a compact three-gradient reconstruction that clears the hard classifier for all six unique
source hashes, but remains experimental because high-contrast inner-disc edge differences are still
being investigated.

See [`research/README.md`](research/README.md) and [`docs/research-log.md`](docs/research-log.md) for the
current status and evidence.

## Licensing and asset scope

Repository code is MIT-licensed. Corvus Belli artwork and trademarks are not covered by that license and
are intentionally excluded from this repository. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
