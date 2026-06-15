import os
import random
import string
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_mail import Mail, Message
from flask_bcrypt import Bcrypt
import pymysql
from dotenv import load_dotenv
from datetime import datetime


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'ims-super-secret-key-2025')

# ── Mail Config ──────────────────────────────────────────────────────────────
app.config['MAIL_SERVER']   = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT']     = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']  = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'aruljose1101974@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'nnbu vlba vhmk xvkz')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME', 'noreply@ims.com')

mail  = Mail(app)
bcrypt = Bcrypt(app)

# ── DB ────────────────────────────────────────────────────────────────────────
DB_CFG = dict(
    host     = os.getenv('DB_HOST',   'localhost'),
    user     = os.getenv('DB_USER',   'root'),
    password = os.getenv('DB_PASS',   'Avj#2603'),
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
            "INSERT INTO users (name,email,phone,role,password_hash,is_active,created_at) VALUES(%s,%s,%s,%s,%s,1,NOW())",
            (name, email, phone, role, pw_hash), commit=True
        )
        # Send welcome email (best-effort)
        try:
            send_mail(email, f"Welcome to IMS, {name}!",
                      f"Your account has been created successfully.\nRole: {role.capitalize()}\nLogin: {email}")
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
        # For demo: expose OTP in flash if mail not configured
        flash(f'[DEMO – configure SMTP to send real email] OTP: {otp}', 'info')
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
        return redirect(url_for('admin_dashboard'))
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
    return render_template('admin/classes.html', classes=classes, mentors=mentors)

