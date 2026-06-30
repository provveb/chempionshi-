from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import sqlite3, os, hashlib, secrets
from datetime import datetime
from github_sync import mark_dirty, start_background_sync

app = Flask(__name__, static_folder='.')
app.secret_key = 'cs2uz_pro_vveb_secret_2024_x3d'
CORS(app, supports_credentials=True, origins='*')

@app.after_request
def sync_db_on_write(response):
    # Ma'lumotni o'zgartiruvchi so'rovlardan keyin GitHub'ga push uchun belgilab qo'yamiz
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and response.status_code < 400:
        mark_dirty()
    return response

DB = 'tournament.db'

def get_db():
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            captain_name TEXT NOT NULL,
            captain_steam TEXT NOT NULL,
            captain_discord TEXT DEFAULT '',
            contact TEXT NOT NULL,
            logo_url TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            points INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            maps_won INTEGER DEFAULT 0,
            maps_lost INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            nickname TEXT NOT NULL,
            steam_id TEXT NOT NULL,
            steam_url TEXT DEFAULT '',
            telegram TEXT DEFAULT '',
            discord TEXT DEFAULT '',
            role TEXT DEFAULT 'Rifler',
            rank TEXT DEFAULT 'Unranked',
            is_reserve INTEGER DEFAULT 0,
            is_leader INTEGER DEFAULT 0,
            kills INTEGER DEFAULT 0,
            deaths INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            rating REAL DEFAULT 0.0,
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team1_id INTEGER,
            team2_id INTEGER,
            score1 INTEGER DEFAULT 0,
            score2 INTEGER DEFAULT 0,
            map TEXT DEFAULT 'TBD',
            stage TEXT DEFAULT 'Group Stage',
            status TEXT DEFAULT 'scheduled',
            winner_id INTEGER,
            scheduled_at TEXT,
            played_at TEXT,
            FOREIGN KEY (team1_id) REFERENCES teams(id),
            FOREIGN KEY (team2_id) REFERENCES teams(id)
        );
        CREATE TABLE IF NOT EXISTS tournament_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        INSERT OR IGNORE INTO tournament_settings VALUES ('name', 'CS2 UZ Championship');
        INSERT OR IGNORE INTO tournament_settings VALUES ('max_teams', '16');
        INSERT OR IGNORE INTO tournament_settings VALUES ('max_players_per_team', '6');
        INSERT OR IGNORE INTO tournament_settings VALUES ('status', 'registration');
        INSERT OR IGNORE INTO tournament_settings VALUES ('prize_pool', '$500');
        INSERT OR IGNORE INTO tournament_settings VALUES ('rules', 'MR12, 5v5, Standard CS2 qoidalari.');
        INSERT OR IGNORE INTO tournament_settings VALUES ('stage', 'Guruh bosqichi');
    ''')
    pw_hash = hashlib.sha256('slx12344'.encode()).hexdigest()
    c.execute("DELETE FROM admins")
    c.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", ('pro_vveb', pw_hash))

    # Migration: add new columns if they don't exist (for existing databases)
    migrations = [
        "ALTER TABLE players ADD COLUMN telegram TEXT DEFAULT ''",
        "ALTER TABLE players ADD COLUMN discord TEXT DEFAULT ''",
        "ALTER TABLE players ADD COLUMN is_reserve INTEGER DEFAULT 0",
        "ALTER TABLE players ADD COLUMN is_leader INTEGER DEFAULT 0",
    ]
    for sql in migrations:
        try:
            c.execute(sql)
        except Exception:
            pass  # Column already exists

    conn.commit()
    conn.close()

# ─── AUTH ────────────────────────────────────────────────────────────────────
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json(force=True)
    pw_hash = hashlib.sha256(data.get('password','').encode()).hexdigest()
    conn = get_db()
    try:
        admin = conn.execute("SELECT * FROM admins WHERE username=? AND password_hash=?",
                             (data.get('username',''), pw_hash)).fetchone()
        if admin:
            session['admin'] = True
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'Noto\'g\'ri login yoki parol'}), 401
    finally:
        conn.close()

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin', None)
    return jsonify({'ok': True})

@app.route('/api/admin/check', methods=['GET'])
def admin_check():
    return jsonify({'admin': session.get('admin', False)})

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin'):
            return jsonify({'error': 'Ruxsat yo\'q'}), 403
        return f(*args, **kwargs)
    return decorated

# ─── PUBLIC ──────────────────────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db()
    try:
        rows = conn.execute("SELECT key, value FROM tournament_settings").fetchall()
        return jsonify({r['key']: r['value'] for r in rows})
    finally:
        conn.close()

@app.route('/api/teams', methods=['GET'])
def get_teams():
    conn = get_db()
    try:
        teams = conn.execute("""
            SELECT t.*, COUNT(p.id) as player_count
            FROM teams t LEFT JOIN players p ON p.team_id = t.id
            WHERE t.status = 'approved'
            GROUP BY t.id ORDER BY t.points DESC, t.wins DESC
        """).fetchall()
        return jsonify([dict(t) for t in teams])
    finally:
        conn.close()

@app.route('/api/teams/<int:team_id>/players', methods=['GET'])
def get_team_players(team_id):
    conn = get_db()
    try:
        players = conn.execute("SELECT * FROM players WHERE team_id=?", (team_id,)).fetchall()
        return jsonify([dict(p) for p in players])
    finally:
        conn.close()

@app.route('/api/matches', methods=['GET'])
def get_matches():
    conn = get_db()
    try:
        matches = conn.execute("""
            SELECT m.*, t1.name as team1_name, t1.logo_url as team1_logo,
                   t2.name as team2_name, t2.logo_url as team2_logo, w.name as winner_name
            FROM matches m
            LEFT JOIN teams t1 ON t1.id = m.team1_id
            LEFT JOIN teams t2 ON t2.id = m.team2_id
            LEFT JOIN teams w ON w.id = m.winner_id
            ORDER BY m.id DESC
        """).fetchall()
        return jsonify([dict(m) for m in matches])
    finally:
        conn.close()

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    conn = get_db()
    try:
        players = conn.execute("""
            SELECT p.*, t.name as team_name FROM players p
            JOIN teams t ON t.id = p.team_id
            WHERE t.status = 'approved'
            ORDER BY p.rating DESC, p.kills DESC LIMIT 50
        """).fetchall()
        return jsonify([dict(p) for p in players])
    finally:
        conn.close()

# ─── REGISTRATION ─────────────────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def register_team():
    conn = get_db()
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({'ok': False, 'error': 'Ma\'lumot yuborilmadi'}), 400

        s = conn.execute("SELECT value FROM tournament_settings WHERE key='status'").fetchone()
        if s and s['value'] != 'registration':
            return jsonify({'ok': False, 'error': 'Ro\'yxatga olish yopiq'}), 400

        required = ['name', 'captain_name', 'captain_steam', 'contact']
        for field in required:
            if not data.get(field, '').strip():
                return jsonify({'ok': False, 'error': f'{field} maydoni to\'ldirilmagan'}), 400

        players = data.get('players', [])
        valid_players = [p for p in players if p.get('nickname','').strip() and p.get('steam_id','').strip()]
        if len(valid_players) < 5:
            return jsonify({'ok': False, 'error': 'Kamida 5 ta o\'yinchi kiritilishi kerak'}), 400

        c = conn.cursor()
        c.execute("""
            INSERT INTO teams (name, captain_name, captain_steam, captain_discord, contact, logo_url)
            VALUES (?,?,?,?,?,?)
        """, (
            data['name'].strip(), data['captain_name'].strip(),
            data['captain_steam'].strip(), data.get('captain_discord','').strip(),
            data['contact'].strip(), data.get('logo_url','').strip()
        ))
        team_id = c.lastrowid

        max_p = int(conn.execute("SELECT value FROM tournament_settings WHERE key='max_players_per_team'").fetchone()['value'])
        for idx, p in enumerate(valid_players[:max_p]):
            c.execute("""
                INSERT INTO players (team_id, nickname, steam_id, steam_url, telegram, discord, role, rank, is_reserve, is_leader)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (team_id, p['nickname'].strip(), p['steam_id'].strip(),
                  p.get('steam_url','').strip(),
                  p.get('telegram','').strip(),
                  p.get('discord','').strip(),
                  p.get('role','') or '', p.get('rank','') or '',
                  1 if p.get('is_reserve') else 0,
                  1 if (p.get('is_leader') or idx==0) else 0))

        conn.commit()
        return jsonify({'ok': True, 'team_id': team_id})

    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({'ok': False, 'error': 'Bu jamoa nomi allaqachon ro\'yxatda mavjud'}), 400
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

# ─── ADMIN ────────────────────────────────────────────────────────────────────
@app.route('/api/admin/teams', methods=['GET'])
@admin_required
def admin_get_teams():
    conn = get_db()
    try:
        teams = conn.execute("""
            SELECT t.*, COUNT(p.id) as player_count
            FROM teams t LEFT JOIN players p ON p.team_id = t.id
            GROUP BY t.id ORDER BY t.created_at DESC
        """).fetchall()
        return jsonify([dict(t) for t in teams])
    finally:
        conn.close()

@app.route('/api/admin/teams/<int:team_id>', methods=['GET'])
@admin_required
def admin_get_team(team_id):
    conn = get_db()
    try:
        team = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
        players = conn.execute("SELECT * FROM players WHERE team_id=?", (team_id,)).fetchall()
        if not team:
            return jsonify({'error': 'Topilmadi'}), 404
        return jsonify({'team': dict(team), 'players': [dict(p) for p in players]})
    finally:
        conn.close()

@app.route('/api/admin/teams/<int:team_id>/status', methods=['PUT'])
@admin_required
def update_team_status(team_id):
    conn = get_db()
    try:
        data = request.get_json(force=True)
        conn.execute("UPDATE teams SET status=? WHERE id=?", (data['status'], team_id))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/teams/<int:team_id>', methods=['PUT'])
@admin_required
def update_team_info(team_id):
    conn = get_db()
    try:
        data = request.get_json(force=True)
        conn.execute("""
            UPDATE teams SET name=?, captain_name=?, captain_steam=?, captain_discord=?, contact=?, logo_url=?
            WHERE id=?
        """, (
            data.get('name','').strip(), data.get('captain_name','').strip(),
            data.get('captain_steam','').strip(), data.get('captain_discord','').strip(),
            data.get('contact','').strip(), data.get('logo_url','').strip(),
            team_id
        ))
        conn.commit()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({'ok': False, 'error': 'Bu jamoa nomi allaqachon mavjud'}), 400
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/players/<int:player_id>', methods=['PUT'])
@admin_required
def update_player_info(player_id):
    conn = get_db()
    try:
        data = request.get_json(force=True)
        conn.execute("""
            UPDATE players SET nickname=?, steam_id=?, steam_url=?, telegram=?, discord=?, role=?, rank=?, is_reserve=?, is_leader=?
            WHERE id=?
        """, (
            data.get('nickname','').strip(), data.get('steam_id','').strip(),
            data.get('steam_url','').strip(), data.get('telegram','').strip(),
            data.get('discord','').strip(), data.get('role','') or '', data.get('rank','') or '',
            1 if data.get('is_reserve') else 0, 1 if data.get('is_leader') else 0, player_id
        ))
        if data.get('is_leader'):
            team_row = conn.execute("SELECT team_id FROM players WHERE id=?", (player_id,)).fetchone()
            if team_row:
                conn.execute("UPDATE players SET is_leader=0 WHERE team_id=? AND id!=?", (team_row['team_id'], player_id))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/teams/<int:team_id>/players', methods=['POST'])
@admin_required
def add_player(team_id):
    conn = get_db()
    try:
        data = request.get_json(force=True)
        if not data.get('nickname','').strip() or not data.get('steam_id','').strip():
            return jsonify({'ok': False, 'error': 'Nickname va Steam ID majburiy'}), 400
        c = conn.cursor()
        c.execute("""
            INSERT INTO players (team_id, nickname, steam_id, steam_url, telegram, discord, role, rank, is_reserve, is_leader)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            team_id, data.get('nickname','').strip(), data.get('steam_id','').strip(),
            data.get('steam_url','').strip(), data.get('telegram','').strip(),
            data.get('discord','').strip(), data.get('role','') or '', data.get('rank','') or '',
            1 if data.get('is_reserve') else 0, 1 if data.get('is_leader') else 0
        ))
        if data.get('is_leader'):
            conn.execute("UPDATE players SET is_leader=0 WHERE team_id=? AND id!=?", (team_id, c.lastrowid))
        conn.commit()
        return jsonify({'ok': True, 'player_id': c.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/players/<int:player_id>', methods=['DELETE'])
@admin_required
def delete_player(player_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM players WHERE id=?", (player_id,))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/teams/<int:team_id>', methods=['DELETE'])
@admin_required
def delete_team(team_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM matches WHERE team1_id=? OR team2_id=?", (team_id, team_id))
        conn.execute("DELETE FROM teams WHERE id=?", (team_id,))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/matches', methods=['POST'])
@admin_required
def create_match():
    conn = get_db()
    try:
        data = request.get_json(force=True)
        c = conn.cursor()
        c.execute("""
            INSERT INTO matches (team1_id, team2_id, map, stage, scheduled_at)
            VALUES (?,?,?,?,?)
        """, (data['team1_id'], data['team2_id'], data.get('map','TBD'),
              data.get('stage','Group Stage'), data.get('scheduled_at','')))
        conn.commit()
        return jsonify({'ok': True, 'match_id': c.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/matches/<int:match_id>/result', methods=['PUT'])
@admin_required
def update_result(match_id):
    conn = get_db()
    try:
        data = request.get_json(force=True)
        s1, s2 = int(data['score1']), int(data['score2'])
        winner_id = int(data['team1_id']) if s1 > s2 else int(data['team2_id']) if s2 > s1 else None
        conn.execute("""
            UPDATE matches SET score1=?,score2=?,winner_id=?,status='finished',played_at=datetime('now')
            WHERE id=?
        """, (s1, s2, winner_id, match_id))
        if winner_id:
            loser_id = int(data['team2_id']) if winner_id == int(data['team1_id']) else int(data['team1_id'])
            conn.execute("UPDATE teams SET wins=wins+1,points=points+3,maps_won=maps_won+? WHERE id=?", (max(s1,s2), winner_id))
            conn.execute("UPDATE teams SET losses=losses+1,maps_lost=maps_lost+? WHERE id=?", (min(s1,s2), loser_id))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/matches/<int:match_id>', methods=['DELETE'])
@admin_required
def delete_match(match_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM matches WHERE id=?", (match_id,))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/players/<int:player_id>/stats', methods=['PUT'])
@admin_required
def update_player_stats(player_id):
    conn = get_db()
    try:
        data = request.get_json(force=True)
        k = int(data.get('kills',0)); d = max(int(data.get('deaths',1)),1); a = int(data.get('assists',0))
        rating = round((k + a*0.5) / d * 0.7 + (k/d) * 0.3, 2)
        conn.execute("UPDATE players SET kills=?,deaths=?,assists=?,rating=? WHERE id=?", (k,d,a,rating,player_id))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/settings', methods=['PUT'])
@admin_required
def update_settings():
    conn = get_db()
    try:
        data = request.get_json(force=True)
        for k, v in data.items():
            conn.execute("INSERT OR REPLACE INTO tournament_settings (key,value) VALUES (?,?)", (k, str(v)))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/bracket/manual', methods=['POST'])
@admin_required
def create_manual_bracket():
    conn = get_db()
    try:
        data = request.get_json(force=True)
        pairs = data.get('pairs', [])  # [{team1_id, team2_id, stage, map}, ...]
        if not pairs:
            return jsonify({'ok': False, 'error': 'Juftliklar yuborilmadi'}), 400

        # Delete existing scheduled matches if requested
        if data.get('clear_scheduled', True):
            conn.execute("DELETE FROM matches WHERE status='scheduled'")

        created = 0
        for p in pairs:
            t1 = p.get('team1_id')
            t2 = p.get('team2_id')
            if not t1:
                continue
            conn.execute(
                "INSERT INTO matches (team1_id, team2_id, stage, map, status) VALUES (?,?,?,?,'scheduled')",
                (t1, t2 if t2 else None, p.get('stage', 'Quarterfinals'), p.get('map', 'TBD'))
            )
            created += 1

        conn.commit()
        return jsonify({'ok': True, 'created': created})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/bracket/generate', methods=['POST'])
@admin_required
def generate_bracket():
    conn = get_db()
    try:
        teams = conn.execute(
            "SELECT id FROM teams WHERE status='approved' ORDER BY points DESC, wins DESC, id ASC"
        ).fetchall()
        ids = [t['id'] for t in teams]
        if len(ids) < 2:
            return jsonify({'ok': False, 'error': 'Kamida 2 ta tasdiqlangan jamoa kerak'})

        while len(ids) < 8:
            ids.append(None)
        ids = ids[:8]

        conn.execute("DELETE FROM matches WHERE status='scheduled'")

        seed_pairs = [(0,7),(3,4),(2,5),(1,6)]
        created = 0
        for i,(a,b) in enumerate(seed_pairs):
            t1 = ids[a]
            t2 = ids[b]
            if t1:
                conn.execute(
                    "INSERT INTO matches (team1_id,team2_id,stage,status) VALUES (?,?,'Quarterfinals','scheduled')",
                    (t1, t2)
                )
                created += 1
        conn.commit()
        return jsonify({'ok': True, 'pairs': created})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/stats/overview', methods=['GET'])
@admin_required
def admin_overview():
    conn = get_db()
    try:
        def cnt(q): return conn.execute(q).fetchone()[0]
        r = {
            'total_teams': cnt("SELECT COUNT(*) FROM teams"),
            'approved_teams': cnt("SELECT COUNT(*) FROM teams WHERE status='approved'"),
            'pending_teams': cnt("SELECT COUNT(*) FROM teams WHERE status='pending'"),
            'rejected_teams': cnt("SELECT COUNT(*) FROM teams WHERE status='rejected'"),
            'total_players': cnt("SELECT COUNT(*) FROM players"),
            'total_matches': cnt("SELECT COUNT(*) FROM matches"),
            'finished_matches': cnt("SELECT COUNT(*) FROM matches WHERE status='finished'"),
        }
        return jsonify(r)
    finally:
        conn.close()

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# Gunicorn orqali ishga tushganda ham (web: gunicorn main:app) shu yerda chaqiriladi
init_db()
start_background_sync()

if __name__ == '__main__':
    print("✅ CS2 Tournament ishga tushdi → http://localhost:5000")
    print("🔐 Admin: pro_vveb / ryzn77800x3d")
    app.run(debug=True, host='0.0.0.0', port=5000)