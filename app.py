import os ,time
import random
import string
from datetime import datetime, timedelta
from functools import wraps
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask_mail import Mail, Message
from flask_bcrypt import Bcrypt
import pymysql
from ims_app.ai_risk import(get_student_risk_data, generate_ai_feedback, career_suggestion, risk_level,)
from dotenv import load_dotenv
from datetime import datetime
from werkzeug.utils import secure_filename
from google import genai
import requests
load_dotenv()
from notifications import Notify
from scheduler import start_scheduler




GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

print("Gemini API key loaded:", bool(GEMINI_API_KEY))

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found. Check your .env file.")

client = genai.Client(api_key=GEMINI_API_KEY)

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'ims-super-secret-key-2025')

# ── Mail Config ──────────────────────────────────────────────────────────────
# ── Mail Config ──────────────────────────────────────────────────────────────
app.config['MAIL_SERVER']   = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT']     = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']  = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'goldajanu@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'iargvxtybxhublra')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME', 'goldajanu@gmail.com')

mail  = Mail(app)
bcrypt = Bcrypt(app)




# ── DB ────────────────────────────────────────────────────────────────────────
DB_CFG = dict(
    host     = os.getenv('DB_HOST',   'localhost'),
    user     = os.getenv('DB_USER',   'root'),
    password = os.getenv('DB_PASS',   '123456'),
    db       = os.getenv('DB_NAME',   'ims_db'),
    charset  = 'utf8mb4',
    cursorclass = pymysql.cursors.DictCursor,
    autocommit = True,
)

def get_db():
    return pymysql.connect(**DB_CFG)

def query(sql, args=(), one=False, commit=False):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            if commit:
                conn.commit()
                return cur.lastrowid
            return (cur.fetchone() if one else cur.fetchall())
    finally:
        conn.close()

# ── Notification system ───────────────────────────────────────────────────────

notify = Notify(mail, query)

UPLOAD_FOLDER_SUBMISSIONS = os.path.join('static', 'uploads', 'submissions')
os.makedirs(UPLOAD_FOLDER_SUBMISSIONS, exist_ok=True)

def save_submission_file(file):
    if file and file.filename:
        filename = secure_filename(file.filename)
        unique_name = f"{int(time.time())}_{filename}"
        file.save(os.path.join(UPLOAD_FOLDER_SUBMISSIONS, unique_name))
        return unique_name
    return None
# ── Auth helpers ──────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*a, **kw)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*a, **kw):
            if session.get('role') not in roles:
                flash('Access denied.', 'error')
                return redirect(url_for('dashboard'))
            return f(*a, **kw)
        return decorated
    return decorator



WHATSAPP_TOKEN = os.getenv('WHATSAPP_TOKEN')
WHATSAPP_PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
WHATSAPP_API_VERSION = os.getenv('WHATSAPP_API_VERSION', 'v21.0')
WHATSAPP_API_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"

def _wa_headers():
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

def normalize_phone(phone):
    """Ensure phone is in E.164 format without '+' (Meta wants digits only, country code first)."""
    phone = ''.join(ch for ch in phone if ch.isdigit())
    return phone

def send_whatsapp_text(to_phone, message):
    """
    Free-form text message. Only works within 24h of the user's last
    incoming message to you. Use send_whatsapp_template for anything else.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(to_phone),
        "type": "text",
        "text": {"body": message}
    }
    try:
        resp = requests.post(WHATSAPP_API_URL, headers=_wa_headers(), json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print("WhatsApp send error:", e, getattr(e.response, 'text', ''))
        return None

def send_whatsapp_template(to_phone, template_name, lang_code='en_US', params=None):
    """
    Template message — works anytime, even outside the 24h window.
    params: list of strings to fill {{1}}, {{2}}, ... placeholders in the approved template body.
    """
    components = []
    if params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in params]
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(to_phone),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang_code},
            "components": components
        }
    }
    try:
        resp = requests.post(WHATSAPP_API_URL, headers=_wa_headers(), json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print("WhatsApp send error:", e, getattr(e.response, 'text', ''))
        return None
# ── OTP store (in-memory, replace with Redis in production) ──────────────────
otp_store = {}   # {email: {otp, expires}}

def gen_otp():
    return ''.join(random.choices(string.digits, k=6))

# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = query("SELECT * FROM users WHERE email=%s AND is_active=1", (email,), one=True)
        if user and bcrypt.check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['name']    = user['name']
            session['email']   = user['email']
            session['role']    = user['role']
            session['avatar']  = user.get('avatar', '')
            query("UPDATE users SET last_login=NOW() WHERE id=%s", (user['id'],), commit=True)
            log_activity(user['id'], 'login', 'User logged in')
            import hashlib
            raw = (request.headers.get('User-Agent','') + request.remote_addr)
            device_hash = hashlib.sha256(raw.encode()).hexdigest()
            known_device = query(
                    "SELECT id FROM student_devices WHERE student_id=%s AND device_hash=%s",
                    (user['id'], device_hash), one=True
                )
            if not known_device:
                    query(
                        "INSERT INTO student_devices (student_id, device_hash, first_seen, last_seen) VALUES (%s,%s,NOW(),NOW())",
                        (user['id'], device_hash), commit=True
                    )
                    device_label = request.headers.get('User-Agent','Unknown device')[:80]
                    notify.security_alert(user['id'], device_label)
            else:
                    query(
                        "UPDATE student_devices SET last_seen=NOW() WHERE student_id=%s AND device_hash=%s",
                        (user['id'], device_hash), commit=True
                    )
            
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'user_id' in session:
        log_activity(session['user_id'], 'logout', 'User logged out')
    session.clear()
    return redirect(url_for('login'))



@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name  = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        role  = request.form.get('role', 'trainee')
        pwd   = request.form.get('password', '')
        cpwd  = request.form.get('confirm_password', '')

        if not all([name, email, phone, role, pwd]):
            flash('All fields are required.', 'error')
            return render_template('register.html')

        if pwd != cpwd:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')

        if len(pwd) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('register.html')

        if query("SELECT id FROM users WHERE email=%s", (email,), one=True):
            flash('Email already registered.', 'error')
            return render_template('register.html')

        pw_hash = bcrypt.generate_password_hash(pwd).decode()

        uid = query(
            """
            INSERT INTO users
            (name, email, phone, role, password_hash, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, 1, NOW())
            """,
            (name, email, phone, role, pw_hash),
            commit=True
        )

        # Welcome notification
        create_notification(
            uid,
            "Welcome to IMS",
            f"Hello {name}, your account has been created successfully."
        )

        # Welcome email
        try:
            send_mail(
                email,
                f"Welcome to IMS, {name}!",
                f"Your account has been created successfully.\nRole: {role.capitalize()}\nLogin: {email}"
            )
        except Exception:
            pass

        log_activity(uid, 'register', f'New {role} account created')

        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    return render_template('forgot_password.html')

@app.route('/send-otp', methods=['POST'])
def send_otp():
    email = request.form.get('email', '').strip().lower()
    user  = query("SELECT id FROM users WHERE email=%s AND is_active=1", (email,), one=True)
    if not user:
        flash('No account found with that email.', 'error')
        return render_template('forgot_password.html')
    otp = gen_otp()
    otp_store[email] = {'otp': otp, 'expires': datetime.now() + timedelta(minutes=10)}
    try:
        send_mail(email, "IMS – Your Password Reset OTP",
                  f"Your OTP is: {otp}\n\nThis OTP expires in 10 minutes.\nIf you did not request this, ignore this email.")
        flash(f'OTP sent to {email}. Check your inbox.', 'success')
    except Exception as e:
           print("Email Error:", e)
           flash(f"Email sending failed: {e}", "danger")

    notify_whatsapp(user['id'], 'otp_alert', params=[otp])

    session['reset_email'] = email
    return redirect(url_for('verify_otp'))

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'reset_email' not in session:
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        entered = request.form.get('otp', '').strip()
        email   = session.get('reset_email')
        rec     = otp_store.get(email)
        if not rec or datetime.now() > rec['expires']:
            flash('OTP expired. Please request a new one.', 'error')
            return redirect(url_for('forgot_password'))
        if entered != rec['otp']:
            flash('Incorrect OTP. Try again.', 'error')
            return render_template('verify_otp.html')
        session['otp_verified'] = True
        return redirect(url_for('reset_password'))
    return render_template('verify_otp.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('otp_verified') or 'reset_email' not in session:
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        pwd  = request.form.get('password', '')
        cpwd = request.form.get('confirm_password', '')
        if pwd != cpwd:
            flash('Passwords do not match.', 'error')
            return render_template('reset_password.html')
        if len(pwd) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('reset_password.html')
        email = session.pop('reset_email')
        session.pop('otp_verified', None)
        otp_store.pop(email, None)
        pw_hash = bcrypt.generate_password_hash(pwd).decode()
        query("UPDATE users SET password_hash=%s WHERE email=%s", (pw_hash, email), commit=True)
        flash('Password reset successfully! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html')

# ═══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/dashboard')
@login_required
def dashboard():
    role = session['role']
    if role == 'admin':
                return redirect(url_for('admin_risk_dashboard'))
    elif role == 'mentor':
        return redirect(url_for('mentor_dashboard'))
    else:
        return redirect(url_for('trainee_dashboard'))

# ─── ADMIN ───────────────────────────────────────────────────────────────────

@app.route('/admin/dashboard')
@login_required
@role_required('admin')
def admin_dashboard():
    stats = {
        'total_users':    query("SELECT COUNT(*) as c FROM users WHERE is_active=1", one=True)['c'],
        'mentors':        query("SELECT COUNT(*) as c FROM users WHERE role='mentor' AND is_active=1", one=True)['c'],
        'trainees':       query("SELECT COUNT(*) as c FROM users WHERE role='trainee' AND is_active=1", one=True)['c'],
        'new_signups':    query("SELECT COUNT(*) as c FROM users WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)", one=True)['c'],
        'active_classes': query("SELECT COUNT(*) as c FROM classes WHERE is_active=1", one=True)['c'],
        'total_assignments': query("SELECT COUNT(*) as c FROM assignments", one=True)['c'],
    }
    recent_users = query("SELECT id,name,email,role,created_at,is_active FROM users ORDER BY created_at DESC LIMIT 5")
    activity_log = query("SELECT al.*,u.name FROM activity_log al JOIN users u ON al.user_id=u.id ORDER BY al.created_at DESC LIMIT 8")
    top_trainees = query("""
        SELECT u.name, ROUND(AVG(s.marks),1) as avg_marks,
               ROUND(AVG(a.present)*100,0) as attendance
        FROM users u
        LEFT JOIN submissions s ON s.user_id=u.id AND s.marks IS NOT NULL
        LEFT JOIN attendance a  ON a.user_id=u.id
        WHERE u.role='trainee' AND u.is_active=1
        GROUP BY u.id ORDER BY avg_marks DESC LIMIT 5
    """)
    reg_trend = query("""
    SELECT
        YEAR(created_at) AS yr,
        MONTH(created_at) AS mon_num,
        DATE_FORMAT(MIN(created_at), '%%b') AS mon,
        COUNT(*) AS cnt
    FROM users
    WHERE created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)
    GROUP BY YEAR(created_at), MONTH(created_at)
    ORDER BY yr, mon_num
