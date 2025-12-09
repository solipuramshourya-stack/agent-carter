from logic.db_models import SessionLocal, DailyQueue

s = SessionLocal()
s.query(DailyQueue).delete()
s.commit()
s.close()

print("Queue cleared!")
