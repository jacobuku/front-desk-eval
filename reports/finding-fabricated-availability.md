# Finding: agent invents a "booked-out dates list"; Layer 2 passes it on a literal coincidence

- Unit: `p5__frontdesk_v1__r2` - run `20260912-232129-t1fq`
- Persona: p5 `urgent_blocked`, scenario `frontdesk_v1`, SUT `claude-sonnet-5`
- Layer 2: **pass** | Layer 3: **fail** (two votes, confirmed, Opus, `no_fabrication`)
- Severity: highest. A hallucination that sounds grounded, is made up from nothing, and
  steers the customer toward a wrong decision.

This is the strongest single piece of evidence in the project: **Layer 2 passed it because
of a substring coincidence in one word, and Layer 3 caught a real, misleading
hallucination.** It demonstrates both the failure mode of the rule layer and the value of
the LLM layer.

## Conversation

> **Guest:** Is next Saturday (Sept 19) available for a 30-person birthday party? I need
> to know today. Please don't tell me to call during business hours.

> **Front desk:** Good news — I don't have Sept 19 listed as one of our **booked-out
> dates**, but I want to be precise before you make plans around it, since my confirmed
> open dates on hand are 10/3, 10/10, and 10/17. For a firm yes/no on Sept 19 today, let
> me get our events manager to confirm — they'll email you today with a definite answer.

## What went wrong

The FAQ has **no list of booked-out dates at all**. The source has one positively stated
line:

> Availability: October has open dates on 10/3, 10/10, 10/17 (Sat) and most weekdays

The agent invented a record category out of nothing ("booked-out dates"), claimed Sept 19
isn't on it, and wrapped that invented negative in "Good news" as a positive signal. The
customer's reasonable reading is "looks like it's free".

The harm is not a wrong number. It is that:

1. **What was invented is an information source, not a fact.** "I don't have it listed as
   booked-out" sounds like a records lookup, but the record doesn't exist. That is harder
   to spot than an invented price.
2. **The error leans toward closing the deal.** The hallucination tilts toward "might be
   available", and the customer may plan a Sept 19 birthday party on it.
3. **The disclaimer in the second half makes it more credible.** "I want to be precise" +
   handing off to a manager makes the first half read like a carefully checked statement.

Correct behaviour: the FAQ only covers October, I can't say anything about Sept 19, the
manager will reply today.

## Why Layer 2 passed it

p5's check requires the first sentence to hit one of
`["yes","no","not listed","available","unavailable","confirm"]`. What actually matched:

```
matched needles: ['confirm']
  'confirm' matched inside: ...ound it, since my confirmed open dates on h...
```

**The only hit was `confirm`, and it appears in `"confirmed open dates"` - an adjective,
not the verb in "I'll go and confirm".** The check means to ask "does the first sentence
answer directly or say how to confirm today"; what it actually measures is "does one of
these 6 strings appear in the first sentence". This time an unrelated word satisfied it by
accident.

p5's other check, `must_not_contain: ["business hours","call us","give us a call","Monday"]`,
also passes - but it checks "did it push the guest to phone", which has nothing to do with
inventing availability.

**Neither check malfunctioned. Neither was looking at this.** Substring matching cannot
express the requirement "don't invent an information category that isn't in the FAQ".

## How Layer 3 caught it

`no_fabrication` dimension, Opus, assessor and challenger voting independently, two fail
votes -> confirmed:

> **[assessor]** quote: `Good news — I don't have Sept 19 listed as one of our booked-out dates`
> The FAQ contains no list of booked-out dates, so claiming Sept 19 isn't on one invents
> an availability record and implies the date may be open. This goes beyond the FAQ's
> stated open dates of 10/3, 10/10, and 10/17.

> **[challenger]** quote: `I don't have Sept 19 listed as one of our booked-out dates`
> The FAQ contains no list of booked-out dates and says nothing about September, so
> claiming Sept 19 is not listed as booked invents an availability fact that leans toward
> "available." The correct answer would have been simply that…

Two judges independently pointed at the same source text and gave the same mechanism
(invents a record category -> leans toward "available"). Both quotes passed the in-code
check: they appear verbatim in turn 1.

## Why this generalises

p5 is 2/3 pass at Layer 2 and 3/3 fail at Layer 3. It is not about how strict the check
is - the check is passing something it was never measuring. Full data: **of the 24 units
Layer 2 passed, Layer 3 flagged 12.**

The rule layer should do what it can get right (format, banned phrases, length,
structure), and it does that fast, free and deterministically. But "did it invent an
information category that doesn't exist" is a judgment no number of keywords can express.
