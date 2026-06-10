# graph/state.py
# LangGraph State Definition
# This is the shared memory that flows between all agents

from typing import TypedDict, List, Optional, Dict


# ─────────────────────────────────────────────────────────────
# FUNCTIONAL REQUIREMENT
# Output of Agent A — extracted from PDF
# ─────────────────────────────────────────────────────────────

class FunctionalRequirement(TypedDict):
    id                          : str
    feature_name                : str
    feature_module              : str
    url_path                    : str
    full_url                    : str
    description                 : str
    preconditions               : List[str]
    user_actions                : List[str]
    expected_behavior           : List[str]
    validation_error_handling   : List[str]
    test_type                   : str
    # positive / negative / edge_case


# ─────────────────────────────────────────────────────────────
# GENERATED TEST
# Output of Agent B — generated Playwright TS code
# ─────────────────────────────────────────────────────────────

class GeneratedTest(TypedDict):
    fr_id                       : str
    feature_module              : str
    spec_file                   : str
    test_code                   : str
    locators_used               : List[str]
    attempt_number              : int
    previous_code               : Optional[str]
    # previous attempt code for diff view in UI


# ─────────────────────────────────────────────────────────────
# PAGE SCANNER
# Output of tools/page_scanner.py
# Used by Agent B before code generation
# ─────────────────────────────────────────────────────────────

class ScannedElement(TypedDict):
    element_type                : str
    # input / button / heading / link / checkbox / dropdown
    locator                     : str
    text                        : Optional[str]
    attributes                  : Dict[str, str]


class PageScanResult(TypedDict):
    url                         : str
    feature_module              : str
    elements                    : List[ScannedElement]
    scan_timestamp              : str


# ─────────────────────────────────────────────────────────────
# AGENT C CHECKS
# One per FR per check type
# ─────────────────────────────────────────────────────────────

class HallucinationCheck(TypedDict):
    status                      : str
    # none / found
    hallucinated_locators       : List[str]
    suggested_fixes             : List[str]


class MissingScriptCheck(TypedDict):
    status                      : str
    # present / missing
    reason                      : Optional[str]


class MissingScenarioCheck(TypedDict):
    status                      : str
    # covered / partial / missing
    missing_cases               : List[str]


class CoverageCheck(TypedDict):
    percentage                  : float
    total_expected_behaviors    : int
    behaviors_covered           : int
    uncovered_behaviors         : List[str]


class ExecutionCheck(TypedDict):
    status                      : str
    # pass / fail / warn / skip
    duration_seconds            : Optional[float]
    error_message               : Optional[str]
    screenshot_path             : Optional[str]


class AgentCResult(TypedDict):
    fr_id                       : str
    overall_result              : str
    # pass / fail / warn / skip
    hallucination               : HallucinationCheck
    missing_script              : MissingScriptCheck
    missing_scenario            : MissingScenarioCheck
    coverage                    : CoverageCheck
    execution                   : ExecutionCheck
    needs_fix                   : bool
    fix_instructions            : Optional[str]


# ─────────────────────────────────────────────────────────────
# TRACEABILITY ROW
# One row per FR in the UI matrix
# ─────────────────────────────────────────────────────────────

class TraceabilityRow(TypedDict):
    fr_id                       : str
    requirement                 : FunctionalRequirement
    generated_test              : Optional[GeneratedTest]
    agent_c_result              : Optional[AgentCResult]
    retry_history               : List[AgentCResult]
    # all attempts history for retry timeline


# ─────────────────────────────────────────────────────────────
# MAIN LANGGRAPH STATE
# Flows through entire graph
# Every agent reads from and writes to this
# ─────────────────────────────────────────────────────────────

class AgentState(TypedDict):

    # ── CONFIGURATION ──────────────────────────────────────
    # Set by Streamlit UI, never changes during run

    llm_provider                : str
    # gemini / claude

    api_key                     : str
    # user provided API key

    base_url                    : str
    # e.g. https://the-internet.herokuapp.com

    max_retries                 : int
    # user set default 1

    selected_features           : List[str]
    # e.g. ["login", "checkboxes", "dropdown"]

    pdf_path                    : str
    # path to uploaded PDF file

    # ── AGENT A ────────────────────────────────────────────
    # Populated after Agent A runs

    all_requirements            : List[FunctionalRequirement]
    # all FRs extracted from PDF

    selected_requirements       : List[FunctionalRequirement]
    # only FRs matching selected features

    agent_a_status              : str
    # pending / running / complete / failed

    agent_a_log                 : List[str]
    # live log messages streamed to UI

    # ── PAGE SCANNER ───────────────────────────────────────
    # Populated inside Agent B before code generation

    page_scan_results           : Dict[str, PageScanResult]
    # key = feature_module
    # e.g. {"login": PageScanResult}

    # ── AGENT B ────────────────────────────────────────────
    # Populated after Agent B runs

    generated_tests             : Dict[str, GeneratedTest]
    # key = fr_id
    # e.g. {"FR-FA-01": GeneratedTest}

    spec_files                  : Dict[str, str]
    # key = feature_module
    # value = file path
    # e.g. {"login": "tests/login.spec.ts"}

    agent_b_status              : str
    # pending / running / complete / failed

    agent_b_log                 : List[str]
    # live log messages streamed to UI

    # ── AGENT C ────────────────────────────────────────────
    # Populated after Agent C runs

    agent_c_results             : Dict[str, AgentCResult]
    # key = fr_id
    # e.g. {"FR-FA-01": AgentCResult}

    failed_fr_ids               : List[str]
    # FRs that need fixing
    # passed back to Agent B on retry

    agent_c_status              : str
    # pending / running / complete / failed

    agent_c_log                 : List[str]
    # live log messages streamed to UI

    # ── RETRY CONTROL ──────────────────────────────────────
    # Managed by LangGraph conditional edge

    current_retry               : int
    # starts at 0 incremented after each Agent C run

    retry_triggered             : bool
    # True if Agent C found failures and retry needed

    # ── TRACEABILITY MATRIX ────────────────────────────────
    # Built progressively as agents run
    # Used directly by Streamlit UI table

    traceability_matrix         : List[TraceabilityRow]
    # one row per selected FR
    # updated after each agent completes

    # ── FINAL REPORT ───────────────────────────────────────
    # Populated at END node

    final_report_path           : Optional[str]
    # path to generated HTML report

    overall_status              : Optional[str]
    # pass / fail / partial

    total_frs                   : Optional[int]
    passed_frs                  : Optional[int]
    failed_frs                  : Optional[int]
    warned_frs                  : Optional[int]
    skipped_frs                 : Optional[int]
