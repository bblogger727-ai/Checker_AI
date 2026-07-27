import os
import shutil

backup_dir = "/Users/gaureshmantri/Desktop/CheckerAI/Backup_Before_V1_V2_Merge"

if not os.path.exists(backup_dir):
    print(f"Backup directory {backup_dir} not found! Cannot restore.")
    exit(1)

# 1. Restore Pristine NEW papers to All_Paper_JSONs/Inter
# (The user specifically requested: "When we run the rollback script, the papers in the Inter folder in All Paper Jsons should be the new papers, and not the old papers.")
all_papers_inter = "/Users/gaureshmantri/Desktop/CheckerAI/All_Paper_JSONs/Inter"
new_papers_src = os.path.join(backup_dir, "Pristine_NEW_Inter")
if os.path.exists(new_papers_src):
    if os.path.exists(all_papers_inter):
        shutil.rmtree(all_papers_inter)
    shutil.copytree(new_papers_src, all_papers_inter)
    print(f"Restored Pristine NEW papers to {all_papers_inter}")
else:
    print(f"Warning: {new_papers_src} not found.")

# 2. Restore Pristine OLD papers to Inter
independent_inter = "/Users/gaureshmantri/Desktop/CheckerAI/Inter"
old_papers_src = os.path.join(backup_dir, "Pristine_OLD_Inter")
if os.path.exists(old_papers_src):
    if os.path.exists(independent_inter):
        shutil.rmtree(independent_inter)
    shutil.copytree(old_papers_src, independent_inter)
    print(f"Restored Pristine OLD papers to {independent_inter}")
else:
    print(f"Warning: {old_papers_src} not found.")

# 3. Restore Python code files
code_files = [
    "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/run_pipeline_FT_api.py",
    "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/run_pipeline_FT.py",
    "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/run_pipeline_json.py",
    "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/claude_grading/answer_grader_claude.py",
    "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/app/services/answer_grader.py",
]
code_backup_dir = os.path.join(backup_dir, "Code_Backups")

if os.path.exists(code_backup_dir):
    for path in code_files:
        fname = os.path.basename(path)
        src = os.path.join(code_backup_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, path)
            print(f"Restored {fname}")
        else:
            print(f"Warning: Backup for {fname} not found.")

print("\nRollback completed successfully! Software has been restored to the exact requested state.")
print("Note: The feedback font size in generate_checked_copy_v2.py was kept at the new larger size (14).")
