# Validation policy

Validation answers two different questions:

1. did the transformation preserve or recover the supported **authorial intent**; and
2. did it remove the structural pathology without introducing new technical problems?

Pixel identity is sufficient evidence for an exact transform, but it is not required for a representative
reconstruction.

## Exact transforms

Exact transforms are accepted only when all configured Inkscape renders are pixel-identical in RGBA.
The source and candidate hashes, element/transform statistics, and renderer metadata must be recorded.

## Representative reconstructions

Representative reconstructions remain `experimental-review-required` unless a case record explicitly
promotes them. Validation should include:

- the provenance evidence used to interpret the intended artwork;
- at least 64, 128, 256, 512, 1024, and 1600 px renders where practical;
- RGBA and white-background metrics;
- alpha comparison;
- diff images;
- rescan of the resulting SVG;
- visual review of high-error regions, not only aggregate RMSE;
- explicit review of silhouette, composition, identifying marks, palette, important gradients/shadows,
  and deliberate texture or asymmetry;
- a structural comparison explaining what complexity was removed and what meaningful primitives remain.

A candidate can be representative without being pixel-identical when the differences are attributable to
exporter artifacts, rasterization, trace noise, redundant blend constructions, or equivalent vector
semantics rather than a change in intended artwork.

## Fidelity and minimality

The objective is the simplest well-supported representation of the artwork, not the lowest byte count or
lowest element count at any cost.

When candidate A is simpler but candidate B adds only a small amount of meaningful structure and
materially improves representation of the source intent, prefer candidate B. The gradient-mask experiment
is a concrete example: one gray gradient plus two differently angled accent gradients is preferable to a
smaller construction when the additional accent gradient materially improves the intended shading while
still replacing dozens of flattened elements.

Numeric comparison is diagnostic evidence, not a universal acceptance threshold. Record both aggregate
metrics and spatial error distribution so high-contrast antialiasing edges are not confused with damage
to important artwork.

## Tooling constraints

Inkscape is the reference renderer for current experiments. Scour may be applied after a structural
transformation, but its contribution must be kept distinguishable from the structural change itself.

If Ruff, Pyright, or another local development tool is unavailable, validation records must say so rather
than implying it was run.
