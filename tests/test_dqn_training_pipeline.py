"""
Tests for the overnight-run hardening of the DQN training pipeline
(core/trainer.py, core/ml_strategy.py):

  - StrategyTrainer.collect_demonstrations() -- gathers the (obs, action)
    set that the imitation warm start clones from, without altering the
    teacher.
  - train_dqn(save_every=...) -- checkpoints weights + log mid-run, so an
    8-hour run that dies at hour 7 leaves hour 7 behind.
  - The progress bar's win% is the real win rate, not "reward > 0" (kills
    and damage rewards can push a lost fight's shaped reward positive).
  - CombatEnv's no-trained-creature fallback obs is as wide as the real
    state vector.
"""
import io
import contextlib

import pytest

import importlib, pkgutil, data.features
for _m in pkgutil.iter_modules(data.features.__path__):
    if _m.name != "base":
        importlib.import_module(f"data.features.{_m.name}")

from core.ml_strategy import CombatEnv, Strategy, TrainingLog
from core.selectors.dqn_selector import DQNStrategySelector, N_OBS
from core.selectors.heuristic_selector import HeuristicStrategySelector
from core.trainer import StrategyTrainer


# Small and short so a handful of episodes takes milliseconds.
SCENARIO = {
    "name": "Pipeline test",
    "max_rounds": 3,
    "map": {"width": 10, "height": 8, "walls": [], "difficult_terrain": []},
    "positions": {"Hero": [1, 4], "monsters": [[6, 3], [6, 5]]},
    "players": [{
        "name": "Hero",
        "classes": [["Fighter", 3]],
        "subclasses": {},
        "stats": {"Str": 16, "Dex": 12, "Con": 14, "Int": 10, "Wis": 10, "Cha": 8},
        "choices": [],
        "items": ["Longsword"],
        "equipped": ["Longsword"],
        "features": [],
    }],
    "monsters": [{"type": "GOBLIN", "count": 2, "weapon_role": "melee"}],
}


def make_env():
    return CombatEnv(scenario_data=SCENARIO, trained_team="red", silent=True)


def make_dqn():
    return DQNStrategySelector(hidden=(16, 8), batch_size=8, buffer_size=200)


# ---------------------------------------------------------------------------
# collect_demonstrations
# ---------------------------------------------------------------------------

class TestCollectDemonstrations:
    def test_returns_paired_obs_and_actions(self):
        trainer = StrategyTrainer(make_env(), make_dqn())
        obs, acts = trainer.collect_demonstrations(HeuristicStrategySelector(), n_episodes=3)

        assert len(obs) == len(acts) > 0
        assert all(len(o) == N_OBS for o in obs)
        assert all(isinstance(a, Strategy) for a in acts)

    def test_leaves_teacher_unmodified(self):
        teacher = HeuristicStrategySelector()
        original = teacher.select
        trainer = StrategyTrainer(make_env(), make_dqn())

        trainer.collect_demonstrations(teacher, n_episodes=2)

        # The recording wrapper must be removed even though it was installed
        # on the instance -- a leaked wrapper would keep growing the lists.
        assert teacher.select == original

    def test_demonstrations_feed_imitate(self):
        sel = make_dqn()
        trainer = StrategyTrainer(make_env(), sel)
        obs, acts = trainer.collect_demonstrations(HeuristicStrategySelector(), n_episodes=4)

        losses = sel.imitate(obs, acts, epochs=8)

        assert len(losses) == 8
        assert losses[-1] < losses[0]


# ---------------------------------------------------------------------------
# save_every checkpointing
# ---------------------------------------------------------------------------

class TestSaveEvery:
    def test_checkpoints_at_the_requested_cadence(self, tmp_path):
        sel = make_dqn()
        trainer = StrategyTrainer(make_env(), sel)
        log = TrainingLog("t")
        weights = tmp_path / "w.pt"
        csv, js = tmp_path / "l.csv", tmp_path / "l.json"

        save_calls = []
        real_save = sel.save
        sel.save = lambda p: (save_calls.append(p), real_save(p))

        with contextlib.redirect_stdout(io.StringIO()):
            trainer.train_dqn(n_episodes=6, verbose=False, log=log,
                              save_every=2, save_path=str(weights),
                              log_paths=(str(csv), str(js)))

        # Episodes 2, 4, 6 -> three checkpoints from inside the loop.
        assert save_calls == [str(weights)] * 3
        assert weights.exists() and csv.exists() and js.exists()

    def test_no_checkpoint_when_disabled(self, tmp_path):
        sel = make_dqn()
        trainer = StrategyTrainer(make_env(), sel)
        save_calls = []
        sel.save = lambda p: save_calls.append(p)

        with contextlib.redirect_stdout(io.StringIO()):
            trainer.train_dqn(n_episodes=4, verbose=False)

        assert save_calls == []

    def test_save_every_without_path_is_rejected(self):
        trainer = StrategyTrainer(make_env(), make_dqn())
        with pytest.raises(ValueError):
            trainer.train_dqn(n_episodes=2, verbose=False, save_every=1)


# ---------------------------------------------------------------------------
# Progress bar reports the real win rate
# ---------------------------------------------------------------------------

class TestProgressWinRate:
    def test_bar_matches_logged_wins_not_reward_sign(self):
        sel = make_dqn()
        trainer = StrategyTrainer(make_env(), sel)
        log = TrainingLog("t")
        n = 6

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            trainer.train_dqn(n_episodes=n, verbose=True, print_every=n, log=log)

        real_rate = sum(e["win"] for e in log.episodes) / n
        assert f"win_rate={real_rate:.0%}" in buf.getvalue()


# ---------------------------------------------------------------------------
# Fallback obs width
# ---------------------------------------------------------------------------

class TestFallbackObsWidth:
    def test_matches_state_vector_when_no_trained_creature_is_alive(self):
        env = make_env()
        with contextlib.redirect_stdout(io.StringIO()):
            env.reset()
            for _, c in env.cm.initiative.initiative_order:
                if c.team == "red":
                    c.hp = 0
            obs = env._get_obs_for_next_trained_creature()

        assert len(obs) == N_OBS
