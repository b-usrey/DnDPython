from __future__ import annotations

from core.ml_strategy import Strategy, StrategySelector


class HeuristicStrategySelector(StrategySelector):
    """
    Hand-crafted, non-learning teacher policy -- not meant as a ceiling,
    but as a cheap, genuinely state-dependent "warm start" for
    DQNStrategySelector's network via behavior cloning (see
    DQNStrategySelector.imitate()), so RL fine-tuning starts from a sane
    prior instead of random weights.

    Retuned against four-PC party scenarios. Measured on
    eval_party_warband (n=80, red team, default AI = 50.0%):

        always AGGRESSIVE      56.2%
        this policy            43.8%
        previous thresholds    15.0%

    The previous version fired FOCUS_FIRE on ``top_threat > 0.5``, which in
    a party fight is true almost every turn -- it picked FOCUS_FIRE on 70%
    of turns and scored 15%. Two things were wrong with that. Against a
    single PC it did no harm, because with one enemy on the board "the
    lowest-HP enemy" is the enemy the default planner already picked, so
    the branch was a no-op; the trigger was never exercised in a fight
    where the choice mattered. And the informative signal for *finishing
    someone off* is the focus target's remaining HP (feature 10), not how
    dangerous the scariest enemy is.

    The guiding measurement is that AGGRESSIVE alone already matches or
    beats the default planner, so a good prior is "play aggressively, and
    deviate only in a real emergency". Every broader deviation rule tried
    scored worse. Narrow triggers only:

      - RETREAT when genuinely hurt *and* outnumbered -- it was the worst
        fixed strategy in every scenario calibrated (0-8% as a blanket
        policy), so it must be rare
      - PROTECT when a teammate is being focused, is badly hurt, and we are
        healthy enough to actually help
      - FOCUS_FIRE only to finish a nearly-dead target
      - AGGRESSIVE otherwise

    Where the RL should beat this: finding the situations in which KITE and
    the other deviations pay off. No hand-written trigger tried here
    identified them, which is precisely the open question training exists
    to answer.
    """

    LOW_HP          = 0.20   # own HP ratio below this = genuinely hurt
    OUTNUMBERED     = 0.35   # team size advantage below this = outnumbered
    PROTECT_SELF_HP = 0.60   # need to be healthy to be any use to an ally
    PROTECT_ALLY_HP = 0.25   # only worth it if the ally is actually in danger
    FINISH_HP       = 0.20   # focus target this close to death = finish them

    def select(self, obs: list[float]) -> Strategy:
        own_hp        = obs[0]
        size_adv      = obs[3]
        ally_pressure = obs[7]
        # Features 10/11 exist only on the 15-wide vector; the 9-wide Q-table
        # layout stops at index 8, so read them defensively.
        focus_hp      = obs[10] if len(obs) > 10 else 0.0
        pressured_hp  = obs[11] if len(obs) > 11 else 0.0

        if own_hp < self.LOW_HP and size_adv < self.OUTNUMBERED:
            result = Strategy.RETREAT
        elif (ally_pressure > 0.5
              and own_hp > self.PROTECT_SELF_HP
              and 0.0 < pressured_hp < self.PROTECT_ALLY_HP):
            result = Strategy.PROTECT
        elif 0.0 < focus_hp < self.FINISH_HP:
            result = Strategy.FOCUS_FIRE
        else:
            result = Strategy.AGGRESSIVE

        self.tactic_counts[result] += 1
        return result
