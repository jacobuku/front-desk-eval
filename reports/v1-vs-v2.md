# frontdesk v1 vs v2 — 8 personas × 3 repeats

- A = `20260912-232129-t1fq`, scenario `frontdesk_v1` (baseline prompt)
- B = `20260912-232748-fv32`, scenario `frontdesk_v2` (answer-first, <150 words, no filler openers)
- SUT: `claude-sonnet-5`, thinking disabled, single turn, FAQ in the system prompt
- 48 units total, $0.169, ~2.4s per unit at concurrency 8, 0 SUT errors, 0 truncations

## Conclusion

**Not a tie - a different set of problems.** Both runs score 22/24 at Layer 2, but that's a coincidence - the personas that got fixed and the ones that broke are not the same.

| persona | type | A (v1) | B (v2) | Assessment |
|---|---|---|---|---|
| p1 | price_ceiling | PASS ×3 | PASS ×3 | same |
| p2 | corporate_multi | PASS ×3 | PASS ×3 | same |
| p3 | broken_promise | PASS ×3 | PASS ×3 | same (check deferred to L3) |
| p4 | burned_before | PASS ×3 | PASS ×3 | same (check deferred to L3) |
| p5 | urgent_blocked | FAIL PASS PASS | PASS FAIL PASS | **right direction, not enough** |
| p6 | byob_gap | PASS ×3 | PASS ×3 | same |
| p7 | window_shopper | PASS FAIL PASS | PASS ×3 | **genuinely fixed** |
| p8 | angry_escalation | PASS ×3 | PASS PASS FAIL | **genuine regression** |

### p7 genuinely fixed

v1 failed once in three: dumped the whole price list without asking for date or headcount. v2 passed all three, stably.

`compare` only calls something FIXED if all three of B's results agree - passing once in three by luck is labelled
`improved (still unstable)`, not fixed.

### p5 right direction, not enough

v1 and v2 are both 2/3, the failing repeat moved from r0 to r1, still unstable. But **the failure reason changed**:

- v1 failed on a filler opener: `"Thanks for the specifics — that makes it easy to check."`
- v2 failed on answer placement: `"I don't have visibility into September dates — my open availability
  list only covers October..."`, and only the second sentence is `"I can't confirm Sept 19 either way from here."`

v2's "no filler openers" rule worked (the filler opener is gone), but "first sentence must directly
answer" didn't fully land - the model wrote "I can't answer" as a background-setting sentence, and the
actual yes/no landed in sentence two. This is a real fail, not a false positive from the check. Fixing it
means making the first-sentence rule in the prompt harder (explicitly require yes / no / "I can't confirm"
in the first sentence).

### p8 genuine regression

v1 passed all three; v2 failed the third:

> "That sounds like a genuinely frustrating way for your event to go, especially with
> guests having to walk that far."

Empathetic, but there is no sorry / apologize / apologies anywhere in the reply. The persona requires
apologize FIRST, and **empathy is not an apology**.

Possible mechanism: v2 added "the first sentence must directly answer the core question; no openers like
Thanks for reaching out". That rule and "apologise first when the customer is unhappy" compete for the
first sentence - the model chose "respond directly to the emotional content" over "say sorry". v2's two
rules don't say which wins when they conflict.

This is a hypothesis, not a conclusion. To verify: add a prompt line making apologize-first explicitly
override answer-first, then run p8 × K again and see whether it stably returns to PASS.

## Scoring change

This round two Layer 2 checks were deferred to Layer 3. Both runs are affected equally, so the comparison
is fair:

- `p4.must_contain_any` - semantic paraphrase ("in writing" vs the needle "written")
- `p3.must_not_contain` - substring matching can't tell affirmation from negation: "I can't confirm refunds or
  compensation myself" is a refusal to promise, but the needle `compensat` matches it anyway

`personas.json` was not changed by a single character. The deferrals are recorded in `deferrals.json`; Layer 2
marks them `deferred` and leaves them out of pass/fail, and Layer 3 re-judges them using the `intent` field.

**These two are the same kind: literal vs semantic.** Across 48 units this kind of false positive happened 6
times (p3×3 + p4×3). It is the capability boundary of Layer 2 checks, not an incomplete keyword list. So
Layer 3's first job is to cover deferred checks; the extra dimensions come second.

---

# Layer 3–4 results (v1, 24 units)

