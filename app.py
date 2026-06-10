# app.py
# Streamlit UI Entry Point
# Agentic AI Tester — Main Application

import csv
import json
import logging
import tempfile
import streamlit as st
from pathlib import Path
from graph.workflow import build_bc_workflow, create_initial_state
from agents.agent_a import run_agent_a
from graph.state import TraceabilityRow
from tools.report_generator import generate_html_report, generate_json_report

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title = "Agentic AI Tester",
    page_icon  = "🤖",
    layout     = "wide"
)

REQUIREMENTS_DIR = Path(__file__).parent / "requirements"


# ─────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────
def init_session_state():
    defaults = {
        # phase: config | discovery | selection | testing | results
        "phase"            : "config",
        "saved_provider"   : "gemini",
        "saved_api_key"    : "",
        "saved_url"        : "https://the-internet.herokuapp.com",
        "saved_pdf_path"   : "",
        "saved_retries"    : 1,
        "agent_a_state"    : None,
        "req_json_path"    : None,
        "req_csv_path"     : None,
        "selected_modules" : [],
        "bc_graph"         : None,
        "final_state"      : None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ─────────────────────────────────────────────────────────────
# SAVE REQUIREMENTS TO DISK
# ─────────────────────────────────────────────────────────────
def save_requirements_to_disk(all_requirements: list) -> dict:
    """
    Saves extracted requirements as JSON and CSV under requirements/.
    Returns dict with {"json": path, "csv": path}.
    """
    REQUIREMENTS_DIR.mkdir(exist_ok=True)

    json_path = REQUIREMENTS_DIR / "extracted_requirements.json"
    csv_path  = REQUIREMENTS_DIR / "extracted_requirements.csv"

    # ── JSON ──────────────────────────────────────────────────
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_requirements, f, indent=2)

    # ── CSV ───────────────────────────────────────────────────
    fieldnames = [
        "id", "feature_name", "feature_module", "url_path",
        "description", "test_type",
        "preconditions", "user_actions",
        "expected_behavior", "validation_error_handling",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for fr in all_requirements:
            writer.writerow({
                "id"                       : fr.get("id", ""),
                "feature_name"             : fr.get("feature_name", ""),
                "feature_module"           : fr.get("feature_module", ""),
                "url_path"                 : fr.get("url_path", ""),
                "description"              : fr.get("description", ""),
                "test_type"                : fr.get("test_type", ""),
                "preconditions"            : " | ".join(fr.get("preconditions", [])),
                "user_actions"             : " | ".join(fr.get("user_actions", [])),
                "expected_behavior"        : " | ".join(fr.get("expected_behavior", [])),
                "validation_error_handling": " | ".join(fr.get("validation_error_handling", [])),
            })

    logger.info(f"Requirements saved → {json_path}, {csv_path}")
    return {"json": str(json_path), "csv": str(csv_path)}


# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────
def render_header():
    st.title("🤖 Agentic AI Tester")
    st.markdown(
        "Multi-agent system that extracts requirements from a PDF, "
        "generates Playwright tests, and validates them automatically."
    )
    st.divider()


# ─────────────────────────────────────────────────────────────
# PHASE 1 — CONFIG + EXTRACT REQUIREMENTS
# ─────────────────────────────────────────────────────────────
def render_phase1():
    st.subheader("⚙️ Step 1 — Configure & Extract Requirements")
    st.info(
        "Upload your SRS PDF and provide the target URL. "
        "Click **Extract Requirements** to let Agent A discover all features."
    )

    col1, col2 = st.columns(2)

    with col1:
        llm_provider = st.radio(
            "Select LLM Provider",
            options    = ["Gemini Flash 2.5 (Free)", "Claude (Paid)"],
            horizontal = True,
        )
        provider_key = "gemini" if "Gemini" in llm_provider else "claude"

        if provider_key == "gemini":
            api_key = st.text_input(
                "Gemini API Key",
                type        = "password",
                placeholder = "Enter your Google AI Studio API key",
            )
            st.warning("⚠️ Gemini free tier has RPM limits. Delays applied between calls.")
        else:
            api_key = st.text_input(
                "Claude API Key",
                type        = "password",
                placeholder = "Enter your Anthropic API key",
            )

    with col2:
        target_url = st.text_input(
            "Target URL",
            value       = st.session_state.saved_url,
            placeholder = "https://your-app-url.com",
        )
        uploaded_pdf = st.file_uploader("Upload SRS PDF", type=["pdf"])

    st.divider()

    if st.button("🔍 Extract Requirements", type="primary"):
        errors = []
        if not api_key:      errors.append("API Key is required")
        if not target_url:   errors.append("Target URL is required")
        if not uploaded_pdf: errors.append("SRS PDF is required")

        if errors:
            for err in errors:
                st.error(f"❌ {err}")
        else:
            st.session_state.saved_provider = provider_key
            st.session_state.saved_api_key  = api_key
            st.session_state.saved_url      = target_url

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_pdf.read())
                st.session_state.saved_pdf_path = tmp.name

            st.session_state.phase = "discovery"
            st.rerun()


