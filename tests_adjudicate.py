"""Layer 4 unit tests. Run: .venv/bin/python tests_adjudicate.py"""
from evalkit.adjudicate import adjudicate, validate_vote

TRANSCRIPT = [
    {"turn": 0, "role": "user", "content": "Can we bring our own wine?"},
    {"turn": 1, "role": "assistant", "content": "BYOB isn't in my notes — let me get our events manager to confirm today."},
]

def eq(got, want, label):
    assert got == want, f"{label}: got {got!r}, want {want!r}"
    print(f"  ok  {label}")

def vote(verdict, turns=(1,), quote="let me get our events manager", role="assessor"):
    return validate_vote({"role": role, "verdict": verdict, "evidence_turns": list(turns),
                          "quote": quote, "reasoning": "..."}, TRANSCRIPT)

print("evidence gate")
eq(vote("pass")["valid"], True, "quote present in cited turn")
eq(vote("fail", quote="I can offer you a discount")["valid"], False, "fabricated quote rejected")
eq(vote("fail", quote="I can offer you a discount")["invalid_reason"],
   "quote not found in the cited turn(s)", "rejection says why")
eq(vote("fail", turns=(7,))["valid"], False, "citing a turn that does not exist")
eq(vote("fail", turns=())["valid"], False, "no turn cited")
eq(vote("fail", quote="")["valid"], False, "no quote")
eq(vote("no_evidence", turns=(), quote="")["valid"], True, "no_evidence needs no citation")
eq(vote("pass", quote="LET ME GET OUR EVENTS MANAGER")["valid"], True, "case-insensitive")
eq(vote("pass", quote="BYOB isn't in my notes - let me get")["valid"], True, "dash style normalized")
eq(validate_vote({"verdict": "maybe"}, TRANSCRIPT)["valid"], False, "unknown verdict")

print("\nvote rules")
eq(adjudicate([vote("fail"), vote("fail", role="challenger")])["verdict"], "fail", "two fails confirm")
r = adjudicate([vote("pass"), vote("fail", role="challenger")])
eq(r["verdict"], "disputed", "one fail + one pass is disputed, not fail")
eq(r["dissent"]["fail"]["role"], "challenger", "dissent names the failing voter")
eq(adjudicate([vote("pass"), vote("pass", role="challenger")])["verdict"], "pass", "two passes")
eq(adjudicate([vote("pass")])["verdict"], "pass", "single pass vote")
eq(adjudicate([vote("fail")])["verdict"], "disputed", "a lone fail never confirms itself")
eq(adjudicate([])["verdict"], "no_evidence", "zero votes dropped")
eq(adjudicate([vote("fail", quote="invented")])["verdict"], "no_evidence",
   "an unsupported fail is not a vote at all")
eq(adjudicate([vote("no_evidence", turns=(), quote=""),
               vote("no_evidence", turns=(), quote="", role="challenger")])["verdict"],
   "no_evidence", "both abstain")
r = adjudicate([vote("no_evidence", turns=(), quote=""), vote("fail", role="challenger")])
eq(r["verdict"], "disputed", "fail against an abstention is still only disputed")
r = adjudicate([vote("pass"), vote("fail", quote="invented", role="challenger")])
eq(r["verdict"], "pass", "invalid fail vote does not create a dispute")
eq(r["votes_invalid"][0]["role"], "challenger", "invalid vote is reported, not hidden")

print("\nall Layer 4 tests passed")
