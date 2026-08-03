from __future__ import annotations

from core.ml_strategy import Strategy, StrategySelector


class HeuristicStrategySelector(StrategySelector):
    """
    Hand-crafted, non-learning teacher policy -- not meant as a ceiling,
    but as a cheap, genuinely state-dependent "warm start" for
    DQNStrategySelector's network via behavior cloning (see
    DQNStrategySelector.imitate()), so RL fine-tuning starts from a sane
    prior instead of random weights.

    Encodes what the fixed-strategy comparisons found empirically across
    every scenario tried this session:
      - AGGRESSIVE and FOCUS_FIRE are strong defaults almost everywhere
      - RETREAT is bad *unless* a creature is genuinely both hurt and
        outnumbered -- it was the worst fixed strategy in every single
        scenario calibrated this session (11-73% vs 79-99% for the good
        ones), so it should be rare, not just "an option"
      - PROTECT and FOCUS_FIRE have narrow, sensible triggers (an ally
        under pressure / a standout threat) rather than being generally
        good picks on their own
    """

    LOW_HP        = 0.25   # own HP ratio below this = genuinely hurt
    OUTNUMBERED   = 0.4    # team size advantage below this = outnumbered
    PROTECT_HP    = 0.4    # only protect if not also critically low yourself
    HIGH_THREAT   = 0.5    # normalised top-enemy-threat score

    def select(self, obs: list[float]) -> Strategy:
        own_hp        = obs[0]
        size_adv      = obs[3]
        ally_pressure = obs[7]
        top_threat    = obs[8]

        if own_hp < self.LOW_HP and size_adv < self.OUTNUMBERED:
            result = Strategy.RETREAT
        elif ally_pressure > 0.5 and own_hp > self.PROTECT_HP:
            result = Strategy.PROTECT
        elif top_threat > self.HIGH_THREAT:
            result = Strategy.FOCUS_FIRE
        else:
            result = Strategy.AGGRESSIVE

        self.tactic_counts[result] += 1
        return result
