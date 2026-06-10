# prompts/agent_b_prompt.py
# Prompt templates for Agent B
# Agent B generates Playwright TypeScript test code

import json


def get_agent_b_prompt(
    feature_module   : str,
    requirements     : list,
    page_scan_text   : str,
    base_url         : str,
    is_retry         : bool = False,
    failed_fr_ids    : list[str] = None,
    fix_instructions : dict = None
) -> str:
    """
    Builds the prompt for Agent B to generate
    Playwright TypeScript test code.

    Args:
        feature_module  : e.g. "login"
        requirements    : List of FR objects for this feature
        page_scan_text  : Formatted page scan output from page_scanner.py
        base_url        : Target base URL
        is_retry        : True if this is a retry attempt
        failed_fr_ids   : FR IDs that need fixing (retry only)
        fix_instructions: Dict of fr_id → fix instructions (retry only)

    Returns:
        Complete prompt string for LLM
    """
    reqs_json = json.dumps(requirements, indent=2)

    # Build retry context if applicable
    retry_context = ""
    if is_retry and failed_fr_ids:
        fix_details = ""
        if fix_instructions:
            for fr_id, instruction in fix_instructions.items():
                if fr_id in failed_fr_ids:
                    fix_details += f"\n  {fr_id}: {instruction}"
        retry_context = f"""
⚠️  RETRY MODE — Fix only these failing FRs: {', '.join(failed_fr_ids)}
Fix instructions from Agent C:
{fix_details}

Generate COMPLETE fixed test code for ONLY the failing FRs listed above.
"""

    return f"""You are Agent B — a Playwright test automation engineer.

Your job is to generate a complete, executable TypeScript Playwright test file
for the feature: {feature_module.upper()}

{'═' * 60}
{'⚠️  RETRY INSTRUCTIONS' if is_retry else 'TASK'}
{retry_context if is_retry else 'Generate Playwright tests for ALL requirements listed below.'}
{'═' * 60}

BASE URL: {base_url}

{'═' * 60}
FUNCTIONAL REQUIREMENTS TO TEST:
{reqs_json}
{'═' * 60}

{'═' * 60}
LIVE PAGE ELEMENTS (use these EXACT locators):
{page_scan_text}
{'═' * 60}

CODE GENERATION RULES:

1. FILE STRUCTURE:
   - Use TypeScript with @playwright/test
   - One describe() block per feature module
   - One test() block per FR ID
   - Name each test EXACTLY as: 'FR-XX-XX: <feature_name>'
     e.g. test('FR-FA-01: Login Form Rendering', ...)

2. LOCATORS — USE BOTH SOURCES (read requirements + page scan before writing any locator):

   SOURCE 1 — Requirements text (expected_behavior + user_actions listed above):
   Read the element labels and roles mentioned in the requirements and map them:
   • "input field labeled Username"       → page.getByLabel('Username')
   • "input field labeled Password"       → page.getByLabel('Password')
   • "button labeled Login"               → page.getByRole('button', {{ name: 'Login' }})
   • "Click for JS Alert" button          → page.getByRole('button', {{ name: 'Click for JS Alert' }})
   • heading "Login Page"                 → page.getByRole('heading', {{ name: 'Login Page' }})
   • "checkbox 1" label                   → page.getByLabel('checkbox 1')
   • link text "Click Here"               → page.getByRole('link', {{ name: 'Click Here' }})
   • "Please select an option" dropdown   → page.getByRole('combobox')
   • "Upload" button                      → page.getByRole('button', {{ name: 'Upload' }})

   SOURCE 2 — Live Page Elements (page scan above):
   Use CSS selectors from the scan as fallback when no label/role exists in requirements:
   • page.locator('#id')                  for elements with a known ID
   • page.locator("input[name='x']")      when only name attribute is available
   • page.locator("select")               for dropdowns with no label

   PRIORITY RULE:
   • ALWAYS prefer SOURCE 1 (getByLabel / getByRole / getByText) — they are robust and match real UI labels
   • Use SOURCE 2 (CSS selectors) only when no semantic locator is derivable from requirements
   • NEVER invent a locator not derivable from either source
   • NEVER use page.locator('.className') unless it is the only option

3. TEST STRUCTURE per FR:
   - Navigate to the correct URL first: await page.goto('{base_url}' + url_path)
   - Perform user actions from the FR
   - Assert ALL expected behaviors from the FR
   - For negative tests: assert error messages appear
   - For edge cases: handle conditional logic with try/catch if needed

4. ASSERTIONS:
   - Use expect() for every expected behavior
   - Use toBeVisible() for UI elements
   - Use toContainText() for text content
   - Use toHaveURL() for navigation assertions
   - Use toBeChecked() / not.toBeChecked() for checkboxes
   - Use toHaveValue() for dropdowns and inputs

5. WAITS:
   - Use await page.waitForLoadState('domcontentloaded') after navigation
   - Use await expect(locator).toBeVisible() instead of arbitrary waits
   - Never use page.waitForTimeout() unless absolutely necessary

6. IMPORTS:
   - Always include: import {{ test, expect }} from '@playwright/test';
   - No other imports needed

7. TYPESCRIPT:
   - Use async/await throughout
   - Use const for variables
   - No any types unless necessary

OUTPUT FORMAT:
Return ONLY the TypeScript code.
No explanation. No markdown. No code blocks.
Just raw TypeScript starting with: import {{ test, expect }} from '@playwright/test';

EXAMPLE OUTPUT STRUCTURE:
import {{ test, expect }} from '@playwright/test';

test.describe('{feature_module} tests', () => {{

  test('FR-XX-01: Feature Name', async ({{ page }}) => {{
    await page.goto('{base_url}/path');
    await page.waitForLoadState('domcontentloaded');
    // assertions here
  }});

  test('FR-XX-02: Another Feature', async ({{ page }}) => {{
    // test code here
  }});

}});
"""


