import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Preferred model list in order of priority
MODEL_CANDIDATES = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-pro-latest"
]

def _get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.error(f"Failed to initialize google.genai Client: {e}")
        return None

def _call_gemini(prompt: str, system_instruction: str = "") -> str:
    """Helper to call Gemini API with fallback across supported models."""
    client = _get_gemini_client()
    if not client:
        return ""

    full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt

    for model_name in MODEL_CANDIDATES:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=full_prompt
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            logger.warning(f"Gemini call with model {model_name} failed: {e}")
            continue

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# 1. ASSIGNMENTS: Answer Generation & Submission Evaluation
# ─────────────────────────────────────────────────────────────────────────────

def generate_assignment_solution(title: str, description: str = "", class_name: str = "") -> dict:
    """
    Generates a structured model answer, solution guide, concepts, and steps for an assignment.
    """
    prompt = f"""You are an expert academic tutor and technical instructor.
Generate a comprehensive, educational, and structured Solution Guide & Model Answer for the following assignment:

Course / Class: {class_name or 'General Course'}
Assignment Title: {title}
Assignment Description: {description or 'No specific description provided.'}

Please structure your response with:
1. **Overview & Core Objectives**: Key concepts to understand.
2. **Step-by-Step Approach / Solution Guide**: Clear breakdown of how to solve the problem.
3. **Model Solution / Code or Outline**: High-quality solution with comments or key points.
4. **Best Practices & Common Pitfalls**: What to avoid and how to ensure top quality.

Keep the formatting clean and readable using standard markdown."""

    res = _call_gemini(prompt, system_instruction="You are an expert academic mentor helping students learn.")
    if not res:
        res = (
            f"### Solution Guide for: {title}\n\n"
            f"**1. Core Objectives:** Review the fundamentals covered in {class_name or 'the course'}.\n"
            f"**2. Step-by-Step Approach:**\n"
            f"- Understand the problem requirements: {description or title}\n"
            f"- Plan the structure and modules needed.\n"
            f"- Implement the core logic and test with sample inputs.\n"
            f"**3. Best Practices:** Ensure clear documentation, modular structure, and edge-case handling."
        )
    return {"title": title, "solution_guide": res}


def evaluate_assignment_submission(title: str, description: str, content: str, max_marks: float = 100.0, student_name: str = "") -> dict:
    """
    Evaluates a trainee's assignment submission, suggests marks (0-max_marks), and provides constructive feedback.
    """
    prompt = f"""You are a professional academic grader and mentor.
Evaluate this student's assignment submission accurately and constructively.

Assignment Title: {title}
Assignment Prompt: {description or 'Standard assignment requirements.'}
Maximum Marks: {max_marks}
Student Name: {student_name or 'Student'}

Student Submission Content / Notes:
\"\"\"
{content or '(Student provided an attachment or link without text notes)'}
\"\"\"

Output your evaluation strictly in the following JSON format without any backticks or markdown wrap:
{{
  "suggested_marks": <number between 0 and {max_marks}>,
  "feedback": "<2-4 sentences of constructive, encouraging feedback highlighting strengths and 1 specific improvement tip>",
  "strengths": "<short bullet-point or sentence on what was done well>",
  "improvements": "<short suggestion for further learning>"
}}"""

    res = _call_gemini(prompt)
    try:
        clean_res = res.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res[7:]
        if clean_res.startswith("```"):
            clean_res = clean_res[3:]
        if clean_res.endswith("```"):
            clean_res = clean_res[:-3]
        data = json.loads(clean_res.strip())
        marks = min(float(max_marks), max(0.0, float(data.get("suggested_marks", round(max_marks * 0.85, 1)))))
        return {
            "suggested_marks": marks,
            "feedback": data.get("feedback", "Good effort on the submission. Review code structure and edge cases for further refinement."),
            "strengths": data.get("strengths", "Clear effort and solution logic."),
            "improvements": data.get("improvements", "Continue practicing modular coding.")
        }
    except Exception as e:
        logger.warning(f"Error parsing Gemini grading JSON: {e}, raw response: {res}")
        # Rule-based fallback
        base_marks = round(max_marks * 0.85, 1) if content and len(content) > 30 else round(max_marks * 0.70, 1)
        return {
            "suggested_marks": base_marks,
            "feedback": f"Good submission for '{title}'. The solution demonstrates understanding of core requirements. Keep refining detail and documentation.",
            "strengths": "Addressed the primary requirements.",
            "improvements": "Focus on optimizing logic and thorough testing."
        }


