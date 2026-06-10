import os
import sqlite3
import urllib.request
import json
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import random
import concurrent.futures
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# --- 1. Database Initialization ---
def init_db():
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS movies (
                    id INTEGER PRIMARY KEY, title TEXT, genre TEXT, year INTEGER, posterUrl TEXT, plot TEXT, director TEXT, actors TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, state_vector TEXT, is_new INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS skipped_movies (
                    username TEXT, movie_id INTEGER, PRIMARY KEY(username, movie_id))''')
    conn.commit()
    conn.close()

def update_db_from_network(download_count=200):
    tmdb_api_key = os.environ.get("TMDB_API_KEY", "cca4acdfbc4f4f6bd3ec8260151fc7ca")
    
    if tmdb_api_key:
        try:
            print("正在從 The Movie Database (TMDB) 獲取最新資料...")
            req_g = urllib.request.Request(f'https://api.themoviedb.org/3/genre/movie/list?api_key={tmdb_api_key}&language=zh-TW')
            res_g = urllib.request.urlopen(req_g)
            genre_map = {g['id']: g['name'] for g in json.loads(res_g.read())['genres']}

            conn = sqlite3.connect('movies.db')
            c = conn.cursor()
            
            c.execute('SELECT id FROM movies')
            existing_ids = set([row[0] for row in c.fetchall()])
            
            added_count = 0
            page = random.randint(1, 500)
            
            print(f"資料庫目前有 {len(existing_ids)} 部電影。開始新增 {download_count} 部...")
            while added_count < download_count:
                try:
                    req_m = urllib.request.Request(f'https://api.themoviedb.org/3/movie/popular?api_key={tmdb_api_key}&language=zh-TW&page={page}')
                    res_m = urllib.request.urlopen(req_m)
                    movies_data = json.loads(res_m.read())['results']
                except:
                    page = (page % 500) + 1
                    continue
                
                new_movies = []
                for m in movies_data:
                    if m['id'] not in existing_ids:
                        new_movies.append(m)
                        if added_count + len(new_movies) >= download_count:
                            break
                            
                if not new_movies:
                    page = (page % 500) + 1
                    continue
                    
                def fetch_credits(movie):
                    try:
                        req_c = urllib.request.Request(f'https://api.themoviedb.org/3/movie/{movie["id"]}/credits?api_key={tmdb_api_key}')
                        res_c = urllib.request.urlopen(req_c)
                        credits_data = json.loads(res_c.read())
                        director = next((c['name'] for c in credits_data['crew'] if c['job'] == 'Director'), 'Unknown')
                        actors_list = [c['name'] for c in credits_data['cast'][:3]]
                        actors = ", ".join(actors_list) if actors_list else 'Unknown'
                    except:
                        director = 'Unknown'
                        actors = 'Unknown'
                    return movie, director, actors

                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    results = list(executor.map(fetch_credits, new_movies))

                for m, director, actors in results:
                    genre_name = genre_map.get(m['genre_ids'][0], 'Unknown') if m.get('genre_ids') else 'Unknown'
                    year = int(m.get('release_date', '2000').split('-')[0]) if m.get('release_date') else 2000
                    poster = f"https://image.tmdb.org/t/p/w500{m.get('poster_path', '')}" if m.get('poster_path') else ""
                    plot = m.get('overview', '')
                    
                    c.execute("INSERT INTO movies (id, title, genre, year, posterUrl, plot, director, actors) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                              (m['id'], m['title'], genre_name, year, poster, plot, director, actors))
                    
                    existing_ids.add(m['id'])
                    added_count += 1
                    
                    if added_count % 50 == 0 or added_count == download_count:
                        print(f"已新增 {added_count}/{download_count} 部...")
                        
                page = (page % 500) + 1
                    
            conn.commit()
            conn.close()
            print("TMDB 資料庫（含導演與演員）更新成功！")
            return
        except Exception as e:
            print(f"TMDB 更新失敗: {e}。將嘗試備用開源資料庫...")

    # Fallback
    try:
        url = 'https://raw.githubusercontent.com/erik-sytnyk/movies-list/master/db.json'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req)
        data = json.loads(response.read())
        
        conn = sqlite3.connect('movies.db')
        c = conn.cursor()
        c.execute('DELETE FROM movies')
        
        for i, m in enumerate(data['movies']):
            genre = m['genres'][0] if m.get('genres') else 'Unknown'
            year = int(m.get('year', 2000))
            poster = m.get('posterUrl', '')
            plot = m.get('plot', '')
            director = m.get('director', 'Unknown')
            actors = m.get('actors', 'Unknown')
            
            c.execute("INSERT INTO movies (id, title, genre, year, posterUrl, plot, director, actors) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                      (i, m['title'], genre, year, poster, plot, director, actors))
            
        conn.commit()
        conn.close()
        print("DB updated from network successfully.")
    except Exception as e:
        print(f"Network update failed: {e}")

init_db()

# --- 2. Load Data ---
def load_movies():
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("SELECT id, title, genre, year, posterUrl, plot, director, actors FROM movies")
    movies_data = c.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "genre": r[2], "year": r[3], "posterUrl": r[4], "plot": r[5], "director": r[6], "actors": r[7]} for r in movies_data]

MOVIES = []
NUM_MOVIES = 0
GENRES = []
DIRECTORS = []
ACTORS = []
NUM_GENRES = 0
NUM_DIRECTORS = 0
NUM_ACTORS = 0
NUM_FEATURES = 0
YEARS = []
agent = None

def get_movie_vector(movie):
    vec = np.zeros(NUM_FEATURES)
    if movie["genre"] in GENRES:
        vec[GENRES.index(movie["genre"])] = 1
    if movie["director"] in DIRECTORS:
        vec[NUM_GENRES + DIRECTORS.index(movie["director"])] = 1
    for a in movie["actors"].split(","):
        a = a.strip()
        if a in ACTORS:
            vec[NUM_GENRES + NUM_DIRECTORS + ACTORS.index(a)] = 1
    return vec

# --- 3. DRL Model & Agent ---
class DQN(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(DQN, self).__init__()
        self.fc1 = nn.Linear(state_dim, 256)
        self.fc2 = nn.Linear(256, 128)
        self.fc3 = nn.Linear(128, action_dim)

    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.fc3(x)

class DQNAgent:
    def __init__(self, state_dim, action_dim):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.epsilon = 1.0
        self.epsilon_decay = 0.95
        self.epsilon_min = 0.05
        self.gamma = 0.9
        
        self.model = DQN(state_dim, action_dim)
        self.optimizer = optim.Adam(self.model.parameters(), lr=0.01)
        self.criterion = nn.MSELoss()
        
    def get_actions(self, state, valid_movie_ids, k=10, explore=True):
        if len(valid_movie_ids) < k:
            k = len(valid_movie_ids)
        if k == 0: return []
        
        if explore and np.random.rand() <= self.epsilon:
            return random.sample(valid_movie_ids, k)
        
        state_tensor = torch.FloatTensor(state).unsqueeze(0)
        with torch.no_grad():
            q_values = self.model(state_tensor)[0]
            
        mask = torch.full((self.action_dim,), float('-inf'))
        for vid in valid_movie_ids:
            if vid < self.action_dim:
                mask[vid] = 0
        q_values = q_values + mask
        
        top_k_indices = torch.topk(q_values, k).indices.tolist()
        return top_k_indices
        
    def train(self, state, action, reward, next_state):
        if action >= self.action_dim: return
        state_tensor = torch.FloatTensor(state).unsqueeze(0)
        next_state_tensor = torch.FloatTensor(next_state).unsqueeze(0)
        reward_tensor = torch.tensor(reward, dtype=torch.float32)
        
        q_values = self.model(state_tensor)
        q_value = q_values[0][action]
        
        with torch.no_grad():
            next_q_values = self.model(next_state_tensor)
            max_next_q_value = torch.max(next_q_values[0])
            
        target_q_value = reward_tensor + self.gamma * max_next_q_value
        loss = self.criterion(q_value, target_q_value)
        
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

def reload_system():
    global MOVIES, NUM_MOVIES, GENRES, DIRECTORS, ACTORS, NUM_GENRES, NUM_DIRECTORS, NUM_ACTORS, NUM_FEATURES, YEARS, agent
    MOVIES = load_movies()
    if len(MOVIES) == 0:
        MOVIES = [{"id": 0, "title": "Fallback Movie", "genre": "Sci-Fi", "year": 2020, "posterUrl": "", "plot": "None", "director": "None", "actors": "None"}]
    for i, m in enumerate(MOVIES):
        m['action_index'] = i
    NUM_MOVIES = len(MOVIES)
    GENRES = sorted(list(set([m["genre"] for m in MOVIES])))
    DIRECTORS = sorted(list(set([m["director"] for m in MOVIES])))
    all_actors = set()
    for m in MOVIES:
        for a in m["actors"].split(","):
            all_actors.add(a.strip())
    ACTORS = sorted(list(all_actors))
    NUM_GENRES = len(GENRES)
    NUM_DIRECTORS = len(DIRECTORS)
    NUM_ACTORS = len(ACTORS)
    NUM_FEATURES = NUM_GENRES + NUM_DIRECTORS + NUM_ACTORS
    YEARS = sorted(list(set([m["year"] for m in MOVIES])), reverse=True)
    agent = DQNAgent(state_dim=NUM_FEATURES, action_dim=NUM_MOVIES)

reload_system()

# --- 4. User State Management ---
def get_user(user_name):
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("SELECT state_vector, is_new FROM users WHERE name=?", (user_name,))
    row = c.fetchone()
    if row:
        try:
            pref_dict = json.loads(row[0])
        except:
            pref_dict = {}
        is_new = row[1]
    else:
        pref_dict = {}
        is_new = 1
        c.execute("INSERT INTO users (name, state_vector, is_new) VALUES (?, ?, ?)", (user_name, json.dumps(pref_dict), 1))
        conn.commit()
    conn.close()
    
    state = np.zeros(NUM_FEATURES)
    for i, g in enumerate(GENRES):
        state[i] = pref_dict.get("G_" + g, 0.0)
    for i, d in enumerate(DIRECTORS):
        state[NUM_GENRES + i] = pref_dict.get("D_" + d, 0.0)
    for i, a in enumerate(ACTORS):
        state[NUM_GENRES + NUM_DIRECTORS + i] = pref_dict.get("A_" + a, 0.0)
        
    return state, is_new

def save_user_state(user_name, state_vector, is_new=0):
    pref_dict = {}
    for i, g in enumerate(GENRES):
        if state_vector[i] > 0.01:
            pref_dict["G_" + g] = state_vector[i]
    for i, d in enumerate(DIRECTORS):
        if state_vector[NUM_GENRES + i] > 0.01:
            pref_dict["D_" + d] = state_vector[NUM_GENRES + i]
    for i, a in enumerate(ACTORS):
        if state_vector[NUM_GENRES + NUM_DIRECTORS + i] > 0.01:
            pref_dict["A_" + a] = state_vector[NUM_GENRES + NUM_DIRECTORS + i]
            
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("UPDATE users SET state_vector=?, is_new=? WHERE name=?", (json.dumps(pref_dict), is_new, user_name))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("SELECT name FROM users")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

# --- 5. Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/init_data', methods=['GET'])
def get_init_data():
    valid_genres = [g for g in GENRES if sum(1 for m in MOVIES if m['genre'] == g) >= 10]
    valid_years = [y for y in YEARS if sum(1 for m in MOVIES if m['year'] == y) >= 10]
    
    return jsonify({
        "genres": valid_genres,
        "years": valid_years,
        "users": get_all_users()
    })

@app.route('/api/recommend', methods=['POST'])
def recommend():
    data = request.json
    user_name = data.get('username', 'Guest')
    filter_genre = data.get('genre', 'All')
    filter_year = data.get('year', 'All')
    
    exclude_ids = set(data.get('exclude_ids', []))
    
    state, is_new = get_user(user_name)
    recommended_movies = []
    
    notice_message = None
    
    if is_new:
        movies_by_genre = {}
        for m in MOVIES:
            if m['id'] not in exclude_ids:
                movies_by_genre.setdefault(m['genre'], []).append(m)
            
        for g, lst in movies_by_genre.items():
            recommended_movies.extend(random.sample(lst, min(10, len(lst))))
            
        random.shuffle(recommended_movies)
        save_user_state(user_name, state, is_new=0)
    else:
        if filter_genre == 'All':
            valid_ids = [m['action_index'] for m in MOVIES if (filter_year == 'All' or str(m['year']) == str(filter_year)) and m['id'] not in exclude_ids]
            if len(valid_ids) < 10:
                if filter_year != 'All':
                    notice_message = "因為該年份在資料庫未達10部，故將相近年份的電影選入推薦"
                    target_year = int(filter_year)
                    fallback_ids = [m['action_index'] for m in MOVIES if m['action_index'] not in valid_ids and m['id'] not in exclude_ids]
                    fallback_ids.sort(key=lambda idx: abs(MOVIES[idx]['year'] - target_year))
                    valid_ids.extend(fallback_ids[:10 - len(valid_ids)])
                else:
                    fallback_ids = [m['action_index'] for m in MOVIES if m['action_index'] not in valid_ids and m['id'] not in exclude_ids]
                    valid_ids.extend(random.sample(fallback_ids, min(10 - len(valid_ids), len(fallback_ids))))
            
            action_ids = random.sample(valid_ids, min(10, len(valid_ids)))
            recommended_movies = [m for m in MOVIES if m['action_index'] in action_ids]
            
        else:
            valid_ids = [m['action_index'] for m in MOVIES if m['genre'] == filter_genre and (filter_year == 'All' or str(m['year']) == str(filter_year)) and m['id'] not in exclude_ids]
            if len(valid_ids) < 10:
                if filter_year != 'All':
                    notice_message = "因為該年份的此類型在資料庫未達10部，故將相近年份的同類型電影選入推薦"
                    target_year = int(filter_year)
                    fallback_ids = [m['action_index'] for m in MOVIES if m['genre'] == filter_genre and m['action_index'] not in valid_ids and m['id'] not in exclude_ids]
                    fallback_ids.sort(key=lambda idx: abs(MOVIES[idx]['year'] - target_year))
                    valid_ids.extend(fallback_ids[:10 - len(valid_ids)])
                
                if len(valid_ids) < 10:
                    fallback_ids2 = [m['action_index'] for m in MOVIES if m['action_index'] not in valid_ids and m['id'] not in exclude_ids]
                    if filter_year != 'All':
                        fallback_ids2.sort(key=lambda idx: abs(MOVIES[idx]['year'] - int(filter_year)))
                    else:
                        random.shuffle(fallback_ids2)
                    valid_ids.extend(fallback_ids2[:10 - len(valid_ids)])
                
            action_ids = agent.get_actions(state, valid_ids, k=10)
            recommended_movies = [m for m in MOVIES if m['action_index'] in action_ids]
            
        # 如果有填補年份，根據目標年份接近程度排序
        if notice_message and filter_year != 'All':
            target_year = int(filter_year)
            recommended_movies.sort(key=lambda m: abs(m['year'] - target_year))

    if not recommended_movies:
        return jsonify({"error": "找不到符合該條件的電影"}), 404
        
    # Get human-readable preferences
    prefs = {}
    for i, g in enumerate(GENRES):
        if state[i] > 0.05: prefs[f"類型: {g}"] = round(state[i], 2)
    for i, d in enumerate(DIRECTORS):
        if state[NUM_GENRES + i] > 0.05: prefs[f"導演: {d}"] = round(state[NUM_GENRES + i], 2)
    for i, a in enumerate(ACTORS):
        if state[NUM_GENRES + NUM_DIRECTORS + i] > 0.05: prefs[f"演員: {a}"] = round(state[NUM_GENRES + NUM_DIRECTORS + i], 2)
        
    # Sort prefs by value
    prefs = dict(sorted(prefs.items(), key=lambda item: item[1], reverse=True)[:10]) # show top 10
    
    return jsonify({
        "movies": recommended_movies,
        "epsilon": round(agent.epsilon, 3),
        "preferences": prefs,
        "is_first_time": bool(is_new),
        "notice": notice_message
    })

@app.route('/api/feedback', methods=['POST'])
def feedback():
    data = request.json
    user_name = data.get('username', 'Guest')
    action = data.get('movie_id')
    reward = int(data.get('reward', 0))
    
    state, is_new = get_user(user_name)
    movie = next((m for m in MOVIES if m['id'] == action), None)
    
    if movie:
        next_state = state.copy() * 0.9 # Decay
        if reward == 1:
            next_state += get_movie_vector(movie)
            
        agent.train(state, movie['action_index'], reward, next_state)
        save_user_state(user_name, next_state, is_new=0)
        
        if reward == 0:
            conn = sqlite3.connect('movies.db')
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO skipped_movies (username, movie_id) VALUES (?, ?)", (user_name, action))
            conn.commit()
            conn.close()
        
    return jsonify({"status": "success", "epsilon": round(agent.epsilon, 3)})

from collections import Counter

@app.route('/api/top3', methods=['POST'])
def top3_recommend():
    data = request.json
    user_name = data.get('username', 'Guest')
    feedbacks = data.get('feedbacks', []) # list of dicts: {'id': 123, 'reward': 1}
    ui_genre = data.get('genre', 'All')
    ui_year = data.get('year', 'All')
    
    state, is_new = get_user(user_name)
    
    # 1. 根據今日資料 (feedbacks) 來選擇類別與年份
    liked_movie_ids = [f['id'] for f in feedbacks if f['reward'] == 1]
    liked_movies = [m for m in MOVIES if m['id'] in liked_movie_ids]
    
    preferred_genre = None
    preferred_year = None
    
    if liked_movies:
        genres = [m['genre'] for m in liked_movies]
        years = [m['year'] for m in liked_movies]
        preferred_genre = Counter(genres).most_common(1)[0][0]
        preferred_year = Counter(years).most_common(1)[0][0]
        
    # **優先考慮當次使用者在 UI 設定的條件**
    if ui_genre != 'All':
        preferred_genre = ui_genre
    if ui_year != 'All':
        preferred_year = int(ui_year)
        
    # 2. 過濾 valid_ids
    valid_ids = [m['action_index'] for m in MOVIES]
    
    if preferred_genre and preferred_year:
        strict_ids = [m['action_index'] for m in MOVIES if m['genre'] == preferred_genre and m['year'] == preferred_year]
        if len(strict_ids) >= 3:
            valid_ids = strict_ids
        else:
            genre_ids = [m['action_index'] for m in MOVIES if m['genre'] == preferred_genre]
            if len(genre_ids) >= 3:
                valid_ids = genre_ids
            else:
                year_ids = [m['action_index'] for m in MOVIES if m['year'] == preferred_year]
                if len(year_ids) >= 3:
                    valid_ids = year_ids

    # 3. 排除剛剛已經出現在畫面上評分過的電影，以及這回合/歷史所有跳過 (skipped) 的電影
    recent_ids = [f['id'] for f in feedbacks]
    
    conn = sqlite3.connect('movies.db')
    cur = conn.cursor()
    cur.execute("SELECT movie_id FROM skipped_movies WHERE username=?", (user_name,))
    db_skipped_ids = set([row[0] for row in cur.fetchall()])
    conn.close()
    
    skipped_ids = set(data.get('skipped_ids', [])).union(db_skipped_ids)
    
    valid_ids = [vid for vid in valid_ids if MOVIES[vid]['id'] not in recent_ids and MOVIES[vid]['id'] not in skipped_ids]
    
    if len(valid_ids) < 3:
        valid_ids = [m['action_index'] for m in MOVIES if m['id'] not in recent_ids and m['id'] not in skipped_ids]
        
    # 4. 根據歷史學習紀錄 (DQN state 及其他條件如導演、演員) 預測前 3 名
    # 計算每部電影與 user 歷史 state 的特徵相似度 (Dot Product)
    def get_historical_score(idx):
        m = MOVIES[idx]
        m_vec = get_movie_vector(m)
        return np.dot(state, m_vec)
        
    # 我們將相似度也納入考量，過濾出最符合歷史條件（導演/演員/類型）的候選清單
    valid_ids.sort(key=get_historical_score, reverse=True)
    # 取前 20 名最符合歷史特徵的電影交由 DQN 進行最後 Q-value 預測
    candidate_ids = valid_ids[:20] if len(valid_ids) > 20 else valid_ids
    
    # 強制不使用 epsilon 隨機探索 (explore=False)，保證運用網路學到的權重
    action_ids = agent.get_actions(state, candidate_ids, k=3, explore=False)
    
    # 最終排序：讓符合歷史條件最高的電影排在 Top 1
    top3_movies = [m for m in MOVIES if m['action_index'] in action_ids]
    top3_movies.sort(key=lambda m: np.dot(state, get_movie_vector(m)), reverse=True)
    
    return jsonify({
        "movies": top3_movies,
        "preferred_genre": preferred_genre,
        "preferred_year": preferred_year
    })

@app.route('/api/clear_state', methods=['POST'])
def clear_state():
    data = request.json
    username = data.get('username')
    if username:
        conn = sqlite3.connect('movies.db')
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE name=?", (username,))
        c.execute("DELETE FROM skipped_movies WHERE username=?", (username,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"已成功清除使用者「{username}」的學習資料！"})
    return jsonify({"status": "error", "message": "未提供使用者名稱"}), 400

@app.route('/api/delete_user', methods=['POST'])
def delete_user():
    data = request.json
    username = data.get('username')
    if username == 'Guest':
        return jsonify({"status": "error", "message": "不能刪除預設訪客"}), 400
    if username:
        conn = sqlite3.connect('movies.db')
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE name=?", (username,))
        c.execute("DELETE FROM skipped_movies WHERE username=?", (username,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"已成功刪除使用者「{username}」！"})
    return jsonify({"status": "error", "message": "未提供使用者名稱"}), 400

@app.route('/api/update_db', methods=['POST'])
def api_update_db():
    count = request.json.get('count', 50)
    try:
        count = int(count)
    except:
        count = 50
    
    update_db_from_network(download_count=count)
    reload_system()
    
    return jsonify({"status": "success", "message": f"成功擴充 {count} 部電影至資料庫！"})

if __name__ == '__main__':
    # 關閉自動重載 (use_reloader=False) 以避免 Flask Debug 模式下重複啟動導致的抓取兩次資料問題
    app.run(host='0.0.0.0', debug=True, port=5000, use_reloader=False)
