"""
data/features/wizard_features.py

Wizard class features.

Base wizard
  lv1   Arcane Recovery    Short rest: regain slots up to half wizard level. Non-combat stub.
  lv2   Arcane Tradition   Subclass selection stub.
  lv18  Spell Mastery      Free cast of chosen 1st/2nd level spells. Non-combat stub.
  lv20  Signature Spells   Two 3rd-level always-prepared free-cast spells. Non-combat stub.

Evocation subclass
  lv2   Sculpt Spells       Protect allies from evocation AoE. Non-combat stub.
  lv6   Potent Cantrip      Half damage on successful save vs cantrip. Non-combat stub.
  lv10  Empowered Evocation +INT mod to evocation spell damage rolls. Non-combat stub.
  lv14  Overchannel         Maximize damage of spells ≤ 5th level. Non-combat stub.

Abjuration subclass
  lv2   Arcane Ward         HP barrier from abjuration spells. Non-combat stub.
  lv6   Projected Ward      Redirect Arcane Ward to protect allies. Non-combat stub.
  lv10  Improved Abjuration +PB to abjuration ability checks. Non-combat stub.
  lv14  Spell Resistance    Advantage vs spells; resistance to spell damage. Non-combat stub.

All subclass features are non-combat stubs — they register in Feature.REGISTRY so
character loading doesn't emit warnings, but they have no runtime effect.
"""
from data.features.base import Feature


# ---------------------------------------------------------------------------
# Base class stubs
# ---------------------------------------------------------------------------

class ArcaneRecovery(Feature):
    """Short rest: regain spell slots whose total level ≤ half wizard level. Non-combat."""
    name = "Arcane Recovery"


class ArcaneTradition(Feature):
    """Arcane Tradition subclass selection at level 2."""
    name = "Arcane Tradition"


class ArcaneTraditionFeature(Feature):
    """Subclass feature granted at levels 6, 10, and 14."""
    name = "Arcane Tradition Feature"


class SpellMastery(Feature):
    """
    Level 18: choose one 1st-level and one 2nd-level spell to cast without
    expending a spell slot. Non-combat stub.
    """
    name = "Spell Mastery"


class SignatureSpells(Feature):
    """
    Level 20: two 3rd-level spells always prepared; one free cast each per
    short rest. Non-combat stub.
    """
    name = "Signature Spells"


# ---------------------------------------------------------------------------
# Evocation subclass stubs
# ---------------------------------------------------------------------------

class SculptSpells(Feature):
    """Evocation lv2: protect allies inside your evocation AoE. Non-combat stub."""
    name = "Sculpt Spells"


class PotentCantrip(Feature):
    """Evocation lv6: cantrip save deals half damage on success. Non-combat stub."""
    name = "Potent Cantrip"


class EmpoweredEvocation(Feature):
    """Evocation lv10: add INT modifier to evocation spell damage. Non-combat stub."""
    name = "Empowered Evocation"


class Overchannel(Feature):
    """Evocation lv14: maximize damage of a spell of 5th level or lower. Non-combat stub."""
    name = "Overchannel"


# ---------------------------------------------------------------------------
# Abjuration subclass stubs
# ---------------------------------------------------------------------------

class ArcaneWard(Feature):
    """Abjuration lv2: HP barrier that absorbs incoming damage. Non-combat stub."""
    name = "Arcane Ward"


class ProjectedWard(Feature):
    """Abjuration lv6: redirect Arcane Ward barrier to protect an ally. Non-combat stub."""
    name = "Projected Ward"


class ImprovedAbjuration(Feature):
    """Abjuration lv10: add proficiency bonus to abjuration spell checks. Non-combat stub."""
    name = "Improved Abjuration"


class SpellResistance(Feature):
    """Abjuration lv14: advantage on saving throws vs spells; resistance to spell damage. Non-combat stub."""
    name = "Spell Resistance"
