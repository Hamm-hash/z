
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Intelligent Study Planning Agent",
    page_icon="📚",
    layout="wide"
)

DB = Path(__file__).with_name("study_agent.db")


# =====================================
# DATABASE
# =====================================

def connect():
    return sqlite3.connect(DB)


def initialize():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                due_date TEXT NOT NULL,
                difficulty INTEGER NOT NULL,
                estimated_hours REAL NOT NULL,
                completed_hours REAL NOT NULL DEFAULT 0,
                done INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)


def get_setting(name, default):
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?",
            (name,)
        ).fetchone()

    return row[0] if row else default


def set_setting(name, value):
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
            (name, str(value))
        )


def get_tasks():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY due_date,id"
        ).fetchall()

    columns = [
        "id", "subject", "title", "kind",
        "due_date", "difficulty",
        "estimated_hours", "completed_hours",
        "done"
    ]

    return [dict(zip(columns, row)) for row in rows]


def add_task(subject, title, kind, due, difficulty, estimated):
    with connect() as conn:
        conn.execute("""
            INSERT INTO tasks
            (subject,title,kind,due_date,difficulty,estimated_hours)
            VALUES (?,?,?,?,?,?)
        """, (
            subject.strip(),
            title.strip(),
            kind,
            due.isoformat(),
            difficulty,
            float(estimated)
        ))


def update_hours(task_id, additional):
    with connect() as conn:
        conn.execute("""
            UPDATE tasks
            SET completed_hours =
                MIN(estimated_hours, completed_hours + ?),
                done = CASE
                    WHEN completed_hours + ? >= estimated_hours
                    THEN 1 ELSE done END
            WHERE id=?
        """, (
            float(additional),
            float(additional),
            int(task_id)
        ))


def mark_done(task_id):
    with connect() as conn:
        conn.execute("""
            UPDATE tasks
            SET done=1,
                completed_hours=estimated_hours
            WHERE id=?
        """, (int(task_id),))


def delete_task(task_id):
    with connect() as conn:
        conn.execute(
            "DELETE FROM tasks WHERE id=?",
            (int(task_id),)
        )


# =====================================
# INTELLIGENT AGENT
# =====================================

def score(task, current_date):

    remaining_days = max(
        (
            date.fromisoformat(task["due_date"])
            - current_date
        ).days,
        0
    )

    urgency = 10 / (remaining_days + 1)

    work = max(
        task["estimated_hours"]
        - task["completed_hours"],
        0
    )

    priority = (
        urgency * 3
        + task["difficulty"] * 2
        + (4 if task["kind"] == "Exam" else 0)
        + min(work, 15) * 0.2
    )

    return priority


def make_plan(tasks, daily_hours, horizon=14):

    today = date.today()

    remaining = {
        t["id"]: round(
            max(
                t["estimated_hours"] - t["completed_hours"],
                0
            ),
            2
        )
        for t in tasks if not t["done"]
    }

    output = []

    for day_offset in range(horizon):

        day = today + timedelta(days=day_offset)
        budget = daily_hours

        eligible = [
            t for t in tasks
            if t["id"] in remaining
            and remaining[t["id"]] > 0
            and date.fromisoformat(t["due_date"]) >= day
        ]

        eligible.sort(
            key=lambda t: (
                -score(t, day),
                t["due_date"],
                t["id"]
            )
        )

        while budget >= 0.25 and eligible:

            t = eligible[0]

            chunk = round(
                min(
                    1.0,
                    budget,
                    remaining[t["id"]]
                ),
                2
            )

            if chunk < 0.25:
                break

            output.append({
                "Date": day.isoformat(),
                "Subject": t["subject"],
                "Task": t["title"],
                "Type": t["kind"],
                "Study hours": chunk,
                "Task ID": t["id"]
            })

            remaining[t["id"]] = round(
                remaining[t["id"]] - chunk,
                2
            )

            budget = round(budget - chunk, 2)

            eligible = [
                x for x in eligible
                if remaining[x["id"]] >= 0.25
            ]

            eligible.sort(
                key=lambda x: (
                    -score(x, day),
                    x["due_date"],
                    x["id"]
                )
            )

    return output


