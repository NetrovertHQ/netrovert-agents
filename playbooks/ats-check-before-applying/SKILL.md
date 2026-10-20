---
name: ATS check before applying
description: >-
  Use before every job application (CV, cover letter, portfolio, form answers)
  to make sure it passes the company's applicant tracking system (Greenhouse,
  Ashby, Lever, Workday, Dover, SmartRecruiters, Taleo, iCIMS, etc.).
---
# ATS check before applying

Run this for every application before the user submits. Keep it lean: use code for file checks, and report in 3-6 lines.

1. **Identify the ATS** from the apply URL (greenhouse.io, ashbyhq.com, lever.co, myworkdayjobs.com, dover.com, smartrecruiters.com, taleo, icims, bamboohr, workable, etc.). Note its quirks:
   - **Workday, Taleo and iCIMS** parse CVs strictly and auto-fill fields. Use a simple single-column layout, check the parsed fields after upload, and expect knockout questions.
   - **Greenhouse, Lever and Ashby** let humans read the original file, but recruiters search by keyword. Watch the character limits on free-text boxes (often ~255).
   - **Dover** relies on minimal forms and the resume does the work.
2. **Keyword match.** Pull the posting's must-have skills, tools, titles and years with code. Compare them against the chosen CV and letter, list the missing terms, and add any that are honestly true, using the posting's exact wording. Never add skills the person doesn't have.
3. **File check** (run pdftotext/python-docx on the file):
   - Text is selectable, not an image.
   - Single column, no tables, text boxes, or header/footer-only contact info.
   - Standard headings: Experience, Skills, Education.
   - Contact details in the body.
   - File name like `First_Last_Role.pdf`, PDF or DOCX as the form allows, under 2-5 MB.
   - Consistent date formats.
4. **Knockout questions.** Read each form question literally and answer it honestly, for example work authorization in the *current* country vs the *role's* country, sponsorship, location, notice period, salary, languages, and years of experience. Flag any that might auto-reject and how to answer truthfully.
5. **Consistency.** Check that numbers match across the CV, letter and form, and that there are no outdated stats or conflicting claims.
6. **Report:** the ATS name, match score (rough % of must-haves covered), missing keywords added or impossible, file issues fixed, and knockout warnings. Fix the files yourself when the fix is safe and honest; otherwise tell the user what to change.
