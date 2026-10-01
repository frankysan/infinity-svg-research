# Roadmap

## Near term

1. Validate the Guijia-derived one-linear + two-radial-highlight interior model against all six unique
   flattened-gradient-mask source families before changing the production reconstruction.
2. Decompose and approximate the effective inner-disc edge stack separately from the interior field; do
   not recreate the original 44-circle export unless the visual evidence requires it.
3. Revisit the gray annulus with the same layer-decomposition method instead of assuming one fitted
   linear gradient is the final model.
4. Re-run the full gradient-mask batch after each accepted model change and record per-hash fidelity
   deltas.
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
