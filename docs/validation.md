# Validation policy

## Exact transforms

Exact transforms are accepted only when all configured Inkscape renders are pixel-identical in RGBA.
The source and candidate hashes, element/transform statistics, and renderer metadata must be recorded.

## Approximate reconstructions

Approximate reconstructions always remain `experimental-review-required` unless a case record explicitly
promotes them. Validation should include:

- at least 64, 128, 256, 512, 1024, and 1600 px where practical;
- RGBA and white-background metrics;
- alpha comparison;
- diff images;
- rescan of the resulting SVG;
- visual review of high-error regions, not only aggregate RMSE.

## Tooling constraints

Inkscape is the reference renderer for current experiments. Scour may be applied after a structural
transformation, but its contribution must be kept distinguishable from the structural change itself.

If Ruff, Pyright, or another local development tool is unavailable, validation records must say so rather
than implying it was run.

## Acceptance principle

The objective is the closest practical rendering with a dramatically simpler representation, not the
lowest byte count at any cost. A small increase in primitive count is preferable when it produces a
meaningful fidelity improvement. This is why the gradient-mask experiment uses one gray gradient plus
two differently angled accent gradients rather than forcing the accent disc into one gradient.
