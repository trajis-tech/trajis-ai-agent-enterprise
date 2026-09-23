import sqlite3
import sys

print("python", sys.version.split()[0])
print("sqlite", sqlite3.sqlite_version)
conn = sqlite3.connect(":memory:")
print("fts5", conn.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0])
for name, sql in (
    ("unicode61", "CREATE VIRTUAL TABLE t USING fts5(x, tokenize='unicode61')"),
    ("trigram", "CREATE VIRTUAL TABLE t2 USING fts5(x, tokenize='trigram')"),
):
    try:
        conn.execute(sql)
        print(name, "ok")
    except Exception as exc:
        print(name, type(exc).__name__, exc)
