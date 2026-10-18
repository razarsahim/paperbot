"""Isolated HISTORICAL BACKTEST replay of the unified 10-strategy Extreme Lab.

Runs the real LabEngine (unchanged) against archived PUBLIC Bybit market data
in throwaway SQLite files. Never touches live paper databases (the main DB is
opened read-only, only for instrument metadata) and never places orders.
Results are historical simulations, not live paper and not predictive.
"""
