import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from infinity_svg_research.vyo_identity import main

if __name__ == "__main__":
    raise SystemExit(main())