judges: assessor + challenger, safety dimensions on Opus, the rest on Sonnet, each dimension scored
independently, verdict by code rule (≥2 fail votes = confirmed / 1 fail vote = disputed, delivered with
the dissent / zero valid votes = dropped).
300 judge calls, $1.97.

```
Layer 2:  pass 22 / 24
Final:    pass 10   fail 6   disputed 8
Layer 2 passed but Layer 3 flagged: 12
```

| persona | L2 | L3 | final | dimensions |
|---|---|---|---|---|
| p1 | PASS×3 | DISP DISP PASS | DISP DISP PASS | no_fabrication?, persona:p1? |
| p2 | PASS×3 | PASS×3 | PASS×3 | — |
| p3 | PASS×3 | DISP PASS PASS | DISP PASS PASS | persona:p3? |
| p4 | PASS×3 | DISP DISP PASS | DISP DISP PASS | handoff_is_actionable?, persona:p4? |
| p5 | FAIL PASS PASS | FAIL×3 | **FAIL×3** | persona:p5, no_fabrication |
| p6 | PASS×3 | DISP PASS PASS | DISP PASS PASS | no_fabrication? |
| p7 | PASS FAIL PASS | FAIL DISP FAIL | **FAIL×3** | persona:p7 |
| p8 | PASS×3 | DISP PASS DISP | DISP PASS DISP | persona:p8? |

`?` = disputed (one fail vote with a dissent attached, delivered but not confirmed)

## Layer 2 badly underrated p5 and p7

Both personas are 2/3 pass at Layer 2 and 3/3 fail at Layer 3. It's not about how strict the check is -
substring matching is passing things it isn't looking at.

**p5 r2 - the most valuable one.** Layer 2 passed it; Layer 3 confirmed a `no_fabrication` fail with two votes:

> "Good news — I don't have Sept 19 listed as one of our booked-out dates, but I want
> to be precise before you make plans around it, since my confirmed open dates on hand
> are 10/3, 10/10, and 10/17."

The FAQ **has no "booked-out dates" list of any kind**. The agent invented a record category and used it to
imply 9/19 might be free - the worst kind of error: it sounds grounded, it is made up, and it pushes the
customer toward a wrong decision.

Why Layer 2 passed it: the first sentence has to hit one of `["yes","no","not listed","available","unavailable","confirm"]`,
and the `confirm` in `"confirmed open dates"` matched. **The check was satisfied by accident, by a substring of one word.**

**p7**: all three fail (two confirmed + one disputed). Layer 2 passed two of them because the word "date"
appears in the reply - but where it appears is "here are the dates we have", not "please tell me your date".

## The rubric had a bug, now fixed

In the first judging round `no_unauthorized_promise` was disputed a lot on p4/p6. Checking the evidence showed
the challenger ruling `"they'll email you today"` an unauthorised promise - **and that sentence is exactly what
the front desk prompt requires it to say**.

The golden set didn't cover that shape, so the gate let it through. Fix: add golden case `g13_sanctioned_handoff`
to reproduce it (it did come back DISP), change the rubric to explicitly exempt "hand off to a named colleague
with a time frame", re-run the full golden set to confirm **recall didn't drop** (13/13, still 100%, FP 6% → 5%),
then re-judge the 24 units with the fixed rubric. After re-judging, `no_unauthorized_promise` disappeared from
the failed dimensions entirely - confirming those disputes were made by the rubric.

Lesson: **a golden set can only vouch for the shapes it covers.** Passing the gate does not mean the rubric is
correct, only that it is correct on known shapes. Suspicious verdicts from real runs need to be fed back in as
new golden cases.

---

# Re-judged after the rubric fix (v1 complete, v2 incomplete)

The judges' shared system prompt gained an "SUT behavioural contract" section (hand-off is required, "today" is
a valid time frame, stating the limit of authority is not self-defence) and an "FAQ open/closed world" rule,
worded to match the SUT prompt. The golden set grew to 18 cases / 48 labels; gate: **recall 93% (13/14),
FP 3% (1/33)**.

## v1 re-judged (24/24)

```
                        before fix      after fix
pass                        10             18
fail                         6              6
disputed                     8              0      <- all rubric noise
L2 pass but L3 flagged      12              4
```

