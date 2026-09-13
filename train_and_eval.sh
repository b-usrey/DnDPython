#!/usr/bin/env bash
# ============================================================
# train_and_eval.sh  --  full overnight run (Linux/macOS)
#
# Port of train_and_eval.bat: same config, same six steps, same output
# layout, so a run on the Linux box and a run on the Windows desktop are
# directly comparable.
#
# Output:
#   saves/<RUN_NAME>/rl/    Q-table weights, logs, eval results
#   saves/<RUN_NAME>/evo/   Evo weights, logs, eval results
#   saves/<RUN_NAME>/dqn/   DQN weights, logs, eval results
#
# Launch unattended with:
#   nohup bash train_and_eval.sh > saves/nohup.out 2>&1 &
# ============================================================
set -u
cd "$(dirname "$0")"

# ── CONFIG ──────────────────────────────────────────────────
RUN_NAME=${RUN_NAME:-overnight_run_$(date +%Y%m%d)}
# Roster training set: the same legal level-5 party against the whole
# SRD roster -- goblinoid warbands, crypt undead, wolf packs and spiders, a
# young dragon with kobolds, a spellcasting coven, plus the two original
# party fights. Every scenario is balanced to a 40-60% monster win rate
# with the stat-block fix and monster abilities in place.
#
# The evals are held out: vampire spawn, wraith, gnoll, chimera, minotaur,
# displacer beast and owlbear appear in no training scenario at all, so
# they measure whether the policy generalises to monsters it never saw.
TRAIN_SCENARIOS=(training_roster_warband.json training_roster_undead.json training_roster_beasts.json training_roster_dragon.json training_roster_casters.json training_party_skirmish.json training_party_ambush.json)
EVAL_SCENARIOS=(eval_roster_undead_lords.json eval_roster_monstrosities.json eval_party_warband.json)
PYTHON=${PYTHON:-.venv/bin/python}
WORKERS=4
export MPLBACKEND=Agg   # headless box: --plot must render to file, not a window

# Which methods to train+eval this run. RL and Evo together cost ~2.6h of
# an 8h night; with DQN as the focus they are off so it gets the whole
# budget. Flip to 1 to include them.
TRAIN_RL=0
TRAIN_EVO=0
TRAIN_DQN=1

RL_EPISODES=80000
RL_BINS=3
RL_ALPHA=0.15
RL_GAMMA=0.95
RL_EPS=1.0
RL_EPS_MIN=0.05
RL_EPS_DECAY=0.9998
RL_PRINT_EVERY=500

EVO_GENERATIONS=50
EVO_POP_SIZE=30
EVO_COMBATS_PER_IND=20
EVO_ELITE_FRAC=0.2
EVO_MUTATION_SCALE=0.1
EVO_CROSSOVER_RATE=0.5

# DQN -- sized to an ~8h overnight budget. Measured on usreyhome after the
# stat-block fix, with DQN updates included: ~0.6 s per training episode on
# the roster set (fights end sooner now that monsters actually hit; the old
# party fights ran ~1.4 s). 40000 episodes is ~6.7 h, plus ~20 min for the
# warm start and the three held-out evals.
# Warm start clones the heuristic teacher first, so eps starts at 0.4 rather
# than 1.0 (exploring at 1.0 would throw the prior away). 0.999931 decays
# 0.4 -> 0.05 over ~30k episodes, i.e. ~75% of the run.
# SAVE_EVERY writes the checkpoint + log every N episodes so a crash at
# hour 7 keeps hour 7's weights instead of nothing.
# Every DQN knob is env-overridable (DQN_EPISODES=50000 bash train_and_eval.sh)
# so a faster or slower box can fill its budget without editing the file.
# If you change DQN_EPISODES, retune DQN_EPS_DECAY so eps still reaches the
# floor ~75% of the way through: decay = exp(ln(EPS_MIN/EPS) / (0.75*EPISODES)).
DQN_EPISODES=${DQN_EPISODES:-40000}
DQN_HIDDEN=${DQN_HIDDEN:-"128 64"}
DQN_LR=${DQN_LR:-0.0005}
DQN_GAMMA=${DQN_GAMMA:-0.95}
DQN_EPS=${DQN_EPS:-0.4}
DQN_EPS_MIN=${DQN_EPS_MIN:-0.05}
DQN_EPS_DECAY=${DQN_EPS_DECAY:-0.999931}
DQN_BUF=${DQN_BUF:-50000}
DQN_BATCH=${DQN_BATCH:-128}
DQN_TARGET_FREQ=${DQN_TARGET_FREQ:-200}
DQN_PRINT_EVERY=${DQN_PRINT_EVERY:-500}
DQN_WARM_START=${DQN_WARM_START:-600}
DQN_SAVE_EVERY=${DQN_SAVE_EVERY:-500}

EVAL_EPISODES=1000
# ── END CONFIG ──────────────────────────────────────────────

BASE_DIR=saves/$RUN_NAME
RL_DIR=$BASE_DIR/rl
EVO_DIR=$BASE_DIR/evo
DQN_DIR=$BASE_DIR/dqn
RL_WEIGHTS=$RL_DIR/${RUN_NAME}_rl.npy
EVO_WEIGHTS=$EVO_DIR/${RUN_NAME}_evo.npy
DQN_WEIGHTS=$DQN_DIR/${RUN_NAME}_dqn.pt
LOG_FILE=$BASE_DIR/run_log.txt

mkdir -p "$RL_DIR" "$EVO_DIR" "$DQN_DIR"

