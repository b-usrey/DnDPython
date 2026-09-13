@echo off
setlocal EnableDelayedExpansion

:: ============================================================
:: train_and_eval.bat  --  full overnight run
::
:: Output:
::   saves\<RUN_NAME>\rl\   Q-table weights, logs, eval results
::   saves\<RUN_NAME>\evo\  Evo weights, logs, eval results
:: ============================================================

:: ── CONFIG ──────────────────────────────────────────────────
:: Scenario set rebalanced 2026-09-10. The previous set (brendiir_vs_*,
:: training_grounds) sat at a 0%% win rate for the trained team under current
:: rules -- those PCs carried illegal loadouts (3 feats on a L5 fighter, 3
:: stacked magic items on the ranger) and fought 12-27 HP monsters that a PC
:: with Extra Attack deletes one per round, so no policy could distinguish
:: itself. These five use legal PCs and multiattack monsters, calibrated so
:: the trained team wins 40-60%% against the no-selector baseline with fights
:: lasting 10-13 rounds. Eval scenarios are held out of training, so results
:: measure generalisation rather than fit.
set RUN_NAME=roster_run_20260912
REM Roster training set: the same legal level-5 party against the whole SRD
REM roster, each scenario balanced to a 40-60%% monster win rate with the
REM stat-block fix and monster abilities in place. The evals are held out:
REM none of their monster types appears in any training scenario.
set TRAIN_SCENARIOS=training_roster_warband.json training_roster_undead.json training_roster_beasts.json training_roster_dragon.json training_roster_casters.json training_party_skirmish.json training_party_ambush.json
set EVAL_SCENARIOS=eval_roster_undead_lords.json eval_roster_monstrosities.json eval_party_warband.json
set PYTHON=python
set WORKERS=4

:: Which methods to train+eval this run. RL and Evo together cost ~2.6h of
:: an 8h night; with DQN as the focus they are off so it gets the whole
:: budget. Flip to 1 to include them.
set TRAIN_RL=0
set TRAIN_EVO=0
set TRAIN_DQN=1

set RL_EPISODES=80000
set RL_BINS=3
set RL_ALPHA=0.15
set RL_GAMMA=0.95
set RL_EPS=1.0
set RL_EPS_MIN=0.05
set RL_EPS_DECAY=0.9998
set RL_PRINT_EVERY=500

set EVO_GENERATIONS=50
set EVO_POP_SIZE=30
set EVO_COMBATS_PER_IND=20
set EVO_ELITE_FRAC=0.2
set EVO_MUTATION_SCALE=0.1
set EVO_CROSSOVER_RATE=0.5

:: DQN -- sized to an ~8h overnight budget at the measured ~0.7-0.9 s/episode.
:: Warm start clones the heuristic teacher first, so eps starts at 0.4 rather
:: than 1.0 (exploring at 1.0 would throw the prior away). 0.99991 decays
:: 0.4 -> 0.05 over ~22.5k episodes, i.e. ~75%% of the run, same shape as before.
:: SAVE_EVERY writes the checkpoint + log every N episodes so a crash at
:: hour 7 keeps hour 7's weights instead of nothing.
set DQN_EPISODES=40000
set DQN_HIDDEN=128 64
set DQN_LR=0.0005
set DQN_GAMMA=0.95
set DQN_EPS=0.4
set DQN_EPS_MIN=0.05
set DQN_EPS_DECAY=0.999931
set DQN_BUF=50000
set DQN_BATCH=128
set DQN_TARGET_FREQ=200
set DQN_PRINT_EVERY=500
set DQN_WARM_START=600
set DQN_SAVE_EVERY=500

set EVAL_EPISODES=1000
:: ── END CONFIG ──────────────────────────────────────────────

