# Wolfgang Amadeus Wolff

Pathology status: **resolved**

Typography reconstruction status: **active research**

Classification: `micro-contour-explosion`

Source SHA-256: `c0f35ff231fce489f688d9e0afddefbb7bc90ca5a77f1f4038f737999dd37eb4`

Semantic paths:

- `units/wolfgang-amadeus-wolff-1-1.svg`
- `units/reinf-wolfgang-amadeus-wolff-wulver-bounty-hunter-1-1.svg`

The two paths are exact duplicates.

## Diagnosis

The 1.175 MB source is almost entirely path data and contains about 19,140 closed subpaths, with the
majority represented by tiny distressed contours. This is qualitatively different from legitimate
subpixel lettering: the hard classifier detects the contour explosion itself.

## Preferred transformation

- Remove closed contours with span <= 0.1 SVG units.
- Apply exactly one Inkscape `path-simplify` pass to the 41 paths changed by pruning.
- Apply Scour.
- Render-compare at multiple sizes.

Repeated simplification was rejected because it visibly damaged the distressed lettering.

## Validated result

- Source: 1,175,564 bytes.
- Candidate: 233,209 bytes.
- Reduction: 80.16%.
- Closed contours removed: 13,795.
- 1200 px RGBA RMSE: 4.652896/255.
- Alpha error: zero.
- 1200 px changed pixels inside radius 480 px: zero.
- Final scanner result: hard pathology cleared; `subpixel-detail-heavy` advisory remains.

## Typography reconstruction research

The validated pruning/simplification pipeline resolves the `micro-contour-explosion` pathology and
remains the preferred fallback cleanup. It does not establish that the surviving distressed lettering is
the final authorial construction.

The fact that the 1200 px differences are confined to the outer lettering motivates a separate
reconstruction track. The working hypothesis is that the symbol may contain an underlying regular
font/layout plus deliberate distress, with additional contour noise introduced by expansion, tracing, or
export.

Research questions:

1. What is the literal text and exact layout of each lettering run?
2. Can the low-frequency glyph shapes identify a specific font family or close official variant?
3. Does that family include a distressed, grunge, stencil, or otherwise matching variant?
4. If the font is intrinsically clean, can the visible chips/scratches be represented as a compact
   separate mask/overlay rather than thousands of independent outline contours?
5. Do repeated glyphs converge on one underlying shape once micro-contours are ignored?

The preferred research/master candidate may retain semantic `<text>` elements so the recovered font,
tracking, baseline, and placement remain explicit. This repository must **not** add another text-to-path
stage: final path conversion is already handled by the downstream InfinityDB symbol pipeline.

Acceptance requires preserving deliberate typographic character. The goal is not to make Wolfgang's
lettering generically clean; it is to separate supported font construction and intentional distress from
incidental contour noise.
