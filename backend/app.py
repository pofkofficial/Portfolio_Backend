import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv # New Import
from flask import Flask, request, jsonify, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq

# === Load Environment Variables ===
load_dotenv()

# === App Configuration ===
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')

CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# === Database Configuration ===
DB_PATH = 'messages.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS site_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT,
                visit_date DATE DEFAULT CURRENT_DATE
            );
            CREATE TABLE IF NOT EXISTS button_clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                button_name TEXT NOT NULL,
                click_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                technologies TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                image TEXT,
                link TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
init_db()

# === Auth Setup ===
login_manager = LoginManager(app)

class User(UserMixin):
    def __init__(self, id):
        self.id = id

# Pulling Admin credentials from ENV
ADMIN_DB = {
    "username": os.environ.get('ADMIN_USERNAME'),
    "password_hash": os.environ.get('ADMIN_PASSWORD_HASH') 
}

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

# === Public API Routes ===

@app.route('/api/projects', methods=['GET'])
def api_get_projects():
    category = request.args.get('category')
    query = 'SELECT * FROM projects'
    params = ()
    
    if category:
        query += ' WHERE category = ?'
        params = (category,)
    
    query += ' ORDER BY created_at DESC'
    
    with get_db() as conn:
        projects = conn.execute(query, params).fetchall()
    return jsonify([dict(p) for p in projects])

@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    data = request.get_json(silent=True) or request.form
    if not data.get('email') or not data.get('message'):
        return jsonify({'status': 'error', 'message': 'Required fields missing'}), 400
        
    try:
        name = data.get('name', 'Anonymous')
        email = data.get('email')
        message = data.get('message')
        subject = data.get('subject', 'System Inquiry') 

        with get_db() as conn:
            conn.execute('''INSERT INTO messages (name, email, subject, message)
                            VALUES (?, ?, ?, ?)''', 
                         (name, email, subject, message))
            conn.commit()
            
        return jsonify({'status': 'success', 'message': 'Message sent to the neural grid!'}), 201
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'Database insertion failed'}), 500

@app.route('/api/admin/messages/<int:id>', methods=['DELETE', 'OPTIONS'])
def delete_message(id):
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        with get_db() as conn:
            conn.execute('DELETE FROM messages WHERE id = ?', (id,))
            conn.commit()
        return jsonify({'status': 'success', 'message': 'Signal purged'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/visit_stats', methods=['GET'])
def get_public_stats():
    with get_db() as conn:
        count = conn.execute('SELECT COUNT(*) FROM site_visits').fetchone()[0]
    return jsonify({'total_visits': count})

@app.route('/api/track_visit', methods=['POST'])
def api_track_visit():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    with get_db() as conn:
        exists = conn.execute(
            'SELECT id FROM site_visits WHERE ip_address = ? AND visit_date = CURRENT_DATE', 
            (ip,)
        ).fetchone()
        if not exists:
            conn.execute('INSERT INTO site_visits (ip_address, visit_date) VALUES (?, CURRENT_DATE)', (ip,))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'New visit logged.'})
    return jsonify({'status': 'success', 'message': 'Returning visitor.'})

@app.route('/api/track_click', methods=['POST'])
def api_track_click():
    data = request.get_json(silent=True)
    button_name = data.get('button_name') if data else None
    if button_name:
        with get_db() as conn:
            conn.execute('INSERT INTO button_clicks (button_name) VALUES (?)', (button_name,))
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400

# === Admin API Routes ===

