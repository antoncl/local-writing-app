"""Markdown guide bodies for built-in plot templates."""

from __future__ import annotations


def template_guide(key: str) -> str:
    return GUIDES[key].strip() + "\n"


def template_description(key: str) -> str:
    return DESCRIPTIONS[key]


DESCRIPTIONS: dict[str, str] = {
    "three_act": "A generic three-part structure template for broad story pressure, commitment, reversal, choice, and consequence.",
    "fifteen_beat_transformation": "A generic fifteen-beat transformation lens with original labels and wording.",
    "mythic_quest": "A generic mythic journey lens for departure, ordeal, return, and integration.",
    "twelve_step_quest": "A generic twelve-step quest structure with rephrased labels and elastic placement.",
    "integration_journey": "A generic integration and connection journey template for identity pressure, failed coping, support, reconnection, and changed action.",
    "circular_change": "A generic eight-part change cycle usable at scene, episode, subplot, or book scale.",
    "seven_point": "A generic seven-point plot lens organized around ending contrast, turns, pressure points, and resolution.",
    "kishotenketsu": "A four-part structure where development, contrast, and reconciliation can matter more than direct conflict.",
    "romance_relationship": "A generic relationship arc for attraction, vulnerability, rupture, repair, and emotionally satisfying closure.",
    "mystery_spine": "A generic fair-play mystery spine for puzzle, evidence, suspects, false interpretations, and earned solution.",
    "thriller_escalation": "A generic thriller lens for threat, time pressure, reversal, exposure, and confrontation.",
    "positive_character_change": "A generic arc for a character moving from a limiting belief toward a harder truth.",
    "negative_character_change": "A generic arc for a character rejecting truth, deepening a lie, or choosing corruption.",
    "steadfast_character": "A generic arc for a character whose stable truth changes the surrounding world.",
}


