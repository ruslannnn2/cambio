"""The game table scene: layout, input, bot pacing, log."""
from __future__ import annotations

import math
import random
import time

import pygame

from .. import actions as A
from ..names import BOT_NAMES
from .. import bot as bot_module
from ..bot import Bot
from ..cards import SUITS, Card, card_from_id
from ..engine import Game, IllegalAction, Phase
from .fx import LOGICAL_H, LOGICAL_W, CardSprite
from .rules import RulesPanel
from .sprites import (BACK_BASE, BLACK, CARD_H, CARD_W, CREAM, GOLD, INK, RED,
                      WHITE, draw_suit, draw_text, suit_color, text_width)

DECK_POS = (190, 138)
DISCARD_POS = (235, 138)
HOLD_POS = (300, 138)
HUMAN_CENTER = (240, 219)
BOT_SEATS = {
    1: [(240, 58)],
    2: [(150, 58), (330, 58)],
    3: [(52, 128), (240, 58), (428, 128)],
    4: [(52, 128), (160, 58), (320, 58), (428, 128)],
}
GAP = 3
# DEV KNOB: card animation speed while a bot is playing (1.0 = same as your turn, lower = slower,
# easier to follow). Bots also wait for animations to finish, so this stretches their turns too.
BOT_ANIM_SPEED = 0.65
SHOW_TIME = 2.4
GOOD = (120, 230, 150)
PANEL = (14, 24, 26)


