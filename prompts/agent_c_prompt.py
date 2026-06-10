# prompts/agent_c_prompt.py
# Prompt templates for Agent C
# Agent C reviews generated Playwright code
# Checks for hallucinations, missing scripts,
# missing scenarios and coverage

import json


def get_hallucination_check_prompt(
    spec_code      : str,
    page_scan_text : str,
    fr_ids         : list[str]
) -> str:
    """
    Builds prompt to check for hallucinated locators.
    Compares locators used in spec against real page scan.

    Args:
        spec_code     : Generated TypeScript spec code
        page_scan_text: Formatted page scan from page_scanner.py
        fr_ids        : FR IDs in this spec file

    Returns:
        Complete prompt string for LLM
    """
    return f"""You are Agent C — a Playwright test code reviewer.

Your task is to check for HALLUCINATED LOCATORS in the generated test code.
A hallucinated locator is one that was invented by the code generator
and does NOT exist on the actual page.

{'═' * 60}
ACTUAL PAGE ELEMENTS (source of truth):
{page_scan_text}
{'═' * 60}

GENERATED TEST CODE TO REVIEW:
{spec_code}
{'═' * 60}

FR IDs in this file: {', '.join(fr_ids)}

INSTRUCTIONS:
1. Extract every locator used in the test code
   (page.locator(), getByRole(), getByLabel(), getByText(), etc.)
2. Check each locator against the ACTUAL PAGE ELEMENTS above
3. Mark a locator as hallucinated if it does NOT appear in page elements
4. For each hallucinated locator suggest the correct one from page elements

OUTPUT FORMAT:
Return ONLY valid JSON. No explanation. No markdown. No code blocks.

{{
  "fr_results": [
    {{
      "fr_id"                  : "FR-FA-01",
      "status"                 : "none",
      "hallucinated_locators"  : [],
      "suggested_fixes"        : []
    }},
    {{
      "fr_id"                  : "FR-FA-02",
      "status"                 : "found",
      "hallucinated_locators"  : ["#loginBtn", ".submit-btn"],
      "suggested_fixes"        : ["button[type='submit']", "button[type='submit']"]
    }}
  ]
}}

Status values:
  "none"  = no hallucinations found
  "found" = hallucinations found

Return ONLY the JSON object above.
"""


def get_missing_scenario_check_prompt(
    spec_code    : str,
    requirements : list
) -> str:
    """
    Builds prompt to check for missing test scenarios.
    Verifies all positive, negative and edge cases are covered.

    Args:
        spec_code   : Generated TypeScript spec code
        requirements: List of FR objects for this feature

    Returns:
        Complete prompt string for LLM
    """
    reqs_json = json.dumps(requirements, indent=2)

    return f"""You are Agent C — a Playwright test coverage reviewer.

Your task is to check if the generated test code covers ALL required scenarios
for each functional requirement.

{'═' * 60}
FUNCTIONAL REQUIREMENTS (what MUST be tested):
{reqs_json}
{'═' * 60}

GENERATED TEST CODE (what WAS tested):
{spec_code}
{'═' * 60}

INSTRUCTIONS:
For each FR:
1. Read the expected_behavior list — every item must have an assertion
2. Read the validation_error_handling list — every item must have a test
3. Check the test_type:
   - "positive"  : must test the happy path
   - "negative"  : must test error/failure scenarios
   - "edge_case" : must handle boundary conditions
4. List any missing cases

COVERAGE CALCULATION:
- Count total items in expected_behavior + validation_error_handling
- Count how many are actually tested in the code
- Coverage % = (tested / total) * 100

OUTPUT FORMAT:
Return ONLY valid JSON. No explanation. No markdown. No code blocks.

{{
  "fr_results": [
    {{
      "fr_id"              : "FR-FA-01",
      "status"             : "covered",
      "missing_cases"      : [],
      "coverage_percentage": 100.0,
      "behaviors_covered"  : 4,
      "total_behaviors"    : 4,
      "uncovered_behaviors": []
    }},
    {{
      "fr_id"              : "FR-FA-02",
      "status"             : "partial",
      "missing_cases"      : [
        "Missing test for wrong password scenario",
        "Missing assertion for staying on /login after failed login"
      ],
      "coverage_percentage": 60.0,
      "behaviors_covered"  : 3,
      "total_behaviors"    : 5,
      "uncovered_behaviors": [
        "System shall display error message for wrong credentials",
        "System shall not navigate to secure area"
      ]
    }}
  ]
}}

Status values:
  "covered" = all scenarios tested (100%)
  "partial" = some scenarios missing (1-99%)
  "missing" = no scenarios tested (0%)

Return ONLY the JSON object above.
"""


def get_fix_instructions_prompt(
    requirements        : list,
    hallucination_results: dict,
    scenario_results    : dict,
    execution_results   : dict,
    spec_code           : str
) -> str:
    """
    Builds prompt to generate specific fix instructions
    for Agent B to use on retry.

    Args:
        requirements        : List of FR objects
        hallucination_results: Hallucination check results per FR
        scenario_results    : Missing scenario results per FR
        execution_results   : Execution results per FR
        spec_code           : Original generated code

    Returns:
        Complete prompt string for LLM
    """
    reqs_json     = json.dumps(requirements, indent=2)
    hall_json     = json.dumps(hallucination_results, indent=2)
    scenario_json = json.dumps(scenario_results, indent=2)
    exec_json     = json.dumps(execution_results, indent=2)

    return f"""You are Agent C — generating fix instructions for Agent B.

Based on the review results below, generate clear and specific
fix instructions for each failing FR so Agent B can fix the code.

{'═' * 60}
ORIGINAL REQUIREMENTS:
{reqs_json}
{'═' * 60}

HALLUCINATION CHECK RESULTS:
{hall_json}
{'═' * 60}

MISSING SCENARIO RESULTS:
{scenario_json}
{'═' * 60}

EXECUTION RESULTS:
{exec_json}
{'═' * 60}

ORIGINAL CODE:
{spec_code}
{'═' * 60}

INSTRUCTIONS:
For each FR that has issues (hallucinations, missing scenarios, or failed execution):
1. Identify the root cause
2. Write specific actionable fix instructions
3. Include exact locators to use if applicable
4. Include exact assertions to add if missing scenarios
5. Be very specific — Agent B will follow these instructions exactly

OUTPUT FORMAT:
Return ONLY valid JSON. No explanation. No markdown. No code blocks.

{{
  "failed_fr_ids"   : ["FR-FA-02", "FR-FA-03"],
  "fix_instructions": {{
    "FR-FA-02": "Fix locator: Replace page.locator('#loginBtn') with page.locator(\"button[type='submit']\"). Add missing assertion: await expect(page).toHaveURL('/secure') after successful login.",
    "FR-FA-03": "Script is missing entirely. Generate a new test that: navigates to /login, enters wrong credentials (username: 'wronguser', password: 'wrongpass'), clicks login button, asserts error message is visible using page.locator('.flash.error') or similar error locator from page scan."
  }}
}}

Return ONLY the JSON object above.
"""
