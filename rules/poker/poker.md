<!--
Copyright (c) 2026 Eric Cooper. Released under the MIT License (see /LICENSE).

ORIGINAL PROSE — SAFE TO COMMIT. A from-scratch description of five public-domain
poker variants (five-card draw, five-card stud, seven-card stud, Razz, and Omaha).
The games are in the public domain, and the rules/method of a game are not
copyrightable (17 U.S.C. §102(b)); this wording is original and ships under the
repo's MIT license. Like rules/checkers/ and rules/tennis/ it is the deliberate
exception to the "no rule docs in git" policy in rules/SOURCES.md.

WHY IT EXISTS — a STRESS corpus for retrieval evaluation. Unlike checkers/tennis
(clean, easy), these five variants share almost all their vocabulary (ante, bring-in,
betting round, showdown, hole cards) but differ in specifics, so their rules are
near-duplicates that differ mainly in the variant each one names. That is exactly the
case a static embedder (which averages token vectors) handles poorly — the variant
phrase gets washed out — and a contextual embedder handles better. Run the eval
(eval/gold/poker.jsonl) against this domain to SEE retrieval get hard; it is the
headroom that makes an embedder comparison mean something.

Numbered so each variant owns a top-level section (1=five-card draw, 2=five-card
stud, 3=seven-card stud, 4=Razz, 5=Omaha) and every rule_id is unique across the
domain. Analogous rules sit at parallel positions (x.2 = the deal, x.4 = betting
rounds, …) so the confusable pairs are easy to target. Simplified for teaching; real
cardroom rules carry far more detail.
-->

# Poker variants — sample rules

Five classic poker variants, described side by side. They share a common skeleton —
a deck of 52 cards, forced bets, rounds of betting, and a showdown where the best
hand wins — but each fills that skeleton in differently. Standard poker hand rankings
(high card, pair, two pair, three of a kind, straight, flush, full house, four of a
kind, straight flush) are assumed throughout except where a variant says otherwise.

## 1. Five-Card Draw

1.1 Object. In five-card draw, each player tries to make the best five-card poker
hand by standard high rankings. The highest hand at the showdown wins the pot.

1.2 The deal. In five-card draw, every player is dealt five cards, all face down, so
no one can see any part of another player's hand. There are no face-up or shared
cards in this game.

1.3 Opening the betting. In five-card draw the hand is seeded by a forced bet — an
ante from every player, or in some home games a small and big blind — after which the
first round of betting begins to the dealer's left.

1.4 Betting rounds. Five-card draw has exactly two betting rounds: one after the
cards are dealt and one after the draw.

1.5 The draw. In five-card draw, on your turn you may discard any number of your cards
(commonly up to three) and receive the same number of replacements from the deck; you
may also "stand pat" and draw none. This exchange is what gives the game its name.

1.6 Showdown. In five-card draw, after the second betting round the remaining players
reveal their hands and the highest five-card hand wins.

## 2. Five-Card Stud

2.1 Object. In five-card stud, each player tries to make the best five-card high
hand. The highest hand at the showdown wins.

2.2 The deal. In five-card stud, each player gets one card face down and then four
cards face up, dealt one at a time across the betting rounds — so most of each
player's hand is visible to the whole table. Cards are never exchanged.

2.3 Opening the betting. In five-card stud the betting is opened by a forced
"bring-in": after the first face-up card, the player showing the lowest up-card must
post it, and the action proceeds from there.

2.4 Betting rounds. Five-card stud has four betting rounds — one after each of the
second, third, fourth, and fifth cards (that is, after each face-up card is dealt).

2.5 No draw. Five-card stud is a stud game, so there is no draw: you keep the cards
you are dealt and never discard or replace any of them.

2.6 Showdown. In five-card stud, after the final betting round the best five-card high
hand among the dealt cards wins the pot.

## 3. Seven-Card Stud

3.1 Object. In seven-card stud, each player makes the best five-card high hand out of
seven cards. The highest five-card hand at the showdown wins.

3.2 The deal. In seven-card stud, each player is dealt two cards face down and one
face up to start (third street), then three more face up (fourth, fifth, and sixth
streets), and finally a seventh card face down. Three of the seven cards are hidden.

3.3 Opening the betting. In seven-card stud the betting opens on third street with a
forced bring-in posted by the player showing the lowest up-card.

3.4 Betting rounds. Seven-card stud has five betting rounds, one on each of third,
fourth, fifth, sixth, and seventh streets.

3.5 No draw. Seven-card stud is a stud game: there is no draw, and you build your hand
only from the seven cards you are dealt.

3.6 Showdown. In seven-card stud, each remaining player forms the best five-card high
hand from their seven cards, and the highest wins.

## 4. Razz

4.1 Object. Razz is seven-card stud played for low: the lowest five-card hand wins the
pot, not the highest. Straights and flushes do not count against the hand and the ace
is always low, so the best possible Razz hand is 5-4-3-2-A, known as the "wheel".

4.2 The deal. In Razz the deal is identical to seven-card stud — two cards face down
and one face up on third street, three more face up, and a seventh card face down.
Only the goal of the game differs.

4.3 Opening the betting. In Razz, because a low hand is the goal, the forced bring-in
on third street is posted by the player showing the highest up-card — the reverse of
seven-card stud, where the lowest card brings in.

4.4 Betting rounds. Razz has five betting rounds, on third through seventh streets,
exactly as in seven-card stud.

4.5 No draw. Razz is a stud game, so there is no draw; you build your low hand from the
seven cards you are dealt.

4.6 Showdown. In Razz, at the showdown the player with the lowest five-card hand, by
the ace-to-five low ranking, wins the pot.

## 5. Omaha

5.1 Object. In Omaha, each player makes the best five-card high hand using exactly two
of their own cards together with three shared community cards.

5.2 The deal. In Omaha, each player is dealt four private "hole" cards face down — twice
as many as in a Texas-style hold'em game.

5.3 Community cards. In Omaha, five shared community cards are dealt face up in the
middle of the table — three at once (the flop), then one (the turn), then one (the
river) — and every player uses them.

5.4 The "exactly two" rule. In Omaha your final hand must use exactly two of your four
hole cards plus exactly three of the five community cards — never one or three of your
own, always precisely two. This is the rule newcomers from hold'em most often get wrong.

5.5 Betting rounds. Omaha has four betting rounds: before the flop, and then after the
flop, the turn, and the river.

5.6 Opening the betting. In Omaha the betting is seeded by two forced blinds — a small
blind and a big blind posted to the dealer's left — with no ante and no bring-in.

5.7 Showdown. In Omaha, at the showdown the best five-card high hand, formed under the
exactly-two-plus-three rule, wins the pot.
