# SPINE (backbone, referee)
Read `SPEC.md`, `../docs/CONTRACT.md`, `research/spine_research_design.md`.
Mission: supervisor + shared clock + cgroup enforcement + baseline B0 + measurement harness + tier ladder (then profile controller, then speculation gate only if it pays) + dashboard.
Order that unblocks everyone: (1) cgroup wrapper + clock/log, (2) mock pipeline, (3) **B0 baseline measured**, (4) harness (latency, cgroup CPU/RAM, RAPL), (5) ladder, (6) dashboard, (7) controller layers.
`research/verify_spine_math.py` only validates algebra on synthetic inputs (120,160 checks). It proves nothing about real performance. Judged machine is Linux; Linux-only code stays in this folder and must degrade gracefully elsewhere.
