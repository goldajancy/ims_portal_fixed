"""
notifications.py — Complete WhatsApp + Email Notification System
================================================================
Drop this file into your ims_app folder.

Your exact Meta template names:
  task_submitted          → mentor gets notified when trainee submits task
  assignment_submitted    → mentor gets notified when trainee submits assignment
  lecture_uploaded        → trainees notified when lecture added
  lms_security_alert      → trainee notified on new device login
  lms_weekly_digest       → Sunday summary of upcoming deadlines
  lms_deadline_reminder   → 2 days before + last day reminder
  lms_welcome_student     → when new student added to class
  lms_exam_result         → when exam results published
  lms_exam_timetable      → when exam scheduled
  lms_class_cancelled     → when class cancelled/rescheduled
  lms_announcements       → when announcement posted
  lms_assignment_graded   → when mentor grades assignment
  lms_task_assigned       → when mentor creates task

HOW TO USE:
  from notifications import notify

  # In mentor_add_task:
  notify.task_assigned(class_id, task_title, due_date)

  # In mentor_add_assignment:
  notify.assignment_assigned(class_id, assignment_title, due_date)

  # In mentor_add_lecture:
  notify.lecture_uploaded(class_id, lecture_title)

  # In mentor_grade:
  notify.assignment_graded(student_id, assignment_title, marks)

  # In trainee_submit_assignment:
  notify.assignment_submitted(assignment_id, student_name, assignment_title)

  # In trainee_submit_task:
  notify.task_submitted(task_id, student_name, task_title)

  # In admin_add_announcement / mentor_announcements POST:
  notify.announcement(target_role, title, content)

  # In admin_add_exam / mentor_add_exam:
  notify.exam_timetable(class_id, exam_title, exam_date)

  # When publishing exam results (add a publish route):
  notify.exam_results(class_id, exam_title)

  # In add_students_to_class / admin_add_class enrollment:
  notify.welcome_student(student_id, class_name)

  # In login route when new device detected:
  notify.security_alert(student_id, device_info)

  # Started automatically by scheduler — no manual call needed:
  notify.deadline_reminder()   # daily 8AM
  notify.weekly_digest()       # Sunday 9AM
"""

import os
import requests
import logging
from datetime import datetime
from flask_mail import Message

logger = logging.getLogger(__name__)

# ── These are read from your existing .env ────────────────────────────────────
def _get_wa_config():
    token    = os.getenv("WHATSAPP_TOKEN", "")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    version  = os.getenv("WHATSAPP_API_VERSION", "v21.0")
    url      = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    return token, phone_id, url


# ═══════════════════════════════════════════════════════════════════════════════
#  CORE SENDERS
# ═══════════════════════════════════════════════════════════════════════════════