@app.route('/admin/classes/add', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_class():
    name      = request.form['name'].strip()
    mentor_id = request.form.get('mentor_id') or None
    desc      = request.form.get('description','').strip()
    query("INSERT INTO classes(name,mentor_id,description,is_active,created_at) VALUES(%s,%s,%s,1,NOW())",
          (name, mentor_id, desc), commit=True)
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

@app.route('/admin/exams/add', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_exam():
    title    = request.form['title'].strip()
    class_id = request.form.get('class_id') or None
    exam_date= request.form.get('exam_date')
    max_marks= request.form.get('max_marks', 100)
    query("INSERT INTO exams(title,class_id,exam_date,max_marks,created_at) VALUES(%s,%s,%s,%s,NOW())",
          (title, class_id, exam_date, max_marks), commit=True)
    flash('Exam scheduled.','success')
    return redirect(url_for('admin_exams'))

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
    return render_template('admin/reports.html', perf=perf)

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
          (title,class_id,desc,due_date,session['user_id']), commit=True)
    flash('Task created.','success')
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
    flash('Assignment created.','success')
    return redirect(url_for('mentor_assignments'))

@app.route('/mentor/submissions')
@login_required
@role_required('mentor')
def mentor_submissions():
    mid = session['user_id']
    classes = query("SELECT id FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    cids = [c['id'] for c in classes] or [0]
    fmt = ','.join(['%s']*len(cids))
    subs = query(f"""
        SELECT s.*,u.name as trainee_name,a.title as assignment_title,c.name as class_name
        FROM submissions s
        JOIN users u ON s.user_id=u.id
        JOIN assignments a ON s.assignment_id=a.id
        JOIN classes c ON a.class_id=c.id
        WHERE a.class_id IN ({fmt}) ORDER BY s.submitted_at DESC
    """, cids)
    return render_template('mentor/submissions.html', submissions=subs)

@app.route('/mentor/submissions/grade/<int:sid>', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_grade(sid):
    marks    = request.form.get('marks')
    feedback = request.form.get('feedback','').strip()
    query("UPDATE submissions SET marks=%s,feedback=%s WHERE id=%s",(marks,feedback,sid), commit=True)
    flash('Marks updated.','success')
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

@app.route('/mentor/lectures/add', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_add_lecture():
    title    = request.form['title'].strip()
    class_id = request.form['class_id']
    url_link = request.form.get('url','').strip()
    desc     = request.form.get('description','').strip()
    query("INSERT INTO lectures(title,class_id,url,description,created_by,created_at) VALUES(%s,%s,%s,%s,%s,NOW())",
          (title,class_id,url_link,desc,session['user_id']), commit=True)
    flash('Lecture uploaded.','success')
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
        return redirect(url_for('mentor_announcements'))
    ann = query("""
        SELECT a.*,u.name as author FROM announcements a JOIN users u ON a.created_by=u.id
        WHERE a.target_role IN ('trainee','mentor','all') OR a.created_by=%s
        ORDER BY a.created_at DESC
    """, (session['user_id'],))
    return render_template('mentor/announcements.html', announcements=ann)

@app.route('/mentor/messages')
@login_required
@role_required('mentor')
def mentor_messages():
    msgs = query("""
        SELECT m.*,u.name as sender_name FROM messages m
        JOIN users u ON m.sender_id=u.id
        WHERE m.receiver_id=%s ORDER BY m.created_at DESC LIMIT 30
    """, (session['user_id'],))
    return render_template('mentor/messages.html', messages=msgs)

@app.route('/mentor/messages/send', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_send_message():
    receiver_id = request.form['receiver_id']
    content     = request.form['content'].strip()
    query("INSERT INTO messages(sender_id,receiver_id,content,created_at) VALUES(%s,%s,%s,NOW())",
          (session['user_id'],receiver_id,content), commit=True)
    flash('Message sent.','success')
    return redirect(url_for('mentor_messages'))

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

@app.route('/mentor/office-hours')
@login_required
@role_required('mentor')
def mentor_office_hours():
    mid = session['user_id']
    slots = query("SELECT oh.*,u.name as trainee_name FROM office_hours oh LEFT JOIN users u ON oh.booked_by=u.id WHERE oh.mentor_id=%s ORDER BY oh.slot_time", (mid,))
    return render_template('mentor/office_hours.html', slots=slots)

@app.route('/mentor/office-hours/add', methods=['POST'])
@login_required
@role_required('mentor')
def mentor_add_office_hour():
    slot_time = request.form['slot_time']
    notes     = request.form.get('notes','').strip()
    query("INSERT INTO office_hours(mentor_id,slot_time,notes,is_booked) VALUES(%s,%s,%s,0)",
          (session['user_id'],slot_time,notes), commit=True)
    flash('Office hour slot added.','success')
    return redirect(url_for('mentor_office_hours'))

@app.route('/mentor/notes', methods=['GET','POST'])
@login_required
@role_required('mentor')
def mentor_notes():
    mid = session['user_id']
    if request.method == 'POST':
        trainee_id = request.form['trainee_id']
        note       = request.form['note'].strip()
        query("INSERT INTO mentor_notes(mentor_id,trainee_id,note,created_at) VALUES(%s,%s,%s,NOW())",
              (mid,trainee_id,note), commit=True)
        flash('Note saved.','success')
        return redirect(url_for('mentor_notes'))
    classes = query("SELECT id FROM classes WHERE mentor_id=%s AND is_active=1",(mid,))
    cids = [c['id'] for c in classes] or [0]
    fmt = ','.join(['%s']*len(cids))
    trainees = query(f"SELECT DISTINCT u.id,u.name FROM users u JOIN class_enrollments ce ON ce.user_id=u.id WHERE ce.class_id IN ({fmt}) AND u.role='trainee'", cids)
    notes    = query("""
        SELECT mn.*,u.name as trainee_name FROM mentor_notes mn JOIN users u ON mn.trainee_id=u.id
        WHERE mn.mentor_id=%s ORDER BY mn.created_at DESC
    """, (mid,))
    return render_template('mentor/notes.html', trainees=trainees, notes=notes)

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
        DATE_FORMAT(MIN(s.submitted_at), '%%b') AS mon,
        ROUND(AVG(s.marks), 0) AS avg
    FROM submissions s
    WHERE s.user_id = %s
      AND s.marks IS NOT NULL
    GROUP BY YEAR(s.submitted_at), MONTH(s.submitted_at)
    ORDER BY MIN(s.submitted_at)
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
    existing = query("SELECT id FROM submissions WHERE assignment_id=%s AND user_id=%s",(aid,tid), one=True)
    if not existing:
        query("INSERT INTO submissions(assignment_id,user_id,content,link,submitted_at) VALUES(%s,%s,%s,%s,NOW())",
              (aid,tid,content,link), commit=True)
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
    existing = query("SELECT id FROM task_submissions WHERE task_id=%s AND user_id=%s",(tid_,tid), one=True)
    if not existing:
        query("INSERT INTO task_submissions(task_id,user_id,content,submitted_at) VALUES(%s,%s,%s,NOW())",
              (tid_,tid,content), commit=True)
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

@app.route('/trainee/messages', methods=['GET','POST'])
@login_required
@role_required('trainee')
def trainee_messages():
    tid = session['user_id']
    if request.method == 'POST':
        receiver_id = request.form['receiver_id']
        content     = request.form['content'].strip()
        query("INSERT INTO messages(sender_id,receiver_id,content,created_at) VALUES(%s,%s,%s,NOW())",
              (tid,receiver_id,content), commit=True)
        flash('Message sent.','success')
        return redirect(url_for('trainee_messages'))
    msgs    = query("SELECT m.*,u.name as sender_name FROM messages m JOIN users u ON m.sender_id=u.id WHERE m.receiver_id=%s ORDER BY m.created_at DESC LIMIT 20", (tid,))
    mentors = query("""
        SELECT DISTINCT u.id,u.name FROM users u
        JOIN classes c ON c.mentor_id=u.id
        JOIN class_enrollments ce ON ce.class_id=c.id
        WHERE ce.user_id=%s
    """, (tid,))
    return render_template('trainee/messages.html', messages=msgs, mentors=mentors)

@app.route('/trainee/progress')
@login_required
@role_required('trainee')
def trainee_progress():
    tid = session['user_id']
    marks_trend = query("""
    SELECT
        DATE_FORMAT(period_date,'%%b %%Y') AS period,
        ROUND(AVG(marks),0) AS avg
    FROM (
        SELECT
            marks,
            DATE_FORMAT(submitted_at,'%%Y-%%m-01') AS period_date
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

@app.route('/trainee/bookmarks', methods=['GET','POST'])
@login_required
@role_required('trainee')
def trainee_bookmarks():
    tid = session['user_id']
    if request.method == 'POST':
        title = request.form['title'].strip()
        url_  = request.form['url'].strip()
        note  = request.form.get('note','').strip()
        query("INSERT INTO bookmarks(user_id,title,url,note,created_at) VALUES(%s,%s,%s,%s,NOW())",
              (tid,title,url_,note), commit=True)
        flash('Bookmark saved.','success')
        return redirect(url_for('trainee_bookmarks'))
    bookmarks = query("SELECT * FROM bookmarks WHERE user_id=%s ORDER BY created_at DESC",(tid,))
    return render_template('trainee/bookmarks.html', bookmarks=bookmarks)

@app.route('/trainee/bookmarks/delete/<int:bid>', methods=['POST'])
@login_required
@role_required('trainee')
def trainee_delete_bookmark(bid):
    query("DELETE FROM bookmarks WHERE id=%s AND user_id=%s",(bid,session['user_id']), commit=True)
    flash('Bookmark removed.','success')
    return redirect(url_for('trainee_bookmarks'))

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

def send_mail(to, subject, body):
    msg = Message(subject, recipients=[to], body=body)
    mail.send(msg)

if __name__ == '__main__':
    app.run(debug=True, port=5000)

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
