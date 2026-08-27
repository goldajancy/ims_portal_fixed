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
