"""P1 comprehensive verification."""
import sys; sys.path.insert(0, '.')
from src.data.db import Database
from src.data.models import Session, Event, Catch
from datetime import datetime, timedelta

# Build test data
db = Database(':memory:')
db.init_schema()
sid = db.create_session(Session(map_name='Old Burg', spot_id='35:67'))

base = datetime.now() - timedelta(hours=2)
for i in range(10):
    cast_time = base + timedelta(minutes=i*10)
    bite_time = cast_time + timedelta(seconds=90 + i*20)
    db.log_event(Event(session_id=sid, rod_slot=(i%3)+1, event_type='CAST', ts=cast_time))
    db.log_event(Event(session_id=sid, rod_slot=(i%3)+1, event_type='BITE', ts=bite_time,
                       confidence=0.85))
    if i < 7:
        db.save_catch(Catch(
            session_id=sid, rod_slot=(i%3)+1,
            fish_name_raw='Common Bream' if i < 5 else 'Roach',
            weight_g=800 + i*150, value=50 + i*15,
            outcome='CATCH', fight_time_s=15+i*3,
            evidence_path=f'data/evidence/catch_{i}.png' if i < 5 else '',
            confidence=0.82 + i*0.02,
            ts_land=bite_time + timedelta(seconds=25),
        ))
    else:
        db.save_catch(Catch(
            session_id=sid, rod_slot=(i%3)+1,
            outcome='LOSS',
            ts_land=bite_time + timedelta(seconds=40),
        ))
db.end_session(sid)

# 1. Reporter
from src.analysis.reporter import ReportGenerator
gen = ReportGenerator(db, sid)
result = gen.generate_all('data/reports_p1_test')
print(f"[OK] Reporter: {result['markdown']}")
print(f"     CSV={len(result['csv_files'])}, Charts={len(result['charts'])}")

# 2. Data Quality
from src.analysis.quality import DataQualityAnalyzer
qa = DataQualityAnalyzer(db, sid)
report = qa.analyze()
print(f"[OK] Quality: score={report.overall_score:.0f}/100, grade={report.grade()}")
print(f"     OCR avg conf={report.ocr_avg_confidence:.0%}")
print(f"     Evidence coverage={report.evidence_coverage_pct:.0f}%")
print(f"     Chains: complete={report.complete_chains}, broken={report.broken_chains}")
md = qa.to_markdown(report)
assert "数据质量报告" in md
print(f"     Markdown output: {len(md)} chars")

# 3. LLM Client (Mock)
from src.utils.llm_client import MockLLMClient
llm = MockLLMClient()
stats = db.get_session_stats(sid)
summary = llm.generate_session_summary(stats)
print(f"[OK] LLM Mock: {summary}")

catch_log = llm.generate_catch_log({
    "fish_name": "Common Bream", "weight_g": 2500,
    "bait": "Garlic Dough", "trophy": True,
})
print(f"     Catch log: {catch_log}")

import json
json_log = llm.generate_fishing_log(json.dumps(stats))
assert len(json_log) > 0
print(f"     JSON log: {json_log[:60]}...")

db.close()
print("\n✅ All P1 verification passed!")
