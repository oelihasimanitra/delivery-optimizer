"""Lance l'application sans installation : python run.py [serve|create-user|plan|benchmark] ..."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from deliveryopt.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