# ─────────────────────────────────────────────────────────────
# DISCOVERY — AGENT A RUNNING
# ─────────────────────────────────────────────────────────────
def render_discovery():
    st.subheader("🔍 Extracting Requirements...")
    st.info("Agent A is reading the PDF. This may take a minute.")

    with st.spinner("Agent A is running..."):
        try:
            initial_state = create_initial_state(
                llm_provider      = st.session_state.saved_provider,
                api_key           = st.session_state.saved_api_key,
                base_url          = st.session_state.saved_url,
                max_retries       = 1,
                selected_features = [],   # empty → Agent A returns all FRs
                pdf_path          = st.session_state.saved_pdf_path,
            )
            state = run_agent_a(initial_state)

            if state["agent_a_status"] == "failed":
                st.error("❌ Agent A failed. Check your API key and PDF.")
                if st.button("← Back"):
                    st.session_state.phase = "config"
                    st.rerun()
                return

            # Save requirements to disk
            paths = save_requirements_to_disk(state["all_requirements"])
            st.session_state.req_json_path = paths["json"]
            st.session_state.req_csv_path  = paths["csv"]
            st.session_state.agent_a_state = state
            st.session_state.phase         = "selection"
            st.rerun()

        except Exception as e:
            st.error(f"❌ Error: {e}")
            logger.error(f"Discovery error: {e}", exc_info=True)
            if st.button("← Back"):
                st.session_state.phase = "config"
                st.rerun()