""")
    batch_attendance = query("""
        SELECT c.name as batch, ROUND(AVG(a.present)*100,0) as pct
        FROM attendance a JOIN classes c ON a.class_id=c.id
        GROUP BY c.id ORDER BY c.name LIMIT 4
    """)
    announcements_count = query("SELECT COUNT(*) as c FROM announcements WHERE created_at >= DATE_SUB(NOW(),INTERVAL 7 DAY)", one=True)['c']
    return render_template('admin/dashboard.html',
        stats=stats, recent_users=recent_users,
        activity_log=activity_log, top_trainees=top_trainees,
        reg_trend=reg_trend, batch_attendance=batch_attendance,
        announcements_count=announcements_count)

@app.route('/admin/users')
@login_required
@role_required('admin')
def admin_users():
    role_filter = request.args.get('role', '')
    search = request.args.get('search', '')
    sql = "SELECT * FROM users WHERE 1=1"
    args = []
    if role_filter:
        sql += " AND role=%s"; args.append(role_filter)
    if search:
        sql += " AND (name LIKE %s OR email LIKE %s)"
        args += [f'%{search}%', f'%{search}%']
    sql += " ORDER BY created_at DESC"
    users = query(sql, args)
    return render_template('admin/users.html', users=users, role_filter=role_filter, search=search)

@app.route('/admin/users/add', methods=['GET','POST'])
@login_required
@role_required('admin')
def admin_add_user():
    if request.method == 'POST':
        name  = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        phone = request.form.get('phone','').strip()
        role  = request.form['role']
        pwd   = request.form['password']
        if query("SELECT id FROM users WHERE email=%s",(email,), one=True):
            flash('Email already exists.','error')
            return render_template('admin/add_user.html')
        pw_hash = bcrypt.generate_password_hash(pwd).decode()
        query("INSERT INTO users(name,email,phone,role,password_hash,is_active,created_at) VALUES(%s,%s,%s,%s,%s,1,NOW())",
              (name,email,phone,role,pw_hash), commit=True)
        flash(f'{role.capitalize()} added successfully.','success')
        return redirect(url_for('admin_users'))
    return render_template('admin/add_user.html')

@app.route('/admin/users/toggle/<int:uid>', methods=['POST'])
@login_required
@role_required('admin')
def toggle_user(uid):
    user = query("SELECT is_active FROM users WHERE id=%s",(uid,), one=True)
    if user:
        query("UPDATE users SET is_active=%s WHERE id=%s",(0 if user['is_active'] else 1, uid), commit=True)
    return redirect(url_for('admin_users'))

@app.route('/admin/class/<int:class_id>')
@login_required
@role_required('admin')
def admin_view_class(class_id):

    cls = query("""
        SELECT c.*, u.name AS mentor_name
        FROM classes c
        LEFT JOIN users u ON c.mentor_id = u.id
        WHERE c.id = %s
    """, (class_id,), one=True)

    if not cls:
        flash("Class not found.", "error")
        return redirect(url_for('admin_classes'))

    return render_template(
        'admin/class_details.html',
        cls=cls
    )

@app.route('/admin/class/<int:class_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_edit_class(class_id):

    if request.method == 'POST':
        query("""
            UPDATE classes
            SET name=%s, mentor_id=%s, description=%s
            WHERE id=%s
        """, (
            request.form['name'],
            request.form['mentor_id'] or None,
            request.form['description'],
            class_id
        ), commit=True)

        # sync trainee enrollments
        selected_ids = set(request.form.getlist('trainee_ids'))
        current = query("SELECT user_id FROM class_enrollments WHERE class_id=%s", (class_id,))
        current_ids = set(str(c['user_id']) for c in current)

        for tid in (selected_ids - current_ids):
            query("INSERT INTO class_enrollments(class_id,user_id) VALUES(%s,%s)", (class_id, tid), commit=True)

        for tid in (current_ids - selected_ids):
            query("DELETE FROM class_enrollments WHERE class_id=%s AND user_id=%s", (class_id, tid), commit=True)

        flash("Class updated successfully.", "success")
        return redirect(url_for('admin_view_class', class_id=class_id))

    cls = query("SELECT * FROM classes WHERE id=%s", (class_id,), one=True)
    mentors = query("SELECT id, name FROM users WHERE role='mentor' AND is_active=1")

    trainees = query("SELECT id, name FROM users WHERE role='trainee' AND is_active=1 ORDER BY name")
    enrolled = query("SELECT user_id FROM class_enrollments WHERE class_id=%s", (class_id,))
    enrolled_ids = {e['user_id'] for e in enrolled}
    for t in trainees:
        t['enrolled'] = t['id'] in enrolled_ids

    return render_template('admin/edit_class.html', cls=cls, mentors=mentors, trainees=trainees)

@app.route('/admin/class/<int:class_id>/delete',
           methods=['POST'])
def admin_delete_class(class_id):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM classes WHERE id=%s",
        (class_id,)
    )

    conn.commit()

    flash('Class deleted successfully','success')

    return redirect(url_for('admin_classes'))

@app.route('/admin/class/<int:class_id>/students')
@login_required
@role_required('admin')
def admin_class_students(class_id):

    enrolled_students = query("""
    SELECT u.*
    FROM users u
    JOIN class_enrollments ce
        ON ce.user_id = u.id
    WHERE ce.class_id = %s
""", (class_id,))

    available_students = query("""
    SELECT *
    FROM users
    WHERE role='trainee'
    AND is_active=1
    AND id NOT IN (
        SELECT user_id
        FROM class_enrollments
        WHERE class_id=%s
    )
