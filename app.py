import os
import sqlite3
import urllib.request
import json
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import random
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# --- 1. Database Initialization ---
def init_db():
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS movies (
                    id INTEGER PRIMARY KEY, title TEXT, genre TEXT, year INTEGER, posterUrl TEXT, plot TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, state_vector TEXT)''')
    conn.commit()
    conn.close()

def update_db_from_network():
    # 若您有 TMDB API Key，請填寫於下方變數中，或設定在環境變數
    tmdb_api_key = os.environ.get("TMDB_API_KEY", "")
    
    if tmdb_api_key:
        try:
            print("正在從 The Movie Database (TMDB) 獲取最新資料...")
            # 1. 取得類型 (Genres) 對照表
            req_g = urllib.request.Request(f'https://api.themoviedb.org/3/genre/movie/list?api_key={tmdb_api_key}&language=zh-TW')
            res_g = urllib.request.urlopen(req_g)
            genre_map = {g['id']: g['name'] for g in json.loads(res_g.read())['genres']}

            # 2. 取得熱門電影
            req_m = urllib.request.Request(f'https://api.themoviedb.org/3/movie/popular?api_key={tmdb_api_key}&language=zh-TW&page=1')
            res_m = urllib.request.urlopen(req_m)
            movies_data = json.loads(res_m.read())['results']

            conn = sqlite3.connect('movies.db')
            c = conn.cursor()
            c.execute('DELETE FROM movies')
            
            for m in movies_data:
                genre_name = genre_map.get(m['genre_ids'][0], 'Unknown') if m.get('genre_ids') else 'Unknown'
                year = int(m.get('release_date', '2000').split('-')[0]) if m.get('release_date') else 2000
                poster = f"https://image.tmdb.org/t/p/w500{m.get('poster_path', '')}" if m.get('poster_path') else ""
                plot = m.get('overview', '')
                c.execute("INSERT INTO movies (id, title, genre, year, posterUrl, plot) VALUES (?, ?, ?, ?, ?, ?)", 
                          (m['id'], m['title'], genre_name, year, poster, plot))
                
            conn.commit()
            conn.close()
            print("TMDB 資料更新成功！")
            return
        except Exception as e:
            print(f"TMDB 更新失敗: {e}。將嘗試備用開源資料庫...")

    # Fallback: 使用原本的 GitHub 開源 JSON
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
            c.execute("INSERT INTO movies (id, title, genre, year, posterUrl, plot) VALUES (?, ?, ?, ?, ?, ?)", 
                      (i, m['title'], genre, year, poster, plot))
            
        conn.commit()
        conn.close()
        print("DB updated from network successfully.")
    except Exception as e:
        print(f"Network update failed: {e}")

init_db()
update_db_from_network()

# --- 2. Load Data ---
def load_movies():
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("SELECT id, title, genre, year, posterUrl, plot FROM movies")
    movies_data = c.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "genre": r[2], "year": r[3], "posterUrl": r[4], "plot": r[5]} for r in movies_data]

MOVIES = load_movies()
if len(MOVIES) == 0:
    MOVIES = [{"id": 0, "title": "Fallback Movie", "genre": "Sci-Fi", "year": 2020, "posterUrl": "", "plot": "None"}]

NUM_MOVIES = len(MOVIES)
GENRES = sorted(list(set([m["genre"] for m in MOVIES])))
NUM_GENRES = len(GENRES)
YEARS = sorted(list(set([m["year"] for m in MOVIES])), reverse=True)

def get_genre_vector(genre):
    vec = np.zeros(NUM_GENRES)
    if genre in GENRES:
        vec[GENRES.index(genre)] = 1
    return vec

# --- 3. DRL Model & Agent ---
class DQN(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(DQN, self).__init__()
        self.fc1 = nn.Linear(state_dim, 64)
        self.fc2 = nn.Linear(64, 64)
        self.fc3 = nn.Linear(64, action_dim)

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
        
    def get_action(self, state, valid_movie_ids=None):
        if np.random.rand() <= self.epsilon:
            if valid_movie_ids:
                return random.choice(valid_movie_ids)
            return random.randrange(self.action_dim)
        
        state_tensor = torch.FloatTensor(state).unsqueeze(0)
        with torch.no_grad():
            q_values = self.model(state_tensor)[0]
            
        if valid_movie_ids is not None:
            mask = torch.full((self.action_dim,), float('-inf'))
            for vid in valid_movie_ids:
                if vid < self.action_dim:
                    mask[vid] = 0
            q_values = q_values + mask
            
        return torch.argmax(q_values).item()
        
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

agent = DQNAgent(state_dim=NUM_GENRES, action_dim=NUM_MOVIES)

# --- 4. User State Management ---
def get_user_state(user_name):
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("SELECT state_vector FROM users WHERE name=?", (user_name,))
    row = c.fetchone()
    if row:
        state = np.array(json.loads(row[0]))
        # if genres expanded, zero-pad
        if len(state) < NUM_GENRES:
            state = np.pad(state, (0, NUM_GENRES - len(state)), 'constant')
    else:
        state = np.zeros(NUM_GENRES)
        c.execute("INSERT INTO users (name, state_vector) VALUES (?, ?)", (user_name, json.dumps(state.tolist())))
        conn.commit()
    conn.close()
    return state

def save_user_state(user_name, state):
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("UPDATE users SET state_vector=? WHERE name=?", (json.dumps(state.tolist()), user_name))
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
    return jsonify({
        "genres": GENRES,
        "years": YEARS,
        "users": get_all_users()
    })

@app.route('/api/recommend', methods=['POST'])
def recommend():
    data = request.json
    user_name = data.get('username', 'Guest')
    filter_genre = data.get('genre', 'All')
    filter_year = data.get('year', 'All')
    
    state = get_user_state(user_name)
    
    valid_ids = []
    for m in MOVIES:
        match_genre = (filter_genre == 'All' or m['genre'] == filter_genre)
        match_year = (filter_year == 'All' or str(m['year']) == str(filter_year))
        if match_genre and match_year:
            valid_ids.append(m['id'])
            
    if not valid_ids:
        return jsonify({"error": "找不到符合該條件的電影"}), 404
        
    action = agent.get_action(state, valid_ids)
    movie = next((m for m in MOVIES if m['id'] == action), MOVIES[valid_ids[0]])
    
    prefs = {GENRES[i]: round(state[i], 2) for i in range(NUM_GENRES) if state[i] > 0.1}
    
    return jsonify({
        "movie": movie,
        "epsilon": round(agent.epsilon, 3),
        "preferences": prefs
    })

@app.route('/api/feedback', methods=['POST'])
def feedback():
    data = request.json
    user_name = data.get('username', 'Guest')
    action = data.get('movie_id')
    reward = int(data.get('reward', 0))
    
    state = get_user_state(user_name)
    movie = next((m for m in MOVIES if m['id'] == action), None)
    
    if movie:
        next_state = state.copy() * 0.8 # Decay older preferences
        if reward == 1:
            next_state += get_genre_vector(movie['genre'])
            
        agent.train(state, action, reward, next_state)
        save_user_state(user_name, next_state)
        
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
