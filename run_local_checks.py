"""Выполняет unittest и сохраняет подлинный вывод/JSON результатов в evidence/."""

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parent


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({"test": test.id(), "status": "passed"})

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({"test": test.id(), "status": "error", "exception": err[0].__name__})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({"test": test.id(), "status": "failed", "exception": err[0].__name__})


class Tee:
    def __init__(self, first, second):
        self.first, self.second = first, second

    def write(self, text):
        self.first.write(text)
        self.second.write(text)

    def flush(self):
        self.first.flush()
        self.second.flush()


def main() -> int:
    import os
    os.chdir(ROOT)
    evidence = ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    versions = {package: version(package) for package in ("python-telegram-bot", "aiohttp", "python-dotenv", "httpx")}
    with (evidence / "test_output.txt").open("w", encoding="utf-8") as output:
        tee = Tee(sys.stdout, output)
        tee.write("LOCAL TEST RUN — SYNTHETIC FIXTURES; NO TELEGRAM DELIVERY\n")
        tee.write(f"Python {platform.python_version()}\n")
        tee.write(json.dumps(versions, ensure_ascii=False) + "\n\n")
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
        result = unittest.TextTestRunner(stream=tee, verbosity=2, resultclass=EvidenceResult).run(suite)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "actual_local_test_execution_with_synthetic_fixtures",
        "live_telegram": False, "live_external_apis": False, "live_hosting": False,
        "python": platform.python_version(), "dependencies": versions,
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "success": result.wasSuccessful(), "tests": result.records,
        "fixtures_sha256": hashlib.sha256((ROOT / "tests/fixtures/api_responses.json").read_bytes()).hexdigest(),
        "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(ROOT.glob("*.py"))},
    }
    (evidence / "test_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