def get_agent_b_retry_prompt(
    feature_module   : str,
    original_code    : str,
    failed_fr_ids    : list[str],
    fix_instructions : dict,
    page_scan_text   : str,
    base_url         : str
) -> str:
    """
    Builds a focused retry prompt for Agent B.
    Used when Agent C sends back specific fix instructions.

    Args:
        feature_module  : e.g. "login"
        original_code   : The original generated spec code
        failed_fr_ids   : FR IDs that need fixing
        fix_instructions: Dict of fr_id → fix instructions
        page_scan_text  : Fresh page scan output
        base_url        : Target base URL

    Returns:
        Complete prompt string for LLM
    """
    # Build fix instructions text
    fix_text = ""
    for fr_id, instruction in fix_instructions.items():
        if fr_id in failed_fr_ids:
            fix_text += f"\n{fr_id}:\n  {instruction}\n"

    return f"""You are Agent B — a Playwright test automation engineer fixing failing tests.

You previously generated a Playwright test file that had issues.
Agent C reviewed and executed the tests and found problems.
Fix ONLY the failing tests — keep passing tests unchanged.

{'═' * 60}
FAILING FR IDs TO FIX:
{', '.join(failed_fr_ids)}
{'═' * 60}

FIX INSTRUCTIONS FROM AGENT C:
{fix_text}
{'═' * 60}

ORIGINAL CODE (keep passing tests, fix failing ones):
{original_code}
{'═' * 60}

FRESH PAGE SCAN (use these EXACT locators):
{page_scan_text}
{'═' * 60}

BASE URL: {base_url}

RULES:
1. Keep ALL passing tests exactly as they are
2. Fix ONLY the tests for failing FR IDs
3. LOCATOR PRIORITY when fixing:
   - First: use getByLabel / getByRole / getByText derived from requirement text (e.g. "labeled Username" → getByLabel('Username'))
   - Second: use CSS selectors from the fresh page scan above as fallback
   - Never invent a locator not found in either source
4. Follow the same code structure as the original
5. Each test must still be named: 'FR-XX-XX: <feature_name>'

OUTPUT FORMAT:
Return ONLY the complete fixed TypeScript file.
No explanation. No markdown. No code blocks.
Return the COMPLETE file including both fixed and unchanged tests.
"""
