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


# ── AI-Powered Personalized Feedback (Gemini API via ai_service) ────────────

def generate_ai_feedback(student_name, risk_data, subject_strengths=None, extra_activities=None, exam_scores=None):
    """
    Generates AI personalized feedback using Gemini.
    """
    try:
        import ai_service
        feedback_data = ai_service.generate_student_comprehensive_feedback(
            student_name=student_name,
            risk_data=risk_data,
            subject_strengths=subject_strengths,
            extra_activities=extra_activities,
            exam_scores=exam_scores
        )
        if isinstance(feedback_data, dict) and feedback_data.get("feedback"):
            return feedback_data.get("feedback")
        elif isinstance(feedback_data, str) and feedback_data.strip():
            return feedback_data.strip()
    except Exception as e:
        pass

    return _rule_based_feedback(student_name, risk_data)


def _rule_based_feedback(student_name, risk_data):
    """Fallback feedback generator — works without network/API."""
    att = risk_data.get('attendance_pct', 0)
    marks = risk_data.get('avg_marks_pct', 0)
    pending = risk_data.get('pending_ratio', 0)
    level = risk_data.get('risk_label', 'Medium Risk')

    parts = []
    if level == "Low Risk":
        parts.append(f"{student_name} is performing consistently well with solid attendance ({att}%) and strong marks ({marks}%). ")
        parts.append("Keep up the momentum and consider taking on advanced portfolio projects to stand out for top career opportunities.")
    elif level == "Medium Risk":
        parts.append(f"{student_name} shows steady performance. ")
        if att < 75:
            parts.append(f"Attendance ({att}%) needs attention — attending sessions regularly will improve concept retention. ")
        if marks < 60:
            parts.append(f"Marks ({marks}%) could improve with focused practice on difficult concepts. ")
        if pending > 20:
            parts.append(f"Clearing pending assignments ({pending}% not submitted) will immediately boost your standing. ")
        parts.append("Scheduling a short 1-on-1 with your mentor is recommended this week.")
    else:
        parts.append(f"{student_name} needs urgent academic support. ")
        if att < 60:
            parts.append(f"Attendance is critically low ({att}%). ")
        if marks < 50:
            parts.append(f"Marks are below passing threshold ({marks}%). ")
        if pending > 40:
            parts.append(f"A significant number of assignments are pending ({pending}%). ")
        parts.append("Immediate intervention with your mentor is strongly advised to structure a fast-track recovery plan.")

    return "".join(parts)


def career_suggestion(risk_data, subject_strengths=None, student_name=""):
    """
    Generates intelligent career path advice.
    """
    try:
        import ai_service
        feedback_data = ai_service.generate_student_comprehensive_feedback(
            student_name=student_name or "Trainee",
            risk_data=risk_data,
            subject_strengths=subject_strengths
        )
        if isinstance(feedback_data, dict) and feedback_data.get("career_suggestion"):
            return feedback_data.get("career_suggestion")
    except Exception:
        pass

    marks = risk_data.get('avg_marks_pct', 0)
    if subject_strengths:
        best = max(subject_strengths, key=lambda s: s.get('avg_marks') or 0, default=None)
        if best and (best.get('avg_marks') or 0) >= 70:
            return f"Demonstrating strong talent in {best['class_name']} ({best['avg_marks']}%) — consider building specialized capstone projects and certifications in this domain."

    if marks >= 80:
        return "Outstanding academic consistency — well positioned for competitive internships, advanced open-source contributions, and technical leadership roles."
    elif marks >= 60:
        return "Solid foundational competence — focus on building 1-2 end-to-end portfolio projects and mock technical interviews to boost placement readiness."
    elif marks >= 40:
        return "Focus on reinforcing core domain fundamentals and solving practical problem sets. Regular mentor reviews will rapidly accelerate progress."
    else:
        return "Prioritize attendance recovery and clearing pending assignments first. Consistent fundamentals form the bedrock for all career opportunities."

if __name__ == '__main__':
    pass