""", (class_id,))

    return render_template(
        'admin/class_students.html',
        enrolled_students=enrolled_students,
        available_students=available_students,
        class_id=class_id
    )
@app.route('/admin/users/delete/<int:uid>', methods=['POST'])
@login_required
@role_required('admin')
def delete_user(uid):

    # Prevent admin from deleting themselves
    if uid == session.get('user_id'):
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin_users'))

    try:
        query(
            "DELETE FROM users WHERE id=%s",
            (uid,),
            commit=True
        )

        flash('User deleted successfully.', 'success')

    except Exception as e:
        flash(f'Error deleting user: {str(e)}', 'error')

    return redirect(request.referrer or url_for('admin_users'))

@app.route('/admin/class/<int:class_id>/add_students', methods=['POST'])
@login_required
@role_required('admin')
def add_students_to_class(class_id):
    student_ids = request.form.getlist('student_ids')  # list of checked checkbox values

    added = 0
    for sid in student_ids:
        existing = query("""
            SELECT id FROM class_enrollments
            WHERE class_id=%s AND user_id=%s
        """, (class_id, sid), one=True)
        if not existing:
            query("""
                INSERT INTO class_enrollments(class_id, user_id)
                VALUES(%s,%s)
            """, (class_id, sid), commit=True)
            cls = query("SELECT name FROM classes WHERE id=%s", (class_id,), one=True)
            if cls:
                notify.welcome_student(int(sid), cls['name'])
            added += 1

    if added:
        flash(f'{added} student(s) added to class.', 'success')
    else:
        flash('No new students were added.', 'info')

    return redirect(url_for('admin_class_students', class_id=class_id))

@app.route('/admin/class/<int:class_id>/add_student/<int:student_id>', methods=['POST'])
@login_required
@role_required('admin')
def add_student_to_class(class_id, student_id):

    # prevent duplicate enrollment
    existing = query("""
        SELECT id 
        FROM class_enrollments
        WHERE class_id=%s AND user_id=%s
    """, (class_id, student_id), one=True)


    if not existing:

        query("""
            INSERT INTO class_enrollments(class_id, user_id)
            VALUES(%s,%s)
        """,
        (class_id, student_id),
        commit=True)

        cls = query("SELECT name FROM classes WHERE id=%s", (class_id,), one=True)
        if cls:
                notify.welcome_student(student_id, cls['name'])

        flash("Student added successfully", "success")

    else:

        flash("Student already exists in this class", "warning")


    return redirect(
        url_for(
            'admin_class_students',
            class_id=class_id
        )
    )

@app.route('/admin/class/<int:class_id>/remove_student/<int:student_id>', methods=['POST'])
@login_required
@role_required('admin')
def remove_student_from_class(class_id, student_id):

    query("""
        DELETE FROM class_enrollments
        WHERE class_id=%s
        AND user_id=%s
    """,
    (class_id, student_id),
    commit=True)


    flash("Student removed from class", "success")


    return redirect(
        url_for(
            'admin_class_students',
            class_id=class_id
        )
    )



@app.route('/admin/classes')
@login_required
@role_required('admin')
def admin_classes():
    classes = query("""
        SELECT c.*, u.name as mentor_name,
               (SELECT COUNT(*) FROM class_enrollments ce WHERE ce.class_id=c.id) as student_count
        FROM classes c LEFT JOIN users u ON c.mentor_id=u.id ORDER BY c.created_at DESC
    """)
    mentors = query("SELECT id,name FROM users WHERE role='mentor' AND is_active=1")
    trainees = query("SELECT id,name FROM users WHERE role='trainee' AND is_active=1 ORDER BY name")
    return render_template('admin/classes.html', classes=classes, mentors=mentors, trainees=trainees)

@app.route('/admin/classes/add', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_class():
    name        = request.form['name'].strip()
    mentor_id   = request.form.get('mentor_id') or None
    desc        = request.form.get('description','').strip()
    trainee_ids = request.form.getlist('trainee_ids')

    class_id = query("INSERT INTO classes(name,mentor_id,description,is_active,created_at) VALUES(%s,%s,%s,1,NOW())",
          (name, mentor_id, desc), commit=True)

    for tid in trainee_ids:
        query("INSERT INTO class_enrollments(class_id,user_id) VALUES(%s,%s)", (class_id, tid), commit=True)

    flash('Class created.','success')
    return redirect(url_for('admin_classes'))

@app.route('/admin/assignments')
@login_required
@role_required('admin')
def admin_assignments():
    assignments = query("""
        SELECT a.*, c.name as class_name, u.name as created_by_name,
               (SELECT COUNT(*) FROM submissions s WHERE s.assignment_id=a.id) as submission_count
        FROM assignments a
        LEFT JOIN classes c ON a.class_id=c.id
        LEFT JOIN users u ON a.created_by=u.id
        ORDER BY a.created_at DESC
    """)
    classes = query("SELECT id,name FROM classes WHERE is_active=1")
    return render_template('admin/assignments.html', assignments=assignments, classes=classes,now=datetime.now().date())

@app.route('/admin/assignments/add', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_assignment():
    title    = request.form['title'].strip()
    class_id = request.form.get('class_id') or None
    due_date = request.form.get('due_date')
    desc     = request.form.get('description','').strip()
    query("INSERT INTO assignments(title,class_id,description,due_date,created_by,created_at) VALUES(%s,%s,%s,%s,%s,NOW())",
          (title, class_id, desc, due_date, session['user_id']), commit=True)
    flash('Assignment created.','success')
    return redirect(url_for('admin_assignments'))

@app.route('/admin/assignments/<int:assignment_id>')
@login_required
@role_required('admin')
def admin_get_assignment(assignment_id):

    assignment = query("""
        SELECT a.*, c.name AS class_name,
               u.name AS created_by_name,
               (SELECT COUNT(*)
                FROM submissions
                WHERE assignment_id=a.id) AS submission_count
        FROM assignments a
        LEFT JOIN classes c
        ON c.id=a.class_id
        LEFT JOIN users u
        ON u.id=a.created_by
        WHERE a.id=%s
    """,(assignment_id,),one=True)

    if not assignment:
        return jsonify({
            "success":False,
            "message":"Assignment not found"
        }),404

    if assignment["due_date"]:
        assignment["due_date"] = assignment["due_date"].strftime("%Y-%m-%d")

    return jsonify({
        "success":True,
        "assignment":assignment
    })

@app.route('/admin/assignments/update/<int:assignment_id>',methods=['POST'])
@login_required
@role_required('admin')
def admin_update_assignment(assignment_id):

    title=request.form["title"].strip()
    class_id=request.form.get("class_id") or None
    due_date=request.form.get("due_date") or None
    description=request.form.get("description","").strip()

    query("""
        UPDATE assignments
        SET
            title=%s,
            class_id=%s,
            due_date=%s,
            description=%s
        WHERE id=%s
    """,
    (
        title,
        class_id,
        due_date,
        description,
        assignment_id
    ),
    commit=True)

    flash("Assignment updated successfully.","success")

    return redirect(url_for("admin_assignments"))


@app.route('/admin/assignments/view/<int:id>')
@login_required
@role_required('admin')
def admin_view_assignment(id):

    assignment = query("""
        SELECT a.*,
               c.name AS class_name,
               u.name AS created_by_name
        FROM assignments a
        LEFT JOIN classes c ON a.class_id = c.id
        LEFT JOIN users u ON a.created_by = u.id
        WHERE a.id=%s
    """, (id,), one=True)

    if not assignment:
        return jsonify({"success": False})

    if assignment.get("due_date"):
        assignment["due_date"] = assignment["due_date"].strftime("%Y-%m-%d")

    if assignment.get("created_at"):
        assignment["created_at"] = assignment["created_at"].strftime("%d %b %Y %I:%M %p")

    assignment["success"] = True

    return jsonify(assignment)


@app.route('/admin/assignments/delete/<int:assignment_id>',methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_assignment(assignment_id):

    submission=query(
        "SELECT COUNT(*) AS total FROM submissions WHERE assignment_id=%s",
        (assignment_id,),
        one=True
    )

    if submission["total"]>0:
        flash(
            "Cannot delete this assignment because students have already submitted it.",
            "danger"
        )
        return redirect(url_for("admin_assignments"))

    query(
        "DELETE FROM assignments WHERE id=%s",
        (assignment_id,),
        commit=True
    )

    flash("Assignment deleted successfully.","success")

    return redirect(url_for("admin_assignments"))


@app.route('/admin/attendance')
@login_required
@role_required('admin')
def admin_attendance():
    records = query("""
        SELECT a.*, u.name as student_name, c.name as class_name
        FROM attendance a JOIN users u ON a.user_id=u.id JOIN classes c ON a.class_id=c.id
        ORDER BY a.date DESC LIMIT 100
    """)
    summary = query("""
        SELECT u.name, COUNT(*) as total, SUM(a.present) as present_days
        FROM attendance a JOIN users u ON a.user_id=u.id
        WHERE u.role='trainee'
        GROUP BY u.id ORDER BY u.name
    """)
    return render_template('admin/attendance.html', records=records, summary=summary)

@app.route('/admin/exams')
@login_required
@role_required('admin')
def admin_exams():
    exams = query("""
        SELECT e.*, c.name as class_name,
               (SELECT ROUND(AVG(es.marks),1) FROM exam_scores es WHERE es.exam_id=e.id) as avg_score
        FROM exams e LEFT JOIN classes c ON e.class_id=c.id ORDER BY e.exam_date DESC
    """)
    classes = query("SELECT id,name FROM classes WHERE is_active=1")
    return render_template('admin/exams.html', exams=exams, classes=classes,now=datetime.now().date())



@app.route('/admin/exams/<int:exam_id>/publish', methods=['POST'])
@login_required
@role_required('admin')
def admin_publish_exam_results(exam_id):
    exam = query("SELECT * FROM exams WHERE id=%s", (exam_id,), one=True)
    if not exam:
        flash('Exam not found.', 'error')
        return redirect(url_for('admin_exams'))
    query("UPDATE exams SET results_published=1 WHERE id=%s", (exam_id,), commit=True)
    if exam.get('class_id'):
        notify.exam_results(exam['class_id'], exam['title'])
    flash('Results published and students notified.', 'success')
    return redirect(url_for('admin_exams'))

from decimal import Decimal

@app.route('/admin/analytics_report')
@login_required
@role_required('admin')
def admin_analytics_report():
    mid = session['user_id']

    classes = query(
        "SELECT id FROM classes WHERE mentor_id=%s AND is_active=1",
        (mid,)
    )

    cids = [c['id'] for c in classes] or [0]
    fmt = ','.join(['%s'] * len(cids))

    perf = query(f"""
        SELECT u.id,
               u.name,
               AVG(s.marks) as avg_marks,
               (SELECT AVG(at2.present)*100
                FROM attendance at2
                WHERE at2.user_id=u.id
                AND at2.class_id IN ({fmt})) as att_pct,
               COUNT(s.id) as submissions
        FROM users u
        JOIN class_enrollments ce
            ON ce.user_id=u.id AND ce.class_id IN ({fmt})
        LEFT JOIN submissions s
            ON s.user_id=u.id AND s.marks IS NOT NULL
        WHERE u.role='trainee'
        GROUP BY u.id
        ORDER BY avg_marks DESC
    """, cids + cids)

    # ✅ FIX: normalize Decimal → float + compute score here
    for p in perf:
        avg = float(p['avg_marks'] or 0)
        att = float(p['att_pct'] or 0)

        p['score'] = (avg * 0.6) + (att * 0.4)

    return render_template('admin/analytics_report.html', perf=perf)

@app.route('/admin/announcements')
@login_required
@role_required('admin')
def admin_announcements():
    ann = query("SELECT a.*,u.name as author FROM announcements a JOIN users u ON a.created_by=u.id ORDER BY a.created_at DESC")
    return render_template('admin/announcements.html', announcements=ann)

@app.route('/admin/announcements/add', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_announcement():
    title   = request.form['title'].strip()
    content = request.form['content'].strip()
    target  = request.form.get('target_role','all')
    query("INSERT INTO announcements(title,content,target_role,created_by,created_at) VALUES(%s,%s,%s,%s,NOW())",
          (title, content, target, session['user_id']), commit=True)
    flash('Announcement posted.','success')

    # WhatsApp
    notify.announcement(target, title, content)

    # Email
    if target == 'all':
        users_to_notify = query(
            "SELECT name, email FROM users WHERE role IN ('trainee','mentor') AND is_active=1 AND email IS NOT NULL"
        )
    else:
        users_to_notify = query(
            "SELECT name, email FROM users WHERE role=%s AND is_active=1 AND email IS NOT NULL", (target,)
        )
    for u in users_to_notify:
        try:
            send_mail(
                u['email'],
                f"Announcement: {title}",
                f"Hi {u['name']},\n\n{title}\n\n{content}\n\nRegards,\nIMS Team"
            )
        except Exception as e:
            print(f"Email failed: {e}")

    return redirect(url_for('admin_announcements'))


@app.route('/admin/announcements/<int:ann_id>')
@login_required
@role_required('admin')
def admin_get_announcement(ann_id):
    ann = query("SELECT * FROM announcements WHERE id=%s", (ann_id,), one=True)
    if not ann:
        return jsonify({"success": False, "message": "Announcement not found"}), 404
    if ann.get("created_at"):
        ann["created_at"] = ann["created_at"].strftime("%d %b %Y %I:%M %p")
    ann["success"] = True
    return jsonify(ann)


@app.route('/admin/announcements/update/<int:ann_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_update_announcement(ann_id):
    title   = request.form['title'].strip()
    content = request.form['content'].strip()
    target  = request.form.get('target_role', 'all')
    query("""
        UPDATE announcements
        SET title=%s, content=%s, target_role=%s
        WHERE id=%s
    """, (title, content, target, ann_id), commit=True)
    flash('Announcement updated successfully.', 'success')
    return redirect(url_for('admin_announcements'))


@app.route('/admin/announcements/delete/<int:ann_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_announcement(ann_id):
    query("DELETE FROM announcements WHERE id=%s", (ann_id,), commit=True)
    flash('Announcement deleted successfully.', 'success')
    return redirect(url_for('admin_announcements'))

@app.route('/admin/reports')
@login_required
@role_required('admin')
def admin_reports():
    perf = query("""
        SELECT u.name, u.role,
               ROUND(AVG(s.marks),1) as avg_marks,
               COUNT(DISTINCT s.assignment_id) as submissions,
               (SELECT ROUND(AVG(a2.present)*100,0) FROM attendance a2 WHERE a2.user_id=u.id) as att_pct
        FROM users u
        LEFT JOIN submissions s ON s.user_id=u.id AND s.marks IS NOT NULL
        WHERE u.role IN ('trainee','mentor') AND u.is_active=1
        GROUP BY u.id ORDER BY avg_marks DESC
    """)

    # Normalize Decimal → float so Jinja math (p.avg_marks * 0.6) doesn't crash
    for p in perf:
        p['avg_marks'] = float(p['avg_marks'] or 0)
        p['att_pct']   = float(p['att_pct'] or 0)

    return render_template('admin/reports.html', perf=perf)
@app.route('/admin/extracurricular/export')
@login_required
@role_required('admin')
def admin_export_extracurricular():
    flash("Export feature coming soon.", "info")
    return redirect(url_for('admin_extracurricular'))

@app.route('/admin/extracurricular')
@login_required
@role_required('admin')
def admin_extracurricular():

    activities = query("""

    SELECT
        e.*,
        s.name AS student_name,
        m.name AS mentor_name

    FROM extracurricular e

    JOIN users s
        ON e.student_id=s.id

    LEFT JOIN users m
        ON e.mentor_id=m.id

    ORDER BY e.created_at DESC

    """)

    stats={

        "total":len(activities),

        "approved":sum(1 for i in activities if i["status"]=="Approved"),

        "pending":sum(1 for i in activities if i["status"]=="Pending"),

        "rejected":sum(1 for i in activities if i["status"]=="Rejected")

    }

    return render_template(
        "admin/extracurricular.html",
        activities=activities,
        stats=stats
    )

@app.route('/admin/system-logs')
@login_required
@role_required('admin')
def admin_system_logs():
    logs = query("""
        SELECT al.*,u.name,u.role FROM activity_log al JOIN users u ON al.user_id=u.id
        ORDER BY al.created_at DESC LIMIT 200
    """)
    return render_template('admin/system_logs.html', logs=logs)

@app.route('/admin/settings', methods=['GET','POST'])
@login_required
@role_required('admin')
def admin_settings():
    if request.method == 'POST':
        name  = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        query("UPDATE users SET name=%s,phone=%s WHERE id=%s",(name,phone,session['user_id']), commit=True)
        session['name'] = name
        flash('Settings updated.','success')
    user = query("SELECT * FROM users WHERE id=%s",(session['user_id'],), one=True)
    return render_template('admin/settings.html', user=user)

@app.route('/admin/change-password', methods=['POST'])
@login_required
@role_required('admin')
def admin_change_password():
    current_pwd = request.form.get('current_password', '')
    new_pwd     = request.form.get('new_password', '')
    confirm_pwd = request.form.get('confirm_password', '')

    user = query("SELECT * FROM users WHERE id=%s", (session['user_id'],), one=True)

    if not bcrypt.check_password_hash(user['password_hash'], current_pwd):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('admin_settings'))

    if new_pwd != confirm_pwd:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('admin_settings'))

    if len(new_pwd) < 6:
        flash('New password must be at least 6 characters.', 'error')
        return redirect(url_for('admin_settings'))

    pw_hash = bcrypt.generate_password_hash(new_pwd).decode()
    query("UPDATE users SET password_hash=%s WHERE id=%s", (pw_hash, session['user_id']), commit=True)
    flash('Password updated successfully.', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/settings/photo', methods=['POST'])
@login_required
@role_required('admin')
def admin_upload_photo():
    photo = request.files.get('photo')
    if not photo or not photo.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('admin_settings'))

    filename = secure_filename(photo.filename)
    extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    allowed = ['png', 'jpg', 'jpeg', 'webp']
    if extension not in allowed:
        flash('Only PNG, JPG, JPEG and WEBP files are allowed.', 'error')
        return redirect(url_for('admin_settings'))

    filename = f"{uuid.uuid4().hex}.{extension}"
    upload_folder = os.path.join(app.static_folder, 'uploads', 'avatars')
    os.makedirs(upload_folder, exist_ok=True)
    photo.save(os.path.join(upload_folder, filename))

    avatar_path = f"uploads/avatars/{filename}"
    query("UPDATE users SET avatar=%s WHERE id=%s", (avatar_path, session['user_id']), commit=True)
    session['avatar'] = avatar_path

    flash('Profile photo updated.', 'success')
    return redirect(url_for('admin_settings'))


@app.route('/admin/settings/photo/remove', methods=['POST'])
@login_required
@role_required('admin')
def admin_remove_photo():
    query("UPDATE users SET avatar=NULL WHERE id=%s", (session['user_id'],), commit=True)
    session['avatar'] = ''
    flash('Profile photo removed.', 'success')
    return redirect(url_for('admin_settings'))


@app.route('/admin/settings/notifications', methods=['POST'])
@login_required
@role_required('admin')
def admin_update_notification_prefs():
    notify_email    = 1 if request.form.get('notify_email') == 'on' else 0
    notify_whatsapp = 1 if request.form.get('notify_whatsapp') == 'on' else 0
    query("UPDATE users SET notify_email=%s, notify_whatsapp=%s WHERE id=%s",
          (notify_email, notify_whatsapp, session['user_id']), commit=True)
    flash('Notification preferences saved.', 'success')
    return redirect(url_for('admin_settings'))
# ─── MENTOR ───────────────────────────────────────────────────────────────────

@app.route('/mentor/dashboard')
@login_required
@role_required('mentor')
def mentor_dashboard():
    mid = session['user_id']
    my_classes = query("SELECT id,name FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    class_ids  = [c['id'] for c in my_classes] or [0]
    fmt = ','.join(['%s']*len(class_ids))
    trainees = query(f"""
        SELECT DISTINCT u.id,u.name,u.email FROM users u
        JOIN class_enrollments ce ON ce.user_id=u.id
        WHERE ce.class_id IN ({fmt}) AND u.role='trainee' AND u.is_active=1
    """, class_ids)
    stats = {
        'total_trainees':    len(trainees),
        'total_assignments': query(f"SELECT COUNT(*) as c FROM assignments WHERE class_id IN ({fmt})", class_ids, one=True)['c'],
        'submissions':       query(f"SELECT COUNT(*) as c FROM submissions s JOIN assignments a ON s.assignment_id=a.id WHERE a.class_id IN ({fmt})", class_ids, one=True)['c'],
        'pending_review':    query(f"SELECT COUNT(*) as c FROM submissions s JOIN assignments a ON s.assignment_id=a.id WHERE a.class_id IN ({fmt}) AND s.marks IS NULL", class_ids, one=True)['c'],
        'tasks':             query(f"SELECT COUNT(*) as c FROM tasks WHERE class_id IN ({fmt})", class_ids, one=True)['c'],
    }
    recent_subs = query(f"""
        SELECT s.*,u.name as trainee_name, a.title as assignment_title
        FROM submissions s JOIN users u ON s.user_id=u.id JOIN assignments a ON s.assignment_id=a.id
        WHERE a.class_id IN ({fmt}) ORDER BY s.submitted_at DESC LIMIT 5
    """, class_ids)
    deadlines = query(f"""
        SELECT a.id,a.title,a.due_date,c.name as class_name,
               (SELECT COUNT(*) FROM submissions s WHERE s.assignment_id=a.id) as sub_count
        FROM assignments a JOIN classes c ON a.class_id=c.id
        WHERE a.class_id IN ({fmt}) AND a.due_date >= CURDATE()
        ORDER BY a.due_date LIMIT 4
    """, class_ids)
    trainee_perf = query(f"""
        SELECT u.name,
               ROUND(AVG(s.marks),1) as avg_marks,
               (SELECT ROUND(AVG(at2.present)*100,0) FROM attendance at2 WHERE at2.user_id=u.id AND at2.class_id IN ({fmt})) as att_pct,
               COUNT(s.id) as task_done
        FROM users u
        JOIN class_enrollments ce ON ce.user_id=u.id AND ce.class_id IN ({fmt})
        LEFT JOIN submissions s ON s.user_id=u.id AND s.marks IS NOT NULL
        WHERE u.role='trainee' GROUP BY u.id ORDER BY avg_marks DESC
    """, class_ids + class_ids)
    announcements = query("SELECT * FROM announcements WHERE (target_role='mentor' OR target_role='all') ORDER BY created_at DESC LIMIT 3")
    return render_template('mentor/dashboard.html',
        stats=stats, my_classes=my_classes, trainees=trainees,
        recent_subs=recent_subs, deadlines=deadlines,
        trainee_perf=trainee_perf, announcements=announcements)

@app.route('/mentor/trainees')
@login_required
@role_required('mentor')
def mentor_trainees():
    mid = session['user_id']
    my_classes = query("SELECT id FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    cids = [c['id'] for c in my_classes] or [0]
    fmt = ','.join(['%s']*len(cids))
    trainees = query(f"""
        SELECT u.*, c.name as class_name,
               ROUND(AVG(s.marks),1) as avg_marks,
               (SELECT ROUND(AVG(a2.present)*100,0) FROM attendance a2 WHERE a2.user_id=u.id) as att_pct
        FROM users u
        JOIN class_enrollments ce ON ce.user_id=u.id AND ce.class_id IN ({fmt})
        JOIN classes c ON ce.class_id=c.id
        LEFT JOIN submissions s ON s.user_id=u.id AND s.marks IS NOT NULL
        WHERE u.role='trainee' GROUP BY u.id,c.id ORDER BY u.name
    """, cids)
    return render_template('mentor/trainees.html', trainees=trainees)

@app.route('/mentor/tasks')
@login_required
@role_required('mentor')
def mentor_tasks():
    mid = session['user_id']
    classes = query("SELECT id,name FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    cids = [c['id'] for c in classes] or [0]
    fmt = ','.join(['%s']*len(cids))
    tasks = query(f"""
        SELECT t.*,c.name as class_name,
               (SELECT COUNT(*) FROM task_submissions ts WHERE ts.task_id=t.id) as sub_count
        FROM tasks t JOIN classes c ON t.class_id=c.id
        WHERE t.class_id IN ({fmt}) ORDER BY t.due_date
    """, cids)
    return render_template('mentor/tasks.html', tasks=tasks, classes=classes)

@app.route('/mentor/tasks/add', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_add_task():
    title    = request.form['title'].strip()
    class_id = request.form['class_id']
    due_date = request.form.get('due_date')
    desc     = request.form.get('description','').strip()

    query("INSERT INTO tasks(title,class_id,description,due_date,created_by,created_at) VALUES(%s,%s,%s,%s,%s,NOW())",
          (title, class_id, desc, due_date, session['user_id']), commit=True)

    trainees = query("""
        SELECT u.id, u.name, u.email, u.phone, u.notify_whatsapp
        FROM users u
        JOIN class_enrollments ce ON ce.user_id = u.id
        WHERE ce.class_id = %s AND u.role = 'trainee' AND u.is_active = 1
    """, (class_id,))
    due_str = str(due_date) if due_date else "No due date"

    for t in trainees:
        create_notification(t['id'], 'New Task', f'{title} has been posted', '/trainee/tasks')

        # WhatsApp
        if t.get('phone') and t.get('notify_whatsapp', 1):
            send_whatsapp_template(t['phone'], 'lms_task_assigned', params=[t['name'], title, due_str])

        # Email
        if t.get('email'):
            try:
                send_mail(
                    t['email'],
                    f"New Task Assigned: {title}",
                    f"Hi {t['name']},\n\nA new task has been assigned to you.\n\nTask: {title}\nDue Date: {due_str}\n\nPlease log in to submit it.\n\nRegards,\nIMS Team"
                )
            except Exception as e:
                print(f"Email failed: {e}")

    flash('Task created.', 'success')
    return redirect(url_for('mentor_tasks'))

@app.route('/mentor/assignments')
@login_required
@role_required('mentor')
def mentor_assignments():
    mid = session['user_id']
    classes = query("SELECT id,name FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    cids = [c['id'] for c in classes] or [0]
    fmt = ','.join(['%s']*len(cids))
    assignments = query(f"""
        SELECT a.*,c.name as class_name,
               (SELECT COUNT(*) FROM submissions s WHERE s.assignment_id=a.id) as sub_count,
               (SELECT COUNT(*) FROM submissions s WHERE s.assignment_id=a.id AND s.marks IS NOT NULL) as graded_count
        FROM assignments a JOIN classes c ON a.class_id=c.id
        WHERE a.class_id IN ({fmt}) ORDER BY a.due_date
    """, cids)
    return render_template('mentor/assignments.html', assignments=assignments, classes=classes)

@app.route('/mentor/assignments/add', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_add_assignment():
    title    = request.form['title'].strip()
    class_id = request.form['class_id']
    due_date = request.form.get('due_date')
    desc     = request.form.get('description','').strip()

    query("INSERT INTO assignments(title,class_id,description,due_date,created_by,created_at) VALUES(%s,%s,%s,%s,%s,NOW())",
          (title,class_id,desc,due_date,session['user_id']), commit=True)

    trainees = query("""
        SELECT u.id, u.name, u.email, u.phone, u.notify_whatsapp
        FROM users u
        JOIN class_enrollments ce ON ce.user_id = u.id
        WHERE ce.class_id = %s AND u.role = 'trainee' AND u.is_active = 1
    """, (class_id,))
    due_str = str(due_date) if due_date else "No due date"

    for t in trainees:
        create_notification(t['id'], 'New Assignment', f'{title} has been posted', '/trainee/assignments')

        # WhatsApp
        if t.get('phone') and t.get('notify_whatsapp', 1):
            send_whatsapp_template(t['phone'], 'lms_task_assigned', params=[t['name'], title, due_str])

        # Email
        if t.get('email'):
            try:
                send_mail(
                    t['email'],
                    f"New Assignment: {title}",
                    f"Hi {t['name']},\n\nA new assignment has been posted.\n\nAssignment: {title}\nDue Date: {due_str}\n\nPlease log in to view and submit.\n\nRegards,\nIMS Team"
                )
            except Exception as e:
                print(f"Email failed: {e}")

    flash('Assignment created.', 'success')
    return redirect(url_for('mentor_assignments'))

@app.route('/mentor/submissions')
@login_required
@role_required('mentor')
def mentor_submissions():
    mid = session['user_id']
    classes = query("SELECT id FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    cids = [c['id'] for c in classes] or [0]
    fmt = ','.join(['%s']*len(cids))

    # Assignment submissions
    assignment_subs = query(f"""
        SELECT s.id, s.user_id, s.submitted_at, s.attachment,
               s.marks, s.feedback, s.content, s.link,
               u.name as trainee_name,
               a.title as assignment_title,
               c.name as class_name,
               'assignment' as sub_type
        FROM submissions s
        JOIN users u ON s.user_id=u.id
        JOIN assignments a ON s.assignment_id=a.id
        JOIN classes c ON a.class_id=c.id
        WHERE a.class_id IN ({fmt})
        ORDER BY s.submitted_at DESC
    """, cids)

    # Task submissions
    task_subs = query(f"""
        SELECT ts.id, ts.user_id, ts.submitted_at, ts.attachment,
               ts.marks, ts.feedback, ts.content,
               NULL as link,
               u.name as trainee_name,
               t.title as assignment_title,
               c.name as class_name,
               'task' as sub_type
        FROM task_submissions ts
        JOIN users u ON ts.user_id=u.id
        JOIN tasks t ON ts.task_id=t.id
        JOIN classes c ON t.class_id=c.id
        WHERE t.class_id IN ({fmt})
        ORDER BY ts.submitted_at DESC
    """, cids)

    return render_template('mentor/submissions.html',
                           assignment_subs=assignment_subs,
                           task_subs=task_subs)

@app.route('/mentor/submissions/grade/<int:sid>', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_grade(sid):
    marks    = request.form.get('marks')
    feedback = request.form.get('feedback','').strip()
    query("UPDATE submissions SET marks=%s,feedback=%s WHERE id=%s",(marks,feedback,sid), commit=True)

    sub = query("""
        SELECT s.user_id, a.title FROM submissions s
        JOIN assignments a ON s.assignment_id=a.id
        WHERE s.id=%s
    """, (sid,), one=True)

    if sub:
        create_notification(sub['user_id'], 'Marks Posted', f'"{sub["title"]}" has been graded: {marks}', '/trainee/assignments')

        # WhatsApp
        notify.assignment_graded(sub['user_id'], sub['title'], marks)

        # Email → notify student
        student = query("SELECT name, email FROM users WHERE id=%s", (sub['user_id'],), one=True)
        if student and student.get('email'):
            try:
                send_mail(
                    student['email'],
                    f"Assignment Graded: {sub['title']}",
                    f"Hi {student['name']},\n\nYour assignment has been graded.\n\nAssignment: {sub['title']}\nMarks: {marks}\n\nLog in to see your feedback.\n\nRegards,\nIMS Team"
                )
            except Exception as e:
                print(f"Email failed: {e}")

    flash('Marks updated.','success')
    return redirect(url_for('mentor_submissions'))

@app.route('/mentor/tasks/grade/<int:sid>', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_grade_task(sid):
    marks    = request.form.get('marks')
    feedback = request.form.get('feedback','').strip()
    query("UPDATE task_submissions SET marks=%s, feedback=%s WHERE id=%s",
          (marks, feedback, sid), commit=True)

    sub = query("""
        SELECT ts.user_id, t.title FROM task_submissions ts
        JOIN tasks t ON ts.task_id = t.id
        WHERE ts.id=%s
    """, (sid,), one=True)

    if sub:
        create_notification(sub['user_id'], 'Task Graded',
                            f'"{sub["title"]}" has been graded: {marks}',
                            '/trainee/tasks')

        # WhatsApp
        notify.assignment_graded(sub['user_id'], sub['title'], marks)

        # Email
        student = query("SELECT name, email FROM users WHERE id=%s",
                        (sub['user_id'],), one=True)
        if student and student.get('email'):
            try:
                send_mail(
                    student['email'],
                    f"Task Graded: {sub['title']}",
                    f"Hi {student['name']},\n\nYour task has been graded.\n\nTask: {sub['title']}\nMarks: {marks}\n\nLog in to see your feedback.\n\nRegards,\nIMS Team"
                )
            except Exception as e:
                print(f"Email failed: {e}")

    flash('Task marks updated.', 'success')
    return redirect(url_for('mentor_submissions'))



@app.route('/mentor/attendance', methods=['GET','POST'])
@login_required
@role_required('mentor')
def mentor_attendance():
    mid = session['user_id']
    classes = query("SELECT id,name FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    if request.method == 'POST':
        class_id = request.form['class_id']
        date     = request.form['date']
        # attendance dict: user_id -> present
        for key, val in request.form.items():
            if key.startswith('att_'):
                uid = int(key.split('_')[1])
                present = 1 if val == '1' else 0
                existing = query("SELECT id FROM attendance WHERE user_id=%s AND class_id=%s AND date=%s",(uid,class_id,date), one=True)
                if existing:
                    query("UPDATE attendance SET present=%s WHERE id=%s",(present,existing['id']), commit=True)
                else:
                    query("INSERT INTO attendance(user_id,class_id,date,present) VALUES(%s,%s,%s,%s)",(uid,class_id,date,present), commit=True)
        flash('Attendance saved.','success')
        return redirect(url_for('mentor_attendance'))
    records = query("""
        SELECT a.*,u.name as student_name,c.name as class_name
        FROM attendance a JOIN users u ON a.user_id=u.id JOIN classes c ON a.class_id=c.id
        WHERE c.mentor_id=%s ORDER BY a.date DESC LIMIT 50
    """, (mid,))
    from datetime import date
    return render_template('mentor/attendance.html', classes=classes, records=records, today=date.today().isoformat())

@app.route('/mentor/lectures')
@login_required
@role_required('mentor')
def mentor_lectures():
    mid = session['user_id']
    classes = query("SELECT id,name FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    cids = [c['id'] for c in classes] or [0]
    fmt = ','.join(['%s']*len(cids))
    lectures = query(f"SELECT l.*,c.name as class_name FROM lectures l JOIN classes c ON l.class_id=c.id WHERE l.class_id IN ({fmt}) ORDER BY l.created_at DESC", cids)
    return render_template('mentor/lectures.html', lectures=lectures, classes=classes)

ALLOWED_LECTURE_EXTENSIONS = {
    'pdf', 'ppt', 'pptx', 'doc', 'docx', 'xls', 'xlsx',
    'mp4', 'avi', 'mov', 'mkv', 'webm',
    'png', 'jpg', 'jpeg', 'gif',
    'zip', 'rar', 'txt'
}

UPLOAD_FOLDER_LECTURES = os.path.join('static', 'uploads', 'lectures')
os.makedirs(UPLOAD_FOLDER_LECTURES, exist_ok=True)

@app.route('/mentor/lectures/add', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_add_lecture():
    title    = request.form['title'].strip()
    class_id = request.form['class_id']
    url_link = request.form.get('url', '').strip()
    desc     = request.form.get('description', '').strip()
    filename = None

    # Handle file upload
    file = request.files.get('lecture_file')
    if file and file.filename:
        ext = file.filename.rsplit('.', 1)[-1].lower()
        if ext not in ALLOWED_LECTURE_EXTENSIONS:
            flash('File type not allowed.', 'error')
            return redirect(url_for('mentor_lectures'))
        filename = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(UPLOAD_FOLDER_LECTURES, filename))

    query("""
        INSERT INTO lectures(title, class_id, url, file_path, description, created_by, created_at)
        VALUES(%s, %s, %s, %s, %s, %s, NOW())
    """, (title, class_id, url_link or None, filename, desc, session['user_id']), commit=True)

    trainees = query("""
        SELECT u.id, u.name, u.email, u.phone, u.notify_whatsapp
        FROM users u
        JOIN class_enrollments ce ON ce.user_id = u.id
        WHERE ce.class_id = %s AND u.role = 'trainee' AND u.is_active = 1
    """, (class_id,))

    for t in trainees:
        create_notification(t['id'], 'New Lecture', f'{title} is available', '/trainee/lectures')
        if t.get('phone') and t.get('notify_whatsapp', 1):
            send_whatsapp_template(t['phone'], 'lecture_uploaded', params=[t['name'], title])
        if t.get('email'):
            try:
                send_mail(
                    t['email'],
                    f"New Lecture Available: {title}",
                    f"Hi {t['name']},\n\nA new lecture has been uploaded.\n\nLecture: {title}\n\nLog in to access it.\n\nRegards,\nIMS Team"
                )
            except Exception as e:
                print(f"Email failed: {e}")

    flash('Lecture uploaded.', 'success')
    return redirect(url_for('mentor_lectures'))

@app.route('/mentor/exams')
@login_required
@role_required('mentor')
def mentor_exams():
    mid = session['user_id']
    classes = query("SELECT id,name FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    cids = [c['id'] for c in classes] or [0]
    fmt = ','.join(['%s']*len(cids))
    exams = query(f"""
        SELECT e.*,c.name as class_name,
               (SELECT ROUND(AVG(es.marks),1) FROM exam_scores es WHERE es.exam_id=e.id) as avg_score
        FROM exams e JOIN classes c ON e.class_id=c.id
        WHERE e.class_id IN ({fmt}) ORDER BY e.exam_date DESC
    """, cids)
    return render_template('mentor/exams.html', exams=exams, classes=classes)

@app.route('/mentor/exams/add', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_add_exam():
    title    = request.form['title'].strip()
    class_id = request.form['class_id']
    exam_date= request.form.get('exam_date')
    max_marks= request.form.get('max_marks', 100)
    query("INSERT INTO exams(title,class_id,exam_date,max_marks,created_at) VALUES(%s,%s,%s,%s,NOW())",
          (title,class_id,exam_date,max_marks), commit=True)
    flash('Exam scheduled.','success')
    notify.exam_timetable(int(class_id), title, exam_date)
    return redirect(url_for('mentor_exams'))

@app.route('/mentor/analytics')
@login_required
@role_required('mentor')
def mentor_analytics():
    mid = session['user_id']
    classes = query("SELECT id FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    cids = [c['id'] for c in classes] or [0]
    fmt = ','.join(['%s']*len(cids))
    perf = query(f"""
        SELECT u.name,
               ROUND(AVG(s.marks),1) as avg_marks,
               (SELECT ROUND(AVG(at2.present)*100,0) FROM attendance at2 WHERE at2.user_id=u.id AND at2.class_id IN ({fmt})) as att_pct,
               COUNT(s.id) as submissions
        FROM users u
        JOIN class_enrollments ce ON ce.user_id=u.id AND ce.class_id IN ({fmt})
        LEFT JOIN submissions s ON s.user_id=u.id AND s.marks IS NOT NULL
        WHERE u.role='trainee' GROUP BY u.id ORDER BY avg_marks DESC
    """, cids+cids)
    return render_template('mentor/analytics.html', perf=perf)

@app.route('/mentor/announcements', methods=['GET','POST'])
@login_required
@role_required('mentor')
def mentor_announcements():
    if request.method == 'POST':
        title   = request.form['title'].strip()
        content = request.form['content'].strip()
        target  = request.form.get('target_role','trainee')
        query("INSERT INTO announcements(title,content,target_role,created_by,created_at) VALUES(%s,%s,%s,%s,NOW())",
              (title,content,target,session['user_id']), commit=True)
        flash('Announcement posted.','success')

        # WhatsApp
        notify.announcement(target, title, content)

        # Email
        if target == 'all':
            users_to_notify = query(
                "SELECT name, email FROM users WHERE role IN ('trainee','mentor') AND is_active=1 AND email IS NOT NULL"
            )
        else:
            users_to_notify = query(
                "SELECT name, email FROM users WHERE role=%s AND is_active=1 AND email IS NOT NULL", (target,)
            )
        for u in users_to_notify:
            try:
                send_mail(
                    u['email'],
                    f"Announcement: {title}",
                    f"Hi {u['name']},\n\n{title}\n\n{content}\n\nRegards,\nIMS Team"
                )
            except Exception as e:
                print(f"Email failed: {e}")

        return redirect(url_for('mentor_announcements'))
    ann = query("""
        SELECT a.*,u.name as author FROM announcements a JOIN users u ON a.created_by=u.id
        WHERE a.target_role IN ('trainee','mentor','all') OR a.created_by=%s
        ORDER BY a.created_at DESC
    """, (session['user_id'],))
    return render_template('mentor/announcements.html', announcements=ann)

@app.route('/mentor/calendar')
@login_required
@role_required('mentor')
def mentor_calendar():
    mid = session['user_id']
    classes = query("SELECT id FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    cids = [c['id'] for c in classes] or [0]
    fmt = ','.join(['%s']*len(cids))
    events = []
    assignments = query(f"SELECT title,due_date,'assignment' as type FROM assignments WHERE class_id IN ({fmt}) AND due_date IS NOT NULL", cids)
    exams       = query(f"SELECT title,exam_date as due_date,'exam' as type FROM exams WHERE class_id IN ({fmt}) AND exam_date IS NOT NULL", cids)
    events = list(assignments) + list(exams)
    return render_template('mentor/calendar.html', events=events)

@app.route('/mentor/question-bank')
@login_required
@role_required('mentor')
def mentor_question_bank():
    mid = session['user_id']
    questions = query("SELECT * FROM questions WHERE created_by=%s ORDER BY created_at DESC",(mid,))
    return render_template('mentor/question_bank.html', questions=questions)

@app.route('/mentor/question-bank/add', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_add_question():
    question = request.form['question'].strip()
    opts     = request.form.get('options','').strip()
    answer   = request.form.get('answer','').strip()
    qtype    = request.form.get('qtype','mcq')
    query("INSERT INTO questions(question,options,answer,qtype,created_by,created_at) VALUES(%s,%s,%s,%s,%s,NOW())",
          (question,opts,answer,qtype,session['user_id']), commit=True)
    flash('Question added.','success')
    return redirect(url_for('mentor_question_bank'))

@app.route('/mentor/risk-dashboard')
@login_required
@role_required('mentor')
def mentor_risk_dashboard():
    mid = session['user_id']

    my_classes = query("SELECT id FROM classes WHERE mentor_id=%s AND is_active=1", (mid,))
    cids = [c['id'] for c in my_classes] or [0]
    fmt = ','.join(['%s'] * len(cids))

    trainees = query(f"""
        SELECT DISTINCT u.id, u.name, u.email
        FROM users u
        JOIN class_enrollments ce ON ce.user_id=u.id
        WHERE ce.class_id IN ({fmt}) AND u.role='trainee' AND u.is_active=1
    """, cids)

    risk_list = []

    sports_count = 0
    technical_count = 0
    leadership_count = 0
    communication_count = 0
    cultural_count = 0
    talented_count = 0

    for t in trainees:

        data = get_student_risk_data(query, t['id'])

        activities = query("""
            SELECT category
            FROM extracurricular
            WHERE student_id=%s
            AND status='Approved'
        """, (t['id'],))

        sports = 0
        technical = 0
        leadership = 0
        communication = 0
        cultural = 0

        for a in activities:
            cat = (a['category'] or "").lower()
            if cat == "sports":
                sports += 1
            elif cat == "technical":
                technical += 1
            elif cat == "leadership":
                leadership += 1
            elif cat == "communication":
                communication += 1
            elif cat == "cultural":
                cultural += 1

        if sports: sports_count += 1
        if technical: technical_count += 1
        if leadership: leadership_count += 1
        if communication: communication_count += 1
        if cultural: cultural_count += 1

        skill_score = (sports*20 + technical*20 + leadership*20 + communication*20 + cultural*20)
        if skill_score > 100:
            skill_score = 100
        if skill_score >= 70:
            talented_count += 1

        scores = {
            "Sports": sports,
            "Technical": technical,
            "Leadership": leadership,
            "Communication": communication,
            "Cultural": cultural
        }

        if max(scores.values()) == 0:
            top_skill = "Not Identified"
            strengths = "No extracurricular participation"
            weaknesses = "Sports, Technical, Leadership, Communication, Cultural"
            ai = "Student has no extracurricular participation. Encourage involvement in extracurricular activities."
        else:
            top_skill = max(scores, key=scores.get)
            strengths = ", ".join([k for k, v in scores.items() if v > 0])
            weaknesses = ", ".join([k for k, v in scores.items() if v == 0])

            if data["risk_label"] == "High Risk" and skill_score >= 70:
                ai = "Excellent extracurricular performance but poor academics. Provide academic mentoring while encouraging extracurricular excellence."
            elif data["risk_label"] == "High Risk":
                ai = "Immediate academic mentoring required."
            elif skill_score >= 70:
                ai = "Excellent extracurricular performance. Encourage competitions and leadership opportunities."
            else:
                ai = "Balanced performance. Continue improving academics and extracurricular activities."

        data["name"] = t["name"]
        data["email"] = t["email"]
        data["skill_score"] = skill_score
        data["top_skill"] = top_skill
        data["strengths"] = strengths
        data["weaknesses"] = weaknesses
        data["ai_recommendation"] = ai

        risk_list.append(data)

    risk_list.sort(key=lambda x: x["risk_score"], reverse=True)

    high_count = sum(1 for r in risk_list if r["risk_label"] == "High Risk")
    medium_count = sum(1 for r in risk_list if r["risk_label"] == "Medium Risk")
    low_count = sum(1 for r in risk_list if r["risk_label"] == "Low Risk")

    return render_template(
        "mentor/risk_dashboard.html",
        risk_list=risk_list,
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        sports_count=sports_count,
        technical_count=technical_count,
        leadership_count=leadership_count,
        communication_count=communication_count,
        cultural_count=cultural_count,
        talented_count=talented_count
    )


@app.route('/mentor/extracurricular')
@login_required
@role_required('mentor')
def mentor_extracurricular():

    mentor = session["user_id"]

    my_classes = query("""
        SELECT id
        FROM classes
        WHERE mentor_id=%s
    """, (mentor,))

    cids = [c["id"] for c in my_classes] or [0]

    fmt = ",".join(["%s"] * len(cids))

    students = query(f"""
        SELECT DISTINCT
            u.id,
            u.name
        FROM users u
        JOIN class_enrollments ce
            ON ce.user_id = u.id
        WHERE ce.class_id IN ({fmt})
        ORDER BY u.name
    """, cids)

    activities = query(f"""
        SELECT
            e.*,
            u.name AS student_name
        FROM extracurricular e
        JOIN users u
            ON e.student_id = u.id
        JOIN class_enrollments ce
            ON ce.user_id = u.id
        WHERE ce.class_id IN ({fmt})
        ORDER BY e.created_at DESC
    """, cids)

    # -----------------------------
    # Dashboard Statistics
    # -----------------------------
    stats = {
        "total": len(activities),
        "pending": sum(1 for a in activities if a["status"] == "Pending"),
        "approved": sum(1 for a in activities if a["status"] == "Approved"),
        "rejected": sum(1 for a in activities if a["status"] == "Rejected")
    }

    return render_template(
        "mentor/extracurricular.html",
        students=students,
        activities=activities,
        stats=stats
    )

@app.route('/mentor/extracurricular/add',methods=["POST"])
@login_required
@role_required('mentor')
def mentor_add_extracurricular():

    query("""

    INSERT INTO extracurricular(

        student_id,
        mentor_id,
        category,
        title,
        description,
        level,
        achievement,
        participation_date,
        remarks

    )

    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)

    """,(


        request.form["student_id"],

        session["user_id"],

        request.form["category"],

        request.form["title"],

        request.form["description"],

        request.form["level"],

        request.form["achievement"],

        request.form["participation_date"],

        request.form["remarks"]

    ),

    commit=True)

    flash("Activity Added","success")

    return redirect(url_for("mentor_extracurricular"))

@app.route('/mentor/extracurricular/<int:eid>/<status>', methods=['GET', 'POST'])
@login_required
@role_required('mentor')
def mentor_verify_extracurricular(eid, status):

    if status not in ["Approved", "Rejected"]:
        flash("Invalid Status", "error")
        return redirect(url_for("mentor_extracurricular"))

    query("""
        UPDATE extracurricular
        SET
            status=%s,
            mentor_id=%s,
            approved_at=NOW()
        WHERE id=%s
    """, (
        status,
        session["user_id"],
        eid
    ),
    commit=True)

    flash("Updated", "success")
    return redirect(url_for("mentor_extracurricular"))


@app.route('/mentor/settings', methods=['GET','POST'])
@login_required
@role_required('mentor')
def mentor_settings():
    if request.method == 'POST':
        name  = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        query("UPDATE users SET name=%s,phone=%s WHERE id=%s",(name,phone,session['user_id']), commit=True)
        session['name'] = name
        flash('Settings updated.','success')
    user = query("SELECT * FROM users WHERE id=%s",(session['user_id'],), one=True)
    return render_template('mentor/settings.html', user=user)



# ─── TRAINEE ──────────────────────────────────────────────────────────────────

@app.route('/trainee/dashboard')
@login_required
@role_required('trainee')
def trainee_dashboard():
    tid = session['user_id']
    my_assignments = query("""
        SELECT a.*,c.name as class_name,
               (SELECT id FROM submissions s WHERE s.assignment_id=a.id AND s.user_id=%s LIMIT 1) as submitted_id,
               (SELECT marks FROM submissions s WHERE s.assignment_id=a.id AND s.user_id=%s LIMIT 1) as my_marks
        FROM assignments a
        JOIN classes c ON a.class_id=c.id
        JOIN class_enrollments ce ON ce.class_id=c.id
        WHERE ce.user_id=%s ORDER BY a.due_date
    """, (tid,tid,tid))

    total_assignments = len(my_assignments)
    submitted_count   = sum(1 for a in my_assignments if a['submitted_id'])
    completed_tasks   = query("SELECT COUNT(*) as c FROM task_submissions WHERE user_id=%s",(tid,), one=True)['c']
    total_tasks       = query("""
        SELECT COUNT(*) as c FROM tasks t
        JOIN class_enrollments ce ON ce.class_id=t.class_id WHERE ce.user_id=%s
    """, (tid,), one=True)['c']
    avg_marks_row = query("""
        SELECT ROUND(AVG(s.marks),1) as avg FROM submissions s WHERE s.user_id=%s AND s.marks IS NOT NULL
    """, (tid,), one=True)
    avg_marks = avg_marks_row['avg'] if avg_marks_row and avg_marks_row['avg'] else 0
    att_row   = query("SELECT ROUND(AVG(present)*100,0) as pct FROM attendance WHERE user_id=%s",(tid,), one=True)
    attendance = att_row['pct'] if att_row and att_row['pct'] else 0
    present_days= query("SELECT COUNT(*) as c FROM attendance WHERE user_id=%s AND present=1",(tid,), one=True)['c']
    absent_days = query("SELECT COUNT(*) as c FROM attendance WHERE user_id=%s AND present=0",(tid,), one=True)['c']
    total_days  = present_days + absent_days

    progress = int((submitted_count / total_assignments * 100) if total_assignments else 0)
    upcoming  = [a for a in my_assignments if not a['submitted_id'] and a.get('due_date')]
    marks_trend = query("""
    SELECT
        YEAR(s.submitted_at) AS yr,
        MONTH(s.submitted_at) AS mn,
        DATE_FORMAT(MIN(s.submitted_at), '%%b') AS mon,
        ROUND(AVG(s.marks), 0) AS avg
    FROM submissions s
    WHERE s.user_id = %s
      AND s.marks IS NOT NULL
    GROUP BY YEAR(s.submitted_at), MONTH(s.submitted_at)
    ORDER BY yr, mn
    LIMIT 6
