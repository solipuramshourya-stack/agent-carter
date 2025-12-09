from logic.db_ops import today_key, add_to_queue
from logic.db_models import SessionLocal, DailyQueue

def test_today_key_format():
    key = today_key()
    parts = key.split("-")
    assert len(parts) == 3
    assert len(parts[0]) == 4  # year
    assert len(parts[1]) == 2  # month
    assert len(parts[2]) == 2  # day

def test_add_to_queue_deduplicates():
    user_id = "test_user"
    candidate = {
        "name": "Test Person",
        "headline": "PM at TestCo",
        "linkedin": "https://linkedin.com/in/testperson"
    }

    # Clean up any previous test data
    s = SessionLocal()
    s.query(DailyQueue).filter(
        DailyQueue.user_id == user_id,
        DailyQueue.linkedin_url == candidate["linkedin"]
    ).delete()
    s.commit()
    s.close()

    # First add → True
    assert add_to_queue(candidate, user_id=user_id) is True
    # Second add → False (duplicate)
    assert add_to_queue(candidate, user_id=user_id) is False
