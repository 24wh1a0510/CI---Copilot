"""Competitive Intelligence Briefing Crew — 3-page Streamlit app.

Pages:
  📊 Dashboard   — overview KPIs from history + last briefing summary
  ✍️ New Briefing — run the multi-agent pipeline
  📚 History      — browse all past runs, view full report for any

Run: streamlit run ui/app.py

NOTE ON COMPETITOR DISCOVERY:
Competitors are now OPTIONAL when generating a report. The "Auto-suggested"
chips below still exist as a fast heuristic preview while you type (via
tools/competitor_suggester.py), but they are no longer required to proceed.
If you click "Generate Report" with zero competitors selected, the crew's own
Competitor Discovery Agent (agents/definitions.py -> agents/tasks.py) runs as
a real pipeline stage — Supervisor -> Discovery -> Research -> Analyst ->
Writer — and the competitors it finds (with citations for why) come back on
the Briefing object itself, not from a UI-side guess.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from config.settings import settings
from crew import run_briefing
from governance.citation_guard import extract_citation_ids
from logging_.audit_logger import AuditLogger
from models.schemas import EvidenceStrength, SourceStatus
from reports.exporter import save_pdf
from tools.trend_memory import (
    _load_history,
    _normalize_key,
    diff_insights,
    save_briefing as tm_save,
)
from ui.theme import CSS
from ui.auth import render_auth, render_logout

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CI Briefing Crew",
    page_icon="🧭",
    layout="wide",
)
st.markdown(CSS, unsafe_allow_html=True)

# ── Authentication gate ───────────────────────────────────────────────────────
name, auth_status, username = render_auth()
if not auth_status:
    st.stop()   # block entire app until logged in


# ── Session state ─────────────────────────────────────────────────────────────
def _init():
    defaults = {
        "page": "Dashboard",
        "accepted_competitors": [],
        "validation_error": "",
        "briefing": None,
        "audit_events": [],
        "nb_last_topic": "",
        "nb_suggestions": [],
        "nb_auto_discover": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_and_add(raw: str):
    """Adds a competitor instantly — no network call in this path at all, so the
    Add button can never appear to hang. (A previous version did a live DDG
    domain lookup here; on a slow/rate-limited network that made clicking Add
    look like it did nothing for several seconds.)"""
    raw = raw.strip()
    if not raw:
        st.session_state["validation_error"] = "Type a competitor name first."
        return
    names = {c["name"].lower() for c in st.session_state["accepted_competitors"]}
    if raw.lower() in names:
        st.session_state["validation_error"] = f"'{raw}' already in list."
        return
    st.session_state["accepted_competitors"].append({"name": raw, "domain": ""})
    st.session_state["validation_error"] = ""


def _load_wl_names():
    try:
        from tools.watchlist import list_watchlists
        return list_watchlists()
    except Exception:
        return []


def _save_wl(name: str):
    if not name.strip():
        st.sidebar.warning("Enter a name first.")
        return
    try:
        from tools.watchlist import save_watchlist
        save_watchlist(name.strip(), st.session_state["accepted_competitors"])
        st.sidebar.success(f"Saved '{name.strip()}'")
    except Exception as e:
        st.sidebar.error(str(e))


def _apply_wl(name: str):
    try:
        from tools.watchlist import load_watchlist
        c = load_watchlist(name)
        if c:
            st.session_state["accepted_competitors"] = c
    except Exception as e:
        st.sidebar.error(str(e))


def _status_color(status: str) -> str:
    return {
        "completed": "badge-ok",
        "completed_with_partial_failures": "badge-warn",
        "stopped_at_limit": "badge-warn",
        "failed": "badge-danger",
    }.get(status, "badge-run")


# ── Sidebar navigation ────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🧭 CI Briefing Crew")
    for pg in ["📊 Dashboard", "✍️ New Briefing", "📚 History"]:
        label = pg.split(" ", 1)[1]
        active = st.session_state["page"] == label
        if st.button(pg, use_container_width=True,
                     type="primary" if active else "secondary"):
            st.session_state["page"] = label
            st.rerun()

    st.markdown("---")
    st.caption(f"Model: `{settings.openrouter_model}`")
    search_info = "Tavily" if settings._tavily_key else ("Serper" if settings._serper_key else "DuckDuckGo")
    st.caption(f"Search: `{search_info}`")
    st.markdown("---")
    render_logout()


# ── Page: Dashboard ───────────────────────────────────────────────────────────
def page_dashboard():
    st.markdown("""
    <div class="app-header">
      <div>
        <div class="title">📊 Dashboard</div>
        <div class="subtitle">Overview of all briefing runs</div>
      </div>
      <div class="badge badge-run">CI Briefing Crew</div>
    </div>
    """, unsafe_allow_html=True)

    history = _load_history()

    if not history:
        st.info("No briefings yet. Go to **✍️ New Briefing** to run your first report.")
        if st.button("✍️ Start New Briefing", type="primary"):
            st.session_state["page"] = "New Briefing"
            st.rerun()
        return

    # ── Summary KPIs ─────────────────────────────────────────────────────────
    total_runs = len(history)
    topics = list({r.get("topic", "") for r in history})
    all_competitors = list({c for r in history for c in r.get("competitors", [])})
    last = history[-1]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Runs", total_runs)
    k2.metric("Unique Topics", len(topics))
    k3.metric("Competitors Tracked", len(all_competitors))
    k4.metric("Last Run", last.get("timestamp", "")[:10])

    st.markdown("---")

    # ── Recent runs table ─────────────────────────────────────────────────────
    st.markdown("#### Recent Runs")
    for i, r in enumerate(reversed(history[-10:])):
        ts   = r.get("timestamp", "")[:19].replace("T", " ")
        tp   = r.get("topic", "—")
        comp = ", ".join(r.get("competitors", []))
        rid  = r.get("run_id", "")
        col1, col2, col3, col4 = st.columns([2, 3, 3, 1])
        col1.caption(ts)
        col2.markdown(f"**{tp}**")
        col3.caption(comp[:60] + ("…" if len(comp) > 60 else ""))
        if col4.button("View", key=f"dash_view_{i}_{rid[:6]}"):
            st.session_state["history_view_run_id"] = rid
            st.session_state["page"] = "History"
            st.rerun()

    st.markdown("---")

    # ── Last briefing quick-view ──────────────────────────────────────────────
    st.markdown("#### Last Briefing Preview")
    with st.expander(f"📋 {last.get('topic','—')} — {last.get('timestamp','')[:10]}", expanded=True):
        md = last.get("markdown", "")
        # Show just executive summary
        lines, capture, out = md.split("\n"), False, []
        for line in lines:
            if "Executive Summary" in line:
                capture = True
                continue
            if capture and line.strip().startswith("##"):
                break
            if capture:
                out.append(line)
        st.markdown("\n".join(out) or "_No summary available._")

    if st.button("✍️ Run New Briefing", type="primary"):
        st.session_state["page"] = "New Briefing"
        st.rerun()



# ── Page: New Briefing ────────────────────────────────────────────────────────
def page_new_briefing():
    st.markdown("""
    <div class="app-header">
      <div>
        <div class="title">✍️ New Briefing</div>
        <div class="subtitle">Configure and run the multi-agent pipeline</div>
      </div>
      <div class="badge badge-run">Supervisor → Research → Analyst → Writer</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Input form ────────────────────────────────────────────────────────────
    with st.container():
        col_t, col_s, col_st = st.columns([4, 1, 1])
        with col_t:
            topic = st.text_input("Market topic", placeholder="e.g. Indian EdTech",
                                  key="nb_topic")
        with col_s:
            max_sources = st.number_input("Max sources", min_value=3, max_value=100,
                                          value=settings.max_sources, step=5)
        with col_st:
            max_steps = st.number_input("Max steps", min_value=5, max_value=120,
                                        value=settings.max_steps, step=5)

    # ── Auto-suggest competitors when topic entered ───────────────────────────
    # This is a fast heuristic PREVIEW only (tools/competitor_suggester.py), shown
    # while typing so you can pick from likely names without waiting for a full
    # agent run. It is entirely optional — you can ignore it and let the crew's
    # own Discovery Agent find competitors for real when you click Generate.
    prev_topic = st.session_state.get("nb_last_topic", "")
    if topic.strip() and topic.strip() != prev_topic:
        st.session_state["nb_last_topic"] = topic.strip()
        st.session_state["nb_suggestions"] = []
        st.session_state["accepted_competitors"] = []
        with st.spinner(f"Finding competitors for '{topic}'…"):
            try:
                from tools.competitor_suggester import suggest_competitors
                suggestions = suggest_competitors(topic.strip())
                st.session_state["nb_suggestions"] = suggestions
                # Do NOT pre-accept suggestions. This is a heuristic (regex/frequency
                # based) preview, not a verified list — accepting everything by
                # default meant obviously-wrong picks (sentence-noise words, generic
                # infra giants unrelated to the actual topic) silently ended up in
                # the competitor list without the user choosing them. Leave the
                # list empty and let the user opt in per-suggestion, or ignore this
                # entirely and let the real Discovery Agent run instead.
                st.session_state["accepted_competitors"] = []
            except Exception as e:
                st.warning(f"Auto-suggest preview failed (not required — you can still "
                           f"generate without it): {e}")

    # ── Competitor management ─────────────────────────────────────────────────
    suggestions  = st.session_state.get("nb_suggestions", [])
    accepted     = st.session_state.get("accepted_competitors", [])
    acc_domains  = {c["domain"] for c in accepted}

    exp_label = (f"👥 Competitors ({len(accepted)} selected)"
                 if accepted else "👥 Competitors — none selected (Discovery Agent will find them)")

    with st.expander(exp_label, expanded=True):

        if not accepted:
            st.info(
                "🕵️ Don't know your competitors? Leave this empty. When you click "
                "**Generate Report**, the crew's **Discovery Agent** will research "
                "the topic itself, identify real competitors from live sources, "
                "and cite why each one was included — you'll still be able to "
                "review and edit the list afterward.",
                icon="🕵️",
            )

        # ── Show suggestions as toggleable chips ──────────────────────────────
        if suggestions:
            st.caption("**Quick-pick suggestions** — uncheck to remove, or ignore and "
                       "let Discovery Agent run instead:")
            changed = False
            for s in suggestions:
                in_acc = s["domain"] in acc_domains
                checked = st.checkbox(
                    f"{s['name']}  `{s['domain']}`  · {int(s['confidence']*100)}%",
                    value=in_acc,
                    key=f"nb_sugg_{s['domain']}",
                )
                if checked and not in_acc:
                    st.session_state["accepted_competitors"].append(
                        {"name": s["name"], "domain": s["domain"]}
                    )
                    acc_domains.add(s["domain"])
                    changed = True
                elif not checked and in_acc:
                    st.session_state["accepted_competitors"] = [
                        c for c in st.session_state["accepted_competitors"]
                        if c["domain"] != s["domain"]
                    ]
                    acc_domains.discard(s["domain"])
                    changed = True

        # ── Manual add ────────────────────────────────────────────────────────
        st.markdown("**Add manually (optional):**")
        c1, c2, c3 = st.columns([4, 1, 1])
        with c1:
            manual = st.text_input("Add competitor", placeholder="e.g. BYJU'S",
                                   label_visibility="collapsed", key="nb_manual")
        with c2:
            if st.button("➕ Add", use_container_width=True, key="nb_add"):
                _validate_and_add(manual)
                st.session_state["nb_manual"] = ""
                st.rerun()
        with c3:
            if st.button("🗑 Clear all", use_container_width=True, key="nb_clear"):
                st.session_state["accepted_competitors"] = []
                st.session_state["nb_suggestions"] = []
                st.session_state["nb_last_topic"] = ""
                st.rerun()

        if st.session_state.get("validation_error"):
            st.error(st.session_state["validation_error"])

        # ── Active list (non-suggestion entries) ──────────────────────────────
        sugg_domains = {s["domain"] for s in suggestions}
        manual_entries = [
            c for c in st.session_state["accepted_competitors"]
            if c["domain"] not in sugg_domains
        ]
        if manual_entries:
            st.caption("**Manually added:**")
            to_remove = []
            all_comps = st.session_state["accepted_competitors"]
            for idx, comp in enumerate(all_comps):
                if comp["domain"] in sugg_domains:
                    continue
                cn, cx = st.columns([6, 1])
                cn.markdown(f"• **{comp['name']}** `{comp.get('domain','')}`")
                if cx.button("✕", key=f"nb_rm_{idx}_{comp.get('domain','x')[:6]}"):
                    to_remove.append(idx)
            for i in reversed(to_remove):
                st.session_state["accepted_competitors"].pop(i)
            if to_remove:
                st.rerun()

        # ── Watchlist load/save ───────────────────────────────────────────────
        st.markdown("---")
        wl_names = _load_wl_names()
        wc1, wc2 = st.columns(2)
        with wc1:
            if wl_names:
                chosen = st.selectbox("Load watchlist", ["— select —"] + wl_names,
                                      label_visibility="collapsed", key="nb_wl_load")
                if chosen != "— select —" and st.button("📂 Load", key="nb_wl_apply"):
                    _apply_wl(chosen)
                    st.rerun()
            else:
                st.caption("No saved watchlists.")
        with wc2:
            wl_name_input = st.text_input("Save list as", placeholder="My Watchlist",
                                          label_visibility="collapsed", key="nb_wl_name")
            if st.button("💾 Save", key="nb_wl_save"):
                _save_wl(wl_name_input)

    # ── Generate ──────────────────────────────────────────────────────────────
    st.markdown("")
    accepted_now = st.session_state.get("accepted_competitors", [])
    generate_label = ("⚡ Generate Report" if accepted_now
                      else "🕵️ Discover Competitors & Generate Report")
    run_btn = st.button(generate_label, type="primary",
                        use_container_width=True, key="nb_generate")

    if run_btn:
        competitors = [c["name"] for c in st.session_state["accepted_competitors"]]
        auto_discover = len(competitors) == 0
        if not topic.strip():
            st.error("Enter a market topic.")
            st.stop()
        # NOTE: competitors is intentionally allowed to be empty here — run_briefing()
        # treats an empty list as "run the Discovery Agent first" rather than an error.

        # ── Agent status display ──────────────────────────────────────────────
        st.markdown("#### 🤖 Agent Pipeline")
        agent_ph   = st.empty()
        progress   = st.progress(0, text="Initialising…")

        pipeline_names = (
            ["Supervisor", "Discovery Agent", "Research Agent", "Analyst Agent", "Writer Agent"]
            if auto_discover else
            ["Supervisor", "Research Agent", "Analyst Agent", "Writer Agent"]
        )

        def _show_agents(active: str, done: list[str]):
            with agent_ph.container():
                cols = st.columns(len(pipeline_names))
                for col, name in zip(cols, pipeline_names):
                    if name in done:
                        bc, lbl = "badge-ok",   "✅ Done"
                    elif name == active:
                        bc, lbl = "badge-run",  "⏳ Working"
                    else:
                        bc, lbl = "badge-warn", "⏸ Queued"
                    col.markdown(
                        f'<div class="kpi-card"><div class="kpi-label">{name}</div>'
                        f'<div class="badge {bc}">{lbl}</div></div>',
                        unsafe_allow_html=True,
                    )

        _show_agents("Supervisor", [])
        progress.progress(5, text="Supervisor: preparing crew…")
        if auto_discover:
            _show_agents("Discovery Agent", ["Supervisor"])
            progress.progress(12, text="Discovery Agent: identifying real competitors for this topic…")
        else:
            _show_agents("Research Agent", ["Supervisor"])
            progress.progress(15, text="Research Agent: searching live sources…")

        # competitors may be [] here — run_briefing runs the Discovery Agent first
        # in that case, and returns the resolved list on briefing.competitors.
        briefing = run_briefing(topic, competitors,
                                max_sources=max_sources, max_steps=max_steps)
        audit_events = AuditLogger.load(briefing.metadata.run_id)

        # If Discovery ran, sync the resolved competitors back into the UI's
        # accepted list so the user can see/edit them for next time.
        if auto_discover and briefing.competitors:
            st.session_state["accepted_competitors"] = [
                {"name": c, "domain": ""} for c in briefing.competitors
            ]

        _show_agents("", pipeline_names)
        progress.progress(100, text="Done ✅")

        try:
            tm_save(topic, briefing.competitors, briefing)
        except Exception:
            pass

        st.session_state["briefing"]     = briefing
        st.session_state["audit_events"] = audit_events
        st.session_state["nb_auto_discover"] = auto_discover
        st.rerun()

    # ── Show results if available ──────────────────────────────────────────────
    briefing = st.session_state.get("briefing")
    if not briefing:
        return

    m = briefing.metadata

    if st.session_state.get("nb_auto_discover"):
        st.success(
            f"🕵️ Discovery Agent identified {len(briefing.competitors)} competitor(s) "
            f"for **{briefing.topic}**: {', '.join(briefing.competitors) or '—'}. "
            "See the Executive Summary and Sources tab for the citations behind this list.",
            icon="🕵️",
        )

    st.markdown("---")
    st.markdown("#### 📊 Run Summary")

    cited_count = len(set(extract_citation_ids(briefing.markdown)))
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Status",          m.status.replace("_"," ").title())
    k2.metric("Exec Time",       f"{m.execution_time_seconds}s")
    k3.metric("Searches",        str(m.search_count))
    k4.metric("Sources",         str(m.sources_attempted))
    k5.metric("Failed",          str(m.sources_failed))
    k6.metric("Unique Citations", str(cited_count))

    # ── Urgency triage ────────────────────────────────────────────────────────
    try:
        from tools.urgency_triage import triage_briefing
        items = triage_briefing(briefing.markdown)
        high  = [i for i in items if i.severity == "high"]
        med   = [i for i in items if i.severity == "medium"]
        if items:
            with st.expander(
                f"🚨 Urgency Triage — {len(high)} high, {len(med)} medium",
                expanded=bool(high)
            ):
                for item in high:
                    st.markdown(
                        f'<div class="timeline-item"><span class="badge badge-danger">HIGH</span>'
                        f'&nbsp;&nbsp;<b>[{item.section}]</b> {item.text}'
                        f'<br><span style="color:var(--text-dim);font-size:0.8rem">'
                        f'{item.reason}</span></div>',
                        unsafe_allow_html=True,
                    )
                for item in med:
                    st.markdown(
                        f'<div class="timeline-item"><span class="badge badge-warn">MED</span>'
                        f'&nbsp;&nbsp;<b>[{item.section}]</b> {item.text}'
                        f'<br><span style="color:var(--text-dim);font-size:0.8rem">'
                        f'{item.reason}</span></div>',
                        unsafe_allow_html=True,
                    )
    except Exception:
        pass

    # ── Trend memory diff ─────────────────────────────────────────────────────
    try:
        history = _load_history()
        key = _normalize_key(briefing.topic, briefing.competitors)
        matching = [r for r in history if r.get("_key") == key]
        if len(matching) >= 2:
            prev_ts = matching[-2].get("timestamp", "")[:19].replace("T", " ")
            diff    = diff_insights(briefing.markdown, matching[-2]["markdown"])
            with st.expander(f"📈 Trend Memory — vs run from {prev_ts}"):
                st.markdown(diff)
        else:
            st.caption("📈 Trend Memory: first run for this topic.")
    except Exception:
        pass

    # ── Result tabs ───────────────────────────────────────────────────────────
    tabs = st.tabs(["📋 Final Briefing", "🔍 Research & Analysis",
                    "📎 Sources & Citations", "🧾 Audit Log"])

    with tabs[0]:
        st.markdown(briefing.markdown)
        # Export buttons
        ec1, ec2 = st.columns(2)
        with ec1:
            st.download_button("⬇️ Export Markdown", briefing.markdown,
                               file_name=f"{m.run_id}.md", use_container_width=True)
        with ec2:
            if st.button("📄 Export PDF", use_container_width=True, key="nb_pdf"):
                path = save_pdf(m.run_id, briefing.markdown)
                with open(path, "rb") as f:
                    st.download_button("⬇️ Download PDF", f.read(),
                                       file_name=Path(path).name,
                                       mime="application/pdf",
                                       use_container_width=True, key="nb_pdf_dl")

    with tabs[1]:
        st.markdown("#### Analyst Insights")
        for ins in briefing.insights:
            ev_badge = "badge-ok" if ins.strength == EvidenceStrength.CONFIRMED else "badge-warn"
            ev_label = ins.strength.value.replace("_", " ").title()
            conf_tag = getattr(ins, "confidence_tag", "unknown")
            cb = "badge-ok" if conf_tag == "corroborated" else ("badge-warn" if conf_tag == "single-source" else "")
            ci = ("✅ Corroborated" if conf_tag == "corroborated"
                  else "⚠️ Single-Source" if conf_tag == "single-source" else conf_tag)
            st.markdown(
                f'<div class="timeline-item">'
                f'<span class="badge {ev_badge}">{ev_label}</span>&nbsp;'
                f'<span class="badge {cb}">{ci}</span>&nbsp;&nbsp;'
                f'<b>{ins.competitor}</b> ({ins.category}) — {ins.insight} '
                f'<span style="color:var(--text-dim)">sources {ins.source_ids}</span></div>',
                unsafe_allow_html=True,
            )
        if not briefing.insights:
            st.info("Insights are populated in live mode from the pipeline output.")

    with tabs[2]:
        ok_src = [s for s in briefing.sources if s.status == SourceStatus.OK]
        if ok_src:
            for s in ok_src:
                tier = getattr(s, "trust_tier", "medium")
                tr   = getattr(s, "trust_reason", "")
                if tier == "high":
                    tb = f'<span class="badge badge-ok" title="{tr}">🟢 High Trust</span>'
                elif tier == "low":
                    tb = f'<span class="badge badge-danger" title="{tr}">🔴 Low Trust</span>'
                else:
                    tb = f'<span class="badge badge-warn" title="{tr}">🟡 Medium Trust</span>'
                st.markdown(f'{tb} &nbsp;<b>[{s.id}]</b> '
                            f'<a href="{s.url}" target="_blank">{s.title or s.url}</a>',
                            unsafe_allow_html=True)
                if s.snippet:
                    st.caption(s.snippet[:180])
        else:
            st.info("Sources are listed in the Final Briefing tab under '## Sources & Citations'.")

        bad = [s for s in briefing.sources if s.status != SourceStatus.OK]
        if bad:
            st.markdown("#### Failed Sources")
            for s in bad:
                st.markdown(f'<span class="badge badge-danger">{s.status.value}</span> {s.url}',
                            unsafe_allow_html=True)

    with tabs[3]:
        events = st.session_state.get("audit_events", [])
        if events:
            agent_counts: dict[str, int] = {}
            for e in events:
                ag = e.get("agent", "—")
                agent_counts[ag] = agent_counts.get(ag, 0) + 1
            st.markdown("#### Agent Activity")
            ac = st.columns(len(agent_counts))
            for col, (ag, cnt) in zip(ac, agent_counts.items()):
                col.metric(ag, cnt, help="audit events logged")
        st.markdown("#### Full Audit Trail")
        for e in (events or []):
            kind_badge = {"tool_call": "badge-run", "decision": "badge-ok",
                          "retry": "badge-warn", "failure": "badge-danger",
                          "limit_reached": "badge-warn"}.get(e.get("event_type",""), "badge-run")
            st.markdown(
                f'<div class="timeline-item">'
                f'<span class="badge {kind_badge}">{e.get("event_type","event")}</span>'
                f'&nbsp;&nbsp;<b>{e.get("agent","")}</b> — {e.get("message","")}'
                f'<span class="timeline-time">&nbsp;{e.get("timestamp","")}</span></div>',
                unsafe_allow_html=True,
            )
        if not events:
            st.info("No audit events yet.")



