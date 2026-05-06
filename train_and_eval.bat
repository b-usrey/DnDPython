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
set RUN_NAME=overnight_run_20260425
set TRAIN_SCENARIOS=brendiir_vs_goblins.json brendiir_vs_orcs.json
set EVAL_SCENARIOS=brendiir_vs_goblins.json brendiir_vs_orcs.json brendiir_vs_hobgoblins.json
set PYTHON=python
set WORKERS=4

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

:: DQN — slow epsilon decay keeps exploration active through ~75%% of training
set DQN_EPISODES=20000
set DQN_HIDDEN=128 64
set DQN_LR=0.0005
set DQN_GAMMA=0.95
set DQN_EPS=1.0
set DQN_EPS_MIN=0.05
set DQN_EPS_DECAY=0.99985
set DQN_BUF=50000
set DQN_BATCH=128
set DQN_TARGET_FREQ=200
set DQN_PRINT_EVERY=500

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
call :log "  [3/6] RL eval  (%EVAL_EPISODES% episodes per scenario)"

for %%S in (%EVAL_SCENARIOS%) do (
    set RL_SNAME=%%~nS
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
call :log "  [4/6] Evo eval  (%EVAL_EPISODES% episodes per scenario)"

for %%S in (%EVAL_SCENARIOS%) do (
    set EVO_SNAME=%%~nS
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
