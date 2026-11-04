# R1D1: observe, report, acknowledge

The first demo is stationary: R1D1 observes a suitcase, reports a photo through
Muse Gadget, the owner acknowledges the observation, and a later inspection
suppresses an unchanged, clearly visible target. A changed or uncertain scene
is not suppressed. An acknowledgment expires after one hour and applies only to
the selected target in the bedroom demo scope. It is not an object identity system.

## Setup on this Pi

Files are installed in `/home/emon/r1d1`. Existing `~/scout-mission` and
`~/scout-snap` are read/reused, never modified. The saved key is read from
`~/.config/r1d1/meta_api_key`; alternatively export `META_MODEL_API_KEY` in the
calling process. Never put a key on a command line or in this repository.

From a fresh shell, with the project copied onto the Pi:

```sh
cd ~/r1d1 && python3 -m venv --system-site-packages .venv && .venv/bin/python -m pip install -r requirements.txt
```

This Pi already has requests and Pillow for `/usr/bin/python3`, used by the
Gadget service commands. On a fresh Raspberry Pi OS install use
`sudo apt-get install python3-requests python3-pil python3-venv` first.
The camera wrapper requires rpicam-still; serial access requires the device's
existing permissions. Python 3.9+; Linux required for physical serial control.

## Live suitcase demonstration

Turn on lights. Put the suitcase in the forward camera view. Do not move the
robot during the stationary sequence. Images are sent to Meta Model API; reports
and photo attachments are sent to the owner's paired Muse account.

```sh
cd ~/r1d1
python3 inspect_demo.py inspect --target suitcase --send
```

The returned observation has an `event_id`. If the suitcase is not visible, aim
the robot manually or move the suitcase, then inspect again. Do not claim the
object is new without an earlier reference view.

After the owner explicitly acknowledges that event:

```sh
python3 inspect_demo.py acknowledge EVENT_ID --note "That's mine; ignore it for this demo"
python3 inspect_demo.py inspect --target suitcase --send
```

A good, matching view returns `suppressed: true` and sends no repeated alert.
Dim, uncertain, missing, changed, or expired references do not suppress alerts.
Visual similarity is judged by a model and can be wrong: this is a supervised
demo, not a home security product. Model output is validated, but visual claims
are not treated as proven facts. A local record distinguishes SDK acceptance
from the owner actually receiving or reading the report.

Optional baseline, captured BEFORE introducing the suitcase from the same view:

```sh
python3 inspect_demo.py baseline
```

A baseline replaces the current scope's acknowledgment. There is no automatic
baseline from an arbitrary past view. Acknowledgments are user statements; the
robot's planning API has no acknowledgment tool. When Muse invokes the command,
it is trusted to act on the owner's explicit request, not to invent consent.

## Muse app commands

```sh
cd ~/r1d1 && python3 register_commands.py
```

This adds five root-owned drop-in definitions and restarts the existing Gadget
service, causing a brief reconnect. Pairing/configuration are preserved.
It does not start any patrol or expose a movement command.

- `r1d1.inspect`: stationary view, optional target, photo report.
- `r1d1.acknowledge`: latest event plus the owner's explicit note; one-hour expiry.
- `r1d1.status`: saved observation and acknowledgment state.
- `r1d1.stop`: latch a stop request for a running local harness.
- `r1d1.locate`: stationary SAM segmentation plus Wonder candidate confirmation;
  sends an outlined image. Requires the SAM environment below.

Ask Muse to inspect for your suitcase. After its report, say that it is yours and
ask it to acknowledge the specific observation for this demo. Then request a
second inspection. This app-driven sequence needs an actual Muse conversation
to verify end to end; successful local command tests alone do not prove it.

To remove these commands, delete only `/etc/musegadget/commands.d/r1d1.*.json`
and restart `musegadget`. Existing SDK built-in commands remain governed by its
existing service configuration; this project does not restrict those commands.

## SAM find-and-frame

SAM 3.1 uses the SAME Meta Model API Bearer key; no extra key was needed on this
account. Access was verified with an image request. Install its official parser
in the project environment (Python 3.10+ for this optional feature):