# ─────────────────────────────────────────────────────────────
# PHASE 2 — FEATURE SELECTION
# ─────────────────────────────────────────────────────────────
def render_feature_selection():
    agent_a_state    = st.session_state.agent_a_state
    all_requirements = agent_a_state.get("all_requirements", [])

    # Build unique feature list from Agent A's output
    seen     = set()
    features = []
    for fr in all_requirements:
        module = fr["feature_module"]
        if module not in seen:
            seen.add(module)
            features.append({
                "module"      : module,
                "display_name": fr["feature_name"].split("–")[0].strip(),
                "fr_count"    : sum(
                    1 for r in all_requirements
                    if r["feature_module"] == module
                ),
            })

    st.subheader("✅ Step 2 — Select Features to Test")
    st.success(
        f"Agent A extracted **{len(all_requirements)} requirements** "
        f"across **{len(features)} features** from the PDF."
    )

    # ── Download extracted requirements ────────────────────────
    st.markdown("**📂 Extracted Requirements (saved to disk):**")
    dl_col1, dl_col2, dl_col3 = st.columns([2, 2, 4])

    with dl_col1:
        if st.session_state.req_json_path:
            with open(st.session_state.req_json_path, "rb") as f:
                st.download_button(
                    label     = "⬇️ Download JSON",
                    data      = f.read(),
                    file_name = "extracted_requirements.json",
                    mime      = "application/json",
                )
    with dl_col2:
        if st.session_state.req_csv_path:
            with open(st.session_state.req_csv_path, "rb") as f:
                st.download_button(
                    label     = "⬇️ Download CSV",
                    data      = f.read(),
                    file_name = "extracted_requirements.csv",
                    mime      = "text/csv",
                )
    with dl_col3:
        st.caption(
            f"Files also saved locally at:  \n"
            f"`{st.session_state.req_json_path}`  \n"
            f"`{st.session_state.req_csv_path}`"
        )

    # ── Agent A log ────────────────────────────────────────────
    with st.expander("📋 View Agent A Extraction Log"):
        logs = agent_a_state.get("agent_a_log", [])
        st.code("\n".join(logs) if logs else "No logs.", language="text")

    st.divider()
    st.info("Select which features you want to generate and run Playwright tests for.")

    # ── Select All / Clear All ─────────────────────────────────
    col_all, col_clear, _ = st.columns([1, 1, 6])
    with col_all:
        if st.button("✅ Select All"):
            for f in features:
                st.session_state[f"feat_{f['module']}"] = True
    with col_clear:
        if st.button("🗑️ Clear All"):
            for f in features:
                st.session_state[f"feat_{f['module']}"] = False

    # ── Feature checkboxes ─────────────────────────────────────
    cols = st.columns(3)
    selected_modules = []

    for i, feat in enumerate(features):
        checked = cols[i % 3].checkbox(
            f"{feat['display_name']}  `({feat['fr_count']} FRs)`",
            value = st.session_state.get(f"feat_{feat['module']}", i < 3),
            key   = f"feat_{feat['module']}",
        )
        if checked:
            selected_modules.append(feat["module"])

    st.divider()

    # ── Retries + Run button ───────────────────────────────────
    col_cfg, col_btn = st.columns([3, 2])
    with col_cfg:
        max_retries = st.slider(
            "Max Retries (Agent C → Agent B fix cycles)",
            min_value = 1,
            max_value = 5,
            value     = st.session_state.saved_retries,
        )
    with col_btn:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        run_clicked = st.button(
            "🚀 Run Tests",
            type                = "primary",
            use_container_width = True,
            disabled            = len(selected_modules) == 0,
        )

    if len(selected_modules) == 0:
        st.warning("Select at least one feature to continue.")

    if st.button("← Change PDF / URL"):
        st.session_state.phase         = "config"
        st.session_state.agent_a_state = None
        st.session_state.req_json_path = None
        st.session_state.req_csv_path  = None
        st.rerun()

    if run_clicked and selected_modules:
        st.session_state.saved_retries   = max_retries
        st.session_state.selected_modules = selected_modules
        st.session_state.phase            = "testing"
        st.rerun()


# ─────────────────────────────────────────────────────────────
# TESTING — B→C PIPELINE
# ─────────────────────────────────────────────────────────────
def render_testing():
    selected = st.session_state.selected_modules
    st.subheader("🤖 Running Tests...")
    st.info(
        f"Agent B → Agent C loop running for **{len(selected)} features**. "
        f"Max retries: **{st.session_state.saved_retries}**"
    )

    log_placeholder = st.empty()

    try:
        with st.spinner("Pipeline running..."):
            final_state = _run_bc_pipeline(log_placeholder)

        st.session_state.final_state = final_state
        st.session_state.phase       = "results"
        st.rerun()

    except Exception as e:
        st.error(f"❌ Pipeline error: {e}")
        logger.error(f"Pipeline error: {e}", exc_info=True)
        if st.button("← Back to Feature Selection"):
            st.session_state.phase = "selection"
            st.rerun()


