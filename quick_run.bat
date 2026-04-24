@echo off
setlocal EnableDelayedExpansion

:: ============================================================
:: quick_run.bat  --  faster test run (~10-15 min with 4 workers)
::
:: Output:
::   saves\<RUN_NAME>\rl\   Q-table weights, logs, eval results
::   saves\<RUN_NAME>\evo\  Evo weights, logs, eval results
:: ============================================================

:: ── CONFIG ──────────────────────────────────────────────────
set RUN_NAME=quick_run
set TRAIN_SCENARIO=brendiir_vs_goblins.json
set EVAL_SCENARIOS=brendiir_vs_goblins.json brendiir_vs_orcs.json
set PYTHON=python
set WORKERS=4

set RL_EPISODES=2000
set RL_BINS=3
set RL_ALPHA=0.20
set RL_GAMMA=0.95
set RL_EPS=1.0
set RL_EPS_MIN=0.05
set RL_EPS_DECAY=0.990
set RL_PRINT_EVERY=200

set EVO_GENERATIONS=10
set EVO_POP_SIZE=20
set EVO_COMBATS_PER_IND=10
set EVO_ELITE_FRAC=0.2
set EVO_MUTATION_SCALE=0.1
set EVO_CROSSOVER_RATE=0.5

set EVAL_EPISODES=200
:: ── END CONFIG ──────────────────────────────────────────────

set BASE_DIR=saves\%RUN_NAME%
set RL_DIR=%BASE_DIR%\rl
set EVO_DIR=%BASE_DIR%\evo
set RL_WEIGHTS=%RL_DIR%\%RUN_NAME%_rl.npy
set EVO_WEIGHTS=%EVO_DIR%\%RUN_NAME%_evo.npy
set LOG_FILE=%BASE_DIR%\run_log.txt

if not exist "%RL_DIR%"  mkdir "%RL_DIR%"
if not exist "%EVO_DIR%" mkdir "%EVO_DIR%"

call :log "========================================================"
call :log "  quick_run.bat  --  %RUN_NAME%"
call :log "  Started: %DATE% %TIME%"
call :log "========================================================"
call :log ""


:: ── 1. RL TRAINING ───────────────────────────────────────────
call :log "  [1/4] RL training  (%RL_EPISODES% episodes)"

%PYTHON% main.py train ^
    --json        %TRAIN_SCENARIO% ^
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
    --smoothing   100

if errorlevel 1 (
    call :log "  ERROR: RL training failed -- aborting."
    goto :end
)
call :log "  RL training done."
call :log ""
(call )


:: ── 2. EVO TRAINING ──────────────────────────────────────────
call :log "  [2/4] Evo training  (%EVO_GENERATIONS% generations)"

%PYTHON% main.py train ^
    --json             %TRAIN_SCENARIO% ^
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
call :log "  [3/4] RL eval  (%EVAL_EPISODES% episodes per scenario)"

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
call :log "  [4/4] Evo eval  (%EVAL_EPISODES% episodes per scenario)"

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