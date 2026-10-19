from __future__ import annotations

import json
import random
from pathlib import Path

from ..action import Action
from ..card import Card, Rank, Suit
from ..game_state import GameState
from ..player import Blind, MyPlayer, Player
from .engine import AI, Match, TimeLimitExceeded, time_limit
from .rules import Rules


# Bots are scored against each other in tournaments, so the score on a push is only a rough guide. A bot gets WORKING_SCORE,
# and then up to MATCH_SCORE for its win rate in heads-up matches against a bot which plays at random. How many sample states
# it returns an Action on is reported as the success rate.
NUM_STATES = 1000
WORKING_SCORE = 10

NUM_MATCHES = 100
MATCH_SCORE = 90


def random_ai(rng: random.Random) -> AI:
    # Plays a random action every time it is asked. It has its own random numbers, so that it plays the same way whatever the AI it is playing against does with the random module.
    def ai(state: GameState) -> Action:
        me = state.my_player

        if not me.chips_in_stack:
            return Action.check()

        raise_by = Action.raise_by(rng.randint(1, me.chips_in_stack))
        facing_a_bet = me.chips_bet < max(player.chips_bet for player in state.players)
        return rng.choice([Action.fold(), Action.call(), raise_by] if facing_a_bet else [Action.check(), Action.check(), raise_by])

    return ai


def sample_state(rng: random.Random) -> GameState:
    deck = [Card(rank, suit) for rank in Rank for suit in Suit]
    rng.shuffle(deck)

    hole_cards = {deck.pop(), deck.pop()}
    community_cards = {deck.pop() for _ in range(rng.choice([0, 3, 4, 5]))}

    blinds = [Blind.SMALL, Blind.BIG] + [None] * rng.randint(0, 4)
    rng.shuffle(blinds)

    my_player = MyPlayer(blind=blinds[0], chips_in_stack=rng.randint(1, 1000), chips_bet=rng.choice([0, rng.randint(1, 100)]), hole_cards=hole_cards)
    others = [Player(blind=blind, has_folded=rng.random() < 0.25, chips_in_stack=rng.randint(0, 1000), chips_bet=rng.choice([0, rng.randint(1, 100)])) for blind in blinds[1:]]

    players = [my_player] + others
    rng.shuffle(players)

    chips_in_pot = sum(player.chips_bet for player in players) + rng.choice([0, rng.randint(1, 500)])
    big_blind = rng.choice([2, 3, 4, 6, 8, 10, 15, 20])

    return GameState(my_player=my_player, players=players, chips_in_pot=chips_in_pot, community_cards=community_cards, small_blind=big_blind // 2, big_blind=big_blind, ante=rng.choice([0, big_blind]))


def check_states(ai: AI, count: int, timeout: float) -> list[str]:
    # Returns a description of each sample state on which the AI doesn't return an Action in time
    rng = random.Random(0)
    failures = []

    for number in range(count):
        state = sample_state(rng)

        try:
            with time_limit(timeout):
                result = ai(state)

        except TimeLimitExceeded:
            failures.append(f"state {number}: took longer than {timeout:g}s")
            continue

        except Exception as e:
            failures.append(f"state {number}: raised {type(e).__name__}: {e}"[:200])
            continue

        if not isinstance(result, Action):
            failures.append(f"state {number}: returned {result!r:.150} instead of an Action")

    return failures


def play_matches(name: str, ai: AI, count: int, rules: Rules) -> tuple[float, int]:
    # Plays heads-up matches against the random bot, and returns the share of matches won and the number of bad actions
    wins = 0.0
    errors = 0

    for number in range(count):
        random.seed(number)  # For AIs which use the random module
        ais = [(name, ai), ("random", random_ai(random.Random(number)))]
        match = Match(ais=ais if number % 2 == 0 else ais[::-1], rules=rules, seed=number)  # Seats swap every match
        match.play()

        most = max(seat.stack for seat in match.seats)
        leaders = [seat for seat in match.seats if seat.stack == most]
        me = next(seat for seat in match.seats if seat.name == name)

        if me in leaders:
            wins += 1 / len(leaders)

        errors += me.errors

    return wins / count, errors


def score(name: str, ai: AI, *, rules: Rules, output: Path, states: int = NUM_STATES, matches: int = NUM_MATCHES):
    # Scores an AI and writes the result to a file, a line for each value, which the competition workflow passes on to GitHub
    failures = check_states(ai, states, rules.timeout)

    for failure in failures[:10]:
        print(failure)

    success_rate = (states - len(failures)) / states if states else 1.0
    win_rate, errors = play_matches(name, ai, matches, rules) if matches else (0.0, 0)
    total = round(WORKING_SCORE + MATCH_SCORE * win_rate)

    print(f"Returned an Action on {success_rate:.0%} of {states} sample states")
    print(f"Won {win_rate:.0%} of {matches} matches against the random bot with {errors} bad actions")
    print(f"Score: {total}")

    details = json.dumps({"states": states, "failures": len(failures), "examples": failures[:10], "matches": matches, "win_rate": win_rate, "bad_actions": errors})  # json.dumps keeps it on one line, as GitHub needs
    output.write_text(f"score={total}\nsuccess_rate={100 * success_rate:g}\nwin_rate={100 * win_rate:g}\ndetails={details}\n", encoding="utf-8")
    print(f"Written to {output}")