# ─────────────────────────────────────────────────────────────────────────────
# 2. TASKS: Solution Guide & Evaluation
# ─────────────────────────────────────────────────────────────────────────────

def generate_task_solution(title: str, description: str = "", class_name: str = "") -> dict:
    """
    Generates step-by-step task execution plan and solution template for trainees.
    """
    prompt = f"""You are a practical technical instructor.
Generate a concise, actionable Task Solution Guide & Action Plan for the following task:

Task: {title}
Class: {class_name or 'General Course'}
Details: {description or 'Perform the task according to specifications.'}

Provide:
1. **Task Goal & Definition of Done**
2. **Action Steps (Checklist format)**
3. **Template / Sample Implementation**
4. **Verification Checklist (How to verify it works)**"""

    res = _call_gemini(prompt, system_instruction="You are an expert mentor helping trainees complete practical tasks efficiently.")
    if not res:
        res = (
            f"### Task Guide: {title}\n\n"
            f"**Goal:** Complete '{title}' successfully.\n\n"
            f"**Steps to Execute:**\n"
            f"1. Review task requirements: {description or title}\n"
            f"2. Prepare necessary files and environment.\n"
            f"3. Implement and test your work step by step.\n"
            f"4. Document your completed work and submit."
        )
    return {"title": title, "solution_guide": res}


