# Kinect 3D Scanner

> **WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN.**
> Version 0.2.0-wip. Free for **non-commercial** use ([PolyForm Noncommercial 1.0.0](LICENSE.md)).
> Copyright Matthew Armstrong ([@The-Dorkknight](https://github.com/The-Dorkknight)). No warranty.

A single-file desktop app that turns a **Kinect v1** (Xbox 360 / Kinect for
Windows) or **Kinect v2** (Kinect for Windows v2 / Kinect for Xbox One)
sensor into a tabletop 3D scanner: live preview → scan while you turn the
object → build a mesh → save `.stl` / `.obj` / `.ply`. The camera type is
detected automatically.

It is a **standalone sibling** of the [`realsense-scanner`](../realsense-scanner)
project (same author, same house style) -- it shares no code and no runtime
dependency with it. `kinect_camera.py`'s camera classes were deliberately
written to match realsense-scanner's own camera-object contract, so that a
real, single-app integration (one scanner, RealSense or Kinect, picked from a
dropdown) is possible later -- but that integration is **not** done in this
release; the two projects just happen to be able to share a scanning engine
if that's ever wanted.

## NONE of this has been run on real Kinect hardware

Being completely straight about this, because it matters more here than
usual: **`kinect_camera.py`, `camera_bridge.py`, and this app's camera code
have never been run against a real Kinect v1 or v2 sensor, and have never
even been run against a real compile of libfreenect or libfreenect2.**

They were written from the published APIs, header comments and examples of
those two (old, community-maintained, and by now largely unmaintained)
driver projects, without access to either piece of hardware or to a machine
set up to build their drivers. The depth-unit conversions, the registered-
depth fallback logic, the packet-pipeline selection, the frame formats --
all of it is "this is what the docs say the API looks like", not "this is
what came back from a sensor on my desk".

As of 0.2.0-wip there is a real automated test suite
(`tests/test_kinect.py`, 25 tests, run with `pytest`), but it runs against
**hand-built stand-in modules** (`tests/fake_kinect_drivers.py`) that mimic
what `freenect` and `pylibfreenect2` are documented to do -- not against the
real driver libraries. It catches a real class of bug (two serious ones were
found and fixed this way -- see CHANGELOG.md's 0.2.0-wip entry) and proves
the app-side logic holds together under failure conditions a real Kinect is
known to produce (hangs, crashes, a stream that stalls). It does **not**
prove a real Kinect works, because nothing on either side of this code has
touched real hardware or a real driver build.

**Treat the first real run on each platform as a debugging session, not a
victory lap.** If something doesn't import, doesn't detect the camera, or
returns a frame shaped wrong, that is the expected starting point, not a
surprise -- please open an issue with what you saw.

## What has actually been tested

| Area | Status |
|---|---|
| The scan → align → mesh → save pipeline's *logic* (point clouds, ICP math, TSDF fusion, Poisson reconstruction) | Ported from realsense-scanner's own camera-agnostic core, which was tested there -- but **not re-run here**, since there's no Kinect frame to feed it yet. |
| `kinect_camera.py` (Kinect v1 / v2 drivers) | **Passes `tests/test_kinect.py`** (25 tests) against hand-built stand-ins for `freenect`/`pylibfreenect2` that mimic their documented behaviour -- frame shapes/dtypes, depth-unit conversion, colour-buffer copying, un-mirroring, BGRX→RGB, pipeline fallback, and clear errors on every missing-driver/no-device/can't-open case tried. **Not run against the real driver libraries or real hardware.** |
| `camera_bridge.py` (child-process isolation + auto-restart) | **Passes the same suite's bridge tests** against a fake camera made to crash, hang, answer with no picture, or simply not be there -- restart/backoff/give-up, heartbeat-vs-no-picture timeouts, range resend after a restart, and fast shutdown are all exercised. **Not exercised against an actual libfreenect/libfreenect2 fault**, since none has been observed firsthand. |
| The GUI (buttons, threading, the Tk event-queue plumbing) | Exercised with the camera code unreachable (no hardware) -- menus and state transitions were checked by hand, not against a live feed. |
| `whoareyousb.py` / "Diagnose USB..." | Tested on **synthetic** USB data only (see that project's own README); not against a real Kinect disconnect. |

Run the test suite yourself with `pip install pytest open3d` (inside
`kinect_env`, or any Python the project's `requirements.txt` works in) then
`pytest tests/`. If something breaks on your camera, please open an issue.

## Install and run

You need Python 3.8-3.12 (same range Open3D supports). Then:

```
python3 kinect_scanner_app.py        # Linux / macOS
py kinect_scanner_app.py             # Windows
```

The first run sets up a private environment next to the script:

* `kinect_env/` -- a venv with `numpy`, `open3d`, `opencv-python`, `Pillow`.
  It's created with `--system-site-packages` **on purpose**: this app does
  **not** try to build the Kinect drivers for you (see "Install the Kinect
  driver" below), so if you've installed `freenect` or `pylibfreenect2` at
  the system/user level yourself, `--system-site-packages` is what keeps
  them importable from inside `kinect_env` without this app having to know
  anything about how you built them.

Options: `--version` (print the version and exit), `--check-drivers` (report
whether `freenect` / `pylibfreenect2` import, and point at the section
below).

## Install the Kinect driver

**This part is manual.** Unlike this project's RealSense sibling (which
builds its camera's driver from source automatically), building
libfreenect/libfreenect2 from source unattended is riskier and slower to get
right without hardware to test against, so this app deliberately does not
attempt it. Use the "Driver setup help..." button (or `--check-drivers`) to
see what's missing, then follow the matching section below.

### Kinect v1 -- [libfreenect](https://github.com/OpenKinect/libfreenect)

**Linux:**
```
sudo apt-get install git cmake build-essential libusb-1.0-0-dev freeglut3-dev libxmu-dev libxi-dev
git clone https://github.com/OpenKinect/libfreenect.git
cd libfreenect && mkdir build && cd build
cmake .. -DBUILD_PYTHON3=ON
make && sudo make install && sudo ldconfig
sudo cp ../platform/linux/udev/51-kinect.rules /etc/udev/rules.d/   # no-sudo USB access; log out/in after
```
The Python wrapper (`freenect`) lives in `libfreenect/wrappers/python`; if
`-DBUILD_PYTHON3=ON` doesn't install it where your Python can see it, `cd`
into that folder and check its own `setup.py`/build instructions, or add it
to `PYTHONPATH`. Package names above are for Debian/Ubuntu; other distros
differ -- check the project's own install docs if a package name doesn't
match what your distro calls it.

**Windows:** there is no pip wheel. Use [Zadig](https://zadig.akeo.ie/) to
bind the **libusbK** driver to the Kinect's camera, audio and motor USB
devices (NOT the official Kinect SDK driver -- they conflict), then build
libfreenect with CMake + Visual Studio following the project's own Windows
build instructions at the link above.

**macOS:** there is no current official Homebrew formula; check the
project's own install docs at the link above for the current recommended
build steps (historically via a Homebrew tap, or a manual
`libusb` + CMake + Visual-Studio-equivalent (Xcode) build).

### Kinect v2 -- [libfreenect2](https://github.com/OpenKinect/libfreenect2) + [pylibfreenect2](https://pypi.org/project/pylibfreenect2/)

**Linux:**
```
sudo apt-get install build-essential cmake pkg-config libusb-1.0-0-dev libturbojpeg0-dev libglfw3-dev
git clone https://github.com/OpenKinect/libfreenect2.git
cd libfreenect2 && mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=$HOME/freenect2 -DENABLE_CXX11=ON
make && make install
sudo cp ../platform/linux/udev/90-kinect2.rules /etc/udev/rules.d/   # log out/in after
LIBFREENECT2_INSTALL_PREFIX=$HOME/freenect2 pip install pylibfreenect2
```
Optional GPU packet pipelines (CUDA/OpenCL) need their SDKs installed before
the `cmake` step; `kinect_camera.py` falls back to the CPU pipeline
automatically if none are available (slower, but always works -- matches
this project's low-end-hardware standard).

**Windows:** use [Zadig](https://zadig.akeo.ie/) to bind the **libusbK**
driver to the Kinect v2's USB device (again, not the official Kinect for
Windows SDK driver). Build libfreenect2 with CMake + Visual Studio per its
own Windows instructions at the link above, then:
```
set LIBFREENECT2_INSTALL_PREFIX=C:\path\to\freenect2
pip install pylibfreenect2
```

**macOS:** there is no official Kinect v2 driver from Microsoft at all; only
the community libfreenect2 build is supported here, and per
`kinect_camera.py`'s own comments, **this is the least-tested path in this
whole project.** `brew install libusb glfw pkg-config`, then the same CMake
build as Linux, then the same `LIBFREENECT2_INSTALL_PREFIX=... pip install
pylibfreenect2` step.

## Using it

1. **Start Camera**. (The "Driver setup help..." button and `--check-drivers`
   tell you what's missing if this fails.)
2. **Start Scan**, slowly turn the object or walk the camera round it.
   **Stop Scan** when done. *Capture Frame* takes a single frame instead.
3. **Build Mesh**: *Smooth surface* (fuses depth images into one TSDF volume,
   recommended) or *Watertight* (Poisson; closes up unscanned gaps, for
   printing).
4. **Save Mesh...** as STL/OBJ/PLY, in millimetres or metres.

## What was simplified from realsense-scanner's alignment engine

`QualityParams`/`quality_to_params` and the meshing (`build_fused_mesh`,
`build_mesh`) are ported close to verbatim from realsense-scanner, since that
part of the pipeline only touches point clouds/meshes and is entirely
camera-agnostic. The frame-*alignment* step (`ScanSession.register_and_merge`)
is a deliberately simpler version:

- **Kept:** sequential coarse-to-fine ICP (colored ICP from a motion-
  extrapolated and an identity starting guess, falling back to feature-based
  global registration when overlap is weak), chaining each new frame onto
  the most recently *successfully aligned* frame. A frame that doesn't line
  up at all is skipped rather than merged in the wrong place.
- **Dropped:** loop closures, full pose-graph global optimisation, the
  tracked-camera-pose rescue/veto machinery (there's no picture-based
  tracking here at all), the frame-consistency outlier check, and per-pixel
  "areas that moved" masking.

This is a real loss of robustness on a long, drifty scan -- a scan that
loops back on itself won't get the loop-closure correction that removes
built-up drift, and there's no safety net for a frame that aligns "well" but
in the wrong place. It is also not yet exercised against anything but
synthetic reasoning, since there's no camera to test it with. It is the
deliberate trade-off this MVP makes for a much smaller, easier-to-debug
alignment path; see realsense-scanner's own `realsense_scanner_app.py` if you
want the fuller version to port back in later.

Explicitly out of scope for this MVP (not ported from realsense-scanner at
all): raw stream recording/replay, the clean-up passes in
`stream_pipeline.py`, sensor-check masking, infrared handling, and tracking-
based pose estimation.

## Troubleshooting: USB flakiness

Kinect v1 and v2 both have a long history of USB hangs, random disconnects
and "works for a bit then drops" issues on community driver stacks. A few
things that help:

- **Kinect v2 needs a real USB 3 port and controller.** It runs close to
  USB3's bandwidth limit; a USB2 port, a USB3 port on a cheap/overloaded hub,
  or a marginal cable will cause it to fail to enumerate or to drop frames.
- **Linux: USB autosuspend** is a common cause of a USB camera randomly
  disconnecting after sitting idle. Check/fix it for the Kinect's device
  with either a udev rule (`ATTR{power/control}="on"` for that device) or,
  as a one-off manual check: `echo -1 | sudo tee /sys/bus/usb/devices/<dev>/power/autosuspend`.
- **Windows:** Device Manager → find the Kinect → Properties → Power
  Management tab → untick "Allow the computer to turn off this device to
  save power".
- **"Diagnose USB..." button** (or `plugins/vendor/whoareyousb.py monitor`
  directly; Linux only) streams a live connect/disconnect/speed-drop log --
  useful for telling a flaky cable/port apart from a driver problem.
- **`camera_bridge.py`'s auto-restart**, from its own docstring: it "cannot
  fix a dead USB cable, a USB2 port being used for a USB3-only Kinect v2, or
  a genuinely unplugged sensor. What it DOES fix is the class of fault where
  the driver's internal state gets wedged (a stuck pipe, a never-returning
  blocking call) -- tearing down and recreating the whole process is a
  strong form of 'unplug and replug' at the software level, which is exactly
  the recovery step commonly suggested in the upstream issue trackers."

## Known limitations

- Both Kinect generations are old, discontinued sensors with unmaintained
  community drivers; expect more friction getting the driver built than
  using the app once it's running.
- No photogrammetry: depth comes from the sensor, colour only decorates it.
- The alignment engine has no loop-closure or drift correction (see above) --
  long scans that come back round to where they started may show a visible
  seam.
- Shiny, transparent and very dark surfaces scan badly on any structured-
  light / time-of-flight camera, Kinect included.

## Licence

Free for non-commercial use under the [PolyForm Noncommercial License 1.0.0](LICENSE.md).
For commercial use, contact the author via GitHub. Third-party parts:
[THIRD_PARTY.md](THIRD_PARTY.md). Copyright Matthew Armstrong. No warranty.
