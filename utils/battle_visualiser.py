"""
utils/battle_visualiser.py

Pluggable matplotlib visualiser for the encounter framework.

Constructor parameters
----------------------
battle_map     : BattleMap
event          : EventBus
combat_mgr     : CombatManager
trail_turns    : int | None
    How many turns of movement history to display.
      1          → current turn only (default)
      N          → last N completed turns + current turn
      None       → every turn of the whole combat
save_video     : bool      — write combat.mp4 at end (default False)
video_path     : str       — output path  (default "combat.mp4")
frame_duration : float     — seconds each frame is shown in the video (default 1.5)
max_log        : int       — max log lines visible (default 18)
figsize        : (w, h)    — matplotlib figure size in inches (default (14, 8))

Keyboard shortcuts while window is open
----------------------------------------
    Any key / close  →  advance to next turn
    Q                →  quit combat entirely
"""

from __future__ import annotations

import io
import os
import textwrap
from typing import TYPE_CHECKING

import matplotlib
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from core.battle_map import BattleMap
    from core.combat_manager import CombatManager


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

TERRAIN_COLOURS = {
    "normal":    "#f2e8d5",
    "difficult": "#b5956a",
    "wall":      "#2e2520",
    "water":     "#4e90b8",
}

TEAM_COLOURS = {
    "blue":  "#2563a8",
    "red":   "#c0392b",
    "green": "#27ae60",
    "gold":  "#d4ac0d",
}

DOWNED_COLOUR  = "#6b6b6b"
DOWNED_BORDER  = "#444444"
ACTIVE_RING    = "#f5c518"
TOKEN_LABEL    = "#ffffff"

GRID_LINE      = "#c9b99a"
MAP_BG         = "#e8dcc8"
THREATENED_FILL = (0.98, 0.80, 0.18, 0.13)
THREATENED_EDGE = "#e8b800"

FIG_BG      = "#1c1812"
TITLE_COL   = "#f0e0c0"
HINT_COL    = "#6b5c48"

LOG_BG      = "#16120e"
LOG_BORDER  = "#3a3025"
LOG_TITLE   = "#f5c518"
LOG_BRIGHT  = "#f0e0c0"
LOG_NORMAL  = "#9a8878"

HP_HIGH = "#27ae60"
HP_MID  = "#e67e22"
HP_LOW  = "#e74c3c"
HP_BG   = "#2a2520"

# Trail rendering constants
TRAIL_ALPHA_ACTIVE  = 0.70   # opacity for the current (active) turn trail
TRAIL_ALPHA_RECENT  = 0.40   # opacity for the most-recent completed turn
TRAIL_ALPHA_OLDEST  = 0.08   # opacity for the oldest shown turn
TRAIL_WIDTH_ACTIVE  = 2.0    # line width for active-turn trail
TRAIL_WIDTH_HISTORY = 1.2    # line width for historical trails
TRAIL_WAYPOINT_R    = 0.055  # radius of waypoint dots


# ---------------------------------------------------------------------------
# BattleVisualiser
# ---------------------------------------------------------------------------