set BASE_DIR=saves\%RUN_NAME%
set RL_DIR=%BASE_DIR%\rl
set EVO_DIR=%BASE_DIR%\evo
set DQN_DIR=%BASE_DIR%\dqn
set RL_WEIGHTS=%RL_DIR%\%RUN_NAME%_rl.npy
set EVO_WEIGHTS=%EVO_DIR%\%RUN_NAME%_evo.npy
set DQN_WEIGHTS=%DQN_DIR%\%RUN_NAME%_dqn.pt
set LOG_FILE=%BASE_DIR%\run_log.txt

if not exist "%RL_DIR%"  mkdir "%RL_DIR%"
if not exist "%EVO_DIR%" mkdir "%EVO_DIR%"
if not exist "%DQN_DIR%" mkdir "%DQN_DIR%"

call :log "========================================================"
call :log "  train_and_eval.bat  --  %RUN_NAME%"
call :log "  Started: %DATE% %TIME%"
call :log "========================================================"
call :log ""


:: ── 1. RL TRAINING ───────────────────────────────────────────
if not "%TRAIN_RL%"=="1" goto :skip_rl
call :log "  [1/6] RL training  (%RL_EPISODES% episodes)"

%PYTHON% main.py train ^
    --json        %TRAIN_SCENARIOS% ^
    --method      rl ^
    --team        red ^
    --run-name    %RUN_NAME% ^
    --save-dir    %RL_DIR% ^
    --episodes    %RL_EPISODES% ^
    --bins        %RL_BINS% ^
    --alpha       %RL_ALPHA% ^
    --gamma       %RL_GAMMA% ^
    --eps         %RL_EPS% ^
    --eps-min     %RL_EPS_MIN% ^
    --eps-decay   %RL_EPS_DECAY% ^
    --print-every %RL_PRINT_EVERY% ^
    --workers     %WORKERS% ^
    --plot ^
    --smoothing   500

if errorlevel 1 (
    call :log "  ERROR: RL training failed -- aborting."
    goto :end
)
call :log "  RL training done."
call :log ""
(call )


:: ── 2. EVO TRAINING ──────────────────────────────────────────
:skip_rl
if not "%TRAIN_EVO%"=="1" goto :skip_evo
call :log "  [2/6] Evo training  (%EVO_GENERATIONS% generations)"

%PYTHON% main.py train ^
    --json             %TRAIN_SCENARIOS% ^
    --method           evo ^
    --team             red ^
    --run-name         %RUN_NAME% ^
    --save-dir         %EVO_DIR% ^
    --generations      %EVO_GENERATIONS% ^
    --combats-per-ind  %EVO_COMBATS_PER_IND% ^
    --pop-size         %EVO_POP_SIZE% ^
    --elite-frac       %EVO_ELITE_FRAC% ^
    --mutation-scale   %EVO_MUTATION_SCALE% ^
    --crossover-rate   %EVO_CROSSOVER_RATE% ^
    --workers          %WORKERS% ^
    --plot

if errorlevel 1 (
    call :log "  ERROR: Evo training failed -- aborting."
    goto :end
)
call :log "  Evo training done."
call :log ""
(call )


:: ── 3. RL EVAL ───────────────────────────────────────────────
:skip_evo
if not "%TRAIN_RL%"=="1" goto :skip_rl_eval
call :log "  [3/6] RL eval  (%EVAL_EPISODES% episodes per scenario)"

for %%S in (%EVAL_SCENARIOS%) do (
    set RL_SNAME=%%~nS
    if "!RL_SNAME:~0,5!"=="eval_" set RL_SNAME=!RL_SNAME:~5!
    call :log "    %%S"
    %PYTHON% main.py eval ^
        --json    %%S ^
        --load    %RL_WEIGHTS% ^
        --method  rl ^
        --team    red ^
        --n       %EVAL_EPISODES% ^
        --workers %WORKERS% ^
        --output  %RL_DIR%\eval_!RL_SNAME!.json ^
        --plot    %RL_DIR%\eval_!RL_SNAME!.png
    if errorlevel 1 (
        call :log "    WARNING: RL eval failed for %%S"
    ) else (
        call :log "    Saved: %RL_DIR%\eval_!RL_SNAME!.json"
    )
    (call )
)
call :log ""


