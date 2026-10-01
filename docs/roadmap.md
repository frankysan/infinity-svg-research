# Roadmap

## Near term

1. Re-run all six unique raw gradient-mask families with the concentric-circle model and record both
   normal full-image metrics and an edge-excluded representative-fidelity metric.
2. Review the concentric candidates visually at native/vector scale and normal UI sizes; do not tune the
   principal circle geometry to reproduce the rejected swept rim artifact.
3. Review any strong fitted gray-mask crescent as a provenance question rather than automatically
   preserving it; Gecko specifically needs an independent first-party appearance reference if possible.
4. Compare the concentric six-family result against both the validated decomposed-rim batch and the legacy
   three-gradient baseline before promoting a default reconstruction model.
5. Exercise the exact optimizer across the current raw corpus and promote case records only where
   pixel-identical validation is reproduced from the repository tooling.
6. Add reduced/synthetic fixtures for every hard pathology so detector contracts do not depend on the
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
