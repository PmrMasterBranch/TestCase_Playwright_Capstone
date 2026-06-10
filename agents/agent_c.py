# agents/agent_c.py
# Agent C — Code Review and Execution Agent
# Reviews generated Playwright code and executes tests
# Produces traceability matrix results and fix instructions

import re
import json
import logging
from pathlib import Path
from datetime import datetime
from graph.state import (
    AgentState, AgentCResult,
    HallucinationCheck, MissingScriptCheck,
    MissingScenarioCheck, CoverageCheck,
    ExecutionCheck, TraceabilityRow
)
from tools.llm_provider import get_llm, invoke_llm_with_retry, apply_rpm_delay
from tools.code_executor import execute_spec_file, run_typescript_check
from tools.page_scanner import format_scan_for_llm
from prompts.agent_c_prompt import (
    get_hallucination_check_prompt,
    get_missing_scenario_check_prompt,
    get_fix_instructions_prompt
)

logger    = logging.getLogger(__name__)
TESTS_DIR = Path(__file__).parent.parent / "tests"


def run_agent_c(state: AgentState) -> AgentState:
    """
    Agent C main function.
    Called by LangGraph as a node.

    Steps:
    1. For each spec file:
       a. Automated checks (missing scripts, coverage, TS syntax)
       b. LLM checks (hallucinations, missing scenarios)
       c. Execute spec file
    2. Combine all results
    3. Generate fix instructions for failing FRs
    4. Update traceability matrix
    5. Decide if retry needed

    Args:
        state: Current AgentState

    Returns:
        Updated AgentState
    """
    logs = []

    def log(msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry     = f"[Agent C] {timestamp}  {msg}"
        logs.append(entry)
        logger.info(msg)

    try:
        state["agent_c_status"] = "running"
        log("Starting code review and execution...")

        # ── Initialize LLM ─────────────────────────────────
        log(f"Initializing {state['llm_provider'].upper()} LLM...")
        llm = get_llm(state["llm_provider"], state["api_key"])

        # ── Get FRs to check ───────────────────────────────
        is_retry     = state["current_retry"] > 0
        failed_fr_ids = state.get("failed_fr_ids", [])

        if is_retry:
            frs_to_check = [
                fr for fr in state["selected_requirements"]
                if fr["id"] in failed_fr_ids
            ]
            log(f"Retry mode — checking {len(frs_to_check)} FRs")
        else:
            frs_to_check = state["selected_requirements"]
            log(f"Checking {len(frs_to_check)} FRs")

        # ── Group FRs by feature module ────────────────────
        feature_groups = _group_by_feature(frs_to_check)

        # ── Initialize results ─────────────────────────────
        agent_c_results = dict(state.get("agent_c_results", {}))
        traceability_matrix = list(state.get("traceability_matrix", []))

        # ── Process each feature ───────────────────────────
        for feature_module, frs in feature_groups.items():
            log(f"Reviewing feature: {feature_module}")

            fr_ids      = [fr["id"] for fr in frs]
            spec_file   = state["spec_files"].get(feature_module, "")
            spec_path   = Path(spec_file) if spec_file else None
            spec_code   = ""

            if spec_path and spec_path.exists():
                spec_code = spec_path.read_text(encoding="utf-8")
            else:
                log(f"⚠️  Spec file not found for {feature_module}")

            # Get page scan for this feature
            scan_result    = state["page_scan_results"].get(feature_module)
            page_scan_text = format_scan_for_llm(scan_result) if scan_result else ""

            # ── CHECK 1: Missing Script (automated) ─────────
            log(f"Running missing script check for {feature_module}...")
            missing_script_results = _check_missing_scripts(
                fr_ids  = fr_ids,
                spec_code = spec_code
            )

            # ── CHECK 2: TypeScript syntax (automated) ──────
            log(f"Running TypeScript syntax check for {feature_module}...")
            ts_check = {"passed": True, "errors": []}
            if spec_path and spec_path.exists():
                ts_check = run_typescript_check(str(spec_path))
                if not ts_check["passed"]:
                    log(f"⚠️  TypeScript errors found in {feature_module}")

            # ── CHECK 3: Hallucination (LLM) ────────────────
            log(f"Running hallucination check for {feature_module}...")
            hallucination_results = {}

            if spec_code and page_scan_text:
                apply_rpm_delay(state["llm_provider"])
                h_prompt   = get_hallucination_check_prompt(
                    spec_code      = spec_code,
                    page_scan_text = page_scan_text,
                    fr_ids         = fr_ids
                )
                h_response = invoke_llm_with_retry(
                    llm      = llm,
                    prompt   = h_prompt,
                    provider = state["llm_provider"]
                )
                hallucination_results = _parse_hallucination_results(
                    h_response, fr_ids
                )
            else:
                for fr_id in fr_ids:
                    hallucination_results[fr_id] = {
                        "status"                : "none",
                        "hallucinated_locators" : [],
                        "suggested_fixes"       : []
                    }

            # ── CHECK 4: Missing Scenarios (LLM) ────────────
            log(f"Running missing scenario check for {feature_module}...")
            scenario_results = {}

            if spec_code:
                apply_rpm_delay(state["llm_provider"])
                s_prompt   = get_missing_scenario_check_prompt(
                    spec_code    = spec_code,
                    requirements = frs
                )
                s_response = invoke_llm_with_retry(
                    llm      = llm,
                    prompt   = s_prompt,
                    provider = state["llm_provider"]
                )
                scenario_results = _parse_scenario_results(
                    s_response, fr_ids
                )
            else:
                for fr_id in fr_ids:
                    scenario_results[fr_id] = {
                        "status"              : "missing",
                        "missing_cases"       : ["No script generated"],
                        "coverage_percentage" : 0.0,
                        "behaviors_covered"   : 0,
                        "total_behaviors"     : len(
                            next(
                                (fr["expected_behavior"] for fr in frs
                                 if fr["id"] == fr_id), []
                            )
                        ),
                        "uncovered_behaviors" : []
                    }

            # ── CHECK 5: Execute tests ───────────────────────
            log(f"Executing {feature_module}.spec.ts...")
            execution_results = {}

            if spec_path and spec_path.exists():
                execution_results = execute_spec_file(
                    spec_file_path = str(spec_path),
                    base_url       = state["base_url"],
                    fr_ids         = fr_ids
                )
                for fr_id, result in execution_results.items():
                    icon = "✅" if result["status"] == "pass" else (
                        "⚠️ " if result["status"] == "warn" else "❌"
                    )
                    dur  = f"({result['duration_seconds']:.1f}s)" if result["duration_seconds"] else ""
                    log(f"  {icon} {fr_id}: {result['status'].upper()} {dur}")
            else:
                for fr_id in fr_ids:
                    execution_results[fr_id] = {
                        "status"          : "skip",
                        "duration_seconds": 0.0,
                        "error_message"   : "Spec file not found",
                        "screenshot_path" : None
                    }

            # ── Generate fix instructions ────────────────────
            log(f"Generating fix instructions for {feature_module}...")
            apply_rpm_delay(state["llm_provider"])

            fix_response = invoke_llm_with_retry(
                llm      = llm,
                prompt   = get_fix_instructions_prompt(
                    requirements         = frs,
                    hallucination_results= hallucination_results,
                    scenario_results     = scenario_results,
                    execution_results    = execution_results,
                    spec_code            = spec_code
                ),
                provider = state["llm_provider"]
            )
            fix_data = _parse_fix_instructions(fix_response)

            # ── Combine all results per FR ───────────────────
            for fr in frs:
                fr_id = fr["id"]

                hallucination    = hallucination_results.get(fr_id, {
                    "status"               : "none",
                    "hallucinated_locators": [],
                    "suggested_fixes"      : []
                })

                missing_script_data = missing_script_results.get(fr_id, {
                    "status": "missing",
                    "reason": "Script not generated"
                })

                scenario = scenario_results.get(fr_id, {
                    "status"              : "missing",
                    "missing_cases"       : [],
                    "coverage_percentage" : 0.0,
                    "behaviors_covered"   : 0,
                    "total_behaviors"     : 0,
                    "uncovered_behaviors" : []
                })

                execution = execution_results.get(fr_id, {
                    "status"          : "skip",
                    "duration_seconds": 0.0,
                    "error_message"   : None,
                    "screenshot_path" : None
                })

                # Determine overall result
                overall = _determine_overall_result(
                    hallucination    = hallucination,
                    missing_script   = missing_script_data,
                    scenario         = scenario,
                    execution        = execution,
                    ts_check         = ts_check
                )

                # Determine if fix needed
                needs_fix = overall in ["fail", "skip"]

                # Get fix instructions
                fix_instructions = fix_data.get(
                    "fix_instructions", {}
                ).get(fr_id)

                result: AgentCResult = {
                    "fr_id"          : fr_id,
                    "overall_result" : overall,
                    "hallucination"  : {
                        "status"                : hallucination.get("status", "none"),
                        "hallucinated_locators" : hallucination.get("hallucinated_locators", []),
                        "suggested_fixes"       : hallucination.get("suggested_fixes", [])
                    },
                    "missing_script" : {
                        "status": missing_script_data.get("status", "missing"),
                        "reason": missing_script_data.get("reason")
                    },
                    "missing_scenario": {
                        "status"      : scenario.get("status", "missing"),
                        "missing_cases": scenario.get("missing_cases", [])
                    },
                    "coverage"       : {
                        "percentage"              : scenario.get("coverage_percentage", 0.0),
                        "total_expected_behaviors": scenario.get("total_behaviors", 0),
                        "behaviors_covered"       : scenario.get("behaviors_covered", 0),
                        "uncovered_behaviors"     : scenario.get("uncovered_behaviors", [])
                    },
                    "execution"      : {
                        "status"          : execution.get("status", "skip"),
                        "duration_seconds": execution.get("duration_seconds", 0.0),
                        "error_message"   : execution.get("error_message"),
                        "screenshot_path" : execution.get("screenshot_path")
                    },
                    "needs_fix"      : needs_fix,
                    "fix_instructions": fix_instructions
                }

                agent_c_results[fr_id] = result

        # ── Collect failing FRs ─────────────────────────────
        new_failed_fr_ids = [
            fr_id for fr_id, result in agent_c_results.items()
            if result["needs_fix"]
        ]

        retry_triggered = len(new_failed_fr_ids) > 0
        new_retry_count = state["current_retry"] + 1

        log(
            f"Review complete: "
            f"{len(frs_to_check) - len(new_failed_fr_ids)} passed, "
            f"{len(new_failed_fr_ids)} need fixing"
        )

        if retry_triggered:
            log(f"Failing FRs: {', '.join(new_failed_fr_ids)}")

        # ── Update traceability matrix ──────────────────────
        for i, row in enumerate(traceability_matrix):
            fr_id = row["fr_id"]
            if fr_id in agent_c_results:
                retry_history = list(row.get("retry_history", []))
                if row.get("agent_c_result"):
                    retry_history.append(row["agent_c_result"])

                traceability_matrix[i] = {
                    **row,
                    "agent_c_result": agent_c_results[fr_id],
                    "retry_history" : retry_history
                }

        # ── Compute summary counts ──────────────────────────
        all_results   = list(agent_c_results.values())
        passed_count  = sum(1 for r in all_results if r["overall_result"] == "pass")
        failed_count  = sum(1 for r in all_results if r["overall_result"] == "fail")
        warned_count  = sum(1 for r in all_results if r["overall_result"] == "warn")
        skipped_count = sum(1 for r in all_results if r["overall_result"] == "skip")
        total_count   = len(state["selected_requirements"])

        overall_status = (
            "pass"    if failed_count == 0 and skipped_count == 0
            else "partial" if passed_count > 0
            else "fail"
        )

        log(
            f"✅ Agent C complete — "
            f"Pass: {passed_count}, Fail: {failed_count}, "
            f"Warn: {warned_count}, Skip: {skipped_count}"
        )

        return {
            **state,
            "agent_c_results"    : agent_c_results,
            "failed_fr_ids"      : new_failed_fr_ids,
            "retry_triggered"    : retry_triggered,
            "current_retry"      : new_retry_count,
            "traceability_matrix": traceability_matrix,
            "agent_c_status"     : "complete",
            "agent_c_log"        : state["agent_c_log"] + logs,
            "overall_status"     : overall_status,
            "total_frs"          : total_count,
            "passed_frs"         : passed_count,
            "failed_frs"         : failed_count,
            "warned_frs"         : warned_count,
            "skipped_frs"        : skipped_count,
        }

    except Exception as e:
        error_msg = f"❌ Agent C failed: {str(e)}"
        log(error_msg)
        logger.error(error_msg, exc_info=True)

        return {
            **state,
            "agent_c_status": "failed",
            "agent_c_log"   : state["agent_c_log"] + logs,
        }


# ─────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────

def _group_by_feature(requirements: list) -> dict:
    groups = {}
    for fr in requirements:
        module = fr["feature_module"]
        if module not in groups:
            groups[module] = []
        groups[module].append(fr)
    return groups


def _check_missing_scripts(fr_ids: list, spec_code: str) -> dict:
    """
    Automated check — verifies each FR ID appears in spec code.
    """
    results = {}
    for fr_id in fr_ids:
        if fr_id in spec_code:
            results[fr_id] = {
                "status": "present",
                "reason": None
            }
        else:
            results[fr_id] = {
                "status": "missing",
                "reason": f"No test found for {fr_id} in spec file"
            }
    return results


def _determine_overall_result(
    hallucination : dict,
    missing_script: dict,
    scenario      : dict,
    execution     : dict,
    ts_check      : dict
) -> str:
    """
    Determines overall FR result from all checks.

    Priority:
    - fail  : missing script OR execution failed OR TS errors
    - warn  : partial coverage OR hallucinations found
    - pass  : all checks pass
    - skip  : execution was skipped
    """
    exec_status  = execution.get("status", "skip")
    script_status = missing_script.get("status", "missing")

    # Critical failures
    if script_status == "missing":
        return "fail"

    if exec_status == "fail":
        return "fail"

    if not ts_check.get("passed", True):
        return "fail"

    if exec_status == "skip":
        return "skip"

    # Warnings
    if hallucination.get("status") == "found":
        return "warn"

    if scenario.get("status") in ["partial", "missing"]:
        return "warn"

    if scenario.get("coverage_percentage", 100) < 100:
        return "warn"

    return "pass"


def _parse_hallucination_results(response: str, fr_ids: list) -> dict:
    """Parses LLM hallucination check response."""
    results = {}
    try:
        data = _extract_json(response)
        for item in data.get("fr_results", []):
            fr_id = item.get("fr_id")
            if fr_id:
                results[fr_id] = {
                    "status"               : item.get("status", "none"),
                    "hallucinated_locators": item.get("hallucinated_locators", []),
                    "suggested_fixes"      : item.get("suggested_fixes", [])
                }
    except Exception as e:
        logger.error(f"Error parsing hallucination results: {e}")

    # Fill missing FRs
    for fr_id in fr_ids:
        if fr_id not in results:
            results[fr_id] = {
                "status"               : "none",
                "hallucinated_locators": [],
                "suggested_fixes"      : []
            }
    return results


def _parse_scenario_results(response: str, fr_ids: list) -> dict:
    """Parses LLM missing scenario check response."""
    results = {}
    try:
        data = _extract_json(response)
        for item in data.get("fr_results", []):
            fr_id = item.get("fr_id")
            if fr_id:
                results[fr_id] = {
                    "status"              : item.get("status", "missing"),
                    "missing_cases"       : item.get("missing_cases", []),
                    "coverage_percentage" : item.get("coverage_percentage", 0.0),
                    "behaviors_covered"   : item.get("behaviors_covered", 0),
                    "total_behaviors"     : item.get("total_behaviors", 0),
                    "uncovered_behaviors" : item.get("uncovered_behaviors", [])
                }
    except Exception as e:
        logger.error(f"Error parsing scenario results: {e}")

    # Fill missing FRs
    for fr_id in fr_ids:
        if fr_id not in results:
            results[fr_id] = {
                "status"              : "missing",
                "missing_cases"       : ["Could not analyze"],
                "coverage_percentage" : 0.0,
                "behaviors_covered"   : 0,
                "total_behaviors"     : 0,
                "uncovered_behaviors" : []
            }
    return results


def _parse_fix_instructions(response: str) -> dict:
    """Parses LLM fix instructions response."""
    try:
        return _extract_json(response)
    except Exception as e:
        logger.error(f"Error parsing fix instructions: {e}")
        return {"failed_fr_ids": [], "fix_instructions": {}}


def _extract_json(text: str) -> dict:
    """
    Extracts JSON from LLM response.
    Handles markdown code blocks and extra text.
    """
    cleaned = text.strip()

    # Remove markdown code blocks
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0]
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0]

    # Find JSON object
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start != -1 and end > start:
        cleaned = cleaned[start:end]

    return json.loads(cleaned)
