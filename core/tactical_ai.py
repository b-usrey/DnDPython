"""
core/tactical_ai.py

Tactical AI for monster/NPC turns. Given a creature and a BattleMap,
decides the best action to take: where to move and what to attack.

Design goals:
  - Pluggable: swap in a different AI by passing a different class
  - Readable: each method represents one decision with clear logic
  - Stateless: AI holds no combat state — all decisions come from
    the current game state passed in at call time

Tactical priorities (in order):
  1. If dead / incapacitated — skip
  2. Pick a target (focus weakest enemy by HP)
  3. Decide weapon (ranged if target is far and we have one, else melee)
  4. Move: close if melee, maintain distance if ranged, disengage if low HP
  5. Attack with chosen weapon
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.attack import hit_probability

if TYPE_CHECKING:
    from core.creature import Creature
    from core.battle_map import BattleMap

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WeaponProfile — lightweight description of an attack option
# ---------------------------------------------------------------------------

class WeaponProfile:
    """
    Describes one attack option available to a creature.
    Populated from the creature's equipped items or monster attack data.
    """
    def __init__(
        self,
        name: str,
        is_ranged: bool,
        normal_range: int,
        long_range: int,
        item=None,              # Item object if equipped, None for raw monster attacks
        attack_bonus: int = 0,
        damage_die: str = "1d6",
        damage_mod: int = 0,
    ):
        self.name = name
        self.is_ranged = is_ranged
        self.normal_range = normal_range
        self.long_range = long_range
        self.item = item
        self.attack_bonus = attack_bonus
        self.damage_die = damage_die
        self.damage_mod = damage_mod

    def __repr__(self):
        kind = "ranged" if self.is_ranged else "melee"
        return f"WeaponProfile({self.name!r}, {kind}, range={self.normal_range}/{self.long_range})"


# ---------------------------------------------------------------------------
# TacticalDecision — what the AI decided to do this turn
# ---------------------------------------------------------------------------

class TacticalDecision:
    """
    The result of the AI's planning phase.
    CombatManager reads this and executes it.
    """
    def __init__(
        self,
        target=None,
        path=None,           # list of (col, row) squares to walk — empty = no move
        weapon=None,
        skip: bool = False,
        reason: str = "",
        use_dash: bool = False,
        use_dodge: bool = False,
    ):
        self.target    = target
        self.path      = path or []
        self.weapon    = weapon
        self.skip      = skip
        self.reason    = reason
        self.use_dash  = use_dash
        self.use_dodge = use_dodge

    @property
    def move_to(self):
        """Final destination square, or None if no movement planned."""
        return self.path[-1] if self.path else None

    def __repr__(self):
        if self.skip:
            return f"TacticalDecision(skip, reason={self.reason!r})"
        dash_str = " [DASH]" if self.use_dash else ""
        steps = len(self.path)
        return (
            f"TacticalDecision("
            f"target={self.target.name if self.target else None!r}, "
            f"path={steps} steps → {self.move_to}, "
            f"weapon={self.weapon.name if self.weapon else None!r}"
            f"{dash_str})"
        )


# ---------------------------------------------------------------------------
# TacticalAI
# ---------------------------------------------------------------------------

class TacticalAI:
    """
    Tactical AI controller. Instantiate once and call plan_turn() each turn.

    Pass strategy_selector=RLStrategySelector() or EvolutionarySelector()
    to enable ML-driven strategy selection. When a selector is present,
    plan_turn() calls selector.select(obs) each turn to choose between
    AGGRESSIVE, KITE, and RETREAT, then executes accordingly.
    Without a selector, the rule-based fallback applies.
    """

    DISENGAGE_THRESHOLD = 0.25
    KITE_DISTANCE = 3

    def __init__(self, strategy_selector=None, trained_team=None):
        self.strategy_selector = strategy_selector
        # trained_team gates the selector so it only fires for creatures
        # on that team.  None means "apply to all" (training mode).
        self.trained_team = trained_team
        # current_strategy can also be set externally by StrategyTrainer
        self.current_strategy = None

    def plan_turn(
        self,
        creature: Creature,
        battle_map: BattleMap,
        memory=None,            # optional TeamMemory — enables coordinated decisions
    ) -> TacticalDecision:
        """
        Main entry point. Returns a TacticalDecision for CombatManager to execute.

        If `memory` is provided (a TeamMemory instance for this creature's team),
        target selection and threat assessment use shared team intelligence instead
        of purely individual observation.
        """
        if not creature.is_alive():
            _log.debug("[%s] %s: skipping turn — dead", creature.team, creature.name)
            return TacticalDecision(skip=True, reason="creature is dead")

        if creature.has_condition("incapacitated") or creature.has_condition("unconscious"):
            _log.info("[%s] %s: skipping turn — %s", creature.team, creature.name,
                      ", ".join(creature.conditions))
            return TacticalDecision(skip=True, reason=f"creature is {list(creature.conditions)}")

        enemies = battle_map.enemies_of(creature)
        if not enemies:
            _log.debug("[%s] %s: skipping turn — no enemies", creature.team, creature.name)
            return TacticalDecision(skip=True, reason="no enemies on map")

        # ── 1. Pick target ─────────────────────────────────────────────
        target = self._pick_target(creature, enemies, battle_map, memory)

        # ── 2. Pick weapon ─────────────────────────────────────────────
        weapons = self._get_weapon_profiles(creature)
        if not weapons:
            _log.info("[%s] %s: skipping turn — no weapons", creature.team, creature.name)
            return TacticalDecision(skip=True, reason="no weapons available")

        weapon = self._pick_weapon(creature, target, weapons, battle_map)

        # ── 3. Resolve strategy ────────────────────────────────────────
        # Priority: selector > externally-set current_strategy > rule-based
        # The selector is only applied to the trained team.  Without this
        # guard, a goblin Q-table attached to cm.ai would also control
        # Brendiir and Thando, making them fight like goblins.
        strategy = None
        team_matches = (
            self.trained_team is None or
            creature.team == self.trained_team
        )
        if self.strategy_selector is not None and memory is not None and team_matches:
            allies = [
                c for c in battle_map.all_creatures()
                if c.team == creature.team and c is not creature and c.is_alive()
            ]
            obs      = memory.get_state_vector(creature, enemies, allies)
            strategy = self.strategy_selector.select(obs)
            _log.debug("[%s] %s: ML strategy → %s", creature.team, creature.name, strategy)
        elif self.current_strategy is not None:
            strategy = self.current_strategy
            _log.debug("[%s] %s: fixed strategy → %s", creature.team, creature.name, strategy)

        # ── 4. Decide movement path ────────────────────────────────────
        path = []
        from core.ml_strategy import Strategy as Strat

        # Rule-based disengage safety net — applies regardless of which
        # strategy is active. Without this, attaching *any* selector (even
        # a poorly- or under-trained one) silently drops the baseline
        # protection that "no selector at all" gets for free: a selector-
        # driven creature would only retreat if the policy itself happens
        # to pick RETREAT at exactly the right moment. RETREAT already
        # reaches the same outcome via the branch below, so skip the
        # duplicate check in that case.
        if strategy != Strat.RETREAT and self._should_disengage(creature, battle_map):
            retreat_from = target
            if memory:
                scored = [(e, memory.threat_level(e)) for e in enemies]
                highest_threat = max(scored, key=lambda x: x[1])[0]
                if memory.threat_level(highest_threat) > 0:
                    retreat_from = highest_threat
            path = self._retreat_square(creature, retreat_from, battle_map)
            range_ok = battle_map.check_attack_range(
                creature, target,
                is_ranged=weapon.is_ranged,
                normal_range=weapon.normal_range,
                long_range=weapon.long_range,
            )
            if not range_ok:
                weapon = None
            _log.info(
                "[%s] %s: DISENGAGE from %s — hp %.0f%% (below %.0f%% threshold)",
                creature.team, creature.name, retreat_from.name,
                100 * creature.hp / max(creature.max_hp, 1),
                100 * self.DISENGAGE_THRESHOLD,
            )
            return TacticalDecision(
                target=target, path=path, weapon=weapon,
                reason="disengaging — low HP",
            )

        # RETREAT strategy — always disengage regardless of HP threshold
        if strategy is not None:
            if strategy == Strat.RETREAT:
                retreat_from = target
                if memory:
                    scored = [(e, memory.threat_level(e)) for e in enemies]
                    highest_threat = max(scored, key=lambda x: x[1])[0]
                    if memory.threat_level(highest_threat) > 0:
                        retreat_from = highest_threat
                path = self._retreat_square(creature, retreat_from, battle_map)
                range_ok = battle_map.check_attack_range(
                    creature, target,
                    is_ranged=weapon.is_ranged,
                    normal_range=weapon.normal_range,
                    long_range=weapon.long_range,
                )
                if not range_ok:
                    weapon = None
                _log.info(
                    "[%s] %s: RETREAT from %s — hp %.0f%%",
                    creature.team, creature.name, retreat_from.name,
                    100 * creature.hp / max(creature.max_hp, 1),
                )
                return TacticalDecision(
                    target=target, path=path, weapon=weapon,
                    reason=f"strategy: RETREAT",
                )
            elif strategy == Strat.AGGRESSIVE:
                # Respect the weapon type _pick_weapon already chose, same
                # as the no-strategy default below -- AGGRESSIVE means
                # "commit to this target," not "always close to melee."
                # Forcing melee unconditionally used to march ranged
                # attackers into range they didn't need to give up, which
                # is why AGGRESSIVE (the strategy this policy leans on
                # most) could underperform even the plain default AI.
                if weapon.is_ranged:
                    path = self._ranged_move(creature, target, weapon, battle_map)
                else:
                    path = self._melee_move(creature, target, battle_map)
            elif strategy == Strat.KITE:
                path = self._ranged_move(creature, target, weapon, battle_map)
            elif strategy == Strat.FOCUS_FIRE:
                # Ignore distance — charge the lowest-HP enemy to finish them fast
                focus_target = min(enemies, key=lambda e: e.hp)
                path         = self._melee_move(creature, focus_target, battle_map)
                target       = focus_target
            elif strategy == Strat.PROTECT:
                # Move to support the most-pressured living ally
                under_pressure = [
                    c for c in battle_map.all_creatures()
                    if c.team == creature.team
                    and c is not creature
                    and c.is_alive()
                    and memory
                    and memory.ally_under_pressure(c)
                ]
                if under_pressure:
                    ally_to_help = min(under_pressure, key=lambda a: a.hp)
                    ally_pos     = battle_map.get_position(ally_to_help)
                    origin_c     = battle_map.get_position(creature)
                    if origin_c and ally_pos:
                        path = self._path_toward(
                            origin_c, ally_pos, creature.speed, battle_map,
                            creature=creature, stop_adjacent=True
                        )
            # After strategy overrides movement, still fall through to dash check

        # Default movement when no strategy overrides (or strategy is AGGRESSIVE/KITE
        # but path is still empty because we didn't enter those branches)
        if not path:
            if weapon.is_ranged:
                path = self._ranged_move(creature, target, weapon, battle_map)
            else:
                path = self._melee_move(creature, target, battle_map)
            if path:
                dest = path[-1]
                target_pos = battle_map.get_position(target)
                if target_pos:
                    dist_after = max(
                        abs(dest[0] - target_pos[0]),
                        abs(dest[1] - target_pos[1]),
                    ) * 5
                    if dist_after > weapon.normal_range:
                        # Still out of range after moving — null weapon so
                        # no attack action is spent, but keep the path so
                        # the creature keeps advancing each turn.
                        weapon = None

        # ── 4. Dash / Dodge when target is out of reach ──────────
        use_dash  = False
        use_dodge = False

        if weapon is None:
            origin     = battle_map.get_position(creature)
            target_pos = battle_map.get_position(target)

            # Ensure we have a normal-speed advance path.
            if not path and not any(w.is_ranged for w in weapons):
                if origin and target_pos:
                    path = self._path_toward(
                        origin, target_pos, creature.speed, battle_map,
                        creature=creature, stop_adjacent=True
                    )

            if self._can_reach_with_dash(creature, target, battle_map):
                # Dash gets us adjacent this turn — always worth it.
                use_dash = True
                path     = self._melee_move_dashed(creature, target, battle_map)
                if path and target_pos:
                    dest = path[-1]
                    for w in weapons:
                        dist_after = max(
                            abs(dest[0] - target_pos[0]),
                            abs(dest[1] - target_pos[1]),
                        ) * 5
                        if dist_after <= w.normal_range:
                            weapon = w
                            break
            elif origin and target_pos:
                # Cannot reach even with a Dash.  Compare how far a dash
                # path goes vs normal movement.  If dashing covers at least
                # one extra square, spend the action dashing to advance
                # faster.  Otherwise take Dodge — imposing disadvantage on
                # incoming attacks is more useful than an empty action when
                # a wall or terrain is blocking progress this turn.
                dash_path      = self._path_toward(
                    origin, target_pos, creature.speed * 2, battle_map,
                    creature=creature, stop_adjacent=True
                )
                if len(dash_path) > len(path):
                    use_dash = True
                    path     = dash_path
                else:
                    # Dashing adds no extra squares — Dodge instead.
                    use_dodge = True

        reason = "standard attack"
        if use_dash:  reason = "dash to close distance"
        if use_dodge: reason = "dodge — can't reach target"

        _log.info(
            "[%s] %s → target: %s | weapon: %s | action: %s | move: %d steps",
            creature.team, creature.name,
            target.name if target else "none",
            weapon.name if weapon else "none",
            reason,
            len(path),
        )

        return TacticalDecision(
            target=target,
            path=path,
            weapon=weapon,
            use_dash=use_dash,
            use_dodge=use_dodge,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Hit probability and damage helpers
    # ------------------------------------------------------------------

    def _hit_probability(
        self,
        weapon: "WeaponProfile",
        target,
        advantage: bool = False,
        disadvantage: bool = False,
    ) -> float:
        """
        P(hit) against target's AC given weapon's total attack bonus.
        Advantage/disadvantage are applied combinatorially per 5e rules.
        Clamped to [0.05, 0.95]: a 1 always misses, a 20 always hits.
        """
        needed       = target.ac - weapon.attack_bonus
        p_straight   = (21 - max(1, min(20, needed))) / 20.0
        if advantage and not disadvantage:
            return 1.0 - (1.0 - p_straight) ** 2
        if disadvantage and not advantage:
            return p_straight ** 2
        return max(0.05, min(0.95, p_straight))

    def _expected_damage(self, weapon: "WeaponProfile") -> float:
        """
        Expected damage per successful hit = avg die roll + damage modifier.
        Parses weapon.damage_die string (e.g. '2d6').
        """
        try:
            num, sides = weapon.damage_die.split("d")
            avg_roll   = int(num) * (int(sides) + 1) / 2.0
        except (ValueError, AttributeError):
            avg_roll = 3.5   # fallback: 1d6 average
        return avg_roll + weapon.damage_mod

    def _best_hit_probability(
        self,
        creature,
        target,
        battle_map,
    ) -> float:
        """
        Hit probability of the creature's best in-range weapon against target,
        accounting for ranged disadvantage from melee proximity.
        Returns 0.0 if no weapon can reach the target.
        """
        weapons = self._get_weapon_profiles(creature)
        best    = 0.0
        for w in weapons:
            rr = battle_map.check_attack_range(
                creature, target,
                is_ranged=w.is_ranged,
                normal_range=w.normal_range,
                long_range=w.long_range,
            )
            if not rr.valid:
                continue
            best = max(best, self._hit_probability(
                w, target, disadvantage=rr.disadvantage
            ))
        return best

    # ------------------------------------------------------------------
    # Target selection
    # ------------------------------------------------------------------

    def _pick_target(
        self,
        creature: Creature,
        enemies: list,
        battle_map: BattleMap,
        memory=None,
    ) -> object:
        """
        Focus the recommended target from TeamMemory if available.
        Memory prioritises: already-focused enemies → highest threat score.
        Fallback (no memory): weakest HP, tiebreak closest.
        """
        if memory:
            recommended = memory.recommended_target(enemies)
            if recommended is not None:
                return recommended

        # Fallback: melee-only creatures chase the closest enemy so they
        # advance on a reachable target rather than fixating on a low-HP
        # enemy a ranged ally is already finishing across the map.
        # Ranged creatures keep weakest-first since distance is less relevant.
        weapons = self._get_weapon_profiles(creature)
        has_ranged = any(w.is_ranged for w in weapons)

        def priority(enemy):
            try:
                dist = battle_map.distance_between(creature, enemy)
            except LookupError:
                dist = 9999
            if has_ranged:
                return (enemy.hp, dist)   # weakest first, tiebreak closest
            return (dist, enemy.hp)        # closest first, tiebreak weakest

        chosen = min(enemies, key=priority)
        _log.info(
            "[%s] %s: no memory — fallback target %s (hp %d/%d)",
            creature.team, creature.name, chosen.name, chosen.hp, chosen.max_hp,
        )
        return chosen

    # ------------------------------------------------------------------
    # Weapon selection
    # ------------------------------------------------------------------

    def _get_weapon_profiles(self, creature: Creature) -> list[WeaponProfile]:
        """
        Build WeaponProfile list from creature's equipped items.
        Falls back to checking creature.attacks (raw monster attack dicts)
        for monsters built from the MONSTER_REGISTRY template.
        """
        profiles = []

        # Equipped item weapons
        for item in creature.equipped_items:
            if item.item_type != "weapon":
                continue
            is_ranged    = getattr(item, "attack_type", "melee") == "range"
            normal_range, long_range = self._parse_item_range(item, is_ranged)
            # Compute the full to-hit modifier the same way Attack.__init__ does
            # so that hit_probability calculations are accurate for item weapons.
            ability   = getattr(item, "ability", "Str")
            atk_bonus = (
                creature.statblock.mods.get(ability, 0)
                + getattr(item, "attack_bonus", 0)
                + creature.proficiency
            )
            dmg_bonus = (
                creature.statblock.mods.get(ability, 0)
                + getattr(item, "damage_bonus", 0)
            )
            profiles.append(WeaponProfile(
                name=item.name,
                is_ranged=is_ranged,
                normal_range=normal_range,
                long_range=long_range,
                item=item,
                attack_bonus=atk_bonus,
                damage_die=getattr(item, "damage_die", "1d6"),
                damage_mod=dmg_bonus,
            ))

        # Raw monster attack list (for creatures built from templates)
        raw_attacks = getattr(creature, "_attack_templates", [])
        for atk in raw_attacks:
            is_ranged = atk.get("attack_type", "melee") == "range"
            normal_range = atk.get("normal_range", 150 if is_ranged else 5)
            long_range = atk.get("long_range", 600 if is_ranged else 5)
            profiles.append(WeaponProfile(
                name=atk["name"],
                is_ranged=is_ranged,
                normal_range=normal_range,
                long_range=long_range,
                attack_bonus=atk.get("attack_bonus", 0),
                damage_die=f"1d{atk.get('damage_die', 6)}",
                damage_mod=atk.get("damage_mod", 0),
            ))

        return profiles

    def _parse_item_range(self, item, is_ranged: bool) -> tuple[int, int]:
        """Extract normal/long range from an item. Defaults to 5/5 for melee."""
        if not is_ranged:
            return 5, 5
        normal = getattr(item, "normal_range", 80)
        long = getattr(item, "long_range", 320)
        return normal, long

    def _score_weapon(
        self,
        weapon: WeaponProfile,
        target,
        dist: float,
        is_concentrating: bool,
    ) -> float:
        """
        Expected useful DPR for weapon against target, with situational modifiers.

        Base score  = P(hit) × avg_damage
        Modifiers:
          - ×1.5 ranged bonus when the creature is concentrating on a spell
            (staying at range reduces melee hit risk and protects concentration)
          - ×1.2 ranged bonus when target is beyond melee reach
        """
        try:
            num, sides = weapon.damage_die.split("d")
            avg = int(num) * (int(sides) + 1) / 2.0 + weapon.damage_mod
        except (ValueError, AttributeError):
            avg = 5.0
        avg = max(avg, 0.0)

        # Advantage from target conditions: paralyzed/restrained/blinded/stunned
        _hc = getattr(target, "has_condition", None)
        has_advantage = bool(_hc) and (
            _hc("paralyzed") or _hc("restrained") or _hc("blinded") or _hc("stunned")
        )

        p_straight = hit_probability(weapon.attack_bonus, target.ac)
        p_hit      = (1.0 - (1.0 - p_straight) ** 2) if has_advantage else p_straight
        score      = p_hit * avg

        if weapon.is_ranged and is_concentrating:
            score *= 1.5   # protect concentration — stay out of melee
        if weapon.is_ranged and dist > 5:
            score *= 1.2   # ranged weapon naturally better at range

        return score

    def _pick_weapon(
        self,
        creature: Creature,
        target: Creature,
        weapons: list[WeaponProfile],
        battle_map: BattleMap,
    ) -> WeaponProfile:
        """
        Choose the highest-value weapon for the current situation.

        Candidates are split into clean (no disadvantage) and dirty (disadvantage)
        pools; clean always preferred. Within each pool the weapon with the highest
        _score_weapon value wins, which accounts for:
          - Expected DPR (P(hit) × average damage vs target AC)
          - Concentration protection (ranged gets a boost when caster is concentrating)
          - Range preference (ranged boosted when target is beyond melee reach)
        """
        try:
            dist = battle_map.distance_between(creature, target)
        except LookupError:
            dist = 0

        is_concentrating = bool(getattr(creature, "concentration", None))

        clean_options: list[WeaponProfile] = []
        any_options:   list[WeaponProfile] = []

        for w in weapons:
            result = battle_map.check_attack_range(
                creature, target,
                is_ranged=w.is_ranged,
                normal_range=w.normal_range,
                long_range=w.long_range,
            )
            if result.valid and not result.disadvantage:
                clean_options.append(w)
            elif result.valid:
                any_options.append(w)

        pool = clean_options or any_options
        cname = getattr(creature, "name", "?")
        tname = getattr(target,   "name", "?")
        if pool:
            scored = [
                (w, self._score_weapon(w, target, dist, is_concentrating))
                for w in pool
            ]
            _log.debug(
                "[%s] weapon scores vs %s (dist=%.0fft%s): %s",
                cname, tname, dist,
                " [concentrating]" if is_concentrating else "",
                ", ".join(f"{w.name}={s:.1f}" for w, s in scored),
            )
            chosen, best = max(scored, key=lambda x: x[1])
            _hc = getattr(target, "has_condition", None)
            adv = _hc and (_hc("paralyzed") or _hc("restrained") or _hc("blinded"))
            _log.info(
                "[%s] picks %s (score=%.1f%s) vs %s",
                cname, chosen.name, best,
                " [advantage]" if adv else "",
                tname,
            )
            return chosen

        _log.debug("[%s] no in-range weapon — falling back to %s", cname, weapons[0].name)
        return weapons[0]   # fallback — CombatManager will handle out-of-range

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def _melee_move(
        self,
        creature: Creature,
        target: Creature,
        battle_map: BattleMap,
    ) -> list[tuple[int, int]]:
        """
        Return the path toward target within the creature's speed budget (feet).
        Stops one square away (melee). Returns [] if already adjacent.
        """
        if battle_map.is_in_melee_range(creature, target):
            return []
        origin = battle_map.get_position(creature)
        target_pos = battle_map.get_position(target)
        if not origin or not target_pos:
            return []
        return self._path_toward(
            origin, target_pos, creature.speed, battle_map,
            creature=creature, stop_adjacent=True
        )

    def _ranged_move(
        self,
        creature: Creature,
        target: Creature,
        weapon: WeaponProfile,
        battle_map: BattleMap,
    ) -> list[tuple[int, int]]:
        """
        Return the path to maintain optimal ranged distance.
        - Back away if enemy is adjacent
        - Close in if target is beyond normal range
        - Stay put otherwise (empty path)
        """
        origin = battle_map.get_position(creature)
        target_pos = battle_map.get_position(target)
        if not origin or not target_pos:
            return []

        try:
            dist_ft = battle_map.distance_between(creature, target)
        except LookupError:
            return []

        # Back away if enemy is adjacent
        if battle_map._attacker_is_in_melee(creature):
            dest = self._step_away(
                origin, target_pos, creature.speed // 5, battle_map
            )
            if dest == origin:
                return []
            return self._path_toward(
                origin, dest, creature.speed, battle_map,
                creature=creature, stop_adjacent=False
            )

        # Close in if beyond normal range.
        # stop_adjacent=True so the goblin stops one square away from the
        # target rather than trying to land on their square.
        if dist_ft > weapon.normal_range:
            return self._path_toward(
                origin, target_pos, creature.speed, battle_map,
                creature=creature, stop_adjacent=True
            )

        return []   # already at good distance

    def _retreat_square(
        self,
        creature: Creature,
        threat: Creature,
        battle_map: BattleMap,
    ) -> list[tuple[int, int]]:
        """Return path moving away from the primary threat."""
        origin = battle_map.get_position(creature)
        threat_pos = battle_map.get_position(threat)
        if not origin or not threat_pos:
            return []
        dest = self._step_away(origin, threat_pos, creature.speed // 5, battle_map)
        if dest == origin:
            return []
        return self._path_toward(
            origin, dest, creature.speed, battle_map,
            creature=creature, stop_adjacent=False
        )

    def _can_reach_with_dash(
        self,
        creature,
        target,
        battle_map,
    ) -> bool:
        """
        Return True if spending the action on Dash (double speed) would
        bring the creature into melee range of target this turn.
        Uses cost-aware pathfinding so difficult terrain is respected.
        """
        origin = battle_map.get_position(creature)
        target_pos = battle_map.get_position(target)
        if not origin or not target_pos:
            return False
        path = self._path_toward(
            origin, target_pos, creature.speed * 2, battle_map,
            creature=creature, stop_adjacent=True
        )
        if not path:
            return False
        dest = path[-1]
        dist_after = max(abs(dest[0] - target_pos[0]),
                         abs(dest[1] - target_pos[1])) * 5
        return dist_after <= 5

    def _melee_move_dashed(
        self,
        creature,
        target,
        battle_map,
    ) -> list[tuple[int, int]]:
        """Return the path using double speed (Dash action)."""
        origin = battle_map.get_position(creature)
        target_pos = battle_map.get_position(target)
        if not origin or not target_pos:
            return []
        return self._path_toward(
            origin, target_pos, creature.speed * 2, battle_map,
            creature=creature, stop_adjacent=True
        )

    # ------------------------------------------------------------------
    # Pathfinding helpers
    # ------------------------------------------------------------------

    def _path_toward(
        self,
        origin: tuple[int, int],
        dest: tuple[int, int],
        budget_ft: int,
        battle_map,
        creature=None,
        stop_adjacent: bool = True,
    ) -> list[tuple[int, int]]:
        """
        Dijkstra pathfinding from origin toward dest within budget_ft feet.

        Returns the list of squares walked (NOT including origin), up to the
        movement budget. Each square's terrain cost is charged in feet so
        difficult terrain (10ft/sq) correctly limits range.

        Diagonal preference: cardinal moves are preferred over diagonals when
        the terrain cost is otherwise equal. A tiny secondary key (0.001 *
        diagonal_count) is added to the heap priority so Dijkstra picks
        straight paths when there is a tie.

        Occupied squares: allies are treated as passable (you can path through
        a teammate's square) but cannot end your move on an occupied square.
        Enemy squares are impassable unless they are the destination.

        - stop_adjacent=True  stop one square away (melee approach)
        - stop_adjacent=False  try to reach dest exactly (ranged/retreat)
        """
        import heapq

        stop_threshold = 1 if stop_adjacent else 0

        # Already at stop condition
        cur_dist = max(abs(origin[0] - dest[0]), abs(origin[1] - dest[1]))
        if cur_dist <= stop_threshold:
            return []

        # Determine the mover's team for ally/enemy distinction
        mover_team = getattr(creature, "team", None) if creature else None

        # Dijkstra state: (terrain_cost, diagonal_tiebreak, position, path)
        heap = [(0, 0, origin, [])]
        # visited maps pos -> (best_terrain_cost, best_diag_count)
        visited: dict[tuple, tuple] = {}

        best_path = []
        best_dist = cur_dist
        best_key  = (float("inf"), float("inf"))

        while heap:
            cost, diag, pos, path = heapq.heappop(heap)

            key = (cost, diag)
            if pos in visited and visited[pos] <= key:
                continue
            visited[pos] = key

            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    if dc == 0 and dr == 0:
                        continue
                    nc, nr = pos[0] + dc, pos[1] + dr
                    npos = (nc, nr)

                    if not battle_map._in_bounds(nc, nr):
                        continue
                    tile = battle_map.get_tile(nc, nr)
                    if not tile.passable:
                        continue

                    # Diagonal corner-clip check: a diagonal move is only
                    # legal if BOTH cardinal neighbours are passable.
                    # Without this, creatures cut through wall corners.
                    if dc != 0 and dr != 0:
                        if not battle_map._in_bounds(pos[0]+dc, pos[1]) or \
                           not battle_map.get_tile(pos[0]+dc, pos[1]).passable:
                            continue
                        if not battle_map._in_bounds(pos[0], pos[1]+dr) or \
                           not battle_map.get_tile(pos[0], pos[1]+dr).passable:
                            continue

                    # Occupied square handling:
                    #   - destination is always allowed
                    #   - ally squares: can path THROUGH but not end on
                    #   - enemy squares: impassable
                    occupant = battle_map.get_creature_at(nc, nr)
                    if occupant is not None and npos != dest:
                        if mover_team and occupant.team != mover_team:
                            continue   # enemy — blocked
                        # ally — can pass through but track that we can't stop here

                    # Terrain cost in feet
                    sq_cost = battle_map.movement_cost_to(creature, nc, nr) if creature else tile.movement_cost
                    new_cost = cost + sq_cost

                    if new_cost > budget_ft:
                        continue   # over budget
                    new_diag = diag + (1 if dc != 0 and dr != 0 else 0)
                    new_key  = (new_cost, new_diag)

                    if npos in visited and visited[npos] <= new_key:
                        continue

                    new_path = path + [npos]
                    d = max(abs(nc - dest[0]), abs(nr - dest[1]))

                    # Can only stop here if the square is genuinely unoccupied.
                    # Removing the "or npos == dest" exemption: that exemption
                    # was intended to allow routing through the target area but
                    # it also allowed creatures to LAND on occupied squares
                    # (including the enemy's own square for KITE close-in and
                    # any ally square chosen as a retreat destination).
                    # Routing through dest for adjacency is still handled by
                    # the occupant-blocking guard above (which skips the block
                    # when npos==dest so Dijkstra can expand through it).
                    can_stop = (occupant is None)

                    # Track the best reachable stopping square within budget
                    if can_stop:
                        if d < best_dist or (d == best_dist and new_key < best_key):
                            best_dist = d
                            best_path = new_path
                            best_key  = new_key

                    # Reached stop condition on a stoppable square
                    if d <= stop_threshold and can_stop:
                        return new_path

                    heapq.heappush(heap, (new_cost, new_diag, npos, new_path))

        return best_path

    def _step_toward(
        self,
        origin: tuple[int, int],
        dest: tuple[int, int],
        max_steps: int,
        battle_map,
        stop_adjacent: bool = True,
    ) -> tuple[int, int]:
        """
        Legacy single-destination wrapper around _path_toward.
        max_steps is treated as a budget in squares (×5 = feet).
        Returns the final square in the path, or origin if no path.
        """
        path = self._path_toward(
            origin, dest, max_steps * 5, battle_map,
            stop_adjacent=stop_adjacent
        )
        return path[-1] if path else origin

    def _step_away(
        self,
        origin: tuple[int, int],
        threat: tuple[int, int],
        max_steps: int,
        battle_map: BattleMap,
    ) -> tuple[int, int]:
        """
        Greedy step-by-step movement away from threat.
        Each step picks the passable neighbour that maximises
        Chebyshev distance from threat.
        """
        pos = origin
        for _ in range(max_steps):
            current_dist = max(
                abs(pos[0] - threat[0]),
                abs(pos[1] - threat[1])
            )
            best_next = None
            best_dist = current_dist

            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    if dc == 0 and dr == 0:
                        continue
                    nc, nr = pos[0] + dc, pos[1] + dr
                    if not battle_map._in_bounds(nc, nr):
                        continue
                    tile = battle_map.get_tile(nc, nr)
                    if not tile.passable:
                        continue
                    if battle_map.get_creature_at(nc, nr) is not None:
                        continue
                    d = max(abs(nc - threat[0]), abs(nr - threat[1]))
                    if d > best_dist:
                        best_dist = d
                        best_next = (nc, nr)

            if best_next is None:
                break
            pos = best_next

        return pos

    # ------------------------------------------------------------------
    # Disengage check
    # ------------------------------------------------------------------

    def _should_disengage(
        self, creature: Creature, battle_map: BattleMap
    ) -> bool:
        """
        Retreat if below DISENGAGE_THRESHOLD HP and at least one ally
        is still alive (so the retreat isn't pointless).
        """
        hp_fraction = creature.hp / creature.max_hp if creature.max_hp > 0 else 1
        if hp_fraction >= self.DISENGAGE_THRESHOLD:
            return False
        # Check for living allies
        allies = [
            c for c in battle_map.all_creatures()
            if c.team == creature.team and c is not creature and c.is_alive()
        ]
        return len(allies) > 0