import os
import shutil

backup_dir = "/Users/gaureshmantri/Desktop/CheckerAI/Backup_Before_V1_V2_Merge"
os.makedirs(backup_dir, exist_ok=True)

# 1. Back up the OLD papers (currently in All_Paper_JSONs/Inter)
old_papers_src = "/Users/gaureshmantri/Desktop/CheckerAI/All_Paper_JSONs/Inter"
old_papers_dest = os.path.join(backup_dir, "Pristine_OLD_Inter")
if os.path.exists(old_papers_src):
    if os.path.exists(old_papers_dest):
        shutil.rmtree(old_papers_dest)
    shutil.copytree(old_papers_src, old_papers_dest)
    print(f"Backed up OLD papers to {old_papers_dest}")

# 2. Back up the NEW papers (currently in Inter)
new_papers_src = "/Users/gaureshmantri/Desktop/CheckerAI/Inter"
new_papers_dest = os.path.join(backup_dir, "Pristine_NEW_Inter")
if os.path.exists(new_papers_src):
    if os.path.exists(new_papers_dest):
        shutil.rmtree(new_papers_dest)
    shutil.copytree(new_papers_src, new_papers_dest)
    print(f"Backed up NEW papers to {new_papers_dest}")

# 3. Back up Python files we will modify
code_files = [
    "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/run_pipeline_FT_api.py",
    "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/run_pipeline_FT.py",
    "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/run_pipeline_json.py",
    "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/claude_grading/answer_grader_claude.py",
    "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/app/services/answer_grader.py",
]
code_backup_dir = os.path.join(backup_dir, "Code_Backups")
os.makedirs(code_backup_dir, exist_ok=True)

for path in code_files:
    if os.path.exists(path):
        fname = os.path.basename(path)
        dest = os.path.join(code_backup_dir, fname)
        shutil.copy2(path, dest)
        print(f"Backed up {fname}")

print("\nAll backups created successfully!")