class BattleVisualiser:

    MAX_LOG_LINES = 18

    def __init__(
        self,
        battle_map: "BattleMap",
        event,
        combat_mgr: "CombatManager",
        trail_turns:    int | None = 1,
        save_video:     bool  = False,
        video_path:     str   = "combat.mp4",
        frame_duration: float = 1.5,
        silent:         bool | None = None,   # None = auto (True when save_video=True)
        max_log:        int   = MAX_LOG_LINES,
        figsize:        tuple = (14, 8),
    ):
        self.battle_map     = battle_map
        self.event          = event
        self.combat_mgr     = combat_mgr
        self.trail_turns    = trail_turns
        self.save_video     = save_video
        self.video_path     = video_path
        self.frame_duration = frame_duration
        self.silent         = save_video if silent is None else silent
        self.max_log        = max_log
        self.figsize        = figsize

        # ── Core display state ─────────────────────────────────────────
        self._log:          list          = []
        self._round:        int           = 1
        self._active:       object | None = None
        self._quit:         bool          = False
        self._key_pressed:  bool          = False

        # ── Trail history ──────────────────────────────────────────────
        # Full per-creature history: creature → [(round_num, [waypoints])]
        # One entry per completed turn. Waypoints are (col, row) tuples.
        self._trail_history: dict = {}

        # Waypoints being collected for the current (in-progress) turn.
        # creature → [(col, row), ...]
        self._active_trail: dict = {}

        # ── Dead creature positions ────────────────────────────────────
        # creature → (col, row) at time of removal
        self._dead_creatures: dict = {}

        # ── Video frame buffer ─────────────────────────────────────────
        # Each element is a uint8 RGB numpy array (H × W × 3)
        self._frames: list = []

        # ── Subscribe to events ────────────────────────────────────────
        event.subscribe("TurnStarted",        self._on_turn_started)
        event.subscribe("TurnEnded",          self._on_turn_ended)
        event.subscribe("RoundStarted",       self._on_round_started)
        event.subscribe("CombatStarted",      self._on_combat_started)
        event.subscribe("attack",             self._on_attack)
        event.subscribe("damage",             self._on_damage)
        event.subscribe("creature_downed",    self._on_downed)
        event.subscribe("opportunity_attack", self._on_opportunity_attack)

        # ── Patch BattleMap.commit_move → record active trail ──────────
        _bmap = battle_map
        _vis  = self

        _orig_commit = _bmap.commit_move
        def _patched_commit(creature, new_col, new_row):
            _orig_commit(creature, new_col, new_row)
            trail = _vis._active_trail.setdefault(creature, [])
            if not trail or trail[-1] != (new_col, new_row):
                trail.append((new_col, new_row))
        _bmap.commit_move = _patched_commit

        # ── Patch BattleMap.remove → capture death position ────────────
        _orig_remove = _bmap.remove
        def _patched_remove(creature):
            pos = _bmap.get_position(creature)
            if pos is not None:
                _vis._dead_creatures[creature] = pos
            _orig_remove(creature)
        _bmap.remove = _patched_remove

        # ── Patch CombatManager._run_turn → show map after each turn ───
        _orig_run_turn = combat_mgr._run_turn
        def _patched_run_turn(creature):
            _orig_run_turn(creature)
            if not _vis._quit:
                _vis._show_turn()
        combat_mgr._run_turn = _patched_run_turn

        # ── Patch run() → show final state + save video ────────────────
        _orig_run = combat_mgr.run
        def _patched_run():
            result = _orig_run()
            if not _vis._quit:
                _vis._log_line("═" * 36)
                _vis._log_line(f"COMBAT OVER  —  {result}")
                _vis._show_turn(final=True)
            if _vis.save_video and _vis._frames:
                _vis._write_video()
            return result
        combat_mgr.run = _patched_run

        matplotlib.rcParams["toolbar"] = "None"
        plt.ion()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_combat_started(self, data):
        self._round = 1
        self._log_line("═" * 36)
        self._log_line("  COMBAT BEGINS")
        self._log_line("═" * 36)
        # Seed every creature's starting position as the first waypoint
        for creature, pos in self.battle_map._positions.items():
            self._active_trail[creature] = [pos]

    def _on_round_started(self, data):
        self._round = data.get("round", self._round)
        self._log_line(f"── Round {self._round} {'─' * (28 - len(str(self._round)))}")

    def _on_turn_started(self, data):
        creature = data.get("creature")
        if not creature:
            return
        self._active = creature

        # Freeze the previous active trail for this creature into history
        self._freeze_active_trail(creature)

        # Start a fresh active trail seeded from current position
        pos = self.battle_map.get_position(creature)
        self._active_trail[creature] = [pos] if pos else []

        hp_str = f"HP {creature.hp}/{creature.max_hp}"
        self._log_line(f"▶  {creature.name}  ({hp_str})", bright=True)

    def _on_turn_ended(self, data):
        self._active = None

    def _on_attack(self, data):
        attacker = data.get("attacker")
        target   = data.get("target")
        attack   = data.get("attack")
        if attacker and target:
            weapon_str = ""
            if attack:
                item = getattr(attack, "item", None) or getattr(attack, "_item", None)
                if item and hasattr(item, "name"):
                    weapon_str = f" w/ {item.name}"
            self._log_line(f"  {attacker.name} → {target.name}{weapon_str}")

    def _on_damage(self, data):
        attack = data.get("attack")
        if attack:
            hit    = attack.result.get("hit", False)
            roll   = attack.result.get("hit_roll", "?")
            total  = attack.result.get("attack_total", "?")
            damage = attack.result.get("damage")
            if hit:
                dmg_str = f" → {damage} dmg" if damage is not None else ""
                self._log_line(f"    Hit! ({roll}+mod={total}){dmg_str}")
            else:
                self._log_line(f"    Miss ({roll}+mod={total})")

    def _on_downed(self, data):
        creature = data.get("creature")
        if creature:
            self._log_line(f"  ✕  {creature.name} is downed!", bright=True)

    def _on_opportunity_attack(self, data):
        attacker = data.get("attacker")
        target   = data.get("target")
        if attacker and target:
            self._log_line(f"  ⚡ OA: {attacker.name} → {target.name}")

    # ------------------------------------------------------------------
    # Trail history helpers
    # ------------------------------------------------------------------

    def _freeze_active_trail(self, creature) -> None:
        """
        Move the current active trail into the history list for this creature.
        Only stores it if there are at least 2 waypoints (i.e. the creature moved).
        """
        trail = self._active_trail.get(creature, [])
        if len(trail) >= 2:
            history = self._trail_history.setdefault(creature, [])
            history.append((self._round, list(trail)))

    def _get_visible_trails(self, creature) -> list[tuple[int, list, bool]]:
        """
        Return the trail segments to draw for this creature, as a list of
        (round_num, waypoints, is_active) tuples ordered oldest → newest.

        trail_turns=None  → all history + active
        trail_turns=1     → active turn only
        trail_turns=N     → last N-1 completed turns + active
        """
        history = self._trail_history.get(creature, [])
        active  = self._active_trail.get(creature, [])

        if self.trail_turns is None:
            # All history
            segments = [(rnd, wp, False) for rnd, wp in history]
        elif self.trail_turns <= 1:
            # Active turn only
            segments = []
        else:
            # Last (trail_turns - 1) completed turns
            keep = history[-(self.trail_turns - 1):]
            segments = [(rnd, wp, False) for rnd, wp in keep]

        # Append active trail if it has any movement
        if len(active) >= 2:
            segments.append((self._round, active, True))

        return segments

    # ------------------------------------------------------------------
    # Log helper
    # ------------------------------------------------------------------

    def _log_line(self, text: str, bright: bool = False):
        for line in textwrap.wrap(text, width=38) or [text]:
            self._log.append(("bright" if bright else "normal", line))
        if len(self._log) > self.max_log:
            self._log = self._log[-self.max_log:]

    # ------------------------------------------------------------------
    # Render + display
    # ------------------------------------------------------------------

    def _build_figure(self, final: bool = False) -> plt.Figure:
        """Create and return a fully rendered figure. Caller owns it."""
        fig = plt.figure(figsize=self.figsize, facecolor=FIG_BG)
        gs  = fig.add_gridspec(
            1, 2, width_ratios=[0.68, 0.32],
            left=0.02, right=0.98,
            top=0.93, bottom=0.04,
            wspace=0.04,
        )
        ax_map = fig.add_subplot(gs[0])
        ax_log = fig.add_subplot(gs[1])

        self._draw_map(ax_map)
        self._draw_log(ax_log)

        if final:
            title = "Combat Over"
        elif self._active:
            title = f"Round {self._round}  —  {self._active.name}'s turn"
        else:
            title = f"Round {self._round}"

        fig.suptitle(title, fontsize=13, fontweight="bold",
                     color=TITLE_COL, y=0.98)
        fig.text(0.5, 0.005,
                 "Press any key or close window to continue",
                 ha="center", fontsize=8, color=HINT_COL, style="italic")

        try:
            fig.canvas.manager.set_window_title(
                f"Battle Map  —  Round {self._round}"
            )
        except Exception:
            pass

        return fig

    def _capture_frame(self, fig: plt.Figure) -> None:
        """Render fig to a numpy RGB array and append to _frames."""
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100,
                    facecolor=fig.get_facecolor(), bbox_inches="tight")
        buf.seek(0)
        img = np.array(Image.open(buf).convert("RGB"))
        self._frames.append(img)

    def _show_turn(self, final: bool = False) -> None:
        """Render the map, optionally capture a video frame, then block."""
        fig = self._build_figure(final=final)

        if self.save_video:
            self._capture_frame(fig)

        if self.silent:
            plt.close(fig)
            return

        self._key_pressed = False

        def on_key(event):
            if event.key and event.key.lower() == "q":
                self._quit = True
            self._key_pressed = True
            plt.close(fig)

        def on_close(event):
            self._key_pressed = True

        fig.canvas.mpl_connect("key_press_event", on_key)
        fig.canvas.mpl_connect("close_event",     on_close)

        plt.show(block=False)
        plt.pause(0.1)

        while not self._key_pressed and plt.fignum_exists(fig.number):
            plt.pause(0.05)

        plt.close("all")

    # ------------------------------------------------------------------
    # Video export
    # ------------------------------------------------------------------

    def _write_video(self) -> None:
        """
        Write all captured frames to self.video_path as an MP4.
        Each frame is held for self.frame_duration seconds.
        """
        import imageio

        if not self._frames:
            print("[Visualiser] No frames captured — skipping video export.")
            return

        fps = max(1, round(1.0 / self.frame_duration))

        # imageio needs all frames the same shape — pad if needed
        h = max(f.shape[0] for f in self._frames)
        w = max(f.shape[1] for f in self._frames)
        padded = []
        for frame in self._frames:
            fh, fw = frame.shape[:2]
            if fh < h or fw < w:
                canvas = np.full((h, w, 3), 28, dtype=np.uint8)  # FIG_BG ≈ #1c1812
                canvas[:fh, :fw] = frame
                padded.append(canvas)
            else:
                padded.append(frame)

        # Each frame repeated to fill its duration at the chosen fps
        repeats = max(1, round(self.frame_duration * fps))
        expanded = []
        for frame in padded:
            expanded.extend([frame] * repeats)

        out_path = self.video_path
        try:
            imageio.mimsave(out_path, expanded, fps=fps, macro_block_size=None)
            abs_path = os.path.abspath(out_path)
            print(f"\n[Visualiser] Video saved → {abs_path}")
            print(f"             {len(self._frames)} frames × "
                  f"{self.frame_duration}s  ({fps} fps, "
                  f"{self.frame_duration * len(self._frames):.1f}s total)")
        except Exception as e:
            # Fallback: save as GIF
            gif_path = os.path.splitext(out_path)[0] + ".gif"
            try:
                imageio.mimsave(gif_path, expanded, fps=fps)
                print(f"\n[Visualiser] MP4 failed ({e}), GIF saved → {gif_path}")
            except Exception as e2:
                print(f"\n[Visualiser] Video export failed: {e2}")

    # ------------------------------------------------------------------
    # Map drawing
    # ------------------------------------------------------------------

    def _draw_map(self, ax: plt.Axes) -> None:
        bmap   = self.battle_map
        width  = bmap.width
        height = bmap.height

        ax.set_facecolor(MAP_BG)
        ax.set_xlim(-0.5, width  - 0.5)
        ax.set_ylim(-0.5, height - 0.5)
        ax.set_aspect("equal")
        ax.invert_yaxis()

        # ── Terrain tiles ──────────────────────────────────────────────
        for row in range(height):
            for col in range(width):
                tile   = bmap.get_tile(col, row)
                colour = TERRAIN_COLOURS.get(tile.terrain_type, TERRAIN_COLOURS["normal"])
                ax.add_patch(mpatches.FancyBboxPatch(
                    (col - 0.5, row - 0.5), 1, 1,
                    boxstyle="square,pad=0",
                    facecolor=colour, edgecolor=GRID_LINE, linewidth=0.4,
                ))

        # ── Threatened squares for active creature ────────────────────
        if self._active and bmap.get_position(self._active):
            for (tc, tr) in bmap.get_threatened_squares(self._active):
                ax.add_patch(mpatches.FancyBboxPatch(
                    (tc - 0.5, tr - 0.5), 1, 1,
                    boxstyle="square,pad=0",
                    facecolor=THREATENED_FILL,
                    edgecolor=THREATENED_EDGE, linewidth=0.6, linestyle="--",
                ))

        # ── Movement trails (below tokens) ─────────────────────────────
        self._draw_all_trails(ax)

        # ── Dead creature tokens (below living) ─────────────────────────
        for creature, (col, row) in self._dead_creatures.items():
            self._draw_dead_token(ax, creature, col, row)

        # ── Living creatures ───────────────────────────────────────────
        for creature, (col, row) in bmap._positions.items():
            self._draw_creature(ax, creature, col, row)

        # ── Axis labels ────────────────────────────────────────────────
        ax.set_xticks(range(width))
        ax.set_xticklabels([str(c % 10) for c in range(width)],
                           fontsize=7, color=HINT_COL)
        ax.set_yticks(range(height))
        ax.set_yticklabels([str(r % 10) for r in range(height)],
                           fontsize=7, color=HINT_COL)
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_edgecolor(LOG_BORDER)
            spine.set_linewidth(0.8)

    # ------------------------------------------------------------------
    # Trail drawing
    # ------------------------------------------------------------------

    def _draw_all_trails(self, ax: plt.Axes) -> None:
        """Draw movement history for all creatures per trail_turns setting."""
        all_creatures = (
            list(self.battle_map._positions.keys()) +
            list(self._dead_creatures.keys())
        )
        for creature in all_creatures:
            segments = self._get_visible_trails(creature)
            if not segments:
                continue
            self._draw_creature_trail(ax, creature, segments)

    def _draw_creature_trail(self, ax, creature, segments) -> None:
        """
        Draw trail segments for one creature.
        segments: [(round_num, waypoints, is_active), ...]  oldest → newest
        """
        team_colour = TEAM_COLOURS.get(creature.team, "#888888")
        n = len(segments)

        for seg_idx, (round_num, waypoints, is_active) in enumerate(segments):
            if len(waypoints) < 2:
                continue

            # Age-based alpha: oldest segment = TRAIL_ALPHA_OLDEST,
            # most recent / active = TRAIL_ALPHA_ACTIVE
            if n == 1:
                base_alpha = TRAIL_ALPHA_ACTIVE if is_active else TRAIL_ALPHA_RECENT
            else:
                t = seg_idx / (n - 1)   # 0.0 = oldest, 1.0 = newest
                if is_active:
                    base_alpha = TRAIL_ALPHA_ACTIVE
                else:
                    base_alpha = TRAIL_ALPHA_OLDEST + t * (TRAIL_ALPHA_RECENT - TRAIL_ALPHA_OLDEST)

            lw = TRAIL_WIDTH_ACTIVE if is_active else TRAIL_WIDTH_HISTORY

            n_segs = len(waypoints) - 1
            for i in range(n_segs):
                x0, y0 = waypoints[i]
                x1, y1 = waypoints[i + 1]

                # Within-segment fade: first step slightly dimmer
                seg_frac  = (i + 1) / n_segs
                seg_alpha = base_alpha * (0.6 + 0.4 * seg_frac)

                ax.plot(
                    [x0, x1], [y0, y1],
                    color=team_colour, alpha=seg_alpha,
                    linewidth=lw, solid_capstyle="round",
                    zorder=2,
                )

            # Waypoint dots at each non-final position
            for i, (col, row) in enumerate(waypoints[:-1]):
                frac  = i / max(n_segs, 1)
                dot_a = base_alpha * (0.5 + 0.5 * frac)
                ax.add_patch(plt.Circle(
                    (col, row), TRAIL_WAYPOINT_R,
                    facecolor=team_colour, alpha=dot_a,
                    edgecolor="none", zorder=2,
                ))

            # Arrowhead at segment end
            x0, y0 = waypoints[-2]
            x1, y1 = waypoints[-1]
            dx = x1 - x0; dy = y1 - y0
            if dx != 0 or dy != 0:
                ax.annotate(
                    "", xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(
                        arrowstyle="-|>",
                        color=team_colour,
                        alpha=base_alpha,
                        lw=lw,
                        mutation_scale=7 if is_active else 5,
                        shrinkB=0.38 * 35,
                    ),
                    zorder=2,
                )

            # Round label on oldest segment so you can read history
            if not is_active and n > 1 and len(waypoints) >= 2:
                mx = (waypoints[0][0] + waypoints[1][0]) / 2
                my = (waypoints[0][1] + waypoints[1][1]) / 2
                ax.text(
                    mx, my - 0.18,
                    f"R{round_num}",
                    ha="center", va="center",
                    fontsize=5, color=team_colour,
                    alpha=base_alpha * 0.9,
                    fontweight="bold", zorder=2,
                )

    # ------------------------------------------------------------------
    # Dead token drawing
    # ------------------------------------------------------------------

    def _draw_dead_token(self, ax: plt.Axes, creature, col: int, row: int) -> None:
        team_colour = TEAM_COLOURS.get(creature.team, "#888888")

        ax.add_patch(plt.Circle(
            (col, row), 0.36,
            facecolor=team_colour, alpha=0.18,
            edgecolor=team_colour, linewidth=0.8,
            zorder=3,
        ))
        ax.plot([col - 0.16, col + 0.16], [row - 0.16, row + 0.16],
                color=team_colour, alpha=0.50, linewidth=1.2, zorder=3)
        ax.plot([col + 0.16, col - 0.16], [row - 0.16, row + 0.16],
                color=team_colour, alpha=0.50, linewidth=1.2, zorder=3)
        ax.text(col, row - 0.48, creature.name,
                ha="center", va="bottom",
                fontsize=5.5, color=team_colour, alpha=0.45,
                fontweight="bold", zorder=3)

    # ------------------------------------------------------------------
    # Living creature drawing
    # ------------------------------------------------------------------

    def _draw_creature(self, ax: plt.Axes, creature, col: int, row: int) -> None:
        is_active  = creature is self._active
        fill       = TEAM_COLOURS.get(creature.team, "#888888")
        border     = "#ffffff" if is_active else "#000000"

        if is_active:
            ax.add_patch(plt.Circle(
                (col, row), 0.48, facecolor="none",
                edgecolor=ACTIVE_RING, linewidth=2.5, zorder=4))
            ax.add_patch(plt.Circle(
                (col, row), 0.43, facecolor="none",
                edgecolor=ACTIVE_RING, linewidth=0.8, alpha=0.4, zorder=4))

        ax.add_patch(plt.Circle(
            (col, row), 0.38,
            facecolor=fill, edgecolor=border, linewidth=1.2, zorder=5))

        label = self._token_label(creature)
        ax.text(col, row, label,
                ha="center", va="center",
                fontsize=10 if len(label) > 1 else 12,
                fontweight="bold", color=TOKEN_LABEL, zorder=6)

        ax.text(col, row - 0.52, creature.name,
                ha="center", va="bottom",
                fontsize=6.5, color=fill, fontweight="bold", zorder=6,
                path_effects=[pe.withStroke(linewidth=2,
                              foreground=TERRAIN_COLOURS["normal"])])

        if creature.max_hp > 0:
            self._draw_hp_bar(ax, creature, col, row)

    def _token_label(self, creature) -> str:
        if "#" in creature.name:
            species, num = creature.name.split("#", 1)
            return f"{species[0].upper()}{num}"
        return creature.name[0].upper()

    def _draw_hp_bar(self, ax: plt.Axes, creature, col: int, row: int) -> None:
        frac   = max(0.0, creature.hp / creature.max_hp)
        bar_w  = 0.72
        bar_h  = 0.11
        x_left = col - bar_w / 2
        y_pos  = row + 0.44

        ax.add_patch(mpatches.FancyBboxPatch(
            (x_left, y_pos), bar_w, bar_h,
            boxstyle="square,pad=0",
            facecolor=HP_BG, edgecolor="#111111", linewidth=0.4, zorder=5))
        if frac > 0:
            colour = HP_HIGH if frac > 0.5 else HP_MID if frac > 0.25 else HP_LOW
            ax.add_patch(mpatches.FancyBboxPatch(
                (x_left, y_pos), bar_w * frac, bar_h,
                boxstyle="square,pad=0",
                facecolor=colour, edgecolor="none", zorder=6))
        ax.text(col, y_pos + bar_h / 2,
                f"{int(creature.hp)}/{int(creature.max_hp)}",
                ha="center", va="center",
                fontsize=5.5, color="#ffffff", fontweight="bold", zorder=7)

    # ------------------------------------------------------------------
    # Log panel
    # ------------------------------------------------------------------

    def _draw_log(self, ax: plt.Axes) -> None:
        ax.set_facecolor(LOG_BG)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        for spine in ax.spines.values():
            spine.set_edgecolor(LOG_BORDER)
            spine.set_linewidth(1.0)
            spine.set_visible(True)

        ax.text(0.5, 0.97, "Combat Log",
                ha="center", va="top", fontsize=9, fontweight="bold",
                color=LOG_TITLE, transform=ax.transAxes)
        ax.plot([0.04, 0.96], [0.945, 0.945],
                color=LOG_BORDER, linewidth=0.8, transform=ax.transAxes)

        if not self._log:
            return

        n         = len(self._log)
        top_y     = 0.92
        step      = (top_y - 0.02) / max(n, 1)
        font_size = max(6.5, min(8.5, 200 / max(n, 1)))

        for i, (style, text) in enumerate(self._log):
            colour = LOG_BRIGHT if style == "bright" else LOG_NORMAL
            weight = "bold"   if style == "bright" else "normal"
            ax.text(0.05, top_y - i * step, text,
                    ha="left", va="top",
                    fontsize=font_size, color=colour, fontweight=weight,
                    fontfamily="monospace",
                    transform=ax.transAxes, clip_on=True)