""", (tid,))
    announcements = query("""
        SELECT a.*,u.name as author FROM announcements a JOIN users u ON a.created_by=u.id
        WHERE a.target_role IN ('trainee','all') ORDER BY a.created_at DESC LIMIT 4
    """)
    recent_activity = query("""
        SELECT al.*  FROM activity_log al WHERE al.user_id=%s ORDER BY al.created_at DESC LIMIT 5
    """, (tid,))

    return render_template('trainee/dashboard.html',
        progress=progress, total_assignments=total_assignments, submitted_count=submitted_count,
        completed_tasks=completed_tasks, total_tasks=total_tasks,
        avg_marks=avg_marks, attendance=attendance,
        present_days=present_days, absent_days=absent_days, total_days=total_days,
        upcoming=upcoming, marks_trend=marks_trend,
        announcements=announcements, recent_activity=recent_activity)

@app.route('/trainee/assignments')
@login_required
@role_required('trainee')
def trainee_assignments():
    tid = session['user_id']
    assignments = query("""
        SELECT a.*,c.name as class_name,
               s.id as submission_id, s.marks, s.feedback, s.submitted_at
        FROM assignments a
        JOIN classes c ON a.class_id=c.id
        JOIN class_enrollments ce ON ce.class_id=c.id AND ce.user_id=%s
        LEFT JOIN submissions s ON s.assignment_id=a.id AND s.user_id=%s
        ORDER BY a.due_date
    """, (tid,tid))
    return render_template('trainee/assignments.html', assignments=assignments)

@app.route('/trainee/assignments/submit/<int:aid>', methods=['POST'])
@login_required
@role_required('trainee')
def trainee_submit_assignment(aid):
    tid     = session['user_id']
    content = request.form.get('content','').strip()
    link    = request.form.get('link','').strip()
    file    = request.files.get('attachment')
    attachment = save_submission_file(file)

    existing = query("SELECT id FROM submissions WHERE assignment_id=%s AND user_id=%s",(aid,tid), one=True)
    if not existing:
        query("INSERT INTO submissions(assignment_id,user_id,content,link,attachment,submitted_at) VALUES(%s,%s,%s,%s,%s,NOW())",
              (aid,tid,content,link,attachment), commit=True)

        asgn = query("SELECT title, class_id FROM assignments WHERE id=%s", (aid,), one=True)
        if asgn:
            notify.assignment_submitted(aid, session['name'], asgn['title'])

            # Email → notify mentor
            mentor = query("""
                SELECT u.name, u.email FROM users u
                JOIN classes c ON c.mentor_id = u.id
                WHERE c.id = %s
            """, (asgn['class_id'],), one=True)
            if mentor and mentor.get('email'):
                try:
                    send_mail(
                        mentor['email'],
                        f"Assignment Submitted: {asgn['title']}",
                        f"Hi {mentor['name']},\n\n{session['name']} has submitted the assignment.\n\nAssignment: {asgn['title']}\n\nLog in to review and grade it.\n\nRegards,\nIMS Team"
                    )
                except Exception as e:
                    print(f"Email failed: {e}")

        log_activity(tid,'submit',f'Submitted assignment id={aid}')
        flash('Assignment submitted!','success')
    else:
        flash('Already submitted.','info')
    return redirect(url_for('trainee_assignments'))

@app.route('/trainee/tasks')
@login_required
@role_required('trainee')
def trainee_tasks():
    tid = session['user_id']
    tasks = query("""
        SELECT t.*,c.name as class_name,
               ts.id as submission_id, ts.submitted_at
        FROM tasks t
        JOIN classes c ON t.class_id=c.id
        JOIN class_enrollments ce ON ce.class_id=t.class_id AND ce.user_id=%s
        LEFT JOIN task_submissions ts ON ts.task_id=t.id AND ts.user_id=%s
        ORDER BY t.due_date
    """, (tid,tid))
    return render_template('trainee/tasks.html', tasks=tasks)

@app.route('/trainee/tasks/submit/<int:tid_>', methods=['POST'])
@login_required
@role_required('trainee')
def trainee_submit_task(tid_):
    tid     = session['user_id']
    content = request.form.get('content','').strip()
    file    = request.files.get('attachment')
    attachment = save_submission_file(file)

    existing = query("SELECT id FROM task_submissions WHERE task_id=%s AND user_id=%s",(tid_,tid), one=True)
    if not existing:
        query("INSERT INTO task_submissions(task_id,user_id,content,attachment,submitted_at) VALUES(%s,%s,%s,%s,NOW())",
              (tid_,tid,content,attachment), commit=True)

        task = query("SELECT title, class_id FROM tasks WHERE id=%s", (tid_,), one=True)
        if task:
            # WhatsApp
            notify.task_submitted(tid_, session['name'], task['title'])
            mentor = query("""
                SELECT u.name, u.email FROM users u
                JOIN classes c ON c.mentor_id = u.id
                WHERE c.id = %s
            """, (task['class_id'],), one=True)
            if mentor and mentor.get('email'):
                try:
                    send_mail(
                        mentor['email'],
                        f"Task Submitted: {task['title']}",
                        f"Hi {mentor['name']},\n\n{session['name']} has submitted a task.\n\nTask: {task['title']}\n\nLog in to review it.\n\nRegards,\nIMS Team"
                    )
                except Exception as e:
                    print(f"Email failed: {e}")

        log_activity(tid,'submit_task',f'Submitted task id={tid_}')
        flash('Task submitted!','success')
    else:
        flash('Already submitted.','info')
    return redirect(url_for('trainee_tasks'))


@app.route('/trainee/lectures')
@login_required
@role_required('trainee')
def trainee_lectures():
    tid = session['user_id']
    lectures = query("""
        SELECT l.*,c.name as class_name FROM lectures l
        JOIN classes c ON l.class_id=c.id
        JOIN class_enrollments ce ON ce.class_id=l.class_id AND ce.user_id=%s
        ORDER BY l.created_at DESC
    """, (tid,))
    return render_template('trainee/lectures.html', lectures=lectures)

@app.route('/trainee/exams')
@login_required
@role_required('trainee')
def trainee_exams():
    tid = session['user_id']
    exams = query("""
        SELECT e.*,c.name as class_name,
               es.marks as my_marks
        FROM exams e
        JOIN classes c ON e.class_id=c.id
        JOIN class_enrollments ce ON ce.class_id=e.class_id AND ce.user_id=%s
        LEFT JOIN exam_scores es ON es.exam_id=e.id AND es.user_id=%s
        ORDER BY e.exam_date DESC
    """, (tid,tid))
    return render_template('trainee/exams.html', exams=exams)

@app.route('/trainee/attendance')
@login_required
@role_required('trainee')
def trainee_attendance():
    tid = session['user_id']
    records = query("""
        SELECT a.*,c.name as class_name FROM attendance a JOIN classes c ON a.class_id=c.id
        WHERE a.user_id=%s ORDER BY a.date DESC
    """, (tid,))
    summary = query("""
        SELECT COUNT(*) as total, SUM(present) as present_count FROM attendance WHERE user_id=%s
    """, (tid,), one=True)
    return render_template('trainee/attendance.html', records=records, summary=summary)

@app.route('/trainee/announcements')
@login_required
@role_required('trainee')
def trainee_announcements():
    ann = query("""
        SELECT a.*,u.name as author FROM announcements a JOIN users u ON a.created_by=u.id
        WHERE a.target_role IN ('trainee','all') ORDER BY a.created_at DESC
    """)
    return render_template('trainee/announcements.html', announcements=ann)



@app.route('/trainee/progress')
@login_required
@role_required('trainee')
def trainee_progress():
    tid = session['user_id']
    marks_trend = query("""
    SELECT
        DATE_FORMAT(period_date, '%%b %%y') AS period,
        ROUND(AVG(marks), 0) AS avg
    FROM (
        SELECT
            marks,
            DATE_FORMAT(submitted_at, '%%y-%%m-01') AS period_date
        FROM submissions
        WHERE user_id=%s
          AND marks IS NOT NULL
    ) x
    GROUP BY period_date
    ORDER BY period_date
