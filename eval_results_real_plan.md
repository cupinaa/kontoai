# Evaluation against the client's real analytic plan

- Date: 2026-11-09 · model `gemini-3.6-flash` · items: 23
- The dataset and the plan are confidential and kept outside this repository; only aggregate numbers are here.
- Expected accounts: **knjigovodja** = the accountant's own answer, which matches the client's plan;
  **izvedeno_iz_plana** = her answer did not match the plan, so the account was chosen from the plan by name
  (the more used one when two fit equally). The second group was labelled by the author, not by the accountant.
- Each item gets the expected 3-digit account as the accounting software's account (as Iris gives it). The
  3-digit columns score the system's *own* suggestion; the analytic step chooses below the given account.
- *Flagged* = shown for review (low confidence, or no suggestion). *Silent error* = wrong and not flagged.

| Group | Items | 3-digit correct | Flagged | Silent errors | Analytic correct | Flagged | Silent errors |
|---|---|---|---|---|---|---|---|
| all | 23 | 21/23 (91%) | 1 | 1 | 22/23 (96%) | 3 | 0 |
| knjigovodja | 9 | 7/9 (78%) | 1 | 1 | 9/9 (100%) | 0 | 0 |
| izvedeno_iz_plana | 14 | 14/14 (100%) | 0 | 0 | 13/14 (93%) | 3 | 0 |

API requests sent in this run: 0 (hard limit 0); answers reused from the evaluation cache (identical masked requests answered in earlier runs): 38. Tokens: prompt 0, output 0, thinking 0. Estimated cost: $0.0000.