log() { echo "$1"; echo "$1" >> "$LOG_FILE"; }

run_eval() {   # run_eval <method> <weights> <out_dir>
    local method=$1 weights=$2 out_dir=$3
    for s in "${EVAL_SCENARIOS[@]}"; do
        local sname=${s%.json}
        sname=${sname#eval_}     # files are already eval_*; do not emit eval_eval_*
        log "    $s"
        if $PYTHON main.py eval \
                --json    "$s" \
                --load    "$weights" \
                --method  "$method" \
                --team    red \
                --n       $EVAL_EPISODES \
                --workers $WORKERS \
                --output  "$out_dir/eval_$sname.json" \
                --plot    "$out_dir/eval_$sname.png"; then
            log "    Saved: $out_dir/eval_$sname.json"
        else
            log "    WARNING: $method eval failed for $s"
        fi
    done
    log ""
}

log "========================================================"
log "  train_and_eval.sh  --  $RUN_NAME"
log "  Started: $(date)"
log "  Host: $(hostname)  cores: $(nproc 2>/dev/null || echo ?)"
log "========================================================"
log ""


# ── 1. RL TRAINING ───────────────────────────────────────────
if [ "$TRAIN_RL" = 1 ]; then
    log "  [1/6] RL training  ($RL_EPISODES episodes)"
    $PYTHON main.py train \
        --json        "${TRAIN_SCENARIOS[@]}" \
        --method      rl \
        --team        red \
        --run-name    "$RUN_NAME" \
        --save-dir    "$RL_DIR" \
        --episodes    $RL_EPISODES \
        --bins        $RL_BINS \
        --alpha       $RL_ALPHA \
        --gamma       $RL_GAMMA \
        --eps         $RL_EPS \
        --eps-min     $RL_EPS_MIN \
        --eps-decay   $RL_EPS_DECAY \
        --print-every $RL_PRINT_EVERY \
        --workers     $WORKERS \
        --quiet \
        --plot \
        --smoothing   500 \
    || { log "  ERROR: RL training failed -- aborting."; exit 1; }
    log "  RL training done."
    log ""
fi


# ── 2. EVO TRAINING ──────────────────────────────────────────
if [ "$TRAIN_EVO" = 1 ]; then
    log "  [2/6] Evo training  ($EVO_GENERATIONS generations)"
    $PYTHON main.py train \
        --json             "${TRAIN_SCENARIOS[@]}" \
        --method           evo \
        --team             red \
        --run-name         "$RUN_NAME" \
        --save-dir         "$EVO_DIR" \
        --generations      $EVO_GENERATIONS \
        --combats-per-ind  $EVO_COMBATS_PER_IND \
        --pop-size         $EVO_POP_SIZE \
        --elite-frac       $EVO_ELITE_FRAC \
        --mutation-scale   $EVO_MUTATION_SCALE \
        --crossover-rate   $EVO_CROSSOVER_RATE \
        --workers          $WORKERS \
        --quiet \
        --plot \
    || { log "  ERROR: Evo training failed -- aborting."; exit 1; }
    log "  Evo training done."
    log ""
fi


# ── 3. RL EVAL ───────────────────────────────────────────────
if [ "$TRAIN_RL" = 1 ]; then
    log "  [3/6] RL eval  ($EVAL_EPISODES episodes per scenario)"
    run_eval rl "$RL_WEIGHTS" "$RL_DIR"
fi


# ── 4. EVO EVAL ──────────────────────────────────────────────
if [ "$TRAIN_EVO" = 1 ]; then
    log "  [4/6] Evo eval  ($EVAL_EPISODES episodes per scenario)"
    run_eval evo "$EVO_WEIGHTS" "$EVO_DIR"
fi


# ── 5. DQN TRAINING ──────────────────────────────────────────
if [ "$TRAIN_DQN" = 1 ]; then
    log "  [5/6] DQN training  ($DQN_EPISODES episodes, warm start $DQN_WARM_START, checkpoint every $DQN_SAVE_EVERY)"
    # shellcheck disable=SC2086  # DQN_HIDDEN is intentionally word-split
    $PYTHON main.py train \
        --json             "${TRAIN_SCENARIOS[@]}" \
        --method           dqn \
        --team             red \
        --run-name         "$RUN_NAME" \
        --save-dir         "$DQN_DIR" \
        --episodes         $DQN_EPISODES \
        --dqn-hidden       $DQN_HIDDEN \
        --dqn-lr           $DQN_LR \
        --gamma            $DQN_GAMMA \
        --eps              $DQN_EPS \
        --eps-min          $DQN_EPS_MIN \
        --eps-decay        $DQN_EPS_DECAY \
        --dqn-buf          $DQN_BUF \
        --dqn-batch        $DQN_BATCH \
        --dqn-target-freq  $DQN_TARGET_FREQ \
        --print-every      $DQN_PRINT_EVERY \
        --warm-start       $DQN_WARM_START \
        --save-every       $DQN_SAVE_EVERY \
        --quiet \
        --plot \
        --smoothing        500 \
    || { log "  ERROR: DQN training failed -- aborting."; exit 1; }
    log "  DQN training done."
    log ""

    # ── 6. DQN EVAL ──────────────────────────────────────────
    log "  [6/6] DQN eval  ($EVAL_EPISODES episodes per scenario)"
    run_eval dqn "$DQN_WEIGHTS" "$DQN_DIR"
fi


log "========================================================"
log "  Finished: $(date)"
log "  Log: $LOG_FILE"
log "========================================================"
