"""
ai_risk.py — AI Risk Prediction Module for IMS Portal
--------------------------------------------------------
Drop this file into your ims_app/ folder (same level as app.py).
Then add the routes from ai_routes_snippet.py into your app.py.

This module:
1. Calculates a Risk Score for every trainee using attendance, marks, and submissions
2. Classifies risk as Low / Medium / High
3. Generates AI-powered personalized feedback using the Claude API (optional)
4. Falls back to rule-based feedback if no API key is configured
"""

import os
import json
import urllib.request
import urllib.error


# ── Risk Score Calculation ──────────────────────────────────────────────────

def calculate_risk_score(attendance_pct, avg_marks_pct, pending_ratio_pct):
    """
    Calculates a 0-100 risk score.
    Higher score = higher risk.

    attendance_pct    : 0-100, student's attendance percentage
    avg_marks_pct     : 0-100, student's average marks percentage
    pending_ratio_pct : 0-100, percentage of tasks/assignments NOT submitted
    """

    # Convert Decimal/None to float
    attendance_pct = float(attendance_pct or 0)
    avg_marks_pct = float(avg_marks_pct or 0)
    pending_ratio_pct = float(pending_ratio_pct or 0)

    risk = (
        (100.0 - attendance_pct) * 0.40 +
        (100.0 - avg_marks_pct) * 0.35 +
        pending_ratio_pct * 0.25
    )

    return round(min(100.0, max(0.0, risk)), 1)


def risk_level(score):
    """Convert numeric score to a label + color."""
    if score <= 30:
        return {"label": "Low Risk",    "color": "success", "emoji": "🟢"}
    elif score <= 60:
        return {"label": "Medium Risk", "color": "warning", "emoji": "🟡"}
    else:
        return {"label": "High Risk",   "color": "danger",  "emoji": "🔴"}


def get_student_risk_data(query_fn, user_id):
    """
    query_fn: pass in your existing `query()` function from app.py
    Returns a dict with all metrics + risk score for one student.
    """
    att_row = query_fn(
        "SELECT ROUND(SUM(present)/NULLIF(COUNT(id),0)*100,1) as pct FROM attendance WHERE user_id=%s",
        (user_id,), one=True
    )
    attendance_pct = att_row['pct'] if att_row and att_row['pct']  is not None else 0.0

    marks_row = query_fn(
        "SELECT ROUND(AVG(marks),1) as avg FROM submissions WHERE user_id=%s AND marks IS NOT NULL",
        (user_id,), one=True
    )
    avg_marks_pct = marks_row['avg'] if marks_row and marks_row['avg'] is not None else 0.0

    total_row = query_fn("""
        SELECT COUNT(*) as c FROM assignments a
        JOIN class_enrollments ce ON ce.class_id=a.class_id
        WHERE ce.user_id=%s
    """, (user_id,), one=True)
    total_assignments = total_row['c'] if total_row else 0

    submitted_row = query_fn(
        "SELECT COUNT(*) as c FROM submissions WHERE user_id=%s", (user_id,), one=True
    )
    submitted = submitted_row['c'] if submitted_row else 0

    pending_ratio = 0
    if total_assignments > 0:
        pending_ratio = round(((total_assignments - submitted) / total_assignments) * 100, 1)

    score = calculate_risk_score(attendance_pct, avg_marks_pct, pending_ratio)
    level = risk_level(score)

    return {
        "user_id": user_id,
        "attendance_pct": attendance_pct,
        "avg_marks_pct": avg_marks_pct,
        "pending_ratio": pending_ratio,
        "total_assignments": total_assignments,
        "submitted": submitted,
        "risk_score": score,
        "risk_label": level["label"],
        "risk_color": level["color"],
        "risk_emoji": level["emoji"],
    }


# ── AI-Powered Personalized Feedback (Claude API) ───────────────────────────

def generate_ai_feedback(student_name, risk_data):
    """
    Calls Claude API to generate personalized feedback.
    Falls back to rule-based feedback if ANTHROPIC_API_KEY is not set
    or the API call fails for any reason.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")

    if not api_key:
        return _rule_based_feedback(student_name, risk_data)

    prompt = f"""You are an academic mentor AI. Analyze this student's data and give a SHORT (3-4 sentences),
encouraging, actionable piece of feedback plus ONE concrete career growth tip.

Student: {student_name}
Attendance: {risk_data['attendance_pct']}%
Average Marks: {risk_data['avg_marks_pct']}%
Pending Assignments: {risk_data['pending_ratio']}% not submitted
Risk Level: {risk_data['risk_label']}

Keep it warm, specific, and motivating. Do not repeat the raw numbers back verbatim — interpret them."""

    try:
        body = json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}]
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
            return "".join(text_blocks).strip() or _rule_based_feedback(student_name, risk_data)
    except Exception:
        return _rule_based_feedback(student_name, risk_data)


def _rule_based_feedback(student_name, risk_data):
    """Fallback feedback generator — no API needed, always works."""
    att = risk_data['attendance_pct']
    marks = risk_data['avg_marks_pct']
    pending = risk_data['pending_ratio']
    level = risk_data['risk_label']

    parts = []

    if level == "Low Risk":
        parts.append(f"{student_name} is performing well overall with solid attendance ({att}%) and good marks ({marks}%).")
        parts.append("Keep up the consistency — consider taking on a mentorship role for peers or exploring advanced projects to build a stronger portfolio.")
    elif level == "Medium Risk":
        parts.append(f"{student_name} shows moderate performance. ")
        if att < 75:
            parts.append(f"Attendance ({att}%) needs attention — try to attend sessions more regularly. ")
        if marks < 60:
            parts.append(f"Marks ({marks}%) could improve with focused revision on weaker topics. ")
        if pending > 20:
            parts.append(f"There are pending assignments ({pending}% not submitted) — clearing the backlog will help. ")
        parts.append("A short check-in with the mentor this week is recommended.")
    else:
        parts.append(f"{student_name} needs immediate support. ")
        if att < 60:
            parts.append(f"Attendance is critically low ({att}%). ")
        if marks < 50:
            parts.append(f"Marks are below passing threshold ({marks}%). ")
        if pending > 40:
            parts.append(f"A large number of assignments are pending ({pending}%). ")
        parts.append("Recommend an urgent one-on-one with the mentor and a personalized recovery plan to get back on track. Early intervention now can prevent falling further behind.")

    return "".join(parts)


def career_suggestion(risk_data, subject_strengths=None):
    """
    Very simple career-path nudge based on performance band.
    subject_strengths: optional list of {class_name, avg_marks} to personalize further.
    """
    marks = risk_data['avg_marks_pct']
    if subject_strengths:
        best = max(subject_strengths, key=lambda s: s.get('avg_marks') or 0, default=None)
        if best and best.get('avg_marks', 0) >= 70:
            return f"Strong performance in {best['class_name']} ({best['avg_marks']}%) — consider exploring advanced or specialized tracks in this area."

    if marks >= 80:
        return "Excellent overall performance — ready for advanced certifications, open-source contributions, or internship applications."
    elif marks >= 60:
        return "Good foundation — focus on building 1-2 portfolio projects to strengthen your profile for placements."
    elif marks >= 40:
        return "Focus on core fundamentals first. Regular practice and doubt-clearing sessions will build the foundation needed for placements."
    else:
        return "Prioritize attendance and assignment completion first — these are the foundation for everything else. Reach out to your mentor for a personalized study plan."
if __name__ == '__main__':
    pass