# =====================================
# APPLICATION
# =====================================

initialize()

st.title("📚 Intelligent Study Planning Agent")

st.caption(
    "An adaptive, rule-based study planner "
    "for university students"
)


# =====================================
# SIDEBAR
# =====================================

with st.sidebar:

    st.header("⚙️ Study Availability")

    daily = float(
        get_setting("daily_hours", "3.0")
    )

    daily = st.slider(
        "Available study hours per day",
        min_value=0.5,
        max_value=12.0,
        value=max(0.5, min(12.0, daily)),
        step=0.5
    )

    if str(daily) != get_setting(
        "daily_hours", "3.0"
    ):
        set_setting("daily_hours", daily)

    st.info(
        "Reminders appear when you open "
        "or refresh the application."
    )

    st.write(
        "Your information is saved locally."
    )


# =====================================
# TASK INFORMATION
# =====================================

tasks = get_tasks()

active = [
    t for t in tasks if not t["done"]
]

now = date.today()


# =====================================
# SMART REMINDERS
# =====================================

alerts = []

for task in active:

    days = (
        date.fromisoformat(task["due_date"])
        - now
    ).days

    if days < 0:

        alerts.append((
            "error",
            f"OVERDUE: {task['subject']} - "
            f"{task['title']} ({-days} days late)"
        ))

    elif days == 0:

        alerts.append((
            "error",
            f"DUE TODAY: {task['subject']} - "
            f"{task['title']}"
        ))

    elif days <= 2:

        alerts.append((
            "warning",
            f"Due in {days} day(s): "
            f"{task['subject']} - {task['title']}"
        ))


for kind, message in alerts:

    if kind == "error":
        st.error("🔔 " + message)

    else:
        st.warning("🔔 " + message)


# =====================================
# DASHBOARD
# =====================================

col1, col2, col3 = st.columns(3)

col1.metric(
    "Active Tasks",
    len(active)
)

col2.metric(
    "Completed Tasks",
    len(tasks) - len(active)
)

remaining_total = sum(
    max(
        t["estimated_hours"] - t["completed_hours"],
        0
    )
    for t in active
)

col3.metric(
    "Study Hours Remaining",
    f"{remaining_total:.1f} h"
)


# =====================================
# MAIN TABS
# =====================================

add_tab, planner_tab, tracking_tab = st.tabs([
    "➕ Add Tasks",
    "🗓️ Smart Plan",
    "✅ Track Progress"
])


# =====================================
# PAGE 1: ADD TASKS
# =====================================

with add_tab:

    st.subheader("New Study Task")

    with st.form("task_form", clear_on_submit=True):

        subject = st.text_input(
            "Subject",
            placeholder="Enter your subject name"
        )

        title = st.text_input(
            "Task or Exam",
            placeholder="Enter your task name"
        )

        c1, c2 = st.columns(2)

        with c1:
            kind = st.selectbox(
                "Type",
                ["Exam", "Assignment", "Revision", "Project"]
            )

            due = st.date_input(
                "Due Date",
                min_value=date.today()
            )

        with c2:
            difficulty_name = st.selectbox(
                "Difficulty",
                ["Easy", "Medium", "Hard"]
            )

            hours = st.number_input(
                "Total Study Hours Needed",
                min_value=0.5,
                max_value=200.0,
                value=3.0,
                step=0.5
            )

        submit = st.form_submit_button(
            "Save Task",
            type="primary"
        )

        if submit:
            if not subject.strip() or not title.strip():
                st.error(
                    "Please enter a subject and task name."
                )
            else:
                difficulty = {
                    "Easy": 1,
                    "Medium": 2,
                    "Hard": 3
                }[difficulty_name]

                add_task(
                    subject,
                    title,
                    kind,
                    due,
                    difficulty,
                    hours
                )

                st.success("Task saved successfully!")
                st.rerun()

# PAGE 2: SMART STUDY PLAN
# =====================================

