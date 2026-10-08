# Clip source (time-boxed substitute for the team-voice bake-off set)

**Dataset:** The Speech Accent Archive, George Mason University (Steven H. Weinberger).
**URL:** https://accent.gmu.edu/ · bulk files via OSF https://osf.io/yh23d
**License:** CC BY-NC-SA 4.0 (non-commercial research/educational use, attribution, share-alike).
**Downloaded:** 2026-10-08, via `scripts/fetch_accent_archive.py` (public OSF API, no login).

## Why this dataset, not the spec's original plan
`ears/research/01_EARS_research_v2.md` and `ears/SPEC.md` call for a 30-clip bake-off on
**the team's own four voices**, hand-labeled for last-word time, with mid-sentence pauses.
With ~2 hours to the submission deadline, recording and hand-labeling that set wasn't possible.

`ai4bharat/Svarah` — the dataset our own research doc cites for Indian-English ASR WER — was
checked and rejected: it is **gated** on HuggingFace (`HfApi().dataset_info('ai4bharat/Svarah')`
→ `gated: 'auto'`), requiring a logged-in account and manual terms acceptance we don't have
time to arrange. A few random community HF uploads (e.g. `Gbssreejith/indian-english-voice`)
were also checked and rejected for having no stated license or data provenance — not
appropriate to rely on for a judged submission.

## What we used instead, and its limits (read before trusting any number)
33 clips, 11 native languages of India (Hindi, Tamil, Telugu, Malayalam, Kannada, Bengali,
Punjabi, Gujarati, Marathi, Urdu, Konkani), each speaker reading the **same fixed English
paragraph** ("Please call Stella...").

- **It is read speech, not spontaneous conversation.** The paragraph has natural reading
  pauses but was not designed to test mid-sentence-pause endpointing the way the spec wanted.
  Ablation rows that depend on "false cut-off on a mid-sentence pause" are weaker evidence here
  than they would be on real conversational clips.
- **`last_word_time_s` in `MANIFEST.csv` is auto-labeled** by an energy/VAD pass
  (`scripts/label_last_word.py`), not hand-labeled by ear. `label_method=auto` is stamped on
  every row so this is never silently read as a hand label.
- Good news: 11-language spread gives real Indian-accent diversity for a WER sanity check,
  which is the thing the team's research doc flagged as the biggest unmeasured risk
  ("Moonshine has no published Indian-English score").

## Attribution
Weinberger, Steven H. (2026). *Speech Accent Archive.* George Mason University.
Used here under CC BY-NC-SA 4.0 for non-commercial hackathon research/educational purposes.
