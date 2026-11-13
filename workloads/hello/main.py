"""Hello workload: a greeting, then one JSON result line, exit 0."""
import json
import platform
import sys


def main() -> int:
    print("hello from a workload", flush=True)
    print(json.dumps({"workload": "hello", "ok": True, "python": platform.python_version()},
                     separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
