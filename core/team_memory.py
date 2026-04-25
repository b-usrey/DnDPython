"""
core/team_memory.py

Shared combat intelligence for a team of creatures.

Each team gets one TeamMemory instance. It subscribes to the event bus
and builds up a picture of the fight that any member of the team can
consult when planning their turn.

Information tracked:
  - ThreatProfile per enemy: estimated hit probability against us,
    damage dealt so far, times targeted each ally, last known position
  - AllyStatus per ally: HP trend (rising/falling), currently targeted by
  - Focus recommendation: which enemy the team should concentrate fire on
  - Round history: a lightweight log for the ML state vector later

Usage:
    # In main.py / CombatManager setup, after creatures are placed:
    memories = TeamMemory.create_for_all_teams(battle_map, event)

    # TacticalAI.plan_turn() receives the relevant memory:
    decision = ai.plan_turn(creature, battle_map,
                            memory=memories.get(creature.team))

No existing files need to change except tactical_ai.py (one optional
parameter added to plan_turn and _pick_target).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.creature import Creature
    from core.battle_map import BattleMap


# ---------------------------------------------------------------------------
# ThreatProfile — what one team knows about a specific enemy
# ---------------------------------------------------------------------------

@dataclass
class ThreatProfile:
    """
    Intelligence gathered about a single enemy creature.
    Updated every time that enemy attacks or is attacked.
    """
    creature:               object                  # the enemy Creature
    attacks_observed:       int   = 0               # how many times it attacked
    hits_landed:            int   = 0               # hits against our team
    total_damage_dealt:     int   = 0               # cumulative damage to our team
    times_targeted_by_team: int   = 0               # how many times WE attacked it
    last_known_hp:          int   = 0               # most recent observed HP
    last_known_max_hp:      int   = 0
    attack_bonuses_seen:    list  = field(default_factory=list)  # raw to-hit totals observed
    damage_rolls_seen:      list  = field(default_factory=list)  # raw damage values observed

    @property
    def estimated_hit_chance_vs_ac(self):
        """
        Estimate probability this enemy hits a given AC based on
        observed attack totals. Returns None if not enough data.
        """
        if len(self.attack_bonuses_seen) < 2:
            return None
        # Infer likely attack bonus from observed totals (median - 10.5 expected d20)
        import statistics
        median_total = statistics.median(self.attack_bonuses_seen)
        estimated_bonus = median_total - 10.5
        return estimated_bonus

    @property
    def average_damage(self):
        if not self.damage_rolls_seen:
            return 0
        return sum(self.damage_rolls_seen) / len(self.damage_rolls_seen)

    @property
    def hp_fraction(self):
        if self.last_known_max_hp <= 0:
            return 1.0
        return self.last_known_hp / self.last_known_max_hp

    @property
    def threat_score(self):
        """
        Composite danger rating. Higher = more threatening.
        Used by TacticalAI to deprioritise focusing already-wounded enemies
        in favour of high-threat ones.

        Formula weights:
          - Damage output (average damage × hit rate observed)
          - HP remaining (lower HP enemy = less future threat)
        """
        hit_rate   = self.hits_landed / max(self.attacks_observed, 1)
        avg_dmg    = self.average_damage
        hp_frac    = self.hp_fraction
        return (avg_dmg * hit_rate) * hp_frac   # scales down as enemy weakens

    def __repr__(self):
        return (
            f"ThreatProfile({self.creature.name!r}, "
            f"dmg={self.total_damage_dealt}, "
            f"hits={self.hits_landed}/{self.attacks_observed}, "
            f"hp={self.last_known_hp}/{self.last_known_max_hp})"
        )


# ---------------------------------------------------------------------------
# AllyStatus — lightweight summary of a teammate's situation
# ---------------------------------------------------------------------------

@dataclass
class AllyStatus:
    creature:           object
    hp_history:         list = field(default_factory=list)   # HP at end of each round
    targeted_by:        list = field(default_factory=list)   # enemies currently focusing this ally

    @property
    def hp_trend(self):
        """
        'falling', 'stable', or 'rising' based on last two HP readings.
        """
        if len(self.hp_history) < 2:
            return "stable"
        delta = self.hp_history[-1] - self.hp_history[-2]
        if delta < -5:
            return "falling"
        if delta > 0:
            return "rising"
        return "stable"

    @property
    def is_under_pressure(self):
        """True if two or more enemies are targeting this ally."""
        return len(self.targeted_by) >= 2


# ---------------------------------------------------------------------------
# TeamMemory
# ---------------------------------------------------------------------------

class TeamMemory:
    """
    Shared combat intelligence for one team.

    Subscribes to the event bus on creation. Every `attack` and `damage`
    event updates the internal knowledge base. Any creature on the team
    can call the query methods during their turn to make smarter decisions.

    Args:
        team:         team identifier string (e.g. "red", "blue")
        event:        shared EventBus instance
        battle_map:   BattleMap (used for position queries)
    """

    def __init__(self, team: str, event, battle_map: BattleMap):
        self.team       = team
        self.event      = event
        self.battle_map = battle_map
        self.round      = 1

        # enemy_id → ThreatProfile
        self._threats:  dict[int, ThreatProfile]  = {}
        # ally_id → AllyStatus
        self._allies:   dict[int, AllyStatus]     = {}

        # Round-by-round summary for ML state vector later
        self._round_log: list[dict] = []

        # Subscribe to relevant events
        event.subscribe("attack",          self._on_attack)
        event.subscribe("damage",          self._on_damage)
        event.subscribe("creature_downed", self._on_downed)
        event.subscribe("TurnStarted",     self._on_turn_started)
        event.subscribe("RoundStarted",    self._on_round_started)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create_for_all_teams(
        cls, battle_map: BattleMap, event
    ) -> dict[str, "TeamMemory"]:
        """
        Create one TeamMemory per team present on the battle map.
        Returns a dict keyed by team name.

        Usage:
            memories = TeamMemory.create_for_all_teams(battle_map, event)
            goblin_memory = memories["red"]
            brendiir_memory = memories["blue"]
        """
        teams = {c.team for c in battle_map.all_creatures()}
        return {team: cls(team, event, battle_map) for team in teams}

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_attack(self, data):
        attacker = data.get("attacker")
        target   = data.get("target")
        attack   = data.get("attack")
        if not attacker or not target or not attack:
            return

        # Enemy is attacking one of our members
        if target.team == self.team and attacker.team != self.team:
            profile = self._get_or_create_threat(attacker)
            profile.attacks_observed += 1
            profile.last_known_hp     = attacker.hp
            profile.last_known_max_hp = attacker.max_hp
            # Track who is targeting which ally
            ally = self._get_or_create_ally(target)
            if attacker not in ally.targeted_by:
                ally.targeted_by.append(attacker)

        # We are attacking an enemy — record that we're focusing them
        if attacker.team == self.team and target.team != self.team:
            profile = self._get_or_create_threat(target)
            profile.times_targeted_by_team += 1
            profile.last_known_hp     = target.hp
            profile.last_known_max_hp = target.max_hp

            # Record the to-hit total for threat estimation
            total = attack.result.get("attack_total")
            if total is not None:
                profile.attack_bonuses_seen.append(total)

    def _on_damage(self, data):
        attacker = data.get("attacker")
        target   = data.get("target")
        attack   = data.get("attack")
        if not attacker or not target or not attack:
            return

        damage = attack.result.get("damage", 0)
        hit    = attack.result.get("hit", False)

        # Enemy damaged one of our members
        if target.team == self.team and attacker.team != self.team and hit:
            profile = self._get_or_create_threat(attacker)
            profile.hits_landed       += 1
            profile.total_damage_dealt += damage or 0
            if damage:
                profile.damage_rolls_seen.append(damage)

        # We damaged an enemy — update their known HP
        if attacker.team == self.team and target.team != self.team:
            profile = self._get_or_create_threat(target)
            profile.last_known_hp     = target.hp
            profile.last_known_max_hp = target.max_hp

    def _on_downed(self, data):
        creature = data.get("creature")
        if not creature:
            return
        # If an enemy is downed, remove them from targeted_by lists
        if creature.team != self.team:
            for ally in self._allies.values():
                ally.targeted_by = [
                    e for e in ally.targeted_by if e is not creature
                ]
        # If an ally is downed, remove their status
        if creature.team == self.team:
            self._allies.pop(id(creature), None)

    def _on_turn_started(self, data):
        creature = data.get("creature")
        # Snapshot ally HP at the start of each of their turns
        if creature and creature.team == self.team:
            ally = self._get_or_create_ally(creature)
            ally.hp_history.append(creature.hp)
            # Clear targeted_by each turn — will be repopulated by attacks
            ally.targeted_by = []

    def _on_round_started(self, data):
        self.round = data.get("round", self.round)
        # Snapshot state for ML history
        self._round_log.append({
            "round":       self.round,
            "threat_scores": {
                id(p.creature): p.threat_score
                for p in self._threats.values()
            },
        })

    # ------------------------------------------------------------------
    # Query API — called by TacticalAI during plan_turn()
    # ------------------------------------------------------------------

    def recommended_target(self, enemies: list) -> object | None:
        """
        Return the enemy this team should focus fire on.

        Priority order:
          1. Enemy already being focused by another ally (finish them fast)
          2. Highest threat score (most dangerous enemy still alive)
          3. Fallback: weakest HP (original behaviour)

        Returns None if no enemies are known yet (first turn).
        """
        if not enemies:
            return None

        # Check if any enemy is already being focused by a teammate
        focus_counts = defaultdict(int)
        for profile in self._threats.values():
            if profile.creature in enemies:
                focus_counts[profile.creature] += profile.times_targeted_by_team

        # Prefer focusing an already-targeted enemy to pile on
        focused = [e for e in enemies if focus_counts[e] > 0]
        if focused:
            # Among focused enemies, pick the one closest to death
            return min(focused, key=lambda e: e.hp / max(e.max_hp, 1))

        # No focus history yet — pick by threat score if available
        scored = [
            (e, self._threats[id(e)].threat_score)
            for e in enemies if id(e) in self._threats
        ]
        if scored:
            return max(scored, key=lambda x: x[1])[0]

        # Fallback — weakest enemy (original TacticalAI behaviour)
        return min(enemies, key=lambda e: e.hp)

    def threat_level(self, enemy) -> float:
        """
        Return the threat score for a specific enemy.
        0.0 if we've never observed them attacking.
        """
        profile = self._threats.get(id(enemy))
        return profile.threat_score if profile else 0.0

    def estimated_hit_bonus(self, enemy) -> float | None:
        """
        Estimate the enemy's attack bonus based on observed rolls.
        Returns None if we haven't seen enough attacks to estimate.
        Useful for deciding whether to retreat or hold position.
        """
        profile = self._threats.get(id(enemy))
        if not profile:
            return None
        return profile.estimated_hit_chance_vs_ac

    def average_damage_from(self, enemy) -> float:
        """Average damage dealt per hit by this enemy. 0 if unknown."""
        profile = self._threats.get(id(enemy))
        return profile.average_damage if profile else 0.0

    def ally_under_pressure(self, ally) -> bool:
        """True if two or more enemies are currently targeting this ally."""
        status = self._allies.get(id(ally))
        return status.is_under_pressure if status else False

    def most_pressured_ally(self, allies: list) -> object | None:
        """
        Return whichever ally is being targeted by the most enemies.
        Useful for positioning — move to support the most threatened teammate.
        """
        if not allies:
            return None
        def pressure(a):
            status = self._allies.get(id(a))
            return len(status.targeted_by) if status else 0
        return max(allies, key=pressure)

    _MELEE_RANGE = 1.5   # squares -- covers orthogonal (1.0) and diagonal (1.41)
    _DIST_CAP    = 10.0  # squares beyond which distance saturates to 1.0

    def get_state_vector(
        self,
        creature,
        enemies: list,
        allies: list,
        max_rounds: int = 30,
    ) -> list[float]:
        """
        Build a normalised state vector for ML input.

        12 features (all in [0, 1]):

        Core 9 -- used by RL Q-table (n_features=9) and Evo
          0  own HP ratio
          1  team HP ratio  (sum alive HP / sum alive max_hp, incl. self)
          2  enemy HP ratio (sum alive enemy HP / sum alive enemy max_hp)
          3  team size advantage  (n_alive_friendly / total_alive)
          4  nearest enemy distance, normalised to _DIST_CAP squares
          5  in melee range of any enemy  (0 or 1)
          6  round fraction  (current_round / max_rounds)
          7  any ally under pressure  (0 or 1)
          8  top enemy threat score, normalised (cap at 10)

        Extended 3 -- used by Evo (n_features=12)
          9  enemies in melee range / 5   (how surrounded)
          10 focus-target HP ratio        (0 if no focus target)
          11 most-pressured ally HP ratio (0 if no ally under pressure)

        Note: features 0-8 replace the previous 9-feature layout.
        Existing .npy weights trained on the old vector must be retrained.
        State space with n_bins=3: 3^9 = 19683 (RL) / 3^12 = 531441 (evo).
        """
        n_friendly = 1 + len(allies)
        n_enemy    = len(enemies)
        n_total    = n_friendly + n_enemy

        # 0: own HP ratio
        own_hp_ratio = creature.hp / max(creature.max_hp, 1)

        # 1: team HP ratio
        all_friendly  = [creature] + allies
        team_hp_ratio = (
            sum(c.hp for c in all_friendly) /
            max(sum(c.max_hp for c in all_friendly), 1)
        )

        # 2: enemy HP ratio
        enemy_hp_ratio = (
            sum(e.hp for e in enemies) /
            max(sum(e.max_hp for e in enemies), 1)
        ) if enemies else 0.0

        # 3: team size advantage
        size_adv = n_friendly / max(n_total, 1)

        # 4-5: distance and melee exposure
        nearest_raw = self._DIST_CAP
        n_melee     = 0
        for e in enemies:
            try:
                d = self.battle_map.distance_between(creature, e)
                if d < nearest_raw:
                    nearest_raw = d
                if d <= self._MELEE_RANGE:
                    n_melee += 1
            except LookupError:
                pass
        nearest_dist = min(nearest_raw / self._DIST_CAP, 1.0)
        in_melee     = 1.0 if nearest_raw <= self._MELEE_RANGE else 0.0

        # 6: round fraction
        round_frac = min(self.round / max(max_rounds, 1), 1.0)

        # 7: ally pressure
        ally_pressure = 1.0 if any(self.ally_under_pressure(a) for a in allies) else 0.0

        # 8: top enemy threat score
        threat_scores = [
            self._threats[id(e)].threat_score
            for e in enemies if id(e) in self._threats
        ]
        top_threat = min(max(threat_scores) / 10.0, 1.0) if threat_scores else 0.0

        # 9: melee crowding (evo)
        melee_crowd = min(n_melee / 5.0, 1.0)

        # 10: focus-target HP ratio (evo)
        target    = self.recommended_target(enemies)
        target_hp = target.hp / max(target.max_hp, 1) if target else 0.0

        # 11: most-pressured ally HP ratio (evo)
        pressured = [a for a in allies if self.ally_under_pressure(a)]
        threatened_ally_hp = (
            min(a.hp / max(a.max_hp, 1) for a in pressured) if pressured else 0.0
        )

        return [
            own_hp_ratio,       # 0  own survivability
            team_hp_ratio,      # 1  whole-team health
            enemy_hp_ratio,     # 2  enemy health remaining (fight progress)
            size_adv,           # 3  relative team size
            nearest_dist,       # 4  range to nearest enemy
            in_melee,           # 5  immediate melee threat
            round_frac,         # 6  time pressure / timeout awareness
            ally_pressure,      # 7  teammate being focused?
            top_threat,         # 8  danger level of scariest enemy
            melee_crowd,        # 9  how surrounded (evo)
            target_hp,          # 10 focus-target health (evo)
            threatened_ally_hp, # 11 most-pressured ally health (evo)
        ]

    def summary(self) -> str:
        """Human-readable summary for debugging / combat log."""
        lines = [f"TeamMemory [{self.team}]  round {self.round}"]
        if self._threats:
            lines.append("  Threats:")
            for p in sorted(self._threats.values(),
                            key=lambda x: x.threat_score, reverse=True):
                lines.append(
                    f"    {p.creature.name:<16} "
                    f"threat={p.threat_score:.1f}  "
                    f"dmg={p.total_damage_dealt}  "
                    f"hp={p.last_known_hp}/{p.last_known_max_hp}"
                )
        if self._allies:
            lines.append("  Allies:")
            for s in self._allies.values():
                pressure = "PRESSURED" if s.is_under_pressure else "ok"
                lines.append(
                    f"    {s.creature.name:<16} "
                    f"trend={s.hp_trend}  {pressure}"
                )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create_threat(self, enemy) -> ThreatProfile:
        key = id(enemy)
        if key not in self._threats:
            self._threats[key] = ThreatProfile(
                creature=enemy,
                last_known_hp=enemy.hp,
                last_known_max_hp=enemy.max_hp,
            )
        return self._threats[key]

    def _get_or_create_ally(self, ally) -> AllyStatus:
        key = id(ally)
        if key not in self._allies:
            self._allies[key] = AllyStatus(creature=ally)
        return self._allies[key]