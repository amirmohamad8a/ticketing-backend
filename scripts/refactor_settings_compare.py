"""Compare the current settings with the refactor baseline.

Exit codes:
    0  every settings module is unchanged
    1  at least one module changed (a unified diff is printed)
    2  the baseline is missing or incomplete
"""

import difflib
import sys

from refactor_settings import capture_all, snapshot_path


def main():
    current = capture_all()
    changed = False
    missing = []

    for settings_module, output in current.items():
        path = snapshot_path(settings_module)
        if not path.exists():
            missing.append(str(path))
            continue
        baseline = path.read_text(encoding="utf-8")
        if baseline == output:
            print(f"{settings_module}: no difference")
            continue
        changed = True
        print(f"{settings_module}: CHANGED")
        diff = difflib.unified_diff(
            baseline.splitlines(keepends=True),
            output.splitlines(keepends=True),
            fromfile=f"{settings_module} (snapshot)",
            tofile=f"{settings_module} (current)",
        )
        sys.stdout.writelines(diff)

    if missing:
        print("Missing snapshot files:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        print("Run scripts/refactor_settings_snapshot.py first.", file=sys.stderr)
        return 2
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
