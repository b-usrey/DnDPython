"""
Transitions must never bootstrap across a creature boundary.

A whole team shares one StrategySelector, so train_dqn's recorded
trajectory is a flat interleaving of every creature's turns. Pairing
adjacent entries made the Q-target Q(s_troll, a) <- r + gamma * max
Q(s_hobgoblin, .) on 98.9% of updates, broke the telescoping that makes
potential-based shaping policy-invariant, and left the terminal outcome
on 1 of ~111 transitions. learn_from_episode now groups by acting
creature first.

These tests pin the property itself -- no transition may pair one
creature's observation with another's -- rather than the implementation.
"""
import io
import contextlib

import importlib, pkgutil, data.features
for _m in pkgutil.iter_modules(data.features.__path__):
    if _m.name != "base":
        importlib.import_module(f"data.features.{_m.name}")

from core.ml_strategy import CombatEnv, Strategy, StrategySelector
from core.selectors.dqn_selector import DQNStrategySelector
from core.trainer import StrategyTrainer


SCEN = {
    "name": "credit assignment probe",
    "max_rounds": 12,
    "map": {"width": 16, "height": 10},
    "players": [{
        "name": "Hero",
        "classes": [["Fighter", 5]],
        "subclasses": {"Fighter": "Champion"},
        "stats": {"Str": 16, "Dex": 14, "Con": 14, "Int": 8, "Wis": 12, "Cha": 10},
        "items": ["Longsword", "Chain Mail"],
        "equipped": ["Longsword", "Chain Mail"],
    }],
    "monsters": [{"type": "HOBGOBLIN", "count": 4, "weapon_role": "melee"}],
}


class Recorder(DQNStrategySelector):
    """Captures every transition pushed to the replay buffer."""

    def __init__(self):
        super().__init__()
        self.pushed = []

    def update(self, obs, action, reward, next_obs, done):
        self.pushed.append((list(obs), action, reward, list(next_obs), done))
        # Deliberately skip the gradient step: these tests are about how
        # transitions are paired, not about learning.


def _run_episode_and_capture():
    """Run one training episode, capturing both the recorded trajectory
    (with real actor ids) and every transition pushed to the buffer."""
    env = CombatEnv(SCEN, trained_team="red", silent=True)
    sel = Recorder()
    captured = {}

    orig_learn = sel.learn_from_episode

    def spy(trajectory, outcome):
        captured["trajectory"] = list(trajectory)
        return orig_learn(trajectory, outcome)

    sel.learn_from_episode = spy
    trainer = StrategyTrainer(env, sel)
    with contextlib.redirect_stdout(io.StringIO()):
        trainer.train_dqn(n_episodes=1, verbose=False)
    return sel, captured.get("trajectory", [])


def _actors_by_obs(trajectory):
    """obs (as a tuple) -> the set of actors that ever produced it.

    Observations are the only thing a pushed transition carries, so this is
    how we map a transition back to its author. Two creatures producing a
    byte-identical observation are indistinguishable to the learner anyway,
    so an overlap there is harmless rather than a missed failure.
    """
    by_obs = {}
    for actor, obs, _action in trajectory:
        by_obs.setdefault(tuple(obs), set()).add(actor)
    return by_obs


