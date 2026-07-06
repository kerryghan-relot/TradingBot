"""Fast vectorbt-based research scripts (exploration only).

These scripts vectorise the signal math for speed.  Final validation
of a strategy must go through ``backtest/event_driven.py``, which runs
the same code as the live bot.

Run them as modules from ``lucas-trading/``::

    python -m backtest.vectorized.backtest_multi
"""
