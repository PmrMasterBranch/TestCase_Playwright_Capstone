# agents/agent_a.py
# Agent A — Requirements Extraction Agent
# Reads PDF and extracts structured functional requirements
# Filters to only selected features

import json
import logging
from datetime import datetime
from graph.state import AgentState, FunctionalRequirement, TraceabilityRow
from tools.pdf_reader import extract_text_from_pdf, get_pdf_metadata
from tools.llm_provider import get_llm, invoke_llm_with_retry, apply_rpm_delay
from prompts.agent_a_prompt import get_agent_a_prompt

logger = logging.getLogger(__name__)


def run_agent_a(state: AgentState) -> AgentState:
    """
    Agent A main function.
    Called by LangGraph as a node.

    Steps:
    1. Read PDF file
    2. Extract all FRs using LLM
    3. Filter to selected features
    4. Initialize traceability matrix rows
    5. Update state

    Args:
        state: Current AgentState

    Returns:
        Updated AgentState
    """
    logs = []

    def log(msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry     = f"[Agent A] {timestamp}  {msg}"
        logs.append(entry)
        logger.info(msg)

    try:
        # ── Mark as running ────────────────────────────────
        state["agent_a_status"] = "running"
        log("Starting requirements extraction...")

        # ── Step 1: Read PDF ───────────────────────────────
        log(f"Reading PDF: {state['pdf_path']}")
        pdf_text = extract_text_from_pdf(state["pdf_path"])
        metadata = get_pdf_metadata(state["pdf_path"])

        log(
            f"PDF loaded: {metadata['file_name']} "
            f"({metadata['page_count']} pages, {metadata['file_size']})"
        )

        # ── Step 2: Initialize LLM ─────────────────────────
        log(f"Initializing {state['llm_provider'].upper()} LLM...")
        llm = get_llm(state["llm_provider"], state["api_key"])

        # # ── Step 3: Extract all FRs ────────────────────────
        # log("Extracting functional requirements from PDF...")
        # apply_rpm_delay(state["llm_provider"])

        # prompt   = get_agent_a_prompt(pdf_text, state["base_url"])
        # response = invoke_llm_with_retry(
        #     llm      = llm,
        #     prompt   = prompt,
        #     provider = state["llm_provider"]
        # )


        # ── Step 3: Extract FRs in chunks ──────────────────
        log("Extracting functional requirements from PDF in chunks...")
        
        chunks = _split_pdf_into_chunks(pdf_text)
        log(f"Split PDF into {len(chunks)} chunks")
        
        all_requirements = []
        seen_ids = set()
        
        for i, chunk in enumerate(chunks, 1):
            log(f"Processing chunk {i}/{len(chunks)}...")
            apply_rpm_delay(state["llm_provider"])
            
            prompt = get_agent_a_prompt(chunk, state["base_url"])
            try:
                response = invoke_llm_with_retry(
                    llm      = llm,
                    prompt   = prompt,
                    provider = state["llm_provider"]
                )
                chunk_reqs = _parse_requirements_safe(response)
                
                # Deduplicate by FR ID
                for req in chunk_reqs:
                    if req["id"] not in seen_ids:
                        seen_ids.add(req["id"])
                        all_requirements.append(req)
                
                log(f"Chunk {i}: extracted {len(chunk_reqs)} FRs (total so far: {len(all_requirements)})")
            except Exception as e:
                log(f"⚠️ Chunk {i} failed: {e}")
                continue

        # ── Step 4: Validate ───────────────────────────────
        all_requirements = [_validate_requirement(r) for r in all_requirements]
        log(f"Extracted {len(all_requirements)} functional requirements total")

        # # ── Step 4: Parse LLM response ─────────────────────
        # all_requirements = _parse_requirements_safe(response)
        # log(f"Extracted {len(all_requirements)} functional requirements")

        # ── Step 5: Filter to selected features ────────────
        selected_features = state["selected_features"]
        log(f"Filtering to selected features: {', '.join(selected_features)}")

        selected_requirements = [
            fr for fr in all_requirements
            if fr["feature_module"] in selected_features
        ]

        log(
            f"Selected {len(selected_requirements)} FRs "
            f"from {len(selected_features)} features"
        )

        # Log which FRs were selected
        for fr in selected_requirements:
            log(f"  ✅ {fr['id']}: {fr['feature_name']}")

        # ── Step 6: Initialize traceability matrix ─────────
        log("Initializing traceability matrix...")
        traceability_matrix: list[TraceabilityRow] = [
            {
                "fr_id"         : fr["id"],
                "requirement"   : fr,
                "generated_test": None,
                "agent_c_result": None,
                "retry_history" : []
            }
            for fr in selected_requirements
        ]

        log(f"✅ Agent A complete — {len(selected_requirements)} FRs ready")

        # ── Update state ───────────────────────────────────
        return {
            **state,
            "all_requirements"      : all_requirements,
            "selected_requirements" : selected_requirements,
            "traceability_matrix"   : traceability_matrix,
            "agent_a_status"        : "complete",
            "agent_a_log"           : state["agent_a_log"] + logs,
        }

    except Exception as e:
        error_msg = f"❌ Agent A failed: {str(e)}"
        log(error_msg)
        logger.error(error_msg)

        return {
            **state,
            "agent_a_status": "failed",
            "agent_a_log"   : state["agent_a_log"] + logs,
        }


def _parse_requirements(llm_response: str) -> list[FunctionalRequirement]:
    """
    Parses LLM response into list of FunctionalRequirement objects.
    Handles common LLM response formatting issues.

    Args:
        llm_response: Raw LLM response string

    Returns:
        List of FunctionalRequirement dicts

    Raises:
        Exception: If response cannot be parsed as valid JSON
    """
    # Clean up common LLM response issues
    cleaned = llm_response.strip()

    # Remove markdown code blocks if present
    if cleaned.startswith("```"):
        lines   = cleaned.split("\n")
        # Remove first line (```json or ```) and last line (```)
        cleaned = "\n".join(lines[1:-1])

    # Remove any text before the JSON array
    start = cleaned.find("[")
    end   = cleaned.rfind("]")

    if start == -1 or end == -1:
        raise Exception(
            "LLM response does not contain a valid JSON array. "
            f"Response preview: {cleaned[:200]}"
        )

    json_str = cleaned[start:end + 1]

    try:
        requirements = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise Exception(
            f"Failed to parse requirements JSON: {e}. "
            f"JSON preview: {json_str[:200]}"
        )

    if not isinstance(requirements, list):
        raise Exception(
            "Expected a JSON array of requirements "
            f"but got: {type(requirements)}"
        )

    # Validate and fill missing fields with defaults
    validated = []
    for req in requirements:
        validated.append(_validate_requirement(req))

    return validated


def _validate_requirement(req: dict) -> FunctionalRequirement:
    """
    Validates a requirement dict and fills missing fields.

    Args:
        req: Raw requirement dict from LLM

    Returns:
        Validated FunctionalRequirement dict
    """
    return {
        "id"                        : req.get("id", "FR-UNKNOWN"),
        "feature_name"              : req.get("feature_name", "Unknown Feature"),
        "feature_module"            : req.get("feature_module", "unknown")
                                        .lower().replace(" ", "_"),
        "url_path"                  : req.get("url_path", "/"),
        "full_url"                  : req.get("full_url", ""),
        "description"               : req.get("description", ""),
        "preconditions"             : req.get("preconditions", []),
        "user_actions"              : req.get("user_actions", []),
        "expected_behavior"         : req.get("expected_behavior", []),
        "validation_error_handling" : req.get("validation_error_handling", []),
        "test_type"                 : req.get("test_type", "positive"),
    }


def _parse_requirements_safe(llm_response: str) -> list:
    """
    Safely parses requirements JSON even if truncated.
    Attempts to fix incomplete JSON by closing it properly.
    """
    cleaned = llm_response.strip()

    # Remove markdown code blocks if present
    if cleaned.startswith("```"):
        lines   = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])

    # Find start of JSON array
    start = cleaned.find("[")
    if start == -1:
        raise Exception("No JSON array found in response")

    cleaned = cleaned[start:]

    # Try parsing as-is first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to fix truncated JSON
    # Find last complete object (ends with })
    last_complete = cleaned.rfind("},")
    if last_complete == -1:
        last_complete = cleaned.rfind("}")

    if last_complete != -1:
        # Close the array after last complete object
        fixed = cleaned[:last_complete + 1] + "\n]"
        try:
            result = json.loads(fixed)
            logger.warning(
                f"JSON was truncated — recovered "
                f"{len(result)} requirements"
            )
            return result
        except json.JSONDecodeError as e:
            raise Exception(f"Could not recover truncated JSON: {e}")

    raise Exception("Could not parse requirements JSON")



def _split_pdf_into_chunks(pdf_text: str, chunk_size: int = 12000) -> list[str]:
    """
    Splits PDF text into chunks of approximately chunk_size characters.
    Splits on double newlines to avoid cutting mid-requirement.
    """
    chunks   = []
    current  = []
    size     = 0
    
    paragraphs = pdf_text.split("\n\n")
    
    for para in paragraphs:
        if size + len(para) > chunk_size and current:
            chunks.append("\n\n".join(current))
            current = [para]
            size    = len(para)
        else:
            current.append(para)
            size += len(para)
    
    if current:
        chunks.append("\n\n".join(current))
    
    return chunks
