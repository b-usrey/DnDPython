class ActionTracker:
    """
    Tracks all action economy resources for one creature's turn.

    Resources:
      actions              — standard actions (1/turn, 2 with Action Surge)
      bonus_actions        — bonus actions (1/turn)
      reactions            — reactions (1/round, resets on turn start)
      extra_attacks        — extra attacks granted by Extra Attack feature
      action_surges        — Action Surge charges (fighters get 1, then 2 at lv17)
      legendary_actions    — legendary action pool for boss monsters
    """

    def __init__(self, extra_attacks=0, legendary_actions=0, action_surges=0):
        self.max_actions         = 1
        self.max_bonus_actions   = 1
        self.max_reactions       = 1
        self.extra_attacks       = extra_attacks
        self.max_action_surges   = action_surges
        self.legendary_actions   = legendary_actions
        self._full_reset()

    def reset(self):
        """Called at the start of each turn.

        Resets per-turn resources only.  Action Surge charges are a
        rest resource — they are NOT reset here.  Call short_rest() or
        long_rest() to recover them.
        """
        self.actions                  = self.max_actions
        self.bonus_actions            = self.max_bonus_actions
        self.reactions                = self.max_reactions
        self.remaining_extra_attacks  = self.extra_attacks
        # remaining_surges intentionally NOT reset here — Action Surge
        # recovers on a short or long rest, not at the start of each turn.
        self.remaining_legendary      = self.legendary_actions

    def _full_reset(self):
        """Reset everything including rest-gated resources. Used by __init__
        to set the initial state before any combat has happened.
        """
        self.reset()
        self.remaining_surges = self.max_action_surges

    def short_rest(self):
        """Recover Action Surge charges (and other short-rest resources)."""
        self.remaining_surges = self.max_action_surges

    def long_rest(self):
        """Recover all resources including those gated on a long rest."""
        self.short_rest()

    # ── Standard actions ──────────────────────────────────────────────

    def use_action(self) -> bool:
        if self.actions > 0:
            self.actions -= 1
            return True
        return False

    def use_bonus_action(self) -> bool:
        if self.bonus_actions > 0:
            self.bonus_actions -= 1
            return True
        return False

    def use_reaction(self) -> bool:
        if self.reactions > 0:
            self.reactions -= 1
            return True
        return False

    # ── Extra attacks (Extra Attack feature) ──────────────────────────

    def use_extra_attack(self) -> bool:
        """
        Consume one extra attack charge.
        Called by CombatManager after the main attack to fire additional hits.
        """
        if self.remaining_extra_attacks > 0:
            self.remaining_extra_attacks -= 1
            return True
        return False

    def grant_temp_extra_attack(self) -> None:
        """
        Add one temporary extra attack for this turn only.
        Used by Dread Ambusher (first round), Haste, etc.
        Does NOT increase self.extra_attacks (the permanent pool).
        """
        self.remaining_extra_attacks += 1

    # ── Action Surge ──────────────────────────────────────────────────

    def use_action_surge(self) -> bool:
        """
        Spend an Action Surge charge, immediately granting one extra action
        and refilling the extra attack pool for that action.
        Returns True if a surge was available and spent.
        """
        if self.remaining_surges > 0:
            self.remaining_surges         -= 1
            self.actions                  += 1          # extra action
            self.remaining_extra_attacks   = self.extra_attacks  # reset pool
            return True
        return False

    @property
    def can_surge(self) -> bool:
        return self.remaining_surges > 0

    # ── Legendary actions ─────────────────────────────────────────────

    def use_legendary_action(self) -> bool:
        if self.remaining_legendary > 0:
            self.remaining_legendary -= 1
            return True
        return False

    # ── Debug ─────────────────────────────────────────────────────────

    def __repr__(self):
        return (
            f"ActionTracker(actions={self.actions}, bonus={self.bonus_actions}, "
            f"reaction={self.reactions}, extra_atk={self.remaining_extra_attacks}, "
            f"surges={self.remaining_surges})"
        )