"""
Standalone test for AFM Full Test 1 Q2b grading fix.

Student answer transcribed from the photo — student only:
  1. Listed all "Given" data directly from the question
  2. Wrote wrong formula for levered beta (WACC formula mislabeled)
  3. Used unlevered beta=1.8 directly (no conversion) → wrong Ke=15.8%
  4. Did NOT adjust EBITDA for extraordinary gain/write-off
  5. Got wrong WACC=11.83%, wrong PV=292.65

Expected result after fix: poor tier, 0/5 marks.
Pre-fix result was: okay tier, 2/5 marks.
"""

import sys, os, json

# Add the backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claude_grading.answer_grader_claude import grade_two_phase

QUESTION = """There is a privately held company X Pvt. Ltd that is operating into the retail space, and is now scouting for angel investors. The details pertinent to valuing X Pvt. Ltd are as follows. The company has achieved break even this year and has an EBITDA of Rs. 90 crore. The unleveraged beta based on the industry in which it operates is 1.8, and the average debt to equity ratio is hovering at 40:60. The rate of return provided by risk free liquid bonds is 5%. The EV is to be taken at a multiple of 5 on EBITDA. The accountant has informed that the EBITDA of Rs. 90 crore includes an extraordinary gain of Rs. 10 crore for the year, and a potential write off of preliminary sales promotion costs of Rs. 20 crore are still pending. The internal assessment of rate of market return for the industry is 11%. The FCFs for the next 3 years are as follows:

Y1: 100 crore, Y2: 120 crore, Y3: 150 crore

The pre-tax cost of debt is 8.40%. Assume a tax regime of 30%.

What is the potential value to be placed on X Pvt. Ltd?"""

MODEL_ANSWER = """The levered beta of the company will be 1.8[1+(1-0.3)*40/60] = 2.64

The adjusted EBITDA would be Rs. 90 crore - Rs. 10 crore - Rs. 20 crore = Rs. 60 crore

The EV will be multiple of 5 on the 60 obtained above = Rs. 300 crore

The Cost of equity in accordance with CAPM = Rf + beta*(Rm-Rf)
= 5% + 2.64*(11%-5%) = 20.84%

The WACC = Cost of Equity * (E/V) + Cost of Debt * (D/V) * (1-tax)
= 20.84*(60/100) + 8.40*(40/100)*(1-0.30)
= 12.504 + 2.352 = 14.856% (approx 14.86%)

Finally, the future cash flows can be discounted at the WACC obtained above:

Y1: Cash Flow=100, DF@14.86%=0.863, PV=86.30
Y2: Cash Flow=120, DF@14.86%=0.745, PV=89.40
Y3: Cash Flow=150, DF@14.86%=0.643, PV=96.45

Value of Firm = 86.30 + 89.40 + 96.45 = 272.15 crore"""

# Transcribed directly from the student's handwritten answer in the photo
STUDENT_ANSWER = """Given
EBITDA = 90 crore
Unleveraged beta = 1.8
Debt : Equity ratio = 40:60
Rf = 5%
EV = 5 x EBITDA
Rm = 11%
Pre-Tax Kd = 8.40%
Tax = 30%

levered beta = Ke x E / D+E  +  Kd x D / D+E

Ke = Rf + (Rm - Rf) x beta
   = 5 + (11-5) x 1.8
   = 15.8%

WACC = 15.8 x 60/100 + 5.88 x 40/100
     = 9.48 + 2.352
     = 11.83%

Cash Flow Table:
       Y.1     Y.2    Y.3
CF     100     120    150
DF@11.83%  0.894   0.799   0.715
PV     89.4    96     107.25

Total PV = 292.65"""

MARKS = 5
QUESTION_TYPE = "practical"

if __name__ == "__main__":
    print("=" * 60)
    print("Testing AFM Q2b — Grading Fix Verification")
    print("=" * 60)
    print(f"\nMax Marks: {MARKS}")
    print("\nRunning two-phase grader...\n")

    result = grade_two_phase(
        question_text=QUESTION,
        model_answer=MODEL_ANSWER,
        student_answer=STUDENT_ANSWER,
        marks=MARKS,
        is_practical=(QUESTION_TYPE == "practical"),
    )

    print(f"Tier (Phase 1):       {result.get('tier', 'N/A')}")
    print(f"Marks Obtained:       {result.get('marks_obtained', 'N/A')} / {MARKS}")
    print(f"Final Answer Correct: {result.get('final_answer_correct', 'N/A')}")
    print(f"\nPhase 1 Reasoning:\n  {result.get('reasoning', 'N/A')}")
    print(f"\nFeedback:\n  {result.get('feedback', 'N/A')}")
    print(f"\nCorrect Items: {result.get('correct_items', [])}")
    print(f"Major Errors:  {result.get('major_errors', [])}")
    print("\n" + "=" * 60)

    marks = result.get("marks_obtained", -1)
    tier = result.get("tier", "")

    if tier == "poor" and marks == 0.0:
        print("✅ FIX VERIFIED — Student correctly received 0/5 (poor tier)")
    elif tier == "poor":
        print(f"⚠️  PARTIAL — Tier is 'poor' but marks={marks} (expected 0)")
    else:
        print(f"❌ FIX FAILED — Tier={tier}, Marks={marks}/5 (expected poor / 0)")
