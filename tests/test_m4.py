"""Quick M4 verification script."""
import sys; sys.path.insert(0, '.')
from src.data.db import Database
from src.data.models import Session, Event, Catch, EnvSnapshot, RodConfig
from src.analysis.reporter import ReportGenerator
from datetime import datetime, timedelta
from pathlib import Path

db = Database(':memory:')
db.init_schema()

session = Session(map_name='Old Burg', spot_id='35:67', notes='Test session')
sid = db.create_session(session)

for slot in (1, 2, 3):
    db.save_rod_config(RodConfig(
        session_id=sid, rod_slot=slot,
        rod_name=f'Feeder Rod {slot}', reel_name='Basic Reel',
        line_type='Mono', line_strength_kg=4.5,
        hook_size='10', bait_name='Garlic Dough',
    ))

base = datetime.now() - timedelta(hours=1)
for i in range(8):
    cast_time = base + timedelta(minutes=i*7)
    bite_time = cast_time + timedelta(seconds=60 + i*15)
    db.log_event(Event(session_id=sid, rod_slot=(i%3)+1, event_type='CAST', ts=cast_time))
    db.log_event(Event(session_id=sid, rod_slot=(i%3)+1, event_type='BITE', ts=bite_time))
    
    if i < 6:
        db.save_catch(Catch(
            session_id=sid, rod_slot=(i%3)+1,
            fish_name_raw='Common Bream' if i < 4 else 'Roach',
            weight_g=800 + i*100, value=50 + i*10,
            outcome='CATCH', fight_time_s=15+i*2,
            ts_land=bite_time + timedelta(seconds=20),
        ))
    else:
        db.save_catch(Catch(
            session_id=sid, rod_slot=(i%3)+1,
            outcome='LOSS',
            ts_land=bite_time + timedelta(seconds=30),
        ))

db.end_session(sid)

gen = ReportGenerator(db, sid)
result = gen.generate_all('data/reports_test')
print(f"Markdown: {result['markdown']}")
print(f"CSV files: {len(result['csv_files'])} files")
print(f"Charts: {len(result['charts'])} files")

md = Path(result['markdown']).read_text(encoding='utf-8')
print("\n--- Report Preview ---")
print(md[:1200])
print("...")

db.close()
print("\nAll M4 verification passed!")
