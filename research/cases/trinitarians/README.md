# Trinitarians

Status: **resolved**

Classification: `duplicate-fill-stroke-geometry`

Path: `units/trinitarians-1-1.svg`

## Evidence

- Source size: 69,161 bytes in scanner v8.6.
- 98 paths.
- 47 exact fill/stroke geometry pairs.
- About 30,638 bytes duplicated path data.

The rewrite merged the systematic duplicate geometry and rendered pixel-identically in the research
experiment. This became an exact transform in `transforms.py`.

The implementation deliberately uses the scanner gate (>=8 pairs and >=4,000 duplicated path-data
bytes), so isolated two-pair cases such as Qishi are reported but not rewritten.