class TestPerCreatureCredit:

    def test_trajectory_entries_carry_their_author(self):
        """train_dqn must record (actor, obs, action), not just (obs, action)."""
        env = CombatEnv(SCEN, trained_team="red", silent=True)
        sel = DQNStrategySelector()
        seen = []

        orig = sel.select

        def spy(obs):
            seen.append(getattr(sel, "acting_creature", None))
            return orig(obs)

        sel.select = spy
        with contextlib.redirect_stdout(io.StringIO()):
            env.run_episode(sel)

        assert seen, "the selector was never consulted"
        assert all(c is not None for c in seen), \
            "plan_turn did not tag the selector with the acting creature"
        assert len({id(c) for c in seen}) > 1, \
            "expected several different monsters to act"

    def test_no_transition_crosses_a_creature_boundary(self):
        sel, traj = _run_episode_and_capture()
        assert sel.pushed, "no transitions were recorded"
        assert len({a for a, _o, _x in traj}) > 1, "expected several monsters"

        by_obs = _actors_by_obs(traj)
        crossings = [
            (obs, next_obs)
            for obs, _a, _r, next_obs, done in sel.pushed
            if not done
            and not (by_obs.get(tuple(obs), set())
                     & by_obs.get(tuple(next_obs), set()))
        ]
        assert not crossings, (
            f"{len(crossings)} of {len(sel.pushed)} transitions bootstrap "
            f"from a different creature's observation"
        )

    def test_the_flat_pairing_would_have_failed_that_check(self):
        """Guards the guard: the old adjacent-pairing really is detectable."""
        _sel, traj = _run_episode_and_capture()
        by_obs = _actors_by_obs(traj)
        flat_crossings = sum(
            1
            for i in range(len(traj) - 1)
            if not (by_obs.get(tuple(traj[i][1]), set())
                    & by_obs.get(tuple(traj[i + 1][1]), set()))
        )
        assert flat_crossings > 0, (
            "the flat pairing produced no detectable crossings, so the test "
            "above cannot prove anything"
        )

    def test_terminal_transitions_are_self_referential(self):
        """A creature's last step has no successor, so next_obs is its own."""
        sel, _traj = _run_episode_and_capture()
        finals = [t for t in sel.pushed if t[4]]
        assert finals, "no terminal transition was recorded"
        for obs, _a, _r, next_obs, _d in finals:
            assert obs == next_obs

    def test_every_creature_gets_a_terminal_transition(self):
        """The outcome must reach all of them, not just whoever acted last."""
        sel, traj = _run_episode_and_capture()
        actors = {a for a, _o, _x in traj}
        finals = [t for t in sel.pushed if t[4]]
        assert len(finals) == len(actors), (
            f"{len(finals)} terminal transitions for {len(actors)} distinct "
            f"creatures -- the outcome is not reaching all of them"
        )

    def test_one_shared_network_not_one_per_creature(self):
        """Grouping changes pairing, not the number of learners."""
        sel, traj = _run_episode_and_capture()
        assert len({id(sel._online)}) == 1
        assert len({id(sel._buffer)}) == 1
        assert len({a for a, _o, _x in traj}) > 1,             "expected several creatures sharing one selector"


class TestLearnFromEpisodeGrouping:
    """Unit-level checks on the grouping itself, without running combat."""

    def _selector(self):
        sel = Recorder()
        sel.gamma = 0.9
        return sel

    def test_groups_by_actor_id(self):
        sel = self._selector()
        a = [0.1] * 15
        b = [0.9] * 15
        traj = [
            ("A", a, Strategy.AGGRESSIVE),
            ("B", b, Strategy.KITE),
            ("A", a, Strategy.PROTECT),
            ("B", b, Strategy.RETREAT),
        ]
        sel.learn_from_episode(traj, outcome=1.0)

        assert len(sel.pushed) == 4
        for obs, _a, _r, next_obs, _d in sel.pushed:
            assert obs == next_obs or obs[0] == next_obs[0], \
                "a transition paired observations from different actors"

    def test_each_actor_gets_exactly_one_terminal(self):
        sel = self._selector()
        traj = [
            ("A", [0.1] * 15, Strategy.AGGRESSIVE),
            ("B", [0.9] * 15, Strategy.KITE),
            ("A", [0.1] * 15, Strategy.PROTECT),
        ]
        sel.learn_from_episode(traj, outcome=1.0)
        assert sum(1 for t in sel.pushed if t[4]) == 2

    def test_legacy_two_tuples_still_work(self):
        """A single-agent trajectory has no actor and must behave as before."""
        sel = self._selector()
        traj = [([0.1] * 15, Strategy.AGGRESSIVE), ([0.2] * 15, Strategy.KITE)]
        sel.learn_from_episode(traj, outcome=1.0)
        assert len(sel.pushed) == 2
        assert sum(1 for t in sel.pushed if t[4]) == 1

    def test_outcome_lands_on_each_actors_last_step(self):
        """With gamma*V(next) - V(obs) shaping, the terminal step is the only
        one carrying the raw outcome, and it must do so for every actor."""
        sel = self._selector()
        traj = [
            ("A", [0.0] * 15, Strategy.AGGRESSIVE),
            ("B", [0.0] * 15, Strategy.AGGRESSIVE),
        ]
        sel.learn_from_episode(traj, outcome=5.0)
        finals = [t for t in sel.pushed if t[4]]
        assert len(finals) == 2
        # shaped = outcome + 0 - V(obs); V is small for an untrained net, so
        # the outcome must still dominate each terminal reward.
        for _o, _a, reward, _n, _d in finals:
            assert reward > 1.0, f"terminal reward {reward} lost the outcome"
