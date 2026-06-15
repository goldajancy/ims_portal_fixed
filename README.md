# IMS Portal – Setup Guide

A full-stack Integrated Management System built with Flask (Python), MySQL, and HTML/CSS/JS.

---

## Features
- **Login / Register / Forgot Password (OTP via Email)**
- **Admin Dashboard** – Users, Classes, Assignments, Attendance, Exams, Announcements, Reports, System Logs, Settings
- **Mentor Dashboard** – My Trainees, Tasks, Assignments, Submissions (with grading), Lectures, Exams, Attendance, Analytics, Announcements, Messages, Calendar, Question Bank, Office Hours, Notes, Settings
- **Trainee Dashboard** – My Assignments (submit), My Tasks, Lectures, Exams & Results, Attendance, Calendar, Announcements, Messages, Bookmarks, Progress Charts, Profile, Settings

---

## Requirements
- Python 3.8+
- MySQL 5.7+ or MariaDB 10.3+

---

## Setup Steps

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Create the database
```bash
mysql -u root -p -e "CREATE DATABASE ims_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p ims_db < schema.sql
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env with your MySQL credentials and email SMTP settings
```

### 4. Configure Email (for OTP)
In `.env`, set:
```
MAIL_USERNAME=your_gmail@gmail.com
MAIL_PASSWORD=your_gmail_app_password   # Use Gmail App Password (not your real password)
```
To get a Gmail App Password: Google Account → Security → 2-Step Verification → App Passwords

> **Demo mode**: If email is not configured, the OTP will be shown in a flash message on screen.

### 5. Run the app
```bash
python app.py
```

Open: http://localhost:5000

---

## First-time Use

1. Go to http://localhost:5000/register
2. Create an **Admin** account
3. Log in as Admin
4. Create **Classes** (Admin → Classes)
5. Register **Mentor** accounts (via Register page or Admin → Add User)
6. Assign mentors to classes
7. Register **Trainee** accounts and enroll them in classes (via MySQL or Admin panel)
8. Mentors can now post tasks/assignments; Trainees can submit

---

## Enrolling Trainees in Classes (direct SQL)
```sql
INSERT INTO class_enrollments (class_id, user_id) VALUES (1, 3);
```
Or add an enrollment UI via the Admin → Classes page.

---

## Project Structure
```
ims_app/
├── app.py                  ← Main Flask application
├── schema.sql              ← Database schema
├── requirements.txt
├── .env.example            ← Copy to .env and configure
├── static/
│   ├── css/style.css       ← All styles
│   └── js/main.js          ← Frontend JS
└── templates/
    ├── base.html           ← Base layout
    ├── macros.html         ← Sidebar, topbar, flash macros
    ├── login.html
    ├── register.html
    ├── forgot_password.html
    ├── verify_otp.html
    ├── reset_password.html
    ├── admin/              ← All admin templates
    ├── mentor/             ← All mentor templates
    └── trainee/            ← All trainee templates
```
