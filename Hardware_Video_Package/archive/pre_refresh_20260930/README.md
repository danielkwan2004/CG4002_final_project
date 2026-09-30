# PickleViz hardware video package

Start with **Hardware_Presentation.md** on screen and **Hardware_Speaking_Script.md** as your narration. The target is a continuous 9:20 recording, exported as MP4. Bracketed script cues tell you when to show code, plots or your physical-hardware photos.

## Included files

- `Hardware_Presentation.md`: 12 numbered presentation screens, diagrams, code excerpts, measured evidence and a preparation appendix.
- `Hardware_Speaking_Script.md`: matching narration, timing targets, visual cues and follow-up placeholders.
- `plots/`: three PNG plots derived from the supplied capture.
- `evidence/output.txt`: unchanged source capture, including both laptop and Serial logs.
- `log_metrics.json`: computed capture statistics and cross-log comparisons.
- `analyze_logs.py`: reproducible parsing and plotting code. Requires Python, NumPy and Matplotlib. From this directory, run `python analyze_logs.py evidence/output.txt`.

## Viewing

Extract the ZIP as a complete folder so the Markdown's relative image paths remain valid. Open the presentation in a Markdown preview that supports Mermaid. The two diagram definitions are editable within the Markdown. You may open each plot as its own image tab for a larger on-screen view.

The hardware photos remain in your own laptop tab. No unseen photos have been invented or inserted. The script directs you to that tab during the physical-build and haptic sections.

## Before the final recording

The follow-up appendix leaves explicit blanks for gyro range/scale alignment, timing and delivery measurements, battery-only operation, the second node and mounted haptics. The existing narration accurately describes the evidence currently available. Replace the identified passages after collecting new evidence rather than extending the video beyond ten minutes.

The existing gyro traces retain the firmware's reported scale. The capture has no per-sample timestamps or synchronized physical-action labels, so charts use sample sequence or report index. Internal zero-drop counters are not presented as proof of full 200 Hz acquisition or zero UDP loss.