def _run_bc_pipeline(log_placeholder):
    agent_a_state    = st.session_state.agent_a_state
    selected_modules = st.session_state.selected_modules
    max_retries      = st.session_state.saved_retries

    selected_requirements = [
        fr for fr in agent_a_state["all_requirements"]
        if fr["feature_module"] in selected_modules
    ]

    traceability_matrix: list[TraceabilityRow] = [
        {
            "fr_id"         : fr["id"],
            "requirement"   : fr,
            "generated_test": None,
            "agent_c_result": None,
            "retry_history" : [],
        }
        for fr in selected_requirements
    ]

    bc_state = {
        **agent_a_state,
        "selected_features"    : selected_modules,
        "selected_requirements": selected_requirements,
        "traceability_matrix"  : traceability_matrix,
        "max_retries"          : max_retries,
        "generated_tests"      : {},
        "spec_files"           : {},
        "page_scan_results"    : {},
        "agent_b_status"       : "pending",
        "agent_b_log"          : [],
        "agent_c_results"      : {},
        "failed_fr_ids"        : [],
        "agent_c_status"       : "pending",
        "agent_c_log"          : [],
        "current_retry"        : 0,
        "retry_triggered"      : False,
        "final_report_path"    : None,
        "overall_status"       : None,
        "total_frs"            : None,
        "passed_frs"           : None,
        "failed_frs"           : None,
        "warned_frs"           : None,
        "skipped_frs"          : None,
    }

    if st.session_state.bc_graph is None:
        st.session_state.bc_graph = build_bc_workflow()

    all_logs    = []
    final_state = None

    for event in st.session_state.bc_graph.stream(bc_state, {"recursion_limit": 50}):
        node_name  = list(event.keys())[0]
        node_state = event[node_name]

        if node_name == "agent_b":
            new_logs = node_state.get("agent_b_log", [])
        elif node_name == "agent_c":
            new_logs = node_state.get("agent_c_log", [])
            retry  = node_state.get("current_retry", 0)
            max_r  = node_state.get("max_retries", 1)
            failed = node_state.get("failed_fr_ids", [])
            if failed and retry <= max_r:
                new_logs.append(
                    f"[Graph]   Retry {retry}/{max_r} triggered → "
                    f"Sending {len(failed)} FRs back to Agent B"
                )
        else:
            new_logs = []

        all_logs.extend(new_logs)
        log_placeholder.code("\n".join(all_logs), language="text")
        final_state = node_state

    return final_state


# ─────────────────────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────────────────────
def render_results():
    state = st.session_state.final_state
    st.success("✅ Pipeline complete!")

    # Activity feed
    st.subheader("🤖 Agent Activity")
    all_logs = (
        state.get("agent_a_log", []) +
        state.get("agent_b_log", []) +
        state.get("agent_c_log", [])
    )
    st.code("\n".join(all_logs) if all_logs else "No logs.", language="text")
    st.divider()

    # Summary cards
    st.subheader("📊 Summary")
    total   = state.get("total_frs", 0) or 0
    passed  = state.get("passed_frs", 0) or 0
    failed  = state.get("failed_frs", 0) or 0
    warned  = state.get("warned_frs", 0) or 0
    skipped = state.get("skipped_frs", 0) or 0
    retries = state.get("current_retry", 0)
    max_ret = state.get("max_retries", 1)
    overall = state.get("overall_status") or "unknown"
    status_color = {"pass": "🟢", "partial": "🟡", "fail": "🔴", "unknown": "⚪"}.get(overall, "⚪")

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("📋 Total FRs", total)
    c2.metric("✅ Passed",     passed)
    c3.metric("❌ Failed",     failed)
    c4.metric("⚠️ Warned",    warned)
    c5.metric("⏭️ Skipped",  skipped)
    c6.metric("🔄 Retries",   f"{retries}/{max_ret}")
    c7.metric("🏁 Overall",   f"{status_color} {overall.upper()}")
    st.divider()

    # Traceability matrix
    _render_traceability_matrix(state)
    st.divider()

    # Exports
    _render_exports(state)
    st.divider()

    # Navigation
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Test Different Features (same PDF)"):
            st.session_state.phase       = "selection"
            st.session_state.final_state = None
            st.rerun()
    with col2:
        if st.button("📄 Use Different PDF"):
            st.session_state.phase         = "config"
            st.session_state.agent_a_state = None
            st.session_state.final_state   = None
            st.session_state.req_json_path = None
            st.session_state.req_csv_path  = None
            st.rerun()