class Button:
    def __init__(self, key, label, rect, color=CREAM, text=INK):
        self.key, self.label, self.rect, self.color, self.text = key, label, pygame.Rect(rect), color, text

    def draw(self, surf, hover):
        r = self.rect
        pygame.draw.rect(surf, INK, r.inflate(2, 2), border_radius=3)
        shade = tuple(min(255, c + 25) for c in self.color) if hover else self.color
        pygame.draw.rect(surf, shade, r, border_radius=3)
        pygame.draw.rect(surf, tuple(c * 3 // 5 for c in self.color), (r.x + 1, r.bottom - 3, r.w - 2, 2))
        draw_text(surf, self.label, (r.centerx, r.centery - 2), self.text, 1, align="center")


class GameScene:
    def __init__(self, app, n_bots: int, level: str, seed=None):
        self.app = app
        self.n_bots, self.level, self.seed = n_bots, level, seed
        self.n = n_bots + 1
        self.g = Game(self.n, seed)
        self.rng = random.Random(seed)
        self.bots = {p: Bot(p, level, self.rng) for p in range(1, self.n)}
        self.names = {0: "YOU", **dict(zip(self.bots, self.rng.sample(BOT_NAMES, len(self.bots))))}
        self.sprites: dict[int, CardSprite] = {}
        self.draw_ids: list[int] = []
        self.reveal: dict[int, float] = {}
        self.flash: dict[tuple, float] = {}
        self.event_idx = 0
        self.log: list[tuple[str, tuple]] = []
        self.toasts: list[list] = []
        self.banner: tuple[str, float] | None = None
        self.bot_timer = 1.6
        self.jump_timers: dict[int, float] = {}
        self.sel: list[tuple[int, int]] = []
        self.shake = 0.0
        self.t = 0.0
        self.paused = False
        self.rules = None  # a RulesPanel while the rules page is open over the pause menu
        self.last_current = -1
        self.mouse = (0, 0)
        self.hover = None
        self.hover_any = None
        self.float_slot = None
        self._deal()

    # ------------------------------------------------------------- layout
    def seat_center(self, pid):
        return HUMAN_CENTER if pid == 0 else BOT_SEATS[self.n_bots][pid - 1]

    def name(self, pid: int) -> str:
        return self.names.get(pid, "TABLE").upper()  # pid -1 = events with no player (reshuffle, game over)

    def poss(self, pid: int) -> str:
        return "YOUR" if pid == 0 else f"{self.name(pid)}'S"

    def slot_pos(self, owner, slot):
        cx, cy = self.seat_center(owner)
        cols = max(2, math.ceil(len(self.g.hands[owner]) / 2))
        w = cols * (CARD_W + GAP) - GAP
        col, row = slot // 2, slot % 2
        x = cx - w / 2 + col * (CARD_W + GAP) + CARD_W / 2
        y = cy - (2 * CARD_H + GAP) / 2 + row * (CARD_H + GAP) + CARD_H / 2
        return x, y

    def _deal(self):
        k = 0
        for slot in range(4):
            for o in range(self.n):
                c = self.g.hands[o][slot]
                sp = self.sprite(c)
                sp.delay = 0.35 + 0.07 * k
                k += 1
        for slot in (1, 3):  # starting peek stays face up until READY
            self.reveal[self.g.hands[0][slot].id] = 1e9

    def sprite(self, c: Card) -> CardSprite:
        sp = self.sprites.get(c.id)
        if sp is None:
            sp = self.sprites[c.id] = CardSprite(c, DECK_POS)
        return sp

    # --------------------------------------------------------- visibility
    def face_up(self, c: Card) -> bool:
        g = self.g
        if g.phase == Phase.GAME_OVER or self.reveal.get(c.id, 0) > 0:
            return True
        if g.held is c and (g.held_from == "discard" or g.current == 0):
            return True
        return False

    # ---------------------------------------------------------- targets
    def refresh_targets(self):
        g = self.g
        placed: set[int] = set()
        shown: list[int] = []

        def put(c, pos, z, rot=0.0, show=True, face=None):
            sp = self.sprite(c)
            sp.set_target(pos[0], pos[1], z, rot)
            sp.face_target = 1.0 if (self.face_up(c) if face is None else face) else 0.0
            placed.add(c.id)
            if show:
                shown.append(c.id)

        for o, hand in enumerate(g.hands):
            for s, c in enumerate(hand):
                if c is not None:
                    put(c, self.slot_pos(o, s), 10 + s)
        if g.held is not None:
            put(g.held, HOLD_POS, 40)
        disc = g.deck.discard
        for i, c in enumerate(disc):
            depth = len(disc) - 1 - i
            if depth < 3:
                j = (c.id * 37) % 5 - 2, (c.id * 53) % 5 - 2
                put(c, (DISCARD_POS[0] + j[0], DISCARD_POS[1] + j[1]), 1 + i, ((c.id * 29) % 9 - 4) * 0.8, face=True)
            else:
                put(c, DISCARD_POS, 0, show=False, face=True)
        for cid, sp in self.sprites.items():
            if cid not in placed:  # back in the draw pile
                sp.x, sp.y = sp.tx, sp.ty = DECK_POS
                sp.face = sp.face_target = 0.0
        self.draw_ids = shown

    # ---------------------------------------------------- what is clickable
    def interactive(self) -> set:
        g = self.g
        if g.phase in (Phase.PEEK, Phase.GAME_OVER) or g.current != 0:
            return set()
        own = {(0, s) for s, c in enumerate(g.hands[0]) if c is not None}
        opp = {(o, s) for o in range(1, self.n) for s, c in enumerate(g.hands[o]) if c is not None}
        ph = g.phase
        if ph in (Phase.HOLDING, Phase.POWER_SELF):
            return own
        if ph == Phase.POWER_OPP:
            return opp
        if ph == Phase.POWER_JACK:
            return {p for p in own | opp if p[0] != g.cambio_caller}
        if ph == Phase.POWER_QUEEN:
            return own | {p for p in opp if p[0] != g.cambio_caller}
        return set()

    def buttons(self):
        g = self.g
        x, w, h = 10, 92, 17
        out = []
        if g.phase == Phase.GAME_OVER:
            return [Button("again", "PLAY AGAIN", (x, 196, w, h), GOLD),
                    Button("menu", "MENU", (x, 218, w, h))]
        if g.phase == Phase.PEEK:
            return [Button("ready", "READY!", (x, 196, w, h), GOLD)]
        if g.current != 0:  # just finished your turn and the next bot hasn't started yet
            if g.can_call_cambio(0):
                out.append(Button("cambio", "CALL CAMBIO", (x, 218, w, h), (240, 110, 100)))
            return out
        if g.phase == Phase.DRAW and g.cambio_caller is None:
            out.append(Button("cambio", "CALL CAMBIO", (x, 218, w, h), (240, 110, 100)))
        elif g.phase in (Phase.POWER_SELF, Phase.POWER_OPP, Phase.POWER_JACK, Phase.POWER_QUEEN):
            out.append(Button("skip", "SKIP POWER", (x, 196, w, h)))
        elif g.phase == Phase.QUEEN_DECIDE:
            out += [Button("swap", "SWAP THEM", (x, 196, w, h), GOLD), Button("keep", "KEEP", (x, 218, w, h))]
        return out

    # ------------------------------------------------------------- input
    def _rect(self, pos):
        return pygame.Rect(0, 0, CARD_W, CARD_H).move(pos[0] - CARD_W / 2, pos[1] - CARD_H / 2)

    def _slot_at(self, pt, allowed=None):
        best = None
        for o, hand in enumerate(self.g.hands):
            for s, c in enumerate(hand):
                if c is None or (allowed is not None and (o, s) not in allowed):
                    continue
                if self._rect(self.slot_pos(o, s)).collidepoint(pt):
                    best = (o, s)  # later slots draw on top
        return best

    def submit(self, action, pid=0):
        try:
            self.g.apply(pid, action)
        except IllegalAction as e:
            if pid == 0:  # a bot losing a race for the pile isn't the player's business
                msg = str(e).upper()
                self.toast(msg if len(msg) < 28 else "NOT ALLOWED", RED, self.mouse)

    def all_slots(self):
        return {(o, s) for o, h in enumerate(self.g.hands) for s, c in enumerate(h) if c is not None}

    def try_jump(self, pos, pid=0):
        owner, slot = pos
        self.submit(A.JumpIn(slot, None if owner == pid else owner), pid)

    def pause_buttons(self):
        return [Button("resume", "RESUME", (190, 116, 100, 18), GOLD),
                Button("rules", "RULES", (190, 140, 100, 18)),
                Button("menu", "MAIN MENU", (190, 164, 100, 18))]

    def on_mouse(self, pos, button, shift=False):
        g = self.g
        if self.paused:
            if self.rules:
                if self.rules.on_mouse(pos, button):
                    self.rules = None
            elif button == 1:
                for b in self.pause_buttons():
                    if b.rect.collidepoint(pos):
                        if b.key == "resume":
                            self.paused = False
                        elif b.key == "rules":
                            self.rules = RulesPanel()
                        else:
                            self.app.go_menu()
            return
        for b in self.buttons():
            if b.rect.collidepoint(pos) and button == 1:
                return self.on_button(b.key)
        if g.phase == Phase.GAME_OVER:
            return
        if button == 3 or (button == 1 and shift):
            hit = self._slot_at(pos, self.all_slots())
            if hit is not None:
                self.try_jump(hit)
            return
        if button != 1 or g.phase == Phase.PEEK or g.current != 0:
            return
        ph = g.phase
        on_deck = self._rect(DECK_POS).collidepoint(pos)
        on_disc = self._rect(DISCARD_POS).collidepoint(pos)
        slot = self._slot_at(pos, self.interactive())
        if ph == Phase.DRAW:
            if on_deck:
                self.submit(A.DrawDeck())
            elif on_disc and g.top is not None:
                self.submit(A.TakeDiscard())
        elif ph == Phase.HOLDING:
            if slot is not None:
                self.submit(A.Swap(slot[1]))
            elif on_disc and g.held_from == "deck":
                self.submit(A.Discard())
        elif ph == Phase.POWER_SELF and slot:
            self.submit(A.LookSelf(slot[1]))
        elif ph == Phase.POWER_OPP and slot:
            self.submit(A.LookOpp(*slot))
        elif ph == Phase.POWER_JACK and slot:
            if slot in self.sel:
                self.sel.remove(slot)
            else:  # the two cards must come from different hands: picking from the same hand replaces
                self.sel = [p for p in self.sel if p[0] != slot[0]] + [slot]
            if len(self.sel) == 2:
                a, b = self.sel
                self.sel = []
                self.submit(A.BlindSwap(a, b))
        elif ph == Phase.POWER_QUEEN and slot:
            self.sel = [p for p in self.sel if (p[0] == 0) != (slot[0] == 0)]  # one own, one opp
            if slot not in self.sel:
                self.sel.append(slot)
            if len(self.sel) == 2:
                own = next(p for p in self.sel if p[0] == 0)
                opp = next(p for p in self.sel if p[0] != 0)
                self.sel = []
                self.submit(A.QueenLook(own[1], opp))

    def on_button(self, key):
        g = self.g
        if key == "ready":
            self.submit(A.Ready())
            self.reveal.clear()
        elif key == "cambio":
            self.submit(A.CallCambio())
        elif key == "skip":
            self.sel = []
            self.submit(A.Skip())
        elif key == "swap":
            self.submit(A.QueenDecide(True))
        elif key == "keep":
            self.submit(A.QueenDecide(False))
        elif key == "again":
            self.app.start_game(self.n_bots, self.level)
        elif key == "menu":
            self.app.go_menu()

    def on_key(self, key):
        if self.rules:
            if self.rules.on_key(key):
                self.rules = None
        elif key == pygame.K_ESCAPE:
            self.paused = not self.paused
            self.sel = []
        elif self.paused:
            return
        elif key == pygame.K_SPACE and self.hover_any is not None:
            self.try_jump(self.hover_any)

    # ------------------------------------------------------------ events
    def toast(self, text, color=WHITE, pos=(240, 150)):
        self.toasts.append([text, color, float(pos[0]), float(pos[1]), 1.1])

    def say(self, text, who=-1):
        self.log.append((text, GOLD if who == 0 else WHITE))
        self.log = self.log[-14:]

    def process_events(self):
        g = self.g
        while self.event_idx < len(g.events):
            ev = g.events[self.event_idx]
            self.event_idx += 1
            k, d, p = ev.kind, ev.data, ev.pid
            n = self.name(p)
            if k == "draw":
                self.say(f"{n} DREW A CARD", p)
            elif k == "take_discard":
                self.say(f"{n} TOOK {d['card']} FROM PILE", p)
            elif k == "discard":
                verb = "SWAPPED, DISCARDING" if d["via"] == "swap" else "DISCARDED"
                self.say(f"{n} {verb} {d['card']}", p)
                for bp, bot in self.bots.items():
                    if bot.wants_jump(g.view(bp)) is not None:
                        self.jump_timers[bp] = bot.reaction_delay()
            elif k == "look":
                own = d["owner"] == p
                if p == 0:
                    self.reveal[d["card"].id] = SHOW_TIME
                    self.say(f"YOU SAW {d['card']} ({'YOUR' if own else self.poss(d['owner'])} CARD)", 0)
                else:
                    self.say(f"{n} PEEKED AT {'THEIR OWN' if own else self.poss(d['owner'])} CARD", p)
                self.flash[(d["owner"], d["slot"])] = 1.0
            elif k == "blind_swap":
                self.say(f"{n} BLIND-SWAPPED {self.poss(d['a'][0])} AND {self.poss(d['b'][0])} CARDS", p)
                self.flash[d["a"]] = self.flash[d["b"]] = 1.0
            elif k == "queen_look":
                if p == 0:
                    for c in d["cards"]:
                        self.reveal[c.id] = 1e9
                    self.say(f"YOU SAW {d['cards'][0]} AND {d['cards'][1]}", 0)
                else:
                    self.say(f"{n} LOOKED AT TWO CARDS", p)
                self.flash[d["own"]] = self.flash[d["opp"]] = 1.0
            elif k in ("queen_swap", "queen_keep"):
                for cid in list(self.reveal):
                    if self.reveal[cid] > 1e8:
                        self.reveal[cid] = 0.7
                if k == "queen_swap":
                    self.say(f"{n} SWAPPED THE TWO CARDS", p)
                    self.flash[d["a"]] = self.flash[d["b"]] = 1.0
                else:
                    self.say(f"{n} KEPT THEM IN PLACE", p)
            elif k == "skip":
                self.say(f"{n} SKIPPED THE POWER", p)
            elif k == "jump_ok":
                o = d["owner"]
                if o == p:
                    self.say(f"{n} JUMPED IN WITH {d['card']}!", p)
                else:
                    self.say(f"{n} JUMPED IN WITH {self.poss(o)} {d['card']}! {self.name(o)} +2 CARDS", p)
                self.jump_timers.clear()
                self.toast("JUMP-IN!", GOOD, self.slot_pos(o, d["slot"]) if o < self.n else (240, 150))
            elif k == "jump_fail":
                o = d["owner"]
                whose = "" if o == p else f"{self.poss(o)} "
                self.say(f"{n} MISJUMPED {whose}{d['card']}! +1 CARD", p)
                if not d["replaced"]:
                    self.reveal[d["card"].id] = 2.6
                self.shake = 0.45 if p == 0 else 0.25
                self.toast("WRONG!", RED, self.slot_pos(o, d["slot"]))
                if d["replaced"]:  # the wrong card is the new top of the pile: bots may react to it
                    for bp, bot in self.bots.items():
                        if bot.wants_jump(g.view(bp)) is not None:
                            self.jump_timers.setdefault(bp, bot.reaction_delay())
            elif k == "cambio":
                self.say(f"{n} CALLED CAMBIO!", p)
                self.banner = (f"{n} CALLED CAMBIO!" if p else "YOU CALLED CAMBIO!", 2.0)
            elif k == "reshuffle":
                self.say("DISCARD PILE RESHUFFLED")
                self.toast("RESHUFFLE", WHITE)
            elif k == "game_over":
                self.say("GAME OVER - ALL CARDS REVEALED")
                self.reveal.clear()

    # ------------------------------------------------------------ update
    def update(self, dt, mouse):
        g = self.g
        self.mouse = mouse
        if self.paused:
            return
        self.t += dt
        self.process_events()
        self.refresh_targets()

        inter = self.interactive()
        self.hover = self._slot_at(mouse, inter) if inter else None
        # any card can be jumped on, so any card floats under the cursor (not while peeking / game over)
        live = g.phase not in (Phase.PEEK, Phase.GAME_OVER)
        self.hover_any = self._slot_at(mouse, self.all_slots()) if live else None
        self.float_slot = self.hover or self.hover_any
        for o, hand in enumerate(g.hands):
            for s, c in enumerate(hand):
                if c is None:
                    continue
                sp = self.sprites[c.id]
                pos = (o, s)
                sp.lift_target = 7 if pos == self.float_slot else (4 if pos in self.sel else 0)
                sp.glow = GOLD if pos in self.sel else (WHITE if self.flash.get(pos, 0) > 0 else None)
        anim = 1.0 if g.current == 0 or g.phase == Phase.GAME_OVER else BOT_ANIM_SPEED
        for sp in self.sprites.values():
            sp.speed = anim
            sp.update(dt)
        for d in (self.reveal, self.flash):
            for k in list(d):
                d[k] -= dt
                if d[k] <= 0:
                    del d[k]
        for tt in self.toasts:
            tt[3] -= 14 * dt
            tt[4] -= dt
        self.toasts = [tt for tt in self.toasts if tt[4] > 0]
        self.shake = max(0.0, self.shake - dt)
        if self.banner:
            self.banner = (self.banner[0], self.banner[1] - dt)
            if self.banner[1] <= 0:
                self.banner = None
        self.update_bots(dt)

    def busy(self):
        return any(sp.moving for sp in self.sprites.values())

    def update_bots(self, dt):
        g = self.g
        if g.phase in (Phase.PEEK, Phase.GAME_OVER):
            return
        for pid in list(self.jump_timers):
            self.jump_timers[pid] -= dt
            if self.jump_timers[pid] <= 0:
                del self.jump_timers[pid]
                pos = self.bots[pid].wants_jump(g.view(pid)) if g.jump_open else None
                if pos is not None:
                    self.try_jump(pos, pid)
        if g.current != self.last_current:
            self.last_current = g.current
            self.bot_timer = 0.9
        if g.current == 0 or g.phase == Phase.GAME_OVER:
            return
        if self.busy():
            return
        self.bot_timer -= dt
        if self.bot_timer <= 0:
            bot = self.bots[g.current]
            time.sleep(bot_module.BOT_SLEEP)
            self.submit(bot.choose(g.view(g.current)), g.current)
            self.bot_timer = self.rng.uniform(0.6, 1.0)

    # -------------------------------------------------------------- draw
    def prompt(self):
        g = self.g
        if g.phase == Phase.PEEK:
            return "MEMORIZE YOUR BOTTOM TWO CARDS, THEN CLICK READY"
        if g.phase == Phase.GAME_OVER:
            return ""
        if g.current == 0:
            ph = g.phase
            if ph == Phase.DRAW:
                return ("LAST TURN: DRAW OR TAKE THE DISCARD" if g.cambio_caller is not None
                        else "YOUR TURN: DRAW A CARD OR TAKE THE DISCARD")
            if ph == Phase.HOLDING:
                return ("CLICK A CARD TO SWAP, OR THE PILE TO DISCARD" if g.held_from == "deck"
                        else "CLICK ONE OF YOUR CARDS TO SWAP IT IN")
            return {
                Phase.POWER_SELF: "7/8: LOOK AT ONE OF YOUR CARDS",
                Phase.POWER_OPP: "9/10: LOOK AT AN OPPONENT'S CARD",
                Phase.POWER_JACK: f"JACK: PICK TWO CARDS TO BLIND-SWAP ({len(self.sel)}/2)",
                Phase.POWER_QUEEN: "QUEEN: PICK ONE OF YOURS AND ONE OF THEIRS",
                Phase.QUEEN_DECIDE: "SWAP THE TWO CARDS YOU JUST SAW?",
            }[ph]
        dots = "." * (int(self.t * 3) % 4)
        who = self.name(g.current)
        if g.phase == Phase.HOLDING:
            return f"{who} IS HOLDING A CARD{dots}"
        if g.phase == Phase.DRAW:
            return f"{who} IS THINKING{dots}"
        return f"{who} IS USING A POWER{dots}"

    def draw_piles(self, surf, atlas):
        g = self.g
        n = len(g.deck.draw_pile)
        if n:
            for i in range(min(3, 1 + n // 12), 0, -1):
                r = atlas.back.get_rect(center=(DECK_POS[0] - i + 1, DECK_POS[1] - i + 1))
                surf.blit(atlas.shadow, r.move(2, 3))
                surf.blit(atlas.back, r)
            can = g.phase == Phase.DRAW and g.current == 0
            if can and self._rect(DECK_POS).collidepoint(self.mouse):
                pygame.draw.rect(surf, GOLD, self._rect(DECK_POS).inflate(4, 4), 1, border_radius=4)
        else:
            pygame.draw.rect(surf, (90, 130, 110), self._rect(DECK_POS), 1, border_radius=4)
        draw_text(surf, "DECK", (DECK_POS[0], 108), WHITE, 1, INK, "center")
        if not g.deck.discard:
            pygame.draw.rect(surf, (90, 130, 110), self._rect(DISCARD_POS), 1, border_radius=4)
        draw_text(surf, "DISCARD", (DISCARD_POS[0] + 2, 108), WHITE, 1, INK, "center")
        if g.jump_open and g.phase not in (Phase.PEEK, Phase.GAME_OVER):
            draw_text(surf, "JUMP!", (DISCARD_POS[0], 166), GOLD, 1, INK, "center")

    def draw_turn_glow(self, surf, cx, cy, w):
        """A pulsing gold frame behind the active player's whole hand."""
        pulse = 0.5 + 0.5 * math.sin(self.t * 5)
        r = pygame.Rect(0, 0, int(w + 9), int(2 * CARD_H + GAP + 9))
        r.center = (int(cx), int(cy))
        glow = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(glow, (*GOLD, int(34 + 30 * pulse)), glow.get_rect(), border_radius=7)
        pygame.draw.rect(glow, (*GOLD, int(150 + 100 * pulse)), glow.get_rect(), 2, border_radius=7)
        surf.blit(glow, r)

    def draw_seats(self, surf):
        g = self.g
        over = g.phase == Phase.GAME_OVER
        scores = g.scores() if over else None
        winners = g.winners() if over else []
        for pid in range(self.n):
            cx, cy = self.seat_center(pid)
            cols = max(2, math.ceil(len(g.hands[pid]) / 2))
            w = cols * (CARD_W + GAP) - GAP
            label = self.name(pid)
            if over:
                label += f" {scores[pid]}"
            active = g.current == pid and not over and g.phase != Phase.PEEK
            won = over and pid in winners
            col = INK if active else (GOLD if won else (175, 195, 188))
            if pid == 0:
                x, y = cx - w / 2 - 7, cy - 3
                lx, ly, align = x, y, "right"
            else:
                lx, ly, align = cx, cy - CARD_H - GAP / 2 - 8 - (2 if over else 0), "center"
            scale = 1 + over
            if active:
                ly = max(ly, 4)  # keep the name tab on screen for the seat at the top edge
                self.draw_turn_glow(surf, cx, cy, w)
                tw = text_width(label, scale)
                px = lx - tw if align == "right" else lx - tw // 2
                pill = pygame.Rect(int(px) - 4, int(ly) - 3, tw + 8, 5 * scale + 6)
                pygame.draw.rect(surf, INK, pill.inflate(2, 2), border_radius=3)
                pygame.draw.rect(surf, GOLD, pill, border_radius=3)
            draw_text(surf, label, (lx, ly), col, scale, None if active else INK, align)
            if active and ly >= 12:  # (the top seat has no room for the arrow)
                bob = int(math.sin(self.t * 6) * 1.5)
                tx = lx - text_width(label) / 2 if align == "right" else lx
                ty = ly - 10 + bob
                pygame.draw.polygon(surf, INK, [(tx - 5, ty - 1), (tx + 5, ty - 1), (tx, ty + 6)])
                pygame.draw.polygon(surf, GOLD, [(tx - 4, ty), (tx + 4, ty), (tx, ty + 5)])
        if g.cambio_caller is not None and not over:
            draw_text(surf, f"{self.name(g.cambio_caller)} CALLED CAMBIO", (6, 6), GOLD, 1, INK)

    def draw_log(self, surf):
        x0, y0, w, h = 292, 184, 184, 82
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (*PANEL, 150), (0, 0, w, h), border_radius=4)
        surf.blit(panel, (x0, y0))
        lines = self.log[-11:]
        for i, (text, color) in enumerate(lines):
            c = color if i == len(lines) - 1 else tuple(int(v * 0.72) for v in color)
            draw_text(surf, text[:44], (x0 + 4, y0 + 4 + i * 7), c, 1)

    def draw(self, surf, atlas, felt):
        g = self.g
        world = pygame.Surface((LOGICAL_W, LOGICAL_H))
        felt.draw(world)
        self.draw_seats(world)
        self.draw_piles(world, atlas)
        order = sorted((self.sprites[i] for i in self.draw_ids), key=lambda s: (s.moving, s.tz))
        for sp in order:
            fs = self.float_slot
            hov = (sp.card is not None and fs is not None
                   and g.hands[fs[0]][fs[1]] is sp.card)
            sp.draw(world, atlas, self.t, self.mouse, hov, idle=False)
        if g.held is not None:
            who = self.name(g.current)
            draw_text(world, f"{who} HOLD{'' if g.current == 0 else 'S'}", (HOLD_POS[0], 108), WHITE, 1, INK, "center")
            if g.held_from == "discard":
                draw_text(world, "FROM PILE", (HOLD_POS[0], 166), (180, 220, 200), 1, INK, "center")
        pr = self.prompt()
        if pr:
            draw_text(world, pr, (240, 163), WHITE, 1, INK, "center")
        self.draw_log(world)
        mp = self.mouse
        for b in self.buttons():
            b.draw(world, b.rect.collidepoint(mp))
        if g.phase != Phase.GAME_OVER:
            draw_text(world, "JUMP IN (ANY CARD): RIGHT-", (8, 244), (170, 200, 190), 1, INK)
            draw_text(world, "CLICK, SHIFT-CLICK OR SPACE", (8, 251), (170, 200, 190), 1, INK)
            draw_text(world, "ESC: PAUSE", (8, 258), (170, 200, 190), 1, INK)
        for text, color, x, y, life in self.toasts:
            draw_text(world, text, (x, y - 8), color, 2, INK, "center")
        if self.banner:
            text, life = self.banner
            sc = 3 if text_width(text, 3) < 440 else 2
            draw_text(world, text, (240, 128), GOLD, sc, INK, "center")
        if g.phase == Phase.GAME_OVER:
            self.draw_result(world)
        if self.paused:
            self.draw_pause(world)
        ox = oy = 0
        if self.shake > 0:
            a = self.shake * 14
            ox, oy = random.uniform(-a, a), random.uniform(-a, a)
        surf.blit(world, (int(ox), int(oy)))

    def draw_pause(self, surf):
        dim = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        dim.fill((6, 12, 14, 190))
        surf.blit(dim, (0, 0))
        pygame.draw.rect(surf, PANEL, (170, 72, 140, 134), border_radius=5)
        pygame.draw.rect(surf, GOLD, (170, 72, 140, 134), 1, border_radius=5)
        draw_text(surf, "PAUSED", (240, 84), GOLD, 3, INK, "center")
        for b in self.pause_buttons():
            b.draw(surf, b.rect.collidepoint(self.mouse))
        draw_text(surf, "ESC TO RESUME", (240, 191), (150, 180, 170), 1, None, "center")
        if self.rules:
            self.rules.draw(surf, self.mouse)

    def draw_result(self, surf):
        g = self.g
        w = g.winners()
        if w == [0]:
            text, col = "YOU WIN!", GOLD
        elif 0 in w:
            text, col = "YOU TIE!", GOLD
        elif len(w) == 1:
            text, col = f"{self.name(w[0]).upper()} WINS", RED
        else:
            text, col = "BOTS TIE", RED
        pygame.draw.rect(surf, PANEL, (130, 118, 220, 30), border_radius=4)
        pygame.draw.rect(surf, col, (130, 118, 220, 30), 1, border_radius=4)
        draw_text(surf, text, (240, 125), col, 3, INK, "center")
