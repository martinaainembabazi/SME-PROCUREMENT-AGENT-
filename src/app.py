"""
SME Procurement-Preparation Agent — web application.

Run from the project root:
    streamlit run src/app.py

On first start the app asks you to create the Business Owner account.

Modules:
    auth.py          users, roles and approval limits
    data_store.py    inventory and quotation management
    requisitions.py  requisition lifecycle (draft -> approved/rejected -> received)
    agent.py         bounded AI agent (can only read data and create drafts)
    rag.py           grounded knowledge-base answers
    memory_store.py  approved-supplier memory (written only on human approval)
"""

from __future__ import annotations

import html
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
# agent.py resolves its trace directory relative to the working directory.
os.chdir(ROOT)

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from auth import (  # noqa: E402
    OWNER_APPROVAL_THRESHOLD_UGX,
    ROLES,
    UserStore,
    can,
    can_approve_amount,
)
from data_store import InventoryStore, QuoteStore  # noqa: E402
from memory_store import ApprovedSupplierMemory, prepare_draft_context  # noqa: E402
from orchestration import AppToolOrchestrator  # noqa: E402
from requisitions import STATUS_LABELS, RequisitionService  # noqa: E402

load_dotenv(ROOT / ".env")

TRACES_DIR = ROOT / "evidence" / "traces"
KNOWLEDGE_DIR = ROOT / "knowledge"
CHROMA_FILE = ROOT / "evidence" / "chroma" / "chroma.sqlite3"
MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 60

STATUS_STYLE = {
    "COMPLETED_PENDING_HUMAN_REVIEW": ("success", "Draft requisition ready for approval"),
    "COMPLETED_NO_REORDER": ("success", "Nothing needs reordering"),
    "WAITING_FOR_HUMAN_APPROVAL": ("info", "Waiting for a human decision"),
    "STOPPED_OUT_OF_SCOPE": ("warning", "Request was outside the agent's role"),
    "BLOCKED_MISSING_INFORMATION": ("warning", "Required information was missing"),
    "BLOCKED_TOOL_FAILURE": ("error", "Stopped safely after a failure"),
}
ACTION_ICONS = {
    "retrieve_context": ":material/menu_book:",
    "get_inventory_snapshot": ":material/inventory_2:",
    "get_reorder_candidates": ":material/trending_down:",
    "compare_supplier_quotes": ":material/compare_arrows:",
    "create_draft_requisition": ":material/edit_note:",
    "stop": ":green[:material/check_circle:]",
    "hand_off": ":orange[:material/front_hand:]",
    "planner": ":red[:material/error:]",
    "parse_failure": ":red[:material/error:]",
}
STATUS_BADGES = {
    "pending_human_approval": ":orange[:material/schedule:]",
    "approved": ":green[:material/check_circle:]",
    "rejected": ":red[:material/cancel:]",
    "received": ":blue[:material/inventory:]",
}
COLUMN_LABELS = {
    "item_code": "Code", "item_name": "Item", "unit": "Unit", "current_qty": "In stock",
    "reorder_threshold": "Reorder at", "last_restock_date": "Last restock", "avg_weekly_sales": "Weekly sales",
    "status": "Status", "supplier": "Supplier", "price_ugx": "Price (UGX)", "moq": "MOQ",
    "lead_time_days": "Lead time (days)", "payment_terms": "Payment terms", "username": "Username",
    "full_name": "Name", "role_label": "Role", "active": "Active", "locked": "Locked", "created_at": "Created",
    "approved_supplier": "Supplier", "approved_quantity": "Quantity", "approved_unit_price_ugx": "Unit price (UGX)",
    "source_draft_id": "From requisition", "approved_by": "Approved by", "approved_at": "Approved",
    "ts": "Time", "timestamp": "Time", "event": "Event", "outcome": "Outcome", "record_id": "Record",
    "detail": "Detail", "requested_by": "Requested by",
}
AGENT_PROMPTS = {
    "Weekly reorder check": "What should we reorder this week, and can you prepare a draft requisition for anything critical?",
    "Compare quotes for an item": "Compare supplier quotes for RICE5 and recommend an option.",
    "Stock status": "Which items are below their reorder threshold?",
}


LOGO = SRC / "assets" / "logo.svg"
# Filled in by main() so pages can link to each other with st.page_link.
PAGE_REFS: dict[str, Any] = {}

