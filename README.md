# Cambio

Cambio card game vs 1-4 bots. (definitely not stolen balatro ui)

## Run

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

Options: `--bots 1-4`, `--difficulty easy|medium|hard`, `--start` (skip the menu).

## Controls

- Left click: deck, discard pile, cards
- Jump in (your cards or opponents'): right click, shift-click, or hover + space
- Esc: pause (press again to resume, or go back to the menu)
- F11: fullscreen

## Rules

- 4 cards each, peek at your bottom two
- A=1, J=11, Q=12, red K=-1, black K=13
- 7/8 look at yours, 9/10 look at theirs, J blind swap, Q look at two then swap
- Jump in if a card matches the top of the discard pile. Wrong guess = penalty card
- You can also jump in with an opponent's card: if you're right they take a penalty card, if wrong you do (and bots can do it to you)
- Call Cambio to end the game after everyone gets one more turn. Lowest score wins

## Tweaking
- `cambio/names.py`: `BOT_NAMES`, the pool bots are named from
- `cambio/bot.py`: `BOT_SLEEP`, an extra pause before each bot move
- `cambio/ui/table.py`: `BOT_ANIM_SPEED`, card animation speed during bot turns
