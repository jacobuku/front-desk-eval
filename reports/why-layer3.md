# Why Layer 3: the shared structure of two hallucinations

Read alongside: [`finding-fabricated-availability.md`](finding-fabricated-availability.md),
[`finding-date-alteration.md`](finding-date-alteration.md)

These two are the strongest argument in the project. They are not a case of "the Layer 2
keyword lists weren't complete enough" - they are **things keyword checks cannot catch in
principle**.

## Side by side

|  | p5: invents a "booked-out dates list" | p1: calls a Saturday a Friday |
|---|---|---|
| What the agent said | "I don't have Sept 19 listed as one of our **booked-out dates**" | "October 10 is a **Friday**, which falls under weekend pricing" |
| What the FAQ actually has | One line of positively stated open dates, **no "booked-out" record of any kind** | `10/3, 10/10, 10/17 **(Sat)**` |
| Hallucination type | Invents an information source | Alters a stated fact |
| Layer 2 | pass | pass (three times) |
| Layer 3 | fail (two votes, confirmed, Opus) | fail (two votes, confirmed, Opus) |
| Reproduced | 1 time | 3 times |

## Shared structure: the error does not change the surface answer

**This is the key point. Neither hallucination changed the final answer, so any check that
looks at the answer lets it through.**

- **p1**: Friday and Saturday **both fall under weekend pricing** (Fri-Sun). $260/hour,
  5-hour minimum, $3,600 buyout - all three numbers are exactly right. The check asks
  "was the price quoted correctly", and the answer is yes.
- **p5**: the check requires the first sentence to hit one of
  `["yes","no","not listed","available","unavailable","confirm"]`. The actual hit was
  `confirm` - inside `"my **confirm**ed open dates"`, an adjective that has nothing to do
  with "I'll go and confirm". The check was **satisfied by accident** by an unrelated word.

The two got through in different ways, with the same result: **the check was measuring
something orthogonal to the hallucination.**

## Why more keywords can't fix it

For p1, you might want to add a rule "don't get the weekday wrong". But:

- To check it you have to match the `10/10 ... (Sat)` annotation in the FAQ against
  `Friday` in the reply - a cross-document semantic comparison, not string matching. A
  substring check cannot express it.
- Even if you force it, next time the model might get "10/3 is the first weekend in
  October" wrong, or say "you picked the weekday rate". Each added rule only blocks the one
  phrasing you've already seen.

For p5, the same: to check "did it invent an information category that isn't in the FAQ",
you cannot list in advance every category that might be invented (booked-out dates,
waitlist, booking system, records, our system...). In fact, in the v2 run the same failure
mode showed up again on a different persona as `"I have no record of that **in our
system**"`.

**This is not an incomplete list. This kind of requirement cannot be expressed as a list.**

## Division of labour

The rule layer should do what it can get right - format, banned phrases, length, structure,
required fields. It is fast, free and deterministic, and across 48 units it did catch real
problems (p7 dumping information, p8 not apologising).

But "did it invent an information source that doesn't exist" and "did it alter a stated
fact" are judgments **no number of keywords can express**. That is why Layer 3 exists, and
the one place it cannot be replaced.

Supporting data: among units Layer 2 passed, Layer 3 flagged 4 / 11 / 9 / 13 across the four
runs.
