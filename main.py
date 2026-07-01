from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import hashlib
from datetime import datetime
from functools import wraps

import store

app = Flask(__name__, static_folder='.')
app.secret_key = 'cs2uz_pro_vveb_secret_2024_x3d'
CORS(app, supports_credentials=True, origins='*')

store.init_store()

# ─── AUTH ────────────────────────────────────────────────────────────────────
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json(force=True)
    pw_hash = hashlib.sha256(data.get('password', '').encode()).hexdigest()
    d = store.load()
    admin = d.get('admin', {})
    if data.get('username', '') == admin.get('username') and pw_hash == admin.get('password_hash'):
        session['admin'] = True
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Noto\'g\'ri login yoki parol'}), 401


@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin', None)
    return jsonify({'ok': True})


@app.route('/api/admin/check', methods=['GET'])
def admin_check():
    return jsonify({'admin': session.get('admin', False)})


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin'):
            return jsonify({'error': 'Ruxsat yo\'q'}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/api/admin/password', methods=['PUT'])
@admin_required
def change_admin_password():
    data = request.get_json(force=True)
    current = data.get('current_password', '')
    new = data.get('new_password', '')

    if not new or len(new) < 6:
        return jsonify({'ok': False, 'error': "Yangi parol kamida 6 ta belgidan iborat bo'lishi kerak"}), 400

    d = store.load()
    current_hash = hashlib.sha256(current.encode()).hexdigest()
    if current_hash != d['admin']['password_hash']:
        return jsonify({'ok': False, 'error': "Joriy parol noto'g'ri"}), 400

    d['admin']['password_hash'] = hashlib.sha256(new.encode()).hexdigest()
    store.save(d, commit_message="Admin paroli o'zgartirildi")
    return jsonify({'ok': True})
# ─── PUBLIC ──────────────────────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(store.load()['settings'])


@app.route('/api/teams', methods=['GET'])
def get_teams():
    d = store.load()
    teams = [t for t in d['teams'] if t.get('status') == 'approved']
    for t in teams:
        t['player_count'] = sum(1 for p in d['players'] if p['team_id'] == t['id'])
    teams.sort(key=lambda t: (-t.get('points', 0), -t.get('wins', 0)))
    return jsonify(teams)


@app.route('/api/teams/<int:team_id>/players', methods=['GET'])
def get_team_players(team_id):
    d = store.load()
    players = [p for p in d['players'] if p['team_id'] == team_id]
    return jsonify(players)


@app.route('/api/matches', methods=['GET'])
def get_matches():
    d = store.load()
    teams_by_id = {t['id']: t for t in d['teams']}
    matches = []
    for m in sorted(d['matches'], key=lambda x: -x['id']):
        m = dict(m)
        t1 = teams_by_id.get(m.get('team1_id'))
        t2 = teams_by_id.get(m.get('team2_id'))
        w = teams_by_id.get(m.get('winner_id'))
        m['team1_name'] = t1['name'] if t1 else None
        m['team1_logo'] = t1['logo_url'] if t1 else None
        m['team2_name'] = t2['name'] if t2 else None
        m['team2_logo'] = t2['logo_url'] if t2 else None
        m['winner_name'] = w['name'] if w else None
        matches.append(m)
    return jsonify(matches)


@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    d = store.load()
    approved_ids = {t['id'] for t in d['teams'] if t.get('status') == 'approved'}
    teams_by_id = {t['id']: t for t in d['teams']}
    players = [dict(p) for p in d['players'] if p['team_id'] in approved_ids]
    for p in players:
        p['team_name'] = teams_by_id[p['team_id']]['name']
    players.sort(key=lambda p: (-p.get('rating', 0), -p.get('kills', 0)))
    return jsonify(players[:50])


# ─── REGISTRATION ─────────────────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def register_team():
    data = request.get_json(force=True)
    if not data:
        return jsonify({'ok': False, 'error': 'Ma\'lumot yuborilmadi'}), 400

    d = store.load()

    if d['settings'].get('status') != 'registration':
        return jsonify({'ok': False, 'error': 'Ro\'yxatga olish yopiq'}), 400

    required = ['name', 'captain_name', 'captain_steam', 'contact']
    for field in required:
        if not data.get(field, '').strip():
            return jsonify({'ok': False, 'error': f'{field} maydoni to\'ldirilmagan'}), 400

    name = data['name'].strip()
    if any(t['name'].lower() == name.lower() for t in d['teams']):
        return jsonify({'ok': False, 'error': 'Bu jamoa nomi allaqachon ro\'yxatda mavjud'}), 400

    players_in = data.get('players', [])
    valid_players = [p for p in players_in if p.get('nickname', '').strip() and p.get('steam_id', '').strip()]
    if len(valid_players) < 5:
        return jsonify({'ok': False, 'error': 'Kamida 5 ta o\'yinchi kiritilishi kerak'}), 400

    team_id = store.next_id(d, 'team')
    team = {
        'id': team_id,
        'name': name,
        'captain_name': data['captain_name'].strip(),
        'captain_steam': data['captain_steam'].strip(),
        'captain_discord': data.get('captain_discord', '').strip(),
        'contact': data['contact'].strip(),
        'logo_url': data.get('logo_url', '').strip(),
        'status': 'pending',
        'points': 0,
        'wins': 0,
        'losses': 0,
        'maps_won': 0,
        'maps_lost': 0,
        'created_at': datetime.utcnow().isoformat(),
    }
    d['teams'].append(team)

    max_p = int(d['settings'].get('max_players_per_team', 6))
    for idx, p in enumerate(valid_players[:max_p]):
        player_id = store.next_id(d, 'player')
        d['players'].append({
            'id': player_id,
            'team_id': team_id,
            'nickname': p['nickname'].strip(),
            'steam_id': p['steam_id'].strip(),
            'steam_url': p.get('steam_url', '').strip(),
            'telegram': p.get('telegram', '').strip(),
            'discord': p.get('discord', '').strip(),
            'role': p.get('role', '') or '',
            'is_reserve': 1 if p.get('is_reserve') else 0,
            'is_leader': 1 if (p.get('is_leader') or idx == 0) else 0,
            'kills': 0,
            'deaths': 0,
            'assists': 0,
            'rating': 0.0,
        })

    store.save(d, commit_message=f"Yangi jamoa qo'shildi: {name}")
    return jsonify({'ok': True, 'team_id': team_id})


# ─── ADMIN: TEAMS ────────────────────────────────────────────────────────────
@app.route('/api/admin/teams', methods=['GET'])
@admin_required
def admin_get_teams():
    d = store.load()
    teams = [dict(t) for t in d['teams']]
    for t in teams:
        t['player_count'] = sum(1 for p in d['players'] if p['team_id'] == t['id'])
    teams.sort(key=lambda t: t.get('created_at', ''), reverse=True)
    return jsonify(teams)


@app.route('/api/admin/teams/<int:team_id>', methods=['GET'])
@admin_required
def admin_get_team(team_id):
    d = store.load()
    team = next((t for t in d['teams'] if t['id'] == team_id), None)
    if not team:
        return jsonify({'error': 'Topilmadi'}), 404
    players = [p for p in d['players'] if p['team_id'] == team_id]
    return jsonify({'team': team, 'players': players})


@app.route('/api/admin/teams/<int:team_id>/status', methods=['PUT'])
@admin_required
def update_team_status(team_id):
    data = request.get_json(force=True)
    d = store.load()
    team = next((t for t in d['teams'] if t['id'] == team_id), None)
    if not team:
        return jsonify({'ok': False, 'error': 'Topilmadi'}), 404
    team['status'] = data['status']
    store.save(d, commit_message=f"Jamoa holati o'zgartirildi: {team['name']} -> {data['status']}")
    return jsonify({'ok': True})


@app.route('/api/admin/teams/<int:team_id>', methods=['PUT'])
@admin_required
def update_team_info(team_id):
    data = request.get_json(force=True)
    d = store.load()
    team = next((t for t in d['teams'] if t['id'] == team_id), None)
    if not team:
        return jsonify({'ok': False, 'error': 'Topilmadi'}), 404
    new_name = data.get('name', '').strip()
    if any(t['name'].lower() == new_name.lower() and t['id'] != team_id for t in d['teams']):
        return jsonify({'ok': False, 'error': 'Bu jamoa nomi allaqachon mavjud'}), 400
    team.update({
        'name': new_name,
        'captain_name': data.get('captain_name', '').strip(),
        'captain_steam': data.get('captain_steam', '').strip(),
        'captain_discord': data.get('captain_discord', '').strip(),
        'contact': data.get('contact', '').strip(),
        'logo_url': data.get('logo_url', '').strip(),
    })
    store.save(d, commit_message=f"Jamoa ma'lumotlari yangilandi: {team['name']}")
    return jsonify({'ok': True})


@app.route('/api/admin/teams/<int:team_id>', methods=['DELETE'])
@admin_required
def delete_team(team_id):
    d = store.load()
    d['matches'] = [m for m in d['matches'] if m.get('team1_id') != team_id and m.get('team2_id') != team_id]
    d['players'] = [p for p in d['players'] if p['team_id'] != team_id]
    d['teams'] = [t for t in d['teams'] if t['id'] != team_id]
    store.save(d, commit_message=f"Jamoa o'chirildi (id={team_id})")
    return jsonify({'ok': True})


# ─── ADMIN: PLAYERS ──────────────────────────────────────────────────────────
@app.route('/api/admin/players/<int:player_id>', methods=['PUT'])
@admin_required
def update_player_info(player_id):
    data = request.get_json(force=True)
    d = store.load()
    player = next((p for p in d['players'] if p['id'] == player_id), None)
    if not player:
        return jsonify({'ok': False, 'error': 'Topilmadi'}), 404
    player.update({
        'nickname': data.get('nickname', '').strip(),
        'steam_id': data.get('steam_id', '').strip(),
        'steam_url': data.get('steam_url', '').strip(),
        'telegram': data.get('telegram', '').strip(),
        'discord': data.get('discord', '').strip(),
        'role': data.get('role', '') or '',
        'is_reserve': 1 if data.get('is_reserve') else 0,
        'is_leader': 1 if data.get('is_leader') else 0,
    })
    if data.get('is_leader'):
        for p in d['players']:
            if p['team_id'] == player['team_id'] and p['id'] != player_id:
                p['is_leader'] = 0
    store.save(d, commit_message=f"O'yinchi yangilandi: {player['nickname']}")
    return jsonify({'ok': True})


@app.route('/api/admin/players/<int:player_id>', methods=['DELETE'])
@admin_required
def delete_player(player_id):
    d = store.load()
    d['players'] = [p for p in d['players'] if p['id'] != player_id]
    store.save(d, commit_message=f"O'yinchi o'chirildi (id={player_id})")
    return jsonify({'ok': True})


@app.route('/api/admin/teams/<int:team_id>/players', methods=['POST'])
@admin_required
def add_player(team_id):
    data = request.get_json(force=True)
    if not data.get('nickname', '').strip() or not data.get('steam_id', '').strip():
        return jsonify({'ok': False, 'error': 'Nickname va Steam ID majburiy'}), 400
    d = store.load()
    player_id = store.next_id(d, 'player')
    player = {
        'id': player_id,
        'team_id': team_id,
        'nickname': data.get('nickname', '').strip(),
        'steam_id': data.get('steam_id', '').strip(),
        'steam_url': data.get('steam_url', '').strip(),
        'telegram': data.get('telegram', '').strip(),
        'discord': data.get('discord', '').strip(),
        'role': data.get('role', '') or '',
        'is_reserve': 1 if data.get('is_reserve') else 0,
        'is_leader': 1 if data.get('is_leader') else 0,
        'kills': 0, 'deaths': 0, 'assists': 0, 'rating': 0.0,
    }
    d['players'].append(player)
    if data.get('is_leader'):
        for p in d['players']:
            if p['team_id'] == team_id and p['id'] != player_id:
                p['is_leader'] = 0
    store.save(d, commit_message=f"Yangi o'yinchi qo'shildi: {player['nickname']}")
    return jsonify({'ok': True, 'player_id': player_id})


@app.route('/api/admin/players/<int:player_id>/stats', methods=['PUT'])
@admin_required
def update_player_stats(player_id):
    data = request.get_json(force=True)
    d = store.load()
    player = next((p for p in d['players'] if p['id'] == player_id), None)
    if not player:
        return jsonify({'ok': False, 'error': 'Topilmadi'}), 404
    k = int(data.get('kills', 0))
    dd = max(int(data.get('deaths', 1)), 1)
    a = int(data.get('assists', 0))
    rating = round((k + a * 0.5) / dd * 0.7 + (k / dd) * 0.3, 2)
    player.update({'kills': k, 'deaths': dd, 'assists': a, 'rating': rating})
    store.save(d, commit_message=f"O'yinchi statistikasi yangilandi: {player['nickname']}")
    return jsonify({'ok': True})


# ─── ADMIN: MATCHES ──────────────────────────────────────────────────────────
@app.route('/api/admin/matches', methods=['POST'])
@admin_required
def create_match():
    data = request.get_json(force=True)
    d = store.load()
    match_id = store.next_id(d, 'match')
    d['matches'].append({
        'id': match_id,
        'team1_id': data['team1_id'],
        'team2_id': data['team2_id'],
        'score1': 0, 'score2': 0,
        'map': data.get('map', 'TBD'),
        'stage': data.get('stage', 'Group Stage'),
        'status': 'scheduled',
        'winner_id': None,
        'scheduled_at': data.get('scheduled_at', ''),
        'played_at': None,
    })
    store.save(d, commit_message="Yangi o'yin yaratildi")
    return jsonify({'ok': True, 'match_id': match_id})


@app.route('/api/admin/matches/<int:match_id>/result', methods=['PUT'])
@admin_required
def update_result(match_id):
    data = request.get_json(force=True)
    d = store.load()
    match = next((m for m in d['matches'] if m['id'] == match_id), None)
    if not match:
        return jsonify({'ok': False, 'error': 'Topilmadi'}), 404
    s1, s2 = int(data['score1']), int(data['score2'])
    t1_id, t2_id = int(data['team1_id']), int(data['team2_id'])
    winner_id = t1_id if s1 > s2 else t2_id if s2 > s1 else None
    match.update({
        'score1': s1, 'score2': s2, 'winner_id': winner_id,
        'status': 'finished', 'played_at': datetime.utcnow().isoformat(),
    })
    if winner_id:
        loser_id = t2_id if winner_id == t1_id else t1_id
        winner = next(t for t in d['teams'] if t['id'] == winner_id)
        loser = next(t for t in d['teams'] if t['id'] == loser_id)
        winner['wins'] += 1
        winner['points'] += 3
        winner['maps_won'] += max(s1, s2)
        loser['losses'] += 1
        loser['maps_lost'] += min(s1, s2)
    store.save(d, commit_message=f"O'yin natijasi kiritildi (id={match_id})")
    return jsonify({'ok': True})


@app.route('/api/admin/matches/<int:match_id>', methods=['DELETE'])
@admin_required
def delete_match(match_id):
    d = store.load()
    d['matches'] = [m for m in d['matches'] if m['id'] != match_id]
    store.save(d, commit_message=f"O'yin o'chirildi (id={match_id})")
    return jsonify({'ok': True})


# ─── BRACKET BUILDER (drag & drop) ───────────────────────────────────────────
# Bracket pozitsiyalari va g'olib avtomatik o'tadigan keyingi pozitsiya/slot xaritasi
BRACKET_STAGE = {
    'QF1': 'Quarterfinals', 'QF2': 'Quarterfinals', 'QF3': 'Quarterfinals', 'QF4': 'Quarterfinals',
    'SF1': 'Semifinals', 'SF2': 'Semifinals', 'GF': 'Grand Final',
}
BRACKET_ADVANCE = {
    'QF1': ('SF1', 1), 'QF2': ('SF1', 2),
    'QF3': ('SF2', 1), 'QF4': ('SF2', 2),
    'SF1': ('GF', 1), 'SF2': ('GF', 2),
}


def _find_bracket_match(d, bracket_pos):
    return next((m for m in d['matches'] if m.get('bracket_pos') == bracket_pos), None)


def _get_or_create_bracket_match(d, bracket_pos):
    m = _find_bracket_match(d, bracket_pos)
    if m:
        return m
    match_id = store.next_id(d, 'match')
    m = {
        'id': match_id, 'team1_id': None, 'team2_id': None,
        'score1': 0, 'score2': 0, 'map': 'TBD',
        'stage': BRACKET_STAGE.get(bracket_pos, 'Group Stage'),
        'status': 'scheduled', 'winner_id': None,
        'scheduled_at': '', 'played_at': None,
        'bracket_pos': bracket_pos,
    }
    d['matches'].append(m)
    return m


@app.route('/api/admin/bracket', methods=['GET'])
@admin_required
def get_admin_bracket():
    d = store.load()
    matches = [m for m in d['matches'] if m.get('bracket_pos')]
    return jsonify({'ok': True, 'matches': matches})


@app.route('/api/admin/bracket/slot', methods=['POST'])
@admin_required
def assign_bracket_slot():
    data = request.get_json(force=True)
    bracket_pos = data.get('bracket_pos')
    slot = data.get('slot')
    team_id = data.get('team_id')
    if bracket_pos not in BRACKET_STAGE or slot not in (1, 2):
        return jsonify({'ok': False, 'error': "Noto'g'ri bracket pozitsiyasi"}), 400
    d = store.load()
    m = _get_or_create_bracket_match(d, bracket_pos)
    if m['status'] == 'finished':
        return jsonify({'ok': False, 'error': "Bu o'yin allaqachon yakunlangan"}), 400
    m['team1_id' if slot == 1 else 'team2_id'] = team_id
    store.save(d, commit_message=f"Bracket: {bracket_pos} slot {slot} yangilandi")
    return jsonify({'ok': True})


@app.route('/api/admin/bracket/<bracket_pos>/result', methods=['PUT'])
@admin_required
def save_bracket_result(bracket_pos):
    data = request.get_json(force=True)
    d = store.load()
    m = _find_bracket_match(d, bracket_pos)
    if not m:
        return jsonify({'ok': False, 'error': 'Topilmadi'}), 404
    if not m.get('team1_id') or not m.get('team2_id'):
        return jsonify({'ok': False, 'error': "Ikkala jamoa ham tanlanmagan"}), 400
    s1, s2 = int(data['score1']), int(data['score2'])
    if s1 == s2:
        return jsonify({'ok': False, 'error': "Durrang bo'lishi mumkin emas"}), 400
    winner_id = m['team1_id'] if s1 > s2 else m['team2_id']
    loser_id = m['team2_id'] if winner_id == m['team1_id'] else m['team1_id']
    m.update({
        'score1': s1, 'score2': s2, 'winner_id': winner_id,
        'status': 'finished', 'played_at': datetime.utcnow().isoformat(),
    })
    winner = next((t for t in d['teams'] if t['id'] == winner_id), None)
    loser = next((t for t in d['teams'] if t['id'] == loser_id), None)
    if winner:
        winner['wins'] += 1
        winner['points'] += 3
        winner['maps_won'] += max(s1, s2)
    if loser:
        loser['losses'] += 1
        loser['maps_lost'] += min(s1, s2)

    # G'olibni avtomatik keyingi bosqichga o'tkazish
    if bracket_pos in BRACKET_ADVANCE:
        next_pos, next_slot = BRACKET_ADVANCE[bracket_pos]
        nm = _get_or_create_bracket_match(d, next_pos)
        nm['team1_id' if next_slot == 1 else 'team2_id'] = winner_id

    store.save(d, commit_message=f"Bracket natija: {bracket_pos}")
    return jsonify({'ok': True, 'winner_id': winner_id})


@app.route('/api/admin/bracket/reset', methods=['POST'])
@admin_required
def reset_bracket():
    d = store.load()
    d['matches'] = [m for m in d['matches'] if not m.get('bracket_pos')]
    store.save(d, commit_message="Bracket tozalandi")
    return jsonify({'ok': True})


@app.route('/api/admin/settings', methods=['PUT'])
@admin_required
def update_settings():
    data = request.get_json(force=True)
    d = store.load()
    for k, v in data.items():
        d['settings'][k] = str(v)
    store.save(d, commit_message="Turnir sozlamalari yangilandi")
    return jsonify({'ok': True})


@app.route('/api/admin/stats/overview', methods=['GET'])
@admin_required
def admin_overview():
    d = store.load()
    teams = d['teams']
    r = {
        'total_teams': len(teams),
        'approved_teams': sum(1 for t in teams if t.get('status') == 'approved'),
        'pending_teams': sum(1 for t in teams if t.get('status') == 'pending'),
        'rejected_teams': sum(1 for t in teams if t.get('status') == 'rejected'),
        'total_players': len(d['players']),
        'total_matches': len(d['matches']),
        'finished_matches': sum(1 for m in d['matches'] if m.get('status') == 'finished'),
    }
    return jsonify(r)


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


if __name__ == '__main__':
    print("✅ CS2 Tournament (JSON + GitHub sync) ishga tushdi -> http://localhost:5000")
    print("Admin: pro_vveb / (ADMIN_PASSWORD env yoki standart: slx12344)")
    app.run(debug=True, host='0.0.0.0', port=5000)
