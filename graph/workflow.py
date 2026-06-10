# graph/workflow.py
# LangGraph Workflow Definition
# Defines nodes, edges and retry loop
# Entry point for the entire pipeline

import logging
from langgraph.graph import StateGraph, END
from graph.state import AgentState
from agents.agent_a import run_agent_a
from agents.agent_b import run_agent_b
from agents.agent_c import run_agent_c

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# NODE FUNCTIONS
# Each node wraps an agent
# ─────────────────────────────────────────────────────────────

def agent_a_node(state: AgentState) -> AgentState:
    """
    Agent A Node
    Extracts functional requirements from PDF
    """
    logger.info("═" * 50)
    logger.info("ENTERING NODE: Agent A")
    logger.info("═" * 50)
    return run_agent_a(state)


def agent_b_node(state: AgentState) -> AgentState:
    """
    Agent B Node
    Scans pages and generates Playwright TS tests
    """
    logger.info("═" * 50)
    logger.info(
        f"ENTERING NODE: Agent B "
        f"(retry={state['current_retry']})"
    )
    logger.info("═" * 50)
    return run_agent_b(state)


def agent_c_node(state: AgentState) -> AgentState:
    """
    Agent C Node
    Reviews code, executes tests, generates report
    """
    logger.info("═" * 50)
    logger.info(
        f"ENTERING NODE: Agent C "
        f"(retry={state['current_retry']})"
    )
    logger.info("═" * 50)
    return run_agent_c(state)


# ─────────────────────────────────────────────────────────────
# CONDITIONAL EDGE
# Decision point after Agent C
# ─────────────────────────────────────────────────────────────

def should_retry_or_end(state: AgentState) -> str:
    """
    Called after Agent C completes.
    Decides whether to retry Agent B or end.

    Logic:
    - If there are failing FRs AND retries remaining → retry
    - Otherwise → end

    Returns:
        "retry" → go back to Agent B
        "end"   → go to END node
    """
    has_failures = len(state.get("failed_fr_ids", [])) > 0
    retries_left = state["current_retry"] < state["max_retries"]

    logger.info(
        f"Routing decision: "
        f"has_failures={has_failures}, "
        f"current_retry={state['current_retry']}, "
        f"max_retries={state['max_retries']}, "
        f"retries_left={retries_left}"
    )

    if has_failures and retries_left:
        logger.info(
            f"→ RETRY: {len(state['failed_fr_ids'])} FRs need fixing"
        )
        return "retry"
    else:
        if not has_failures:
            logger.info("→ END: All FRs passed")
        else:
            logger.info(
                f"→ END: Max retries reached "
                f"({state['current_retry']}/{state['max_retries']})"
            )
        return "end"


# ─────────────────────────────────────────────────────────────
# BUILD WORKFLOW
# ─────────────────────────────────────────────────────────────

def build_workflow():
    """
    Builds and compiles the LangGraph workflow.
    Called once from app.py on startup.

    Graph structure:
        START → agent_a → agent_b → agent_c
                                        │
                            ┌───────────┴───────────┐
                            │                       │
                         retry                     end
                            │                       │
                         agent_b                   END
                            │
                         agent_c
                            │
                        (loop until max retries or all pass)

    Returns:
        Compiled LangGraph workflow
    """
    workflow = StateGraph(AgentState)

    # ── Add nodes ──────────────────────────────────────────
    workflow.add_node("agent_a", agent_a_node)
    workflow.add_node("agent_b", agent_b_node)
    workflow.add_node("agent_c", agent_c_node)

    # ── Add edges ──────────────────────────────────────────
    # START → Agent A (always)
    workflow.set_entry_point("agent_a")

    # Agent A → Agent B (always)
    workflow.add_edge("agent_a", "agent_b")

    # Agent B → Agent C (always)
    workflow.add_edge("agent_b", "agent_c")

    # Agent C → retry or end (conditional)
    workflow.add_conditional_edges(
        "agent_c",
        should_retry_or_end,
        {
            "retry": "agent_b",
            "end"  : END
        }
    )

    # ── Compile ────────────────────────────────────────────
    compiled = workflow.compile()
    logger.info("LangGraph workflow compiled successfully")
    return compiled


# ─────────────────────────────────────────────────────────────
# BUILD B→C WORKFLOW (Phase 2 — Agent A already ran)
# ─────────────────────────────────────────────────────────────

def build_bc_workflow():
    """
    Builds a LangGraph workflow with only Agent B and Agent C.
    Used in Phase 2 after Agent A has already discovered requirements
    and the user has selected which features to test.

    Graph structure:
        START → agent_b → agent_c
                              │
              ┌───────────────┴───────────────┐
              │                               │
           retry                             end
              │                               │
           agent_b                           END
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("agent_b", agent_b_node)
    workflow.add_node("agent_c", agent_c_node)

    workflow.set_entry_point("agent_b")
    workflow.add_edge("agent_b", "agent_c")
    workflow.add_conditional_edges(
        "agent_c",
        should_retry_or_end,
        {
            "retry": "agent_b",
            "end"  : END
        }
    )

    compiled = workflow.compile()
    logger.info("B→C workflow compiled successfully")
    return compiled


# ─────────────────────────────────────────────────────────────
# INITIAL STATE FACTORY
# ─────────────────────────────────────────────────────────────

def create_initial_state(
    llm_provider     : str,
    api_key          : str,
    base_url         : str,
    max_retries      : int,
    selected_features: list,
    pdf_path         : str
) -> AgentState:
    """
    Creates the initial AgentState from Streamlit UI inputs.
    All agent fields start empty/pending.

    Args:
        llm_provider     : "gemini" or "claude"
        api_key          : User provided API key
        base_url         : Target application URL
        max_retries      : Max retry attempts (default 1)
        selected_features: List of feature module names
        pdf_path         : Path to uploaded SRS PDF

    Returns:
        Initial AgentState dict
    """
    return {
        # ── Configuration ───────────────────────────────────
        "llm_provider"           : llm_provider,
        "api_key"                : api_key,
        "base_url"               : base_url.rstrip("/"),
        "max_retries"            : max_retries,
        "selected_features"      : selected_features,
        "pdf_path"               : pdf_path,

        # ── Agent A ─────────────────────────────────────────
        "all_requirements"       : [],
        "selected_requirements"  : [],
        "agent_a_status"         : "pending",
        "agent_a_log"            : [],

        # ── Page Scanner ────────────────────────────────────
        "page_scan_results"      : {},

        # ── Agent B ─────────────────────────────────────────
        "generated_tests"        : {},
        "spec_files"             : {},
        "agent_b_status"         : "pending",
        "agent_b_log"            : [],

        # ── Agent C ─────────────────────────────────────────
        "agent_c_results"        : {},
        "failed_fr_ids"          : [],
        "agent_c_status"         : "pending",
        "agent_c_log"            : [],

        # ── Retry Control ───────────────────────────────────
        "current_retry"          : 0,
        "retry_triggered"        : False,

        # ── Traceability Matrix ─────────────────────────────
        "traceability_matrix"    : [],

        # ── Final Report ────────────────────────────────────
        "final_report_path"      : None,
        "overall_status"         : None,
        "total_frs"              : None,
        "passed_frs"             : None,
        "failed_frs"             : None,
        "warned_frs"             : None,
        "skipped_frs"            : None,
    }
