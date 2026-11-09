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
| all | 23 | 20/23 (87%) | 1 | 2 | 22/23 (96%) | 0 | 1 |
| knjigovodja | 9 | 6/9 (67%) | 1 | 2 | 9/9 (100%) | 0 | 0 |
| izvedeno_iz_plana | 14 | 14/14 (100%) | 0 | 0 | 13/14 (93%) | 0 | 1 |

API requests sent: 31 (hard limit 33); answers reused from the evaluation cache (identical requests of the earlier synthetic run): 7. Tokens: prompt 32302, output 2331, thinking 15650. Estimated cost: $0.0917.
