from pdb import set_trace as S
class StatBlock:
    def __init__(self, stats, proficiency=2):
        # stats is a dict: {"Str": 12, "Dex": 16, "Con": 14, ...}
        self.scores = stats
        self.proficiency = proficiency
        # Precompute modifiers
        self.mods = {k: (v - 10) // 2 for k, v in stats.items()}
        # Saving throw proficiencies (0 or 1 by default)
        self.save_profs = {k: 0 for k in stats.keys()}

    def mod(self, ability):
        return self.mods.get(ability, 0)

    def save_bonus(self, ability):
        return self.mod(ability) + (self.proficiency if self.save_profs.get(ability, 0) else 0)