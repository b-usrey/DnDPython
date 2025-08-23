import random
class CombatManager:
    def __init__(self, creatures,factory=None):
        """
        creatures: list of Creature instances
        factory: optional CreatureFactory (for lookups/registry)
        """
        self.factory = factory
        self.creatures = creatures[:]  # active creatures (will be pruned as they die)
        self.round = 0
        self.initiative_order = []
    def roll_initiative_once(self):
        """Roll initiative for all creatures once at start of combat."""
        for c in self.creatures:
            c.roll_initiative()
        self.initiative_order = sorted(
            [c for c in self.creatures if c.is_alive()],
            key=lambda x: getattr(x, "initiative_roll", 0),
            reverse=True
        )
        print("Initiative order:")
        for i, c in enumerate(self.initiative_order, 1):
            init = getattr(c, "initiative_roll", None)
            tag = getattr(c, "display_name", lambda: c.name)()
            print(f"  {i}. {tag} (init {init})")

    def remove_dead(self):
        self.creatures = [c for c in self.creatures if c.is_alive()]

    def get_targets_for(self, actor):
        """Return living enemies for actor:
           We assume actor has boolean attribute `is_monster` (True for monsters).
           Enemies are creatures where is_monster != actor.is_monster and is_alive.
        """
        return [c for c in self.creatures if c.is_alive() and getattr(c, "is_monster", False) != getattr(actor, "is_monster", False)]

    def run(self):
        """Run full combat until one side is eliminated."""
        # initial set up: roll initiative once
        self.roll_initiative_once()

        # use this initiative order for whole combat; update order when new creatures are added/removed
        while True:
            self.round += 1
            print(f"\n=== ROUND {self.round} ===")
            # iterate over snapshot of initiative order (filtered for alive)
            for actor in list(self.initiative_order):
                if not actor.is_alive():
                    continue
                # ensure actor still in active creature list
                if actor not in self.creatures:
                    continue

                # start of turn housekeeping
                if hasattr(actor, "start_turn"):
                    actor.start_turn()

                # choose targets (monsters target any non-monster)
                targets = self.get_targets_for(actor)

                if not targets:
                    # no enemies remain -> combat ends
                    print("\nCombat ended early (no enemies remain for {})".format(getattr(actor, "name", "Actor")))
                    self.declare_winner()
                    return

                # Actor action logic
                # default flow: use Action to attack; supports multi-attack
                # We track per-turn context (first-hit tracking etc.)
                turn_context = {"hit_done": False}
                num_attacks = getattr(actor, "num_attacks", 1)

                for attack_index in range(num_attacks):
                    # allow dynamic target switching: pick a target from available list each attack
                    targets = self.get_targets_for(actor)
                    if not targets:
                        break
                    # simple target selection: pick lowest HP target (or random)
                    target = min(targets, key=lambda t: t.hp)

                    # expect actor to have choose_attack(target) -> returns an Attack object OR to have attacks list
                    attack_obj = None
                    # try a few common patterns gracefully:
                    if hasattr(actor, "choose_attack"):
                        try:
                            attack_obj = actor.choose_attack(target=target, attack_number=attack_index+1)
                        except TypeError:
                            # choose_attack might accept only (target) or none
                            try:
                                attack_obj = actor.choose_attack(target)
                            except TypeError:
                                try:
                                    attack_obj = actor.choose_attack()
                                except Exception:
                                    attack_obj = None
                    # fallback: if actor has attacks list, pick first or cycle
                    if attack_obj is None:
                        atks = getattr(actor, "attacks", [])
                        if atks:
                            attack_obj = atks[min(attack_index, len(atks)-1)]

                    # If still no attack object, skip
                    if attack_obj is None:
                        print(f"{actor.display_name() if hasattr(actor,'display_name') else actor.name} has no attack to perform.")
                        break

                    # perform attack — support both .perform(...) and .execute(...) names
                    performed = False
                    if hasattr(attack_obj, "perform"):
                        # signature expected: perform(attacker, target, attack_number=..., context=...)
                        try:
                            attack_obj.perform(actor, target, attack_number=attack_index+1, context=turn_context)
                            performed = True
                        except TypeError:
                            # fallback to less-arg perform
                            attack_obj.perform(actor, target)
                            performed = True
                    elif hasattr(attack_obj, "execute"):
                        try:
                            attack_obj.execute(actor, target)
                            performed = True
                        except TypeError:
                            attack_obj.execute(actor, target, attack_index+1, turn_context)
                            performed = True
                    else:
                        # if attack_obj is a simple tuple/dict, attempt simple resolution
                        try:
                            # Attack-like dict: {"name":..,"damage_die":..,"attack_bonus":..}
                            name = attack_obj.get("name", "Attack")
                            atk_bonus = attack_obj.get("attack_bonus", 0)
                            dmg_die = attack_obj.get("damage_die", 6)
                            roll = random.randint(1, 20) + getattr(actor, "attack_bonus", 0) + atk_bonus
                            if roll >= target.ac:
                                dmg = random.randint(1, dmg_die)
                                target.hp -= dmg
                                print(f"{actor.display_name() if hasattr(actor,'display_name') else actor.name} hits {target.display_name() if hasattr(target,'display_name') else target.name} with {name} for {dmg} damage!")
                            else:
                                print(f"{actor.display_name() if hasattr(actor,'display_name') else actor.name} misses {target.display_name() if hasattr(target,'display_name') else target.name}.")
                            performed = True
                        except Exception:
                            performed = False

                    # after attack bookkeeping: if target died, announce
                    if performed and not target.is_alive():
                        print(f"💀 {target.display_name() if hasattr(target,'display_name') else target.name} falls!")

                    # quick victory check after each attack
                    if not any(not c.is_monster and c.is_alive() for c in self.creatures):
                        self.declare_winner()
                        return
                    if not any(c.is_monster and c.is_alive() for c in self.creatures):
                        self.declare_winner()
                        return

                # end of actor's turn (bonus actions, reactions could be handled here)
                # Optionally we could call actor.end_turn() if you have one

            # round end: remove dead and rebuild initiative order for next round (keeps original ordering of survivors)
            self.remove_dead()
            # Recompute initiative_order while preserving the original relative order among survivors:
            self.initiative_order = [c for c in self.initiative_order if c.is_alive()]
            # If any new creatures were added mid-combat you'd insert them here (not covered by this snippet)

    def declare_winner(self):
        pcs_alive = [c for c in self.creatures if not getattr(c, "is_monster", False) and c.is_alive()]
        monsters_alive = [c for c in self.creatures if getattr(c, "is_monster", False) and c.is_alive()]
        if pcs_alive and not monsters_alive:
            print("\n=== PCs are victorious! ===")
        elif monsters_alive and not pcs_alive:
            print("\n=== Monsters win! ===")
        else:
            print("\n=== Combat ended inconclusively ===")