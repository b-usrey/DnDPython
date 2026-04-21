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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.creature import Creature
    from core.battle_map import BattleMap


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
        move_to=None,
        weapon=None,
        skip: bool = False,
        reason: str = "",
        use_dash: bool = False,
    ):
        self.target   = target
        self.move_to  = move_to
        self.weapon   = weapon
        self.skip     = skip
        self.reason   = reason
        self.use_dash = use_dash   # spend action to double movement this turn

    def __repr__(self):
        if self.skip:
            return f"TacticalDecision(skip, reason={self.reason!r})"
        dash_str = " [DASH]" if self.use_dash else ""
        return (
            f"TacticalDecision("
            f"target={self.target.name if self.target else None!r}, "
            f"move_to={self.move_to}, "
            f"weapon={self.weapon.name if self.weapon else None!r}"
            f"{dash_str})"
        )


# ---------------------------------------------------------------------------
# TacticalAI
# ---------------------------------------------------------------------------

class TacticalAI:
    """
    Tactical AI controller. Instantiate once and call plan_turn() each turn.

    Tactical logic:
      - Focus the weakest enemy (lowest current HP) — reduces the number
        of incoming attacks fastest
      - Use ranged weapon when target is beyond melee reach and we have one
      - Move toward target if using melee (close the gap)
      - Maintain optimal ranged distance if using ranged (stay at normal_range,
        back away if enemy closes in)
      - Disengage logic: if below 25% HP and an ally is alive, move away
        from the strongest threat instead of attacking
    """

    DISENGAGE_THRESHOLD = 0.25   # fraction of max HP below which we consider retreating
    KITE_DISTANCE = 3             # squares — preferred distance when kiting ranged

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
            return TacticalDecision(skip=True, reason="creature is dead")

        if creature.has_condition("incapacitated") or creature.has_condition("unconscious"):
            return TacticalDecision(skip=True, reason=f"creature is {list(creature.conditions)}")

        enemies = battle_map.enemies_of(creature)
        if not enemies:
            return TacticalDecision(skip=True, reason="no enemies on map")

        # ── 1. Pick target ─────────────────────────────────────────────
        target = self._pick_target(creature, enemies, battle_map, memory)

        # ── 2. Pick weapon ─────────────────────────────────────────────
        weapons = self._get_weapon_profiles(creature)
        if not weapons:
            return TacticalDecision(skip=True, reason="no weapons available")

        weapon = self._pick_weapon(creature, target, weapons, battle_map)

        # ── 3. Decide movement ─────────────────────────────────────────
        move_to = None

        # Disengage check — badly hurt and there's an ally still up
        # With memory: also retreat from the highest-threat enemy, not just target
        if self._should_disengage(creature, battle_map):
            # If we have memory, retreat from the most dangerous enemy
            retreat_from = target
            if memory:
                scored = [(e, memory.threat_level(e)) for e in enemies]
                highest_threat = max(scored, key=lambda x: x[1])[0]
                if memory.threat_level(highest_threat) > 0:
                    retreat_from = highest_threat
            move_to = self._retreat_square(creature, retreat_from, battle_map)
            range_ok = battle_map.check_attack_range(
                creature, target,
                is_ranged=weapon.is_ranged,
                normal_range=weapon.normal_range,
                long_range=weapon.long_range,
            )
            if not range_ok:
                weapon = None
            return TacticalDecision(
                target=target,
                move_to=move_to,
                weapon=weapon,
                reason="disengaging — low HP",
            )

        if weapon.is_ranged:
            move_to = self._ranged_move(creature, target, weapon, battle_map)
        else:
            move_to = self._melee_move(creature, target, battle_map)
            if move_to is not None:
                target_pos = battle_map.get_position(target)
                if target_pos:
                    dist_after = max(
                        abs(move_to[0] - target_pos[0]),
                        abs(move_to[1] - target_pos[1]),
                    ) * 5
                    if dist_after > weapon.normal_range:
                        weapon = None

        # ── 4. Dash if no weapon can reach after normal movement ────────
        use_dash = False

        if weapon is None:
            if self._can_reach_with_dash(creature, target, battle_map):
                use_dash = True
                move_to  = self._melee_move_dashed(creature, target, battle_map)
                # Re-check weapon reach after dashing
                for w in weapons:
                    target_pos = battle_map.get_position(target)
                    if move_to and target_pos:
                        dist_after = max(
                            abs(move_to[0] - target_pos[0]),
                            abs(move_to[1] - target_pos[1]),
                        ) * 5
                        if dist_after <= w.normal_range:
                            weapon = w
                            break

        reason = "standard attack"
        if use_dash: reason = "dash to close distance"

        return TacticalDecision(
            target=target,
            move_to=move_to,
            weapon=weapon,
            use_dash=use_dash,
            reason=reason,
        )

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

        # Original fallback — weakest enemy, tiebreak closest
        def priority(enemy):
            hp = enemy.hp
            try:
                dist = battle_map.distance_between(creature, enemy)
            except LookupError:
                dist = 9999
            return (hp, dist)

        return min(enemies, key=priority)

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
            is_ranged = getattr(item, "attack_type", "melee") == "range"
            # Parse range from item properties if present
            normal_range, long_range = self._parse_item_range(item, is_ranged)
            profiles.append(WeaponProfile(
                name=item.name,
                is_ranged=is_ranged,
                normal_range=normal_range,
                long_range=long_range,
                item=item,
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

    def _pick_weapon(
        self,
        creature: Creature,
        target: Creature,
        weapons: list[WeaponProfile],
        battle_map: BattleMap,
    ) -> WeaponProfile:
        """
        Choose the best weapon for the situation.

        Preference order:
          1. Any weapon that can hit the target without disadvantage
          2. Any weapon that can hit at all (even with disadvantage)
          3. Fallback to first available weapon
        """
        try:
            dist = battle_map.distance_between(creature, target)
        except LookupError:
            dist = 0

        clean_options = []
        any_options = []

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

        if clean_options:
            # Among clean options, prefer ranged if target is far
            if dist > 5:
                ranged = [w for w in clean_options if w.is_ranged]
                if ranged:
                    return ranged[0]
            return clean_options[0]

        if any_options:
            return any_options[0]

        return weapons[0]   # fallback — CombatManager will handle out-of-range

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def _melee_move(
        self,
        creature: Creature,
        target: Creature,
        battle_map: BattleMap,
    ) -> tuple[int, int] | None:
        """
        Move as close as possible to the target within the creature's speed,
        stopping one square away (adjacent) if possible.
        Returns the destination square, or None if already adjacent.
        """
        if battle_map.is_in_melee_range(creature, target):
            return None   # already in melee, no need to move

        origin = battle_map.get_position(creature)
        target_pos = battle_map.get_position(target)
        if not origin or not target_pos:
            return None

        speed_squares = creature.speed // 5
        best = self._step_toward(
            origin, target_pos, speed_squares, battle_map, stop_adjacent=True
        )
        return best if best != origin else None

    def _ranged_move(
        self,
        creature: Creature,
        target: Creature,
        weapon: WeaponProfile,
        battle_map: BattleMap,
    ) -> tuple[int, int] | None:
        """
        Maintain optimal ranged distance.

        - If an enemy is adjacent (in melee): back away to KITE_DISTANCE squares
        - If target is beyond normal range: close until within normal range
        - Otherwise: stay put
        """
        origin = battle_map.get_position(creature)
        target_pos = battle_map.get_position(target)
        if not origin or not target_pos:
            return None

        try:
            dist_squares = battle_map.distance_between(creature, target) // 5
        except LookupError:
            return None

        speed_squares = creature.speed // 5

        # Back away if enemy is adjacent
        if battle_map._attacker_is_in_melee(creature):
            best = self._step_away(
                origin, target_pos, speed_squares, battle_map
            )
            return best if best != origin else None

        # Close in if target is beyond normal range
        normal_squares = weapon.normal_range // 5
        if dist_squares > normal_squares:
            best = self._step_toward(
                origin, target_pos, speed_squares, battle_map, stop_adjacent=False
            )
            return best if best != origin else None

        return None   # already at good distance

    def _retreat_square(
        self,
        creature: Creature,
        threat: Creature,
        battle_map: BattleMap,
    ) -> tuple[int, int] | None:
        """Move away from the primary threat."""
        origin = battle_map.get_position(creature)
        threat_pos = battle_map.get_position(threat)
        if not origin or not threat_pos:
            return None
        speed_squares = creature.speed // 5
        best = self._step_away(origin, threat_pos, speed_squares, battle_map)
        return best if best != origin else None

    def _can_reach_with_dash(
        self,
        creature,
        target,
        battle_map,
    ) -> bool:
        """
        Return True if spending the action on Dash (double speed) would
        bring the creature into melee range of target this turn.
        """
        origin = battle_map.get_position(creature)
        target_pos = battle_map.get_position(target)
        if not origin or not target_pos:
            return False
        dash_squares = (creature.speed * 2) // 5
        dest = self._step_toward(origin, target_pos, dash_squares, battle_map,
                                 stop_adjacent=True)
        dist_after = max(abs(dest[0] - target_pos[0]),
                         abs(dest[1] - target_pos[1])) * 5
        return dist_after <= 5   # adjacent = in melee reach

    def _melee_move_dashed(
        self,
        creature,
        target,
        battle_map,
    ) -> tuple[int, int] | None:
        """
        Return the best destination using double speed (Dash action).
        """
        origin = battle_map.get_position(creature)
        target_pos = battle_map.get_position(target)
        if not origin or not target_pos:
            return None
        dash_squares = (creature.speed * 2) // 5
        best = self._step_toward(origin, target_pos, dash_squares, battle_map,
                                 stop_adjacent=True)
        return best if best != origin else None

    # ------------------------------------------------------------------
    # Pathfinding helpers
    # ------------------------------------------------------------------

    def _step_toward(
        self,
        origin: tuple[int, int],
        dest: tuple[int, int],
        max_steps: int,
        battle_map: BattleMap,
        stop_adjacent: bool = True,
    ) -> tuple[int, int]:
        """
        BFS pathfinding toward dest, following the path up to max_steps.

        Correctly navigates around walls and impassable terrain.
        If stop_adjacent=True, stops one square away (melee approach).
        If the destination is unreachable, moves as close as possible.
        Returns the final position after consuming up to max_steps moves.
        """
        from collections import deque

        # If already at the stop condition, return immediately
        cur_dist = max(abs(origin[0] - dest[0]), abs(origin[1] - dest[1]))
        stop_threshold = 1 if stop_adjacent else 0
        if cur_dist <= stop_threshold:
            return origin

        # BFS to find shortest path
        queue   = deque([(origin, [origin])])
        visited = {origin}

        best_pos  = origin      # fallback: best reachable square
        best_dist = cur_dist

        while queue:
            pos, path = queue.popleft()

            # Check neighbours
            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    if dc == 0 and dr == 0:
                        continue
                    nc, nr = pos[0] + dc, pos[1] + dr
                    npos = (nc, nr)
                    if npos in visited:
                        continue
                    if not battle_map._in_bounds(nc, nr):
                        continue
                    tile = battle_map.get_tile(nc, nr)
                    if not tile.passable:
                        continue
                    # Don't path through occupied squares (except destination)
                    occupant = battle_map.get_creature_at(nc, nr)
                    if occupant is not None and npos != dest:
                        continue

                    visited.add(npos)
                    new_path = path + [npos]
                    d = max(abs(nc - dest[0]), abs(nr - dest[1]))

                    # Track the best reachable square
                    if d < best_dist:
                        best_dist = d
                        best_pos  = npos

                    # If we've reached the stop condition, follow path up to max_steps
                    if d <= stop_threshold:
                        # Return the square max_steps along this path
                        # (new_path[0] is origin, new_path[1] is first step)
                        target_idx = min(max_steps, len(new_path) - 1)
                        return new_path[target_idx]

                    queue.append((npos, new_path))

                    # Cap BFS to avoid searching the entire map for huge maps
                    if len(visited) > 2000:
                        break
                else:
                    continue
                break

        # Destination unreachable — return max_steps along path toward best_pos
        if best_pos == origin:
            return origin

        # Re-run BFS just toward best_pos to get the path
        queue2  = deque([(origin, [origin])])
        visited2 = {origin}
        while queue2:
            pos, path = queue2.popleft()
            if pos == best_pos:
                target_idx = min(max_steps, len(path) - 1)
                return path[target_idx]
            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    if dc == 0 and dr == 0:
                        continue
                    nc, nr = pos[0] + dc, pos[1] + dr
                    npos = (nc, nr)
                    if npos in visited2:
                        continue
                    if not battle_map._in_bounds(nc, nr):
                        continue
                    if not battle_map.get_tile(nc, nr).passable:
                        continue
                    visited2.add(npos)
                    queue2.append((npos, path + [npos]))

        return origin

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