# Colours live in .streamlit/config.toml; this adds the layout and typography details.
STYLES = """
<style>
:root { --accent: #3DDC97; --muted: #94A39D; --panel: #0E1614; --line: #1D2925; }
#MainMenu, footer, [data-testid="stDecoration"] { display: none !important; }
[data-testid="stHeader"] {
    background: rgba(6, 9, 10, 0.88); backdrop-filter: blur(10px); border-bottom: 1px solid var(--line);
}
[data-testid="stMainBlockContainer"], .block-container { max-width: 1280px; padding-top: 4.5rem; }
h1 { letter-spacing: -0.025em; }
.eyebrow {
    color: var(--accent); text-transform: uppercase; letter-spacing: 0.14em;
    font-size: 0.78rem; font-weight: 600; margin: 0 0 0.15rem;
}
.subtitle { color: var(--muted); font-size: 1.05rem; margin: -0.6rem 0 1.6rem; max-width: 62rem; }
.hero-title {
    font-size: clamp(2.6rem, 6vw, 4.8rem); font-weight: 800; line-height: 1.02;
    letter-spacing: -0.035em; margin: 0.3rem 0 1rem;
}
.hero-title span { color: var(--accent); }
.hero-sub { color: var(--muted); font-size: 1.15rem; line-height: 1.6; max-width: 38rem; margin-bottom: 1.4rem; }
.section-label {
    color: var(--accent); text-transform: uppercase; letter-spacing: 0.14em;
    font-size: 0.78rem; font-weight: 600; margin: 1.6rem 0 0.6rem;
}
.feature { display: flex; gap: 0.7rem; align-items: baseline; color: #DCE3E0; margin: 0.45rem 0; }
.feature b { color: var(--accent); font-weight: 600; }

/* Primary actions are white pills that turn mint on hover. */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
    background: #FFFFFF !important; border: none !important; font-weight: 600; padding: 0.5rem 1.4rem;
}
[data-testid="stBaseButton-primary"] *, [data-testid="stBaseButton-primaryFormSubmit"] * { color: #06090A !important; }
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {
    background: var(--accent) !important;
}

[data-testid="stMetric"] {
    background: var(--panel); border: 1px solid var(--line); border-radius: 1rem; padding: 1.1rem 1.3rem;
}
[data-testid="stMetricLabel"] p {
    color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.74rem; font-weight: 600;
}
[data-testid="stMetricValue"] { font-weight: 800; letter-spacing: -0.02em; }
[data-testid="stExpander"] details { background: var(--panel); border-radius: 1rem; }
[data-testid="stExpander"] [data-testid="stMetric"] { background: #0A100F; padding: 0.8rem 1rem; }
[data-testid="stExpander"] [data-testid="stMetricValue"] { font-size: 1.45rem; }
[data-testid="stForm"] { background: var(--panel); border-radius: 1rem; padding: 1.4rem; }
[data-baseweb="tab-list"] { gap: 1.6rem; border-bottom: 1px solid var(--line); }
[data-baseweb="tab"] p { font-weight: 600; }
[data-testid="stPageLink"] a { border: 1px solid var(--line); border-radius: 999px; padding: 0.35rem 1rem; }
[data-testid="stPageLink"] a:hover { border-color: var(--accent); background: rgba(61, 220, 151, 0.08); }
</style>
"""


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def inject_styles() -> None:
    st.markdown(STYLES, unsafe_allow_html=True)


