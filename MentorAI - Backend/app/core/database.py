"""
Database connection for MentorAI.
Shares PostgreSQL with CheckerAI and SetterAI.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@postgres:5432/checkerai"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables and seed initial data."""
    from app.models import Base, ProblemCategory, Problem
    Base.metadata.create_all(bind=engine)
    
    # Seed problem categories and problems
    db = SessionLocal()
    try:
        # Check if already seeded
        if db.query(ProblemCategory).count() == 0:
            seed_problems(db)
        db.commit()
    finally:
        db.close()


def seed_problems(db):
    """Seed predefined problems."""
    from app.models import ProblemCategory, Problem
    
    categories_data = [
        {
            "name": "Health",
            "icon": "🏥",
            "order_index": 1,
            "problems": [
                ("Feeling sleepy all the time", "Student experiences excessive daytime sleepiness affecting study sessions.", "Recommend 7-8 hours of sleep, fixed sleep schedule, and avoiding screens before bed."),
                ("Low energy levels", "Persistent fatigue throughout the day.", "Check diet, hydration, and suggest light exercise. Consider medical checkup if persistent."),
                ("Irregular sleep schedule", "Inconsistent bedtime and wake-up times.", "Establish fixed sleep routine, no caffeine after 4 PM, wind-down routine before bed."),
                ("Skipping meals / poor diet", "Not eating properly or at regular times.", "Plan meals in advance, keep healthy snacks ready, don't skip breakfast."),
                ("Eye strain / headaches", "Physical discomfort from prolonged study.", "Follow 20-20-20 rule, proper lighting, regular breaks, eye exercises."),
                ("Physical inactivity", "Sedentary lifestyle affecting health.", "30 minutes daily walk, stretching between study sessions, desk exercises."),
            ]
        },
        {
            "name": "Mindset",
            "icon": "🧠",
            "order_index": 2,
            "problems": [
                ("Lack of motivation", "Student feeling unmotivated to study.", "Revisit goals, break down tasks, reward system, connect with study buddies."),
                ("Exam anxiety / stress", "Overwhelming stress about upcoming exams.", "Relaxation techniques, proper preparation schedule, mock tests for practice."),
                ("Fear of failure", "Paralyzed by the thought of failing.", "Reframe failure as learning, focus on process not outcome, celebrate small wins."),
                ("Procrastination", "Delaying study tasks repeatedly.", "Start with 5-minute rule, eliminate distractions, accountability partner."),
                ("Negative self-talk", "Self-defeating thoughts and low confidence.", "Positive affirmations, focus on past achievements, cognitive reframing."),
                ("Overwhelmed by syllabus", "Feeling the syllabus is too vast.", "Break into chunks, prioritize topics, focus on one chapter at a time."),
            ]
        },
        {
            "name": "Study Technique",
            "icon": "📚",
            "order_index": 3,
            "problems": [
                ("Can't concentrate for long", "Difficulty maintaining focus during study.", "Pomodoro technique, remove distractions, study in focused bursts."),
                ("Poor time management", "Not able to manage study schedule effectively.", "Weekly planning, time blocking, prioritize high-value tasks."),
                ("Ineffective revision strategy", "Not retaining studied material.", "Active recall, spaced repetition, teach-back method."),
                ("Not making notes", "Passive reading without note-taking.", "Cornell method, concept maps, summarize key points in own words."),
                ("Skipping difficult topics", "Avoiding challenging subjects.", "Start with difficult topics when fresh, break into smaller concepts."),
                ("Not practicing enough questions", "Theory focus without application.", "Daily question practice, time-bound tests, review mistakes."),
            ]
        },
        {
            "name": "Personal",
            "icon": "🏠",
            "order_index": 4,
            "problems": [
                ("Family distractions", "Home environment not conducive for study.", "Dedicated study space, communicate study schedule, noise-cancelling headphones."),
                ("Work-life balance issues", "Juggling work/job with studies.", "Time audit, integrate study into routine, weekend intensive sessions."),
                ("Social media addiction", "Excessive time on social platforms.", "App blockers, scheduled social media time, phone in different room."),
                ("Financial stress", "Money worries affecting concentration.", "Discuss with family, look for scholarships, focus on what's controllable."),
                ("Health issues in family", "Family member's health affecting student.", "Acknowledge difficulty, adjusted study plan, seek support if needed."),
                ("Relationship problems", "Personal relationships causing distress.", "Healthy boundaries, time for self, consider counseling if severe."),
            ]
        },
    ]
    
    for cat_data in categories_data:
        category = ProblemCategory(
            name=cat_data["name"],
            icon=cat_data["icon"],
            order_index=cat_data["order_index"]
        )
        db.add(category)
        db.flush()  # Get category ID
        
        for title, description, solution in cat_data["problems"]:
            problem = Problem(
                category_id=category.id,
                title=title,
                description=description,
                default_solution=solution,
                is_custom=False
            )
            db.add(problem)
    
    print("[MentorAI] Seeded problem categories and problems", flush=True)
