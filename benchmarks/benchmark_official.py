import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from powerplant import optimize, parse_json_payload  # noqa: E402


def main() -> None:
    total_started = perf_counter()
    for path in sorted((ROOT / "example_payloads").glob("payload*.json")):
        problem = parse_json_payload(path.read_bytes())
        started = perf_counter()
        plan = optimize(problem)
        elapsed = perf_counter() - started
        encoded = json.dumps(plan, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()[:12]
        print(f"{path.name}: {elapsed:.6f}s sha256={digest}")
    print(f"total: {perf_counter() - total_started:.6f}s")


if __name__ == "__main__":
    main()
