# tools/report_generator.py
# Generates final HTML report from traceability matrix
# Called at END node after all agents complete

import json
import logging
from pathlib import Path
from datetime import datetime
from graph.state import TraceabilityRow

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def generate_html_report(
    traceability_matrix : list[TraceabilityRow],
    overall_status      : str,
    total_frs           : int,
    passed_frs          : int,
    failed_frs          : int,
    warned_frs          : int,
    skipped_frs         : int,
    base_url            : str,
    retries_used        : int,
    max_retries         : int,
) -> str:
    """
    Generates a complete HTML report from traceability matrix.
    
    Args:
        traceability_matrix: List of TraceabilityRow
        overall_status     : pass / fail / partial
        total_frs          : Total FR count
        passed_frs         : Passed FR count
        failed_frs         : Failed FR count
        warned_frs         : Warned FR count
        skipped_frs        : Skipped FR count
        base_url           : Target URL tested
        retries_used       : How many retries were used
        max_retries        : Max retries configured
        
    Returns:
        Path to generated HTML file
    """
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"final_report_{timestamp}.html"

    html = _build_html(
        traceability_matrix,
        overall_status,
        total_frs,
        passed_frs,
        failed_frs,
        warned_frs,
        skipped_frs,
        base_url,
        retries_used,
        max_retries,
        timestamp
    )

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"HTML report generated: {report_path}")
    return str(report_path)


def generate_json_report(
    traceability_matrix: list[TraceabilityRow]
) -> str:
    """
    Generates JSON report for machine reading.
    
    Args:
        traceability_matrix: List of TraceabilityRow
        
    Returns:
        Path to generated JSON file
    """
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"traceability_{timestamp}.json"

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(traceability_matrix, f, indent=2, default=str)

    logger.info(f"JSON report generated: {report_path}")
    return str(report_path)


def _get_status_icon(status: str) -> str:
    icons = {
        "pass" : "✅",
        "fail" : "❌",
        "warn" : "⚠️",
        "skip" : "⏭️",
        "none" : "✅",
        "found": "❌",
        "present": "✅",
        "missing": "❌",
        "covered": "✅",
        "partial": "⚠️",
    }
    return icons.get(status.lower(), "❓")


def _get_status_color(status: str) -> str:
    colors = {
        "pass"   : "#28a745",
        "fail"   : "#dc3545",
        "warn"   : "#ffc107",
        "skip"   : "#6c757d",
        "partial": "#ffc107",
    }
    return colors.get(status.lower(), "#6c757d")