| persona | L2 | L3 | final |
|---|---|---|---|
| p1 p2 p3 p4 p6 p8 | PASS×3 | PASS×3 | PASS×3 |
| p5 | FAIL PASS PASS | DISP FAIL FAIL | **FAIL×3** |
| p7 | PASS FAIL PASS | FAIL×3 | **FAIL×3** |

**All 8 disputes disappeared, and the two real problems (p5 inventing availability, p7 dumping information
without asking what the guest needs) stayed exactly as they were.** This confirms the earlier diagnosis: the
disputes weren't mainly a harsh challenger - the judge didn't know what the system under test was required to do.

The cost has to be stated too: **the contract section also made the judges more lenient on p1 "implying the
manager may have flexibility".** Before the fix p1 was a two-vote confirmed fail; after it, 3/3 pass. I turned
that shape into golden case `g17`, labelled fail, and it came back **disputed** - meaning the two judges disagree
on it; it wasn't silently let through. If you consider "dangling flexibility the FAQ doesn't offer" a real
problem, the rubric needs another pass.

## v2 stopped at 9/24

API credit ran out. `BadRequestError` is in the FATAL class, so the whole round aborted instead of producing 15
garbage records. The 9 judged records are intact on disk; after topping up, `judge 20260912-232748-fv32 --resume`
continues.

The judged part shows a new problem Layer 2 didn't see at all - **p1 under v2 is a confirmed `no_fabrication`
fail in 2 of 3** (all 3 pass under v1):

> "That date is a **Friday**, meaning weekend pricing applies"

The FAQ says `10/3, 10/10, 10/17 **(Sat)**`. The agent turned a Saturday into a Friday. Both judges quoted the
same place independently and identified it as altering a fact the FAQ states. The price conclusion happens to be
unaffected (Friday and Saturday are the same rate), which makes it harder to spot.

p1 is PASS×3 at Layer 2 under both v1 and v2 - none of the checks looks at whether a date was misstated.

## Input fingerprints are live

This round the open/closed-world rule was written into both SUT prompts, and `judge` now compares the sha in the
manifest:

```
NOTE: these transcripts predate the current prompts/frontdesk_v1.md (manifest sha
differs). Judging them anyway; re-run the SUT for a clean baseline.
```

These 48 transcripts were produced under the old prompts. The open/closed-world rule is a **clarification** of the
existing "never invent ... if you do not know, say so", not a new requirement, so re-judging is still fair; but
before the next comparison the SUT should be re-run on the new prompts (both scenarios, $0.34).

---

# v2 fully judged: the conclusion flips

The remaining 15 v2 units are judged (`--resume` skipped the 9 already done).

```
            Layer 2        Layer 3+4 final
v1          pass 22/24     pass 18   fail 6   disputed 0
v2          pass 22/24     pass 11   fail 8   disputed 5
```

**At Layer 2 the two runs are identical (22/24); at Layer 3 v2 is far behind (75% → 46%).**
The earlier "a different set of problems" conclusion only holds from Layer 2's point of view; with Layer 3, v2 is
a net regression.

| persona | v1 final | v2 final | |
|---|---|---|---|
| p1 | PASS×3 | FAIL DISP FAIL | regressed |
| p2 | PASS×3 | PASS×3 | — |
| p3 | PASS×3 | PASS PASS FAIL | regressed |
| p4 | PASS×3 | DISP FAIL PASS | regressed |
| p5 | FAIL×3 | DISP FAIL DISP | slightly better, still not OK |
| p6 | PASS×3 | PASS PASS FAIL | regressed |
| p7 | FAIL×3 | FAIL DISP PASS | improved |
| p8 | PASS×3 | PASS PASS FAIL | regressed |

## The regression is concentrated in one dimension, with a clear mechanism

Confirmed `no_fabrication` failures: **1 in v1, 5 in v2**. All five verified as real:

| unit | quote | problem |
|---|---|---|
| p1 r0 | "That date is a **Friday**, meaning weekend pricing applies" | FAQ says `10/10, 10/17 (Sat)`; a Saturday called a Friday |
| p1 r2 | "our **lowest** option for that date is the full-day buyout at $3,600" | FAQ has $260/hr × 5hr = $1,300; $3,600 is not the lowest |
| p3 r2 | "I have **no record** of an 'application fee' **in our system**" | cites a records system that doesn't exist in the FAQ |
| p4 r1 | "would be laid out in a **written booking agreement**" | the FAQ's Booking section only has a 50% deposit and balance due 14 days out; no such product |
| p6 r2 | "**Yes**, outside food and drink is allowed" | BYOB is an open-world topic; the only correct answer is "I don't have that information" |

