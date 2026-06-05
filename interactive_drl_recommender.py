import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import random
import os
import sqlite3
import urllib.request
import json

# 1. 準備電影資料庫 (每次啟動時從網路更新，並儲存至 SQLite)
def update_db_from_network():
    print("🔄 正在從網路下載最新電影資料並更新資料庫...")
    try:
        url = 'https://raw.githubusercontent.com/erik-sytnyk/movies-list/master/db.json'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req)
        data = json.loads(response.read())
        
        conn = sqlite3.connect('movies.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS movies (id INTEGER PRIMARY KEY, title TEXT, genre TEXT)''')
        c.execute('DELETE FROM movies') # 清空舊資料
        
        # 將網路資料寫入資料庫
        for i, m in enumerate(data['movies'][:50]): # 取前50筆作為互動模擬
            genre = m['genres'][0] if m.get('genres') else 'Unknown'
            c.execute("INSERT INTO movies (id, title, genre) VALUES (?, ?, ?)", (i, m['title'], genre))
            
        conn.commit()
        conn.close()
        print("✅ 網路資料下載完成並已更新資料庫！")
    except Exception as e:
        print(f"⚠️ 下載網路資料失敗: {e}。將使用現有的資料庫資料。")

def load_movies_from_db():
    update_db_from_network()
    
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute("SELECT id, title, genre FROM movies")
    movies_data = c.fetchall()
    conn.close()
    
    movies = []
    for row in movies_data:
        movies.append({"id": row[0], "title": row[1], "genre": row[2]})
    return movies

MOVIES = load_movies_from_db()

NUM_MOVIES = len(MOVIES)
GENRES = list(set([m["genre"] for m in MOVIES]))
NUM_GENRES = len(GENRES)

# 2. 定義 DQN (Deep Q-Network) 模型
class DQN(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(DQN, self).__init__()
        self.fc1 = nn.Linear(state_dim, 24)
        self.fc2 = nn.Linear(24, 24)
        self.fc3 = nn.Linear(24, action_dim)

    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.fc3(x)

# 3. 建立 DRL 代理人 (Agent)
class DQNAgent:
    def __init__(self, state_dim, action_dim):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.epsilon = 1.0  # 初始探索率 (Exploration rate)
        self.epsilon_decay = 0.90 # 每次互動後的衰減率
        self.epsilon_min = 0.05   # 最低探索率
        self.gamma = 0.9    # 折扣因子 (Discount factor)，重視長期回饋
        
        self.model = DQN(state_dim, action_dim)
        self.optimizer = optim.Adam(self.model.parameters(), lr=0.01)
        self.criterion = nn.MSELoss()
        
    def get_action(self, state):
        # Epsilon-Greedy 策略：平衡探索 (Exploration) 與利用 (Exploitation)
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.action_dim)
        state_tensor = torch.FloatTensor(state).unsqueeze(0)
        with torch.no_grad():
            q_values = self.model(state_tensor)
        return torch.argmax(q_values[0]).item()
        
    def train(self, state, action, reward, next_state):
        state_tensor = torch.FloatTensor(state).unsqueeze(0)
        next_state_tensor = torch.FloatTensor(next_state).unsqueeze(0)
        reward_tensor = torch.tensor(reward, dtype=torch.float32)
        
        # 取得當前狀態下的預測 Q 值
        q_values = self.model(state_tensor)
        q_value = q_values[0][action]
        
        # 取得下一個狀態的最大 Q 值
        with torch.no_grad():
            next_q_values = self.model(next_state_tensor)
            max_next_q_value = torch.max(next_q_values[0])
        
        # 計算 Target Q = Reward + gamma * Max Q(s', a')
        target_q_value = reward_tensor + self.gamma * max_next_q_value
        
        # 計算 Loss 並更新網路權重
        loss = self.criterion(q_value, target_q_value)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        # 降低探索率
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

# 4. 互動環境設計
def get_genre_vector(genre):
    vec = np.zeros(NUM_GENRES)
    vec[GENRES.index(genre)] = 1
    return vec

def run_interactive_system():
    print("="*60)
    print("🎬 歡迎來到基於深度強化學習 (DRL) 的電影推薦系統！")
    print("此程式實作了報告中的 DQN 架構。")
    print("代理人將根據您的回饋 (Reward) 即時更新神經網路，學習您的偏好。")
    print("如果您喜歡推薦的電影，請輸入 '1'，不喜歡請輸入 '0'。")
    print("輸入 'q' 隨時退出系統。")
    print("="*60)
    
    # 狀態 (State) 表示：使用者近期喜歡的電影類型分佈向量
    state = np.zeros(NUM_GENRES) 
    agent = DQNAgent(state_dim=NUM_GENRES, action_dim=NUM_MOVIES)
    
    step = 0
    while True:
        step += 1
        # 代理人根據當前 State (偏好) 選擇 Action (推薦電影)
        action = agent.get_action(state)
        recommended_movie = MOVIES[action]
        
        print(f"\n🎥 [回合 {step}] 系統推薦: 《{recommended_movie['title']}》 (類型: {recommended_movie['genre']})")
        user_input = input("喜歡 (1) / 不喜歡 (0) / 退出 (q): ").strip()
        
        if user_input.lower() == 'q':
            print("感謝使用！代理人已結束學習。再見！")
            break
            
        if user_input not in ['0', '1']:
            print("⚠️ 無效輸入，請輸入 1, 0 或 q。")
            continue
            
        reward = int(user_input)
        
        # 更新狀態 (State Transition)：將近期喜歡的電影類型加入偏好向量
        # 並加入衰減機制 (0.8)，使模型更注重近期偏好
        next_state = state.copy() * 0.8
        if reward == 1:
            next_state += get_genre_vector(recommended_movie['genre'])
            print("✅ 您喜歡這部電影！代理人獲得正向回饋 (Reward: +1)")
        else:
            print("❌ 您不喜歡這部電影。代理人獲得 (Reward: 0)")
            
        # 訓練 DQN 模型 (Experience Replay 簡化版：即時學習)
        agent.train(state, action, reward, next_state)
        
        # 更新目前狀態
        state = next_state
        print(f"🤖 代理人內部狀態更新 -> 探索率 (Epsilon) 降至: {agent.epsilon:.4f}")

if __name__ == "__main__":
    run_interactive_system()
