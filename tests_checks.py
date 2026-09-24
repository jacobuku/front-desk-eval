"""Layer 2 unit tests. Run: .venv/bin/python tests_checks.py"""
from evalkit.checks import evaluate, first_sentence

def eq(got, want, label):
    assert got == want, f"{label}: got {got!r}, want {want!r}"
    print(f"  ok  {label}")

print("first_sentence")
eq(first_sentence("No, Oct. 3 is taken. Try 10/17."), "No, Oct. 3 is taken.", "abbrev not a boundary")
eq(first_sentence("Hi there! Happy to help."), "Hi there!", "filler opener is its own sentence")
eq(first_sentence("Weekend rate is $260/hour with a 5-hour minimum."),
   "Weekend rate is $260/hour with a 5-hour minimum.", "decimal-free price, single sentence")
eq(first_sentence("I'm sorry about the parking.\nHere is what we can do."),
   "I'm sorry about the parking.", "newline collapses, split still works")
eq(first_sentence(""), "", "empty")

print("statuses")
eq(evaluate(None, {"max_words": 10})["overall"], "no_evidence", "no reply -> no_evidence not fail")
eq(evaluate("   ", {"max_words": 10})["overall"], "no_evidence", "blank reply -> no_evidence")
eq(evaluate("anything", {"must_not_contain": []})["overall"], "no_evidence", "empty needles -> no_evidence")
eq(evaluate("anything", {})["overall"], "no_evidence", "no checks -> no_evidence")

print("individual checks")
eq(evaluate("It is $260/hour.", {"must_mention_price": True})["overall"], "pass", "price found")
eq(evaluate("Let me check for you.", {"must_mention_price": True})["overall"], "fail", "no price")
eq(evaluate("Seats 40, projector included, catering from $35.",
            {"must_contain_all": ["40", "projector", "$35"]})["overall"], "pass", "contain_all pass")
r = evaluate("Seats 40 with a projector.", {"must_contain_all": ["40", "projector", "$35"]})
eq(r["overall"], "fail", "contain_all fail")
eq(r["checks"][0]["detail"]["missing"], ["$35"], "contain_all reports what is missing")
eq(evaluate("I can offer you a discount.", {"must_not_contain": ["discount"]})["overall"], "fail", "banned phrase")
eq(evaluate("We may compensate you.", {"must_not_contain": ["compensat"]})["overall"], "fail", "prefix needle")
eq(evaluate("MUST NOT be CASE sensitive", {"must_not_contain": ["case sensitive"]})["overall"],
   "fail", "case-insensitive")
eq(evaluate("Sorry about that. Here is the plan.",
            {"first_sentence_must_contain_any": ["sorry"]})["overall"], "pass", "apology first")
eq(evaluate("Thanks for reaching out! Sorry about that.",
            {"first_sentence_must_contain_any": ["sorry"]})["overall"], "fail", "apology buried")
eq(evaluate("one two three", {"max_words": 3})["overall"], "pass", "at the limit")
eq(evaluate("one two three four", {"max_words": 3})["overall"], "fail", "over the limit")

print("rollup")
r = evaluate("I can offer you a discount of $50.",
             {"must_mention_price": True, "must_not_contain": ["discount"], "must_contain_any": []})
eq(r["overall"], "fail", "any fail dominates")
eq(r["failed"], ["must_not_contain"], "failed list names the check")

print("\ndeferred")
d = {"must_contain_any": "semantic paraphrase - Layer 3 owns this"}
r = evaluate("we will confirm terms in writing", {"must_contain_any": ["written"]}, deferred=d)
eq(r["checks"][0]["status"], "deferred", "deferred check is not evaluated")
eq(r["overall"], "no_evidence", "only-deferred unit rolls up to no_evidence, not pass")
eq(r["failed"], [], "deferred never counts as a failure")
eq(r["deferred"], ["must_contain_any"], "deferred list names the check")
eq(r["checks"][0]["detail"]["reason"], d["must_contain_any"], "reason is recorded on the record")

r = evaluate("we will confirm terms in writing",
             {"must_contain_any": ["written"], "must_not_contain": ["guarantee that"]}, deferred=d)
eq(r["overall"], "pass", "remaining checks still decide the rollup")
r = evaluate("I guarantee that nothing changes.",
             {"must_contain_any": ["written"], "must_not_contain": ["guarantee that"]}, deferred=d)
eq(r["overall"], "fail", "a real failure still dominates a deferral")
r = evaluate(None, {"must_contain_any": ["written"]}, deferred=d)
eq(r["checks"][0]["status"], "deferred", "deferral wins over no-reply")

print("\nall Layer 2 tests passed")