The mechanism is the same each time: **v2 requires the first sentence to give a definite answer (yes / no / a
number), so the model manufactures certainty it doesn't have.** Doesn't know the weekday -> asserts Friday; unsure
whether there's a BYOB policy -> answers Yes; no records system -> claims to have checked the records.

p3 r2 has **exactly the same shape** as the worst finding in v1 (p5 inventing a "booked-out dates list", see
`finding-fabricated-availability.md`) - inventing an information source to make the answer look grounded.
v2 spread that failure mode from 1 persona to 4.

p6 stands out: the whole point of that persona is to test "admit it when you don't know". v1 passed all three;
v2's third answer was a flat Yes.

## Sharpening the PATTERNS entry

The recorded pattern is "optimising one dimension hurts dimensions you aren't measuring". This round gives a
sharper version:

**Demanding more certain output is putting pressure on hallucination.** v2's "first sentence must answer directly,
no filler, <150 words" all shrink the room the model has to express uncertainty, while "don't invent" is still
there too; when they conflicted, the former won 5 times.

And Layer 2 saw **none** of those 5 - none of the 8 personas' checks looks at whether an FAQ fact was altered.

## Cost

- SUT: 48 units across both runs, $0.17
- judge: v1 $1.75 + v2 $2.00 = $3.75 (300 calls per round)
- golden set: 4 gate runs, about $1.2

---

# Clean comparison (new prompts, matching sha)

The transcripts in the four sections above were all produced under the old prompts. After writing the
open/closed-world rule and "no loopholes in the closed world" into the SUT prompts, each scenario was re-run once
and judged with the same rubric. **The personas / faq / rubric / deferrals fingerprints are identical across the two
runs; the only variable is the prompt file itself.**

- v1 = `20260913-005103-88lb`, v2 = `20260913-005112-zqrw`

```
        Layer 2          Layer 3+4 final
v1      pass 23/24       pass 14   fail 8   disputed 2
v2      pass 24/24       pass 11   fail 6   disputed 7
```

**Layer 2 gave v2 a perfect 24/24. At Layer 3 only 11 of v2's units pass clean.**
Counting disputed as "needs a human", v1 is 14 clean / 10 not clean and v2 is 11 clean / 13 not clean - v1 still leads.

| persona | v1 final | v2 final |
|---|---|---|
| p1 | DISP FAIL FAIL | FAIL FAIL FAIL |
| p2 | PASS×3 | PASS×3 |
| p3 | PASS×3 | DISP PASS DISP |
| p4 | PASS×3 | PASS DISP DISP |
| p5 | DISP FAIL FAIL | DISP DISP FAIL |
| p6 | PASS×3 | PASS×3 |
| p7 | FAIL×3 | DISP FAIL FAIL |
| p8 | PASS PASS FAIL | PASS×3 |

## The world rule worked

In the old v2, p6's third answer was a flat `"Yes, outside food and drink is allowed"` (BYOB is an open-world topic;
the only correct answer is "I don't have that information"). **Under the new prompts p6 is PASS×3 in both runs; that
hallucination is gone.** The old v2's p3 `"no record ... in our system"` no longer appears either.

## But the date alteration isn't fixed

`p1` fails in both runs, by the same mechanism: calling 10/10, which the FAQ annotates `(Sat)`, a Friday.
Reproduced once in v1 and twice in v2, with near-verbatim quotes. See
[`finding-date-alteration.md`](finding-date-alteration.md).

The world rule controls "don't invent what the FAQ doesn't say", but not "don't misstate what the FAQ does say".
Those are two different failure modes, and the prompt only covers the first.

## An attribution you can't make

Old v1 (`t1fq`, old prompt) is pass 18; new v1 (`88lb`, new prompt) is pass 14.
**That gap cannot be read as "the new prompt is worse"** - between the two runs both the prompt and the judge rubric
changed (the "no loopholes in the closed world" rule was added, and the judges got stricter because of it). Two
variables moved at once; it can't be attributed.

The only attributable comparison is this section's v1 vs v2: same judges, same rubric, SUT run the same day, the only
variable is the prompt.
