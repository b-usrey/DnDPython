"""
core/combat_manager.py

Runs the encounter loop. Owns the relationship between
InitiativeManager, BattleMap, and the AI/player controllers.

Two modes (toggled at any time via set_mode()):
  CombatMode.AUTO   — AI controls all creatures (good for simulation/testing)
  CombatMode.PLAYER — Player input for blue-team PCs, AI for everything else

Usage:
    cm = CombatManager(event, initiative, battle_map)
    cm.set_mode(CombatMode.PLAYER)   # optional, AUTO is default
    cm.run()

The encounter ends when one side has no living creatures.
"""

from __future__ import annotations

import enum

from core.tactical_ai import TacticalAI, WeaponProfile
from core.attack import WeaponAttack
from core.team_memory import TeamMemory


# ---------------------------------------------------------------------------
# CombatMode
# ---------------------------------------------------------------------------

class CombatMode(enum.Enum):
    AUTO   = "auto"    # all creatures AI-controlled
    PLAYER = "player"  # blue team prompts for input


# ---------------------------------------------------------------------------
# CombatManager
# ---------------------------------------------------------------------------

class CombatManager:
    """
    Orchestrates a full encounter from first round to last.

    Args:
        event:       shared EventBus
        initiative:  InitiativeManager (already populated with creatures)
        battle_map:  BattleMap (creatures already placed)
        mode:        CombatMode.AUTO or CombatMode.PLAYER (default: AUTO)
        max_rounds:  safety cap to prevent infinite loops (default: 100)
    """

    def __init__(self, event, initiative, battle_map, mode=CombatMode.AUTO, max_rounds=100):
        self.event = event
        self.initiative = initiative
        self.battle_map = battle_map
        self.mode = mode
        self.max_rounds = max_rounds
        self.ai = TacticalAI()

        # Subscribe to creature_downed so we can prune the initiative order
        self.event.subscribe("creature_downed", self._on_creature_downed)

        # Create one TeamMemory per team — works for any number of teams
        self.memories: dict[str, TeamMemory] = TeamMemory.create_for_all_teams(
            battle_map, event
        )
        print(f"  [TeamMemory] Tracking teams: {list(self.memories.keys())}")

    def set_mode(self, mode: CombatMode) -> None:
        self.mode = mode
        print(f"\n[CombatManager] Mode set to: {mode.value.upper()}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> str:
        """
        Run the encounter until one side is eliminated or max_rounds is hit.
        Returns a string describing the outcome.
        """
        print("\n" + "=" * 52)
        print("  COMBAT BEGINS")
        print("=" * 52)

        self.initiative.roll_initiative()
        self._print_initiative_order()

        # Broadcast CombatStarted without calling initiative.start_combat()
        # (start_combat also calls start_turn which spuriously fires TurnStarted
        # before _run_turn gets to handle it properly)
        self.event.broadcast("CombatStarted", {"round": self.initiative.round})

        for _ in range(self.max_rounds):
            if not self._combat_continues():
                break
            self._run_round()

        return self._resolve_outcome()

    def _run_round(self) -> None:
        """Execute one full round — every creature in initiative order gets a turn."""
        active = [c for _, c in self.initiative.initiative_order if c.is_alive()]
        print(f"\n{'─'*52}")
        print(f"  Round {self.initiative.round}")
        print(f"{'─'*52}")

        for _, creature in list(self.initiative.initiative_order):
            if not creature.is_alive():
                continue
            if not self._combat_continues():
                break
            self._run_turn(creature)

        self.initiative.round += 1

    def _run_turn(self, creature) -> None:
        """Execute one creature's full turn."""
        print(f"\n  >> {creature.name}'s turn  "
              f"(HP: {creature.hp}/{creature.max_hp}  AC: {creature.ac})")

        creature.start_turn()
        self.event.broadcast("TurnStarted", {
            "round": self.initiative.round,
            "creature": creature,
        })

        if self._is_player_turn(creature):
            self._run_player_turn(creature)
        else:
            self._run_ai_turn(creature)

        self.event.broadcast("TurnEnded", {
            "round": self.initiative.round,
            "creature": creature,
        })

    # ------------------------------------------------------------------
    # Player turn
    # ------------------------------------------------------------------

    def _run_player_turn(self, creature) -> None:
        """
        Prompt the player for actions. Loop until they end their turn.
        Available actions: move, attack, info, skip, auto (hand off to AI).
        """
        print(f"\n  Your turn, {creature.name}!")
        remaining_movement = creature.speed

        while True:
            self._print_player_prompt(creature, remaining_movement)
            raw = input("  > ").strip().lower()
            parts = raw.split()
            cmd = parts[0] if parts else ""

            if cmd in ("end", "done", "skip", ""):
                break

            elif cmd == "auto":
                print("  [Handing turn to AI...]")
                self._run_ai_turn(creature)
                break

            elif cmd == "map":
                self.battle_map.print_grid()

            elif cmd == "info":
                self._print_combat_info(creature)

            elif cmd == "move":
                if len(parts) < 3:
                    print("  Usage: move <col> <row>")
                    continue
                try:
                    col, row = int(parts[1]), int(parts[2])
                except ValueError:
                    print("  Col and row must be integers.")
                    continue
                cost = self._try_move(creature, col, row, remaining_movement)
                if cost is not None:
                    remaining_movement -= cost

            elif cmd == "dash":
                if not creature.actions.use_action():
                    print("  No actions remaining.")
                    continue
                remaining_movement += creature.speed
                print(f"  {creature.name} uses Dash "
                      f"(+{creature.speed}ft, {remaining_movement}ft remaining)")

            elif cmd == "attack":
                if not creature.actions.use_action():
                    print("  No actions remaining.")
                    continue
                target = self._prompt_target(creature)
                if target:
                    weapon = self._prompt_weapon(creature)
                    self._do_attack_action(creature, target, weapon)
                else:
                    creature.actions.actions += 1  # refund

            elif cmd == "surge":
                if not creature.actions.use_action_surge():
                    print("  No Action Surge available.")
                    continue
                print(f"  {creature.name} uses Action Surge!")
                target = self._prompt_target(creature)
                if target:
                    weapon = self._prompt_weapon(creature)
                    self._do_attack_action(creature, target, weapon)
                else:
                    # Refund — no good target
                    creature.actions.actions += 1

            else:
                surge_str = " | surge" if creature.actions.can_surge else ""
                print(f"  Commands: move <col> <row> | attack | dash{surge_str} | map | info | auto | end")

    def _print_player_prompt(self, creature, remaining_movement: int) -> None:
        enemies = self.battle_map.enemies_of(creature)
        pos = self.battle_map.get_position(creature)
        pos_str = f"({pos[0]},{pos[1]})" if pos else "unknown"
        print(f"\n  Position: {pos_str}  "
              f"Movement: {remaining_movement}ft  "
              f"Actions: {creature.actions.actions}  "
              f"Bonus: {creature.actions.bonus_actions}")
        if enemies:
            print("  Enemies:")
            for e in enemies:
                epos = self.battle_map.get_position(e)
                try:
                    dist = self.battle_map.distance_between(creature, e)
                    dist_str = f"{dist}ft"
                except LookupError:
                    dist_str = "?"
                epos_str = f"({epos[0]},{epos[1]})" if epos else "?"
                print(f"    {e.name:<16} HP: {e.hp}/{e.max_hp}  "
                      f"AC: {e.ac}  pos: {epos_str}  dist: {dist_str}")

    def _prompt_target(self, creature) -> object | None:
        enemies = self.battle_map.enemies_of(creature)
        if not enemies:
            print("  No valid targets.")
            return None
        print("  Choose target:")
        for i, e in enumerate(enemies):
            print(f"    {i+1}) {e.name}  HP: {e.hp}/{e.max_hp}")
        raw = input("  > ").strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(enemies):
                return enemies[idx]
        except ValueError:
            pass
        print("  Invalid choice.")
        return None

    def _prompt_weapon(self, creature):
        weapons = [i for i in creature.equipped_items if i.item_type == "weapon"]
        if not weapons:
            return None
        if len(weapons) == 1:
            return weapons[0]
        print("  Choose weapon:")
        for i, w in enumerate(weapons):
            print(f"    {i+1}) {w.name}")
        raw = input("  > ").strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(weapons):
                return weapons[idx]
        except ValueError:
            pass
        return weapons[0]

    # ------------------------------------------------------------------
    # AI turn
    # ------------------------------------------------------------------

    def _run_ai_turn(self, creature) -> None:
        memory = self.memories.get(creature.team)
        decision = self.ai.plan_turn(creature, self.battle_map, memory=memory)

        if decision.skip:
            print(f"  {creature.name} skips ({decision.reason})")
            return

        # Print memory summary on first turn each round for debugging
        if memory:
            print(f"  [Memory] {memory.summary()}")

        # Dash — spend action, double movement this turn
        effective_speed = creature.speed
        if decision.use_dash and creature.actions.use_action():
            effective_speed = creature.speed * 2
            print(f"  {creature.name} uses Dash "
                  f"(speed {effective_speed}ft this turn)")

        # Walk path step by step — each square charged individually
        # so difficult terrain, OAs, and trail waypoints are all correct.
        # Print a single summary line rather than one line per square.
        remaining = effective_speed
        first_pos = self.battle_map.get_position(creature)
        steps_taken = 0
        for step in decision.path:
            cost = self._try_move(creature, step[0], step[1], remaining,
                                  silent=True)
            if cost is None:
                break
            remaining   -= cost
            steps_taken += 1

        if steps_taken:
            end_pos = self.battle_map.get_position(creature)
            ft_used = effective_speed - remaining
            print(f"  {creature.name} moves "
                  f"({first_pos[0]},{first_pos[1]}) → "
                  f"({end_pos[0]},{end_pos[1]})  [{ft_used}ft]")

        # Dodge — spend action to impose disadvantage on incoming attacks
        # until the start of this creature's next turn.
        if getattr(decision, "use_dodge", False) and creature.actions.use_action():
            creature.add_condition("dodging")
            print(f"  {creature.name} takes the Dodge action.")

        # Attack — fire main attack, extra attacks, then Action Surge if available
        if decision.target and decision.weapon and creature.actions.use_action():
            self._do_attack_action(creature, decision.target, decision.weapon)

            while creature.actions.can_surge:
                enemies = self.battle_map.enemies_of(creature)
                if not enemies:
                    break
                # Only surge if at least one enemy is actually in range.
                # Spending Action Surge when nothing is reachable wastes the
                # charge — Action Surge recovers on a short rest, not each turn.
                surge_target = min(enemies, key=lambda e: e.hp)
                in_range = self.battle_map.check_attack_range(
                    creature, surge_target,
                    is_ranged=decision.weapon.is_ranged,
                    normal_range=decision.weapon.normal_range,
                    long_range=decision.weapon.long_range,
                )
                if not in_range:
                    break
                creature.actions.use_action_surge()
                print(f"  {creature.name} uses Action Surge!")
                self._do_attack_action(creature, surge_target, decision.weapon)
        elif not decision.target:
            print(f"  {creature.name} found no target.")

    # ------------------------------------------------------------------
    # Shared action helpers
    # ------------------------------------------------------------------

    def _try_move(
        self, creature, col: int, row: int, remaining_movement: int,
        silent: bool = False,
    ) -> int | None:
        """
        Attempt to move creature to (col, row).
        silent=True suppresses the per-step "moves to" print but OA messages
        still print. Returns movement cost spent, or None if move failed.
        """
        try:
            cost = self.battle_map.movement_cost_to(creature, col, row)
        except ValueError as e:
            if not silent:
                print(f"  Cannot move: {e}")
            return None

        if cost > remaining_movement:
            return None

        try:
            oa_targets = self.battle_map.move_creature(creature, col, row)
        except ValueError as e:
            if not silent:
                print(f"  Cannot move: {e}")
            return None

        if not silent:
            print(f"  {creature.name} moves to ({col}, {row})")

        # Trigger opportunity attacks BEFORE committing position so the
        # attacker is still adjacent for the range check.
        for attacker in oa_targets:
            if attacker.actions.use_reaction():
                print(f"  {attacker.name} takes an opportunity attack on {creature.name}!")
                self.event.broadcast("opportunity_attack", {
                    "attacker": attacker,
                    "target":   creature,
                })
                self._execute_attack(attacker, creature, weapon=None)

        # Now commit the move
        self.battle_map.commit_move(creature, col, row)

        return cost

    def _do_attack_action(self, creature, target, weapon) -> None:
        """
        Fire one attack action: main attack + all extra attacks.
        Shared by AI turn, player turn, and Action Surge.
        Re-picks target automatically if the current one goes down mid-loop.
        """
        self._execute_attack(creature, target, weapon)
        while creature.actions.use_extra_attack():
            if not target.is_alive():
                enemies = self.battle_map.enemies_of(creature)
                if not enemies:
                    break
                target = min(enemies, key=lambda e: e.hp)
                print(f"  Target down — switching to {target.name}")
            self._execute_attack(creature, target, weapon)

    def _execute_attack(self, attacker, target, weapon=None) -> None:
        """
        Resolve an attack. weapon can be an Item, WeaponProfile, or None.
        Validates range via BattleMap before rolling.
        """
        # Determine range parameters
        is_ranged = False
        normal_range = 5
        long_range = 5
        item_obj = None

        if weapon is not None:
            if hasattr(weapon, "item_type"):
                # It's an Item
                item_obj = weapon
                is_ranged = getattr(weapon, "attack_type", "melee") == "range"
                normal_range = getattr(weapon, "normal_range", 150 if is_ranged else 5)
                long_range = getattr(weapon, "long_range", 600 if is_ranged else 5)
            elif hasattr(weapon, "is_ranged"):
                # It's a WeaponProfile
                is_ranged = weapon.is_ranged
                normal_range = weapon.normal_range
                long_range = weapon.long_range
                item_obj = weapon.item

        # Range check
        if self.battle_map.get_position(attacker) and self.battle_map.get_position(target):
            range_result = self.battle_map.check_attack_range(
                attacker, target,
                is_ranged=is_ranged,
                normal_range=normal_range,
                long_range=long_range,
            )
            if not range_result.valid:
                print(f"  {attacker.name} cannot reach {target.name}: {range_result.reason}")
                return
            if range_result.disadvantage:
                print(f"  {attacker.name} attacks with disadvantage: {range_result.reason}")

        atk = WeaponAttack(attacker, target, "1d6", item=item_obj)

        # Apply disadvantage from range check
        if self.battle_map.get_position(attacker) and self.battle_map.get_position(target):
            if range_result.disadvantage:
                atk.advantage = False
                atk._forced_disadvantage = True

        atk.declare_attack()

    # ------------------------------------------------------------------
    # Opportunity attack response
    # ------------------------------------------------------------------

    # (Handled inline in _try_move — creatures use their reaction automatically)

    # ------------------------------------------------------------------
    # Downed creature cleanup
    # ------------------------------------------------------------------

    def _on_creature_downed(self, data) -> None:
        """Remove downed creatures from the battle map."""
        creature = data.get("creature")
        if creature:
            self.battle_map.remove(creature)
            print(f"  [{creature.name} removed from map]")

    # ------------------------------------------------------------------
    # Combat state checks
    # ------------------------------------------------------------------

    def _combat_continues(self) -> bool:
        """Return True if both sides still have living creatures."""
        creatures = self.battle_map.all_creatures()
        # Also check creatures that were just downed and may not be removed yet
        all_creatures = [c for _, c in self.initiative.initiative_order]
        teams = {}
        for c in all_creatures:
            if c.is_alive():
                teams.setdefault(c.team, 0)
                teams[c.team] += 1
        return len(teams) > 1

    def _resolve_outcome(self) -> str:
        all_creatures = [c for _, c in self.initiative.initiative_order]
        survivors = [c for c in all_creatures if c.is_alive()]
        if not survivors:
            result = "Draw — all creatures are down."
        else:
            winning_team = survivors[0].team
            winner_names = [c.name for c in survivors]
            result = (f"Victory for team '{winning_team}'! "
                      f"Survivors: {', '.join(winner_names)}")
        print(f"\n{'='*52}")
        print(f"  COMBAT OVER — {result}")
        print(f"  Lasted {self.initiative.round - 1} round(s)")
        print(f"{'='*52}\n")
        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _is_player_turn(self, creature) -> bool:
        return self.mode == CombatMode.PLAYER and creature.team == "blue"

    def _print_initiative_order(self) -> None:
        print("\n  Initiative order:")
        for roll, c in self.initiative.initiative_order:
            print(f"    {roll:>2}  {c.name}  (team: {c.team})")

    def _print_combat_info(self, creature) -> None:
        print(f"\n  {creature.name} info:")
        print(f"    HP: {creature.hp}/{creature.max_hp}  AC: {creature.ac}")
        print(f"    Speed: {creature.speed}ft")
        weapons = [i for i in creature.equipped_items if i.item_type == "weapon"]
        if weapons:
            print(f"    Weapons: {', '.join(w.name for w in weapons)}")
        print(f"    Conditions: {creature.conditions or 'none'}")