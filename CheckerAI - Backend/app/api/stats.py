import json
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/stats", tags=["stats"])

STATS_FILE = Path(__file__).parent.parent.parent / "profile_stats.json"

def _read_stats() -> dict:
    if not STATS_FILE.exists():
        return {}
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _write_stats(data: dict):
    STATS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def increment_stat(profile: str, paper_type: str):
    """
    Increment stats for a given profile.
    paper_type should be "full" or "portionwise".
    """
    if not profile:
        profile = "Profile 1"
    
    stats = _read_stats()
    
    if profile not in stats:
        stats[profile] = {"total": 0, "full": 0, "portionwise": 0}
        
    stats[profile]["total"] += 1
    
    if paper_type == "full":
        stats[profile]["full"] += 1
    elif paper_type == "portionwise":
        stats[profile]["portionwise"] += 1
        
    _write_stats(stats)

@router.get("")
def get_stats():
    return _read_stats()

class ResetRequest(BaseModel):
    profile: str

@router.post("/reset")
def reset_stats(req: ResetRequest):
    stats = _read_stats()
    stats[req.profile] = {"total": 0, "full": 0, "portionwise": 0}
    _write_stats(stats)
    return {"status": "success", "stats": stats[req.profile]}