@app.route('/api/admin/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "No data received"}), 400
    username = data.get('username')
    password = data.get('password')
    if username == ADMIN_DB["username"] and check_password_hash(ADMIN_DB["password_hash"], password):
        user = User(1)
        login_user(user, remember=True)
        return jsonify({"success": True, "message": "Welcome back, Kwesi"})
    return jsonify({"success": False, "message": "Invalid credentials"}), 401

@app.route('/api/logout')
@login_required
def api_logout():
    logout_user()
    return jsonify({"success": True})

@app.route('/api/admin/metrics', methods=['GET'])
@login_required
def api_metrics():
    with get_db() as conn:
        msg_count = conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
        visit_count = conn.execute('SELECT COUNT(*) FROM site_visits').fetchone()[0]
        monthly_v = conn.execute("SELECT strftime('%Y-%m', visit_date), COUNT(*) FROM site_visits GROUP BY 1").fetchall()
        cat_counts = conn.execute('SELECT category, COUNT(*) FROM projects GROUP BY category').fetchall()
        projects_query = conn.execute('SELECT * FROM projects ORDER BY id DESC').fetchall()
        all_projects = [dict(p) for p in projects_query]
        messages = conn.execute('SELECT * FROM messages ORDER BY created_at DESC LIMIT 50').fetchall()
    return jsonify({
        'total_messages': msg_count,
        'total_visits': visit_count,
        'monthly_visits': [list(v) for v in monthly_v],
        'category_counts': dict(cat_counts),
        'recent_messages': [dict(m) for m in messages],
        'all_projects': all_projects
    })

@app.route('/api/admin/projects', methods=['POST'])
@login_required
def api_manage_project():
    pid = request.form.get('id')
    title = request.form.get('title')
    desc = request.form.get('description')
    cat = request.form.get('category')
    link = request.form.get('link')
    tech = request.form.get('technologies')
    image_file = request.files.get('image')
    image_url = request.form.get('existing_image')
    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        upload_path = os.path.join('static', 'uploads')
        os.makedirs(upload_path, exist_ok=True)
        image_file.save(os.path.join(upload_path, filename))
        image_url = f'/static/uploads/{filename}'
    with get_db() as conn:
        if pid:
            conn.execute('UPDATE projects SET title=?, description=?, category=?, image=?, link=?, technologies=? WHERE id=?',
                         (title, desc, cat, image_url, link, tech, pid))
        else:
            conn.execute('INSERT INTO projects (title, description, category, image, link, technologies) VALUES (?,?,?,?,?,?)',
                         (title, desc, cat, image_url, link, tech))
    return jsonify({"status": "success"})

@app.route('/api/admin/projects/<int:id>', methods=['DELETE', 'OPTIONS'])
@login_required 
def delete_project(id):
    if request.method == 'OPTIONS': return jsonify({'ok': True}), 200
    try:
        with get_db() as conn:
            conn.execute('DELETE FROM projects WHERE id = ?', (id,))
            conn.commit()
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/admin/projects/<int:id>', methods=['PUT', 'OPTIONS'])
@login_required
def update_project(id):
    if request.method == 'OPTIONS': return jsonify({'status': 'ok'}), 200
    title = request.form.get('title')
    category = request.form.get('category')
    description = request.form.get('description')
    link = request.form.get('link')
    technologies = request.form.get('technologies')
    image_file = request.files.get('image')
    with get_db() as conn:
        if image_file:
            filename = secure_filename(image_file.filename)
            upload_path = os.path.join('static', 'uploads')
            image_file.save(os.path.join(upload_path, filename))
            image_path = f'/static/uploads/{filename}'
            conn.execute('''UPDATE projects SET title=?, category=?, description=?, link=?, image=?, technologies=? WHERE id=?''', 
                         (title, category, description, link, image_path, technologies, id))
        else:
            conn.execute('''UPDATE projects SET title=?, category=?, description=?, link=?, technologies=? WHERE id=?''', 
                         (title, category, description, link, technologies, id))
        conn.commit()
    return jsonify({"message": "Protocol updated successfully"}), 200

@app.route('/download_cv')
def download_cv():
    return send_from_directory('docs', 'Kwesi_Coder_CV.pdf', as_attachment=True)


#-----------------------------AI AGENT SETUP-----------------------------
chat_sessions = {}

# --- HELPER: DATA AGGREGATOR ---
def get_neural_grid_context():
    try:
        with get_db() as conn:
            # 1. Fetch site metrics
            visit_count = conn.execute('SELECT COUNT(*) FROM site_visits').fetchone()[0]
            
            # 2. Fetch projects with all necessary columns for AI reasoning
            # Make sure your 'projects' table has a 'technologies' or 'tags' column
            query = "SELECT title, category, description, technologies, link FROM projects"
            projects = conn.execute(query).fetchall()
            
            # 3. Build a high-fidelity string for the LLM
            project_list = []
            for p in projects:
                # We combine title, category, tech, and info into a single line per project
                # This helps the AI use 'internal scanning' to find keywords like "Django"
                entry = (
                    f"| PROJECT: {p['title']} "
                    f"| CATEGORY: {p['category']} "
                    f"| TECH: {p['technologies']} "
                    f"| INFO: {p['description']} "
                    f"| LINK: {p['link']}"
                )
                project_list.append(entry)
            
            # 4. Final summary construction
            if project_list:
                project_summary = "\n".join(project_list)
            else:
                project_summary = "Registry is currently empty. No projects found."
                
            return visit_count, project_summary

    except Exception as e:
        # Log the error to your console for debugging
        print(f"DATABASE_READ_ERROR: {e}")
        return 0, "Neural Registry is offline. Connection to database failed."

# --- THE AGENT ROUTE ---
client = Groq(api_key=os.environ.get('GROQ_API_KEY'))

@app.route('/api/agent/chat', methods=['POST', 'OPTIONS'])
def ai_agent_chat():
    if request.method == 'OPTIONS':
        return jsonify({"status": "ok"}), 200
    
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        session_id = request.headers.get('X-Forwarded-For', request.remote_addr)

        if not user_message:
            return jsonify({"status": "error", "message": "No signal detected"}), 400

        visit_total, project_data = get_neural_grid_context()

        if session_id not in chat_sessions:
            chat_sessions[session_id] = []
        
        history = chat_sessions[session_id][-10:] 

        # --- UPDATED SYSTEM PROMPT ---
        system_prompt = {
            "role": "system",
            "content": (
                "You are Akosua, the Neural Proxy for KwesiCoder a.k.a Prince Fabrice Kwesi Opoku. You are currently on his portfolio website."
                "Identity: Kwesi is a Systems Architect/Software Engineer."
                "Kwesi's Stack: Django, Python, React, Flask, Node.js."
                "Personality: Technical, sleek, brief, witty and professional."
                f"LIVE REGISTRY (Use ONLY these projects): \n{project_data}\n\n"
                f"Live Stats: {visit_total} visits logged. Registry: {project_data}. "

                "BIO RESPONSE: "
                "If asked about Kwesi's background or bio, summarize his expertise in 2-3 sentences "
                "and conclude with: 'You can refer to the **Bio** section.' "

                "SOCIALS & LINKS: "
                "- LinkedIn: linkedin.com/in/pofkofficial " # Update these with your real links
                "- GitHub: github.com/pofkofficial "
                "- Email: pofkofficial@gmail.com "
                
                "PERSONALITY: Technical, sleek, and high-fidelity. "
                
                "STRICT CONSTRAINTS: "
                "1. HALT HALLUCINATIONS: Never mention a project that is not in the 'LIVE REGISTRY' above. "
                "2. TECH MATCHING: If a user asks for a particular stack or technology in a projects, scan the descriptions in the Registry for that keyword. "
                "3. Use [SCROLL_PROJECTS] when listing work. "
                "4. Use [SCROLL_CONTACT] ONLY when a user asks for contact or socials. "
                "5. Use [SCROLL_ABOUT] to scroll to the bio section ONLY when a user ask about Kwesi"
                "6. Formatting: Use **bold** for project titles."
                "7. Use [SAVE_MESSAGE] ONLY after collecting Name, Email, and Message. "
                "8. Pricing: Respond with: 'Consultation required for architectural scope. I'll notify Kwesi to review the logs.' "

                "AVAILABILITY PROTOCOL: "
                "If a user asks about Kwesi's availability for roles or freelance work: "
                "1. State that Kwesi is open to high-impact opportunities but requires project details first. "
                "2. Ask the user to provide: Project Scope, Timeline, and their Company Name. "
                "3. Tell them: 'Provide these details here, and I will ensure Kwesi reviews them immediately.' "
                "4. Use [SCROLL_CONTACT] to guide them to the form if they prefer to send a formal email."
            )
        }

        messages = [system_prompt] + history + [{"role": "user", "content": user_message}]

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.2, # DROPPED temperature further to stop hallucinations
            max_tokens=500
        )

        ai_response = completion.choices[0].message.content
        chat_sessions[session_id].append({"role": "user", "content": user_message})
        chat_sessions[session_id].append({"role": "assistant", "content": ai_response})

        return jsonify({"status": "success", "reply": ai_response})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    

'''client = genai.Client(api_key="AIzaSyC488SIhva4a4AEwLc7dWt_662KpGEHgZ8")

@app.route('/api/agent/chat', methods=['POST', 'OPTIONS'])
def ai_agent_chat():
    if request.method == 'OPTIONS':
        return jsonify({"status": "ok"}), 200
    
    data = request.get_json()
    user_message = data.get('message')
    
    # Clean system instruction
    system_instruction = "You are Akosua, the Neural Interface for KwesiCoder. Kwesi is a Systems Architect and IT student specializing in Python, React, and Flask. Answer questions about his expertise confidently and briefly."
    
    try:
        # Change: Using 'gemini-1.5-flash' (latest stable ID)
        # Change: Use content as a list for better parsing
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            config={'system_instruction': system_instruction},
            contents=[user_message] 
        )
        
        # Ensure we check for text before returning
        if response.text:
            return jsonify({"status": "success", "reply": response.text})
        else:
            return jsonify({"status": "error", "message": "Empty response from AI"}), 500

    except Exception as e:
        print(f"🔥 Detailed Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500'''


if __name__ == '__main__':
    app.run(debug=True, port=5000)
