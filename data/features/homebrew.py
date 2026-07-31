"""
data/features/homebrew.py

A safe, data-driven Feature for homebrew content.

A homebrew feature is a JSON blob describing "on trigger X, if conditions Y,
do effects Z" — interpreted at runtime by HomebrewFeature. No code from the
definition is ever executed, imported, or eval'd: every trigger, condition,
and effect name is resolved through a fixed whitelist dispatch table below,
and every parameter is range/type-checked before use. This is the only
feature type intended to be safe to accept from untrusted users (e.g. a
Tailscale-funnel-exposed server where players submit their own homebrew
classes) — every other Feature subclass in data/features/ is real Python
and must only ever be written by a trusted developer.

Scope (deliberately limited — see README-style notes below):
  - Passive/triggered riders and "when I'm hit" reactions only. No homebrew
    feature can spend its own action or bonus action (matches the rest of
    this codebase — bonus-action-spending features aren't AI-decidable yet
    either; see README "Known Limitations").
  - One trigger + a fixed effect vocabulary per definition. For anything
    fancier, a developer needs to write a real Feature subclass.

Schema
------
{
  "name":       "Frost Strike",           # display name, becomes self.name
  "trigger":    "hit",                    # one of ALLOWED_TRIGGERS
  "conditions": [ {"type": "attacker_is_owner"} ],   # ALL must pass (AND)
  "effects":    [ {"type": "add_damage_dice", "count": 1, "die": 6} ],
  "recharge":   "turn",                   # optional: "turn" | "encounter" | "at_will" (default)
  "max_uses":   1                         # required unless recharge == "at_will"
}

Triggers, and the roles ("self"/"attacker"/"target") available to their
conditions/effects:

  TurnStarted    — fires only on the owner's own turn. role: self
  attack         — an attack roll is being made (before to-hit is rolled).
                   roles: self, attacker, target. Requires an identity
                   condition (attacker_is_owner or target_is_owner).
  hit            — a hit was just confirmed (before damage is rolled) —
                   the right place for on-hit damage riders.
                   roles: self, attacker, target. Requires an identity
                   condition.
  damage_dealt   — the owner (or someone else) just took damage; a
                   reaction window. roles: self, attacker, target.
                   Requires an identity condition. Always spends the
                   owner's reaction and is a no-op if the owner can't
                   react (unconscious/dying/dead) — matches every other
                   reaction feature in this codebase.
  saving_throw   — the owner is making a saving throw. roles: self, target
                   (target is always the owner here — enforced by the
                   required target_is_owner condition).
"""

import logging

from data.features.base import Feature

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation limits — keep homebrew content sane regardless of trust level
# ---------------------------------------------------------------------------

MAX_DICE_COUNT   = 10
MAX_DIE_SIZE     = 20
MAX_FLAT_DAMAGE  = 50
MAX_HEAL_AMOUNT  = 100
MAX_TEMP_HP      = 100
MAX_AC_DELTA     = 5
MAX_USES         = 10
MAX_CONDITION_LEN = 32
MAX_DAMAGE_TYPE_LEN = 32
MAX_NAME_LEN     = 64

ALLOWED_TRIGGERS = {"TurnStarted", "attack", "hit", "damage_dealt", "saving_throw"}
ALLOWED_RECHARGE = {"turn", "encounter", "at_will"}
ALLOWED_ROLES    = {"self", "attacker", "target"}

# Which roles each trigger's event data actually exposes.
_TRIGGER_ROLES = {
    "TurnStarted":   {"self"},
    "attack":        {"self", "attacker", "target"},
    "hit":           {"self", "attacker", "target"},
    "damage_dealt":  {"self", "attacker", "target"},
    "saving_throw":  {"self", "target"},
}

# Triggers on the Attack pipeline (attacker/target aimed at *some* attack,
# not necessarily the owner) must anchor themselves to the owner via an
# explicit identity condition, or every attack in combat would fire them.
_REQUIRES_IDENTITY_CONDITION = {"attack", "hit", "damage_dealt"}
_IDENTITY_CONDITIONS = {"attacker_is_owner", "target_is_owner"}

