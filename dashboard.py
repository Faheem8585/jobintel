"""
JobIntel Streamlit Dashboard.

A visual interface for the JobIntel skill with five sections:
  1. Overview  — pipeline stats and digest summary
  2. Applications — full tracker with add/update/delete
  3. Analyser  — paste a JD, get match score + gap report
  4. Search    — job board search results
  5. Profile   — view and edit the candidate profile

Talks directly to the skill's service layer (no HTTP hop needed).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on the path when run via `streamlit run dashboard.py`
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

import skill as sk

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="JobIntel",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Warm up services once per session
# ---------------------------------------------------------------------------

@st.cache_resource
def _init_services():
    sk._get_services()
    return True

_init_services()

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

PAGES = ["📊 Overview", "📋 Applications", "🔍 Analyser", "🌐 Search", "👤 Profile"]
page = st.sidebar.radio("Navigate", PAGES, label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.caption("JobIntel v1.0.0")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATUS_EMOJI = {
    "wishlist": "📋",
    "applied": "📤",
    "phone_screen": "📞",
    "technical": "💻",
    "onsite": "🏢",
    "offer": "🎉",
    "rejected": "❌",
    "withdrawn": "↩️",
    "accepted": "✅",
}

STATUS_OPTIONS = ["wishlist", "applied", "phone_screen", "technical", "onsite", "offer", "rejected", "withdrawn", "accepted"]

MATCH_COLOURS = {
    "Strong Match": "🟢",
    "Good Match":   "🟡",
    "Weak Match":   "🟠",
    "Poor Match":   "🔴",
}


def _call(tool: str, params: dict) -> dict:
    """Call a skill tool and surface errors as st.error."""
    result = sk.handle_tool_call(tool, params)
    if "error" in result:
        st.error(result["error"])
        return {}
    return result


# ===========================================================================
# PAGE 1 — Overview
# ===========================================================================

if page == "📊 Overview":
    st.title("📊 Overview")

    stats = _call("get_stats", {})
    if stats:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Applications", stats.get("total", 0))
        c2.metric("Active", stats.get("active", 0))
        c3.metric("Response Rate", f"{stats.get('response_rate_pct', 0):.0f}%")
        c4.metric("Offer Rate", f"{stats.get('offer_rate_pct', 0):.0f}%")

        st.divider()
        st.subheader("Pipeline Breakdown")
        by_status = stats.get("by_status", {})
        if by_status:
            cols = st.columns(len(by_status))
            for col, (status, count) in zip(cols, sorted(by_status.items())):
                emoji = STATUS_EMOJI.get(status, "•")
                col.metric(f"{emoji} {status.replace('_', ' ').title()}", count)
        else:
            st.info("No applications yet — head to the Applications tab to add some.")

    st.divider()
    st.subheader("Daily Digest")

    if st.button("🔄 Generate Digest"):
        with st.spinner("Generating…"):
            digest = _call("get_daily_digest", {})
        if digest:
            st.code(digest.get("formatted_text", ""), language=None)

    st.divider()
    st.subheader("⏰ Upcoming Deadlines")
    apps = _call("list_applications", {"limit": 200})
    if apps:
        deadlines = [
            a for a in apps.get("applications", [])
            if a.get("deadline") and a["status"] not in ("rejected", "withdrawn", "accepted")
        ]
        if deadlines:
            for a in sorted(deadlines, key=lambda x: x["deadline"]):
                st.warning(f"**{a['company']}** — {a['role']} · deadline: `{a['deadline']}`")
        else:
            st.success("No upcoming deadlines.")


# ===========================================================================
# PAGE 2 — Applications
# ===========================================================================

elif page == "📋 Applications":
    st.title("📋 Applications")

    # ---- Filters ----
    col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
    with col_f1:
        filter_status = st.selectbox("Filter by status", ["(all)"] + STATUS_OPTIONS)
    with col_f2:
        filter_company = st.text_input("Filter by company")
    with col_f3:
        st.write("")
        st.write("")
        refresh = st.button("🔄 Refresh")

    status_param = None if filter_status == "(all)" else filter_status
    data = _call("list_applications", {"status": status_param, "company": filter_company or None, "limit": 200})
    apps = data.get("applications", [])

    st.caption(f"{len(apps)} application(s)")

    # ---- Table ----
    if apps:
        for app in apps:
            emoji = STATUS_EMOJI.get(app["status"], "•")
            score_str = f"  ·  Match: {app['match_score']:.0%}" if app.get("match_score") else ""
            label = f"{emoji} **{app['company']}** — {app['role']} · `{app['status']}`{score_str}"

            with st.expander(label):
                c1, c2 = st.columns(2)
                c1.write(f"**ID:** `{app['id']}`")
                c1.write(f"**Location:** {app.get('location') or '—'}")
                c1.write(f"**Applied:** {app.get('applied_date') or '—'}")
                c1.write(f"**Deadline:** {app.get('deadline') or '—'}")
                c2.write(f"**Notes:** {app.get('notes') or '—'}")
                if app.get("url"):
                    c2.write(f"**URL:** {app['url']}")

                st.divider()
                col_s, col_n, col_d = st.columns([2, 3, 1])

                with col_s:
                    new_status = st.selectbox(
                        "Change status", STATUS_OPTIONS,
                        index=STATUS_OPTIONS.index(app["status"]),
                        key=f"status_{app['id']}",
                    )
                    if st.button("Update status", key=f"upd_{app['id']}"):
                        result = _call("update_application_status", {
                            "app_id": app["id"], "new_status": new_status
                        })
                        if result:
                            st.success(f"→ {result['new_status']}")
                            st.rerun()

                with col_n:
                    new_notes = st.text_area("Notes", value=app.get("notes", ""), key=f"notes_{app['id']}")
                    if st.button("Save notes", key=f"savnotes_{app['id']}"):
                        tracker, *_ = sk._get_services()
                        tracker.update_notes(app["id"], new_notes)
                        st.success("Saved.")
                        st.rerun()

                with col_d:
                    st.write("")
                    st.write("")
                    if st.button("🗑 Delete", key=f"del_{app['id']}"):
                        _call("update_application_status", {})  # trigger init
                        tracker, *_ = sk._get_services()
                        tracker.delete(app["id"])
                        st.rerun()
    else:
        st.info("No applications match your filters.")

    # ---- Add new ----
    st.divider()
    st.subheader("➕ Add Application")
    with st.form("add_app"):
        fc1, fc2 = st.columns(2)
        company   = fc1.text_input("Company *")
        role      = fc2.text_input("Role *")
        location  = fc1.text_input("Location")
        url       = fc2.text_input("Job URL")
        status    = fc1.selectbox("Status", STATUS_OPTIONS)
        contact   = fc2.text_input("Contact / Recruiter")
        applied_d = fc1.text_input("Applied date (YYYY-MM-DD)")
        deadline  = fc2.text_input("Deadline (YYYY-MM-DD)")
        sal_min   = fc1.number_input("Salary min", min_value=0, value=0)
        sal_max   = fc2.number_input("Salary max", min_value=0, value=0)
        notes     = st.text_area("Notes")
        submitted = st.form_submit_button("Add Application")

    if submitted:
        if not company or not role:
            st.error("Company and Role are required.")
        else:
            result = _call("track_application", {
                "company": company, "role": role, "location": location,
                "url": url or None, "status": status, "contact": contact,
                "applied_date": applied_d or None, "deadline": deadline or None,
                "salary_min": sal_min or None, "salary_max": sal_max or None,
                "notes": notes,
            })
            if result:
                st.success(f"Added: **{role}** at **{company}** (ID: `{result['id']}`)")
                st.rerun()


# ===========================================================================
# PAGE 3 — Analyser
# ===========================================================================

elif page == "🔍 Analyser":
    st.title("🔍 Job Description Analyser")

    tab_jd, tab_gap = st.tabs(["Match Scorer", "CV Gap Analyser"])

    # ---- Match Scorer ----
    with tab_jd:
        st.write("Paste a job description to extract skills and compute your match score.")
        with st.form("jd_form"):
            jd_title   = st.text_input("Job Title (optional)")
            jd_company = st.text_input("Company (optional)")
            jd_loc     = st.text_input("Location (optional)")
            jd_text    = st.text_area("Job Description *", height=300,
                                      placeholder="Paste the full job posting here…")
            run_jd = st.form_submit_button("Analyse")

        if run_jd:
            if not jd_text.strip():
                st.error("Please paste a job description.")
            else:
                with st.spinner("Analysing…"):
                    result = _call("analyze_job_description", {
                        "raw_text": jd_text, "title": jd_title,
                        "company": jd_company, "location": jd_loc,
                    })
                if result:
                    job = result.get("job", {})
                    score = result.get("match_score")
                    label = result.get("match_label", "")
                    breakdown = result.get("score_breakdown", {})

                    # Score banner
                    colour = MATCH_COLOURS.get(label, "⚪")
                    if score is not None:
                        st.markdown(f"## {colour} {label} — {score:.0%}")
                        bc1, bc2, bc3, bc4 = st.columns(4)
                        bc1.metric("Skills",     f"{breakdown.get('skills', 0):.0%}")
                        bc2.metric("Experience", f"{breakdown.get('experience', 0):.0%}")
                        bc3.metric("Education",  f"{breakdown.get('education', 0):.0%}")
                        bc4.metric("Location",   f"{breakdown.get('location', 0):.0%}")
                    else:
                        st.info("Set your profile on the Profile tab to enable match scoring.")

                    st.divider()
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        st.subheader("Required Skills")
                        for s in job.get("required_skills", []):
                            matched = s in result.get("top_matching_skills", [])
                            icon = "✅" if matched else "❌"
                            st.write(f"{icon} `{s}`")

                    with dc2:
                        st.subheader("Nice to Have")
                        for s in job.get("nice_to_have_skills", []):
                            matched = s in result.get("top_matching_skills", [])
                            icon = "✅" if matched else "⬜"
                            st.write(f"{icon} `{s}`")

                    st.divider()
                    ic1, ic2, ic3 = st.columns(3)
                    ic1.write(f"**Seniority:** `{job.get('seniority', '—')}`")
                    ic2.write(f"**Years req:** `{job.get('years_required') or '—'}`")
                    ic3.write(f"**Education:** `{job.get('education_required') or '—'}`")

                    sc1, sc2, sc3 = st.columns(3)
                    sal_min = job.get("salary_min")
                    sal_max = job.get("salary_max")
                    salary_str = (
                        f"€{sal_min:,} – €{sal_max:,}" if sal_min and sal_max
                        else f"up to €{sal_max:,}" if sal_max
                        else "—"
                    )
                    sc1.write(f"**Salary:** {salary_str}")
                    sc2.write(f"**Remote:** {'✅' if job.get('remote_ok') else '❌'}")
                    sc3.write(f"**Languages:** {', '.join(job.get('language_requirements', [])) or '—'}")

                    # Quick-add to tracker
                    st.divider()
                    if st.button("➕ Add to Application Tracker"):
                        r = _call("track_application", {
                            "company": job.get("company") or jd_company,
                            "role": job.get("title") or jd_title or "Unknown Role",
                            "location": job.get("location") or jd_loc,
                            "match_score": score,
                        })
                        if r:
                            st.success(f"Added to tracker! ID: `{r['id']}`")

    # ---- Gap Analyser ----
    with tab_gap:
        st.write("Find missing skills before you apply.")
        with st.form("gap_form"):
            gap_title   = st.text_input("Job Title (optional)")
            gap_company = st.text_input("Company (optional)")
            gap_text    = st.text_area("Job Description *", height=300,
                                       placeholder="Paste the full job posting here…")
            run_gap = st.form_submit_button("Find Gaps")

        if run_gap:
            if not gap_text.strip():
                st.error("Please paste a job description.")
            else:
                with st.spinner("Analysing gaps…"):
                    result = _call("analyze_cv_gap", {
                        "raw_jd_text": gap_text, "title": gap_title, "company": gap_company,
                    })
                if result:
                    cov = result.get("coverage_pct", 0)
                    colour = "🟢" if cov >= 80 else "🟡" if cov >= 50 else "🔴"
                    st.markdown(f"## {colour} Required Skills Coverage: {cov:.0f}%")
                    st.progress(cov / 100)

                    gc1, gc2, gc3 = st.columns(3)
                    with gc1:
                        st.subheader("✅ Matching Skills")
                        for s in result.get("matching_skills", []):
                            st.success(f"`{s}`")
                        if not result.get("matching_skills"):
                            st.write("None")

                    with gc2:
                        st.subheader("❌ Missing Required")
                        for s in result.get("missing_required", []):
                            priority = s in result.get("priority_gaps", [])
                            badge = "🔥" if priority else ""
                            st.error(f"{badge} `{s}`")
                        if not result.get("missing_required"):
                            st.write("None — you meet all requirements!")

                    with gc3:
                        st.subheader("⬜ Missing Nice-to-Have")
                        for s in result.get("missing_nice_to_have", []):
                            st.warning(f"`{s}`")
                        if not result.get("missing_nice_to_have"):
                            st.write("None")

                    st.divider()
                    st.subheader("💡 Suggestions")
                    for tip in result.get("suggested_additions", []):
                        st.info(tip)


# ===========================================================================
# PAGE 4 — Search
# ===========================================================================

elif page == "🌐 Search":
    st.title("🌐 Job Search")
    st.write("Search LinkedIn, Indeed, StepStone, and XING simultaneously.")

    with st.form("search_form"):
        sc1, sc2 = st.columns(2)
        query    = sc1.text_input("Keywords *", placeholder="AI Engineer Python Berlin")
        location = sc2.text_input("Location", value="Germany")
        sources  = st.multiselect(
            "Sources",
            ["linkedin", "indeed", "stepstone", "xing"],
            default=["linkedin", "indeed"],
        )
        run_search = st.form_submit_button("🔍 Search")

    if run_search:
        if not query.strip():
            st.error("Please enter a search query.")
        else:
            with st.spinner(f"Searching {', '.join(sources)}…"):
                result = _call("search_jobs", {
                    "query": query,
                    "location": location or None,
                    "sources": sources or None,
                })
            if result:
                jobs = result.get("results", [])
                st.success(f"Found **{result.get('count', 0)}** results")

                for job in jobs:
                    source_badge = f"`{job['source']}`"
                    title_line = f"**{job['title']}** at **{job['company']}**"
                    loc_line = f"📍 {job['location']}" if job.get("location") else ""

                    with st.container():
                        hc1, hc2 = st.columns([4, 1])
                        with hc1:
                            st.markdown(f"{title_line}  ·  {source_badge}  {loc_line}")
                            if job.get("snippet"):
                                st.caption(job["snippet"][:180] + "…" if len(job.get("snippet","")) > 180 else job.get("snippet",""))
                        with hc2:
                            if job.get("url"):
                                st.link_button("View →", job["url"])
                            if st.button("➕ Track", key=f"track_{hash(job['title']+job['company'])}"):
                                r = _call("track_application", {
                                    "company": job["company"],
                                    "role": job["title"],
                                    "location": job.get("location", ""),
                                    "url": job.get("url"),
                                })
                                if r:
                                    st.success("Added to tracker!")
                        st.divider()

                if not jobs:
                    st.info("No results returned. Try different keywords or sources.")


# ===========================================================================
# PAGE 5 — Profile
# ===========================================================================

elif page == "👤 Profile":
    st.title("👤 Candidate Profile")

    db = sk._get_db()
    profile = db.load_candidate_profile()

    if profile:
        st.success(f"Profile loaded: **{profile.name}**  ·  last updated `{profile.updated_at.strftime('%Y-%m-%d %H:%M')}`")
        pc1, pc2, pc3 = st.columns(3)
        pc1.metric("Skills", len(profile.skills))
        pc2.metric("Experience", f"{profile.years_of_experience} yrs")
        pc3.metric("Education", profile.education_level or "—")

        st.subheader("Skills")
        if profile.skills:
            skill_cols = st.columns(4)
            for i, skill in enumerate(sorted(profile.skills, key=lambda s: -(s.proficiency or 0))):
                pct = f" {skill.proficiency:.0%}" if skill.proficiency else ""
                skill_cols[i % 4].write(f"`{skill.name}`{pct}")

        st.subheader("Targets")
        tc1, tc2 = st.columns(2)
        tc1.write("**Roles:** " + ", ".join(profile.target_roles or ["—"]))
        tc2.write("**Locations:** " + ", ".join(profile.target_locations or ["—"]))

        st.divider()

    st.subheader("Update Profile")
    with st.form("profile_form"):
        pf1, pf2 = st.columns(2)
        p_name  = pf1.text_input("Name *", value=profile.name if profile else "")
        p_email = pf2.text_input("Email", value=profile.email if profile else "")
        p_yoe   = pf1.number_input("Years of experience", min_value=0.0, step=0.5,
                                    value=float(profile.years_of_experience) if profile else 0.0)
        p_edu   = pf2.text_input("Education level (e.g. MSc, BSc, PhD)",
                                  value=profile.education_level if profile else "")
        p_field = pf1.text_input("Education field",
                                  value=profile.education_field if profile else "")
        p_roles = st.text_input(
            "Target roles (comma-separated)",
            value=", ".join(profile.target_roles) if profile else "AI Engineer, Data Scientist",
        )
        p_locs  = st.text_input(
            "Target locations (comma-separated)",
            value=", ".join(profile.target_locations) if profile else "Berlin, Munich, Remote",
        )
        p_langs = st.text_input(
            "Spoken languages (comma-separated)",
            value=", ".join(profile.languages) if profile else "English, German",
        )
        p_cv    = st.text_area(
            "Paste your CV text (used for keyword matching)",
            height=200,
            value=profile.cv_raw_text if profile else "",
        )
        p_skills_raw = st.text_area(
            "Skills — one per line as  name, category, proficiency  (e.g. python, language, 0.95)",
            height=200,
            value="\n".join(
                f"{s.name}, {s.category.value}, {s.proficiency or ''}"
                for s in profile.skills
            ) if profile else "",
        )
        save_profile = st.form_submit_button("💾 Save Profile")

    if save_profile:
        skills_list = []
        for line in p_skills_raw.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 1 and parts[0]:
                entry: dict = {"name": parts[0]}
                if len(parts) >= 2:
                    entry["category"] = parts[1]
                if len(parts) >= 3:
                    try:
                        entry["proficiency"] = float(parts[2])
                    except ValueError:
                        pass
                skills_list.append(entry)

        result = _call("set_candidate_profile", {
            "name": p_name,
            "email": p_email,
            "skills": skills_list,
            "years_of_experience": p_yoe,
            "education_level": p_edu,
            "education_field": p_field,
            "target_roles": [r.strip() for r in p_roles.split(",") if r.strip()],
            "target_locations": [l.strip() for l in p_locs.split(",") if l.strip()],
            "languages": [l.strip() for l in p_langs.split(",") if l.strip()],
            "cv_raw_text": p_cv,
        })
        if result:
            st.success(f"Profile saved! {result['skills_count']} skills stored.")
            st.rerun()
