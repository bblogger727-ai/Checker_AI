from generate_checked_copy_v2 import _find_question_line_bounds, _heading_ocr

ocr_text = """papergrid
Date / / (3)

of engagement team.

In this case the auditor has violated Competence
principle white by not sending audit engagement
letter to the society's governing body. because
(i) Scope of Objective of Audit is to achieve
roa Reasonable Assurance and Probable not
(ii) Absolute Assurance.
(ii) Audit cannot detect future errors and frauds
in Financial Statements.
(iii) Audit has limitations which prevent from
achieving Absolute Assurance.
(iv) Audit is not an Investigation.

Question - 2. b.

Audit Engagement letter is a letter which comprises
of .
(i) Objective of Audit.
(ii) Report to be submitted
(iii) Period of Audit & Applicable Financial Reporting
(iv) Access to Management personnel                    Framework
(v) Access to Those Charged with governance.
(vi) Auditor will not performing anything beyond
his competence.

(vii) Management should provide all information
that Auditor requires.
An Audit Engagement letter is letter letter
which specifies the Objective of Audit.
(i) To Attain reasonable assurance that Financial
Statements are free from Material Misstatement
whether due to fraud or error."""

with open("temp_ocr.txt", "w") as f:
    f.write("=== Page 3 ===\n" + ocr_text)

y = _heading_ocr("temp_ocr.txt", 3, 1000, "2b")
print("y =", y, "frac =", 1.0 - y/1000)

bounds = _find_question_line_bounds(ocr_text, "2b")
print("bounds =", bounds)
