Spine research code bundle (HNX26EPS08, Entry 2)
spine_core.py             reference implementations: Bayesian endpointer, stall-free start, planner, NNLS energy calibrator, tier controller
verify_*.py, nice_test.py verification scripts (python3 file.py). Needs numpy + scipy only.
verification_output.txt   output of all scripts as run on 8 Oct 2026
ALL numbers in verify_* are SYNTHETIC unless stated (nice_test.py ran on a real kernel but not on our laptop).
They check the logic and the math. They do NOT estimate real effect sizes. Replace the tier tables with measurements.