:: ── 4. EVO EVAL ──────────────────────────────────────────────
:skip_rl_eval
if not "%TRAIN_EVO%"=="1" goto :skip_evo_eval
call :log "  [4/6] Evo eval  (%EVAL_EPISODES% episodes per scenario)"

for %%S in (%EVAL_SCENARIOS%) do (
    set EVO_SNAME=%%~nS
    if "!EVO_SNAME:~0,5!"=="eval_" set EVO_SNAME=!EVO_SNAME:~5!
    call :log "    %%S"
    %PYTHON% main.py eval ^
        --json    %%S ^
        --load    %EVO_WEIGHTS% ^
        --method  evo ^
        --team    red ^
        --n       %EVAL_EPISODES% ^
        --workers %WORKERS% ^
        --output  %EVO_DIR%\eval_!EVO_SNAME!.json ^
        --plot    %EVO_DIR%\eval_!EVO_SNAME!.png
    if errorlevel 1 (
        call :log "    WARNING: Evo eval failed for %%S"
    ) else (
        call :log "    Saved: %EVO_DIR%\eval_!EVO_SNAME!.json"
    )
    (call )
)
call :log ""


:: ── 5. DQN TRAINING ──────────────────────────────────────────
:skip_evo_eval
if not "%TRAIN_DQN%"=="1" goto :skip_dqn
call :log "  [5/6] DQN training  (%DQN_EPISODES% episodes)"

%PYTHON% main.py train ^
    --json             %TRAIN_SCENARIOS% ^
    --method           dqn ^
    --team             red ^
    --run-name         %RUN_NAME% ^
    --save-dir         %DQN_DIR% ^
    --episodes         %DQN_EPISODES% ^
    --dqn-hidden       %DQN_HIDDEN% ^
    --dqn-lr           %DQN_LR% ^
    --gamma            %DQN_GAMMA% ^
    --eps              %DQN_EPS% ^
    --eps-min          %DQN_EPS_MIN% ^
    --eps-decay        %DQN_EPS_DECAY% ^
    --dqn-buf          %DQN_BUF% ^
    --dqn-batch        %DQN_BATCH% ^
    --dqn-target-freq  %DQN_TARGET_FREQ% ^
    --print-every      %DQN_PRINT_EVERY% ^
    --warm-start       %DQN_WARM_START% ^
    --save-every       %DQN_SAVE_EVERY% ^
    --quiet ^
    --plot ^
    --smoothing        500

if errorlevel 1 (
    call :log "  ERROR: DQN training failed -- aborting."
    goto :end
)
call :log "  DQN training done."
call :log ""
(call )


:: ── 6. DQN EVAL ──────────────────────────────────────────────
call :log "  [6/6] DQN eval  (%EVAL_EPISODES% episodes per scenario)"

for %%S in (%EVAL_SCENARIOS%) do (
    set DQN_SNAME=%%~nS
    if "!DQN_SNAME:~0,5!"=="eval_" set DQN_SNAME=!DQN_SNAME:~5!
    call :log "    %%S"
    %PYTHON% main.py eval ^
        --json    %%S ^
        --load    %DQN_WEIGHTS% ^
        --method  dqn ^
        --team    red ^
        --n       %EVAL_EPISODES% ^
        --workers %WORKERS% ^
        --output  %DQN_DIR%\eval_!DQN_SNAME!.json ^
        --plot    %DQN_DIR%\eval_!DQN_SNAME!.png
    if errorlevel 1 (
        call :log "    WARNING: DQN eval failed for %%S"
    ) else (
        call :log "    Saved: %DQN_DIR%\eval_!DQN_SNAME!.json"
    )
    (call )
)
call :log ""

:skip_dqn

:end
call :log "========================================================"
call :log "  Finished: %DATE% %TIME%"
call :log "  Log: %LOG_FILE%"
call :log "========================================================"
exit /b 0


:log
echo %~1
echo %~1 >> "%LOG_FILE%"
exit /b 0
