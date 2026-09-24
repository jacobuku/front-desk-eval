# front-desk-eval

front-desk is a planned agent that answers customer enquiries for small businesses across
several channels. **Only the evaluation layer in this repo exists so far. The agent is not
built yet: it exists only as a spec.** That order is deliberate: first a way to tell whether an
agent's answer is right, then the agent.

To exercise the harness, the system under test (SUT) here is a stand-in: an event-venue front
desk that is a single LLM call (`claude-sonnet-5`) with `faq.md` in the system prompt, no tools,
single-turn. Two prompt versions, `prompts/frontdesk_v1.md` and `prompts/frontdesk_v2.md`, are
compared.

**Demo video (3 min):** https://youtu.be/ZOGRgDQy0Ww

## Result

The clean comparison uses v1 = run `20260913-005103-88lb` and v2 = run `20260913-005112-zqrw`.
The personas, FAQ, rubric and deferrals have identical fingerprints in both runs. The prompt
file is the only variable. Each version has 8 personas × 3 repeats = 24 units.

|                                   | v1            | v2                    |
|-----------------------------------|---------------|-----------------------|
| Layer 2, deterministic rules      | 23/24         | **24/24**             |
| Final (Layer 3 judges + Layer 4)  | **14/24 (58%)** | 11/24 (46%)         |
| confirmed fail                    | 8             | 6                     |
| disputed                          | 2             | 7                     |

v2 got a perfect score from the rule layer and the lower score overall. **Conclusion: v2
should not ship.**

What the LLM layer caught that keyword checks could not:

- **A weekday changed, with a correct price.** In 2 of 3 v2 units (and 1 of 3 v1 units), the
  agent said October 10 is a Friday. The FAQ says `10/10 ... (Sat)`. Friday and Saturday share
  the weekend rate, so the quoted price was correct and every price keyword matched. The
  conclusion was right, but the fact behind it was wrong.
  [`reports/finding-date-alteration.md`](reports/finding-date-alteration.md)
- **An invented record presented as a lookup.** The agent said "I don't have Sept 19 listed as
  one of our booked-out dates". The FAQ contains no such list. This came from v1 in an earlier
  run (`20260912-232129-t1fq`, before the prompt revision). Layer 2 passed it because `confirm`
  matched inside the word "confirmed". Under the pre-revision prompts, v2 spread the same shape
  to four personas, for example "I have no record of that in our system".
  [`reports/finding-fabricated-availability.md`](reports/finding-fabricated-availability.md)

![v1 vs v2, Layer 2 and final](reports/images/compare.png)

Write-ups:
- [`reports/why-layer3.md`](reports/why-layer3.md): why these two can't be caught by keyword checks
- [`reports/v1-vs-v2.md`](reports/v1-vs-v2.md): the full history, including the rubric bug and the re-judge

## Architecture

```
L0  Input validation (code, no model)      evalkit/loader.py
    persona schema + check vocabulary, scenario files reachable,
    API key present, 1-token preflight call before any fan-out.
    Bad input stops the run; it is never a warning.
        |
L1  Conversation execution                  evalkit/runner.py, evalkit/sut.py
    persona x scenario x repeat (K=3), asyncio + semaphore.
    Units are independent; auth/model errors abort the whole run.
    One JSON transcript per unit -> runs/<run_id>/units/<unit>.json
        |
L2  Deterministic rules (code, no model)    evalkit/checks.py
    18 checks across 8 personas, unit-tested.
    Four states: pass / fail / no_evidence / deferred
        |
L3  LLM judge                               evalkit/judge.py, rubric.json
    one call per (transcript, dimension, role);
    assessor + challenger vote independently, never see each other.
    Safety dimensions -> Opus, the rest -> Sonnet.
        |
L4  Deterministic adjudication (code)       evalkit/adjudicate.py
    >= 2 fail votes = confirmed
       1 fail vote  = disputed (delivered with the dissent attached)
       0 valid votes = dropped
```

### Two design choices

**1. The judge has to pass a golden set before it may score anything.** `goldens/cases.json`
has 19 hand-labelled transcripts with 50 labels, 15 of which are planted failures. `evalkit golden`
measures recall and false-positive rate against the bars in `evalkit/config.py` (80% / 10%).
Below either bar, the command prints `GATE FAILED` and exits 3, and the rubric gets fixed before
anything is judged. This is a step in the workflow; the `judge` command does not read the gate
result itself. The current
results are **93% recall (14/15) and 3% false positives (1/34)**. On its first run, the gate
caught a judge fabricating a quote.