# ── Page: History ─────────────────────────────────────────────────────────────
def page_history():
    st.markdown("""
    <div class="app-header">
      <div>
        <div class="title">📚 History</div>
        <div class="subtitle">All past briefing runs</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    history = _load_history()
    if not history:
        st.info("No past runs yet. Run a briefing first.")
        if st.button("✍️ New Briefing", type="primary"):
            st.session_state["page"] = "New Briefing"
            st.rerun()
        return

    # ── Run list ──────────────────────────────────────────────────────────────
    selected_id = st.session_state.get("history_view_run_id")

    st.markdown(f"**{len(history)} total runs**")

    # Search / filter
    search = st.text_input("🔍 Filter by topic or competitor",
                           placeholder="e.g. EdTech", key="hist_search")

    filtered = [
        r for r in reversed(history)
        if not search or search.lower() in r.get("topic","").lower()
        or any(search.lower() in c.lower() for c in r.get("competitors", []))
    ]

    if not filtered:
        st.warning(f"No runs matching '{search}'.")
        return

    for i, r in enumerate(filtered):
        ts    = r.get("timestamp", "")[:19].replace("T", " ")
        tp    = r.get("topic", "—")
        comp  = ", ".join(r.get("competitors", []))
        rid   = r.get("run_id", "")
        is_sel = rid == selected_id

        with st.container():
            c1, c2, c3, c4 = st.columns([2, 3, 4, 1])
            c1.caption(ts)
            c2.markdown(f"**{tp}**")
            c3.caption(comp[:70] + ("…" if len(comp) > 70 else ""))
            btn_label = "▼ Hide" if is_sel else "View"
            if c4.button(btn_label, key=f"hv_{i}_{rid[:6]}"):
                if is_sel:
                    st.session_state.pop("history_view_run_id", None)
                else:
                    st.session_state["history_view_run_id"] = rid
                st.rerun()

        if is_sel:
            md = r.get("markdown", "")
            with st.expander("📋 Full Report", expanded=True):
                st.markdown(md if md else "_No markdown saved for this run._")

                key = _normalize_key(r.get("topic",""), r.get("competitors",[]))
                matching = [h for h in history if h.get("_key") == key]
                pos = next((j for j, h in enumerate(matching) if h.get("run_id") == rid), None)
                if pos is not None and pos > 0:
                    prev = matching[pos - 1]
                    diff = diff_insights(md, prev.get("markdown",""))
                    prev_ts = prev.get("timestamp","")[:19].replace("T"," ")
                    with st.expander(f"📈 Diff vs {prev_ts}"):
                        st.markdown(diff)

                if md:
                    st.download_button("⬇️ Export Markdown", md,
                                       file_name=f"{rid}.md",
                                       use_container_width=True,
                                       key=f"hdl_{i}_{rid[:6]}")
            st.markdown("---")


# ── Router ─────────────────────────────────────────────────────────────────────
page = st.session_state.get("page", "Dashboard")
if page == "Dashboard":
    page_dashboard()
elif page == "New Briefing":
    page_new_briefing()
elif page == "History":
    page_history()