def _render_traceability_matrix(state: dict):
    st.subheader("📋 Traceability Matrix")
    matrix = state.get("traceability_matrix", [])
    if not matrix:
        st.info("No results yet.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        filter_result = st.selectbox("Filter by Result", ["All", "✅ Pass", "❌ Fail", "⚠️ Warn", "⏭️ Skip"])
    with col2:
        filter_hallucination = st.selectbox("Filter by Hallucination", ["All", "✅ None", "❌ Found"])
    with col3:
        search_fr = st.text_input("Search FR ID", placeholder="e.g. FR-FA-01")

    for col, hdr in zip(
        st.columns([1, 2, 1.5, 1, 1.5, 1.5, 2, 1, 1.5, 0.4, 0.4]),
        ["FR ID", "Requirement", "Test File", "Result", "Hallucination",
         "Missing Script", "Missing Scenario", "Coverage", "Execution", "Code", "📸"]
    ):
        col.markdown(f"**{hdr}**")
    st.divider()

    for row in matrix:
        fr     = row["requirement"]
        test   = row.get("generated_test")
        result = row.get("agent_c_result")
        overall = (result["overall_result"] if result else "skip") or "skip"

        filter_map = {"✅ Pass": "pass", "❌ Fail": "fail", "⚠️ Warn": "warn", "⏭️ Skip": "skip"}
        if filter_result != "All" and overall != filter_map.get(filter_result, ""):
            continue
        if filter_hallucination != "All" and result:
            h_status = result["hallucination"]["status"]
            if filter_hallucination == "✅ None" and h_status != "none": continue
            if filter_hallucination == "❌ Found" and h_status != "found": continue
        if search_fr and search_fr.upper() not in fr["id"].upper():
            continue

        overall_icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}.get(overall, "❓")
        spec_file    = test["spec_file"] if test else "—"
        h_icon  = "—"
        ms_icon = "—"
        msc_icon= "—"
        cov_text= "—"
        ex_text = "—"

        if result:
            h = result["hallucination"]
            h_icon = "✅ None" if h["status"] == "none" else f"❌ {', '.join(h['hallucinated_locators'][:1])}"
            ms = result["missing_script"]
            ms_icon = "✅ Present" if ms["status"] == "present" else "❌ Missing"
            msc = result["missing_scenario"]
            msc_icon = {"covered": "✅ Covered", "partial": "⚠️ Partial", "missing": "❌ Missing"}.get(msc["status"], "—")
            pct = result["coverage"]["percentage"]
            cov_text = f"{'✅' if pct==100 else '⚠️' if pct>=50 else '❌'} {pct:.0f}%"
            ex = result["execution"]
            ex_icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}.get(ex["status"], "—")
            ex_dur  = f"{ex['duration_seconds']:.1f}s" if ex.get("duration_seconds") else ""
            ex_text = f"{ex_icon} {ex_dur}"

        screenshot_path = None
        if result and result.get("execution", {}).get("screenshot_path"):
            screenshot_path = result["execution"]["screenshot_path"]

        row_cols = st.columns([1, 2, 1.5, 1, 1.5, 1.5, 2, 1, 1.5, 0.4, 0.4])
        row_cols[0].markdown(f"**{fr['id']}**")
        row_cols[1].markdown(
            f"**{fr['feature_name']}**  \n<small>{fr['description'][:60]}...</small>",
            unsafe_allow_html=True
        )
        row_cols[2].markdown(f"`{spec_file}`")
        row_cols[3].markdown(f"{overall_icon} **{overall.upper()}**")
        row_cols[4].markdown(h_icon)
        row_cols[5].markdown(ms_icon)
        row_cols[6].markdown(msc_icon)
        row_cols[7].markdown(cov_text)
        row_cols[8].markdown(ex_text)

        with row_cols[9]:
            if test and test.get("test_code"):
                if st.button("👁️", key=f"code_{fr['id']}"):
                    st.session_state[f"show_code_{fr['id']}"] = (
                        not st.session_state.get(f"show_code_{fr['id']}", False)
                    )

        with row_cols[10]:
            if screenshot_path and Path(screenshot_path).exists():
                if st.button("📸", key=f"shot_{fr['id']}"):
                    st.session_state[f"show_shot_{fr['id']}"] = (
                        not st.session_state.get(f"show_shot_{fr['id']}", False)
                    )

        if st.session_state.get(f"show_shot_{fr['id']}", False) and screenshot_path:
            with st.expander(f"📸 {fr['id']} — Browser Screenshot", expanded=True):
                st.image(screenshot_path, use_container_width=True)

        if st.session_state.get(f"show_code_{fr['id']}", False) and test:
            with st.expander(f"📝 {fr['id']} — Generated Code", expanded=True):
                if test.get("previous_code") and test["attempt_number"] > 1:
                    cb, ca = st.columns(2)
                    with cb:
                        st.markdown(f"**Attempt {test['attempt_number']-1} (Before)**")
                        st.code(test["previous_code"], language="typescript")
                    with ca:
                        st.markdown(f"**Attempt {test['attempt_number']} (After)**")
                        st.code(test["test_code"], language="typescript")
                else:
                    st.code(test["test_code"], language="typescript")

                if result:
                    st.markdown("**🔍 Agent C Notes:**")
                    n1, n2 = st.columns(2)
                    with n1:
                        if result["hallucination"]["hallucinated_locators"]:
                            st.error(f"Hallucinated locators: {', '.join(result['hallucination']['hallucinated_locators'])}")
                        if result["missing_scenario"]["missing_cases"]:
                            st.warning("Missing cases:\n" + "\n".join(f"• {c}" for c in result["missing_scenario"]["missing_cases"][:3]))
                    with n2:
                        if result["execution"]["error_message"]:
                            st.error(f"Execution error: {result['execution']['error_message']}")
                        if result["fix_instructions"]:
                            st.info(f"Fix instructions: {result['fix_instructions']}")

                if row.get("retry_history"):
                    st.markdown("**🔄 Retry History:**")
                    for i, hist in enumerate(row["retry_history"], 1):
                        r = hist.get("overall_result") or "unknown"
                        st.markdown(f"Attempt {i}: {'✅' if r=='pass' else '❌'} {r.upper()}")

        st.divider()