![golden-set gate](reports/images/gate.png)

**2. Evidence must be quoted verbatim and is checked in code.** Every pass or fail vote must cite
a turn id and quote it. `adjudicate.validate_vote` normalises quote marks and dashes, then
checks that the quote appears in the cited turn. A vote that fails the check is voided and not
counted. So a judge can't assert a failure it can't point to.

## What this does not claim

- **Two checks are deferred, not counted as passes.** Substring matching can't tell affirmation
  from negation. For example, `p3.must_not_contain` flags "I can't confirm refunds or compensation
  myself", which is a refusal, because it contains `compensat`. `p4.must_contain_any` fails on a
  paraphrase ("in writing" vs "written"). Both are recorded with a reason and a judge question in
  `deferrals.json`. Layer 2 marks them `deferred` and excludes them from the rollup, and Layer 3
  judges them. `personas.json` was not edited to make any check pass.
- A passed gate only shows the rubric is right on the shapes the golden set covers. When a
  suspicious verdict turns up in a real run, it goes back into the golden set as a new case.
  `v1-vs-v2.md` records one that was missed.
- The sample is small: 8 single-turn personas, 3 repeats, one SUT model.
- The SUT is a stand-in, not the front-desk agent.

## Cost

$9.89 in total. That covers every SUT run, judge run and golden-set run in this repo. For scale,
one 24-unit SUT run costs about $0.05, and judging it takes 300 judge calls at about $1.8–1.9.

## Quickstart

There is no dependency file. The only runtime dependency is `anthropic`, and the harness was
developed and tested on Python 3.14 with `anthropic==1.5.0`.

```bash
cd front-desk-eval
python3 -m venv .venv
.venv/bin/pip install anthropic==1.5.0

# No API key needed: read the stored runs and run the unit tests
.venv/bin/python -m evalkit.cli show 20260913-005112-zqrw          # Layer 2 view of v2: 24/24
.venv/bin/python -m evalkit.cli verdicts 20260913-005112-zqrw      # Layer 3-4 view of v2
.venv/bin/python -m evalkit.cli compare 20260913-005103-88lb 20260913-005112-zqrw
.venv/bin/python tests_checks.py                                   # Layer 2
.venv/bin/python tests_adjudicate.py                               # Layer 4

# Needs a key (read from .env or the environment)
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
.venv/bin/python -m evalkit.cli validate                           # Layer 0 only, no model calls
.venv/bin/python -m evalkit.cli golden                             # judge gate; exits 3 if it fails
.venv/bin/python -m evalkit.cli run --scenario frontdesk_v2        # Layer 0-2, 24 units
.venv/bin/python -m evalkit.cli judge                              # Layer 3-4 on the latest run
```

Other commands: `run --dry-run` (prints the unit plan), `judge --dry-run` (prints the call count),
`run --resume RUN_ID` and `judge --resume` (skip finished units), and `rescore [RUN_ID]`. `rescore`
re-applies Layer 2 to stored transcripts with no API calls and **rewrites the stored unit files**.

## Layout

```
personas.json      8 personas: first_message + Layer 2 checks + llm_check
faq.md             the SUT's only source of facts, appended to its system prompt
prompts/           frontdesk_v1.md (baseline), frontdesk_v2.md (answer-first, <150 words)
scenarios.json     SUT config (model, max_tokens, thinking)
deferrals.json     checks handed to Layer 3: reason (for humans) + intent (for the judge)
rubric.json        cross-persona dimensions
goldens/           cases.json (hand-labelled) + results/ (every gate run)
evalkit/           loader (L0), runner + sut (L1), checks (L2), judge + rubric (L3), adjudicate (L4)
runs/<run_id>/     manifest.json (input sha256s), units/, judgments/, summary.json
reports/           findings, terminal captures, images
tools/             render_capture.py (terminal output -> PNG; needs Pillow)
```

## The agent

The front-desk agent has a spec (Gmail and Telegram channels, classification into action levels,
human approval before anything is sent), and that spec lives in a separate repo. None of it is
implemented yet.