""", (tid,))
    subject_perf = query("""
        SELECT c.name as class_name, ROUND(AVG(s.marks),1) as avg_marks
        FROM submissions s JOIN assignments a ON s.assignment_id=a.id JOIN classes c ON a.class_id=c.id
        WHERE s.user_id=%s AND s.marks IS NOT NULL GROUP BY c.id
    """, (tid,))
    return render_template('trainee/progress.html', marks_trend=marks_trend, subject_perf=subject_perf)

@app.route('/trainee/extracurricular')
@login_required
@role_required('trainee')
def trainee_extracurricular():

    activities=query("""

    SELECT *

    FROM extracurricular

    WHERE student_id=%s

    ORDER BY created_at DESC

    """,(session["user_id"],))

    stats={

        "total":len(activities),

        "approved":sum(1 for i in activities if i["status"]=="Approved"),

        "pending":sum(1 for i in activities if i["status"]=="Pending")

    }

    return render_template(

        "trainee/extracurricular.html",

        activities=activities,

        stats=stats

    )

@app.route('/trainee/extracurricular/add', methods=["POST"])
@login_required
@role_required('trainee')
def trainee_add_extracurricular():

    certificate_name = None

    certificate = request.files.get("certificate")

    if certificate and certificate.filename:

        filename = secure_filename(certificate.filename)

        extension = filename.rsplit(".", 1)[1].lower()

        allowed = ["pdf", "png", "jpg", "jpeg"]

        if extension not in allowed:

            flash("Only PDF, JPG, JPEG and PNG files are allowed.", "error")

            return redirect(url_for("trainee_extracurricular"))

        filename = f"{uuid.uuid4().hex}.{extension}"

        upload_folder = os.path.join(
            app.static_folder,
            "uploads",
            "extracurricular"
        )

        os.makedirs(upload_folder, exist_ok=True)

        certificate.save(
            os.path.join(upload_folder, filename)
        )

        certificate_name = filename

    query("""

        INSERT INTO extracurricular(

            student_id,
            category,
            title,
            description,
            level,
            achievement,
            certificate,
            participation_date,
            status,
            ai_feedback

        )

        VALUES(

            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            'Pending',
            NULL

        )

    """,

    (

        session["user_id"],

        request.form["category"],

        request.form["title"],

        request.form["description"],

        request.form["level"],

        request.form["achievement"],

        certificate_name,

        request.form["participation_date"]

    ),

    commit=True)

    flash("Activity submitted successfully.", "success")

    return redirect(url_for("trainee_extracurricular"))


@app.route('/trainee/extracurricular/edit/<int:activity_id>', methods=['GET', 'POST'])
@login_required   # keep whatever decorators your other trainee routes use
def trainee_edit_extracurricular(activity_id):
    activity = ExtracurricularActivity.query.get_or_404(activity_id)

    # Optional: make sure trainees can only edit their own activity
    # if activity.trainee_id != current_user.id:
    #     abort(403)

    if request.method == 'POST':
        activity.title = request.form.get('title')
        activity.description = request.form.get('description')
        activity.date = request.form.get('date')
        # add/adjust fields to match your actual model

        db.session.commit()
        flash('Activity updated successfully.', 'success')
        return redirect(url_for('trainee_extracurricular'))

    return render_template('trainee/edit_extracurricular.html', activity=activity)



@app.route('/trainee/profile', methods=['GET','POST'])
@login_required
@role_required('trainee')
def trainee_profile():
    tid = session['user_id']
    if request.method == 'POST':
        name  = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        bio   = request.form.get('bio','').strip()
        query("UPDATE users SET name=%s,phone=%s,bio=%s WHERE id=%s",(name,phone,bio,tid), commit=True)
        session['name'] = name
        flash('Profile updated.','success')
    user = query("SELECT * FROM users WHERE id=%s",(tid,), one=True)
    return render_template('trainee/profile.html', user=user)

@app.route('/trainee/calendar')
@login_required
@role_required('trainee')
def trainee_calendar():
    tid = session['user_id']
    assignments = query("""
        SELECT a.title,a.due_date,'assignment' as type FROM assignments a
        JOIN class_enrollments ce ON ce.class_id=a.class_id AND ce.user_id=%s
        WHERE a.due_date IS NOT NULL
    """, (tid,))
    exams = query("""
        SELECT e.title,e.exam_date as due_date,'exam' as type FROM exams e
        JOIN class_enrollments ce ON ce.class_id=e.class_id AND ce.user_id=%s
        WHERE e.exam_date IS NOT NULL
    """, (tid,))
    events = list(assignments) + list(exams)
    return render_template('trainee/calendar.html', events=events)

@app.route('/trainee/settings', methods=['GET','POST'])
@login_required
@role_required('trainee')
def trainee_settings():
    if request.method == 'POST':
        name  = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        query("UPDATE users SET name=%s,phone=%s WHERE id=%s",(name,phone,session['user_id']), commit=True)
        session['name'] = name
        flash('Settings updated.','success')
    user = query("SELECT * FROM users WHERE id=%s",(session['user_id'],), one=True)
    return render_template('trainee/settings.html', user=user)




# ─── API (JSON) ───────────────────────────────────────────────────────────────

@app.route('/api/stats')
@login_required
def api_stats():
    role = session['role']
    if role == 'admin':
        return jsonify({
            'users': query("SELECT COUNT(*) as c FROM users WHERE is_active=1", one=True)['c'],
            'classes': query("SELECT COUNT(*) as c FROM classes WHERE is_active=1", one=True)['c'],
        })
    return jsonify({})

# ─── helpers ─────────────────────────────────────────────────────────────────

def log_activity(user_id, action, detail=''):
    try:
        query("INSERT INTO activity_log(user_id,action,detail,created_at) VALUES(%s,%s,%s,NOW())",
              (user_id, action, detail), commit=True)
    except Exception:
        pass

def create_notification(user_id, title, message, link=None):
    query("""
        INSERT INTO notifications
        (user_id, title, message, is_read, created_at)
        VALUES (%s, %s, %s, 0, NOW())
    """, (user_id, title, message), commit=True)

def notify_email(user_id, subject, body):
    """Send email only if the user hasn't opted out."""
    user = query("SELECT email, notify_email FROM users WHERE id=%s", (user_id,), one=True)
    if user and user.get('email') and user.get('notify_email', 1):
        try:
            send_mail(user['email'], subject, body)
        except Exception as e:
            print("Email failed:", e)

