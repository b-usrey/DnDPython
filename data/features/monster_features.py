"""
data/features/monster_features.py

Monster abilities, built from the data in data/monsters/monsters.py by
CreatureFactory. Four families:

  Traits          passive or triggered rules on the monster itself
                  (Regeneration, Pack Tactics, Undead Fortitude, ...)
  Attack riders   what a hit does beyond its damage: a ghoul's paralysis,
                  a wolf's trip, a wight draining maximum HP (MonsterRiders)
  Actions         recharge or limited-use actions that replace the attack
                  action: breath weapons, a giant spider's web (MonsterAction)
  Legendary       Legendary Resistance and Legendary Actions

Abilities are rules, not learned policy. Each one makes a decision a DM
could read off the combat log -- "Poison Breath (expected 41 vs attacks
17)" -- which is the point: the simulator's job is to play monsters the way
a competent DM would, and to be able to say why.

Not modelled: a troll's "dies only if it starts its turn at 0 HP" (monsters
here die at 0), charges and pounces that need a straight-line run, a
chimera breathing in place of one attack rather than the whole action,
sunlight sensitivity, and any spell the engine does not implement.
"""
import random

from data.features.base import Feature
from data.features.combat_spells import _AoESpell
from core.saving_throw import SavingThrow, DamageOnSave
from core.monster_stats import parse_dice
from core.attack import hit_probability


# ── helpers ──────────────────────────────────────────────────────────────────

def _roll(dice, crit=False) -> int:
    n, s = parse_dice(dice)
    if crit:
        n *= 2
    return sum(random.randint(1, s) for _ in range(n))


def _avg(dice) -> float:
    n, s = parse_dice(dice)
    return n * (s + 1) / 2.0


def _allies_of(creature):
    bm = getattr(creature, "battle_map", None)
    if bm is None:
        return []
    return [c for c in bm.all_creatures()
            if c.team == creature.team and c is not creature and c.is_alive()]


def _enemies_of(creature):
    bm = getattr(creature, "battle_map", None)
    if bm is None:
        return []
    return [e for e in bm.enemies_of(creature) if e.is_alive()]


def _dist(a, b):
    bm = getattr(a, "battle_map", None)
    if bm is None:
        return None
    try:
        return bm.distance_between(a, b)
    except (LookupError, AttributeError):
        return None


def _incapacitated(c) -> bool:
    f = getattr(c, "is_incapacitated", None)
    return bool(f and f())


def _ally_adjacent_to(creature, target) -> bool:
    """True if one of creature's allies, able to act, is within 5 ft of target."""
    for ally in _allies_of(creature):
        if _incapacitated(ally):
            continue
        d = _dist(ally, target)
        if d is not None and d <= 5:
            return True
    return False


def rider_source(attack) -> str:
    return (getattr(attack, "_weapon_name_hint", None)
            or getattr(getattr(attack, "item", None), "name", None) or "attack")


class _MonsterFeature(Feature):
    """Base for data-driven monster features. configure() receives the
    trait's dict from the monster template, or {} for a bare name."""

    def configure(self, params):
        self.params = dict(params or {})


class _ConditionTracker:
    """
    Conditions a monster inflicted that end on a saving throw -- a ghoul's
    paralysis, a dragon's fear. The target repeats the save at the end of
    each of its turns; the effect ends after max_rounds regardless
    (1 minute = 10 rounds).
    """

    def __init__(self, source):
        self.source  = source
        self._active = {}   # (id(target), condition) -> [target, cond, ability, dc, rounds]

    def add(self, target, condition, ability=None, dc=None, max_rounds=10) -> bool:
        if not target.add_condition(condition):
            return False   # immune
        if ability and dc:
            self._active[(id(target), condition)] = [target, condition, ability, dc, max_rounds]
        return True

    def on_turn_ended(self, creature):
        for key, entry in list(self._active.items()):
            target, condition, ability, dc, _ = entry
            if target is not creature:
                continue
            if not target.has_condition(condition) or not target.is_alive():
                del self._active[key]
                continue
            res = SavingThrow.roll(caster=self.source, target=target,
                                   ability=ability, dc=dc, on_save=DamageOnSave.NONE)
            entry[4] -= 1
            if res.success or entry[4] <= 0:
                target.remove_condition(condition)
                del self._active[key]
                print(f"  {target.name} is no longer {condition}.")