with planner_tab:

    st.subheader(
        "Personalized Study Schedule"
    )

    if active:

        plan = make_plan(
            active,
            daily
        )

        if plan:

            df = pd.DataFrame(plan)

            today_df = df[
                df["Date"] == now.isoformat()
            ]

            st.markdown(
                "### 📅 Today's Study Sessions"
            )

            if not today_df.empty:

                st.dataframe(
                    today_df[
                        [
                            "Subject",
                            "Task",
                            "Study hours"
                        ]
                    ],
                    hide_index=True,
                    use_container_width=True
                )

            else:

                st.info(
                    "No sessions scheduled today."
                )

            st.markdown(
                "### 🗓️ Next 14 Days"
            )

            st.dataframe(
                df[
                    [
                        "Date",
                        "Subject",
                        "Task",
                        "Type",
                        "Study hours"
                    ]
                ],
                hide_index=True,
                use_container_width=True
            )

            st.download_button(
                "Download Study Schedule",
                df.to_csv(index=False).encode("utf-8"),
                file_name="study_schedule.csv",
                mime="text/csv"
            )

            assigned = (
                df.groupby("Task ID")["Study hours"]
                .sum()
                .to_dict()
            )

            for t in active:

                unplanned = round(
                    max(
                        t["estimated_hours"]
                        - t["completed_hours"],
                        0
                    )
                    - assigned.get(t["id"], 0),
                    2
                )

                if unplanned >= 0.25:

                    st.warning(
                        f"Not enough available time for "
                        f"{t['subject']} - {t['title']}. "
                        f"{unplanned:g} hours unplanned. "
                        f"Consider increasing study hours."
                    )

        else:

            st.info(
                "No sessions can be scheduled. "
                "Please check your deadlines."
            )

    else:

        st.info(
            "Add at least one task to generate "
            "your study schedule."
        )


# =====================================
# PAGE 3: TRACK PROGRESS
# =====================================

with tracking_tab:

    st.subheader(
        "Track Progress and Replan"
    )

    if not tasks:

        st.info(
            "No tasks added yet."
        )

    else:

        for t in tasks:

            task_label = (
                f"{'✅' if t['done'] else '📘'} "
                f"{t['subject']} - {t['title']} "
                f"(Due {t['due_date']})"
            )

            with st.expander(task_label):

                progress = min(
                    t["completed_hours"]
                    / t["estimated_hours"],
                    1.0
                )

                st.progress(progress)

                st.write(
                    f"{t['completed_hours']:g} / "
                    f"{t['estimated_hours']:g} "
                    f"hours completed"
                )

                if not t["done"]:

                    remaining_hours = round(
                        t["estimated_hours"]
                        - t["completed_hours"],
                        2
                    )

                    added = st.number_input(
                        "Hours Studied",
                        min_value=0.25,
                        max_value=max(
                            0.25,
                            remaining_hours
                        ),
                        value=min(
                            0.5,
                            max(0.25, remaining_hours)
                        ),
                        step=0.25,
                        key=f"study_{t['id']}"
                    )

                    a, b, c = st.columns(3)

                    if a.button(
                        "Log Hours",
                        key=f"log_{t['id']}"
                    ):

                        update_hours(
                            t["id"],
                            added
                        )

                        st.rerun()

                    if b.button(
                        "Mark Complete",
                        key=f"done_{t['id']}"
                    ):

                        mark_done(t["id"])

                        st.rerun()

                    if c.button(
                        "Delete",
                        key=f"delete_{t['id']}"
                    ):

                        delete_task(t["id"])

                        st.rerun()

                else:

                    st.success(
                        "Task completed!"
                    )

                    if st.button(
                        "Delete",
                        key=f"delete_{t['id']}"
                    ):

                        delete_task(t["id"])

                        st.rerun()


# =====================================
# FOOTER
# =====================================

st.divider()

st.caption(
    "Intelligent Agent Cycle: "
    "Observe → Prioritize → Plan → Adapt"
)

st.caption(
    "This application uses a rule-based "
    "intelligent decision-making system."
)
