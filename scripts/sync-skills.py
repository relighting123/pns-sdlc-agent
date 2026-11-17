from pathlib import Path
import shutil
root = Path(__file__).resolve().parents[1]
for host in ("codex", "claude"):
    target = root / "plugins" / host / "skills"
    shutil.rmtree(target)
    shutil.copytree(root / "skills", target)
