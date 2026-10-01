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
6. Generalize the reusable geometry/symmetry analysis demonstrated by Morat: common circle/arc fits,
   constant-width bands, supported intersections, and tangent-transition diagnostics. Keep these as
   advisory reconstruction tools rather than automatic rewrite rules.
7. Start the Wolfgang typography study: recover the literal lettering/layout, identify candidate fonts
   and distressed variants, and test clean semantic text plus a separate distress treatment where needed.
   Reuse InfinityDB's existing text-to-path publication stage rather than implementing one here.
8. Add reduced/synthetic fixtures for every hard pathology so detector contracts do not depend on the
   private/raw corpus.

## Medium term

- Investigate Druze/Taowu raster-heavy reconstruction separately.
- Resume palette-fragmented trace work with source-render-guided geometry reconstruction.
- Resolve the remaining missing-external-image cases, especially Kaeltar Specialists.
- Improve provenance tooling for historical first-party assets without treating second-party mirrors as
  authoritative.
- Add advisory tooling for rotational/reflection symmetry, common circle/arc fits, angular spacing, and
  constant-width curved bands. These tools should propose construction hypotheses, not rewrite geometry
  automatically.
- If the Wolfgang study proves reusable, add typography-analysis helpers for repeated glyph comparison,
  baseline/cap-height recovery, and font-candidate evaluation. Keep font identification advisory and
  evidence-driven rather than automatically replacing outlines.

## Release direction

The repository starts at `0.1.0`. A first tagged release should wait until the package layout and CLI
contracts are stable enough that experiments no longer depend on harness-ZIP versioning.
