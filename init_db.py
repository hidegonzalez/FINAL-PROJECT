import sqlite3

MOVIES = [
    {"id": 0, "title": "駭客任務 (The Matrix)", "genre": "Sci-Fi"},
    {"id": 1, "title": "全面啟動 (Inception)", "genre": "Sci-Fi"},
    {"id": 2, "title": "復仇者聯盟 (The Avengers)", "genre": "Action"},
    {"id": 3, "title": "終極警探 (Die Hard)", "genre": "Action"},
    {"id": 4, "title": "玩具總動員 (Toy Story)", "genre": "Animation"},
    {"id": 5, "title": "海底總動員 (Finding Nemo)", "genre": "Animation"},
    {"id": 6, "title": "手札情緣 (The Notebook)", "genre": "Romance"},
    {"id": 7, "title": "鐵達尼號 (Titanic)", "genre": "Romance"},
    {"id": 8, "title": "厲陰宅 (The Conjuring)", "genre": "Horror"},
    {"id": 9, "title": "牠 (It)", "genre": "Horror"}
]

conn = sqlite3.connect('movies.db')
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS movies
             (id INTEGER PRIMARY KEY, title TEXT, genre TEXT)''')
c.execute('DELETE FROM movies') # Clear existing

for m in MOVIES:
    c.execute("INSERT INTO movies (id, title, genre) VALUES (?, ?, ?)",
              (m['id'], m['title'], m['genre']))

conn.commit()
conn.close()
print("Database movies.db created successfully.")