GUIDES: dict[str, str] = {
    "three_act": """
# Three-Act Story Arc

Use this template as a broad pressure map for a complete story. It is not a
chapter plan. A single beat can be earned by several cards, and one strong card
can carry more than one beat when the story logic supports it.

## How To Use It

Start by naming the ordinary pressure around the protagonist: what they want,
what they believe will work, and what is already unstable. The early turn should
make the old path unavailable, not merely add another event. The middle should
change the power balance, information state, or strategy so the story is not
just repeating the opening problem at higher volume. The crisis and climax
should test a choice the story has prepared.

## Beat Logic

- Setup pressure: show normal conditions, desire, and pressure before commitment.
- Inciting change: introduce a disruption the protagonist cannot fully ignore.
- First turn: close the old path and commit the story to its central problem.
- Midpoint reversal: change power, information, relationship, or strategy.
- Crisis: force the hard choice before resolution.
- Climax: test that choice in irreversible action.
- Resolution: show the consequence of the final choice.

## Common Weak Spots

- The first turn is only a new event, not a commitment.
- The midpoint raises stakes without changing what the protagonist understands or does.
- The resolution explains consequences instead of showing changed behavior.
""",
    "fifteen_beat_transformation": """
# Fifteen-Beat Transformation Arc

Use this template when you want a finer-grained diagnostic than a three-act map.
It tracks the pressure that moves a character or world from an opening state to
a visibly changed final state. Treat the labels as app-authored generic beats,
not as a branded beat sheet.

## How To Use It

The early beats should make the protagonist's want, lack, relationships, and
value question visible before the story engine starts moving. The middle is
where the premise proves itself: the story should explore the promised genre
pleasures while steadily increasing consequence. The late-middle beats should
make the current strategy fail, expose the cost of the old approach, and prepare
the synthesis that makes the ending feel earned.

## Beat Logic

- Opening state: show the self and world before pressure changes them.
- Theme pressure: raise the value question the story will test.
- Setup web: plant relationships, wants, lacks, and stakes.
- Catalyst: deliver the disruption that creates motion.
- Choice debate: let avoidance, risk, and desire compete.
- New world entry: move into the main pressure field.
- Promise play: explore the premise and genre engine.
- Central shift: reframe the visible win, loss, or problem.
- Opposition closes: increase pressure and resistance.
- Apparent loss: make the current strategy fail.
- Dark reckoning: face cost, lie, or impossible bargain.
- Solution synthesis: combine learned truth with practical action.
- Final plan: commit to the ending strategy and its cost.
- Final test: prove the changed strategy under maximum pressure.
- Final state: show the transformed self, world, or relationship.

## Common Weak Spots

- The opening has many facts but no pressure.
- The middle has incidents without a clear change in tactic, knowledge, or cost.
- The final test does not require anything learned earlier.
""",
    "mythic_quest": """
# Mythic Quest Arc

Use this template when the story feels like a movement out of a known order,
through an ordeal, and back into consequence. The journey can be literal,
psychological, social, spiritual, or political. What matters is that the return
changes the protagonist's relationship to the world they left.

## How To Use It

Define the known world strongly enough that leaving it has meaning. The call
should expose a lack, threat, invitation, or obligation that cannot be solved
from inside the old order. The middle trials should test more than competence:
they should also test loyalties, values, perception, and identity. The ending
should not stop at survival or victory. It should ask what the protagonist
brings back, what it costs, and whether the original world can receive it.

## Beat Logic

- Known world: establish the starting order and its limits.
- Call to change: invite or force movement beyond the known world.
- Threshold: enter a space where old rules no longer suffice.
- Tests, allies, enemies: build trials, bargains, helpers, and opposition.
- Central ordeal: confront the deepest test.
- Boon or cost: gain knowledge, power, wound, loss, or obligation.
- Return pressure: force the change back toward consequence.
- Integrated return: show what the journey changes for self and community.

## Common Weak Spots

- The known world is thin, so departure has no weight.
- Trials test only skill and never belief, loyalty, or identity.
- The return is skipped, so the journey has no social or internal consequence.
""",
    "twelve_step_quest": """
# Twelve-Step Quest Arc

Use this template when you want a quest or adventure spine with more checkpoints
than the mythic quest lens. It is useful for fantasy, science fiction, adventure,
heist, portal, and personal transformation stories where the protagonist moves
from ordinary order into unfamiliar rules and back into consequence.

## How To Use It

The first five beats should make commitment difficult: the starting order,
summons, resistance, guidance, and crossing all clarify why the quest matters and
why the protagonist is not already ready for it. The middle should be a network
of trials rather than a straight tunnel. The ordeal should change the quest's
meaning, not merely produce a difficult fight. The return beats should prove
that the gained truth, wound, or boon matters outside the ordeal itself.

## Beat Logic

- Starting order: show the world and identity before disruption.
- Summons: present the invitation, threat, or need.
- Resistance: show why engagement is difficult.
- Guidance: offer tools, warning, model, or misleading counsel.
- Crossing: commit to unfamiliar rules.
- Trial network: test skill, loyalty, desire, and perception.
- Deep approach: narrow options before the ordeal.
- Ordeal: test the protagonist at a symbolic or practical death point.
- Reward: gain boon, truth, wound, or leverage.
- Return route: drive the changed protagonist toward consequence.
- Last transformation: require the deepest change under ending pressure.
- Boon shared: show the changed bond between protagonist, world, and gift.

## Common Weak Spots

- The refusal or resistance is perfunctory.
- Guidance solves problems for the protagonist instead of changing readiness.
- The boon is obtained but never tested by the return.
""",
    "integration_journey": """
# Integration Journey

Use this template for a journey where the central movement is not conquest but a
more workable relationship with self, support, belonging, and action. It is
useful for stories where the protagonist survives by performing a role or coping
strategy, then has to discover that the strategy no longer fits the reality of
the story.

## How To Use It

Begin with the world the protagonist believes they understand and the coping
strategy that helps them function inside it. That strategy may be pleasing,
exceptionalism, detachment, compliance, control, ambition, caretaking, secrecy,
or any other pattern that once worked. The story pressure should expose the
strategy's limits through betrayal, disillusionment, exhaustion, failed success,
or a mismatch between what the protagonist wins and what they actually need.

The middle should not be vague introspection. It should create concrete moments
where old tactics stop working and where support, friendship, community, trust,
or a different model of strength becomes available. The ending should show
integration through changed behavior: the protagonist acts from a fuller
understanding of self and relationship, not just from a new private insight.

## Beat Logic

- Identity pressure: show the assumed world, role, or value system under strain.
- Adaptation strategy: show the coping pattern that helps the protagonist get by.
- Outer success, inner cost: let success, approval, or survival reveal what is missing.
- Descent: expose the practical limit of the old strategy.
- Reconnection: rebuild support, belonging, trust, or a needed model of strength.
- Integration: align self-understanding, relationship, and action.

## Common Weak Spots

- The adaptation strategy is only bad, so losing it costs nothing.
- Support arrives as rescue instead of changing what the protagonist can choose.
- Integration is stated as self-knowledge but not shown through behavior.
""",
    "circular_change": """
# Circular Change Arc

Use this template for a compact cycle of desire, departure, search, cost, return,
and change. It scales well: a whole novel, a subplot, an episode, or a single
sequence can all use the same eight-part movement.

## How To Use It

Define the comfort state clearly enough that desire has a direction. The need
should break stasis and pull the character into an unfamiliar mode of action.
The search phase should force adaptation rather than simply delay the goal. The
find and take-the-cost beats belong together: a gain should create obligation,
loss, compromise, or irreversible knowledge. The return and changed beats should
make the ending visibly contrast with the opening.

## Beat Logic

- Comfort: show the known state before desire pulls outward.
- Need: clarify the want, lack, or pressure that breaks stasis.
- Go: move into an unfamiliar situation or tactic.
- Search: force adaptation through pursuit, trial, or improvisation.
- Find: reach the apparent goal or discover its real cost.
- Take the cost: pay for the gain with loss, compromise, or change.
- Return: carry the changed self or prize back toward the known world.
- Changed: show contrast between initial and final state.

## Common Weak Spots

- The character leaves comfort for plot convenience rather than need.
- The apparent gain has no cost.
- The return repeats the old world without showing what has changed.
""",
    "seven_point": """
# Seven-Point Plot Arc

Use this template when you want a small, scalable structure built around contrast
between the opening and ending, with turns and pressure points controlling the
middle. It is useful for subplots because it is compact and easy to nest inside a
larger book structure.

## How To Use It

Think from both ends. The hook shows the starting state that the resolution will
answer or reverse. The first turn commits the story to motion. The pressure
points should prove that opposition is active and that easy paths are closing.
The midpoint should move the protagonist from reaction toward action. The second
turn should supply the final missing insight, resource, or decision path needed
for the resolution.

## Beat Logic

- Hook: show the initial state that will contrast with the resolution.
- First plot turn: introduce the central conflict or opportunity.
- First pressure point: prove the problem is real.
- Midpoint shift: move the protagonist from reaction toward action.
- Second pressure point: tighten stakes and remove easy paths.
- Second plot turn: provide the final missing insight, resource, or decision path.
- Resolution: pay off the hook by showing the changed ending state.

## Common Weak Spots

- The hook and resolution do not clearly contrast.
- Pressure points are random setbacks rather than targeted opposition.
- The midpoint does not change initiative, knowledge, or strategy.
""",
    "kishotenketsu": """
# Kishotenketsu Four-Part Arc

Use this template when contrast, juxtaposition, and reconciliation matter more
than direct antagonist escalation. It can still contain conflict, but conflict is
not the engine the template requires. The turn can be a surprising image,
perspective, fact, relationship, or context that reinterprets what came before.

## How To Use It

Let the introduction establish material worth developing without forcing an
immediate battle. The development should deepen, vary, or accumulate that
material so the reader has a pattern to recognize. The turn should introduce a
meaningful contrast, not merely a louder event. The reconciliation should make
the first three parts belong together by producing a new understanding, emotional
shape, or situation.

## Beat Logic

- Introduction: present the situation, image, relationship, or premise.
- Development: deepen the initial material through variation or accumulation.
- Turn: introduce contrast, surprise, or a new perspective.
- Reconciliation: combine the first three movements into a new understanding.

## Common Weak Spots

- The development repeats the introduction instead of deepening it.
- The turn is treated as a mandatory combat climax.
- The ending resolves events without integrating the contrast.
""",
    "romance_relationship": """
# Romance Relationship Arc

Use this template to track the emotional movement of a central relationship. It
is not only a sequence of events between two people. Each beat should change the
state of attraction, trust, vulnerability, risk, accountability, or commitment.

## How To Use It

The encounter should matter because it creates a new relational possibility. The
early pull and resistance should both be believable: attraction without risk is
thin, and resistance without desire becomes stalling. The middle should provide
evidence of trust or partnership, then test it through external pressure or
internal wounds. The rupture should reveal why the relationship genuinely seems
impossible. The repair should require changed behavior, not just explanation.

## Beat Logic

- Encounter: bring the participants into meaningful contact.
- Attraction and resistance: create pull while naming why intimacy is risky.
- Bond deepens: show trust, vulnerability, intimacy, or partnership.
- Relationship test: force pressure against the bond.
- Dark moment: make the relationship appear impossible or too costly.
- Repair choice: require accountability, courage, sacrifice, or changed behavior.
- Satisfying ending: confirm an emotionally satisfying optimistic relationship state.

## Common Weak Spots

- Attraction is asserted but not dramatized.
- The rupture depends only on an easily fixed misunderstanding.
- The ending promises commitment without showing changed behavior.
""",
    "mystery_spine": """
# Mystery Investigation Arc

Use this template to track a fair-play puzzle: what question is being solved,
what evidence is available, how false interpretations are supported, and why the
solution feels earned when it arrives. It can support murder mystery, procedural,
cozy, noir, conspiracy, or any story where discovery is a core engine.

## How To Use It

The opening should define a concrete question the reader can track. The
investigator may be a detective, amateur, journalist, friend, victim, or any
viewpoint character who commits to seeking truth. Clues should be inspectable:
they can be misunderstood, but the reader should be able to look back and see
that they were present. Red herrings should be plausible interpretations, not
random distractions. The solution should resolve the puzzle with evidence the
story has earned.

## Beat Logic

- Crime or question: create the explicit puzzle.
- Investigator engages: commit a viewpoint character to seeking truth.
- First clue: provide inspectable evidence.
- Suspect web: build motives, opportunity, alibis, and competing interpretations.
- Red herring: support a plausible but wrong interpretation.
- Reveal chain: make the solution feel earned before confirmation.
- Solution: resolve the puzzle with evidence already made available.

## Common Weak Spots

- Clues are hidden from the reader until the reveal.
- Red herrings are decorative rather than plausible alternatives.
- The solution depends on late information that was never planted.
""",
    "thriller_escalation": """
# Thriller Escalation Arc

Use this template when the story engine is danger under pressure. A thriller does
not only need high stakes; it needs visible threat, narrowing time, reversals,
exposure, and choices that make delay expensive.

## How To Use It

Make the threat concrete enough that the reader knows what could happen and why
it matters. The clock can be literal time, a closing investigation, a spreading
conspiracy, a health risk, a deadline, or a rapidly changing opportunity. Each
middle beat should either intensify the threat, remove safety, change trust, or
force the protagonist into a riskier tactic. The final window should narrow the
story to one dangerous option, and the confrontation should require direct
action against the threat.

## Beat Logic

- Threat declared: make the danger concrete enough to track.
- Stakes and clock: define what is at risk and why delay matters.
- First reversal: show the threat adapting, expanding, or becoming personal.
- No safe place: remove refuge, trust, or procedural protection.
- Truth exposure: reveal information that changes trust or strategy.
- Last window: narrow the problem to one dangerous, time-bound option.
- Confrontation: force direct action against the threat.

## Common Weak Spots

- Stakes are large but emotionally generic.
- Escalation only adds more danger without changing options.
- The final confrontation could have happened earlier with the same effect.
""",
    "positive_character_change": """
# Positive Character Change Arc

Use this template to track a character moving from a limiting belief toward a
harder truth. The arc is strongest when the false belief once protected the
character, so releasing it costs something real.

## How To Use It

Name both the want and the lie. The want creates visible motion; the lie shapes
how the character pursues it. Early pressure should demonstrate that the old
belief cannot solve the story's real problem. The middle should offer glimpses
of a better truth, but the character should not accept it simply because the
author says so. The cost beat should make the old belief visibly damage the
character, their relationships, or their goal. The ending should show changed
belief through changed action.

## Beat Logic

- Want and lie: show desire and the false belief shaping it.
- Need pressure: create pressure that the old belief cannot solve.
- Truth glimpse: offer evidence of a better value or self-understanding.
- Lie cost: make clinging to the old belief visibly costly.
- Truth choice: require action from the changed belief.
- Changed self: show the new internal state in external behavior.

## Common Weak Spots

- The lie is obviously wrong from the start and never tempting.
- The truth is preached rather than dramatized.
- The ending says the character changed but shows the same behavior.
""",
    "negative_character_change": """
# Negative Character Change Arc

Use this template for tragedy, corruption, obsession, downfall, or any story
where a character rejects truth and commits more deeply to a destructive belief.
The arc is not simply failure. It is a pattern of choices that make the false
path increasingly attractive, useful, or irreversible.

## How To Use It

Begin with a desire and wound that make the false path understandable. The story
should offer real chances to choose differently, not just push the character down
a chute. False gains matter: the destructive strategy should work well enough in
the short term that the character has a reason to keep using it. The moral point
of no return should be an action the character owns. The ending can be collapse,
victory, isolation, punishment, or coronation, but it should show the consequence
of embracing the destructive path.

## Beat Logic

- Want and wound: show desire and pain that make the false path attractive.
- Truth rejected: offer a healthier alternative the character refuses.
- False gain: reward the destructive strategy enough to deepen commitment.
- Moral point of no return: turn the false belief into an irreversible choice.
- Collapse or coronation: show the consequence of fully embracing the path.

## Common Weak Spots

- The character has no meaningful opportunity to choose differently.
- The false path never provides a believable reward.
- The ending punishes the character without revealing the logic of the fall.
""",
    "steadfast_character": """
# Steadfast Character Arc

Use this template for a character whose core truth remains stable while the
surrounding world changes. The movement is not internal reversal but tested
conviction, cost, influence, and external transformation.

## How To Use It

The opening should make the core value specific enough to be tested. The world
challenge should not be a mild disagreement; it should show why this value is
inconvenient, punished, dismissed, or dangerous. The middle must make steadfastness
expensive. If the character never pays a cost, the value is not being tested. The
influence turn should show another person, institution, family, team, or system
beginning to shift because the character held firm. The ending should pay off
that influence through an external change.

## Beat Logic

- Core truth: establish the value the character will hold under pressure.
- World challenge: show the world testing or punishing that value.
- Cost of steadfastness: make remaining true meaningfully expensive.
- Influence turn: show another person, institution, or system beginning to change.
- World changed: pay off the steadfast value through external transformation.

## Common Weak Spots

- The core truth is vague, so pressure cannot test it.
- The character is passive while the world changes by coincidence.
- The ending validates the value without showing external consequence.
""",
}