def _send_wa_template(phone: str, template: str, params: list) -> bool:
    WA_TOKEN, WA_PHONE_ID, WA_URL = _get_wa_config()
    if not WA_TOKEN or not WA_PHONE_ID:
        logger.warning("WhatsApp credentials not set in .env")
        return False

    # Clean phone — strip non-digits, add 91 if 10 digits (India)
    digits = "".join(c for c in str(phone) if c.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) < 11:
        logger.warning(f"Invalid phone skipped: {phone}")
        return False

    payload = {
        "messaging_product": "whatsapp",
        "to": digits,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": "en"},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in params]
            }] if params else []
        }
    }

    try:
        resp = requests.post(
            WA_URL,
            headers={
                "Authorization": f"Bearer {WA_TOKEN}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=10
        )
        resp.raise_for_status()
        logger.info(f"WA sent | template={template} | to={digits}")
        return True
    except requests.exceptions.HTTPError as e:
        logger.error(f"WA error | template={template} | {e.response.status_code} | {e.response.text}")
    except Exception as e:
        logger.error(f"WA failed | template={template} | {e}")
    return False


def _send_email(mail, to_email: str, subject: str, body: str) -> bool:
    """Send plain text email using your existing Flask-Mail setup."""
    try:
        msg = Message(
            subject=subject,
            recipients=[to_email],
            body=body,
            sender=os.getenv("MAIL_USERNAME", "")
        )
        mail.send(msg)
        logger.info(f"Email sent | to={to_email} | subject={subject}")
        return True
    except Exception as e:
        logger.error(f"Email failed | to={to_email} | {e}")
        return False


def _already_notified(query_fn, event_type: str, phone: str, ref_id: str) -> bool:
    """Prevent duplicate notifications using notification_log table."""
    try:
        row = query_fn(
            "SELECT id FROM notification_log WHERE event_type=%s AND recipient_phone=%s AND ref_id=%s",
            (event_type, phone, str(ref_id)), one=True
        )
        return row is not None
    except Exception:
        return False  # If table doesn't exist yet, don't block


def _log_notification(query_fn, event_type: str, phone: str, ref_id: str):
    """Log a sent notification."""
    try:
        query_fn(
            "INSERT INTO notification_log (event_type, recipient_phone, ref_id, sent_at) VALUES (%s,%s,%s,NOW())",
            (event_type, phone, str(ref_id)), commit=True
        )
    except Exception:
        pass  # Don't crash if table missing


# ═══════════════════════════════════════════════════════════════════════════════
#  NOTIFICATION CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class Notify:
    """
    Main notification class. Initialize once in app.py and reuse everywhere.

    Usage in app.py:
        from notifications import Notify
        notify = Notify(mail, query)
    """

    def __init__(self, mail, query_fn):
        self.mail  = mail
        self.query = query_fn

    def _get_user(self, user_id: int):
        return self.query(
            "SELECT id, name, email, phone, notify_whatsapp FROM users WHERE id=%s",
            (user_id,), one=True
        )

    def _get_class_students(self, class_id: int):
        return self.query("""
            SELECT u.id, u.name, u.email, u.phone, u.notify_whatsapp
            FROM users u
            JOIN class_enrollments ce ON ce.user_id = u.id
            WHERE ce.class_id = %s AND u.role = 'trainee' AND u.is_active = 1
        """, (class_id,))

    def _get_class_mentor(self, class_id: int):
        return self.query("""
            SELECT u.id, u.name, u.email, u.phone, u.notify_whatsapp
            FROM users u
            JOIN classes c ON c.mentor_id = u.id
            WHERE c.id = %s
        """, (class_id,), one=True)

    def _get_assignment_class(self, assignment_id: int):
        return self.query(
            "SELECT class_id FROM assignments WHERE id=%s",
            (assignment_id,), one=True
        )

    def _get_task_class(self, task_id: int):
        return self.query(
            "SELECT class_id FROM tasks WHERE id=%s",
            (task_id,), one=True
        )

    # ─── 1. Task Assigned → all trainees in class ──────────────────────────────
    def task_assigned(self, class_id: int, task_title: str, due_date=None):
        """
        Call in: mentor_add_task (after INSERT)
        Replace existing notify_whatsapp loop with:
            notify.task_assigned(class_id, title, due_date)
        """
        students = self._get_class_students(class_id)
        due = due_date.strftime("%d %b %Y") if hasattr(due_date, 'strftime') else str(due_date or "No due date")

        for s in students:
            # WhatsApp
            if s.get("phone") and s.get("notify_whatsapp", 1):
                _send_wa_template(s["phone"], "lms_task_assigned", [s["name"], task_title, due])

            # Email
            if s.get("email"):
                _send_email(
                    self.mail, s["email"],
                    f"New Task: {task_title}",
                    f"Hi {s['name']},\n\nA new task has been assigned to you.\n\nTask: {task_title}\nDue Date: {due}\n\nPlease log in to submit it.\n\nRegards,\nIMS Team"
                )

    # ─── 2. Assignment Assigned → all trainees in class ───────────────────────
    def assignment_assigned(self, class_id: int, assignment_title: str, due_date=None):
        """
        Call in: mentor_add_assignment and admin_add_assignment (after INSERT)
        Replace existing notify_whatsapp loop with:
            notify.assignment_assigned(class_id, title, due_date)
        """
        students = self._get_class_students(class_id)
        due = due_date.strftime("%d %b %Y") if hasattr(due_date, 'strftime') else str(due_date or "No due date")

        for s in students:
            if s.get("phone") and s.get("notify_whatsapp", 1):
                _send_wa_template(s["phone"], "lms_task_assigned", [s["name"], assignment_title, due])

            if s.get("email"):
                _send_email(
                    self.mail, s["email"],
                    f"New Assignment: {assignment_title}",
                    f"Hi {s['name']},\n\nA new assignment has been posted.\n\nAssignment: {assignment_title}\nDue Date: {due}\n\nPlease log in to view and submit.\n\nRegards,\nIMS Team"
                )

    # ─── 3. Lecture Uploaded → all trainees in class ──────────────────────────
    def lecture_uploaded(self, class_id: int, lecture_title: str):
        """
        Call in: mentor_add_lecture (after INSERT)
        Replace existing notify_whatsapp loop with:
            notify.lecture_uploaded(class_id, title)
        """
        students = self._get_class_students(class_id)

        for s in students:
            if s.get("phone") and s.get("notify_whatsapp", 1):
                _send_wa_template(s["phone"], "lecture_uploaded", [s["name"], lecture_title])

            if s.get("email"):
                _send_email(
                    self.mail, s["email"],
                    f"New Lecture Available: {lecture_title}",
                    f"Hi {s['name']},\n\nA new lecture has been uploaded.\n\nLecture: {lecture_title}\n\nLog in to watch it.\n\nRegards,\nIMS Team"
                )

    # ─── 4. Assignment Submitted → notify mentor ───────────────────────────────
    def assignment_submitted(self, assignment_id: int, student_name: str, assignment_title: str):
        """
        Call in: trainee_submit_assignment (after INSERT)
        Add after existing code:
            notify.assignment_submitted(aid, session['name'], assignment_title)

        Note: fetch assignment_title before calling:
            asgn = query("SELECT title, class_id FROM assignments WHERE id=%s", (aid,), one=True)
            notify.assignment_submitted(aid, session['name'], asgn['title'])
        """
        asgn = self.query("SELECT class_id FROM assignments WHERE id=%s", (assignment_id,), one=True)
        if not asgn:
            return
        mentor = self._get_class_mentor(asgn["class_id"])
        if not mentor:
            return

        if mentor.get("phone") and mentor.get("notify_whatsapp", 1):
            _send_wa_template(mentor["phone"], "assignment_submitted", [mentor["name"], student_name, assignment_title])

        if mentor.get("email"):
            _send_email(
                self.mail, mentor["email"],
                f"Assignment Submitted: {assignment_title}",
                f"Hi {mentor['name']},\n\n{student_name} has submitted the assignment.\n\nAssignment: {assignment_title}\n\nLog in to review and grade it.\n\nRegards,\nIMS Team"
            )

    # ─── 5. Task Submitted → notify mentor ────────────────────────────────────
    def task_submitted(self, task_id: int, student_name: str, task_title: str):
        """
        Call in: trainee_submit_task (after INSERT)
        Add after existing code:
            task = query("SELECT title, class_id FROM tasks WHERE id=%s", (tid_,), one=True)
            notify.task_submitted(tid_, session['name'], task['title'])
        """
        task = self.query("SELECT class_id FROM tasks WHERE id=%s", (task_id,), one=True)
        if not task:
            return
        mentor = self._get_class_mentor(task["class_id"])
        if not mentor:
            return

        if mentor.get("phone") and mentor.get("notify_whatsapp", 1):
            _send_wa_template(mentor["phone"], "task_submitted", [mentor["name"], student_name, task_title])

        if mentor.get("email"):
            _send_email(
                self.mail, mentor["email"],
                f"Task Submitted: {task_title}",
                f"Hi {mentor['name']},\n\n{student_name} has submitted a task.\n\nTask: {task_title}\n\nLog in to review it.\n\nRegards,\nIMS Team"
            )

    # ─── 6. Assignment Graded → notify student ────────────────────────────────
    def assignment_graded(self, student_id: int, assignment_title: str, marks):
        """
        Call in: mentor_grade (after UPDATE)
        Replace existing notify_whatsapp with:
            notify.assignment_graded(sub['user_id'], sub['title'], marks)
        """
        student = self._get_user(student_id)
        if not student:
            return

        if student.get("phone") and student.get("notify_whatsapp", 1):
            _send_wa_template(student["phone"], "lms_assignment_graded", [student["name"], assignment_title, str(marks)])

        if student.get("email"):
            _send_email(
                self.mail, student["email"],
                f"Assignment Graded: {assignment_title}",
                f"Hi {student['name']},\n\nYour assignment has been graded.\n\nAssignment: {assignment_title}\nMarks: {marks}\n\nLog in to see your feedback.\n\nRegards,\nIMS Team"
            )

    # ─── 7. Announcement Posted → trainees / mentors / all ───────────────────
    def announcement(self, target_role: str, title: str, content: str, sub_type: str = None):
        """
        Call in: admin_add_announcement and mentor_announcements POST
        Add after INSERT:
            notify.announcement(target, title, content)

        For class cancelled, pass sub_type='cancelled':
            notify.announcement('trainee', title, content, sub_type='cancelled')
        """
        if target_role in ("trainee", "all"):
            students = self.query(
                "SELECT id, name, email, phone, notify_whatsapp FROM users WHERE role='trainee' AND is_active=1"
            )
            template = "lms_class_cancelled" if sub_type in ("cancelled", "rescheduled") else "lms_announcements"
            for s in students:
                if s.get("phone") and s.get("notify_whatsapp", 1):
                    _send_wa_template(s["phone"], template, [s["name"], title, content[:200]])
                if s.get("email"):
                    _send_email(
                        self.mail, s["email"],
                        f"Announcement: {title}",
                        f"Hi {s['name']},\n\n{title}\n\n{content}\n\nRegards,\nIMS Team"
                    )

        if target_role in ("mentor", "all"):
            mentors = self.query(
                "SELECT id, name, email, phone, notify_whatsapp FROM users WHERE role='mentor' AND is_active=1"
            )
            for m in mentors:
                if m.get("phone") and m.get("notify_whatsapp", 1):
                    _send_wa_template(m["phone"], "lms_announcements", [m["name"], title, content[:200]])
                if m.get("email"):
                    _send_email(
                        self.mail, m["email"],
                        f"Announcement: {title}",
                        f"Hi {m['name']},\n\n{title}\n\n{content}\n\nRegards,\nIMS Team"
                    )

    # ─── 8. Exam Timetable → all trainees in class ────────────────────────────
    def exam_timetable(self, class_id: int, exam_title: str, exam_date=None):
        """
        Call in: admin_add_exam and mentor_add_exam (after INSERT)
        Add after INSERT:
            notify.exam_timetable(class_id, title, exam_date)
        """
        students = self._get_class_students(class_id)
        date_str = exam_date.strftime("%d %b %Y") if hasattr(exam_date, 'strftime') else str(exam_date or "TBA")

        for s in students:
            if s.get("phone") and s.get("notify_whatsapp", 1):
                _send_wa_template(s["phone"], "lms_exam_timetable", [s["name"], exam_title, date_str])
            if s.get("email"):
                _send_email(
                    self.mail, s["email"],
                    f"Exam Scheduled: {exam_title}",
                    f"Hi {s['name']},\n\nAn exam has been scheduled.\n\nExam: {exam_title}\nDate: {date_str}\n\nPlease prepare accordingly.\n\nRegards,\nIMS Team"
                )

    # ─── 9. Exam Results Published → all trainees in class ───────────────────
    def exam_results(self, class_id: int, exam_title: str):
        """
        Call in: when admin publishes exam results
        Add a publish button/route in your admin_exams page, then:
            notify.exam_results(class_id, exam_title)
        """
        students = self._get_class_students(class_id)

        for s in students:
            if s.get("phone") and s.get("notify_whatsapp", 1):
                _send_wa_template(s["phone"], "lms_exam_result", [s["name"], exam_title])
            if s.get("email"):
                _send_email(
                    self.mail, s["email"],
                    f"Exam Results Published: {exam_title}",
                    f"Hi {s['name']},\n\nThe results for {exam_title} have been published.\n\nLog in to check your score.\n\nRegards,\nIMS Team"
                )

    # ─── 10. Welcome Student → new student added to class ─────────────────────
    def welcome_student(self, student_id: int, class_name: str):
        """
        Call in: add_students_to_class and add_student_to_class (after INSERT)
        Add:
            notify.welcome_student(sid, class_name)

        Fetch class_name before:
            cls = query("SELECT name FROM classes WHERE id=%s", (class_id,), one=True)
            notify.welcome_student(student_id, cls['name'])
        """
        student = self._get_user(student_id)
        if not student:
            return

        if student.get("phone") and student.get("notify_whatsapp", 1):
            _send_wa_template(student["phone"], "lms_welcome_student", [student["name"], class_name])

        if student.get("email"):
            _send_email(
                self.mail, student["email"],
                f"Welcome to {class_name}!",
                f"Hi {student['name']},\n\nYou have been enrolled in {class_name}.\n\nLog in to access your coursework, assignments, and connect with your mentor.\n\nRegards,\nIMS Team"
            )

    # ─── 11. Security Alert → student logs in from new device ─────────────────
    def security_alert(self, student_id: int, device_info: str):
        """
        Call in: login route when new device fingerprint detected.
        notify.security_alert(user['id'], request.headers.get('User-Agent','Unknown')[:80])
        """
        student = self._get_user(student_id)
        if not student:
            return

        timestamp = datetime.now().strftime("%d %b %Y %I:%M %p")

        if student.get("phone") and student.get("notify_whatsapp", 1):
            _send_wa_template(student["phone"], "lms_security_alert", [student["name"], device_info, timestamp])

        if student.get("email"):
            _send_email(
                self.mail, student["email"],
                "Security Alert: New Device Login",
                f"Hi {student['name']},\n\nA login was detected from a new device.\n\nDevice: {device_info}\nTime: {timestamp}\n\nIf this was not you, change your password immediately.\n\nRegards,\nIMS Team"
            )

    # ─── 12. Deadline Reminder → called by scheduler daily ───────────────────
    def deadline_reminder(self):
        """
        Called automatically by scheduler every day at 8AM.
        Do NOT call this manually from views.
        """
        for days_ahead in [2, 0]:
            label = "in 2 days" if days_ahead == 2 else "TODAY"
            pending = self.query("""
                SELECT
                    t.id AS task_id, t.title, t.due_date, t.class_id,
                    'task' AS item_type,
                    s.id AS student_id, s.name AS student_name, s.email, s.phone
                FROM tasks t
                JOIN class_enrollments ce ON ce.class_id = t.class_id
                JOIN users s ON s.id = ce.user_id
                LEFT JOIN task_submissions ts ON ts.task_id = t.id AND ts.user_id = s.id
                WHERE DATE(t.due_date) = DATE(NOW() + INTERVAL %s DAY)
                  AND ts.id IS NULL
                  AND s.phone IS NOT NULL AND s.is_active = 1

                UNION ALL

                SELECT
                    a.id AS task_id, a.title, a.due_date, a.class_id,
                    'assignment' AS item_type,
                    s.id AS student_id, s.name AS student_name, s.email, s.phone
                FROM assignments a
                JOIN class_enrollments ce ON ce.class_id = a.class_id
                JOIN users s ON s.id = ce.user_id
                LEFT JOIN submissions sub ON sub.assignment_id = a.id AND sub.user_id = s.id
                WHERE DATE(a.due_date) = DATE(NOW() + INTERVAL %s DAY)
                  AND sub.id IS NULL
                  AND s.phone IS NOT NULL AND s.is_active = 1
            """, (days_ahead, days_ahead))

            for row in pending:
                due_str = row["due_date"].strftime("%d %b %Y") if row.get("due_date") else "soon"
                ref = f"reminder:{row['task_id']}:{row['item_type']}:{row['student_id']}:{days_ahead}:{datetime.today().date()}"

                if _already_notified(self.query, "deadline_reminder", row["phone"], ref):
                    continue

                ok = _send_wa_template(row["phone"], "lms_deadline_reminder", [row["student_name"], row["title"], label, due_str])
                if ok:
                    _log_notification(self.query, "deadline_reminder", row["phone"], ref)

                if row.get("email"):
                    _send_email(
                        self.mail, row["email"],
                        f"Deadline Reminder: {row['title']} due {label}",
                        f"Hi {row['student_name']},\n\nThis is a reminder that your {row['item_type']} is due {label}.\n\n{row['item_type'].capitalize()}: {row['title']}\nDue: {due_str}\n\nPlease submit before the deadline.\n\nRegards,\nIMS Team"
                    )

    # ─── 13. Weekly Digest → called by scheduler every Sunday ─────────────────
    def weekly_digest(self):
        """
        Called automatically by scheduler every Sunday at 9AM.
        Do NOT call this manually from views.
        """
        students_with_deadlines = self.query("""
            SELECT
                s.id AS student_id, s.name AS student_name, s.email, s.phone,
                COUNT(t.id) AS deadline_count,
                GROUP_CONCAT(
                    CONCAT(t.title, ' (due: ', DATE_FORMAT(t.due_date,'%d %b'), ')')
                    ORDER BY t.due_date SEPARATOR ', '
                ) AS deadlines
            FROM users s
            JOIN class_enrollments ce ON ce.user_id = s.id
            JOIN tasks t ON t.class_id = ce.class_id
            LEFT JOIN task_submissions ts ON ts.task_id = t.id AND ts.user_id = s.id
            WHERE t.due_date BETWEEN NOW() AND DATE_ADD(NOW(), INTERVAL 7 DAY)
              AND ts.id IS NULL AND s.is_active = 1 AND s.phone IS NOT NULL
            GROUP BY s.id

            UNION ALL

            SELECT
                s.id, s.name, s.email, s.phone,
                COUNT(a.id),
                GROUP_CONCAT(
                    CONCAT(a.title, ' (due: ', DATE_FORMAT(a.due_date,'%d %b'), ')')
                    ORDER BY a.due_date SEPARATOR ', '
                )
            FROM users s
            JOIN class_enrollments ce ON ce.user_id = s.id
            JOIN assignments a ON a.class_id = ce.class_id
            LEFT JOIN submissions sub ON sub.assignment_id = a.id AND sub.user_id = s.id
            WHERE a.due_date BETWEEN NOW() AND DATE_ADD(NOW(), INTERVAL 7 DAY)
              AND sub.id IS NULL AND s.is_active = 1 AND s.phone IS NOT NULL
            GROUP BY s.id
        """)

        week_label = datetime.today().strftime("Week of %d %b")

        for row in students_with_deadlines:
            ref = f"digest:{row['student_id']}:{datetime.today().date()}"
            if _already_notified(self.query, "weekly_digest", row["phone"], ref):
                continue

            ok = _send_wa_template(row["phone"], "lms_weekly_digest", [
                row["student_name"],
                week_label,
                str(row["deadline_count"]),
                row["deadlines"]
            ])
            if ok:
                _log_notification(self.query, "weekly_digest", row["phone"], ref)

            if row.get("email"):
                _send_email(
                    self.mail, row["email"],
                    f"Your Weekly Digest — {week_label}",
                    f"Hi {row['student_name']},\n\nHere are your upcoming deadlines this week:\n\n{row['deadlines']}\n\nStay on top of your work!\n\nRegards,\nIMS Team"
                )
