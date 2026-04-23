from graph.graph_builder import extract_skills, clean_text
from services.db import DATABASE_URL
import psycopg2


conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute("""
    SELECT p.resume_text, p.preferences_json
    FROM profiles p
    JOIN users u ON p.user_id = u.id
    WHERE u.id = %s
""", ("2840978c-5444-49c6-9547-23c174dc727d",))
row = cur.fetchone()
cur.close()
conn.close()

resume = row[0] or ""
prefs  = row[1] or {}

print("=== raw resume (first 500 chars) ===")
print(resume[:500])

print("\n=== cleaned resume ===")
print(clean_text(resume)[:500])

print("\n=== extracted skills ===")
print(extract_skills(resume))

print("\n=== preferences ===")
print(prefs)
