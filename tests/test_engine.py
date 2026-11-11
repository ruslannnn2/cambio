import pytest

from cambio import actions as A
from cambio.cards import Card, full_deck
from cambio.engine import Game, IllegalAction, Phase
from cambio.sim import play_game


def rig(g: Game, hands=None, top=None, draw=None):
    """Force specific cards: replaces everything with a consistent arrangement."""
    cards = {c.id: c for c in full_deck()}
    used = []
    if hands:
        for pid, hand in enumerate(hands):
            g.hands[pid] = list(hand)
            used += hand
    if top is not None:
        g.deck.discard = [top]
        used.append(top)
    if draw:
        used += draw
    used_ids = {c.id for c in used}
    rest = [c for c in full_deck() if c.id not in used_ids]
    g.deck.draw_pile = rest + list(reversed(draw or []))  # draw pops from the end
    for k in g.known:
        k.clear()
    g.phase, g.current = Phase.DRAW, 0
    g.known[0].update(c.id for c in g.hands[0] if c)  # not important unless asserted


def C(label):
    r = {"A": 1, "J": 11, "Q": 12, "K": 13}.get(label[:-1]) or int(label[:-1])
    return Card(r, label[-1])


def hand(*labels):
    return [C(x) for x in labels]


def test_values():
    assert C("KH").value == -1 and C("KD").value == -1
    assert C("KS").value == 13 and C("KC").value == 13
    assert C("AS").value == 1 and C("JS").value == 11 and C("QS").value == 12
    assert C("10H").value == 10


def test_deal_and_peek_memory():
    g = Game(3, seed=1)
    assert len(g.all_cards()) == 52 and len({c.id for c in g.all_cards()}) == 52
    for pid in range(3):
        v = g.view(pid)
        assert set(v.known) == {(pid, 1), (pid, 3)}  # only own bottom cards


def test_swap_from_deck_is_private_to_holder():
    g = Game(2, seed=2)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("10C"), draw=[C("AH")])
    g.apply(0, A.Ready()) if g.phase == Phase.PEEK else None
    g.apply(0, A.DrawDeck())
    g.apply(0, A.Swap(0))
    assert g.top == C("2S") and g.hands[0][0] == C("AH")
    assert (0, 0) in g.view(0).known
    assert (0, 0) not in g.view(1).known  # opponent didn't see it


def test_take_discard_is_public_and_must_swap():
    g = Game(2, seed=2)
    rig(g, [hand("9S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("AC"))
    g.apply(0, A.TakeDiscard())
    with pytest.raises(IllegalAction):
        g.apply(0, A.Discard())
    g.apply(0, A.Swap(0))
    assert (0, 0) in g.view(1).known and g.view(1).known[(0, 0)] == C("AC")


def test_red_black_king_scoring():
    g = Game(2, seed=3)
    rig(g, [hand("KH", "KD", "AS", "AC"), hand("KS", "KC", "AH", "AD")])
    assert g.scores() == [0, 28]


def test_seven_looks_at_own_card():
    g = Game(2, seed=4)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("10C"), draw=[C("7D")])
    g.apply(0, A.DrawDeck())
    g.apply(0, A.Discard())
    assert g.phase == Phase.POWER_SELF
    g.apply(0, A.LookSelf(0))
    assert g.view(0).known[(0, 0)] == C("2S")
    assert g.current == 1


def test_nine_looks_at_opponent():
    g = Game(2, seed=4)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("10C"), draw=[C("9D")])
    g.apply(0, A.DrawDeck())
    g.apply(0, A.Discard())
    assert g.phase == Phase.POWER_OPP
    with pytest.raises(IllegalAction):
        g.apply(0, A.LookOpp(0, 0))
    g.apply(0, A.LookOpp(1, 2))
    assert g.view(0).known[(1, 2)] == C("8H")
    assert (1, 2) not in g.view(1).known or g.view(1).known[(1, 2)] == C("8H")


def test_jack_blind_swap_knowledge_follows_card():
    g = Game(2, seed=5)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("10C"), draw=[C("JD")])
    g.known[1].add(C("6H").id)  # opponent knows own slot 0
    g.apply(0, A.DrawDeck())
    g.apply(0, A.Discard())
    assert g.phase == Phase.POWER_JACK
    g.apply(0, A.BlindSwap((0, 0), (1, 0)))
    assert g.hands[0][0] == C("6H") and g.hands[1][0] == C("2S")
    assert g.view(1).known[(0, 0)] == C("6H")  # opponent tracks the moved card
    assert (0, 0) not in g.view(0).known       # swapper learned nothing


