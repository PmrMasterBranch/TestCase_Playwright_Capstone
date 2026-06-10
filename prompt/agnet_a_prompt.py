# prompts/agent_a_prompt.py
# Prompt templates for Agent A
# Agent A extracts structured FRs from PDF text

def get_agent_a_prompt(pdf_text: str, base_url: str) -> str:
    """
    Builds the prompt for Agent A to extract
    functional requirements from PDF text.

    Args:
        pdf_text: Full text extracted from SRS PDF
        base_url: Target base URL for the application

    Returns:
        Complete prompt string for LLM
    """
    return f"""You are Agent A — a requirements extraction specialist.

Your job is to read a Software Requirements Specification (SRS) document 
and extract ALL functional requirements into a structured JSON format.

═══════════════════════════════════════════════════════════════
BASE URL OF APPLICATION UNDER TEST:
{base_url}
═══════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════
SRS DOCUMENT TEXT:
{pdf_text}
═══════════════════════════════════════════════════════════════

EXTRACTION RULES:
1. Extract EVERY functional requirement (FR-XX-XX format)
2. Do NOT skip any FR even if it seems simple
3. For each FR extract ALL fields listed below
4. Determine test_type based on what is being tested:
   - "positive"   : happy path, valid inputs, successful scenarios
   - "negative"   : error handling, invalid inputs, failure scenarios
   - "edge_case"  : boundary conditions, random behavior, optional states
5. url_path must start with / e.g. /login /checkboxes
6. full_url = base_url + url_path
7. feature_module must be lowercase with underscores e.g. login, checkboxes
8. Keep expected_behavior as separate list items — one behavior per item
9. Keep user_actions as separate steps — one action per step

OUTPUT FORMAT:
Return ONLY a valid JSON array. No explanation. No markdown. No code blocks.
Just the raw JSON array starting with [ and ending with ]

Each item in the array must follow this exact structure:
{{
  "id"                        : "FR-FA-01",
  "feature_name"              : "Login Form Rendering",
  "feature_module"            : "login",
  "url_path"                  : "/login",
  "full_url"                  : "{base_url}/login",
  "description"               : "Display username and password fields with a Login button",
  "preconditions"             : [
    "User navigates to /login"
  ],
  "user_actions"              : [
    "Load /login page"
  ],
  "expected_behavior"         : [
    "Page displays heading indicating Login Page",
    "Page displays input field labeled Username",
    "Page displays input field labeled Password",
    "Page displays Login button"
  ],
  "validation_error_handling" : [
    "No validation on initial page load"
  ],
  "test_type"                 : "positive"
}}

IMPORTANT:
- Return ONLY the JSON array
- No text before or after the JSON
- No markdown code blocks
- Ensure valid JSON — double quotes for all strings
- Every FR from the SRS must appear in the output
"""


def get_agent_a_filter_prompt(
    all_requirements : list,
    selected_features: list[str]
) -> str:
    """
    Builds prompt to filter requirements by selected features.
    Used after full extraction to get only selected FRs.

    Args:
        all_requirements : Full list of extracted FRs
        selected_features: Feature modules selected by user

    Returns:
        Complete prompt string for LLM
    """
    import json
    reqs_json = json.dumps(all_requirements, indent=2)
    features  = ", ".join(selected_features)

    return f"""You are a requirements filter.

Given a list of functional requirements and a list of selected feature modules,
return ONLY the requirements that belong to the selected features.

SELECTED FEATURES:
{features}

ALL REQUIREMENTS:
{reqs_json}

RULES:
1. Keep only requirements where feature_module matches one of the selected features
2. Return the SAME JSON structure — do not modify any fields
3. Return ONLY a valid JSON array
4. No explanation, no markdown, no code blocks

Return ONLY the filtered JSON array.
"""
