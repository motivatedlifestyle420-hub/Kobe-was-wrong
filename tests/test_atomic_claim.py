import sqlite3
import threading

def claim_job(conn):
    cur = conn.execute("""
        UPDATE jobs
        SET state='running'
        WHERE id = (
            SELECT id FROM jobs WHERE state='pending' LIMIT 1
        )
        RETURNING id
    """)
    row = cur.fetchone()
    return row[0] if row else None


def test_only_one_worker_claims_job(tmp_path):
    db = tmp_path / "test.db"

    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, state TEXT)")
    conn.execute("INSERT INTO jobs(state) VALUES ('pending')")
    conn.commit()
    conn.close()

    results = []

    def worker():
        c = sqlite3.connect(db)
        job = claim_job(c)
        results.append(job)
        c.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    claimed = [r for r in results if r is not None]

    assert len(claimed) == 1
