# Vector Engine Native Geometry

This directory contains the optional C++17 geometry kernel used by the editor.
It does not own Qt objects, OpenGL contexts, document shapes, or GPU resources.

## Build on the configured Windows development machine

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File native\build_native.ps1
```

The script locates Visual Studio through `vswhere`, imports the x64 developer
environment, uses the CMake and Ninja bundled with Visual Studio, and links
against the configured CPython 3.9 development files. The output is:

```text
native/bin/vector_engine_native.pyd
```

An alternative interpreter can be supplied explicitly:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File native\build_native.ps1 `
  -PythonExe C:\path\to\python.exe
```

The extension ABI must match the interpreter architecture and Python minor
version. Rebuild it when either changes.

## Runtime behavior

`src/core/native_geometry.py` discovers the local module automatically. If the
binary is absent or cannot load, the editor uses the pure-Python reference
implementation. Force the reference path for comparison with:

```powershell
$env:VECTOR_EDITOR_NATIVE = "0"
python start.py
```

Run the safe comparison benchmark with:

```powershell
python benchmarks\benchmark_native_geometry.py --counts 100 1000
```

`native/build-ninja` and `native/bin` are generated artifacts and are ignored by
source control.
