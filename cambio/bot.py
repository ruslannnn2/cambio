"""Bots that play from a legitimate `View` only (no peeking at hidden cards).

A bot's knowledge is whatever the engine says it has seen. On top of that,
difficulty controls how often it forgets a card it once knew, how willing it is
to call Cambio, and how fast it reacts when jumping in.
"""
from __future__ import annotations

import random
from typing import Optional

from . import actions as A
from .actions import Pos
from .cards import Card, card_from_id
from .engine import Phase, View

# DEV KNOB: seconds the bot sleeps (time.sleep) right before each move it makes
# on its turn. 0 = no extra pause. Raise it to slow the game down.
BOT_SLEEP = 0.5

LEVELS = {
    #          forget/turn  cambio total  max unknown own  jump reaction (s)
    "easy":   dict(forget=0.12, cambio=7,  unknown_ok=2, react=(1.6, 3.2)),
    "medium": dict(forget=0.04, cambio=9,  unknown_ok=1, react=(1.1, 2.4)),
    "hard":   dict(forget=0.0,  cambio=11, unknown_ok=1, react=(0.8, 1.6)),
}


class Bot:
    def __init__(self, pid: int, level: str = "medium", rng: Optional[random.Random] = None):
        self.pid = pid
        self.cfg = LEVELS[level]
        self.rng = rng or random.Random()
        self.forgotten: set[int] = set()
        self.turns = 0

    # ------------------------------------------------------------ knowledge
    def _mem(self, v: View) -> dict[Pos, Card]:
        return {p: c for p, c in v.known.items() if c.id not in self.forgotten}

    def _pool_mean(self, v: View, mem: dict[Pos, Card]) -> float:
        """Card counting: mean value of every card not yet accounted for."""
        seen = {c.id for c in v.discard} | {c.id for c in mem.values()}
        if v.held is not None:
            seen.add(v.held.id)
        vals = [card_from_id(i).value for i in range(52) if i not in seen]
        return sum(vals) / len(vals) if vals else 6.5

    def _own(self, v: View) -> list[Pos]:
        return [(self.pid, s) for s, ok in enumerate(v.occupied[self.pid]) if ok]

    def _opp(self, v: View, swappable: bool = False) -> list[Pos]:
        out = []
        for o in range(v.n):
            if o == self.pid or (swappable and o == v.cambio_caller):
                continue
            out += [(o, s) for s, ok in enumerate(v.occupied[o]) if ok]
        return out

    # ---------------------------------------------------------------- jumps
    def wants_jump(self, v: View) -> Optional[Pos]:
        """A remembered card matching the pile top: own cards first, then any opponent's."""
        if not v.jump_open or not v.discard or self.pid == v.cambio_caller:
            return None
        top = v.discard[-1]
        hits = [pos for pos, c in self._mem(v).items()
                if c.rank == top.rank and pos[0] != v.cambio_caller and v.occupied[pos[0]][pos[1]]
                and not (pos[0] == self.pid and c.value < 0)]  # never throw away our own red king (-1)
        hits.sort(key=lambda p: p[0] != self.pid)
        return hits[0] if hits else None

    def reaction_delay(self) -> float:
        return self.rng.uniform(*self.cfg["react"])

    # --------------------------------------------------------------- choose
    def choose(self, v: View):
        return {
            Phase.DRAW: self._draw, Phase.HOLDING: self._holding,
            Phase.POWER_SELF: self._look_self, Phase.POWER_OPP: self._look_opp,
            Phase.POWER_JACK: self._jack, Phase.POWER_QUEEN: self._queen,
            Phase.QUEEN_DECIDE: self._queen_decide,
        }[v.phase](v)

    def _est(self, pos: Pos, mem, mean) -> float:
        c = mem.get(pos)
        return c.value if c is not None else mean

    def _draw(self, v: View):
        self.turns += 1
        self.forgotten &= {c.id for c in v.known.values()}
        for c in v.known.values():
            if self.rng.random() < self.cfg["forget"]:
                self.forgotten.add(c.id)
        mem = self._mem(v)
        mean = self._pool_mean(v, mem)
        own = self._own(v)
        est = [self._est(p, mem, mean) for p in own]
        unknown = sum(1 for p in own if p not in mem)
        # Be increasingly willing to end a long game.
        limit = self.cfg["cambio"] + max(0, self.turns - 10)
        if (v.cambio_caller is None and self.turns >= 3 and own
                and unknown <= self.cfg["unknown_ok"] + max(0, self.turns - 14)
                and sum(est) <= limit):
            return A.CallCambio()
        if v.discard and own and v.discard[-1].value <= max(est) - 3:
            return A.TakeDiscard()
        return A.DrawDeck()

    def _holding(self, v: View):
        mem = self._mem(v)
        mean = self._pool_mean(v, mem)
        own = self._own(v)
        h = v.held
        if not own:  # every card already jumped away
            return A.Discard()
        best = max(own, key=lambda p: self._est(p, mem, mean) - h.value)
        gain = self._est(best, mem, mean) - h.value
        if v.held_from == "discard" or gain >= 2:
            return A.Swap(best[1])
        return A.Discard()

    def _look_self(self, v: View):
        mem = self._mem(v)
        unknown = [p for p in self._own(v) if p not in mem]
        return A.LookSelf(self.rng.choice(unknown)[1]) if unknown else A.Skip()

    def _look_opp(self, v: View):
        mem = self._mem(v)
        opp = self._opp(v)
        fresh = [p for p in opp if p not in mem] or opp
        p = self.rng.choice(fresh)
        return A.LookOpp(*p)

    def _jack(self, v: View):
        mem = self._mem(v)
        mean = self._pool_mean(v, mem)
        own = [p for p in self._own(v)] if self.pid != v.cambio_caller else []
        opp = self._opp(v, swappable=True)
        if not own or not opp:
            return A.Skip()
        # Steal a card we already know is great, giving away our worst.
        great = [p for p in opp if p in mem and mem[p].value <= 2]
        worst = max(own, key=lambda p: self._est(p, mem, mean))
        if great and self._est(worst, mem, mean) >= 5:
            return A.BlindSwap(worst, min(great, key=lambda p: mem[p].value))
        # Otherwise dump a known-terrible card on a random opponent card.
        if worst in mem and mem[worst].value >= 8:
            fresh = [p for p in opp if p not in mem] or opp
            return A.BlindSwap(worst, self.rng.choice(fresh))
        return A.Skip()

    def _queen(self, v: View):
        mem = self._mem(v)
        mean = self._pool_mean(v, mem)
        own = self._own(v)
        opp = self._opp(v, swappable=True)
        if not own or not opp:
            return A.Skip()
        unknown_own = [p for p in own if p not in mem]
        mine = self.rng.choice(unknown_own) if unknown_own else max(own, key=lambda p: self._est(p, mem, mean))
        low_known = [p for p in opp if p in mem and mem[p].value <= 3]
        fresh = [p for p in opp if p not in mem]
        theirs = min(low_known, key=lambda p: mem[p].value) if low_known else self.rng.choice(fresh or opp)
        return A.QueenLook(mine[1], theirs)

    def _queen_decide(self, v: View):
        a, b = v.queen_pair
        ca, cb = v.known.get(a), v.known.get(b)
        if ca is None or cb is None:
            return A.QueenDecide(False)
        return A.QueenDecide(cb.value < ca.value)
