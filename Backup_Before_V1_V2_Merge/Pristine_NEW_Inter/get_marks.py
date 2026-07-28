import json

files = ["FM_Mock_Paper_1.json", "FM_Mock_Paper_2.json", "FM_Mock_Paper_3.json"]

for f in files:
    with open(f, 'r') as file:
        data = json.load(file)
        print(f"\n--- {f} ---")
        for q in data.get('section_b', []):
            if f == "FM_Mock_Paper_1.json" and q.get('q_main') in [5, 7]:
                print(f"Q{q['q_main']} Total Marks: {q['total_marks']}")
                for sq in q.get('sub_questions', []):
                    print(f"  {sq['label']}: {sq['marks']} marks - {sq['question'][:50]}...")
            if f in ["FM_Mock_Paper_2.json", "FM_Mock_Paper_3.json"] and q.get('q_main') in [4, 5]:
                print(f"Q{q['q_main']} Total Marks: {q['total_marks']}")
                for sq in q.get('sub_questions', []):
                    print(f"  {sq['label']}: {sq['marks']} marks - {sq['question'][:50]}...")
