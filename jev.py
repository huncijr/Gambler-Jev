"""Gambler Jev backend: blackjack math in code, judgment via TypeSafe Jev.

Design follows the TypeSafe skill: code owns the workflow and all exact
calculations (totals, bust chance, basic strategy). Jev only supplies the
typed judgment (Choice over hit/stand/double + Noul on whether to hit),
which code then composes into percentages and a message for the UI.
"""

import os

from typesafe_sdk import Choice, Noul, TypeSafeClient

MODEL = "jev-latest"
REQUEST_TIMEOUT = 10.0


def key_is_plausible(key):
    """True when the key at least looks like a real TypeSafe key."""
    return bool(key) and key.startswith("apikey_") and len(key) > 20

TEN_VALUES = {"10", "J", "Q", "K"}


def card_min_value(value):
    """Minimum blackjack value of a rank (ace counts as 1 here)."""
    if value == "A":
        return 1
    if value in TEN_VALUES:
        return 10
    return int(value)


def hand_total(cards):
    """Return (total, soft) for a list of card dicts/values.

    `soft` is True when an ace is currently counted as 11.
    """
    values = [c["value"] if isinstance(c, dict) else c for c in cards]
    total = 0
    aces = 0
    for v in values:
        if v == "A":
            aces += 1
            total += 11
        elif v in TEN_VALUES:
            total += 10
        else:
            total += int(v)
    soft = aces > 0
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    if aces == 0:
        soft = False
    return total, soft


def bust_chance(cards):
    """Exact probability that one more hit busts (13-rank, infinite deck).

    For totals <= 11 nothing can bust. Otherwise a rank busts when
    total + its minimum value > 21 (a usable ace always counts as 1
    here, since total + 11 > 21 for any total >= 12).
    """
    total, _ = hand_total(cards)
    if total > 21:
        return 1.0
    if total <= 11:
        return 0.0
    bust_ranks = 0
    for rank in ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]:
        if total + card_min_value(rank) > 21:
            bust_ranks += 1
    return round(bust_ranks / 13.0, 4)


def dealer_up_value(card):
    if card is None:
        return None
    v = card["value"] if isinstance(card, dict) else card
    if v == "A":
        return 11
    if v in TEN_VALUES:
        return 10
    return int(v)


def basic_strategy(player_cards, dealer_up):
    """Simplified basic strategy, used for fallback text and state context."""
    total, soft = hand_total(player_cards)
    dealer = dealer_up_value(dealer_up)
    dealer = dealer if dealer is not None else 10
    if total > 21:
        return "stand"  # already bust, nothing to do
    if soft:
        if total <= 14:
            return "hit"
        if total in (15, 16):
            return "double" if dealer in (4, 5, 6) else "hit"
        if total == 17:
            return "double" if dealer in (3, 4, 5, 6) else "hit"
        if total == 18:
            if dealer in (3, 4, 5, 6):
                return "double"
            return "stand" if dealer in (2, 7, 8) else "hit"
        return "stand"
    if total <= 8:
        return "hit"
    if total == 9:
        return "double" if dealer in (3, 4, 5, 6) else "hit"
    if total == 10:
        return "double" if dealer <= 9 else "hit"
    if total == 11:
        return "double" if dealer != 11 else "hit"
    if total == 12:
        return "stand" if dealer in (4, 5, 6) else "hit"
    if 13 <= total <= 16:
        return "stand" if dealer <= 6 else "hit"
    return "stand"


def format_card(card):
    v = card["value"] if isinstance(card, dict) else card
    s = card.get("suit", "") if isinstance(card, dict) else ""
    return f"{v}{s}"


def build_message(choice, confidence, player_total, dealer_up, bust, basic):
    dealer_txt = format_card(dealer_up) if dealer_up else "?"
    bust_pct = round(bust * 100)
    if choice == "hit":
        msg = (
            f"You've got {player_total} against a dealer {dealer_txt}. "
            f"I'd HIT — bust chance is only {bust_pct}%."
            if bust < 0.4
            else f"You've got {player_total} against a dealer {dealer_txt}. "
            f"I'd still HIT, but careful — bust chance is {bust_pct}%!"
        )
    elif choice == "double":
        msg = (
            f"You've got {player_total} against a dealer {dealer_txt}. "
            f"Strong spot — I'd DOUBLE! Bust chance is just {bust_pct}%."
        )
    else:
        msg = (
            f"You've got {player_total} against a dealer {dealer_txt}. "
            f"I'd STAND — bust chance is {bust_pct}%, not worth the risk."
        )
    if confidence < 0.5:
        msg = "Hmm, close call. " + msg + " Math says the same as basic strategy."
    return msg


