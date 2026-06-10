# agents/agent_b.py
# Agent B — Playwright Test Generation Agent
# Scans live pages and generates TypeScript Playwright test files
# Handles both initial generation and partial retry

import re
import logging
from pathlib import Path
from datetime import datetime
from graph.state import AgentState, GeneratedTest, TraceabilityRow
from tools.page_scanner import scan_page, format_scan_for_llm
from tools.llm_provider import get_llm, invoke_llm_with_retry, apply_rpm_delay
from prompts.agent_b_prompt import get_agent_b_prompt, get_agent_b_retry_prompt

logger     = logging.getLogger(__name__)
TESTS_DIR  = Path(__file__).parent.parent / "tests"


def run_agent_b(state: AgentState) -> AgentState:
    """
    Agent B main function.
    Called by LangGraph as a node.

    Steps:
    1. Determine if initial run or retry
    2. Group FRs by feature module
    3. For each feature: scan page + generate spec file
    4. Save spec files to tests/ directory
    5. Update state and traceability matrix

    Args:
        state: Current AgentState

    Returns:
        Updated AgentState
    """
    logs = []

    def log(msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry     = f"[Agent B] {timestamp}  {msg}"
        logs.append(entry)
        logger.info(msg)

    try:
        state["agent_b_status"] = "running"
        TESTS_DIR.mkdir(exist_ok=True)

        is_retry     = state["current_retry"] > 0
        failed_fr_ids = state.get("failed_fr_ids", [])

        if is_retry:
            log(
                f"Retry mode — fixing {len(failed_fr_ids)} FRs: "
                f"{', '.join(failed_fr_ids)}"
            )
        else:
            log("Starting test generation...")

        # ── Initialize LLM ─────────────────────────────────
        log(f"Initializing {state['llm_provider'].upper()} LLM...")
        llm = get_llm(state["llm_provider"], state["api_key"])

        # ── Group FRs by feature module ────────────────────
        if is_retry:
            # Only process features that have failing FRs
            requirements_to_process = [
                fr for fr in state["selected_requirements"]
                if fr["id"] in failed_fr_ids
            ]
        else:
            requirements_to_process = state["selected_requirements"]

        feature_groups = _group_by_feature(requirements_to_process)
        log(f"Processing {len(feature_groups)} feature modules")

        # ── Process each feature ───────────────────────────
        generated_tests = dict(state.get("generated_tests", {}))
        spec_files      = dict(state.get("spec_files", {}))
        page_scan_results = dict(state.get("page_scan_results", {}))
        traceability_matrix = list(state.get("traceability_matrix", []))

        for feature_module, frs in feature_groups.items():
            log(f"Processing feature: {feature_module} ({len(frs)} FRs)")

            # ── Scan page ───────────────────────────────────
            url_path = frs[0]["url_path"]
            log(f"Scanning {url_path}...")

            try:
                scan_result = scan_page(
                    base_url       = state["base_url"],
                    url_path       = url_path,
                    feature_module = feature_module
                )
                page_scan_results[feature_module] = scan_result
                page_scan_text = format_scan_for_llm(scan_result)

                element_count = len(scan_result["elements"])
                log(f"Found {element_count} elements on {url_path}")

            except Exception as e:
                log(f"⚠️  Page scan failed for {url_path}: {e}")
                log("Continuing with empty scan result")
                page_scan_text = f"Page scan failed: {e}"

            # ── Apply RPM delay ─────────────────────────────
            apply_rpm_delay(state["llm_provider"])

            # ── Generate test code ──────────────────────────
            spec_file_path = TESTS_DIR / f"{feature_module}.spec.ts"

            if is_retry:
                # Get fix instructions for failing FRs
                fix_instructions = {}
                for fr in frs:
                    result = state.get("agent_c_results", {}).get(fr["id"])
                    if result and result.get("fix_instructions"):
                        fix_instructions[fr["id"]] = result["fix_instructions"]

                # Get original code
                original_code = ""
                if spec_file_path.exists():
                    original_code = spec_file_path.read_text(encoding="utf-8")

                log(f"Generating fix for {feature_module}...")
                prompt = get_agent_b_retry_prompt(
                    feature_module   = feature_module,
                    original_code    = original_code,
                    failed_fr_ids    = [fr["id"] for fr in frs],
                    fix_instructions = fix_instructions,
                    page_scan_text   = page_scan_text,
                    base_url         = state["base_url"]
                )
            else:
                log(f"Generating tests for {feature_module}...")
                prompt = get_agent_b_prompt(
                    feature_module = feature_module,
                    requirements   = frs,
                    page_scan_text = page_scan_text,
                    base_url       = state["base_url"],
                    is_retry       = False
                )

            # ── Call LLM ────────────────────────────────────
            test_code = invoke_llm_with_retry(
                llm      = llm,
                prompt   = prompt,
                provider = state["llm_provider"]
            )

            # Clean up LLM response
            test_code = _clean_code_response(test_code)

            # ── Save spec file ──────────────────────────────
            spec_file_path.write_text(test_code, encoding="utf-8")
            log(f"✅ Saved: {spec_file_path.name}")
            spec_files[feature_module] = str(spec_file_path)

            # ── Extract locators used ───────────────────────
            locators_used = _extract_locators(test_code)

            # ── Update generated tests per FR ───────────────
            for fr in frs:
                previous_code = None
                if fr["id"] in generated_tests:
                    previous_code = generated_tests[fr["id"]]["test_code"]

                generated_tests[fr["id"]] = GeneratedTest(
                    fr_id          = fr["id"],
                    feature_module = feature_module,
                    spec_file      = spec_file_path.name,
                    test_code      = test_code,
                    locators_used  = locators_used,
                    attempt_number = state["current_retry"] + 1,
                    previous_code  = previous_code
                )

            # ── Update traceability matrix ──────────────────
            for i, row in enumerate(traceability_matrix):
                if row["fr_id"] in [fr["id"] for fr in frs]:
                    traceability_matrix[i] = {
                        **row,
                        "generated_test": generated_tests[row["fr_id"]]
                    }

            log(f"✅ {feature_module} complete")

        log(
            f"✅ Agent B complete — "
            f"{len(spec_files)} spec files generated"
        )

        return {
            **state,
            "generated_tests"   : generated_tests,
            "spec_files"        : spec_files,
            "page_scan_results" : page_scan_results,
            "traceability_matrix": traceability_matrix,
            "agent_b_status"    : "complete",
            "agent_b_log"       : state["agent_b_log"] + logs,
        }

    except Exception as e:
        error_msg = f"❌ Agent B failed: {str(e)}"
        log(error_msg)
        logger.error(error_msg)

        return {
            **state,
            "agent_b_status": "failed",
            "agent_b_log"   : state["agent_b_log"] + logs,
        }


def _group_by_feature(requirements: list) -> dict:
    """
    Groups requirements by feature_module.

    Args:
        requirements: List of FR objects

    Returns:
        Dict of feature_module → list of FRs
    """
    groups = {}
    for fr in requirements:
        module = fr["feature_module"]
        if module not in groups:
            groups[module] = []
        groups[module].append(fr)
    return groups


def _clean_code_response(response: str) -> str:
    """
    Cleans LLM response to extract pure TypeScript code.

    Args:
        response: Raw LLM response

    Returns:
        Clean TypeScript code string
    """
    cleaned = response.strip()

    # Remove markdown code blocks
    if "```typescript" in cleaned:
        cleaned = cleaned.split("```typescript")[1]
        cleaned = cleaned.split("```")[0]
    elif "```ts" in cleaned:
        cleaned = cleaned.split("```ts")[1]
        cleaned = cleaned.split("```")[0]
    elif cleaned.startswith("```"):
        lines   = cleaned.split("\n")
        cleaned = "\n".join(lines[1:])
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

    return cleaned.strip()


def _extract_locators(code: str) -> list[str]:
    """
    Extracts all locator strings from TypeScript code.
    Used for hallucination checking by Agent C.

    Args:
        code: TypeScript spec file content

    Returns:
        List of locator strings found in code
    """
    locators = []

    # Match page.locator('...') and page.locator("...")
    pattern = r'page\.locator\([\'"]([^\'"]+)[\'"]\)'
    matches = re.findall(pattern, code)
    locators.extend(matches)

    # Match getByRole, getByLabel, getByText
    role_pattern = r'getBy(?:Role|Label|Text|Placeholder)\([\'"]([^\'"]+)[\'"]\)'
    role_matches = re.findall(role_pattern, code)
    locators.extend(role_matches)

    return list(set(locators))  # Remove duplicates