```sh
cd ~/r1d1 && python3 -m venv --system-site-packages .venv && .venv/bin/python -m pip install -r requirements-sam.txt
.venv/bin/python -m unittest -q test_demo.py test_sam.py
.venv/bin/python frame_target.py --concept "black suitcase" --send
```

The default command is stationary. SAM returns boxes and masks, decoded by
Meta's `meta-sam-parser` package. An earlier suitcase photo yielded one candidate
with score 0.906 and a visible outline at the right edge. The model score is not
a verified probability. The stored sample overlay is `runtime/suitcase-sam.overlay.jpg`.
A fresh stationary view after the previous exploration returned no target; its
report was accepted by Muse. The subsequent supervised rotation-only test on
November 3, 2026 succeeded: three 15-degree right search turns found a candidate,
Wonder confirmed it, and a 10-degree right correction reduced horizontal box-center
error from 33.75% to 6.60% of image width. Five observations and four turns were
used, totaling 55 requested degrees (60 degrees by cumulative wheel odometry).
There was no forward-drive command; odometry reported 13 mm of accumulated
absolute translation during turns. Final commanded velocity was zero, safety
sensors were clear, the stop latch was engaged, and Muse accepted the overlay.
Estimated model cost was $0.0207. This establishes one successful horizontal
framing trial, not general reliability or fully visible vertical framing.

After a human is present, the area checked and the STOP latch explicitly cleared:

```sh
.venv/bin/python frame_target.py --concept "black suitcase" --allow-motion --send
```

The optional physical routine searches by rotation ONLY: at most five turns,
each at most 15 degrees, at most 75 degrees requested total, and six observations.
Missing targets trigger a bounded scan in the selected direction. A single
candidate with score at least 0.7 is visually checked by Wonder before initial
centering. Multiple candidates cause a stop rather than an arbitrary choice.
Pixel offset determines +/-10-degree adjustments; a center within 10% of image
width is accepted unless the target remains horizontally clipped. A clipped
centered target returns partial, not successful framing. Loss after initial
detection stops the routine. There is no persistent object identity across stills.
All turns are re-observed; pixels never authorize driving or imply distance.
The routine re-engages the STOP latch after physical use. Search direction
defaults right and can be set with `--search-direction left`.

Raw SAM responses, decoded detection summaries and overlays are private local
runtime files. Empty completed SAM output is a valid not-found result. Parser
diagnostics, incomplete output and out-of-bounds geometry are rejected.
SAM cost estimate is $0.0025 per image, separate from Wonder usage. A live
finding/centering run makes at most six SAM requests and one Wonder candidate
check. Its 150-second decision deadline excludes cleanup/report time.