def fallback_advice(player_cards, dealer_up, reason="Jev is offline"):
    total, _ = hand_total(player_cards)
    bust = bust_chance(player_cards)
    basic = basic_strategy(player_cards, dealer_up)
    dealer_txt = format_card(dealer_up) if dealer_up else "?"
    return {
        "jev_available": False,
        "source": "fallback",
        "choice": basic,
        "probabilities": {},
        "percent": {},
        "confidence": 0.0,
        "should_hit": None,
        "bust_chance": bust,
        "basic": basic,
        "message": (
            f"{reason} — math says: {basic.upper()} "
            f"({total} vs dealer {dealer_txt}, bust chance {round(bust * 100)}%)."
        ),
    }


def get_jev_advice(player_cards, dealer_up):
    """Ask Jev for the next move. Always returns a UI-ready dict."""
    total, soft = hand_total(player_cards)
    bust = bust_chance(player_cards)
    basic = basic_strategy(player_cards, dealer_up)

    if not os.environ.get("TYPESAFE_API_KEY"):
        return fallback_advice(player_cards, dealer_up, "Jev is offline (no API key)")

    if not key_is_plausible(os.environ.get("TYPESAFE_API_KEY")):
        return fallback_advice(
            player_cards,
            dealer_up,
            "Jev is offline (API key looks like a placeholder — "
            "put your real key in .env and restart the server)",
        )

    player_txt = ", ".join(format_card(c) for c in player_cards)
    dealer_txt = format_card(dealer_up) if dealer_up else "unknown"
    state = {
        "player_hand": player_txt,
        "player_total": total,
        "is_soft": soft,
        "dealer_upcard": dealer_txt,
        "exact_bust_chance_if_hit": bust,
        "basic_strategy_says": basic,
        "allowed_actions": ["hit", "stand", "double"],
    }
    questions = {
        "best_move": Choice(
            instructions=(
                "What is the player's best next move in blackjack given "
                "`player_hand` (`player_total`, soft means an ace counts as 11) "
                "against the dealer's visible card `dealer_upcard`? "
                "Consider `exact_bust_chance_if_hit`."
            ),
            criteria={
                "hit": "Take one more card. Good with low totals or when the hand must improve to beat a strong dealer card.",
                "stand": "Take no more cards. Good with high totals or when the bust chance makes hitting too risky.",
                "double": "Double down (take exactly one more card). Only for strong totals around 9-11 against a weak dealer card.",
            },
        ),
        "should_hit": Noul(
            instructions=(
                "Should the player take another card given `player_hand` "
                "against `dealer_upcard`?"
            ),
        ),
    }

    try:
        with TypeSafeClient() as client:
            response = client.system_one(
                state=state, questions=questions, model=MODEL, timeout=REQUEST_TIMEOUT
            )
        answers = response.answers
        best = answers["best_move"]
        hit_noul = answers["should_hit"].noul
        probs = {k: round(float(v), 4) for k, v in best.probabilities.items()}
        percent = {k: round(float(v) * 100) for k, v in best.probabilities.items()}
        choice = best.choice
        confidence = round(float(best.confidence), 4)
    except Exception as exc:  # network, auth, rate limits -> honest fallback
        name = type(exc).__name__
        if "Auth" in name or "401" in str(exc):
            reason = (
                "Jev is offline (API key rejected with 401 — "
                "check .env for typos and restart the server; "
                "if it persists, generate a new key)"
            )
        else:
            reason = f"Jev is offline ({name})"
        return fallback_advice(player_cards, dealer_up, reason)

    return {
        "jev_available": True,
        "source": "jev",
        "choice": choice,
        "probabilities": probs,
        "percent": percent,
        "confidence": confidence,
        "should_hit": round(float(hit_noul), 4),
        "bust_chance": bust,
        "basic": basic,
        "player_total": total,
        "is_soft": soft,
        "message": build_message(choice, confidence, total, dealer_up, bust, basic),
    }