def _render_exports(state: dict):
    st.subheader("📥 Export")

    # ── Playwright HTML report ─────────────────────────────────
    pw_html = Path(__file__).parent / "reports" / "playwright_html" / "index.html"
    if pw_html.exists():
        with open(pw_html, "rb") as f:
            st.download_button(
                label     = "🎭 Download Playwright HTML Report",
                data      = f.read(),
                file_name = "playwright_report.html",
                mime      = "text/html",
                help      = "Full Playwright report with screenshots and execution details",
            )
        st.caption(f"Report saved at: `{pw_html}`")
        st.divider()

    col1, col2, col3 = st.columns(3)
    matrix = state.get("traceability_matrix", [])

    with col1:
        if st.button("📄 Generate HTML Report"):
            try:
                html_path = generate_html_report(
                    traceability_matrix = matrix,
                    overall_status      = state.get("overall_status", "unknown"),
                    total_frs           = state.get("total_frs", 0) or 0,
                    passed_frs          = state.get("passed_frs", 0) or 0,
                    failed_frs          = state.get("failed_frs", 0) or 0,
                    warned_frs          = state.get("warned_frs", 0) or 0,
                    skipped_frs         = state.get("skipped_frs", 0) or 0,
                    base_url            = state.get("base_url", ""),
                    retries_used        = state.get("current_retry", 0),
                    max_retries         = state.get("max_retries", 1),
                )
                with open(html_path, "rb") as f:
                    st.download_button("⬇️ Download HTML", f.read(), Path(html_path).name, "text/html")
            except Exception as e:
                st.error(f"Error generating report: {e}")

    with col2:
        if st.button("📋 Generate JSON Report"):
            try:
                json_path = generate_json_report(matrix)
                with open(json_path, "rb") as f:
                    st.download_button("⬇️ Download JSON", f.read(), Path(json_path).name, "application/json")
            except Exception as e:
                st.error(f"Error generating JSON: {e}")

    with col3:
        spec_files = state.get("spec_files", {})
        if spec_files and st.button("🧪 Download Spec Files"):
            import zipfile, io
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                for _, path in spec_files.items():
                    if Path(path).exists():
                        zf.write(path, Path(path).name)
            buf.seek(0)
            st.download_button("⬇️ Download ZIP", buf.getvalue(), "playwright_specs.zip", "application/zip")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    init_session_state()
    render_header()

    phase = st.session_state.phase

    if phase == "config":
        render_phase1()
    elif phase == "discovery":
        render_discovery()
    elif phase == "selection":
        render_feature_selection()
    elif phase == "testing":
        render_testing()
    elif phase == "results":
        render_results()


if __name__ == "__main__":
    main()