def test_queen_informed_swap():
    g = Game(2, seed=5)
    rig(g, [hand("KS", "3S", "4S", "5S"), hand("AH", "7H", "8H", "9H")], top=C("10C"), draw=[C("QD")])
    g.apply(0, A.DrawDeck())
    g.apply(0, A.Discard())
    g.apply(0, A.QueenLook(0, (1, 0)))
    assert g.phase == Phase.QUEEN_DECIDE
    v = g.view(0)
    assert v.known[(0, 0)] == C("KS") and v.known[(1, 0)] == C("AH")
    g.apply(0, A.QueenDecide(True))
    assert g.hands[0][0] == C("AH") and g.hands[1][0] == C("KS")


def test_jump_in_correct_and_wrong():
    g = Game(2, seed=6)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("10C"), draw=[C("AD"), C("2D")])
    g.apply(0, A.DrawDeck())
    g.apply(0, A.Discard())  # discards AD, jump window opens
    assert g.jump_open
    # player 1 jumps with a wrong card: penalty + card revealed to all
    g.apply(1, A.JumpIn(0))
    assert len(g.hands[1]) == 5 and g.hands[1][4] is not None
    assert g.view(0).known[(1, 0)] == C("6H")
    assert g.jump_open  # still open after a failed jump
    # player 0 jumps... has no ace, wrong again; then give them one
    g.hands[0][2] = C("AS")
    g.apply(0, A.JumpIn(2))
    assert g.hands[0][2] is None and g.top == C("AS")
    assert not g.jump_open
    with pytest.raises(IllegalAction):
        g.apply(1, A.JumpIn(1))  # too late, first jump wins


def test_jump_in_on_opponent_card():
    g = Game(2, seed=6)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("10C"), draw=[C("AD"), C("2D"), C("3D")])
    g.apply(0, A.DrawDeck())
    g.apply(0, A.Discard())  # discards AD
    # wrong guess on an opponent's card: the jumper gets the penalty, the card is revealed
    g.apply(0, A.JumpIn(0, 1))
    assert len(g.hands[0]) == 5 and len(g.hands[1]) == 4
    assert g.top == C("6H")                          # their card went to the pile...
    assert g.hands[1][0] is not None and g.hands[1][0] != C("6H")  # ...and was replaced
    assert (1, 0) not in g.view(0).known and (1, 0) not in g.view(1).known  # unseen by all
    assert len({c.id for c in g.all_cards()}) == 52
    # right guess: opponent's card goes to the pile and the opponent gets the penalty
    g.deck.discard[-1] = C("AH")
    g.hands[1][2] = C("AS")
    g.apply(0, A.JumpIn(2, 1))
    assert g.top == C("AS") and g.hands[1][2] is not None and g.hands[1][2] != C("AS")
    assert len(g.hands[1]) == 5 and all(c is not None for c in g.hands[1])  # replacement + penalty
    assert len(g.hands[0]) == 5 and not g.jump_open


def test_queen_swap_is_cancelled_if_a_jump_replaced_a_looked_at_card():
    g = Game(2, seed=6)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("10C"), draw=[C("QD"), C("2D"), C("3D"), C("4D")])
    g.apply(0, A.DrawDeck())
    g.apply(0, A.Discard())                  # discards the queen
    g.apply(0, A.QueenLook(0, (1, 1)))
    g.hands[1][1] = C("QH")                  # opponent's card gets slammed on the queen
    g.apply(0, A.JumpIn(1, 1))
    assert g.hands[1][1] is not None and g.hands[1][1] != C("QH")
    before = (g.hands[0][0], g.hands[1][1])
    g.apply(0, A.QueenDecide(True))          # the card they saw is gone: no swap
    assert (g.hands[0][0], g.hands[1][1]) == before


