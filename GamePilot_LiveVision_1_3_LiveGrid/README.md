# GamePilot Live Vision 1.0 — developer preview

Windows GUI application for an **owned local test game client**. The application is a tested **developer preview**, not a validated, fully autonomous game agent. It offers separate screen capture and image analysis, T1 visual-template training, tooltip-image verification, progress-bar ROI tracking, a local map, an A* routing planner, event logs, and a guarded click/controller state machine.

## Launch (Windows)

1. Install Python 3.11, check **Add to PATH**.
2. `py -m pip install -r requirements.txt`
3. `py main.py`

Without local Python, upload this folder to a GitHub repository and select **Actions → Build Windows EXE → Run workflow**, then download `GamePilot_LiveVision_Windows` from the completed workflow. Unzip the artifact, run `GamePilot_LiveVision.exe` **alongside** the other bundled files (onedir build). No `.exe` is included in the source ZIP; we cannot test a Windows GUI build on the Linux authoring machine.

## Initial calibration

1. Run in **observation mode**; select correct primary monitor. The full screen is captured; **do not display GamePilot on the same monitor in front of the game** while recording templates — its window would be captured too. Prefer a second monitor or minimize the program when preparing the view.
2. On the **Живий екран** tab, choose `Камінь T1`, drag a tight rectangle around an isolated rock in the video preview to save a template. Do **not** select HUD text or a progress bar as part of the stone.
3. Hover the resource in the game, choose `Назва в підказці`, drag over the stable readable tooltip label (same as in the test client). This image matcher is a lightweight OCR-free verification. For tooltip text that moves or changes visual appearance, the optional OCR fallback requires an installed Tesseract executable and suitable languages.
4. Start gathering manually, choose `Індикатор збору` and select the entire bar rectangle in preview; the green fill must be visible inside.
5. On the **Карта** tab manually mark visible exits (yellow outline with forbidden red buffer) and known physical obstacles **before enabling clicks**. The preview does not automatically classify exits or rivers.
6. Adjust admin settings. Select `Дозволити автоматичні кліки`, confirm, then `ПОЧАТИ`. Press **F8** or **СТОП** to immediately disarm.

## Safety / notable limitations

- **Location estimate is relative camera optical flow**, not absolute world coordinates. It can drift, especially with animations, occlusion, fast moves, camera zoom or scene cuts. The safety controller disarms if accumulated positional uncertainty is too large. It does not support teleportation.
- Rock and tooltip detection use **trained image patterns** and are sensitive to zoom, lighting and overlap. The tooltip pattern is required to arm the controller. This is not a general-purpose object recognition model.
- Interior obstacles and exits are **not automatically classified**. Users must mark them on the map. The A* grid only knows visited/blocked/forbidden cells; unknown cells are hypotheses, not certified traversable space.
- The progress bar is detected by a **green-fill heuristic** in a manually selected ROI. Depletion requires both a persistent bar disappearance and lack of the previous rock template near its last estimated position. This heuristic can still misclassify occluded rocks; inspect logs and tune settings.
- Visual progress during gathering cannot be reliably distinguished from a brief animation or interrupted progress until calibrated on multiple clips. Unconfirmed collection is skipped, not counted as success.
- Waypoint clicks are generated using screen-space motion estimates, not verified game-world navigation. Three route retries are allowed. No guarantee of navigation reliability without actual client footage and experiments.
- Automated movement controls the **system mouse**. Never enable it while doing unrelated desktop tasks. F8 (global shortcut via pynput) works only if Windows permits the keyboard hook; always keep the UI stop button available. Avoid running elevated target apps unless necessary.
- Windows display scaling, multiple monitors, window overlays and camera placement require calibration. Only one selected monitor is captured at a time.
- The UI itself is not pixel-transparent; place it on another monitor for best recognition.

## Files and persistence

`%LOCALAPPDATA%\GamePilotLiveVision\settings.json`: user settings.
`%LOCALAPPDATA%\GamePilotLiveVision\map.json`: relative local map, known rocks, blocked cells, exits.
`%LOCALAPPDATA%\GamePilotLiveVision\templates\`: T1 and tooltip crops.
`%LOCALAPPDATA%\GamePilotLiveVision\progress_roi.txt`: progress-bar region.

Recalibrate templates if resolution, window size, HUD or zoom changes. Do not reuse a saved map on a different map instance without resetting it.

## Tests

`python -m unittest discover -s tests -v`

These tests cover algorithmic units, not a Windows GUI integration test or interaction with the private game client.

## 1.1 hardening notes

- InputBridge now **fails closed** without an explicit foreground window title, even if called outside the UI.
- Navigation checks every screen-space click segment against blocked/forbidden map cells and retries instead of crossing known obstacles.
- Failed exploration frontiers are temporarily quarantined so the search does not immediately repeat the same dead end.
- Additional automated tests cover these behaviors.

**Still not a production-ready autonomous agent:** screen-derived location can drift; exit and terrain detection require calibration; gathering, pathfinding and full-session autonomy cannot be validated without real test-client runs on Windows.

## Live Grid 1.3

Накладення сітки поверх гри в реальному часі, відмітки T1 та автоматичне віддалення карти у міру дослідження. Див. [LIVE_GRID_UA.md](LIVE_GRID_UA.md). Клавіша F5 вмикає/вимикає оверлей за умови підтримки виключення вікна із захоплення Windows.