# Which effect types are meaningful for which triggers.
_EFFECT_ALLOWED_TRIGGERS = {
    "add_damage_dice":    {"hit"},
    "add_flat_damage":    {"hit"},
    "add_advantage":      {"attack", "saving_throw"},
    "add_disadvantage":   {"attack", "saving_throw"},
    "add_condition":      {"hit", "damage_dealt", "TurnStarted"},
    "remove_condition":   {"hit", "damage_dealt", "TurnStarted"},
    "add_resistance":     {"TurnStarted", "damage_dealt"},
    "remove_resistance":  {"TurnStarted", "damage_dealt"},
    "heal":               {"TurnStarted", "hit", "damage_dealt"},
    "add_temp_hp":        {"TurnStarted", "hit", "damage_dealt"},
    "modify_ac":          {"TurnStarted"},
    "grant_extra_attack": {"TurnStarted"},
}

# Which condition types are meaningful for which triggers.
_CONDITION_ALLOWED_TRIGGERS = {
    "attacker_is_owner":    {"attack", "hit", "damage_dealt"},
    "target_is_owner":      {"attack", "hit", "damage_dealt", "saving_throw"},
    "is_critical":          {"attack", "hit", "damage_dealt"},
    "is_melee":             {"attack", "hit", "damage_dealt"},
    "is_ranged":            {"attack", "hit", "damage_dealt"},
    "owner_has_condition":  ALLOWED_TRIGGERS,
    "target_has_condition": {"attack", "hit", "damage_dealt"},
    "hp_below_percent":     ALLOWED_TRIGGERS,
    "ability_is":           {"saving_throw"},
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_homebrew_definition(data: dict) -> list[str]:
    """
    Validate a homebrew feature definition against the schema and safety
    limits above. Returns a list of error strings — empty means valid.
    Never raises; callers decide whether to reject or (for
    HomebrewFeature.__init__) treat a non-empty result as "do nothing".
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["definition must be a JSON object"]

    name = data.get("name")
    if not isinstance(name, str) or not (1 <= len(name) <= MAX_NAME_LEN):
        errors.append(f"'name' must be a string of 1-{MAX_NAME_LEN} characters")

    trigger = data.get("trigger")
    if trigger not in ALLOWED_TRIGGERS:
        errors.append(f"'trigger' must be one of {sorted(ALLOWED_TRIGGERS)}")
        return errors  # can't validate conditions/effects without a valid trigger

    conditions = data.get("conditions", [])
    if not isinstance(conditions, list):
        errors.append("'conditions' must be a list")
        conditions = []
    parsed_conditions = []
    for i, cond in enumerate(conditions):
        err = _validate_condition(cond, trigger, i)
        if err:
            errors.append(err)
        else:
            parsed_conditions.append(cond)

    if trigger in _REQUIRES_IDENTITY_CONDITION:
        has_identity = any(
            c.get("type") in _IDENTITY_CONDITIONS for c in parsed_conditions
        )
        if not has_identity:
            errors.append(
                f"trigger '{trigger}' requires an 'attacker_is_owner' or "
                f"'target_is_owner' condition, otherwise it would fire on "
                f"every attack in combat, not just the owner's"
            )

    effects = data.get("effects", [])
    if not isinstance(effects, list) or not effects:
        errors.append("'effects' must be a non-empty list")
        effects = []
    for i, effect in enumerate(effects):
        err = _validate_effect(effect, trigger, i)
        if err:
            errors.append(err)

    recharge = data.get("recharge", "at_will")
    if recharge not in ALLOWED_RECHARGE:
        errors.append(f"'recharge' must be one of {sorted(ALLOWED_RECHARGE)}")
    max_uses = data.get("max_uses")
    if recharge != "at_will":
        if not isinstance(max_uses, int) or not (1 <= max_uses <= MAX_USES):
            errors.append(
                f"'max_uses' must be an integer 1-{MAX_USES} when recharge != 'at_will'"
            )
    elif max_uses is not None:
        errors.append("'max_uses' must be omitted when recharge is 'at_will'")

    return errors


def _validate_condition(cond, trigger: str, index: int) -> str | None:
    if not isinstance(cond, dict):
        return f"conditions[{index}] must be an object"
    ctype = cond.get("type")
    if ctype not in _CONDITION_ALLOWED_TRIGGERS:
        return f"conditions[{index}]: unknown condition type '{ctype}'"
    if trigger not in _CONDITION_ALLOWED_TRIGGERS[ctype]:
        return f"conditions[{index}]: '{ctype}' doesn't apply to trigger '{trigger}'"

    if ctype in ("owner_has_condition", "target_has_condition"):
        cval = cond.get("condition")
        if not isinstance(cval, str) or not (1 <= len(cval) <= MAX_CONDITION_LEN):
            return f"conditions[{index}]: 'condition' must be a short string"
    elif ctype == "hp_below_percent":
        who = cond.get("who", "self")
        if who not in ALLOWED_ROLES or who not in _TRIGGER_ROLES[trigger]:
            return f"conditions[{index}]: invalid 'who' for trigger '{trigger}'"
        pct = cond.get("percent")
        if not isinstance(pct, (int, float)) or not (0 < pct <= 100):
            return f"conditions[{index}]: 'percent' must be in (0, 100]"
    elif ctype == "ability_is":
        ability = cond.get("ability")
        if ability not in ("Str", "Dex", "Con", "Int", "Wis", "Cha"):
            return f"conditions[{index}]: 'ability' must be a valid ability name"

    return None


def validate_homebrew_class(class_data: dict) -> list[str]:
    """
    Validate an entire homebrew *class* JSON (the data/classes/*.json shape)
    before it's saved/loaded — the natural entry point for an upload API.

    Checks basic shape (hit_die, features_by_level) and, for every feature
    entry across every level (base class and any subclasses), either:
      - it has an inline "homebrew" block, which must pass
        validate_homebrew_definition(), or
      - its "name" must already exist in Feature.REGISTRY (a real,
        developer-written feature) — this catches typos and references to
        features that don't exist, at upload time instead of silently
        warning per-character later.

    Returns a list of error strings — empty means valid.
    """
    errors: list[str] = []

    if not isinstance(class_data, dict):
        return ["class definition must be a JSON object"]

    if not isinstance(class_data.get("hit_die"), int) or not (4 <= class_data["hit_die"] <= 20):
        errors.append("'hit_die' must be an integer 4-20")

    features_by_level = class_data.get("features_by_level")
    if not isinstance(features_by_level, dict) or not features_by_level:
        errors.append("'features_by_level' must be a non-empty object")
        features_by_level = {}

    def _validate_levels(levels: dict, where: str):
        for lvl, feats in levels.items():
            if not isinstance(feats, list):
                errors.append(f"{where} level '{lvl}': must be a list of feature entries")
                continue
            for i, feat in enumerate(feats):
                if not isinstance(feat, dict) or "name" not in feat:
                    errors.append(f"{where} level '{lvl}' entry {i}: must have a 'name'")
                    continue
                homebrew_def = feat.get("homebrew")
                if homebrew_def is not None:
                    sub_errors = validate_homebrew_definition(homebrew_def)
                    for e in sub_errors:
                        errors.append(f"{where} level '{lvl}' '{feat['name']}': {e}")
                elif feat["name"] not in Feature.REGISTRY:
                    errors.append(
                        f"{where} level '{lvl}': feature '{feat['name']}' is neither "
                        f"a homebrew block nor a known feature name"
                    )

    _validate_levels(features_by_level, "base class")

    for sub_name, sub_data in class_data.get("subclasses", {}).items():
        sub_levels = sub_data.get("features_by_level") if isinstance(sub_data, dict) else None
        if not isinstance(sub_levels, dict):
            errors.append(f"subclass '{sub_name}': missing/invalid 'features_by_level'")
            continue
        _validate_levels(sub_levels, f"subclass '{sub_name}'")

    return errors


def _validate_effect(effect, trigger: str, index: int) -> str | None:
    if not isinstance(effect, dict):
        return f"effects[{index}] must be an object"
    etype = effect.get("type")
    if etype not in _EFFECT_ALLOWED_TRIGGERS:
        return f"effects[{index}]: unknown effect type '{etype}'"
    if trigger not in _EFFECT_ALLOWED_TRIGGERS[etype]:
        return f"effects[{index}]: '{etype}' doesn't apply to trigger '{trigger}'"

    def _role_ok(role):
        return role in ALLOWED_ROLES and role in _TRIGGER_ROLES[trigger]

    if etype == "add_damage_dice":
        count, die = effect.get("count"), effect.get("die")
        if not isinstance(count, int) or not (1 <= count <= MAX_DICE_COUNT):
            return f"effects[{index}]: 'count' must be 1-{MAX_DICE_COUNT}"
        if not isinstance(die, int) or die not in (4, 6, 8, 10, 12, 20):
            return f"effects[{index}]: 'die' must be one of 4/6/8/10/12/20"
    elif etype == "add_flat_damage":
        amount = effect.get("amount")
        if not isinstance(amount, int) or not (1 <= amount <= MAX_FLAT_DAMAGE):
            return f"effects[{index}]: 'amount' must be 1-{MAX_FLAT_DAMAGE}"
    elif etype in ("add_condition", "remove_condition"):
        cond_str = effect.get("condition")
        if not isinstance(cond_str, str) or not (1 <= len(cond_str) <= MAX_CONDITION_LEN):
            return f"effects[{index}]: 'condition' must be a short string"
        if not _role_ok(effect.get("target", "self")):
            return f"effects[{index}]: invalid 'target' for trigger '{trigger}'"
    elif etype in ("add_resistance", "remove_resistance"):
        dmg_type = effect.get("damage_type")
        if not isinstance(dmg_type, str) or not (1 <= len(dmg_type) <= MAX_DAMAGE_TYPE_LEN):
            return f"effects[{index}]: 'damage_type' must be a short string"
        if not _role_ok(effect.get("target", "self")):
            return f"effects[{index}]: invalid 'target' for trigger '{trigger}'"
    elif etype == "heal":
        amount = effect.get("amount")
        if not isinstance(amount, int) or not (1 <= amount <= MAX_HEAL_AMOUNT):
            return f"effects[{index}]: 'amount' must be 1-{MAX_HEAL_AMOUNT}"
        if not _role_ok(effect.get("target", "self")):
            return f"effects[{index}]: invalid 'target' for trigger '{trigger}'"
    elif etype == "add_temp_hp":
        amount = effect.get("amount")
        if not isinstance(amount, int) or not (1 <= amount <= MAX_TEMP_HP):
            return f"effects[{index}]: 'amount' must be 1-{MAX_TEMP_HP}"
        if not _role_ok(effect.get("target", "self")):
            return f"effects[{index}]: invalid 'target' for trigger '{trigger}'"
    elif etype == "modify_ac":
        delta = effect.get("delta")
        if not isinstance(delta, int) or not (-MAX_AC_DELTA <= delta <= MAX_AC_DELTA) or delta == 0:
            return f"effects[{index}]: 'delta' must be a nonzero integer in [-{MAX_AC_DELTA}, {MAX_AC_DELTA}]"
    # add_advantage / add_disadvantage / grant_extra_attack take no params

    return None


# ---------------------------------------------------------------------------
# HomebrewFeature — the interpreter
# ---------------------------------------------------------------------------

class HomebrewFeature(Feature):
    """
    Interprets one validated homebrew definition. Constructed directly with
    (name, definition) rather than looked up by name in Feature.REGISTRY,
    since each instance carries its own data — see
    Creature._add_feature_by_name(name, homebrew_def=...).
    """

    def __init__(self, name: str = "Homebrew Feature", definition: dict | None = None):
        super().__init__(name=name)
        self.definition = definition or {}
        self._uses_remaining = self.definition.get("max_uses")

    def attach(self, owner, bus):
        self.owner = owner
        self.bus = bus
        trigger = self.definition.get("trigger")
        if trigger not in ALLOWED_TRIGGERS:
            _log.warning("[%s] homebrew feature '%s' has invalid trigger — not attached",
                         getattr(owner, "name", "?"), self.name)
            return
        # Recharge tick is subscribed to "TurnStarted" *before* the effect
        # handler below (EventBus calls subscribers in subscription order),
        # so a "recharge each turn" pool is refilled before this turn's
        # own trigger fires — including when the trigger itself IS
        # TurnStarted (subscribing to the same event twice, with two
        # different handlers, is fine — the bus just calls both).
        bus.subscribe("TurnStarted", self._on_recharge_tick)
        self._subscriptions.append(("TurnStarted", self._on_recharge_tick))
        bus.subscribe(trigger, self._on_event)
        self._subscriptions.append((trigger, self._on_event))
        print(f"  {owner.name}: homebrew feature '{self.name}' ready "
              f"(trigger={trigger})")

    # ------------------------------------------------------------------
    # Recharge
    # ------------------------------------------------------------------

    def _on_recharge_tick(self, data):
        if data.get("creature") is not self.owner:
            return
        if self.definition.get("recharge") == "turn":
            self._uses_remaining = self.definition.get("max_uses")

    def _consume_use(self) -> bool:
        if self._uses_remaining is None:
            return True   # at_will
        if self._uses_remaining <= 0:
            return False
        self._uses_remaining -= 1
        return True

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _on_event(self, data):
        trigger = self.definition.get("trigger")

        if trigger == "TurnStarted":
            if data.get("creature") is not self.owner:
                return
        # else: attack/hit/damage_dealt/saving_throw are gated by the
        # mandatory identity condition validated at definition time.

        if not self._check_conditions(trigger, data):
            return

        if trigger == "damage_dealt":
            if not self._owner_can_react():
                return
            if not self.owner.actions.use_reaction():
                return

        if not self._consume_use():
            _log.debug("[%s] homebrew '%s': no uses remaining", self.owner.name, self.name)
            return

        self._apply_effects(trigger, data)

    def _resolve_role(self, role: str, data: dict):
        if role == "self":
            return self.owner
        if role == "attacker":
            return data.get("attacker")
        if role == "target":
            return data.get("target")
        return None

    def _check_conditions(self, trigger: str, data: dict) -> bool:
        for cond in self.definition.get("conditions", []):
            if not self._check_one_condition(cond, trigger, data):
                return False
        return True

    def _check_one_condition(self, cond: dict, trigger: str, data: dict) -> bool:
        ctype = cond.get("type")

        if ctype == "attacker_is_owner":
            return data.get("attacker") is self.owner
        if ctype == "target_is_owner":
            return data.get("target") is self.owner

        attack = data.get("attack")
        if ctype == "is_critical":
            return bool(attack) and bool(getattr(attack, "critical", False))
        if ctype == "is_melee":
            return bool(attack) and not getattr(attack, "range", False)
        if ctype == "is_ranged":
            return bool(attack) and bool(getattr(attack, "range", False))

        if ctype == "owner_has_condition":
            return self.owner.has_condition(cond.get("condition", ""))
        if ctype == "target_has_condition":
            target = data.get("target")
            return bool(target) and target.has_condition(cond.get("condition", ""))

        if ctype == "hp_below_percent":
            who = self._resolve_role(cond.get("who", "self"), data)
            if not who or not getattr(who, "max_hp", 0):
                return False
            return (100.0 * who.hp / who.max_hp) < cond.get("percent", 0)

        if ctype == "ability_is":
            return data.get("ability") == cond.get("ability")

        return False   # unknown condition types never pass (fail closed)

    def _apply_effects(self, trigger: str, data: dict):
        for effect in self.definition.get("effects", []):
            self._apply_one_effect(effect, trigger, data)

    def _apply_one_effect(self, effect: dict, trigger: str, data: dict):
        etype = effect.get("type")
        attack = data.get("attack")

        if etype == "add_damage_dice" and attack:
            attack.extra_dice.append((effect["count"], effect["die"]))
            print(f"  {self.owner.name}: {self.name} adds {effect['count']}d{effect['die']}")

        elif etype == "add_flat_damage" and attack:
            attack.damage_mod += effect["amount"]
            print(f"  {self.owner.name}: {self.name} adds +{effect['amount']} damage")

        elif etype == "add_advantage":
            self._set_adv_disadv(trigger, data, advantage=True)

        elif etype == "add_disadvantage":
            self._set_adv_disadv(trigger, data, advantage=False)

        elif etype == "add_condition":
            who = self._resolve_role(effect.get("target", "self"), data)
            if who:
                who.add_condition(effect["condition"])
                print(f"  {self.owner.name}: {self.name} applies '{effect['condition']}' to {who.name}")

        elif etype == "remove_condition":
            who = self._resolve_role(effect.get("target", "self"), data)
            if who:
                who.remove_condition(effect["condition"])

        elif etype == "add_resistance":
            who = self._resolve_role(effect.get("target", "self"), data)
            if who:
                who.resistances.add(effect["damage_type"].lower())
                print(f"  {self.owner.name}: {self.name} grants resistance to {effect['damage_type']}")

        elif etype == "remove_resistance":
            who = self._resolve_role(effect.get("target", "self"), data)
            if who:
                who.resistances.discard(effect["damage_type"].lower())

        elif etype == "heal":
            who = self._resolve_role(effect.get("target", "self"), data)
            if who:
                healed = who.heal(effect["amount"])
                if healed:
                    print(f"  {self.owner.name}: {self.name} heals {who.name} for {healed}")

        elif etype == "add_temp_hp":
            who = self._resolve_role(effect.get("target", "self"), data)
            if who:
                who.add_temp_hp(effect["amount"])
                print(f"  {self.owner.name}: {self.name} grants {who.name} {effect['amount']} temp HP")

        elif etype == "modify_ac":
            self.owner.apply_misc_ac(effect["delta"])

        elif etype == "grant_extra_attack":
            self.owner.actions.grant_temp_extra_attack()
            print(f"  {self.owner.name}: {self.name} grants an extra attack")

    def _set_adv_disadv(self, trigger: str, data: dict, advantage: bool):
        if trigger == "saving_throw":
            data["advantage" if advantage else "disadvantage"] = True
            return
        attack = data.get("attack")
        if attack:
            if advantage:
                attack.advantage = True
            else:
                attack.disadvantage = True