def evaluate_task_submission(title: str, description: str, content: str, student_name: str = "") -> dict:
    """
    Evaluates a task submission and generates feedback and suggested marks (0-100).
    """
    prompt = f"""You are an instructor evaluating a trainee's task completion notes.

Task Title: {title}
Task Description: {description or 'Standard practical task.'}
Student: {student_name or 'Student'}

Completion Notes:
\"\"\"
{content or '(Student submitted file attachment)'}
\"\"\"

Output strictly as JSON:
{{
  "suggested_marks": <number between 0 and 100>,
  "feedback": "<2-3 sentences of positive and actionable feedback>"
}}"""

    res = _call_gemini(prompt)
    try:
        clean_res = res.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res[7:]
        if clean_res.startswith("```"):
            clean_res = clean_res[3:]
        if clean_res.endswith("```"):
            clean_res = clean_res[:-3]
        data = json.loads(clean_res.strip())
        marks = min(100.0, max(0.0, float(data.get("suggested_marks", 85))))
        return {
            "suggested_marks": marks,
            "feedback": data.get("feedback", "Task completed satisfactorily. Good work following the instructions.")
        }
    except Exception:
        return {
            "suggested_marks": 85.0 if content else 80.0,
            "feedback": f"Task '{title}' has been reviewed. Good progress shown. Continue to maintain clean code and documentation."
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. EXAMS & QUESTION BANK: AI Answers & Score Feedback
# ─────────────────────────────────────────────────────────────────────────────

def generate_question_answer(question: str, qtype: str = "mcq", options: str = "") -> dict:
    """
    Generates correct answer, explanation, and pedagogical notes for questions in the question bank.
    """
    prompt = f"""You are an academic exam expert.
Provide the correct answer and a clear explanation for this question.

Question Type: {qtype.upper()}
Question: {question}
Options (if MCQ): {options or 'None'}

Output strictly as JSON format:
{{
  "correct_answer": "<the correct option or direct answer text>",
  "explanation": "<step-by-step reasoning explaining why this answer is correct>",
  "key_takeaway": "<1 sentence takeaway for students to remember>"
}}"""

    res = _call_gemini(prompt)
    try:
        clean_res = res.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res[7:]
        if clean_res.startswith("```"):
            clean_res = clean_res[3:]
        if clean_res.endswith("```"):
            clean_res = clean_res[:-3]
        data = json.loads(clean_res.strip())
        return {
            "correct_answer": data.get("correct_answer", ""),
            "explanation": data.get("explanation", "Reasoning generated based on standard subject concepts."),
            "key_takeaway": data.get("key_takeaway", "")
        }
    except Exception:
        return {
            "correct_answer": "See subject reference",
            "explanation": f"Review concepts related to '{question}'.",
            "key_takeaway": "Focus on core principles."
        }


def generate_exam_feedback(exam_title: str, max_marks: float, student_marks: float, class_name: str = "", student_name: str = "") -> dict:
    """
    Generates personalized feedback, strengths, weak areas, and a study plan for an exam result.
    """
    pct = round((student_marks / max_marks * 100), 1) if max_marks > 0 else 0.0

    prompt = f"""You are a supportive academic advisor and subject mentor.
Analyze the student's exam performance and generate personalized feedback and a 3-step revision plan.

Student: {student_name or 'Trainee'}
Class: {class_name or 'General Course'}
Exam: {exam_title}
Score: {student_marks} / {max_marks} ({pct}%)

Output strictly as JSON:
{{
  "performance_summary": "<short 2-sentence summary of performance level>",
  "strengths": "<1-2 bullet points or sentence on positive indicators>",
  "areas_to_improve": "<1-2 bullet points or sentence on key concepts to revisit>",
  "study_plan": [
    "<Step 1: Immediate concept revision>",
    "<Step 2: Practical problem solving or mock test>",
    "<Step 3: Mentor check-in or doubt clearing>"
  ]
}}"""

    res = _call_gemini(prompt)
    try:
        clean_res = res.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res[7:]
        if clean_res.startswith("```"):
            clean_res = clean_res[3:]
        if clean_res.endswith("```"):
            clean_res = clean_res[:-3]
        data = json.loads(clean_res.strip())
        return data
    except Exception:
        status = "Strong" if pct >= 75 else ("Satisfactory" if pct >= 50 else "Needs Improvement")
        return {
            "performance_summary": f"Scored {pct}% on {exam_title}. Performance band: {status}.",
            "strengths": "Solid engagement with course material.",
            "areas_to_improve": "Focus on reviewing questions where points were lost.",
            "study_plan": [
                "Review the exam answer key and note recurring weak spots.",
                "Solve 3-5 practice problems on the challenging topics.",
                "Schedule a short discussion with your mentor to clarify remaining doubts."
            ]
        }


def generate_practice_questions(topic: str, count: int = 3, qtype: str = "mcq") -> list:
    """
    Generates new practice questions for mentors to quickly populate question bank or exams.
    """
    prompt = f"""You are an instructor creating exam questions.
Generate {count} high-quality {qtype.upper()} questions about '{topic}'.

Format your output strictly as a JSON array of objects:
[
  {{
    "question": "<Question text>",
    "options": "<Option A, Option B, Option C, Option D if MCQ else empty>",
    "answer": "<Correct answer>",
    "qtype": "{qtype}"
  }}
]"""

    res = _call_gemini(prompt)
    try:
        clean_res = res.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res[7:]
        if clean_res.startswith("```"):
            clean_res = clean_res[3:]
        if clean_res.endswith("```"):
            clean_res = clean_res[:-3]
        data = json.loads(clean_res.strip())
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.warning(f"Error generating practice questions: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 4. COMPREHENSIVE AI FEEDBACK (TRAINEE, MENTOR, ADMIN)
# ─────────────────────────────────────────────────────────────────────────────

def generate_student_comprehensive_feedback(
    student_name: str,
    risk_data: dict,
    subject_strengths: list = None,
    extra_activities: list = None,
    exam_scores: list = None
) -> dict:
    """
    Generates rich, personalized AI evaluation, feedback, career pathway advice, and 
    targeted action steps using Gemini.
    """
    subjects_str = ", ".join([f"{s.get('class_name', 'Subject')}: {s.get('avg_marks', 0)}%" for s in (subject_strengths or [])]) or "No subject marks recorded yet"
    extras_str = ", ".join([f"{e.get('title', 'Activity')} ({e.get('category', 'General')})" for e in (extra_activities or [])]) or "No extracurricular recorded"
    exams_str = ", ".join([f"{ex.get('title', 'Exam')}: {ex.get('marks', 0)}/{ex.get('max_marks', 100)}" for ex in (exam_scores or [])]) or "No exams recorded"

    prompt = f"""You are a senior academic advisor and career mentor in an Integrated Management System.
Analyze the following complete student profile and generate a constructive, highly motivating, and personalized AI evaluation.

Student Name: {student_name}
Attendance: {risk_data.get('attendance_pct', 0)}%
Average Assignment Marks: {risk_data.get('avg_marks_pct', 0)}%
Pending Assignments Ratio: {risk_data.get('pending_ratio', 0)}% (Submitted: {risk_data.get('submitted', 0)} of {risk_data.get('total_assignments', 0)})
Risk Classification: {risk_data.get('risk_label', 'Unknown')}
Subject Scores: {subjects_str}
Exams Performance: {exams_str}
Extracurricular Activities: {extras_str}

Output STRICTLY a JSON object matching this schema:
{{
  "summary": "<1-2 sentence executive summary of student status>",
  "feedback": "<2-4 sentences of warm, encouraging, specific pedagogical feedback>",
  "career_suggestion": "<1-2 sentences of concrete career & technical path advice based on their best subjects and talents>",
  "strengths": ["<strength 1>", "<strength 2>"],
  "improvements": ["<actionable improvement area 1>", "<actionable improvement area 2>"],
  "study_plan": [
    "<Step 1: Immediate focus for this week>",
    "<Step 2: Practical skill reinforcement>",
    "<Step 3: Milestone goal for the month>"
  ]
}}"""

    res = _call_gemini(prompt, system_instruction="You are an expert student advisor giving compassionate, data-driven academic advice.")
    try:
        clean_res = res.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res[7:]
        if clean_res.startswith("```"):
            clean_res = clean_res[3:]
        if clean_res.endswith("```"):
            clean_res = clean_res[:-3]
        data = json.loads(clean_res.strip())
        if isinstance(data, dict) and "feedback" in data:
            return data
    except Exception as e:
        logger.warning(f"Failed to parse student feedback JSON from Gemini: {e}")

    # Fallback structure
    att = float(risk_data.get('attendance_pct', 0))
    avg_m = float(risk_data.get('avg_marks_pct', 0))
    return {
        "summary": f"{student_name} holds {att}% attendance with an average score of {avg_m}%.",
        "feedback": f"{student_name} is showing steady progress across assignments. Focus on consistent attendance and clearing pending submissions to maintain strong academic momentum.",
        "career_suggestion": f"Based on academic performance, developing practical portfolio projects and strengthening foundational concepts will open competitive career opportunities.",
        "strengths": [
            f"Active participation in assignments ({risk_data.get('submitted', 0)} submitted)",
            "Consistent subject engagement"
        ],
        "improvements": [
            "Maintain attendance above 85% for optimal retention",
            "Submit upcoming tasks before deadlines"
        ],
        "study_plan": [
            "Review challenging class modules with your mentor",
            "Complete all pending assignment submissions",
            "Take mock quizzes to test core concepts"
        ]
    }


def generate_mentor_class_insights(
    mentor_name: str,
    class_names: list,
    risk_list: list
) -> dict:
    """
    Generates class-wide diagnostic insights, at-risk triage, and actionable mentoring tips for a Mentor.
    """
    total_students = len(risk_list)
    high_risk = sum(1 for r in risk_list if r.get('risk_label') == 'High Risk')
    med_risk = sum(1 for r in risk_list if r.get('risk_label') == 'Medium Risk')
    low_risk = sum(1 for r in risk_list if r.get('risk_label') == 'Low Risk')
    avg_att = round(sum(float(r.get('attendance_pct', 0)) for r in risk_list) / max(1, total_students), 1) if risk_list else 0
    avg_marks = round(sum(float(r.get('avg_marks_pct', 0)) for r in risk_list) / max(1, total_students), 1) if risk_list else 0

    at_risk_names = [r.get('name') for r in risk_list if r.get('risk_label') == 'High Risk'][:4]

    prompt = f"""You are an educational analytics consultant assisting a course mentor.
Mentor: {mentor_name}
Classes: {', '.join(class_names) if class_names else 'General Batches'}
Total Enrolled Trainees: {total_students}
High Risk Trainees: {high_risk} (Notable: {', '.join(at_risk_names) or 'None'})
Medium Risk Trainees: {med_risk}
Low Risk / High Performers: {low_risk}
Batch Average Attendance: {avg_att}%
Batch Average Marks: {avg_marks}%

Generate actionable mentor insights in strictly JSON format:
{{
  "overview": "<2 sentences summarizing class health and trends>",
  "priority_actions": [
    "<Action 1: specific guidance for high-risk students>",
    "<Action 2: teaching or assignment recommendation>"
  ],
  "positive_highlights": "<1-2 sentences on what the batch is doing well>",
  "mentor_tip": "<1 pedagogical advice for next week's sessions>"
}}"""

    res = _call_gemini(prompt, system_instruction="You are an expert teaching mentor providing strategic class improvement guidance.")
    try:
        clean_res = res.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res[7:]
        if clean_res.startswith("```"):
            clean_res = clean_res[3:]
        if clean_res.endswith("```"):
            clean_res = clean_res[:-3]
        data = json.loads(clean_res.strip())
        if isinstance(data, dict) and "overview" in data:
            return data
    except Exception as e:
        logger.warning(f"Error parsing mentor insights JSON: {e}")

    return {
        "overview": f"Your batch of {total_students} trainees is maintaining an average attendance of {avg_att}% and marks average of {avg_marks}%. {high_risk} students require academic intervention.",
        "priority_actions": [
            f"Conduct 1-on-1 check-ins with high-risk trainees to address backlogs.",
            "Schedule an interactive doubt-clearing session on core topics before next assessments."
        ],
        "positive_highlights": f"{low_risk} trainees are performing consistently in the low-risk band.",
        "mentor_tip": "Provide bite-sized weekly task milestones to keep trainees engaged and submitting on time."
    }


def generate_admin_institutional_insights(
    stats: dict,
    risk_list: list,
    extra_summary: dict = None
) -> dict:
    """
    Generates strategic institutional AI insights for the Admin dashboard.
    """
    total_trainees = len(risk_list)
    high_risk = sum(1 for r in risk_list if r.get('risk_label') == 'High Risk')
    med_risk = sum(1 for r in risk_list if r.get('risk_label') == 'Medium Risk')
    low_risk = sum(1 for r in risk_list if r.get('risk_label') == 'Low Risk')
    
    prompt = f"""You are an executive institutional advisor for an academy management system.
Provide an executive AI analysis for administrators.

Platform Stats:
- Total Trainees: {total_trainees}
- Total Mentors: {stats.get('total_mentors', 0)}
- Active Classes: {stats.get('total_classes', 0)}
- Risk Distribution: High Risk: {high_risk}, Medium Risk: {med_risk}, Low Risk: {low_risk}
- Extracurricular Summary: {extra_summary or 'General activities registered'}

Output strictly JSON:
{{
  "executive_summary": "<2-3 sentences assessing overall institutional performance, retention health, and engagement>",
  "key_risks": [
    "<Risk point 1>",
    "<Risk point 2>"
  ],
  "growth_opportunities": [
    "<Opportunity 1>",
    "<Opportunity 2>"
  ],
  "strategic_recommendation": "<1 overarching administrative recommendation>"
}}"""

    res = _call_gemini(prompt, system_instruction="You are a senior academic director providing high-level operational intelligence.")
    try:
        clean_res = res.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res[7:]
        if clean_res.startswith("```"):
            clean_res = clean_res[3:]
        if clean_res.endswith("```"):
            clean_res = clean_res[:-3]
        data = json.loads(clean_res.strip())
        if isinstance(data, dict) and "executive_summary" in data:
            return data
    except Exception as e:
        logger.warning(f"Error parsing admin insights JSON: {e}")

    return {
        "executive_summary": f"Institution operates across {stats.get('total_classes', 0)} classes with {total_trainees} enrolled trainees. {low_risk} students are thriving, while {high_risk} require targeted academic retention programs.",
        "key_risks": [
            f"{high_risk} trainees currently flagged in high-risk zone requiring mentor follow-up",
            "Assignment completion lag observed in certain classes"
        ],
        "growth_opportunities": [
            "Expand cross-functional extracurricular competitions and workshops",
            "Incentivize early assignment completions and peer-assisted study sessions"
        ],
        "strategic_recommendation": "Coordinate with mentors of high-risk batches to implement structured recovery plans."
    }


def evaluate_extracurricular_activity_ai(
    title: str,
    category: str,
    level: str,
    achievement: str = "",
    description: str = "",
    student_name: str = "Trainee"
) -> str:
    """
    Evaluates student extracurricular achievement and generates authentic AI feedback for career portfolios.
    """
    prompt = f"""You are a student development and holistic career coach.
Generate a professional, encouraging 2-3 sentence AI evaluation and career impact review for this student's extracurricular activity:

Student: {student_name}
Activity Title: {title}
Category: {category}
Level: {level}
Achievement / Role: {achievement or 'Active Participant'}
Description / Details: {description or 'Participated actively'}

The feedback should recognize the effort, highlight transferable soft/hard skills demonstrated (e.g., leadership, teamwork, technical prowess, discipline), and explain how this enhances their professional placement profile."""

    res = _call_gemini(prompt, system_instruction="You are an encouraging student career and talent development mentor.")
    if not res:
        res = f"{student_name}'s participation in '{title}' under the {category} category ({level} level) demonstrates commendable initiative and commitment. This achievement showcases strong dedication and teamwork, enriching their holistic portfolio for future career placements."
    return res


# ─────────────────────────────────────────────────────────────────────────────
# 5. UNIVERSAL FLOATING AI CHATBOT
# ─────────────────────────────────────────────────────────────────────────────

def chat_with_ims_assistant(
    message: str,
    role: str,
    user_name: str,
    user_context: dict = None,
    history: list = None
) -> str:
    """
    Universal conversational AI assistant for all pages across Admin, Mentor, and Trainee roles.
    """
    context_str = ""
    if user_context:
        context_str = "\n".join([f"- {k}: {v}" for k, v in user_context.items()])

    history_str = ""
    if history:
        for turn in history[-6:]: # Keep last 6 turns for context
            u = turn.get('user', '')
            b = turn.get('bot', '')
            if u:
                history_str += f"User: {u}\n"
            if b:
                history_str += f"Assistant: {b}\n"

    system_instruction = f"""You are 'IMS AI Smart Assistant', an intelligent, warm, and highly capable pair-assistant embedded inside the Integrated Management System (IMS) portal.

User Information:
- Name: {user_name}
- Role: {role.upper()}
{'- Live User Context / Metrics:' + chr(10) + context_str if context_str else ''}

Your capabilities:
1. Academic Assistance: Explain complex technical concepts, answer questions, provide study tips, write code examples, and suggest problem-solving approaches.
2. Portal Navigation & Help: Guide the user on how to use IMS features based on their role:
   - Trainees: viewing assignments, submitting tasks, checking exam scores, attendance, extracurriculars, AI feedback.
   - Mentors: creating tasks/assignments, grading submissions, posting lectures, taking attendance, student AI risk reports.
   - Admins: managing users, classes, attendance links, system logs, announcements, institutional analytics.
3. Performance Guidance: Interpret their risk level, scores, and give tailored next steps.
4. Professional Tone: Be concise, clear, encouraging, and helpful. Use clean Markdown formatting (bullet points, bold text, code snippets when relevant). Keep answers direct without unnecessary filler."""

    full_prompt = ""
    if history_str:
        full_prompt += f"Conversation History:\n{history_str}\n"
    full_prompt += f"User ({user_name}): {message}"

    reply = _call_gemini(full_prompt, system_instruction=system_instruction)
    if not reply:
        reply = f"Hello {user_name}! I am your IMS AI Assistant. I am here to help you navigate your {role} dashboard, answer questions about your coursework, assignments, and provide personalized guidance. How can I help you today?"

    return reply

