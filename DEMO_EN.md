DEMO Script (English)

Before recording: cd ~/Downloads/front-desk-eval → source .venv/bin/activate → terminal fullscreen, font size up → Do Not Disturb on

0:00–0:20 Open

"The system under test is a venue front-desk agent — one LLM call plus an FAQ. The question I need to answer is simple: which of two prompt versions is better. Here's the conclusion first — the rule layer gave the second version a perfect score. Add the LLM layer, and the verdict is that it should not ship."

clear
.venv/bin/python -m evalkit.cli validate

"Layer 0 validates inputs first: 8 personas, 2 scenarios. If the data is bad, it stops — no analysis on top of broken input. Note these two deferred lines, I'll come back to them."

0:20–0:50 How it runs
clear
.venv/bin/python -m evalkit.cli run --dry-run

"The unit of concurrency is persona times scenario times repeat — 24 units. They're independent, so they fan out; inside each unit it's a single sequential call. Running three times isn't for averaging — it's to catch instability. If the same input gives you three different verdicts, that pass isn't trustworthy."

0:50–1:20 What the rule layer says
clear
.venv/bin/python -m evalkit.cli show 20260913-005112-zqrw

(pause two seconds)

"This is v2 at the rule layer: 24 out of 24. Perfect. If this were the only layer, the answer is v2 is flawless — ship it."

1:20–2:00 What the LLM layer sees
clear
.venv/bin/python -m evalkit.cli verdicts 20260913-005112-zqrw

"Same transcripts, now with an LLM judge. The L2 column is all PASS. The L3 column is full of FAIL and DISP. Of 24 units, only 11 pass clean — 13 are flagged."

"The clearest one is p1. The agent says October 10th is a Friday. The FAQ says Saturday, in writing. Three out of three. And the price it quoted is completely correct — because Friday and Saturday are both weekend rate, so all three numbers match. Any check asking 'did it quote the right price' passes this. The conclusion isn't wrong. The fact it reasoned from is."

"There's a worse one. The agent invented a 'booked-out dates list' that doesn't exist anywhere in the FAQ, implying a date might be open. The rule layer passed it because the substring 'confirm' inside the word 'confirmed' happened to match a keyword."

2:00–2:40 Why trust the judge
open reports/images/gate.png

"The judge gets measured before it's allowed to score anything. 19 hand-labeled transcripts, 15 with planted failures. We compute recall and false positive rate. 93% recall, 3% false positives. It has to clear the gate before it can score the SUT."

"Two judges vote independently and can't see each other. The verdict is a code rule: two fail votes confirm, one fail is disputed and ships with the dissent attached, zero valid votes gets dropped. The model never produces the final call."

"There's one more mechanical gate: every vote has to quote the transcript verbatim, and the quote is verified against the record in code. A vote whose quote can't be found is voided. The golden set caught a judge fabricating a quote immediately — without that check, it would have been a two-vote confirmed false positive."

(Cmd+W to close the image)

2:40–3:00 The verdict
clear
.venv/bin/python -m evalkit.cli compare 20260913-005103-88lb 20260913-005112-zqrw

"Clean comparison. The only variable is the prompt file — personas, FAQ, and rubric all have identical fingerprints."

"Top half is the rule layer: v2 is 100%. Bottom half is the final verdict: v1 is 58%, v2 is 46%. Same transcripts, opposite answers."

"Cost is eight cents to run, two dollars to judge. The rule layer should do what it's good at — fast, free, deterministic. But 'did it invent an information source that doesn't exist' is a judgment no amount of keywords can express. That's the one thing the LLM layer can't be replaced on."

Backup Q&A

Why not have one judge score every dimension?
Dimensions are scored independently so they don't contaminate each other. And safety dimensions run on Opus while the rest run on Sonnet — you can't tier that if they're bundled.

Isn't disputed too high?
The first round had 8. The root cause was that the judge didn't know what the SUT is required to do — handing off to a manager and stating the limits of its authority are both mandated by the prompt, and the judge was reading them as violations. Writing the behavioral contract into the judge's shared prompt brought it to zero. The key word is shared: I first fixed the wording on one dimension, and the same misjudgment reappeared under a different one.

If I change a check, do I have to re-run everything?
No. rescore recomputes the rule layer against transcripts already on disk, zero API calls. That's why you persist between the two fan-outs.

Why not just make the rules stricter?
Tried it, doesn't work. Checking whether October 10th is a Saturday requires comparing the "(Sat)" in the FAQ against the word "Friday" in the reply — a cross-document semantic comparison a substring check can't express. Checking whether the agent invented an information category is worse: you can't enumerate it in advance. In testing, the same pattern reappeared under a different persona with a different made-up name.
