"""Development artifacts live outside the installable extension folder."""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
WORK = Path(os.environ.get("METAMORPHOSIS_WORK_DIR", str(
    Path.home() / "Documents" / "Codex" / "MetaMorphosis-development" / "work"
))).expanduser().resolve()
WORK.mkdir(parents=True, exist_ok=True)