def send_mail(to, subject, body):
    msg = Message(
        subject=subject,
        recipients=[to],
        body=body,
        sender=app.config['MAIL_DEFAULT_SENDER']
    )
    mail.send(msg)

def notify_whatsapp(user_id, template_name, params=None):
    """Fetch user's phone and send a WhatsApp template message, respecting their preference."""
    user = query("SELECT phone, notify_whatsapp FROM users WHERE id=%s", (user_id,), one=True)
    if user and user.get('phone') and user.get('notify_whatsapp', 1):
        send_whatsapp_template(user['phone'], template_name, params=params or [])

@app.route('/api/class-students/<int:class_id>')
@login_required
def api_class_students(class_id):
    students = query("""
        SELECT u.id, u.name FROM users u
        JOIN class_enrollments ce ON ce.user_id=u.id
        WHERE ce.class_id=%s AND u.role='trainee' AND u.is_active=1
        ORDER BY u.name
    """, (class_id,))
    return jsonify(list(students))

    
# ─── WHATSAPP ATTENDANCE ──────────────────────────────────────────────────────

@app.route('/admin/attendance/send-link', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_send_attendance_link():
    classes = query("SELECT c.*, u.name as mentor_name FROM classes c LEFT JOIN users u ON c.mentor_id=u.id WHERE c.is_active=1")
    if request.method == 'POST':
        class_id  = request.form['class_id']
        section   = request.form.get('section', '').strip()
        period    = request.form.get('period', '1')
        date      = request.form.get('date', datetime.now().strftime('%%y-%m-%d'))
        # Build a signed token so only valid links work
        token = str(uuid.uuid4())
        query("""
            INSERT INTO attendance_tokens(token, class_id, section, period, date, created_by, created_at, used)
            VALUES(%s,%s,%s,%s,%s,%s,NOW(),0)
        """, (token, class_id, section, period, date, session['user_id']), commit=True)
        link = request.host_url + f"attendance/fill/{token}"
        flash(f'Link generated! Copy and send via WhatsApp: {link}', 'success')
        return render_template('admin/send_attendance_link.html',
                               classes=classes, link=link, token=token,now=datetime.now())
    return render_template('admin/send_attendance_link.html', 
                       classes=classes, link=None, now=datetime.now())


@app.route('/attendance/fill/<token>', methods=['GET', 'POST'])
def attendance_form(token):
    """Public form — no login required (accessible via WhatsApp link)."""
    rec = query("SELECT * FROM attendance_tokens WHERE token=%s", (token,), one=True)
    if not rec:
        return render_template('attendance_public_error.html', msg='Invalid link.')
    if rec['used']:
        return render_template('attendance_public_error.html', msg='This link has already been used.')
    cls  = query("SELECT * FROM classes WHERE id=%s", (rec['class_id'],), one=True)
    trainees = query("""
        SELECT u.id, u.name FROM users u
        JOIN class_enrollments ce ON ce.user_id=u.id
        WHERE ce.class_id=%s AND u.role='trainee' AND u.is_active=1
        ORDER BY u.name
    """, (rec['class_id'],))

    if request.method == 'POST':
        absent_ids  = request.form.getlist('absent_ids')   # list of user_ids
        mentor_name = request.form.get('mentor_name', '').strip()
        remarks     = request.form.get('remarks', '').strip()
        image_data  = request.form.get('image_data', '')   # base64 from canvas
        ai_result   = request.form.get('ai_result', '')    # JSON string from AI

        # Save each trainee's attendance
        for t in trainees:
            present = 0 if str(t['id']) in absent_ids else 1
            existing = query("""
                SELECT id FROM attendance
                WHERE user_id=%s AND class_id=%s AND date=%s
            """, (t['id'], rec['class_id'], rec['date']), one=True)
            if existing:
                query("UPDATE attendance SET present=%s WHERE id=%s",
                      (present, existing['id']), commit=True)
            else:
                query("""
                    INSERT INTO attendance(user_id, class_id, date, present, section, period, remarks)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)
                """, (t['id'], rec['class_id'], rec['date'], present,
                      rec['section'], rec['period'], remarks), commit=True)

        # Save image if uploaded
        if image_data:
            query("""
                INSERT INTO attendance_images(token, class_id, date, image_data, ai_result, mentor_name, created_at)
                VALUES(%s,%s,%s,%s,%s,%s,NOW())
            """, (token, rec['class_id'], rec['date'], image_data, ai_result, mentor_name), commit=True)

        # Mark token as used
        query("UPDATE attendance_tokens SET used=1 WHERE token=%s", (token,), commit=True)
        log_activity(0, 'attendance_submit', f'Token {token} used by {mentor_name}')
        return render_template('attendance_success.html', date=rec['date'], cls=cls)

    return render_template('attendance_form.html',
                           rec=rec, cls=cls, trainees=trainees)
@app.route('/api/analyze-attendance-image', methods=['POST'])
def analyze_attendance_image():
    from google import genai
    from google.genai import types
    import base64

    data = request.get_json()
    image_data = data.get('image_data', '')
    names = data.get('names', [])

    media_type = image_data.split(';')[0].split(':')[1]
    image_b64 = image_data.split(',')[1]

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                mime_type=media_type,
                                data=base64.b64decode(image_b64)
                            )
                        ),
                        types.Part(
                            text=f"""
Analyze this handwritten attendance sheet.

Students:
{', '.join(names)}
"""
                        )
                    ]
                )
            ]
        )

        return jsonify({"result": response.text})

    except Exception as e:
        return jsonify({"error": f"AI analysis failed: {str(e)}"}), 500
    

