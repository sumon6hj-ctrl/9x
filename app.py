import os
import signal
import subprocess
import threading
import time
import shutil
import zipfile
import json
import psutil
import hashlib
import urllib.request
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file, session, flash
from functools import wraps

app = Flask(__name__)
app.secret_key = "sumon9x_vps_secret_key_2024_fixed"

# --- CONFIGURATION ---
BASE_DIR = os.getcwd()
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'user_files')
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
DB_FILE = 'servers_db.json'
CONFIG_FILE = 'config.json'
BLOCKED_FILE = 'blocked_users.json'
RESTART_PROTECTION_FILE = 'restart_protection.json'

if not os.path.exists(STATIC_FOLDER):
    os.makedirs(STATIC_FOLDER)
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ===== RESTART PROTECTION =====
def load_restart_protection():
    if os.path.exists(RESTART_PROTECTION_FILE):
        try:
            with open(RESTART_PROTECTION_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"last_restart": 0, "restart_count": 0}
    return {"last_restart": 0, "restart_count": 0}

def save_restart_protection(data):
    try:
        with open(RESTART_PROTECTION_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except:
        pass

RESTART_DATA = load_restart_protection()

# 30 মিনিটের মধ্যে ম্যাক্সিমাম 1 বার রেস্টার্ট
def can_restart():
    global RESTART_DATA
    current_time = time.time()
    if current_time - RESTART_DATA.get("last_restart", 0) > 1800:  # 30 মিনিট
        RESTART_DATA["restart_count"] = 0
        RESTART_DATA["last_restart"] = current_time
        save_restart_protection(RESTART_DATA)
        return True
    if RESTART_DATA.get("restart_count", 0) < 1:
        RESTART_DATA["restart_count"] = RESTART_DATA.get("restart_count", 0) + 1
        RESTART_DATA["last_restart"] = current_time
        save_restart_protection(RESTART_DATA)
        return True
    return False

# ===== LOG MANAGEMENT (শুধু শেষ 50 লাইন) =====
MAX_LOG_LINES = 50

def append_log(server_id, line):
    server = SERVERS.get(server_id)
    if not server:
        return
    logs = server.get('logs', [])
    logs.append(f"[{time.strftime('%H:%M:%S')}] {line}")
    if len(logs) > MAX_LOG_LINES:
        logs = logs[-MAX_LOG_LINES:]
    server['logs'] = logs

def get_recent_logs(server_id):
    server = SERVERS.get(server_id)
    if not server:
        return []
    return server.get('logs', [])[-MAX_LOG_LINES:]

# ===== KEEP ALIVE (২৫+ দিন চলবে) =====
def keep_alive_forever():
    """প্রতি ৫ মিনিটে পিং দিয়ে Render-কে সক্রিয় রাখে"""
    while True:
        time.sleep(300)  # ৫ মিনিট
        try:
            render_url = os.environ.get("RENDER_EXTERNAL_URL")
            if render_url:
                ping_url = f"{render_url}/api/ping"
            else:
                port = os.environ.get("PORT", 8080)
                ping_url = f"http://127.0.0.1:{port}/api/ping"
            
            req = urllib.request.Request(
                ping_url, 
                headers={'User-Agent': 'KeepAlive-Bot/2.0'}
            )
            urllib.request.urlopen(req, timeout=10)
            print(f"[KeepAlive] ✅ Ping sent at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print(f"[KeepAlive] ⚠️ Ping failed: {e}")

# Keep Alive থ্রেড শুরু করুন
threading.Thread(target=keep_alive_forever, daemon=True).start()

# ===== AUTO RESTART STOPPED SERVERS =====
def auto_restart_stopped_servers():
    """বন্ধ হয়ে যাওয়া সার্ভারগুলো আবার চালু করে"""
    while True:
        time.sleep(30)  # প্রতি ৩০ সেকেন্ডে চেক করে
        try:
            for server_id, server in list(SERVERS.items()):
                if server.get('status') == 'stopped' and server.get('auto_restart', False):
                    print(f"[AutoRestart] 🔄 Restarting {server_id}")
                    start_server_internal(server_id, server)
        except Exception as e:
            print(f"[AutoRestart] ⚠️ Error: {e}")

# Auto Restart থ্রেড শুরু করুন
threading.Thread(target=auto_restart_stopped_servers, daemon=True).start()

# --- DEFAULT CONFIG ---
DEFAULT_ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='%2300ff00'%3E%3Cpath d='M20 9V7c0-1.1-.9-2-2-2h-4c0-1.1-.9-2-2-2H6c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-2h-2v2H6V5h4v2h8v2h2z'/%3E%3C/svg%3E"

DEFAULT_CONFIG = {
    "site_title": "SUMON 9X VPS",
    "site_header": "SUMON VPS",
    "icon_url": DEFAULT_ICON,
    "theme": "matrix",
    "font_family": "default",
    "colors": {
        "matrix": {"name": "Matrix Green", "primary": "#00ff00", "secondary": "#00cc00", "accent": "#00ff80", "background": "#000000", "card_bg": "#0a0a0a", "text": "#00ff00", "danger": "#ff0000", "header_text": "#00ff00", "stats_text": "#00ff00"},
        "night": {"name": "Night Blue", "primary": "#4d88ff", "secondary": "#3366cc", "accent": "#aa88ff", "background": "#000000", "card_bg": "#0a0a0a", "text": "#4d88ff", "danger": "#ff4d4d", "header_text": "#4d88ff", "stats_text": "#4d88ff"},
        "ocean": {"name": "Ocean Blue", "primary": "#3399ff", "secondary": "#0066cc", "accent": "#ff99cc", "background": "#000000", "card_bg": "#0a0a0a", "text": "#3399ff", "danger": "#ff4d4d", "header_text": "#3399ff", "stats_text": "#3399ff"},
        "sunset": {"name": "Sunset Orange", "primary": "#ff9933", "secondary": "#cc6600", "accent": "#ff66b3", "background": "#000000", "card_bg": "#0a0a0a", "text": "#ff9933", "danger": "#ff4d4d", "header_text": "#ff9933", "stats_text": "#ff9933"},
        "blood": {"name": "Blood Red", "primary": "#ff4d4d", "secondary": "#cc0000", "accent": "#ff80bf", "background": "#000000", "card_bg": "#0a0a0a", "text": "#ff4d4d", "danger": "#ff0000", "header_text": "#ff4d4d", "stats_text": "#ff4d4d"},
        "neon": {"name": "Neon Purple", "primary": "#ff66ff", "secondary": "#cc33cc", "accent": "#ffff80", "background": "#000000", "card_bg": "#0a0a0a", "text": "#ff66ff", "danger": "#ff4d4d", "header_text": "#ff66ff", "stats_text": "#ff66ff"},
        "cyber": {"name": "Cyber Cyan", "primary": "#33ffff", "secondary": "#00cccc", "accent": "#ff80ff", "background": "#000000", "card_bg": "#0a0a0a", "text": "#33ffff", "danger": "#ff4d4d", "header_text": "#33ffff", "stats_text": "#33ffff"},
        "vapor": {"name": "Vapor Pink", "primary": "#ff99ff", "secondary": "#cc66cc", "accent": "#80ffff", "background": "#000000", "card_bg": "#0a0a0a", "text": "#ff99ff", "danger": "#ff4d4d", "header_text": "#ff99ff", "stats_text": "#ff99ff"},
        "gold": {"name": "Royal Gold", "primary": "#ffcc66", "secondary": "#cc9933", "accent": "#ffb380", "background": "#000000", "card_bg": "#0a0a0a", "text": "#ffcc66", "danger": "#ff4d4d", "header_text": "#ffcc66", "stats_text": "#ffcc66"},
        "silver": {"name": "Silver Grey", "primary": "#b3b3b3", "secondary": "#808080", "accent": "#cccccc", "background": "#000000", "card_bg": "#0a0a0a", "text": "#b3b3b3", "danger": "#ff4d4d", "header_text": "#b3b3b3", "stats_text": "#b3b3b3"},
        # নতুন 10 টি রং
        "crimson": {"name": "Crimson Red", "primary": "#dc143c", "secondary": "#8b0000", "accent": "#ff6b6b", "background": "#000000", "card_bg": "#0a0a0a", "text": "#dc143c", "danger": "#ff0000", "header_text": "#dc143c", "stats_text": "#dc143c"},
        "emerald": {"name": "Emerald Green", "primary": "#50c878", "secondary": "#2e8b57", "accent": "#98fb98", "background": "#000000", "card_bg": "#0a0a0a", "text": "#50c878", "danger": "#ff4d4d", "header_text": "#50c878", "stats_text": "#50c878"},
        "sapphire": {"name": "Sapphire Blue", "primary": "#0f52ba", "secondary": "#003366", "accent": "#6699ff", "background": "#000000", "card_bg": "#0a0a0a", "text": "#0f52ba", "danger": "#ff4d4d", "header_text": "#0f52ba", "stats_text": "#0f52ba"},
        "ruby": {"name": "Ruby Red", "primary": "#e0115f", "secondary": "#9b111e", "accent": "#ff69b4", "background": "#000000", "card_bg": "#0a0a0a", "text": "#e0115f", "danger": "#ff0000", "header_text": "#e0115f", "stats_text": "#e0115f"},
        "topaz": {"name": "Topaz Yellow", "primary": "#ffc87c", "secondary": "#e8a317", "accent": "#ffdb58", "background": "#000000", "card_bg": "#0a0a0a", "text": "#ffc87c", "danger": "#ff4d4d", "header_text": "#ffc87c", "stats_text": "#ffc87c"},
        "amethyst": {"name": "Amethyst Purple", "primary": "#9966cc", "secondary": "#6a0dad", "accent": "#d8b4fe", "background": "#000000", "card_bg": "#0a0a0a", "text": "#9966cc", "danger": "#ff4d4d", "header_text": "#9966cc", "stats_text": "#9966cc"},
        "jade": {"name": "Jade Green", "primary": "#00a86b", "secondary": "#006a4e", "accent": "#7ddfb3", "background": "#000000", "card_bg": "#0a0a0a", "text": "#00a86b", "danger": "#ff4d4d", "header_text": "#00a86b", "stats_text": "#00a86b"},
        "coral": {"name": "Coral Pink", "primary": "#ff7f50", "secondary": "#cd5c5c", "accent": "#ffa07a", "background": "#000000", "card_bg": "#0a0a0a", "text": "#ff7f50", "danger": "#ff4d4d", "header_text": "#ff7f50", "stats_text": "#ff7f50"},
        "indigo": {"name": "Indigo Blue", "primary": "#4b0082", "secondary": "#2c0066", "accent": "#8b5cf6", "background": "#000000", "card_bg": "#0a0a0a", "text": "#4b0082", "danger": "#ff4d4d", "header_text": "#4b0082", "stats_text": "#4b0082"},
        "rose": {"name": "Rose Gold", "primary": "#b76e79", "secondary": "#8a5a64", "accent": "#e8a2b0", "background": "#000000", "card_bg": "#0a0a0a", "text": "#b76e79", "danger": "#ff4d4d", "header_text": "#b76e79", "stats_text": "#b76e79"}
    },
    "fonts": {
        "default": "'Segoe UI', sans-serif",
        "hacker": "'Courier New', monospace",
        "terminal": "'Consolas', monospace",
        "code": "'Fira Code', monospace",
        "retro": "'VT323', monospace"
    },
    "passwords": {
        "secret": "sumon000",
        "user": "sumon9"
    }
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                for key in DEFAULT_CONFIG:
                    if key not in config:
                        config[key] = DEFAULT_CONFIG[key]
                if 'passwords' in config:
                    if 'secret' in config['passwords'] and len(config['passwords']['secret']) > 20:
                        config['passwords']['secret'] = "sumon000"
                    if 'user' in config['passwords'] and len(config['passwords']['user']) > 20:
                        config['passwords']['user'] = "sumon9"
                return config
        except:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except:
        pass

CONFIG = load_config()

def load_blocked_users():
    if os.path.exists(BLOCKED_FILE):
        try:
            with open(BLOCKED_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_blocked_users(blocked):
    try:
        with open(BLOCKED_FILE, 'w') as f:
            json.dump(blocked, f, indent=2)
    except:
        pass

BLOCKED_USERS = load_blocked_users()
SERVERS = {}

def save_servers():
    try:
        data = {}
        for sid, s in SERVERS.items():
            data[sid] = {
                'cmd': s.get('cmd', ''),
                'cwd': s.get('cwd', ''),
                'path': s.get('path', ''),
                'auto_restart': s.get('auto_restart', False),
                'restart_interval': s.get('restart_interval', '1h'),
                'status': s.get('status', 'stopped'),
                'last_start_time': s.get('last_start_time', 0),
                'owner': s.get('owner', 'user'),
                'logs': s.get('logs', [])[-MAX_LOG_LINES:]
            }
        with open(DB_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except:
        pass

def load_servers():
    global SERVERS
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                saved = json.load(f)
                for sid, s in saved.items():
                    SERVERS[sid] = {
                        'process': None,
                        'cmd': s.get('cmd', ''),
                        'cwd': s.get('cwd', ''),
                        'auto_restart': s.get('auto_restart', False),
                        'restart_interval': s.get('restart_interval', '1h'),
                        'logs': s.get('logs', ["Restored from previous session..."])[-MAX_LOG_LINES:],
                        'status': s.get('status', 'stopped'),
                        'path': s.get('path', ''),
                        'last_start_time': s.get('last_start_time', 0),
                        'owner': s.get('owner', 'user')
                    }
        except:
            pass

load_servers()

# --- LOGIN DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session.get('is_secret'):
            flash('Admin access required', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def check_blocked(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('username') in BLOCKED_USERS:
            session.clear()
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- HELPER FUNCTIONS ---
def get_system_stats():
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        return cpu, ram
    except Exception as e:
        print(f"Stats error: {e}")
        return 0, 0

def log_monitor(server_id, proc_obj):
    server = SERVERS.get(server_id)
    if not server:
        return
    try:
        for line in iter(proc_obj.stdout.readline, ''):
            if server_id not in SERVERS or SERVERS[server_id].get('process') != proc_obj:
                break
            if line:
                append_log(server_id, line.strip())
    except:
        pass
    finally:
        try:
            proc_obj.stdout.close()
        except:
            pass
    if server_id in SERVERS and SERVERS[server_id].get('process') == proc_obj:
        SERVERS[server_id]['status'] = 'stopped'
        SERVERS[server_id]['process'] = None
        save_servers()

def kill_process_completely(proc):
    try:
        if proc is None:
            return
        import psutil
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except:
                pass
        gone, alive = psutil.wait_procs(children, timeout=3)
        for child in alive:
            try:
                child.kill()
            except:
                pass
        try:
            parent.terminate()
            parent.wait(timeout=3)
        except:
            try:
                parent.kill()
            except:
                pass
    except:
        pass

def start_server_internal(server_id, server):
    if server['status'] == 'running':
        return True
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    work_dir = os.path.join(server['path'], server.get('cwd', ''))
    if not os.path.exists(work_dir):
        work_dir = server['path']
    try:
        if not server['cmd'] or server['cmd'].strip() == '':
            append_log(server_id, "❌ Error: No start command specified")
            return False
        if not os.path.exists(work_dir):
            append_log(server_id, f"❌ Error: Working directory does not exist: {work_dir}")
            return False
        proc = subprocess.Popen(
            server['cmd'],
            shell=True,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=env,
            preexec_fn=os.setsid if os.name != 'nt' else None
        )
        server['process'] = proc
        server['status'] = 'running'
        server['last_start_time'] = time.time()
        append_log(server_id, "🚀 Server started successfully!")
        threading.Thread(target=log_monitor, args=(server_id, proc), daemon=True).start()
        save_servers()
        return True
    except Exception as e:
        append_log(server_id, f"❌ Failed to start: {str(e)}")
        return False

# --- AUTH ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        if request.method == 'POST':
            password = request.form.get('password')
            
            if password == CONFIG['passwords']['secret']:
                session['logged_in'] = True
                session['is_secret'] = True
                session['username'] = 'admin'
                return redirect(url_for('admin_panel'))
            
            elif password == CONFIG['passwords']['user']:
                if 'user' in BLOCKED_USERS:
                    return render_template('login.html', error="You have been blocked by admin", config=CONFIG)
                session['logged_in'] = True
                session['is_secret'] = False
                session['username'] = 'user'
                return redirect(url_for('index'))
            
            else:
                return render_template('login.html', error="Invalid password", config=CONFIG)
        
        return render_template('login.html', config=CONFIG)
    except Exception as e:
        return f"Login error: {e}", 500

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    try:
        if request.method == 'POST':
            password = request.form.get('password')
            
            if password == CONFIG['passwords']['secret']:
                session['logged_in'] = True
                session['is_secret'] = True
                session['username'] = 'admin'
                return redirect(url_for('admin_panel'))
            else:
                return render_template('admin_login.html', error="Invalid admin password", config=CONFIG)
        
        return render_template('admin_login.html', config=CONFIG)
    except Exception as e:
        return f"Login error: {e}", 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- USER DASHBOARD ---
@app.route('/')
@login_required
@check_blocked
def index():
    try:
        cpu, ram = get_system_stats()
        current_colors = CONFIG['colors'].get(CONFIG['theme'], CONFIG['colors']['matrix'])
        serializable_servers = {}
        for sid, s in SERVERS.items():
            if s.get('owner', 'user') == 'user':
                serializable_servers[sid] = {
                    'cmd': s.get('cmd', ''),
                    'cwd': s.get('cwd', ''),
                    'auto_restart': s.get('auto_restart', False),
                    'restart_interval': s.get('restart_interval', '1h'),
                    'status': s.get('status', 'stopped'),
                    'path': s.get('path', ''),
                    'last_start_time': s.get('last_start_time', 0),
                    'owner': s.get('owner', 'user')
                }
        return render_template('index.html', 
                             servers=serializable_servers,
                             cpu=cpu, 
                             ram=ram,
                             total_count=len(serializable_servers),
                             running_count=sum(1 for s in serializable_servers.values() if s['status'] == 'running'),
                             config=CONFIG,
                             colors=current_colors,
                             is_secret=session.get('is_secret', False))
    except Exception as e:
        return f"Error: {e}", 500

# --- ADMIN PANEL ---
@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    try:
        cpu, ram = get_system_stats()
        current_colors = CONFIG['colors'].get(CONFIG['theme'], CONFIG['colors']['matrix'])
        serializable_servers = {}
        for sid, s in SERVERS.items():
            if s.get('owner', 'user') == 'admin':
                serializable_servers[sid] = {
                    'cmd': s.get('cmd', ''),
                    'cwd': s.get('cwd', ''),
                    'auto_restart': s.get('auto_restart', False),
                    'restart_interval': s.get('restart_interval', '1h'),
                    'status': s.get('status', 'stopped'),
                    'path': s.get('path', ''),
                    'last_start_time': s.get('last_start_time', 0),
                    'owner': s.get('owner', 'user')
                }
        return render_template('admin.html', 
                             servers=serializable_servers,
                             cpu=cpu, 
                             ram=ram,
                             total_count=len(serializable_servers),
                             running_count=sum(1 for s in serializable_servers.values() if s['status'] == 'running'),
                             config=CONFIG,
                             colors=current_colors,
                             blocked_users=BLOCKED_USERS)
    except Exception as e:
        return f"Error: {e}", 500

# --- CHANGE USER PASSWORD (Admin) ---
@app.route('/admin/change_password', methods=['POST'])
@admin_required
def change_user_password():
    try:
        new_password = request.form.get('new_password')
        if not new_password or len(new_password) < 3:
            return jsonify({'error': 'Password must be at least 3 characters'}), 400
        if len(new_password) > 20:
            return jsonify({'error': 'Password too long (max 20 chars)'}), 400
        
        CONFIG['passwords']['user'] = new_password
        save_config(CONFIG)  # শুধু এটুকুই যথেষ্ট
        return jsonify({'status': 'ok', 'message': 'User password updated successfully!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Admin: User Management ---
@app.route('/admin/block_user/<username>')
@admin_required
def block_user(username):
    if username not in BLOCKED_USERS:
        BLOCKED_USERS.append(username)
        save_blocked_users(BLOCKED_USERS)
    return redirect(url_for('admin_panel'))

@app.route('/admin/unblock_user/<username>')
@admin_required
def unblock_user(username):
    if username in BLOCKED_USERS:
        BLOCKED_USERS.remove(username)
        save_blocked_users(BLOCKED_USERS)
    return redirect(url_for('admin_panel'))

# --- Admin: Server Actions ---
@app.route('/admin/action/<server_id>/<action>')
@admin_required
def admin_server_action(server_id, action):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        server = SERVERS[server_id]
        if action == 'start':
            start_server_internal(server_id, server)
        elif action == 'stop':
            if server['process']:
                kill_process_completely(server['process'])
                server['process'] = None
            server['status'] = 'stopped'
            append_log(server_id, "⏹️ Stopped by admin")
            save_servers()
        elif action == 'restart':
            if not can_restart():
                append_log(server_id, "⛔ Restart blocked! Wait 30 minutes.")
                return redirect(url_for('admin_panel'))
            if server['process']:
                kill_process_completely(server['process'])
                server['process'] = None
            server['status'] = 'stopped'
            append_log(server_id, "🔄 Manual restart triggered by admin...")
            time.sleep(1)
            start_server_internal(server_id, server)
        elif action == 'delete':
            if server['process']:
                kill_process_completely(server['process'])
                server['process'] = None
            if os.path.exists(server['path']):
                shutil.rmtree(server['path'], ignore_errors=True)
            del SERVERS[server_id]
            save_servers()
        return redirect(url_for('admin_panel'))
    except Exception as e:
        return redirect(url_for('admin_panel'))

# --- Admin: File Management ---
@app.route('/admin/files/<server_id>')
@admin_required
def admin_list_files(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        subpath = request.args.get('path', '')
        if '..' in subpath:
            subpath = ''
        base_path = SERVERS[server_id]['path']
        full_path = os.path.join(base_path, subpath)
        if not os.path.realpath(full_path).startswith(os.path.realpath(base_path)):
            full_path = base_path
            subpath = ''
        if not os.path.exists(full_path):
            full_path = base_path
            subpath = ''
        files = []
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            is_file = os.path.isfile(item_path)
            size = 0
            if is_file:
                size = os.path.getsize(item_path)
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size/1024:.1f} KB"
            else:
                size_str = f"{size/(1024*1024):.1f} MB"
            files.append({
                'name': item,
                'size': size_str,
                'raw_size': size,
                'type': 'file' if is_file else 'dir'
            })
        files.sort(key=lambda x: (x['type'] != 'dir', x['name'].lower()))
        return jsonify({
            'files': files,
            'cmd': SERVERS[server_id]['cmd'],
            'cwd': SERVERS[server_id].get('cwd', ''),
            'auto_restart': SERVERS[server_id].get('auto_restart', False),
            'restart_interval': SERVERS[server_id].get('restart_interval', '1h'),
            'current_path': subpath
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/download/<server_id>/<filename>')
@admin_required
def admin_download_file(server_id, filename):
    try:
        if server_id not in SERVERS:
            return "Server not found", 404
        subpath = request.args.get('path', '')
        if '..' in subpath or '..' in filename:
            return "Invalid path", 400
        file_path = os.path.join(SERVERS[server_id]['path'], subpath, filename)
        if not os.path.realpath(file_path).startswith(os.path.realpath(SERVERS[server_id]['path'])):
            return "Invalid path", 400
        if not os.path.exists(file_path):
            return "File not found", 404
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return str(e), 500

@app.route('/admin/delete_file/<server_id>/<filename>')
@admin_required
def admin_delete_file(server_id, filename):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        subpath = request.args.get('path', '')
        if '..' in subpath or '..' in filename:
            return jsonify({'error': 'Invalid path'}), 400
        file_path = os.path.join(SERVERS[server_id]['path'], subpath, filename)
        if not os.path.realpath(file_path).startswith(os.path.realpath(SERVERS[server_id]['path'])):
            return jsonify({'error': 'Invalid path'}), 400
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        if os.path.isdir(file_path):
            shutil.rmtree(file_path)
        else:
            os.remove(file_path)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/file_content/<server_id>')
@admin_required
def admin_file_content(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        filename = request.args.get('filename')
        subpath = request.args.get('path', '')
        if not filename:
            return jsonify({'error': 'No filename'}), 400
        subpath = subpath.replace('..', '')
        filename = filename.replace('..', '')
        file_path = os.path.join(SERVERS[server_id]['path'], subpath, filename)
        if not os.path.realpath(file_path).startswith(os.path.realpath(SERVERS[server_id]['path'])):
            return jsonify({'error': 'Invalid path'}), 400
        if not os.path.isfile(file_path):
            return jsonify({'error': 'File not found'}), 404
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return jsonify({'content': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/get_logs/<server_id>')
@admin_required
def admin_get_logs(server_id):
    try:
        if server_id in SERVERS:
            return jsonify({'logs': "\n".join(get_recent_logs(server_id))})
        return jsonify({'logs': ''})
    except:
        return jsonify({'logs': ''})

@app.route('/admin/update_settings/<server_id>', methods=['POST'])
@admin_required
def admin_update_settings(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        cmd = request.form.get('cmd', '').strip()
        cwd = request.form.get('cwd', '').strip()
        auto_restart = request.form.get('auto_restart') == 'true'
        restart_interval = request.form.get('restart_interval', '1h')
        SERVERS[server_id]['cmd'] = cmd
        SERVERS[server_id]['cwd'] = cwd
        SERVERS[server_id]['auto_restart'] = auto_restart
        SERVERS[server_id]['restart_interval'] = restart_interval
        append_log(server_id, "⚙️ Settings updated by admin")
        save_servers()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Admin: Package Management ---
@app.route('/admin/install_pkg/<server_id>', methods=['POST'])
@admin_required
def admin_install_pkg(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        pkg_type = request.form.get('type')
        pkg_name = request.form.get('name')
        if not pkg_name:
            return jsonify({'error': 'Package name required'}), 400
        cmd = ""
        if pkg_type == 'pip':
            cmd = f"pip install {pkg_name}"
        elif pkg_type == 'pkg':
            cmd = f"pkg install -y {pkg_name}"
        elif pkg_type == 'apt':
            cmd = f"apt-get install -y {pkg_name}"
        elif pkg_type == 'npm':
            cmd = f"npm install -g {pkg_name}"
        else:
            return jsonify({'error': 'Invalid package type'}), 400
        threading.Thread(target=lambda: run_install_command(server_id, cmd), daemon=True).start()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/uninstall_pkg/<server_id>', methods=['POST'])
@admin_required
def admin_uninstall_pkg(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        pkg_type = request.form.get('type')
        pkg_name = request.form.get('name')
        if not pkg_name:
            return jsonify({'error': 'Package name required'}), 400
        cmd = ""
        if pkg_type == 'pip':
            cmd = f"pip uninstall -y {pkg_name}"
        elif pkg_type == 'pkg':
            cmd = f"pkg uninstall -y {pkg_name}"
        elif pkg_type == 'apt':
            cmd = f"apt-get remove -y {pkg_name}"
        elif pkg_type == 'npm':
            cmd = f"npm uninstall -g {pkg_name}"
        else:
            return jsonify({'error': 'Invalid package type'}), 400
        threading.Thread(target=lambda: run_install_command(server_id, cmd), daemon=True).start()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def run_install_command(server_id, command):
    if server_id in SERVERS:
        append_log(server_id, f"📦 {command}")
        try:
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in iter(process.stdout.readline, ''):
                if line:
                    append_log(server_id, line.strip())
            append_log(server_id, "✅ Installation finished.")
        except Exception as e:
            append_log(server_id, f"❌ Error: {str(e)}")

# --- Admin: Theme & Config ---
@app.route('/admin/update_config', methods=['POST'])
@admin_required
def admin_update_config():
    try:
        site_title = request.form.get('site_title')
        site_header = request.form.get('site_header')
        icon_url = request.form.get('icon_url')
        theme = request.form.get('theme')
        font_family = request.form.get('font_family')
        if site_title:
            CONFIG['site_title'] = site_title
        if site_header:
            CONFIG['site_header'] = site_header
        if icon_url:
            CONFIG['icon_url'] = icon_url
        if theme and theme in CONFIG['colors']:
            CONFIG['theme'] = theme
        if font_family and font_family in CONFIG['fonts']:
            CONFIG['font_family'] = font_family
        save_config(CONFIG)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- USER SERVER ACTIONS ---
@app.route('/action/<server_id>/<action>')
@login_required
@check_blocked
def user_server_action(server_id, action):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        server = SERVERS[server_id]
        if action == 'start':
            start_server_internal(server_id, server)
        elif action == 'stop':
            if server['process']:
                kill_process_completely(server['process'])
                server['process'] = None
            server['status'] = 'stopped'
            append_log(server_id, "⏹️ Stopped by user")
            save_servers()
        elif action == 'restart':
            if not can_restart():
                append_log(server_id, "⛔ Restart blocked! Wait 30 minutes.")
                return redirect(url_for('index'))
            if server['process']:
                kill_process_completely(server['process'])
                server['process'] = None
            server['status'] = 'stopped'
            append_log(server_id, "🔄 Manual restart triggered...")
            time.sleep(1)
            start_server_internal(server_id, server)
        elif action == 'delete':
            if server['process']:
                kill_process_completely(server['process'])
                server['process'] = None
            if os.path.exists(server['path']):
                shutil.rmtree(server['path'], ignore_errors=True)
            del SERVERS[server_id]
            save_servers()
        return redirect(url_for('index'))
    except Exception as e:
        return redirect(url_for('index'))

# --- USER FILE MANAGEMENT ---
@app.route('/files/<server_id>')
@login_required
@check_blocked
def user_list_files(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        subpath = request.args.get('path', '')
        if '..' in subpath:
            subpath = ''
        base_path = SERVERS[server_id]['path']
        full_path = os.path.join(base_path, subpath)
        if not os.path.realpath(full_path).startswith(os.path.realpath(base_path)):
            full_path = base_path
            subpath = ''
        if not os.path.exists(full_path):
            full_path = base_path
            subpath = ''
        files = []
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            is_file = os.path.isfile(item_path)
            size = 0
            if is_file:
                size = os.path.getsize(item_path)
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size/1024:.1f} KB"
            else:
                size_str = f"{size/(1024*1024):.1f} MB"
            files.append({
                'name': item,
                'size': size_str,
                'raw_size': size,
                'type': 'file' if is_file else 'dir'
            })
        files.sort(key=lambda x: (x['type'] != 'dir', x['name'].lower()))
        return jsonify({
            'files': files,
            'cmd': SERVERS[server_id]['cmd'],
            'cwd': SERVERS[server_id].get('cwd', ''),
            'auto_restart': SERVERS[server_id].get('auto_restart', False),
            'restart_interval': SERVERS[server_id].get('restart_interval', '1h'),
            'current_path': subpath
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<server_id>/<filename>')
@login_required
@check_blocked
def user_download_file(server_id, filename):
    try:
        if server_id not in SERVERS:
            return "Server not found", 404
        subpath = request.args.get('path', '')
        if '..' in subpath or '..' in filename:
            return "Invalid path", 400
        file_path = os.path.join(SERVERS[server_id]['path'], subpath, filename)
        if not os.path.realpath(file_path).startswith(os.path.realpath(SERVERS[server_id]['path'])):
            return "Invalid path", 400
        if not os.path.exists(file_path):
            return "File not found", 404
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return str(e), 500

@app.route('/delete_file/<server_id>/<filename>')
@login_required
@check_blocked
def user_delete_file(server_id, filename):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        subpath = request.args.get('path', '')
        if '..' in subpath or '..' in filename:
            return jsonify({'error': 'Invalid path'}), 400
        file_path = os.path.join(SERVERS[server_id]['path'], subpath, filename)
        if not os.path.realpath(file_path).startswith(os.path.realpath(SERVERS[server_id]['path'])):
            return jsonify({'error': 'Invalid path'}), 400
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        if os.path.isdir(file_path):
            shutil.rmtree(file_path)
        else:
            os.remove(file_path)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/file_content/<server_id>')
@login_required
@check_blocked
def user_file_content(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        filename = request.args.get('filename')
        subpath = request.args.get('path', '')
        if not filename:
            return jsonify({'error': 'No filename'}), 400
        subpath = subpath.replace('..', '')
        filename = filename.replace('..', '')
        file_path = os.path.join(SERVERS[server_id]['path'], subpath, filename)
        if not os.path.realpath(file_path).startswith(os.path.realpath(SERVERS[server_id]['path'])):
            return jsonify({'error': 'Invalid path'}), 400
        if not os.path.isfile(file_path):
            return jsonify({'error': 'File not found'}), 404
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return jsonify({'content': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/save_file/<server_id>', methods=['POST'])
@login_required
@check_blocked
def user_save_file(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        filename = request.form.get('filename')
        subpath = request.form.get('path', '')
        content = request.form.get('content')
        if not filename or content is None:
            return jsonify({'error': 'Missing data'}), 400
        subpath = subpath.replace('..', '')
        filename = filename.replace('..', '')
        file_path = os.path.join(SERVERS[server_id]['path'], subpath, filename)
        if not os.path.realpath(file_path).startswith(os.path.realpath(SERVERS[server_id]['path'])):
            return jsonify({'error': 'Invalid path'}), 400
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/create_file/<server_id>', methods=['POST'])
@login_required
@check_blocked
def user_create_file(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        filename = request.form.get('filename')
        subpath = request.form.get('path', '')
        content = request.form.get('content', '')
        if not filename:
            return jsonify({'error': 'Filename required'}), 400
        subpath = subpath.replace('..', '')
        filename = filename.replace('..', '')
        file_path = os.path.join(SERVERS[server_id]['path'], subpath, filename)
        if not os.path.realpath(file_path).startswith(os.path.realpath(SERVERS[server_id]['path'])):
            return jsonify({'error': 'Invalid path'}), 400
        if os.path.exists(file_path):
            return jsonify({'error': 'File already exists'}), 400
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload/<server_id>', methods=['POST'])
@login_required
@check_blocked
def user_upload_file(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        file = request.files.get('file')
        subpath = request.form.get('path', '')
        if '..' in subpath:
            subpath = ''
        if not file or not file.filename:
            return jsonify({'error': 'No file provided'}), 400
        target_dir = os.path.join(SERVERS[server_id]['path'], subpath)
        if not os.path.realpath(target_dir).startswith(os.path.realpath(SERVERS[server_id]['path'])):
            return jsonify({'error': 'Invalid path'}), 400
        os.makedirs(target_dir, exist_ok=True)
        file_path = os.path.join(target_dir, file.filename)
        file.save(file_path)
        return jsonify({'status': 'ok', 'message': 'File uploaded successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/create_folder/<server_id>', methods=['POST'])
@login_required
@check_blocked
def user_create_folder(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        folder_name = request.form.get('name')
        subpath = request.form.get('path', '')
        if '..' in subpath:
            subpath = ''
        if not folder_name:
            return jsonify({'error': 'Folder name required'}), 400
        folder_name = folder_name.replace('..', '')
        target = os.path.join(SERVERS[server_id]['path'], subpath, folder_name)
        if not os.path.realpath(target).startswith(os.path.realpath(SERVERS[server_id]['path'])):
            return jsonify({'error': 'Invalid path'}), 400
        os.makedirs(target, exist_ok=True)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/update_settings/<server_id>', methods=['POST'])
@login_required
@check_blocked
def user_update_settings(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        cmd = request.form.get('cmd', '').strip()
        cwd = request.form.get('cwd', '').strip()
        auto_restart = request.form.get('auto_restart') == 'true'
        restart_interval = request.form.get('restart_interval', '1h')
        SERVERS[server_id]['cmd'] = cmd
        SERVERS[server_id]['cwd'] = cwd
        SERVERS[server_id]['auto_restart'] = auto_restart
        SERVERS[server_id]['restart_interval'] = restart_interval
        append_log(server_id, "⚙️ Settings updated")
        save_servers()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/install_pkg/<server_id>', methods=['POST'])
@login_required
@check_blocked
def user_install_pkg(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        pkg_type = request.form.get('type')
        pkg_name = request.form.get('name')
        if not pkg_name:
            return jsonify({'error': 'Package name required'}), 400
        cmd = ""
        if pkg_type == 'pip':
            cmd = f"pip install {pkg_name}"
        elif pkg_type == 'pkg':
            cmd = f"pkg install -y {pkg_name}"
        elif pkg_type == 'apt':
            cmd = f"apt-get install -y {pkg_name}"
        elif pkg_type == 'npm':
            cmd = f"npm install -g {pkg_name}"
        else:
            return jsonify({'error': 'Invalid package type'}), 400
        threading.Thread(target=lambda: run_install_command(server_id, cmd), daemon=True).start()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/uninstall_pkg/<server_id>', methods=['POST'])
@login_required
@check_blocked
def user_uninstall_pkg(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Server not found'}), 404
        pkg_type = request.form.get('type')
        pkg_name = request.form.get('name')
        if not pkg_name:
            return jsonify({'error': 'Package name required'}), 400
        cmd = ""
        if pkg_type == 'pip':
            cmd = f"pip uninstall -y {pkg_name}"
        elif pkg_type == 'pkg':
            cmd = f"pkg uninstall -y {pkg_name}"
        elif pkg_type == 'apt':
            cmd = f"apt-get remove -y {pkg_name}"
        elif pkg_type == 'npm':
            cmd = f"npm uninstall -g {pkg_name}"
        else:
            return jsonify({'error': 'Invalid package type'}), 400
        threading.Thread(target=lambda: run_install_command(server_id, cmd), daemon=True).start()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_logs/<server_id>')
@login_required
@check_blocked
def user_get_logs(server_id):
    try:
        if server_id in SERVERS:
            return jsonify({'logs': "\n".join(get_recent_logs(server_id))})
        return jsonify({'logs': ''})
    except:
        return jsonify({'logs': ''})

@app.route('/send_input/<server_id>', methods=['POST'])
@login_required
@check_blocked
def user_send_input(server_id):
    try:
        cmd = request.form.get('command')
        if not cmd:
            return jsonify({'status': 'error', 'message': 'No command provided'})
        if server_id not in SERVERS:
            return jsonify({'status': 'error', 'message': 'Server not found'})
        server = SERVERS[server_id]
        if not server['process']:
            return jsonify({'status': 'error', 'message': 'Process not running'})
        proc = server['process']
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.write(cmd + "\n")
            proc.stdin.flush()
            append_log(server_id, f"📝 Input: {cmd}")
            return jsonify({'status': 'ok'})
        else:
            return jsonify({'status': 'error', 'message': 'stdin closed'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/server_info/<server_id>')
@login_required
def server_info(server_id):
    try:
        if server_id not in SERVERS:
            return jsonify({'error': 'Not found'}), 404
        s = SERVERS[server_id]
        uptime = 0
        if s['status'] == 'running' and s['last_start_time'] > 0:
            uptime = int(time.time() - s['last_start_time'])
        return jsonify({
            'status': s['status'],
            'auto_restart': s.get('auto_restart', False),
            'restart_interval': s.get('restart_interval', '1h'),
            'last_start_time': s.get('last_start_time', 0),
            'uptime': uptime
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/system_stats')
@login_required
def system_stats():
    try:
        cpu, ram = get_system_stats()
        return jsonify({'cpu': cpu, 'ram': ram})
    except:
        return jsonify({'cpu': 0, 'ram': 0})

@app.route('/create_server', methods=['POST'])
@login_required
@check_blocked
def create_server():
    try:
        server_name = request.form.get('server_name').strip().replace(" ", "_")
        start_command = request.form.get('start_command').strip()
        if not server_name:
            return "Server name required", 400
        if server_name in SERVERS:
            return "Server name already exists", 400
        file = request.files.get('file')
        server_path = os.path.join(UPLOAD_FOLDER, server_name)
        os.makedirs(server_path, exist_ok=True)
        if file and file.filename:
            file_path = os.path.join(server_path, file.filename)
            file.save(file_path)
            if file.filename.lower().endswith('.zip'):
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(server_path)
                except:
                    pass
        SERVERS[server_name] = {
            'process': None, 
            'cmd': start_command, 
            'cwd': '', 
            'logs': [f"🚀 Server '{server_name}' created at {time.strftime('%H:%M:%S')}"],
            'auto_restart': True,  # অটো রিস্টার্ট ডিফল্ট অন
            'restart_interval': '1h', 
            'last_start_time': 0,
            'status': 'stopped', 
            'path': server_path,
            'owner': 'user'
        }
        save_servers()
        return redirect(url_for('index'))
    except Exception as e:
        return f"Error: {e}", 500

# --- Telegram Bot ---
@app.route('/telegram_bot', methods=['POST'])
@login_required
@check_blocked
def user_telegram_bot():
    try:
        token = request.form.get('token')
        if not token:
            return jsonify({'error': 'Token required'}), 400
        if ':' not in token or len(token) < 40:
            return jsonify({'error': 'Invalid token format'}), 400
            
        timestamp = int(time.time())
        server_name = f"tg_bot_{timestamp}"
        server_path = os.path.join(UPLOAD_FOLDER, server_name)
        os.makedirs(server_path, exist_ok=True)
        
        bot_script = '''import json
import time
import platform
from datetime import datetime
import requests
import telebot

BOT_TOKEN = "{}"

bot = telebot.TeleBot(BOT_TOKEN)
START_TIME = time.time()

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "🤖 *SUMON VPS Telegram Bot*\\n\\n"
        "Send API request like:\\n"
        "`/api https://api.github.com`\\n\\n"
        "*Commands:*\\n"
        "/start - Show this message\\n"
        "/help - Show help\\n"
        "/api <url> - Check API endpoint\\n"
        "/ping - Check bot status\\n"
        "/uptime - Show bot uptime\\n"
        "/info - Show system info"
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = (
        "📚 *Available Commands:*\\n\\n"
        "🔹 `/start` - Welcome message\\n"
        "🔹 `/help` - Show this help\\n"
        "🔹 `/api <url>` - Check API endpoint (JSON response)\\n"
        "🔹 `/ping` - Check bot status\\n"
        "🔹 `/uptime` - Show bot uptime\\n"
        "🔹 `/info` - Show system info\\n\\n"
        "📌 *Example:*\\n"
        "`/api https://api.github.com`"
    )
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['ping'])
def send_ping(message):
    bot.reply_to(message, "🏓 Pong! Bot is alive!")

@bot.message_handler(commands=['uptime'])
def send_uptime(message):
    uptime_seconds = int(time.time() - START_TIME)
    days = uptime_seconds // 86400
    hours = (uptime_seconds % 86400) // 3600
    minutes = (uptime_seconds % 3600) // 60
    seconds = uptime_seconds % 60
    uptime_str = f"⏱ *Bot Uptime:*\\n"
    if days > 0:
        uptime_str += f"{{days}} days, "
    uptime_str += f"{{hours}}h {{minutes}}m {{seconds}}s"
    bot.reply_to(message, uptime_str, parse_mode='Markdown')

@bot.message_handler(commands=['info'])
def send_info(message):
    info_text = (
        f"📊 *System Information*\\n"
        f"• Platform: {{platform.system()}} {{platform.release()}}\\n"
        f"• Python: {{platform.python_version()}}\\n"
        f"• Bot Status: Active\\n"
        f"• Time: {{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}\\n"
        f"• Host: SUMON VPS (24/7 Uptime)"
    )
    bot.reply_to(message, info_text, parse_mode='Markdown')

@bot.message_handler(commands=['api'])
def send_api_response(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(
            message,
            "❌ *Usage:*\\n`/api <url>`\\n\\n📌 *Example:*\\n`/api https://api.github.com`",
            parse_mode='Markdown'
        )
        return

    url = args[1].strip()
    bot.send_chat_action(message.chat.id, 'typing')

    try:
        r = requests.get(url, timeout=15, headers={{'User-Agent': 'SUMON-TeleBot'}})
        
        try:
            response_data = r.json()
            formatted_json = json.dumps(response_data, indent=2, ensure_ascii=False)
        except:
            formatted_json = r.text

        if len(formatted_json) > 4000:
            formatted_json = formatted_json[:4000] + "\\n\\n... (response too long)"

        response_text = (
            f"📡 *API Response:*\\n"
            f"• URL: `{{url}}`\\n"
            f"• Status: `{{r.status_code}}`\\n"
            f"• Time: `{{r.elapsed.total_seconds():.2f}}s`\\n\\n"
            f"```json\\n{{formatted_json}}\\n```"
        )
        bot.reply_to(message, response_text, parse_mode='Markdown')

    except requests.exceptions.Timeout:
        bot.reply_to(message, "❌ *Error:* Request timeout (15s)", parse_mode='Markdown')
    except requests.exceptions.ConnectionError:
        bot.reply_to(message, "❌ *Error:* Connection failed", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ *Error:* `{{str(e)}}`", parse_mode='Markdown')

if __name__ == "__main__":
    print("✅ Bot Started Successfully!")
    print(f"⏱ Started at: {{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}")
    bot.infinity_polling()
'''.format(token)
        
        script_path = os.path.join(server_path, "bot.py")
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(bot_script)
        
        with open(os.path.join(server_path, "requirements.txt"), 'w') as f:
            f.write("pyTelegramBotAPI==4.14.1\nrequests==2.31.0")
        
        SERVERS[server_name] = {
            'process': None, 
            'cmd': 'pip install -r requirements.txt && python bot.py', 
            'cwd': '', 
            'logs': [
                f"🤖 Telegram Bot created at {time.strftime('%H:%M:%S')}",
                f"🔑 Token: {token[:10]}...{token[-5:]}",
                "▶️ Use 'Start' to launch the bot"
            ],
            'auto_restart': True, 
            'restart_interval': '24h', 
            'last_start_time': 0,
            'status': 'stopped', 
            'path': server_path,
            'owner': 'user'
        }
        save_servers()
        return jsonify({'status': 'ok', 'server_name': server_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Keep Alive Ping Endpoint ---
@app.route("/api/ping")
def ping():
    """Keep Alive পিং এন্ডপয়েন্ট - Render-কে সক্রিয় রাখে"""
    return jsonify({
        "status": "alive", 
        "time": time.time(),
        "servers": len(SERVERS),
        "running": sum(1 for s in SERVERS.values() if s.get('status') == 'running')
    })

@app.route("/ping")
def ping_simple():
    return "alive"

@app.route("/json")
def json_alive():
    return jsonify({"status": "alive", "time": time.time()})

# --- Health Check (Render Restart Prevent) ---
@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "servers": len(SERVERS),
        "running": sum(1 for s in SERVERS.values() if s.get('status') == 'running'),
        "uptime": time.time() - RESTART_DATA.get("last_restart", time.time())
    })

# --- Error Handlers ---
@app.errorhandler(404)
def not_found(e):
    if session.get('logged_in'):
        return redirect(url_for('index'))
    return redirect(url_for('login'))

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

# --- RUN SERVER ---
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    port = os.environ.get('PORT', 8080)
    debug = os.environ.get("DEBUG", "False").lower() == "true"
    
    print("=" * 50)
    print("SUMON PREMIUM VPS - Starting...")
    print("=" * 50)
    print(f"Port: {port}")
    print(f"Debug: {debug}")
    print("=" * 50)
    print("Admin Password: sumon000")
    print("User Password: sumonfree")
    print("=" * 50)
    print("✅ Keep Alive: ACTIVE (every 5 min)")
    print("✅ Auto Restart: ACTIVE (every 30 sec)")
    print("✅ Restart Protection: ACTIVE (30 min cooldown)")
    print("=" * 50)
    
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)