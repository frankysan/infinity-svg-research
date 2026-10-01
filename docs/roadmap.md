# Roadmap

## Near term

1. Run the new decomposed gradient-mask model against all six unique raw source hashes with gray-shadow
   fitting enabled and record per-family manifests/renders.
2. Review any strong fitted gray-mask crescent as a provenance question rather than automatically
   preserving it; Gecko specifically needs an independent first-party appearance reference if possible.
3. Compare the raw six-family batch against the legacy three-gradient baseline and promote the new model
   to the default only if the family-wide results support it.
4. Exercise the exact optimizer across the current raw corpus and promote case records only where
   pixel-identical validation is reproduced from the repository tooling.
5. Add reduced/synthetic fixtures for every hard pathology so detector contracts do not depend on the
   private/raw corpus.

## Medium term

- Investigate Druze/Taowu raster-heavy reconstruction separately.
- Resume palette-fragmented trace work with source-render-guided geometry reconstruction.
- Resolve the remaining missing-external-image cases, especially Kaeltar Specialists.
- Improve provenance tooling for historical first-party assets without treating second-party mirrors as
  authoritative.

## Release direction

The repository starts at `0.1.0`. A first tagged release should wait until the package layout and CLI
contracts are stable enough that experiments no longer depend on harness-ZIP versioning.