def _build_html(
    matrix         : list[TraceabilityRow],
    overall_status : str,
    total_frs      : int,
    passed_frs     : int,
    failed_frs     : int,
    warned_frs     : int,
    skipped_frs    : int,
    base_url       : str,
    retries_used   : int,
    max_retries    : int,
    timestamp      : str
) -> str:

    # Build matrix rows
    rows_html = ""
    for row in matrix:
        fr      = row["requirement"]
        test    = row.get("generated_test")
        result  = row.get("agent_c_result")

        # Overall result
        overall = result["overall_result"] if result else "skip"
        overall_icon = _get_status_icon(overall)
        overall_color = _get_status_color(overall)

        # Agent C checks
        hallucination    = result["hallucination"]    if result else None
        missing_script   = result["missing_script"]   if result else None
        missing_scenario = result["missing_scenario"] if result else None
        coverage         = result["coverage"]         if result else None
        execution        = result["execution"]        if result else None

        # Hallucination column
        if hallucination:
            h_status = hallucination["status"]
            h_icon   = _get_status_icon(h_status)
            h_detail = (
                ", ".join(hallucination["hallucinated_locators"])
                if hallucination["hallucinated_locators"]
                else "None found"
            )
            h_cell = f'{h_icon} {h_detail}'
        else:
            h_cell = "⏭️ N/A"

        # Missing script column
        if missing_script:
            ms_icon   = _get_status_icon(missing_script["status"])
            ms_cell   = f'{ms_icon} {missing_script["status"].title()}'
        else:
            ms_cell = "⏭️ N/A"

        # Missing scenario column
        if missing_scenario:
            msc_icon = _get_status_icon(missing_scenario["status"])
            msc_cases = (
                "; ".join(missing_scenario["missing_cases"])
                if missing_scenario["missing_cases"]
                else "All covered"
            )
            msc_cell = f'{msc_icon} {msc_cases}'
        else:
            msc_cell = "⏭️ N/A"

        # Coverage column
        if coverage:
            pct      = coverage["percentage"]
            cov_icon = "✅" if pct == 100 else ("⚠️" if pct >= 50 else "❌")
            cov_cell = f'{cov_icon} {pct:.0f}%'
        else:
            cov_cell = "⏭️ N/A"

        # Execution column
        if execution:
            ex_icon  = _get_status_icon(execution["status"])
            ex_dur   = f'({execution["duration_seconds"]:.1f}s)' if execution["duration_seconds"] else ""
            ex_err   = f'<br><small style="color:red">{execution["error_message"]}</small>' if execution["error_message"] else ""
            ex_cell  = f'{ex_icon} {ex_dur}{ex_err}'
        else:
            ex_cell = "⏭️ N/A"

        # Test file
        spec_file = test["spec_file"] if test else "Not generated"

        # Code view (collapsed)
        code_html = ""
        if test and test.get("test_code"):
            code_escaped = (
                test["test_code"]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            code_html = f"""
            <tr id="code-{fr['id']}" style="display:none">
                <td colspan="10" style="background:#1e1e1e;padding:16px">
                    <pre style="color:#d4d4d4;margin:0;font-size:12px;overflow-x:auto">{code_escaped}</pre>
                </td>
            </tr>
            """

        rows_html += f"""
        <tr>
            <td><strong>{fr['id']}</strong></td>
            <td>
                <strong>{fr['feature_name']}</strong><br>
                <small style="color:#666">{fr['description'][:80]}...</small>
            </td>
            <td><small>{spec_file}</small></td>
            <td style="color:{overall_color};font-weight:bold">{overall_icon} {overall.upper()}</td>
            <td>{h_cell}</td>
            <td>{ms_cell}</td>
            <td>{msc_cell}</td>
            <td>{cov_cell}</td>
            <td>{ex_cell}</td>
            <td>
                <button onclick="toggleCode('{fr['id']}')"
                    style="padding:4px 8px;cursor:pointer;border:1px solid #ccc;
                           border-radius:4px;background:#f8f9fa;font-size:12px">
                    👁️ Code
                </button>
            </td>
        </tr>
        {code_html}
        """

    # Overall status color
    status_color = _get_status_color(overall_status)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agentic AI Tester — Final Report</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #f5f7fa; color: #333; padding: 24px; }}
        h1   {{ font-size: 24px; margin-bottom: 4px; }}
        h2   {{ font-size: 18px; margin: 24px 0 12px; }}
        .header {{ background: white; padding: 24px; border-radius: 8px;
                   box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 24px; }}
        .meta {{ color: #666; font-size: 14px; margin-top: 8px; }}
        .cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
        .card  {{ background: white; padding: 16px 24px; border-radius: 8px;
                  box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 140px; text-align: center; }}
        .card .number {{ font-size: 32px; font-weight: bold; }}
        .card .label  {{ font-size: 13px; color: #666; margin-top: 4px; }}
        .matrix {{ background: white; border-radius: 8px;
                   box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }}
        table  {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th     {{ background: #2c3e50; color: white; padding: 12px 8px;
                  text-align: left; font-weight: 600; white-space: nowrap; }}
        td     {{ padding: 10px 8px; border-bottom: 1px solid #eee; vertical-align: top; }}
        tr:hover {{ background: #f8f9ff; }}
        .status-badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px;
                         font-size: 11px; font-weight: bold; }}
        .footer {{ text-align: center; margin-top: 24px; color: #999; font-size: 12px; }}
    </style>
</head>
<body>

<div class="header">
    <h1>🤖 Agentic AI Tester — Final Report</h1>
    <div class="meta">
        <strong>Target URL:</strong> {base_url} &nbsp;|&nbsp;
        <strong>Generated:</strong> {timestamp} &nbsp;|&nbsp;
        <strong>Retries Used:</strong> {retries_used}/{max_retries} &nbsp;|&nbsp;
        <strong>Overall Status:</strong>
        <span style="color:{status_color};font-weight:bold">
            {_get_status_icon(overall_status)} {overall_status.upper()}
        </span>
    </div>
</div>

<div class="cards">
    <div class="card">
        <div class="number">{total_frs}</div>
        <div class="label">Total FRs</div>
    </div>
    <div class="card">
        <div class="number" style="color:#28a745">{passed_frs}</div>
        <div class="label">✅ Passed</div>
    </div>
    <div class="card">
        <div class="number" style="color:#dc3545">{failed_frs}</div>
        <div class="label">❌ Failed</div>
    </div>
    <div class="card">
        <div class="number" style="color:#ffc107">{warned_frs}</div>
        <div class="label">⚠️ Warned</div>
    </div>
    <div class="card">
        <div class="number" style="color:#6c757d">{skipped_frs}</div>
        <div class="label">⏭️ Skipped</div>
    </div>
    <div class="card">
        <div class="number" style="color:#17a2b8">{retries_used}/{max_retries}</div>
        <div class="label">🔄 Retries</div>
    </div>
</div>

<h2>📊 Traceability Matrix</h2>
<div class="matrix">
    <table>
        <thead>
            <tr>
                <th>FR ID</th>
                <th>Requirement</th>
                <th>Test File</th>
                <th>Result</th>
                <th>Hallucination</th>
                <th>Missing Script</th>
                <th>Missing Scenario</th>
                <th>Coverage</th>
                <th>Execution</th>
                <th>Code</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
</div>

<div class="footer">
    Generated by Agentic AI Tester &nbsp;|&nbsp;
    LangGraph + Playwright + Gemini/Claude
</div>

<script>
function toggleCode(frId) {{
    var row = document.getElementById('code-' + frId);
    if (row) {{
        row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
    }}
}}
</script>

</body>
</html>"""
