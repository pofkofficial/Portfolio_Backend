import os
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from groq import Groq
import psycopg2
from psycopg2.extras import RealDictCursor

# === Load Environment Variables ===
load_dotenv()

# === App Configuration ===
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET')
app.config.update(
    SESSION_COOKIE_SECURE=True,     # Must be True for HTTPS (Vercel)
    SESSION_COOKIE_SAMESITE='None', # Required for cross-site cookie sharing
    SESSION_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=True,
    REMEMBER_COOKIE_SAMESITE='None'
)

CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# === Database Configuration ===
DB_URL = os.environ.get('DATABASE_URL')

def get_db():
    # Connects to Supabase PostgreSQL
    conn = psycopg2.connect(DB_URL)
    return conn

def init_db():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS site_visits (
                        id SERIAL PRIMARY KEY,
                        ip_address TEXT UNIQUE,
                        visit_date DATE DEFAULT CURRENT_DATE
                    );
                    CREATE TABLE IF NOT EXISTS button_clicks (
                        id SERIAL PRIMARY KEY,
                        button_name TEXT NOT NULL,
                        click_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS projects (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        technologies TEXT NOT NULL,
                        description TEXT NOT NULL,
                        category TEXT NOT NULL,
                        image TEXT,
                        link TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS admin (
                    id SERIAL PRIMARY KEY,
                    user_name TEXT UNIQUE NOT NULL,
                    pwd_hash TEXT NOT NULL
                    );
                ''')
            conn.commit()
            print("Neural Registry Initialized on Supabase.")
    except Exception as e:
        print(f"Database Migration Error: {e}")

init_db()

# === Auth Setup ===
login_manager = LoginManager(app)

class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

# === Public API Routes ===

@app.route('/api/projects', methods=['GET'])
def api_get_projects():
    category = request.args.get('category')
    query = 'SELECT * FROM projects'
    params = []
    
    if category:
        query += ' WHERE category = %s'
        params.append(category)
    
    query += ' ORDER BY created_at DESC'
    
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            projects = cur.fetchall()
    return jsonify(projects)

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
            with conn.cursor() as cur:
                cur.execute('''INSERT INTO messages (name, email, subject, message)
                                VALUES (%s, %s, %s, %s)''', 
                             (name, email, subject, message))
            conn.commit()
        return jsonify({'status': 'success', 'message': 'Message sent to the neural grid!'}), 201
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/admin/messages/<int:id>', methods=['DELETE', 'OPTIONS'])
def delete_message(id):
    if request.method == 'OPTIONS': return jsonify({'status': 'ok'}), 200
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM messages WHERE id = %s', (id,))
            conn.commit()
        return jsonify({'status': 'success', 'message': 'Signal purged'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/visit_stats', methods=['GET'])
def get_public_stats():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM site_visits')
                count = cur.fetchone()[0]
        return jsonify({'total_visitors': count})
    except:
        return jsonify({'total_visitors': 0})


@app.route('/api/track_visit', methods=['POST'])
def api_track_visit():
    # Get the user's IP
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0]

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # 'ON CONFLICT DO NOTHING' turns off the error if the IP exists
                cur.execute('''
                    INSERT INTO site_visits (ip_address) 
                    VALUES (%s) 
                    ON CONFLICT (ip_address) DO NOTHING
                ''', (ip,))
                conn.commit()
        
        # We return success regardless because if it didn't insert, 
        # it's because they are already a known visitor.
        return jsonify({'status': 'success', 'message': 'Identity logged to neural grid.'})
    except Exception as e:
        print(f"Tracking Error: {e}")
        return jsonify({'status': 'error'}), 500




@app.route('/api/track_click', methods=['POST'])
def api_track_click():
    data = request.get_json(silent=True)
    button_name = data.get('button_name') if data else None
    if button_name:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute('INSERT INTO button_clicks (button_name) VALUES (%s)', (button_name,))
            conn.commit()
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400


# === Admin API Routes ===

@app.route('/api/admin/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True)
    if not data: 
        return jsonify({"success": False, "message": "No signal detected"}), 400
    
    username = data.get('username')
    password = data.get('password')

    try:
        admin_user = None
        with get_db() as conn:
            # Using RealDictCursor allows admin_user['id'] syntax
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT * FROM admin WHERE user_name = %s', (username,))
                admin_user = cur.fetchone()

        # Debug: See if the user was even found
        if not admin_user:
            print(f"Login failed: User '{username}' not found in database.")
            return jsonify({"success": False, "message": "Invalid credentials"}), 401

        # Check password hash
        if check_password_hash(admin_user['pwd_hash'], password):
            # 1. Create user object
            user = User(admin_user['id'])
            
            # 2. Log them in (This requires app.secret_key to be set!)
            login_user(user, remember=True)
            
            return jsonify({"success": True, "message": f"Welcome back, {username}"})
        
        print(f"Login failed: Password mismatch for '{username}'.")
        return jsonify({"success": False, "message": "Invalid credentials"}), 401

    except Exception as e:
        # This will print the full error to your VS Code terminal
        import traceback
        traceback.print_exc() 
        return jsonify({"success": False, "message": f"Server Error: {str(e)}"}), 500
    

@app.route('/api/logout')
@login_required
def api_logout():
    logout_user()
    return jsonify({"success": True})

@app.route('/api/admin/metrics', methods=['GET'])
@login_required
def api_metrics():
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT COUNT(*) as count FROM messages')
            msg_count = cur.fetchone()['count']
            
            cur.execute('SELECT COUNT(*) as count FROM site_visits')
            visit_count = cur.fetchone()['count']
            
            # strftime is SQLite; PostgreSQL uses TO_CHAR
            cur.execute("SELECT TO_CHAR(visit_date, 'YYYY-MM') as month, COUNT(*) FROM site_visits GROUP BY 1")
            monthly_v = cur.fetchall()
            
            cur.execute('SELECT category, COUNT(*) FROM projects GROUP BY category')
            cat_counts = dict(cur.fetchall())
            
            cur.execute('SELECT * FROM projects ORDER BY id DESC')
            all_projects = cur.fetchall()
            
            cur.execute('SELECT * FROM messages ORDER BY created_at DESC LIMIT 50')
            messages = cur.fetchall()
            
    return jsonify({
        'total_messages': msg_count,
        'total_visits': visit_count,
        'monthly_visits': monthly_v,
        'category_counts': cat_counts,
        'recent_messages': messages,
        'all_projects': all_projects
    })

@app.route('/api/admin/projects', methods=['POST'])
@login_required
def api_manage_project():
    # 1. Check for JSON data first, then Fallback to Form data
    data = request.get_json(silent=True) or request.form
    
    pid = data.get('id')
    title = data.get('title')
    desc = data.get('description')
    cat = data.get('category')
    link = data.get('link')
    tech = data.get('technologies')
    
    # Handle Image Logic
    image_file = request.files.get('image')
    image_url = data.get('existing_image') or data.get('image')

    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        upload_path = os.path.join('static', 'uploads')
        os.makedirs(upload_path, exist_ok=True)
        image_file.save(os.path.join(upload_path, filename))
        image_url = f'/static/uploads/{filename}'

    # 2. Validation Check
    if not title or not desc:
        return jsonify({"status": "error", "message": "Title and Description are required"}), 400

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                if pid:
                    # Update Existing
                    cur.execute('''
                        UPDATE projects 
                        SET title=%s, description=%s, category=%s, image=%s, link=%s, technologies=%s 
                        WHERE id=%s
                    ''', (title, desc, cat, image_url, link, tech, pid))
                else:
                    # Insert New
                    cur.execute('''
                        INSERT INTO projects (title, description, category, image, link, technologies) 
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (title, desc, cat, image_url, link, tech))
                conn.commit()
        return jsonify({"status": "success", "message": "Project protocol updated."})
    except Exception as e:
        print(f"DATABASE ERROR: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ... (AI Agent Routes follow the same Cursor pattern) ...

chat_sessions={}

def get_neural_grid_context():
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT COUNT(*) as count FROM site_visits')
                visit_count = cur.fetchone()['count']
                
                cur.execute("SELECT title, category, description, technologies, link FROM projects")
                projects = cur.fetchall()
                
                project_list = [f"| PROJECT: {p['title']} | TECH: {p['technologies']} | INFO: {p['description']}" for p in projects]
                project_summary = "\n".join(project_list) if project_list else "Registry empty."
                
                return visit_count, project_summary
    except Exception as e:
        return 0, f"Error: {e}"
    

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
