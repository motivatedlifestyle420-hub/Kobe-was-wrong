import sqlite3

class TestJobEvents:
    def test_events_are_append_only(self, db):
        jid = _enqueue(db)
        job = _claim(db)
        jobs.succeed(job["id"], job["worker_id"], job["lease_id"], db_path=db)

        conn = get_conn(db)
        try:
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
                conn.execute(
                    "UPDATE job_events SET event_type = 'mutated' WHERE job_id = ?",
                    (jid,),
                )
                conn.commit()
        finally:
            close_conn(conn)

        conn = get_conn(db)
        try:
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
                conn.execute(
                    "DELETE FROM job_events WHERE job_id = ?",
                    (jid,),
                )
                conn.commit()
        finally:
            close_conn(conn)

        events_after = jobs.get_job_events(jid, db_path=db)
        assert len(events_after) == 3


class TestSchemaConstraints:
    def test_invalid_state_rejected(self, db):
        jid = _enqueue(db)
        conn = get_conn(db)
        try:
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
                conn.execute(
                    "UPDATE jobs SET state = 'zombie' WHERE id = ?",
                    (jid,),
                )
                conn.commit()
        finally:
            close_conn(conn)

    def test_foreign_key_on_job_events(self, db):
        conn = get_conn(db)
        try:
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
                conn.execute(
                    """
                    INSERT INTO job_events (job_id, event_type, created_at)
                    VALUES ('nonexistent-job', 'enqueued', ?)
                    """,
                    (time.time(),),
                )
                conn.commit()
        finally:
            close_conn(conn)