def page_header(eyebrow: str, title: str, subtitle: str | None = None) -> None:
    st.markdown(f'<p class="eyebrow">{eyebrow}</p>', unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        st.markdown(f'<p class="subtitle">{subtitle}</p>', unsafe_allow_html=True)


def readable(frame: pd.DataFrame) -> pd.DataFrame:
    """Human-friendly column headings for tables."""
    return frame.rename(columns=lambda c: COLUMN_LABELS.get(c, str(c).replace("_", " ").capitalize()))


def section_label(text: str) -> None:
    st.markdown(f'<p class="section-label">{text}</p>', unsafe_allow_html=True)


def api_key_present() -> bool:
    key = os.getenv("GEMINI_API_KEY", "")
    return bool(key) and key != "your-real-key-here"


def ugx(value: Any) -> str:
    return f"UGX {value:,.0f}" if isinstance(value, (int, float)) else "—"


def flash(kind: str, message: str) -> None:
    st.session_state.setdefault("flash", []).append((kind, message))


def show_flash() -> None:
    for kind, message in st.session_state.pop("flash", []):
        getattr(st, kind)(message)


def current_user() -> dict[str, Any] | None:
    username = st.session_state.get("username")
    if not username:
        return None
    user = UserStore().get_user(username)
    # Re-read every run so role changes and deactivations apply immediately.
    if not user or not user["active"]:
        st.session_state.pop("username", None)
        return None
    return user


def index_status() -> tuple[str, str]:
    if not CHROMA_FILE.exists():
        return "missing", "The knowledge index has not been built yet."
    indexed = CHROMA_FILE.stat().st_mtime
    newest = max((p.stat().st_mtime for p in KNOWLEDGE_DIR.rglob("*") if p.is_file()), default=0)
    built = datetime.fromtimestamp(indexed).strftime("%Y-%m-%d %H:%M")
    if newest > indexed:
        return "stale", f"Knowledge data changed after the index was built ({built})."
    return "ok", f"Index is up to date (built {built})."


@st.cache_data(ttl=60, show_spinner=False)
def draft_context(item_code: str) -> dict[str, Any]:
    # Cached so page reruns don't flood the memory audit log with repeat reads.
    return prepare_draft_context(AppToolOrchestrator(), ApprovedSupplierMemory(), item_code)


@st.cache_resource(show_spinner=False)
def get_retriever():
    from retriever import Retriever

    return Retriever()


@st.cache_resource(show_spinner=False)
def get_rag():
    from rag import RAGPipeline

    return RAGPipeline()


class LiveOrchestrator(AppToolOrchestrator):
    """Same tools and guardrails as the agent normally uses, plus progress events."""

    def __init__(self, on_event: Callable[[str], None]):
        super().__init__()
        self.on_event = on_event

    def call_tool(self, tool_name, arguments=None, *, principal="agent"):
        self.on_event(f"{ACTION_ICONS.get(tool_name, '🔧')} `{tool_name}` {json.dumps(arguments or {})}")
        try:
            result = super().call_tool(tool_name, arguments, principal=principal)
        except Exception as exc:
            self.on_event(f"❌ `{tool_name}` failed: {exc}")
            raise
        return result


def render_steps(steps: list[dict[str, Any]]) -> None:
    if not steps:
        st.caption("No steps were recorded.")
        return
    for step in steps:
        action = step.get("action", "?")
        failed = bool(step.get("error"))
        title = f"{ACTION_ICONS.get(action, '🔧')} Step {step.get('iteration', '?')}: {action}"
        with st.expander(title + (" — error" if failed else ""), expanded=failed):
            if step.get("thought"):
                st.markdown(f"**Reasoning:** {step['thought']}")
            if step.get("args"):
                st.json(step["args"])
            if failed:
                st.error(step["error"])
            observation = step.get("observation")
            if observation not in (None, ""):
                if isinstance(observation, (dict, list)):
                    st.json(observation, expanded=False)
                else:
                    st.write(observation)


def render_run(run: dict[str, Any]) -> None:
    kind, label = STATUS_STYLE.get(run.get("final_status"), ("info", run.get("final_status")))
    getattr(st, kind)(f"**{label}** · `{run.get('final_status')}`")
    c1, c2 = st.columns(2)
    c1.metric("Iterations", f"{run.get('iterations_used', '?')} / 8")
    c2.metric("Tool calls", f"{run.get('tool_calls_used', '?')} / 12")
    if run.get("final_answer"):
        st.markdown(run["final_answer"])
    if run.get("hand_off_reason"):
        st.warning(run["hand_off_reason"])
    drafts = [
        s["observation"]["draft_id"] for s in run.get("steps", [])
        if s.get("action") == "create_draft_requisition"
        and isinstance(s.get("observation"), dict) and s["observation"].get("draft_id")
    ]
    if drafts:
        st.info(f"Created {', '.join(drafts)}. Review it under **Requisitions**.")
    with st.expander("Step-by-step trace"):
        render_steps(run.get("steps", []))


# --------------------------------------------------
# Authentication
# --------------------------------------------------

def auth_hero() -> None:
    st.markdown(
        """
<p class="eyebrow">CAC Supermarket · Kyanja</p>
<div class="hero-title">Procurement,<br><span>prepared.</span></div>
<p class="hero-sub">Spot low stock, compare supplier quotes and draft requisitions with an AI agent.
Every purchase still waits for a person to approve it.</p>
<p class="section-label">What you can do</p>
<div class="feature"><b>01</b> See what needs reordering, at a glance</div>
<div class="feature"><b>02</b> Let the agent compare quotes and draft requisitions</div>
<div class="feature"><b>03</b> Approve within your limit, then record the delivery</div>
""",
        unsafe_allow_html=True,
    )


def page_first_run() -> None:
    hero, form_col = st.columns([1.25, 1], gap="large")
    with hero:
        auth_hero()
    with form_col:
        st.subheader("Set up the app")
        st.caption("No accounts exist yet. Create the Business Owner account; you can add other users afterwards.")
        _first_run_form()


def _first_run_form() -> None:
    with st.form("first_owner"):
        full_name = st.text_input("Full name")
        username = st.text_input("Username", help="3-32 lowercase letters, digits, '.', '_' or '-'")
        password = st.text_input("Password", type="password", help="At least 8 characters")
        confirm = st.text_input("Repeat password", type="password")
        submitted = st.form_submit_button("Create account", type="primary", width="stretch")
    if submitted:
        if password != confirm:
            st.error("Passwords do not match.")
            return
        store = UserStore()
        if store.has_users():
            st.error("An account already exists. Please sign in.")
            return
        try:
            user = store.create_user(username, password, "owner", full_name)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state["username"] = user["username"]
        st.rerun()


def page_login() -> None:
    hero, form_col = st.columns([1.25, 1], gap="large")
    with hero:
        auth_hero()
    with form_col:
        st.subheader("Sign in")
        _login_form()


def _login_form() -> None:
    locked_until = st.session_state.get("locked_until", 0)
    if time.time() < locked_until:
        st.error(f"Too many failed attempts. Try again in {int(locked_until - time.time())} seconds.")
        return
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
    if submitted:
        user = UserStore().authenticate(username, password)
        if user:
            st.session_state.pop("login_failures", None)
            st.session_state["username"] = user["username"]
            st.rerun()
        failures = st.session_state.get("login_failures", 0) + 1
        st.session_state["login_failures"] = failures
        if failures >= MAX_LOGIN_FAILURES:
            st.session_state["locked_until"] = time.time() + LOCKOUT_SECONDS
            st.session_state["login_failures"] = 0
        st.error(
            "Invalid username or password. After 5 failed attempts an account is "
            "locked for 15 minutes; a Business Owner can unlock it by resetting the password."
        )


# --------------------------------------------------
# Pages
# --------------------------------------------------

def page_dashboard(user: dict[str, Any]) -> None:
    show_flash()
    service = RequisitionService()
    items = InventoryStore().list_items()
    low = [i for i in items if i["current_qty"] < i["reorder_threshold"]]
    pending = service.list("pending_human_approval")
    approved = service.list("approved")

    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    first_name = html.escape(user["full_name"].split()[0])
    if low:
        headline = f"{len(low)} item{'s' if len(low) != 1 else ''}<br><span>need restocking.</span>"
    else:
        headline = "Shelves are<br><span>fully stocked.</span>"
    st.markdown(
        f"""
<p class="eyebrow">{greeting}, {first_name}</p>
<div class="hero-title">{headline}</div>
<p class="hero-sub">{len(pending)} requisition{'s' if len(pending) != 1 else ''} awaiting approval ·
{len(approved)} awaiting delivery</p>
""",
        unsafe_allow_html=True,
    )
    links = st.columns([1, 1, 4])
    if can(user, "run_agent") and "agent" in PAGE_REFS:
        links[0].page_link(PAGE_REFS["agent"], label="Ask the agent", icon=":material/smart_toy:")
    if "requisitions" in PAGE_REFS:
        links[1].page_link(PAGE_REFS["requisitions"], label="Requisitions", icon=":material/arrow_forward:")

    section_label("At a glance")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Items in stock register", len(items))
    c2.metric("Below reorder threshold", len(low))
    c3.metric("Awaiting approval", len(pending))
    c4.metric("Awaiting delivery", len(approved))

    left, right = st.columns([3, 2], gap="large")
    with left:
        section_label("Items to reorder")
        if low:
            open_items = {r["item_code"] for r in pending + approved}
            frame = pd.DataFrame([
                {
                    "Item": f"{i['item_code']} — {i['item_name']}",
                    "Stock": i["current_qty"],
                    "Threshold": i["reorder_threshold"],
                    "Open requisition": "yes" if i["item_code"] in open_items else "no",
                }
                for i in low
            ])
            st.dataframe(frame, hide_index=True, width="stretch")
        else:
            st.success("All items are above their reorder threshold.")
    with right:
        section_label("Needs your action")
        actions = []
        if can(user, "approve"):
            for r in pending:
                total = service.evaluate(r)["total_ugx"]
                if can_approve_amount(user, total)[0]:
                    actions.append(f":material/approval: **Approve** {r.get('item_name')} · {ugx(total)}  \n"
                                   f"<small>{r['draft_id']}</small>")
        if can(user, "receive_goods"):
            actions += [
                f":material/local_shipping: **Record delivery** of {r.get('item_name')}  \n<small>{r['draft_id']}</small>"
                for r in approved
            ]
        with st.container(border=True):
            if actions:
                for line in actions[:8]:
                    st.markdown(line, unsafe_allow_html=True)
            else:
                st.markdown(":material/check_circle: Nothing waiting for you.")

    status, message = index_status()
    if status != "ok":
        st.warning(f"{message} " + ("Rebuild it under **Administration**." if can(user, "rebuild_index") else "Ask the Business Owner to rebuild it."))


def page_agent(user: dict[str, Any]) -> None:
    page_header(
        "AI tools", "Procurement agent",
        "Reads stock and quotes, and can create draft requisitions. It cannot approve, order or pay. "
        "Limits: 8 steps, 12 tool calls.",
    )
    if not api_key_present():
        st.error("GEMINI_API_KEY is not set in `.env`. The agent is unavailable.")
        return

    preset = st.selectbox("Common requests", ["Custom request", *AGENT_PROMPTS])
    goal = st.text_area("What should the agent do?", value=AGENT_PROMPTS.get(preset, ""), height=90)

    if st.button("Run agent", type="primary", disabled=not goal.strip()):
        from agent import ProcurementAgent

        with st.status("Agent working…", expanded=True) as status:
            def retrieve(question: str):
                status.write(f"📚 Searching knowledge base: `{question}`")
                return get_retriever().retrieve(question)

            started = datetime.now(timezone.utc)
            try:
                run = ProcurementAgent(
                    orchestrator=LiveOrchestrator(status.write),
                    context_retriever=retrieve,
                ).run(goal)
            except ValueError as exc:
                status.update(label="Request rejected", state="error")
                st.error(f"Request rejected: {exc}")
                return
            except Exception as exc:
                status.update(label="Agent failed", state="error")
                st.error(f"{type(exc).__name__}: {exc}")
                return
            record = {
                "goal": goal,
                "requested_by": user["username"],
                "started_at": started.isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                **asdict(run),
            }
            TRACES_DIR.mkdir(parents=True, exist_ok=True)
            path = TRACES_DIR / f"trace_app_{started.strftime('%Y%m%dT%H%M%SZ')}.json"
            path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            st.session_state["last_run"] = record
            state = "error" if run.final_status == "BLOCKED_TOOL_FAILURE" else "complete"
            status.update(label=run.final_status, state=state, expanded=False)

    if st.session_state.get("last_run"):
        st.divider()
        render_run(st.session_state["last_run"])


def _requisition_card(user: dict[str, Any], service: RequisitionService, record: dict[str, Any]) -> None:
    draft_id = record["draft_id"]
    ev = service.evaluate(record)
    status = record.get("status", "?")
    header = (
        f"{STATUS_BADGES.get(status, '')} {draft_id} · {record.get('item_name', record.get('item_code'))} · "
        f"{record.get('quantity')} × {record.get('supplier_name')} · {ugx(ev['total_ugx'])}"
    )
    with st.expander(header, expanded=status == "pending_human_approval"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Quantity", record.get("quantity"))
        c2.metric("Unit price", ugx(ev["unit_price_ugx"]))
        c3.metric("Total", ugx(ev["total_ugx"]))
        c4.metric("Status", STATUS_LABELS.get(status, status))
        quote = ev["quote"] or {}
        st.caption(
            f"Supplier: {record.get('supplier_name')} · Terms: {quote.get('payment_terms', record.get('payment_terms', '—'))} · "
            f"Lead time: {quote.get('lead_time_days', record.get('lead_time_days', '—'))} days · MOQ: {quote.get('moq', '—')} · "
            f"Created {str(record.get('created_at', ''))[:16].replace('T', ' ')} by {record.get('created_by', 'AI agent')}"
        )
        if record.get("notes"):
            st.markdown(f"**Notes:** {record['notes']}")
        if record.get("approved_by"):
            st.markdown(f"Approved by **{record['approved_by']}** on {str(record.get('approved_at'))[:16].replace('T', ' ')}")
        if record.get("rejected_by"):
            st.markdown(f"Rejected by **{record['rejected_by']}**: {record.get('rejection_reason', '')}")
        if record.get("received_at"):
            st.markdown(
                f"Received {record.get('received_qty')} by **{record.get('received_by')}** on "
                f"{str(record['received_at'])[:16].replace('T', ' ')} · stock now {record.get('stock_after_receipt')}"
            )

        if status == "pending_human_approval":
            for issue in ev["issues"]:
                st.error(issue)
            if ev["needs_owner"]:
                st.warning(f"At or above {ugx(OWNER_APPROVAL_THRESHOLD_UGX)}: Business Owner approval required.")
            if can(user, "approve") or can(user, "reject"):
                allowed, reason = can_approve_amount(user, ev["total_ugx"])
                a, r, _ = st.columns([1, 1, 4])
                with a:
                    if st.button("Approve", key=f"approve_{draft_id}", type="primary",
                                 disabled=bool(ev["issues"]) or not allowed,
                                 help=reason or None):
                        try:
                            service.approve(user, draft_id)
                            draft_context.clear()
                            flash("success", f"{draft_id} approved. Supplier preference saved to memory.")
                        except (ValueError, PermissionError) as exc:
                            flash("error", str(exc))
                        st.rerun()
                    if reason and not ev["issues"]:
                        st.caption(reason)
                with r:
                    if can(user, "reject"):
                        with st.popover("Reject"):
                            why = st.text_input("Reason", key=f"why_{draft_id}")
                            if st.button("Confirm rejection", key=f"reject_{draft_id}"):
                                try:
                                    service.reject(user, draft_id, why)
                                    flash("warning", f"{draft_id} rejected. Memory was not changed.")
                                except (ValueError, PermissionError) as exc:
                                    flash("error", str(exc))
                                st.rerun()

        if status == "approved" and can(user, "receive_goods"):
            with st.form(f"receive_{draft_id}"):
                qty = st.number_input("Quantity delivered", min_value=1, value=int(record.get("quantity") or 1), step=1)
                if st.form_submit_button("Record delivery"):
                    try:
                        service.receive(user, draft_id, int(qty))
                        flash("success", f"Delivery recorded; stock for {record['item_code']} updated.")
                    except (ValueError, PermissionError) as exc:
                        flash("error", str(exc))
                    st.rerun()

        st.download_button(
            "Download requisition (CSV)",
            data=service.export_csv(record),
            file_name=f"{draft_id}.csv",
            mime="text/csv",
            key=f"dl_{draft_id}",
        )


def page_requisitions(user: dict[str, Any]) -> None:
    page_header("Operations", "Requisitions", "Draft, approve, receive and export purchase requisitions.")
    show_flash()
    service = RequisitionService()
    tabs = ["Pending approval", "Approved", "Received", "Rejected"]
    statuses = ["pending_human_approval", "approved", "received", "rejected"]
    if can(user, "create_draft"):
        tabs.append(":material/add: New requisition")
    rendered = st.tabs(tabs)

    for tab, status in zip(rendered, statuses):
        with tab:
            records = service.list(status)
            if not records:
                st.caption("No requisitions here.")
            for record in records:
                _requisition_card(user, service, record)

    if can(user, "create_draft"):
        with rendered[-1]:
            items = InventoryStore().list_items()
            if not items:
                st.info("Add items to the stock register first.")
                return
            names = {i["item_code"]: i for i in items}
            code = st.selectbox(
                "Item", list(names),
                format_func=lambda c: f"{c} — {names[c]['item_name']} (stock {names[c]['current_qty']}, threshold {names[c]['reorder_threshold']})",
            )
            quotes = QuoteStore().list_quotes(code)
            if not quotes:
                st.warning("No supplier quotes for this item. Add one under **Supplier quotes** first.")
                return
            st.dataframe(readable(pd.DataFrame(quotes).drop(columns=["item_code"])), hide_index=True, width="stretch")
            context = draft_context(code)
            if context["prefill_supplier"]:
                st.info(f"Previously approved: Supplier {context['prefill_supplier']['supplier']} ({context['prefill_supplier']['label']})")
            for flag in context["flags"]:
                if flag not in ("no_preference_found",):
                    st.caption(f"⚑ {flag.replace('_', ' ')}")
            suppliers = [q["supplier"] for q in quotes]
            default_supplier = context["prefill_supplier"]["supplier"] if context["prefill_supplier"] else suppliers[0]
            item = names[code]
            suggested = max(item["reorder_threshold"] * 2 - item["current_qty"], 1)
            with st.form("new_requisition"):
                supplier = st.selectbox(
                    "Supplier", suppliers,
                    index=suppliers.index(default_supplier) if default_supplier in suppliers else 0,
                )
                quantity = st.number_input("Quantity", min_value=1, value=suggested, step=1,
                                           help="Policy default: top up to 2 × reorder threshold.")
                notes = st.text_area("Notes", max_chars=1000)
                if st.form_submit_button("Create requisition", type="primary"):
                    try:
                        record = service.create_manual(user, code, int(quantity), supplier, notes)
                        flash("success", f"Created {record['draft_id']}; it is now pending approval.")
                        st.rerun()
                    except (ValueError, PermissionError) as exc:
                        st.error(str(exc))


def page_inventory(user: dict[str, Any]) -> None:
    page_header("Operations", "Inventory", "Stock levels against reorder thresholds. Rows in red need reordering.")
    show_flash()
    store = InventoryStore()
    items = store.list_items()
    if items:
        frame = pd.DataFrame(items)
        frame["status"] = ["Reorder" if q < t else "OK" for q, t in zip(frame["current_qty"], frame["reorder_threshold"])]
        frame = readable(frame)

        def highlight(row):
            return ["background-color: rgba(232,115,138,0.16)" if row["Status"] == "Reorder" else ""] * len(row)

        st.dataframe(frame.style.apply(highlight, axis=1), hide_index=True, width="stretch")
    else:
        st.info("The stock register is empty.")

    if not can(user, "manage_data"):
        return

    add_tab, edit_tab = st.tabs(["Add item", "Edit or remove item"])
    with add_tab:
        with st.form("add_item", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            code = c1.text_input("Item code", placeholder="e.g. BEANS1")
            name = c2.text_input("Item name")
            unit = c3.text_input("Unit", placeholder="bag, box, bale…")
            c4, c5, c6 = st.columns(3)
            qty = c4.number_input("Current quantity", min_value=0, step=1)
            threshold = c5.number_input("Reorder threshold", min_value=0, step=1)
            weekly = c6.number_input("Avg weekly sales", min_value=0, step=1)
            restock = st.date_input("Last restock date", value=None)
            if st.form_submit_button("Add item", type="primary"):
                try:
                    store.add_item({
                        "item_code": code, "item_name": name, "unit": unit, "current_qty": qty,
                        "reorder_threshold": threshold, "avg_weekly_sales": weekly,
                        "last_restock_date": restock.isoformat() if restock else "",
                    })
                    flash("success", f"Added {code.upper()}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    with edit_tab:
        if not items:
            st.caption("Nothing to edit.")
            return
        by_code = {i["item_code"]: i for i in items}
        code = st.selectbox("Item", list(by_code), format_func=lambda c: f"{c} — {by_code[c]['item_name']}")
        item = by_code[code]
        with st.form(f"edit_{code}"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Item name", value=item["item_name"])
            unit = c2.text_input("Unit", value=item["unit"])
            c3, c4, c5 = st.columns(3)
            qty = c3.number_input("Current quantity", min_value=0, step=1, value=item["current_qty"])
            threshold = c4.number_input("Reorder threshold", min_value=0, step=1, value=item["reorder_threshold"])
            weekly = c5.number_input("Avg weekly sales", min_value=0, step=1, value=item["avg_weekly_sales"])
            try:
                restock_value = datetime.fromisoformat(item["last_restock_date"]).date() if item["last_restock_date"] else None
            except ValueError:
                restock_value = None
            restock = st.date_input("Last restock date", value=restock_value)
            if st.form_submit_button("Save changes", type="primary"):
                try:
                    store.update_item(code, {
                        "item_name": name, "unit": unit, "current_qty": qty, "reorder_threshold": threshold,
                        "avg_weekly_sales": weekly, "last_restock_date": restock.isoformat() if restock else "",
                    })
                    flash("success", f"Saved {code}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with st.popover(f"Remove {code}"):
            st.write(f"Remove **{item['item_name']}** from the stock register? Its quotes are kept.")
            if st.button("Remove item", key=f"del_{code}"):
                store.delete_item(code)
                flash("warning", f"Removed {code}.")
                st.rerun()


def page_quotes(user: dict[str, Any]) -> None:
    page_header("Operations", "Supplier quotes", "Compare suppliers on price, lead time, MOQ and payment terms.")
    show_flash()
    store = QuoteStore()
    items = InventoryStore().list_items()
    names = {i["item_code"]: i["item_name"] for i in items}
    quoted = {q["item_code"] for q in store.list_quotes()}
    codes = sorted(set(names) | quoted)
    if not codes:
        st.info("Add items to the stock register first.")
        return
    code = st.selectbox(
        "Item", codes,
        format_func=lambda c: f"{c} — {names.get(c, 'not in stock register')}" + ("" if c in quoted else " · no quotes"),
    )
    try:
        comparison = AppToolOrchestrator().call_tool("compare_supplier_quotes", {"item_code": code}, principal="viewer")
    except Exception as exc:
        st.error(f"Quotes could not be loaded: {exc}")
        return
    if comparison["quotes"]:
        st.dataframe(readable(pd.DataFrame(comparison["quotes"])), hide_index=True, width="stretch")
        rec = comparison["recommendation"]
        st.caption(
            f"Ranked by price, then lead time. Lowest: Supplier {rec['supplier']} at {ugx(rec['price_ugx'])}, "
            f"{rec['lead_time_days']} days. Reorder policy weighs price, lead time and reliability, so this is not automatic."
        )
    else:
        st.info("No quotes recorded for this item.")

    if not can(user, "manage_data"):
        if comparison.get("notes"):
            st.markdown(f"**Notes:** {comparison['notes']}")
        return

    section_label("Add or update a quote")
    st.caption("Saving a quote for a supplier that already quoted this item replaces their old quote.")
    with st.form(f"quote_{code}", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        supplier = c1.text_input("Supplier", placeholder="A, B, C or a name")
        price = c2.number_input("Unit price (UGX)", min_value=0, step=500)
        moq = c3.number_input("MOQ", min_value=1, step=1)
        c4, c5 = st.columns(2)
        lead = c4.number_input("Lead time (days)", min_value=0, max_value=365, step=1)
        terms = c5.text_input("Payment terms", placeholder="Net 30, Cash on delivery…")
        if st.form_submit_button("Save quote", type="primary"):
            try:
                saved = store.upsert_quote(code, {
                    "supplier": supplier, "price_ugx": price, "moq": moq,
                    "lead_time_days": lead, "payment_terms": terms,
                })
                flash("success", f"Saved quote from supplier {saved['supplier']} for {code}.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if comparison["quotes"]:
        with st.popover("Remove a quote"):
            supplier = st.selectbox("Supplier", [q["supplier"] for q in comparison["quotes"]], key=f"rmq_{code}")
            if st.button("Remove quote", key=f"rmq_btn_{code}"):
                store.delete_quote(code, supplier)
                flash("warning", f"Removed supplier {supplier}'s quote for {code}.")
                st.rerun()
    with st.form(f"notes_{code}"):
        notes = st.text_area("Comparison notes", value=store.get_notes(code) if code in quoted else "", max_chars=2000)
        if st.form_submit_button("Save notes"):
            try:
                store.set_notes(code, notes)
                flash("success", "Notes saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def page_knowledge(user: dict[str, Any]) -> None:
    page_header("AI tools", "Knowledge assistant",
                "Answers come only from the procurement knowledge base (policies, catalogues, stock, quotes), with sources.")
    if not api_key_present():
        st.error("GEMINI_API_KEY is not set in `.env`.")
        return
    status, message = index_status()
    if status == "missing":
        st.error(message)
        return
    if status == "stale":
        st.warning(message + " Answers may not reflect the latest edits.")

    history = st.session_state.setdefault("qa_history", [])
    for entry in history:
        with st.chat_message("user"):
            st.write(entry["question"])
        with st.chat_message("assistant"):
            st.markdown(entry["answer"])
            with st.expander("Sources"):
                for n, s in enumerate(entry["sources"], 1):
                    st.markdown(f"**[{n}] {s['source']}** · chunk {s['chunk']}")
                    st.text(s["text"][:800])

    question = st.chat_input("Ask about policies, suppliers, stock or quotes")
    if question:
        with st.spinner("Searching the knowledge base…"):
            try:
                result = get_rag().generate_answer(question, top_k=5)
            except Exception as exc:
                st.error(f"{type(exc).__name__}: {exc}")
                return
        history.append({"question": question, "answer": result["answer"], "sources": result["sources"]})
        st.rerun()
    if history and st.button("Clear conversation"):
        st.session_state["qa_history"] = []
        st.rerun()


def page_memory(user: dict[str, Any]) -> None:
    page_header("Admin", "Supplier memory",
                "Supplier choices remembered from approved requisitions. Records older than 90 days are not suggested.")
    show_flash()
    memory = ApprovedSupplierMemory()
    records, error = memory._load()
    if error:
        st.error("The memory file is unreadable. The app will draft without supplier preferences.")
    elif records:
        st.dataframe(readable(pd.DataFrame(records.values())), hide_index=True, width="stretch")
        if can(user, "manage_memory"):
            with st.popover("Forget a supplier preference"):
                code = st.selectbox("Item", list(records))
                if st.button("Forget"):
                    memory.delete(code, f"{user['full_name']} ({ROLES[user['role']]})")
                    draft_context.clear()
                    flash("warning", f"Forgot the remembered supplier for {code}.")
                    st.rerun()
    else:
        st.caption("No supplier preferences remembered yet.")

    section_label("Audit log")
    if memory.log_path.exists():
        rows = []
        for line in memory.log_path.read_text(encoding="utf-8").splitlines()[-50:]:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        st.dataframe(readable(pd.DataFrame(list(reversed(rows)))), hide_index=True, width="stretch")
    else:
        st.caption("No events yet.")


def page_history(user: dict[str, Any]) -> None:
    page_header("AI tools", "Agent run history", "Every agent run with its full step-by-step trace.")
    runs = []
    for path in sorted(TRACES_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("steps"), list) and data.get("final_status"):
            runs.append((path, data))
    if not runs:
        st.info("No agent runs recorded yet.")
        return
    summary = pd.DataFrame([
        {
            "When": str(d.get("started_at", ""))[:16].replace("T", " "),
            "Requested by": d.get("requested_by", "—"),
            "Goal": (d.get("goal") or "—")[:80],
            "Status": d["final_status"],
            "Steps": d.get("iterations_used"),
        }
        for _, d in runs
    ])
    st.dataframe(summary, hide_index=True, width="stretch")
    index = st.selectbox(
        "Open a run", range(len(runs)),
        format_func=lambda i: f"{summary.iloc[i]['When']} · {summary.iloc[i]['Status']} · {runs[i][0].name}",
    )
    data = runs[index][1]
    if data.get("goal"):
        st.markdown(f"**Goal:** {data['goal']}")
    render_run(data)


def page_admin(user: dict[str, Any]) -> None:
    page_header("Admin", "Administration", "Users, roles and the knowledge index.")
    show_flash()
    store = UserStore()

    section_label("Users")
    st.dataframe(
        readable(pd.DataFrame(store.list_users())[["username", "full_name", "role_label", "active", "locked", "created_at"]]),
        hide_index=True, width="stretch",
    )
    add_tab, edit_tab = st.tabs(["Add user", "Change user"])
    with add_tab:
        with st.form("add_user", clear_on_submit=True):
            c1, c2 = st.columns(2)
            full_name = c1.text_input("Full name")
            username = c2.text_input("Username")
            c3, c4 = st.columns(2)
            role = c3.selectbox("Role", list(ROLES), format_func=ROLES.get)
            password = c4.text_input("Initial password", type="password")
            if st.form_submit_button("Add user", type="primary"):
                try:
                    created = store.create_user(username, password, role, full_name)
                    flash("success", f"Added {created['username']} as {created['role_label']}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    with edit_tab:
        users = {u["username"]: u for u in store.list_users()}
        name = st.selectbox("User", list(users), format_func=lambda u: f"{u} — {users[u]['full_name']}")
        target = users[name]
        with st.form(f"edit_user_{name}"):
            role = st.selectbox("Role", list(ROLES), index=list(ROLES).index(target["role"]), format_func=ROLES.get)
            active = st.checkbox("Active", value=target["active"])
            password = st.text_input("New password (leave blank to keep; setting one also unlocks the account)", type="password")
            if st.form_submit_button("Save", type="primary"):
                try:
                    store.update_user(name, role=role, active=active, password=password or None)
                    flash("success", f"Updated {name}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    section_label("Knowledge index")
    status, message = index_status()
    {"ok": st.success, "stale": st.warning, "missing": st.error}[status](message)
    st.caption("Rebuild after changing stock, quotes or policy files so the knowledge assistant sees the changes. The agent's tools always read live data.")
    if st.button("Rebuild knowledge index", disabled=not api_key_present()):
        with st.spinner("Embedding the knowledge base…"):
            try:
                get_retriever.clear()
                get_rag.clear()
                from ingest import ingest

                ingest()
                flash("success", "Knowledge index rebuilt.")
            except Exception as exc:
                flash("error", f"Rebuild failed: {type(exc).__name__}: {exc}")
        st.rerun()

    section_label("System")
    c1, c2 = st.columns(2)
    c1.metric("Gemini API key", "configured" if api_key_present() else "missing")
    c2.metric("Model", os.getenv("MODEL_NAME", "gemini-2.5-flash"))


# --------------------------------------------------
# App
# --------------------------------------------------

def page_sign_out() -> None:
    for key in list(st.session_state):
        del st.session_state[key]
    st.rerun()


# (key, section, title, icon, page function, permission) — sections become top-bar dropdowns.
PAGES: list[tuple[str, str, str, str, Callable[[dict[str, Any]], None], str]] = [
    ("dashboard", "", "Dashboard", ":material/space_dashboard:", page_dashboard, "view"),
    ("requisitions", "Operations", "Requisitions", ":material/receipt_long:", page_requisitions, "view"),
    ("inventory", "Operations", "Inventory", ":material/inventory_2:", page_inventory, "view"),
    ("quotes", "Operations", "Supplier quotes", ":material/compare_arrows:", page_quotes, "view"),
    ("agent", "AI tools", "Procurement agent", ":material/smart_toy:", page_agent, "run_agent"),
    ("knowledge", "AI tools", "Knowledge assistant", ":material/menu_book:", page_knowledge, "view"),
    ("history", "AI tools", "Agent run history", ":material/history:", page_history, "view"),
    ("memory", "Admin", "Supplier memory", ":material/psychology:", page_memory, "view"),
    ("admin", "Admin", "Administration", ":material/admin_panel_settings:", page_admin, "manage_users"),
]


def main() -> None:
    st.set_page_config(page_title="CAC Procure", page_icon=":material/shopping_cart:", layout="wide")
    inject_styles()
    st.logo(str(LOGO), size="large")

    if not UserStore().has_users():
        page_first_run()
        return
    user = current_user()
    if user is None:
        page_login()
        return

    sections: dict[str, list[Any]] = {}
    PAGE_REFS.clear()
    for key, section, title, icon, fn, permission in PAGES:
        if not can(user, permission):
            continue
        page = st.Page(lambda fn=fn: fn(user), title=title, icon=icon, url_path=key, default=key == "dashboard")
        PAGE_REFS[key] = page
        sections.setdefault(section, []).append(page)
    account = f"{user['full_name'].split()[0]} · {user['role_label']}"
    sections[account] = [
        st.Page(page_sign_out, title="Sign out", icon=":material/logout:", url_path="sign-out"),
    ]
    st.navigation(sections, position="top").run()


main()
