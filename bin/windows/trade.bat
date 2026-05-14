@echo off
cd /d "%~dp0..\.."
call venv\Scripts\activate

if "%1"=="start"    goto :start
if "%1"=="backtest" goto :backtest
if "%1"=="review"   goto :review
goto :usage

:start
echo Starting auto trader...
python runner.py
goto :eof

:backtest
echo Starting backtest...
python run_backtest.py
goto :eof

:review
if "%2"=="" (
    python -m journal.review
) else (
    python -m journal.review %2 %3
)
goto :eof

:usage
echo Usage: trade.bat [start^|backtest^|review]
echo.
echo   start                        Run auto trader
echo   backtest                     Run backtest
echo   review                       Show all trade history
echo   review --month 2026-05       Monthly report
echo   review --date  2026-05-12    Daily detail
pause