The stationary `r1d1.locate` Gadget command uses the project environment and can
be invoked by asking Muse to locate the black suitcase with SAM and show its
outline. The app's actual command invocation still needs user-side verification.
References: [SAM overview](https://dev.meta.ai/docs/sam/overview),
[output format](https://dev.meta.ai/docs/sam/reading-segmentation), and
[official parser](https://dev.meta.ai/docs/sam/client-libraries).

## Bounded agent harness

```sh
python3 harness.py --goal "Inspect the scene and report what is visible" --dry-run --send
python3 harness.py --goal "Look for a suitcase in the current view" --send --max-calls 4
```

Dry-run uses a fake camera, serial controller, scripted five-turn model, and fake
report delivery: zero hardware, external requests or real messages. Runtime state
is isolated beneath `runtime/simulation`. The second command uses the real camera
and Wonder but does not open serial or move. The API preflight counts against
the call budget. Empty/incomplete replies cause a stopped mission, never motion.
Output budget is 800 tokens because reasoning consumes output tokens too.

Limited supervised motion was tested on this hardware on November 3, 2026:
a 100 mm forward request measured 104 mm by wheel odometry; a 15-degree
counterclockwise request measured 15 degrees. Both ended with zero reported
commanded velocity and no observed sensor hazards. A photo was captured after
the turn. These checks do not establish absolute accuracy, larger-movement
reliability, or autonomous navigation safety.
An additional supervised Wonder-selected turn requested 10 degrees left and
measured 11 degrees by odometry, ended with zero commanded velocity and no
sensor warnings, and produced a post-turn photo report accepted by the SDK.
The stop latch was re-engaged. This test cost approximately $0.016 by API usage.

`one_turn_demo.py` implements that narrow test: a maximum of one +/-15-degree
turn, no forward drive, pre/post photos, and three model calls including the
preflight. It can choose no movement. It always re-engages the stop latch on
exit. A human must check the robot and explicitly clear the latch before another
supervised test; do not run it unattended.

`wander_demo.py` is a separate supervised three-step investigation. Each model
proposal includes an explanation and visibility assessment. It permits at most
15-degree turns or 75 mm forward steps (200 mm total requested-distance budget),
with no reverse. Dim/unclear forward views cannot authorize a drive. Every action
ends stopped, with a photo and explanation sent through Muse Gadget, followed by
a final answer about what R1D1 was doing. It has a 150-second planning deadline
and five-call cap including preflight and summary, and re-engages the stop latch.
Report/camera cleanup may extend wall-clock runtime beyond the planning deadline.
This is a short supervised test, not autonomous household patrol.
Only after a human is present in a clear, level, enclosed test area:

```sh
python3 harness.py --goal "Make one small supervised turn, then report" --allow-motion --send --max-calls 4
```

The controller owns serial exclusively among this project's processes, uses OI
SAFE mode, polls bump/cliff/wheel-drop/virtual-wall/overcurrent throughout drives
and turns, and stops rather than reversing on hazards. No reverse actions.
Forward requests are capped at 500 mm at 80 mm/s; turns at 180 degrees and
60 mm/s wheel speed. Distance/angle feedback, hard motion timeouts and an
independent serial-worker process bound actions. Parent disconnect or a caught
termination signal makes the worker stop. Sensor read timeouts abort.

Stop before photos, network calls and reports. The worker checks a local STOP
file during movements; the parent checks it before issuing an action. Ctrl+C
closes the worker pipe. A physical power cutoff is still necessary: software
cannot guarantee stopping after a Pi power loss, kernel hang, forced worker kill,
serial failure or motor electronics failure. This is not a hardware watchdog.

Do not run legacy robot scripts, robot servers, or unrestricted SDK shell motor
commands concurrently: those programs do not honor this project's advisory locks.
Dead reckoning drifts. No map, depth estimation, SLAM or room-to-room navigation.
All decisions are bounded by call, requested-distance and time budgets; braking,
sensor latency and wheel slip mean physical travel is approximate.

Emergency local stop (or use `r1d1.stop` in Muse):

```sh
touch ~/r1d1/runtime/STOP
```

After a human checks the robot, explicitly clear the latch:

```sh
rm ~/r1d1/runtime/STOP
```

## Logs, memory and tests

```sh
cd ~/r1d1 && python3 -m unittest -v test_demo.py
python3 supervised_test.py sensors
python3 inspect_demo.py status
python3 inspect_demo.py reset
```

`runtime/inspection.jsonl` records observations, reference order, raw model text,
usage/spend estimates, photos and delivery results. `runtime/memory.json` stores
scoped acknowledgment state. `runtime/mission-*.jsonl` records harness turns,
pose, raw reply, rejected/validated actions and controller results.
`runtime/sensors.jsonl` records live controller samples including hazard samples.
`runtime/hardware-checks.jsonl` records fixed supervised sensor, drive, turn and
stationary stop-adapter checks. The stop test leaves `runtime/STOP` engaged.
Photos remain local under `runtime/photos` until you delete them. Reset clears
scope memory, not logs/photos. Files are private by process umask and excluded
from source control. No API key, auth header or base64 image body is logged.

Spend estimates use reported input/cached/output token usage at Wonder standard
rates ($4/$0.20/$20 per million tokens), including reasoning output tokens.
They are estimates, not a billing ledger. Failed or interrupted requests may
incur cost that cannot be estimated without returned usage. Rates last checked
November 3, 2026.

References: [Meta API](https://dev.meta.ai/docs/overview),
[images](https://dev.meta.ai/docs/image-understanding),
[reasoning](https://dev.meta.ai/docs/reasoning),
[pricing](https://dev.meta.ai/docs/pricing-rate-limits), and
[original Create OI specification](https://www.cgl.cs.tau.ac.il/wp-content/uploads/2025/06/create-open-interface_v2.pdf).
Gadget command format was verified against the SDK installed on this Pi.