def test_cambio_can_be_called_right_after_your_turn_until_next_player_acts():
    g = Game(3, seed=7)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H"), hand("AH", "AD", "2D", "3D")],
        top=C("10C"), draw=[C("4D"), C("5D"), C("6D"), C("7D")])
    g.current = 0
    g.apply(0, A.DrawDeck())
    g.apply(0, A.Swap(0))                    # turn over, player 1 is up but hasn't acted
    assert g.current == 1 and g.can_call_cambio(0) and not g.can_call_cambio(2)
    g.apply(0, A.CallCambio())
    assert g.cambio_caller == 0 and g.current == 1
    g.apply(1, A.DrawDeck())                 # player 1 still gets their last turn
    g.apply(1, A.Swap(0))
    g.apply(2, A.DrawDeck())
    g.apply(2, A.Swap(0))
    assert g.phase == Phase.GAME_OVER

    g = Game(3, seed=7)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H"), hand("AH", "AD", "2D", "3D")],
        top=C("10C"), draw=[C("4D"), C("5D"), C("6D"), C("7D")])
    g.current = 0
    g.apply(0, A.DrawDeck())
    g.apply(0, A.Swap(0))
    g.apply(1, A.DrawDeck())                 # next player started: window closed
    assert not g.can_call_cambio(0)
    with pytest.raises(IllegalAction):
        g.apply(0, A.CallCambio())


def test_cambio_gives_everyone_else_one_last_turn():
    g = Game(3, seed=7)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H"), hand("AH", "AD", "2D", "3D")], top=C("10C"))
    g.apply(0, A.CallCambio())
    assert g.current == 1 and g.phase == Phase.DRAW
    g.apply(1, A.DrawDeck())
    g.apply(1, A.Swap(0))
    assert g.current == 2
    g.apply(2, A.DrawDeck())
    g.apply(2, A.Swap(0))
    assert g.phase == Phase.GAME_OVER
    with pytest.raises(IllegalAction):
        g.apply(0, A.CallCambio())


def test_caller_cards_locked_from_blind_swap():
    g = Game(2, seed=7)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("10C"), draw=[C("JD")])
    g.current = 1
    g.cambio_caller = 0
    g.apply(1, A.DrawDeck())
    g.apply(1, A.Discard())
    # only player 1's cards are swappable and a Jack can't swap within one hand: no power,
    # so the turn just ends (and with it the game, since 0 called Cambio)
    assert g.phase == Phase.GAME_OVER


def test_blind_swap_cannot_swap_two_cards_of_the_same_hand():
    g = Game(2, seed=7)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("10C"), draw=[C("JD")])
    g.current = 1
    g.apply(1, A.DrawDeck())
    g.apply(1, A.Discard())
    assert g.phase == Phase.POWER_JACK
    with pytest.raises(IllegalAction):
        g.apply(1, A.BlindSwap((1, 0), (1, 1)))
    g.apply(1, A.BlindSwap((1, 0), (0, 1)))


def test_deck_reshuffles_and_forgets():
    g = Game(2, seed=8)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("6H", "7H", "8H", "9H")], top=C("10C"))
    g.deck.discard = [c for c in g.deck.draw_pile] + [C("10C")]
    g.deck.draw_pile = []
    n_before = len(g.deck.discard)
    g.apply(0, A.DrawDeck())
    assert g.held is not None and len(g.deck.draw_pile) == n_before - 2
    assert g.deck.discard == [C("10C")]
    assert len({c.id for c in g.all_cards()}) == 52


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_bot_games_finish_and_conserve_cards(n):
    for seed in range(40):
        g = play_game(n, seed, level=["easy", "medium", "hard"][seed % 3])
        cards = g.all_cards()
        assert len(cards) == 52 and len({c.id for c in cards}) == 52
        assert g.phase == Phase.GAME_OVER


def test_bot_never_jumps_in_with_its_own_red_king():
    from cambio.bot import Bot
    g = Game(2, seed=6)
    rig(g, [hand("2S", "3S", "4S", "5S"), hand("KH", "7H", "8H", "9H")], top=C("KS"), draw=[C("AD")])
    g.jump_open = True
    g.known[1].update(c.id for c in g.hands[1])      # the bot remembers all of its own cards
    assert Bot(1, "hard").wants_jump(g.view(1)) is None
    g.known[1].update(c.id for c in g.hands[0])
    g.hands[0][0] = C("KC")                          # but a black king of ours is fair game
    g.known[1].add(C("KC").id)
    assert Bot(1, "hard").wants_jump(g.view(1)) == (0, 0)