@app.route('/admin/attendance/submissions')
@login_required
@role_required('admin')
def admin_attendance_submissions():
    submissions = query("""
        SELECT at.*, c.name as class_name,
               (SELECT COUNT(*) FROM attendance a WHERE a.class_id=at.class_id AND a.date=at.date AND a.present=0) as absent_count,
               (SELECT COUNT(*) FROM attendance a WHERE a.class_id=at.class_id AND a.date=at.date) as total_count
        FROM attendance_tokens at
        JOIN classes c ON at.class_id=c.id
        WHERE at.used=1
        ORDER BY at.created_at DESC
    """)
    return render_template('admin/attendance_submissions.html', submissions=submissions)


@app.route('/admin/attendance/export/<int:class_id>')
@login_required
@role_required('admin')
def admin_export_attendance(class_id):
    fmt        = request.args.get('format', 'excel')
    date_from  = request.args.get('from', '')
    date_to    = request.args.get('to', '')
    cls        = query("SELECT * FROM classes WHERE id=%s", (class_id,), one=True)

    sql = """
        SELECT u.name, a.date, a.present, a.section, a.period, a.remarks
        FROM attendance a JOIN users u ON a.user_id=u.id
        WHERE a.class_id=%s
    """
    args = [class_id]
    if date_from:
        sql += " AND a.date >= %s"; args.append(date_from)
    if date_to:
        sql += " AND a.date <= %s"; args.append(date_to)
    sql += " ORDER BY a.date, u.name"
    records = query(sql, args)

    if fmt == 'excel':
        return _export_excel(records, cls)
    else:
        return _export_pdf(records, cls)


