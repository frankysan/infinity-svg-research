# Roadmap

## Near term

1. Finish the flattened-gradient-mask family by approximating the effective inner-disc edge stack with a
   compact representation. Keep the current three-gradient interior model unless evidence shows a better
   tradeoff.
2. Re-run the full gradient-mask batch after any edge-model change and record per-hash fidelity deltas.
3. Exercise the exact optimizer across the current raw corpus and promote case records only where
   pixel-identical validation is reproduced from the repository tooling.
4. Add reduced/synthetic fixtures for every hard pathology so detector contracts do not depend on the
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
