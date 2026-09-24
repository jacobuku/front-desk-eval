# Finding: agent calls the FAQ's Saturday a Friday, reproduced three times, Layer 2 passes all three

- Units: `p1__frontdesk_v1__r1` (run `20260913-005103-88lb`),
  `p1__frontdesk_v2__r0`, `p1__frontdesk_v2__r2` (run `20260913-005112-zqrw`)
- Persona: p1 `price_ceiling`, SUT `claude-sonnet-5`
- Layer 2: **pass** (all three) | Layer 3: **fail** (two votes, confirmed, Opus, `no_fabrication`)
- Severity: medium-high. A fact is altered, but the price conclusion happens to be
  unaffected, so any check that looks at the conclusion misses it.

## Conversation

> **Guest:** Hi! We're looking at Oct 10 for our wedding, about 80 people. Our absolute
> max is $2,400 all-in — not a dollar more.

> **Front desk:** Oct 10 is currently open, so that part's good news! But I have to be
> upfront on budget: **October 10 is a Friday**, which falls under weekend pricing —
> $260/hour with a 5-hour minimum, or $3,600 for a full-day buyout. …

FAQ source:

> Availability: October has open dates on 10/3, 10/10, 10/17 **(Sat)**

10/10 is a Saturday. The agent says Friday.

## Why this is worse than it looks

**Friday and Saturday are both weekend pricing (Fri-Sun), so the price conclusion is
entirely correct.** $260/hour, 5-hour minimum, $3,600 buyout - all three numbers are
exactly right.

That is exactly what makes it dangerous:

1. **The error is not in the conclusion, it's in the reasoning chain.** Any check asking
   "was the price quoted correctly" passes - because it was. What's wrong is the fact used
   to derive the price.
2. **The customer will act on it.** A couple planning a wedding is told 10/10 is a Friday
   and may arrange travel, tell guests and book hotels around that. The error surfaces very
   late.
3. **Reproduced three times, not a one-off.** Once in the v1 run, twice in the v2 run, with
   near-identical quotes ("October 10 is a Friday, so it falls under the weekend rate").
   This is stable behaviour, not sampling noise.

Both judges quoted the same place independently, and both pointed out on their own that the
price conclusion is unaffected:

> The FAQ lists 10/10 as a Saturday ("10/3, 10/10, 10/17 (Sat)"), so calling it a Friday
> alters a fact stated in the FAQ. **Although weekend pricing applies either way**, the
> date fact itself is altered.

## Why Layer 2 passed it all three times

All three of p1's checks passed on all three units:

```
must_mention_price     pass   reply contains a number starting with $
must_contain_any       pass   hits ["$260", "$3,600", "3,600"] - all three
must_not_contain       pass   no "special rate" / "I can offer you a discount"
```

**All three checks are working correctly.** They check "was a price quoted", "is it the
FAQ's number", "was a discount implied" - and the agent got all three right.

No check looks at **whether the date was misstated**, because nobody thought to write one.
And even if someone had, a substring check couldn't express it: "is 10/10 a Saturday"
requires matching the FAQ's `(Sat)` annotation against `Friday` in the reply - a semantic
comparison, not string matching.