def _export_excel(records, cls):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Attendance"

    # Header styling
    header_fill = PatternFill("solid", fgColor="4F46E5")
    header_font = Font(color="FFFFFF", bold=True)
    headers = ['Student Name', 'Date', 'Status', 'Section', 'Period', 'Remarks']
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill  = header_fill
        cell.font  = header_font
        cell.alignment = Alignment(horizontal='center')

    for row_idx, r in enumerate(records, 2):
        ws.cell(row=row_idx, column=1, value=r['name'])
        ws.cell(row=row_idx, column=2, value=str(r['date']))
        status_cell = ws.cell(row=row_idx, column=3, value='Present' if r['present'] else 'Absent')
        if not r['present']:
            status_cell.font = Font(color="DC2626", bold=True)
        ws.cell(row=row_idx, column=4, value=r['section'] or '')
        ws.cell(row=row_idx, column=5, value=r['period'] or '')
        ws.cell(row=row_idx, column=6, value=r['remarks'] or '')

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 18

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"attendance_{cls['name'].replace(' ','_')}.xlsx"
    return send_file(buf, download_name=fname,
                     as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def _export_pdf(records, cls):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    elements.append(Paragraph(f"Attendance Report – {cls['name']}", styles['Title']))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%d %%b %%y %H:%M')}", styles['Normal']))

    data = [['Student Name', 'Date', 'Status', 'Section', 'Period']]
    for r in records:
        data.append([r['name'], str(r['date']),
                     'Present' if r['present'] else 'Absent',
                     r['section'] or '', str(r['period'] or '')])

    t = Table(data, colWidths=[140, 80, 70, 70, 60])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4F46E5')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F5F3FF')]),
        ('TEXTCOLOR', (2,1), (2,-1), colors.HexColor('#DC2626')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    fname = f"attendance_{cls['name'].replace(' ','_')}.pdf"
    return send_file(buf, download_name=fname,
                     as_attachment=True, mimetype='application/pdf')


@app.route('/admin/attendance/image/<int:img_id>')
@login_required
@role_required('admin')
def admin_view_attendance_image(img_id):
    img = query("SELECT * FROM attendance_images WHERE id=%s", (img_id,), one=True)
    return render_template('admin/view_attendance_image.html', img=img)

@app.route('/admin/risk-dashboard')
@login_required
@role_required('admin')
def admin_risk_dashboard():

    trainees = query("""
        SELECT id,name,email
        FROM users
        WHERE role='trainee'
        AND is_active=1
    """)

    risk_list = []

    sports_count = 0
    technical_count = 0
    leadership_count = 0
    communication_count = 0
    cultural_count = 0
    talented_count = 0

    for t in trainees:

        # Existing prediction
        data = get_student_risk_data(query, t['id'])

        # -----------------------------------------
        # Extracurricular
        # -----------------------------------------

        activities = query("""
            SELECT category
            FROM extracurricular
            WHERE student_id=%s
            AND status='Approved'
        """,(t['id'],))

        sports = 0
        technical = 0
        leadership = 0
        communication = 0
        cultural = 0

        for a in activities:

            cat = (a['category'] or "").lower()

            if cat == "sports":
                sports += 1

            elif cat == "technical":
                technical += 1

            elif cat == "leadership":
                leadership += 1

            elif cat == "communication":
                communication += 1

            elif cat == "cultural":
                cultural += 1

        # Dashboard Counts

        if sports:
            sports_count += 1

        if technical:
            technical_count += 1

        if leadership:
            leadership_count += 1

        if communication:
            communication_count += 1

        if cultural:
            cultural_count += 1

        # -----------------------------------------

        skill_score = (
            sports*20 +
            technical*20 +
            leadership*20 +
            communication*20 +
            cultural*20
        )

        if skill_score > 100:
            skill_score = 100

        if skill_score >= 70:
            talented_count += 1

        # -----------------------------------------
        # Top Skill
        # -----------------------------------------

        scores = {

            "Sports":sports,

            "Technical":technical,

            "Leadership":leadership,

            "Communication":communication,

            "Cultural":cultural

        }

            # -----------------------------------------
        # Top Skill
        # -----------------------------------------

        scores = {
            "Sports": sports,
            "Technical": technical,
            "Leadership": leadership,
            "Communication": communication,
            "Cultural": cultural
        }

        if max(scores.values()) == 0:

            top_skill = "Not Identified"
            strengths = "No extracurricular participation"
            weaknesses = "Sports, Technical, Leadership, Communication, Cultural"

            ai = "Student has no extracurricular participation. Encourage involvement in extracurricular activities."

        else:

            top_skill = max(scores, key=scores.get)

            strengths = ", ".join(
                [k for k, v in scores.items() if v > 0]
            )

            weaknesses = ", ".join(
                [k for k, v in scores.items() if v == 0]
            )

            if data["risk_label"] == "High Risk" and skill_score >= 70:

                ai = "Excellent extracurricular performance but poor academics. Provide academic mentoring while encouraging extracurricular excellence."

            elif data["risk_label"] == "High Risk":

                ai = "Immediate academic mentoring required."

            elif skill_score >= 70:

                ai = "Excellent extracurricular performance. Encourage competitions and leadership opportunities."

            else:

                ai = "Balanced performance. Continue improving academics and extracurricular activities."

        data["name"] = t["name"]
        data["email"] = t["email"]

        data["skill_score"] = skill_score
        data["top_skill"] = top_skill
        data["strengths"] = strengths
        data["weaknesses"] = weaknesses
        data["ai_recommendation"] = ai

        risk_list.append(data)

    risk_list.sort(
        key=lambda x: x["risk_score"],
        reverse=True
    )

    high_count = sum(
        1 for r in risk_list
        if r["risk_label"] == "High Risk"
    )

    medium_count = sum(
        1 for r in risk_list
        if r["risk_label"] == "Medium Risk"
    )

    low_count = sum(
        1 for r in risk_list
        if r["risk_label"] == "Low Risk"
    )

    return render_template(

        "admin/risk_dashboard.html",

        risk_list=risk_list,

        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,

        sports_count=sports_count,
        technical_count=technical_count,
        leadership_count=leadership_count,
        communication_count=communication_count,
        cultural_count=cultural_count,

        talented_count=talented_count

    )

@app.route('/trainee/extracurricular/delete/<int:activity_id>', methods=['POST'])
@login_required 
def trainee_delete_extracurricular(activity_id): 
    activity = ExtracurricularActivity.query.get_or_404(activity_id) 

    db.session.delete(activity)
    db.session.commit()
    
    flash('Activity deleted successfully.', 'success')
    return redirect(url_for('trainee_extracurricular'))

@app.route('/mentor/student-ai-report/<int:student_id>')
@login_required
@role_required('mentor')
def mentor_student_ai_report(student_id):
    student = query("SELECT id, name, email FROM users WHERE id=%s AND role='trainee'", (student_id,), one=True)
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('mentor_risk_dashboard'))

    risk_data = get_student_risk_data(query, student_id)
    ai_feedback = generate_ai_feedback(student['name'], risk_data)

    subject_strengths = query("""
        SELECT c.name as class_name, ROUND(AVG(s.marks),1) as avg_marks
        FROM submissions s
        JOIN assignments a ON s.assignment_id = a.id
        JOIN classes c ON a.class_id = c.id
        WHERE s.user_id=%s AND s.marks IS NOT NULL
        GROUP BY c.id
    """, (student_id,))

    suggestion = career_suggestion(risk_data, subject_strengths)

    return render_template('mentor/student_ai_report.html',
        student=student, risk_data=risk_data,
        ai_feedback=ai_feedback, suggestion=suggestion,
        subject_strengths=subject_strengths)


@app.route('/trainee/ai-feedback')
@login_required
@role_required('trainee')
def trainee_ai_feedback():
    tid = session['user_id']
    risk_data = get_student_risk_data(query, tid)
    ai_feedback = generate_ai_feedback(session['name'], risk_data)

    subject_strengths = query("""
        SELECT c.name as class_name, ROUND(AVG(s.marks),1) as avg_marks
        FROM submissions s
        JOIN assignments a ON s.assignment_id = a.id
        JOIN classes c ON a.class_id = c.id
        WHERE s.user_id=%s AND s.marks IS NOT NULL
        GROUP BY c.id
    """, (tid,))

    suggestion = career_suggestion(risk_data, subject_strengths)

    return render_template('trainee/ai_feedback.html',
        risk_data=risk_data, ai_feedback=ai_feedback,
        suggestion=suggestion, subject_strengths=subject_strengths)

@app.route('/mentor/generate-ai-feedback/<int:activity_id>', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_generate_ai_feedback(activity_id):
    activity = query("SELECT * FROM extracurricular WHERE id=%s", (activity_id,), one=True)

    if not activity:
        flash('Activity not found.', 'error')
        return redirect(url_for('mentor_extracurricular'))

    feedback_text = (
        f"{activity['student_name']} participated in \"{activity['title']}\" "
        f"under the {activity['category']} category at {activity['level']} level"
        + (f", achieving: {activity['achievement']}." if activity.get('achievement') else ".")
        + " This activity reflects strong initiative, teamwork and time-management skills, "
          "and is a valuable addition to their overall profile for placements and higher studies."
    )

    query(
        "UPDATE extracurricular SET ai_feedback=%s WHERE id=%s",
        (feedback_text, activity_id),
        commit=True
    )

    flash('AI feedback generated successfully.', 'success')
    return redirect(url_for('mentor_extracurricular'))

@app.route('/admin/delete-extracurricular/<int:activity_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_extracurricular(activity_id):
    activity = query(
        "SELECT * FROM extracurricular_activities WHERE id=%s",
        (activity_id,), one=True
    )
    if not activity:
        flash('Activity not found.', 'error')
        return redirect(url_for('admin_extracurricular'))

    # delete certificate file too, if you store one, before/after this
    query(
        "DELETE FROM extracurricular_activities WHERE id=%s",
        (activity_id,), commit=True
    )

    flash('Activity deleted successfully.', 'success')
    return redirect(url_for('admin_extracurricular'))


# ── Mentor edit/delete assignment ─────────────────────────────────────────────
@app.route('/mentor/assignments/edit/<int:aid>', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_edit_assignment(aid):
    title    = request.form['title'].strip()
    due_date = request.form.get('due_date') or None
    desc     = request.form.get('description', '').strip()
    query("UPDATE assignments SET title=%s, due_date=%s, description=%s WHERE id=%s",
          (title, due_date, desc, aid), commit=True)
    flash('Assignment updated.', 'success')
    return redirect(url_for('mentor_assignments'))

@app.route('/mentor/assignments/delete/<int:aid>', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_delete_assignment(aid):
    query("DELETE FROM submissions WHERE assignment_id=%s", (aid,), commit=True)
    query("DELETE FROM assignments WHERE id=%s", (aid,), commit=True)
    flash('Assignment deleted.', 'success')
    return redirect(url_for('mentor_assignments'))

# ── Mentor edit/delete task ───────────────────────────────────────────────────
@app.route('/mentor/tasks/edit/<int:tid>', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_edit_task(tid):
    title    = request.form['title'].strip()
    due_date = request.form.get('due_date') or None
    desc     = request.form.get('description', '').strip()
    query("UPDATE tasks SET title=%s, due_date=%s, description=%s WHERE id=%s",
          (title, due_date, desc, tid), commit=True)
    flash('Task updated.', 'success')
    return redirect(url_for('mentor_tasks'))

@app.route('/mentor/tasks/delete/<int:tid>', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_delete_task(tid):
    query("DELETE FROM task_submissions WHERE task_id=%s", (tid,), commit=True)
    query("DELETE FROM tasks WHERE id=%s", (tid,), commit=True)
    flash('Task deleted.', 'success')
    return redirect(url_for('mentor_tasks'))

# ── Admin exam edit/delete/scores ─────────────────────────────────────────────
@app.route('/admin/exams/edit/<int:exam_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_edit_exam(exam_id):
    title     = request.form['title'].strip()
    class_id  = request.form.get('class_id') or None
    exam_date = request.form.get('exam_date') or None
    max_marks = request.form.get('max_marks', 100)
    subject   = request.form.get('subject', '').strip()
    venue     = request.form.get('venue', '').strip()
    start_time= request.form.get('start_time') or None
    end_time  = request.form.get('end_time') or None
    instructions = request.form.get('instructions', '').strip()
    query("""
        UPDATE exams SET title=%s, class_id=%s, exam_date=%s, max_marks=%s,
        subject=%s, venue=%s, start_time=%s, end_time=%s, instructions=%s
        WHERE id=%s
    """, (title, class_id, exam_date, max_marks, subject, venue,
          start_time, end_time, instructions, exam_id), commit=True)
    flash('Exam updated.', 'success')
    return redirect(url_for('admin_exams'))

@app.route('/admin/exams/delete/<int:exam_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_exam(exam_id):
    query("DELETE FROM exam_scores WHERE exam_id=%s", (exam_id,), commit=True)
    query("DELETE FROM exams WHERE id=%s", (exam_id,), commit=True)
    flash('Exam deleted.', 'success')
    return redirect(url_for('admin_exams'))

@app.route('/admin/exams/<int:exam_id>/scores')
@login_required
@role_required('admin')
def admin_exam_scores(exam_id):
    exam = query("SELECT e.*, c.name as class_name FROM exams e LEFT JOIN classes c ON e.class_id=c.id WHERE e.id=%s", (exam_id,), one=True)
    if not exam:
        return jsonify({'success': False, 'message': 'Exam not found'}), 404
    scores = query("""
        SELECT u.id, u.name, es.marks, es.grade
        FROM users u
        JOIN class_enrollments ce ON ce.user_id=u.id
        LEFT JOIN exam_scores es ON es.exam_id=%s AND es.user_id=u.id
        WHERE ce.class_id=%s AND u.role='trainee' AND u.is_active=1
        ORDER BY u.name
    """, (exam_id, exam['class_id']))
    if exam.get('exam_date'):
        exam['exam_date'] = exam['exam_date'].strftime('%Y-%m-%d')
    return jsonify({'success': True, 'exam': exam, 'scores': scores})

@app.route('/admin/exams/<int:exam_id>/scores/save', methods=['POST'])
@login_required
@role_required('admin')
def admin_save_exam_scores(exam_id):
    exam = query("SELECT * FROM exams WHERE id=%s", (exam_id,), one=True)
    if not exam:
        flash('Exam not found.', 'error')
        return redirect(url_for('admin_exams'))
    for key, val in request.form.items():
        if key.startswith('marks_'):
            uid = int(key.split('_')[1])
            marks = val.strip()
            if marks == '':
                continue
            marks = float(marks)
            max_m = exam['max_marks']
            # Auto grade
            pct = (marks / max_m * 100) if max_m else 0
            grade = 'A+' if pct>=90 else 'A' if pct>=80 else 'B' if pct>=70 else 'C' if pct>=60 else 'D' if pct>=50 else 'F'
            existing = query("SELECT id FROM exam_scores WHERE exam_id=%s AND user_id=%s", (exam_id, uid), one=True)
            if existing:
                query("UPDATE exam_scores SET marks=%s, grade=%s WHERE exam_id=%s AND user_id=%s",
                      (marks, grade, exam_id, uid), commit=True)
            else:
                query("INSERT INTO exam_scores(exam_id, user_id, marks, grade) VALUES(%s,%s,%s,%s)",
                      (exam_id, uid, marks, grade), commit=True)
        flash('Scores saved successfully.', 'success')
    return redirect(url_for('admin_exams'))   

# ── Admin add exam updated with new fields ────────────────────────────────────
@app.route('/admin/exams/add', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_exam():
    title     = request.form['title'].strip()
    class_id  = request.form.get('class_id') or None
    exam_date = request.form.get('exam_date')
    max_marks = request.form.get('max_marks', 100)
    subject   = request.form.get('subject', '').strip()
    venue     = request.form.get('venue', '').strip()
    start_time= request.form.get('start_time') or None
    end_time  = request.form.get('end_time') or None
    instructions = request.form.get('instructions', '').strip()
    query("""
        INSERT INTO exams(title, class_id, exam_date, max_marks,
        subject, venue, start_time, end_time, instructions, created_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
    """, (title, class_id, exam_date, max_marks,
          subject or None, venue or None, start_time, end_time,
          instructions or None), commit=True)
    flash('Exam scheduled.', 'success')
    if class_id:
        notify.exam_timetable(int(class_id), title, exam_date)
    return redirect(url_for('admin_exams'))


if __name__ == '__main__':
        start_scheduler(notify)
        app.run(debug=True, port=5000)

