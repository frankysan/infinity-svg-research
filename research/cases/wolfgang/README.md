# Wolfgang Amadeus Wolff

Status: **resolved**

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
