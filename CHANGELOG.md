# Changelog

## 0.2.0-wip (2026-10-04)

A bug report from a sibling chat -- working on `realsense-scanner`, which had
imported `kinect_camera.py`/`camera_bridge.py` as an optional camera backend
-- found and fixed 14 real faults in both files, by running them against
hand-built stand-in driver modules that mimic `freenect`'s and
`pylibfreenect2`'s documented behaviour, and by reading libfreenect's and
pylibfreenect2's own source rather than just this code. Every fix is applied
here too, and the test suite that caught them (`tests/test_kinect.py`,
`tests/fake_kinect_drivers.py`, 25 tests) is ported in and passes.

**This is a genuine step up in confidence, not a claim of "tested on
hardware"** -- there is still no real Kinect or real driver build on either
side of any of this. See README.md's honesty section.

The two worst bugs, for context:
- An Open3D intrinsic object isn't picklable, so it was silently dropped
  when `camera_bridge.py` put a frame on its `multiprocessing.Queue`. No
  picture ever reached the app through the bridge -- and after enough
  failed restarts, the bridge would blame "a genuine hardware/cable/port
  problem" that was never actually there. Fixed: the intrinsic now crosses
  as six plain numbers and is rebuilt on the other side.
- `pylibfreenect2`'s `waitForNewFrame()` takes its timeout as a *keyword*
  argument; calling it positionally raised `TypeError` on every frame,
  silently, meaning the Kinect v2 path never produced a picture at all.
  Fixed, with a fallback to the no-argument form for builds that don't
  accept the keyword either.

Other fixes, by area:
- **Kinect v1:** `sync_get_depth`/`sync_get_video` returning `None` (camera
  counted but not openable -- commonly a Linux permissions/udev issue) is
  now checked and reported clearly instead of crashing or silently handing
  back garbage; the colour frame is now a real copy of the driver's buffer
  (not a view that changes under the caller on the next call); a
  shape-mismatch between colour and depth is now caught.
- **Kinect v2:** frames are now correctly un-mirrored and converted from
  BGRX to RGB; the registered (depth-aligned) colour and the *undistorted*
  depth frame are used together, rather than pairing registered colour with
  still-distorted raw depth, which was a lower-level alignment bug; NaN/inf
  depth values (which `Registration.apply()` can emit for unknown pixels)
  are now treated as "no data" instead of exploding the `uint16` cast;
  added `KINECT_V2_PIPELINE` (cpu/cuda/opencl/opengl) as a manual override
  for a graphics pipeline that loads but then fails at device start.
- **`camera_bridge.py`:** restart-worthy conditions are now judged *after*
  draining the queue, not before, so a GUI thread that was briefly busy is
  no longer mistaken for a hung camera; a camera that keeps answering but
  never sends a real picture (a stalled USB stream) now triggers a restart
  on its own timeout, separate from the "no response at all" heartbeat; a
  dead child process is now detected quickly during start-up instead of
  waiting out the full start timeout; the restart count now resets after a
  period of stable running, so one old failure doesn't count against a
  camera that has long since recovered; the user's Near/Far range is now
  resent to a freshly-restarted child, instead of being forgotten; `stop()`
  no longer waits out a multi-second queue-join against a reader that has
  already stopped.
- Added `kinect_camera.driver_status()`/`driver_status_text()` (a
  structured, reusable driver-presence check) and
  `kinect_camera.make_camera()` (the bridge's camera-factory, now shipped
  from this module instead of duplicated as this app's own
  `_kinect_camera_factory()`).
- Both camera classes now also look outside this app's own private venv for
  `freenect`/`pylibfreenect2` if the normal import fails, in case the
  driver was built against a different Python installation than the one
  this app is running under.

## 0.1.0-wip (2026-10-03)

First release. **Untested on real hardware** -- see README.md's honesty section.

- Kinect v1 (libfreenect/`freenect`) and Kinect v2 (libfreenect2/`pylibfreenect2`) camera
  support, via the sibling modules `kinect_camera.py` and `camera_bridge.py`.
- `camera_bridge.py`: runs the camera driver in an isolated, auto-restarting child
  process, to mitigate the USB hangs/crashes both Kinect generations are known for.
- Basic scan -> align/merge -> mesh -> save pipeline (`.stl`/`.obj`/`.ply`, mm or m),
  with a simplified (sequential coarse-to-fine ICP, no loop closures or pose-graph
  optimisation) version of realsense-scanner's alignment engine.
- "Smooth" (TSDF fusion) and "Watertight" (Poisson) mesh methods; a 0-100 quality slider.
- `whoareyousb.py`-based "Diagnose USB..." live connection monitor (Linux only).
- `--check-drivers` CLI flag and an in-app "Driver setup help..." button.
- Version, build time and WORK IN PROGRESS notice in the title bar and status bar;
  `--version`. Licence set to PolyForm Noncommercial 1.0.0.
