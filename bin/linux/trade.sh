#!/bin/bash

cd "$(dirname "$0")/../.."

source venv/bin/activate

case "$1" in
  start)
    echo "Starting auto trader..."
    python3 runner.py
    ;;
  backtest)
    echo "Starting backtest..."
    python3 run_backtest.py
    ;;
  review)
    shift
    python3 -m journal.review "$@"
    ;;
  *)
    echo "Usage: ./trade.sh [start|backtest|review]"
    echo ""
    echo "  start                        Run auto trader"
    echo "  backtest                     Run backtest"
    echo "  review                       Show all trade history"
    echo "  review --month 2026-05       Monthly report"
    echo "  review --date  2026-05-12    Daily detail"
    ;;
esac
