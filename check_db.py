import sqlite3
conn = sqlite3.connect('rfid_logs.db')
tables = conn.execute("SELECT name FROM sqlite_master").fetchall()
print('Tables:', tables)
try:
    users = conn.execute("SELECT student_no, full_name FROM users").fetchall()
    print('Users:', users)
except Exception as e:
    print('No users table:', e)
conn.close()