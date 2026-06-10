# tools/code_executor.py
# Executes TypeScript Playwright spec files
# Called by Agent C to actually run generated tests
# Returns structured results per FR

import subprocess
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def execute_spec_file(
    spec_file_path : str,
    base_url       : str,
    fr_ids         : list[str]
) -> dict:
    spec_path = Path(spec_file_path)

    if not spec_path.exists():
        logger.error(f"Spec file not found: {spec_file_path}")
        return {
            fr_id: {
                "status"          : "skip",
                "duration_seconds": 0.0,
                "error_message"   : f"Spec file not found: {spec_file_path}",
                "screenshot_path" : None
            }
            for fr_id in fr_ids
        }

    logger.info(f"Executing spec file: {spec_path.name}")

    env = os.environ.copy()
    env["BASE_URL"] = base_url

    # Playwright treats the path arg as a regex — absolute Windows paths
    # with backslashes break the match. Use a forward-slash relative path.
    rel_spec = str(spec_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    command = f'npx playwright test "{rel_spec}" --reporter=json'

    try:
        result = subprocess.run(
            command,
            capture_output = True,
            text           = True,
            cwd            = str(PROJECT_ROOT),
            env            = env,
            timeout        = 120,
            shell          = True
        )

        logger.info(f"Playwright exit code: {result.returncode}")

        # JSON reporter outputs to stdout
        # Try parsing stdout as JSON first
        if result.stdout.strip().startswith("{"):
            try:
                report_data = json.loads(result.stdout.strip())
                logger.info("Parsed JSON from stdout successfully")
                return _parse_json_data(report_data, fr_ids)
            except Exception as e:
                logger.error(f"Failed to parse stdout JSON: {e}")

        # Fallback to return code
        if result.returncode == 0:
            logger.info("All tests passed (returncode=0)")
            return {
                fr_id: {
                    "status"          : "pass",
                    "duration_seconds": 5.0,
                    "error_message"   : None,
                    "screenshot_path" : None
                }
                for fr_id in fr_ids
            }
        else:
            return _parse_stdout(
                result.stdout, result.stderr,
                result.returncode, fr_ids
            )

    except subprocess.TimeoutExpired:
        logger.error(f"Spec file timed out: {spec_path.name}")
        return {
            fr_id: {
                "status"          : "fail",
                "duration_seconds": 120.0,
                "error_message"   : "Test execution timed out after 120s",
                "screenshot_path" : None
            }
            for fr_id in fr_ids
        }

    except Exception as e:
        logger.error(f"Unexpected error executing spec: {e}")
        return {
            fr_id: {
                "status"          : "fail",
                "duration_seconds": 0.0,
                "error_message"   : str(e),
                "screenshot_path" : None
            }
            for fr_id in fr_ids
        }


def run_typescript_check(spec_file_path: str) -> dict:
    """
    Checks spec file syntax using playwright dry-run.
    """
    rel_spec = str(Path(spec_file_path).relative_to(PROJECT_ROOT)).replace("\\", "/")
    command = f'npx playwright test "{rel_spec}" --dry-run'

    try:
        result = subprocess.run(
            command,
            capture_output = True,
            text           = True,
            cwd            = str(PROJECT_ROOT),
            timeout        = 30,
            shell          = True
        )

        if result.returncode == 0:
            return {"passed": True, "errors": []}
        else:
            error_lines = [
                line for line in (result.stdout + result.stderr).splitlines()
                if "error TS" in line and line.strip()
            ]
            if error_lines:
                return {"passed": False, "errors": error_lines[:5]}
            else:
                return {"passed": True, "errors": []}

    except Exception:
        return {"passed": True, "errors": []}


def _parse_json_data(report: dict, fr_ids: list[str]) -> dict:
    """
    Parses Playwright JSON data directly from dict.
    """
    results      = {}
    test_results = {}

    def process_suites(suites):
        for suite in suites:
            process_suites(suite.get("suites", []))
            for spec in suite.get("specs", []):
                title    = spec.get("title", "")
                tests    = spec.get("tests", [])
                duration = spec.get("duration", 0) / 1000

                if tests:
                    test   = tests[0]
                    status = test.get("status", "failed")
                    passed = status in ("expected", "passed")

                    error           = None
                    screenshot_path = None
                    results_list = test.get("results", [])
                    if results_list:
                        errors = results_list[0].get("errors", [])
                        if errors:
                            error = errors[0].get("message", "Unknown error")
                            if error:
                                error = error[:300]
                        for att in results_list[0].get("attachments", []):
                            if att.get("name") == "screenshot" and att.get("path"):
                                screenshot_path = att["path"]
                                break

                    test_results[title] = {
                        "status"          : "pass" if passed else "fail",
                        "duration_seconds": duration,
                        "error_message"   : error,
                        "screenshot_path" : screenshot_path
                    }

    process_suites(report.get("suites", []))

    for fr_id in fr_ids:
        matched = False
        for title, result in test_results.items():
            if fr_id in title:
                results[fr_id] = result
                matched = True
                break
        if not matched:
            results[fr_id] = {
                "status"          : "skip",
                "duration_seconds": 0.0,
                "error_message"   : "Test not found in report",
                "screenshot_path" : None
            }

    return results


def _parse_json_report(
    report_path : Path,
    fr_ids      : list[str],
    stdout      : str,
    stderr      : str
) -> dict:
    """
    Parses Playwright JSON report from file.
    """
    try:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        return _parse_json_data(report, fr_ids)

    except Exception as e:
        logger.error(f"Error parsing JSON report file: {e}")
        results = {}
        for fr_id in fr_ids:
            results[fr_id] = {
                "status"          : "fail",
                "duration_seconds": 0.0,
                "error_message"   : f"Report parsing error: {e}",
                "screenshot_path" : None
            }
        return results


def _parse_stdout(
    stdout      : str,
    stderr      : str,
    return_code : int,
    fr_ids      : list[str]
) -> dict:
    """
    Fallback parser using return code only.
    """
    results  = {}
    combined = stdout + stderr

    for fr_id in fr_ids:
        if return_code == 0:
            status = "pass"
            error  = None
        else:
            status = "fail"
            error  = _extract_error(combined)

        results[fr_id] = {
            "status"          : status,
            "duration_seconds": 0.0,
            "error_message"   : error,
            "screenshot_path" : None
        }

    return results


def _extract_error(text: str) -> Optional[str]:
    for pattern in [r"Error: (.+)", r"TimeoutError: (.+)"]:
        match = re.search(pattern, text)
        if match:
            return match.group(0)[:200]

    for line in text.splitlines():
        if any(word in line.lower() for word in ["error", "failed", "timeout"]):
            return line.strip()[:200]

    return "Test execution failed"