# ── attack riders ────────────────────────────────────────────────────────────

class MonsterRiders(_MonsterFeature):
    """
    What a monster's hit does beyond its damage, read from the attack
    template's "on_hit" block:

      extra_damage "2d6", extra_damage_type   added damage, own damage type
      save "Con", dc 10                       an initial saving throw
      save_effect "half" / "negates"          extra damage on a success
      condition "paralyzed"                   applied on a failed save
                                              (or on the hit, if no save)
      repeat_save True                        repeat the save at the end of
                                              each of the target's turns
      escape {"ability": "Str", "dc": 12}     condition on hit, escaped by
                                              a save at end of turn (webs)
      not_types ["undead"]                    creature types unaffected
      max_hp_reduction True / "extra"         reduce max HP by the damage
                                              dealt (all, or rider only)
      heal_self True                          regain the rider damage
    """
    name = "Monster Riders"
    EVENT_MAP = {"damage_dealt": "on_damage_dealt", "TurnEnded": "on_turn_ended"}

    def __init__(self):
        super().__init__()
        self.tracker = None

    def attach(self, owner, bus):
        super().attach(owner, bus)
        self.tracker = _ConditionTracker(owner)

    def on_turn_ended(self, data):
        c = data.get("creature")
        if c is not None:
            self.tracker.on_turn_ended(c)

    def on_damage_dealt(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        rider = (getattr(attack, "_template", None) or {}).get("on_hit") if attack else None
        if not rider:
            return
        target = data.get("target")
        if target is None or not target.is_alive():
            return
        if getattr(target, "creature_type", None) in rider.get("not_types", []):
            return
        self.apply(rider, target, attack)

    def apply(self, rider, target, attack=None):
        owner      = self.owner
        crit       = bool(attack and getattr(attack, "critical", False))
        hit_damage = (attack.result.get("damage", 0) if attack else 0) or 0
        extra      = rider.get("extra_damage")
        extra_type = rider.get("extra_damage_type", "")
        save, dc   = rider.get("save"), rider.get("dc")
        dealt      = 0
        failed     = True

        if save and dc:
            dmg = _roll(extra, crit) if extra else 0
            on_save = (DamageOnSave.HALF if rider.get("save_effect", "half") == "half"
                       else DamageOnSave.NONE)
            res = SavingThrow.roll(caster=owner, target=target, ability=save, dc=dc,
                                   on_save=on_save, damage=dmg, damage_type=extra_type)
            failed = not res.success
            dealt  = res.damage_dealt
        elif extra:
            dealt = target.take_damage(_roll(extra, crit), damage_type=extra_type)
            if dealt:
                print(f"  {target.name} takes {dealt} {extra_type} damage "
                      f"from {owner.name}'s {rider_source(attack)}.")

        if rider.get("heal_self") and dealt > 0:
            owner.heal(dealt)
        if not target.is_alive():
            return

        cond = rider.get("condition")
        esc  = rider.get("escape")
        if cond and esc:
            if self.tracker.add(target, cond, esc.get("ability"), esc.get("dc")):
                print(f"  {target.name} is {cond} by {owner.name}!")
        elif cond and failed:
            if rider.get("repeat_save") and save and dc:
                applied = self.tracker.add(target, cond, save, dc)
            else:
                applied = target.add_condition(cond)
            if applied:
                print(f"  {target.name} is {cond} by {owner.name}!")

        drain = rider.get("max_hp_reduction")
        if drain and failed:
            amount = dealt if drain == "extra" else hit_damage + dealt
            if amount > 0:
                target._max_hp     = max(1, target._max_hp - amount)
                target._current_hp = min(target._current_hp, target._max_hp)
                print(f"  {target.name}'s maximum HP drops by {amount} "
                      f"(now {target._max_hp}).")


# ── recharge / limited-use actions ───────────────────────────────────────────

class MonsterAction(_AoESpell):
    """
    A monster's special action from the template's "actions" list. Replaces
    the attack action for the turn, as a breath weapon does in 5e.

      kind "save_aoe"  an area everyone in it saves against
                       shape "cone" / "line" / "burst" (centred on the
                       monster) / "sphere" (a point up to range_ft away),
                       size_ft, width_ft (lines), save, dc, damage_dice,
                       damage_mod, damage_type, save_effect, condition,
                       not_types
      kind "attack"    a special attack with its own template and rider
                       (a giant spider's Web)
      recharge 5       regains its use on a 5-6 at the start of the turn
      uses N           or a fixed number of uses

    Decision rule, deliberately legible: after moving, use the action when
    its expected damage across everyone it would catch is at least the
    expected damage of the monster's normal attacks this turn.
    """
    name = "Monster Action"
    EVENT_MAP = {"TurnStarted": "on_turn_started", "action_phase": "on_action_phase"}

    MIN_ENEMIES_HIT   = 1
    FRIENDLY_FIRE_MAX = 0.0

    def __init__(self):
        super().__init__()
        self.cfg         = {}
        self.action_name = "Special Action"
        self.kind        = "save_aoe"
        self.available   = True
        self.uses_left   = None
        self.recharge    = None
        self.dc          = 10
        self.damage_dice = None
        self.damage_mod  = 0
        self.damage_type = ""
        self.save_effect = "half"
        self.condition   = None
        self.not_types   = []

    def configure(self, cfg):
        cfg = dict(cfg or {})
        self.cfg          = cfg
        self.action_name  = cfg.get("name", "Special Action")
        self.name         = self.action_name
        self.kind         = cfg.get("kind", "save_aoe")
        self.SAVE_ABILITY = cfg.get("save", "Dex")
        self.dc           = cfg.get("dc", 10)
        self.damage_dice  = cfg.get("damage_dice")
        self.damage_mod   = cfg.get("damage_mod", 0)
        self.damage_type  = cfg.get("damage_type", "")
        self.save_effect  = cfg.get("save_effect", "half")
        self.condition    = cfg.get("condition")
        self.not_types    = list(cfg.get("not_types", []))
        self.recharge     = cfg.get("recharge")
        self.uses_left    = cfg.get("uses")
        shape = cfg.get("shape", "cone")
        size  = cfg.get("size_ft", 15)
        if shape == "cone":
            self.SHAPE, self.CONE_LENGTH_FT = "cone", size
        elif shape == "line":
            self.SHAPE, self.LINE_LENGTH_FT = "line", size
            self.LINE_WIDTH_FT = cfg.get("width_ft", 5)
        elif shape == "sphere":
            self.SHAPE, self.SELF_CENTERED = "burst", False
            self.RADIUS_FT, self.CAST_RANGE_FT = size, cfg.get("range_ft", 60)
        else:   # "burst", centred on the monster
            self.SHAPE, self.SELF_CENTERED, self.RADIUS_FT = "burst", True, size

    # resources ---------------------------------------------------------------

    def on_turn_started(self, ctx):
        if ctx.get("creature") is not self.owner:
            return
        if not self.available and self.recharge:
            roll = random.randint(1, 6)
            if roll >= self.recharge:
                self.available = True
                print(f"  {self.owner.name}: {self.action_name} recharges (rolled {roll}).")

    def ready(self) -> bool:
        if self.uses_left is not None and self.uses_left <= 0:
            return False
        return self.available

    def _spend(self):
        if self.recharge:
            self.available = False
        if self.uses_left is not None:
            self.uses_left -= 1

    # decision ----------------------------------------------------------------

    def on_action_phase(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner or not self.ready():
            return
        if creature.actions.actions <= 0 or _incapacitated(creature):
            return
        if self.kind == "attack":
            self._try_special_attack(creature)
            return
        bm = getattr(creature, "battle_map", None)
        if bm is None:
            return
        placement = self._find_best_placement(creature, bm)
        if placement is None:
            return
        enemies, allies = placement
        expected  = self.placement_value(creature, enemies, allies)
        attack_ev = self.multiattack_ev(creature, ctx.get("decision"))
        if expected < attack_ev:
            print(f"  {creature.name} holds {self.action_name} "
                  f"(expected {expected:.0f} vs attacks {attack_ev:.0f}).")
            return
        if not creature.actions.use_action():
            return
        self._spend()
        print(f"  {creature.name} uses {self.action_name} "
              f"(expected {expected:.0f} vs attacks {attack_ev:.0f}).")
        creature.event_manager.broadcast("monster_action", {
            "creature": creature, "action": self.action_name,
            "targets": [e.name for e in enemies],
            "expected": round(expected, 1), "attack_expected": round(attack_ev, 1),
        })
        self._cast_aoe(creature, enemies, allies, 0)

    def execute_now(self, creature, min_targets=1) -> bool:
        """Fire immediately, no resource or action cost -- for legendary actions."""
        bm = getattr(creature, "battle_map", None)
        if bm is None:
            return False
        placement = self._find_best_placement(creature, bm)
        if placement is None or len(placement[0]) < min_targets:
            return False
        self._cast_aoe(creature, placement[0], placement[1], 0)
        return True

    def placement_value(self, caster, enemies, allies) -> float:
        avg = self._avg_damage_at(0)
        e = sum(min(t.hp, self._expected_dmg(caster, t, avg)) for t in enemies)
        a = sum(min(t.hp, self._expected_dmg(caster, t, avg)) for t in allies)
        return e - self.FRIENDLY_PENALTY * a

    @staticmethod
    def multiattack_ev(creature, decision) -> float:
        """Expected damage of the attack action the planner lined up."""
        if decision is None:
            return 0.0
        weapon, target = getattr(decision, "weapon", None), getattr(decision, "target", None)
        if weapon is None or target is None or not target.is_alive():
            return 0.0
        n = 1 + getattr(creature.actions, "extra_attacks", 0)
        num, sides = parse_dice(weapon.damage_die)
        per_hit = num * (sides + 1) / 2.0 + weapon.damage_mod
        return n * hit_probability(weapon.attack_bonus, target.ac) * max(0.0, per_hit)

    # placement overrides: honour not_types -----------------------------------

    def _filter(self, pairs):
        for es, als in pairs:
            yield ([e for e in es if getattr(e, "creature_type", None) not in self.not_types],
                   [a for a in als if getattr(a, "creature_type", None) not in self.not_types])

    def _burst_placements(self, *args):
        return self._filter(super()._burst_placements(*args))

    def _line_placements(self, *args):
        return self._filter(super()._line_placements(*args))

    def _cone_placements(self, *args):
        return self._filter(super()._cone_placements(*args))

    # damage model ------------------------------------------------------------

    def _avg_damage_at(self, slot_level):
        return (_avg(self.damage_dice) if self.damage_dice else 0.0) + self.damage_mod

    def _expected_dmg(self, caster, target, avg_dmg):
        sb = getattr(target, "statblock", None)
        try:
            mod = sb.save_bonus(self.SAVE_ABILITY)
        except (AttributeError, KeyError, ValueError):
            mod = getattr(sb, "mods", {}).get(self.SAVE_ABILITY, 0) if sb else 0
        p_save = max(0.05, min(0.95, (21 - self.dc + mod) / 20.0))
        factor = (1.0 - 0.5 * p_save) if self.save_effect == "half" else (1.0 - p_save)
        dt = self.damage_type
        if dt and dt in getattr(target, "immunities", ()):
            return 0.0
        if dt and dt in getattr(target, "resistances", ()):
            factor *= 0.5
        if dt and dt in getattr(target, "vulnerabilities", ()):
            factor *= 2.0
        return avg_dmg * factor

    def _cast_aoe(self, caster, targets, allies, slot_level):
        dmg = ((_roll(self.damage_dice) if self.damage_dice else 0) + self.damage_mod)
        on_save = DamageOnSave.HALF if self.save_effect == "half" else DamageOnSave.NONE
        print(f"  {caster.name}: {self.action_name}! ({dmg} {self.damage_type}, "
              f"{self.SAVE_ABILITY} DC {self.dc}) -- {len(targets)} "
              f"target{'s' if len(targets) != 1 else ''}"
              + (f", {len(allies)} allied" if allies else ""))
        for t in targets + allies:
            if getattr(t, "creature_type", None) in self.not_types:
                continue
            res = SavingThrow.roll(caster=caster, target=t, ability=self.SAVE_ABILITY,
                                   dc=self.dc, on_save=on_save,
                                   damage=max(0, dmg), damage_type=self.damage_type)
            if self.condition and not res.success and t.is_alive():
                t.add_condition(self.condition)

    # special attack (webs) ---------------------------------------------------

    def _try_special_attack(self, creature):
        tmpl   = self.cfg.get("attack") or {}
        combat = getattr(creature, "combat", None)
        bm     = getattr(creature, "battle_map", None)
        if not tmpl or combat is None or bm is None:
            return
        from core.tactical_ai import WeaponProfile
        from core.monster_stats import template_dice_str
        is_ranged = tmpl.get("attack_type", "melee") == "range"
        prof = WeaponProfile(
            name=tmpl.get("name", self.action_name), is_ranged=is_ranged,
            normal_range=tmpl.get("normal_range", 5), long_range=tmpl.get("long_range", 5),
            attack_bonus=tmpl.get("attack_bonus", 0), damage_die=template_dice_str(tmpl),
            damage_mod=tmpl.get("damage_mod", 0),
            damage_type=tmpl.get("damage_type", "bludgeoning"), template=tmpl,
        )
        cond = (tmpl.get("on_hit") or {}).get("condition")
        candidates = []
        for e in _enemies_of(creature):
            if cond and e.has_condition(cond):
                continue
            try:
                ok = bm.check_attack_range(creature, e, is_ranged=prof.is_ranged,
                                           normal_range=prof.normal_range,
                                           long_range=prof.long_range).valid
            except LookupError:
                ok = False
            if ok:
                candidates.append(e)
        if not candidates:
            return
        memory = getattr(creature, "team_memory", None)
        target = max(candidates, key=lambda e: (memory.effective_danger_score(e)
                                                if memory else e.hp))
        if not creature.actions.use_action():
            return
        self._spend()
        print(f"  {creature.name} uses {self.action_name} on {target.name}!")
        combat._execute_attack(creature, target, prof)


# ── spellcasting ─────────────────────────────────────────────────────────────

class MonsterSpellcasting(_MonsterFeature):
    """
    A monster's stat-block spellcasting: fixed DC, attack bonus, caster
    level and slots, then the listed spells attached by name. Plays the
    same role as the PC Spellcasting feature -- owner.spell_slots = self --
    so every existing spell feature works unchanged for monsters.
    """
    name = "Monster Spellcasting"

    def __init__(self):
        super().__init__()
        self._slots       = {}
        self.spell_dc     = 10
        self.spell_attack = 0

    def configure(self, params):
        super().configure(params)
        owner = self.owner
        self.spell_dc     = int(self.params.get("dc", 10))
        self.spell_attack = int(self.params.get("attack", 0))
        self._slots = {int(k): int(v) for k, v in (self.params.get("slots") or {}).items()}
        owner.spellcasting_ability = self.params.get("ability", "Int")
        owner.caster_level         = int(self.params.get("caster_level", 1))
        owner.spell_slots          = self
        print(f"  {owner.name}: Spellcasting [{owner.spellcasting_ability}] "
              f"(attack +{self.spell_attack}, DC {self.spell_dc}, slots {self._slots})")
        for spell in self.params.get("spells", []):
            owner._add_feature_by_name(spell)

    def has_slot(self, min_level=1) -> bool:
        return any(cnt > 0 for lvl, cnt in self._slots.items() if lvl >= min_level)

    def spend_slot(self, min_level=1):
        for lvl in sorted(self._slots):
            if lvl >= min_level and self._slots[lvl] > 0:
                self._slots[lvl] -= 1
                if self.owner is not None:
                    self.owner.event_manager.broadcast("resource_spent", {
                        "creature": self.owner, "resource": f"spell_slot_{lvl}",
                        "remaining": self._slots[lvl],
                    })
                return lvl
        return None

    def remaining(self) -> dict:
        return {k: v for k, v in self._slots.items() if v > 0}


# ── legendary ────────────────────────────────────────────────────────────────

class LegendaryResistance(_MonsterFeature):
    """
    N times per day, turn a failed save into a success. Spent on any failed
    save that would impose a condition or cost a tenth of max HP -- the
    moments a DM would actually spend one on.
    """
    name = "Legendary Resistance"
    EVENT_MAP = {"saving_throw_resolved": "on_resolved"}

    def __init__(self):
        super().__init__()
        self.uses = 3

    def configure(self, params):
        super().configure(params)
        self.uses = int(self.params.get("uses", 3))

    def on_resolved(self, data):
        result = data.get("result")
        if not result or result.target is not self.owner:
            return
        if result.success or self.uses <= 0:
            return
        applied = [n.split(": ", 1)[1] for n in result.notes
                   if n.startswith("condition applied: ")]
        if not applied and result.damage_dealt < max(10, self.owner.max_hp // 10):
            return
        self.uses -= 1
        result.success = True
        refund = 0
        if result.damage_dealt and result.on_save == DamageOnSave.HALF:
            refund = result.damage_dealt - result.damage_dealt // 2
        elif result.damage_dealt and result.on_save == DamageOnSave.NONE:
            refund = result.damage_dealt
        if refund:
            self.owner.heal(refund)
        for cond in applied:
            self.owner.remove_condition(cond)
        print(f"  {self.owner.name} uses Legendary Resistance "
              f"({self.uses} left): the save succeeds instead.")


class LegendaryActions(_MonsterFeature):
    """
    Spend legendary action points at the end of other creatures' turns.
    Options from the template: kind "attack" (a named attack, or a cantrip's
    pseudo-weapon) or kind "save_aoe" (same fields as MonsterAction).
    Points refill at the start of the monster's own turn. Policy: at the end
    of each enemy's turn, use the most expensive option that has a worthwhile
    target -- a Wing Attack needs min_targets enemies in range, otherwise
    fall back to a Tail Attack.
    """
    name = "Legendary Actions"
    EVENT_MAP = {"TurnStarted": "on_turn_started", "TurnEnded": "on_turn_ended"}

    def __init__(self):
        super().__init__()
        self.max_points = 3
        self.points     = 3
        self.options    = []
        self._aoe       = {}

    def configure(self, params):
        super().configure(params)
        self.max_points = int(self.params.get("count", 3))
        self.points     = self.max_points
        self.options    = list(self.params.get("options", []))
        for opt in self.options:
            if opt.get("kind") == "save_aoe":
                act = MonsterAction()
                act.owner = self.owner      # not attached: fired by hand below
                act.configure(opt)
                self._aoe[opt["name"]] = act

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self.points = self.max_points

    def on_turn_ended(self, data):
        c, owner = data.get("creature"), self.owner
        if c is None or c is owner or c.team == owner.team:
            return
        if not owner.is_alive() or _incapacitated(owner) or self.points <= 0:
            return
        combat = getattr(owner, "combat", None)
        if combat is None:
            return
        for opt in sorted(self.options, key=lambda o: -o.get("cost", 1)):
            cost = opt.get("cost", 1)
            if cost > self.points:
                continue
            if self._use(opt, combat):
                self.points -= cost
                print(f"  {owner.name} legendary action: {opt['name']} "
                      f"({self.points} left).")
                return

    def _use(self, opt, combat) -> bool:
        kind = opt.get("kind", "attack")
        if kind == "attack":
            return combat.monster_attack_out_of_turn(self.owner, opt.get("attack"))
        if kind == "save_aoe":
            act = self._aoe.get(opt["name"])
            return bool(act and act.execute_now(self.owner, opt.get("min_targets", 1)))
        return False


# ── traits ───────────────────────────────────────────────────────────────────

class Regeneration(_MonsterFeature):
    """Regain hp at the start of each turn, unless it took one of the
    stopped_by damage types since its last turn (fire or acid, for a troll)."""
    name = "Regeneration"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self.amount     = 10
        self.stopped_by = {"fire", "acid"}

    def configure(self, params):
        super().configure(params)
        self.amount     = int(self.params.get("hp", 10))
        self.stopped_by = set(self.params.get("stopped_by", ["fire", "acid"]))

    def on_turn_started(self, ctx):
        o = self.owner
        if ctx.get("creature") is not o:
            return
        blocked = self.stopped_by & o.damage_types_taken
        o.damage_types_taken.clear()
        if not o.is_alive():
            return
        if blocked:
            print(f"  {o.name} does not regenerate ({', '.join(sorted(blocked))}).")
            return
        healed = o.heal(self.amount)
        if healed:
            print(f"  {o.name} regenerates {healed} HP ({o.hp}/{o.max_hp}).")


class PackTactics(_MonsterFeature):
    """Advantage on an attack when an able ally is within 5 ft of the target."""
    name = "Pack Tactics"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        if data.get("attacker") is not self.owner:
            return
        target, attack = data.get("target"), data.get("attack")
        if attack and target and _ally_adjacent_to(self.owner, target):
            attack.advantage = True


class MartialAdvantage(_MonsterFeature):
    """Once per turn, extra damage (2d6) when an ally is within 5 ft of the target."""
    name = "Martial Advantage"
    EVENT_MAP = {"hit": "on_hit", "TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self.dice  = "2d6"
        self._used = False

    def configure(self, params):
        super().configure(params)
        self.dice = self.params.get("dice", "2d6")

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._used = False

    def on_hit(self, data):
        if self._used or data.get("attacker") is not self.owner:
            return
        target, attack = data.get("target"), data.get("attack")
        if attack and target and _ally_adjacent_to(self.owner, target):
            attack.extra_dice.append(parse_dice(self.dice))
            self._used = True
            print(f"  {self.owner.name}: Martial Advantage (+{self.dice}).")


class UndeadFortitude(_MonsterFeature):
    """Dropping to 0 HP from anything but radiant damage or a crit: a Con save
    (DC 5 + the damage taken) leaves it at 1 HP instead."""
    name = "Undead Fortitude"

    def prevent_drop_to_zero(self, damage, damage_type, critical) -> bool:
        if critical or damage_type == "radiant":
            return False
        res = SavingThrow.roll(caster=self.owner, target=self.owner, ability="Con",
                               dc=5 + int(damage), on_save=DamageOnSave.NONE)
        if res.success:
            print(f"  {self.owner.name}'s Undead Fortitude keeps it up at 1 HP!")
        return res.success


class NimbleEscape(_MonsterFeature):
    """Disengage as a bonus action -- handled in CombatManager._try_move."""
    name = "Nimble Escape"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.nimble_escape = True


class Aggressive(_MonsterFeature):
    """Bonus action: move up to its speed toward a hostile creature."""
    name = "Aggressive"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self._bonus = 0

    def on_turn_started(self, ctx):
        o = self.owner
        if ctx.get("creature") is not o:
            return
        if self._bonus:
            o.speed -= self._bonus
            self._bonus = 0
        enemies = _enemies_of(o)
        if not enemies or o.actions.bonus_actions <= 0:
            return
        dists = [d for d in (_dist(o, e) for e in enemies) if d is not None]
        if not dists or min(dists) <= 5:
            return
        if o.actions.use_bonus_action():
            self._bonus = o.speed
            o.speed += self._bonus
            print(f"  {o.name} is Aggressive: dashes toward the enemy.")


class Displacement(_MonsterFeature):
    """Attacks against it have disadvantage, until it takes damage; the
    illusion returns at the end of its next turn."""
    name = "Displacement"
    EVENT_MAP = {"attack": "on_attack", "damage_dealt": "on_damage_dealt",
                 "TurnEnded": "on_turn_ended"}

    def __init__(self):
        super().__init__()
        self._down = False

    def on_attack(self, data):
        if data.get("target") is not self.owner or self._down or _incapacitated(self.owner):
            return
        attack = data.get("attack")
        if attack:
            attack.disadvantage = True

    def on_damage_dealt(self, data):
        if data.get("target") is self.owner:
            self._down = True

    def on_turn_ended(self, data):
        if data.get("creature") is self.owner:
            self._down = False


class Reckless(_MonsterFeature):
    """Advantage on its melee attacks; attacks against it have advantage too."""
    name = "Reckless"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        attack = data.get("attack")
        if not attack:
            return
        if data.get("attacker") is self.owner and not getattr(attack, "range", False):
            attack.advantage = True
        if data.get("target") is self.owner:
            attack.advantage = True


class MagicResistance(_MonsterFeature):
    """Advantage on saving throws against spells."""
    name = "Magic Resistance"
    EVENT_MAP = {"saving_throw": "on_saving_throw"}

    def on_saving_throw(self, ctx):
        if ctx.get("target") is not self.owner:
            return
        caster = ctx.get("caster")
        if caster is not None and caster is not self.owner \
                and getattr(caster, "spell_slots", None) is not None:
            ctx["advantage"] = True


class FrightfulPresence(_MonsterFeature):
    """
    At the start of its turn, each enemy within range_ft that has not faced
    it yet makes a Wis save or is frightened (repeat at the end of each of
    its turns). Either way that creature is then immune -- in 5e for 24
    hours, which is the whole fight here. Costs no action, as in the adult
    dragons' Multiattack.
    """
    name = "Frightful Presence"
    EVENT_MAP = {"TurnStarted": "on_turn_started", "TurnEnded": "on_turn_ended"}

    def __init__(self):
        super().__init__()
        self.range_ft = 120
        self.dc       = 10
        self._rolled  = set()
        self.tracker  = None

    def attach(self, owner, bus):
        super().attach(owner, bus)
        self.tracker = _ConditionTracker(owner)

    def configure(self, params):
        super().configure(params)
        self.range_ft = int(self.params.get("range_ft", 120))
        self.dc       = int(self.params.get("dc", 10))

    def on_turn_started(self, ctx):
        o = self.owner
        if ctx.get("creature") is not o or _incapacitated(o):
            return
        for e in _enemies_of(o):
            if id(e) in self._rolled:
                continue
            d = _dist(o, e)
            if d is None or d > self.range_ft:
                continue
            self._rolled.add(id(e))
            res = SavingThrow.roll(caster=o, target=e, ability="Wis", dc=self.dc,
                                   on_save=DamageOnSave.NONE)
            if not res.success and self.tracker.add(e, "frightened", "Wis", self.dc):
                print(f"  {e.name} is frightened of {o.name}!")

    def on_turn_ended(self, data):
        c = data.get("creature")
        if c is not None:
            self.tracker.on_turn_ended(c)


class Stench(_MonsterFeature):
    """An enemy starting its turn within 5 ft makes a Con save or is poisoned
    until the start of its next turn. A success makes it immune."""
    name = "Stench"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self.dc        = 10
        self._immune   = set()
        self._poisoned = set()

    def configure(self, params):
        super().configure(params)
        self.dc = int(self.params.get("dc", 10))

    def on_turn_started(self, ctx):
        c, o = ctx.get("creature"), self.owner
        if c is None:
            return
        if id(c) in self._poisoned:
            self._poisoned.discard(id(c))
            c.remove_condition("poisoned")
        if c.team == o.team or not o.is_alive() or id(c) in self._immune:
            return
        d = _dist(o, c)
        if d is None or d > 5:
            return
        res = SavingThrow.roll(caster=o, target=c, ability="Con", dc=self.dc,
                               on_save=DamageOnSave.NONE)
        if res.success:
            self._immune.add(id(c))
        elif c.add_condition("poisoned"):
            self._poisoned.add(id(c))
            print(f"  {c.name} is poisoned by {o.name}'s stench.")
