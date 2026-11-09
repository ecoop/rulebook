<!--
Copyright (c) 2026 Eric Cooper. Released under the MIT License (see /LICENSE).

ORIGINAL PROSE — SAFE TO COMMIT. This file is a from-scratch description of
the public-domain game of checkers (English draughts), written for this repo
as a runnable sample corpus. The *game* is in the public domain, and the
*rules/method* of a game are not copyrightable (17 U.S.C. §102(b)); this
particular wording is original and ships under the repo's MIT license. It is
intentionally the exception to the "no rule docs in git" policy in
rules/SOURCES.md — it exists so a fresh clone can build an index and run the
pipeline end-to-end with no downloads.

Numbered "section.rule" so each clause chunks cleanly and cites as
[checkers 3.2]. Simplified for teaching: tournament checkers has more
detail (e.g. the three-move restriction) deliberately left out.
-->

# Checkers (English Draughts) — sample rules

A two-player board game of diagonal moves and jumps. These rules describe the
standard version, played on an 8x8 board with twelve pieces per side. They are
written as a small, self-contained ruleset for retrieval demos, not as a
tournament reference.

1.1 The board. Checkers is played on a square board of 64 alternating light and
dark squares, eight rows by eight columns. Play happens only on the 32 dark
squares; a piece never leaves the dark squares for the entire game. The board is
oriented so that each player has a dark square at their near-left corner.

1.2 The pieces. Each player has twelve identical disc-shaped pieces, called men,
of a single colour. The two colours are traditionally called black and white (or
red and white). A man that is later promoted becomes a king, usually shown by
stacking a second piece of the same colour on top of it.

1.3 Starting position. Each player places their twelve men on the dark squares of
the three rows nearest to them, filling all twelve of those dark squares. The two
middle rows of the board start empty, leaving a two-row gap between the armies.

2.1 Object of the game. The goal is to leave your opponent unable to move, either
by capturing all of their pieces or by blocking every piece they have so that no
legal move remains. The player who cannot move on their turn loses.

2.2 Who moves first. Black (the darker colour) moves first. Players then alternate
turns, making exactly one move per turn. A turn may be a single simple move or a
capturing move, including a chain of several jumps counted as one turn.

2.3 Simple moves. A man moves one square diagonally forward to an adjacent dark
square that is empty. "Forward" means toward the opponent's side of the board. A
simple move is only available when no capture is possible that turn (see 3.3).

2.4 Direction of movement. An ordinary man may move and capture only forward,
never backward, until it is promoted to a king. This forward-only restriction is
the main difference between a man and a king, and it is why reaching the far side
of the board is valuable.

3.1 Capturing. If an opponent's piece sits on a square diagonally adjacent and
forward, and the square immediately beyond it (in the same diagonal line) is
empty, you must jump: move your piece over the opponent's piece to the empty
square and remove the jumped piece from the board.

3.2 Multiple captures. If, after a jump, the same piece can immediately jump
another opponent's piece, it must continue jumping in the same turn. A chain of
jumps counts as a single turn, and every piece jumped along the way is removed.
The turn ends only when no further jump is available from the piece's new square.

3.3 Captures are compulsory. Capturing is mandatory: if any capture is available
at the start of your turn, you must make a capturing move rather than a simple
move. When more than one capturing move exists, you may choose which to take, but
you may not decline to capture in favour of a quiet move.

4.1 Crowning a king. When a man reaches the farthest row from its owner — the
opponent's back row, called the king row — it is promoted to a king at once by
crowning it with a second piece. If a man reaches the king row by the final jump
of a capturing chain, the turn ends there; the newly crowned king does not
continue jumping until the player's next turn.

4.2 How a king moves. A king moves one square diagonally in any direction, forward
or backward, to an adjacent empty dark square. This freedom to move backward makes
a king far more powerful than an ordinary man, because it can threaten and retreat
along both diagonals.

4.3 King captures. A king captures the same way a man does — by jumping an adjacent
opponent's piece into the empty square beyond it — but it may jump forward or
backward, and it may chain multiple jumps in any mix of directions. The same
compulsory-capture rule (3.3) applies to kings.

5.1 Winning. You win when your opponent has no legal move at the start of their
turn. This happens either because you have captured all of their pieces, or
because all of their remaining pieces are blocked and cannot move.

5.2 Draws. A game is drawn when neither player can force a win. In practice a draw
is agreed when both sides have so little material or such a locked position that no
progress is possible; many rule sets also declare a draw if no capture and no
promotion occur within a fixed number of moves by each side.

5.3 Touch-and-move. Under standard etiquette, if you touch one of your own movable
pieces you must move it, and if you touch an opponent's capturable piece you must
capture it, provided a legal move or capture with that piece exists. To adjust a
piece on its square without committing to move it, announce "I adjust" before
touching it.
