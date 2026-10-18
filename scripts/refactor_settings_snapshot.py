"""Save the current settings as the refactor baseline.

Run this before touching ``config/settings``.  The output lands in the
untracked ``.refactor/settings/`` directory, so it never becomes part of a
commit.  Compare a new run with:

    python scripts/refactor_settings_compare.py
"""

import json
import sys

from refactor_settings import SNAPSHOT_DIR, capture_all, snapshot_path


def main():
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    captured = capture_all()
    manifest = {}
    for settings_module, output in captured.items():
        path = snapshot_path(settings_module)
        path.write_text(output, encoding="utf-8", newline="\n")
        manifest[settings_module] = str(path.relative_to(SNAPSHOT_DIR.parent.parent))
        print(f"saved {path}")
    (SNAPSHOT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
