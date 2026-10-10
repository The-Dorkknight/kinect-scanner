# Third-party components

| Component | Used for | Licence (upstream) |
|---|---|---|
| `whoareyousb.py` | USB diagnostics ("Diagnose USB..." button) | PolyForm Noncommercial 1.0.0 -- same author (Matthew Armstrong), vendored verbatim in `plugins/vendor/whoareyousb.py`, bundled in this repository. |
| [libfreenect](https://github.com/OpenKinect/libfreenect) (OpenKinect) + its `freenect` Python wrapper | Kinect v1 driver | Dual-licensed Apache License 2.0 / GNU GPL v2.0 (per the project's own `APACHE20`/`GPL2` license files) -- you may use either. **Not bundled**; you build/install it yourself (see README.md -> Install). |
| [libfreenect2](https://github.com/OpenKinect/libfreenect2) (OpenKinect) | Kinect v2 driver | Dual-licensed Apache License 2.0 / GNU GPL v2.0 (per the project's own `APACHE20`/`GPL2` license files) -- you may use either. **Not bundled**; you build/install it yourself (see README.md -> Install). |
| [pylibfreenect2](https://pypi.org/project/pylibfreenect2/) | Python wrapper for libfreenect2 | MIT. **Not bundled**; installed via pip once libfreenect2 itself is built (see README.md -> Install). |
| Open3D | point clouds, ICP, TSDF, Poisson meshing | MIT |
| OpenCV (opencv-python) | image processing (depth clean-up, preview colour map) | Apache-2.0 (OpenCV 4.5+) |
| NumPy | arrays | BSD-3-Clause |
| Pillow | images (live preview) | HPND |
| Python / tkinter | runtime and GUI | PSF |

Nothing in the "Not bundled" rows above ships in this repository; this app only
imports them if you've installed them yourself. Check each upstream licence
before redistributing anything built against them.

See also: [README.md](README.md) (install steps and the honesty section on
what has/hasn't been run against real hardware) and
[LICENSE.md](LICENSE.md) (this project's own licence).
