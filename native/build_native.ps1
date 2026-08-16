param(
    [string]$PythonExe = "",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$NativeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildRoot = Join-Path $NativeRoot "build-ninja"
$VsWhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"

if (-not $PythonExe) {
    $PythonExe = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) `
        "Programs\Python\Python39\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python interpreter not found: $PythonExe"
}
if (-not (Test-Path -LiteralPath $VsWhere)) {
    throw "Visual Studio Installer vswhere.exe was not found"
}
$VisualStudio = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $VisualStudio) {
    throw "Visual Studio C++ x64 tools were not found"
}
$CMake = Join-Path $VisualStudio "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
$Ninja = Join-Path $VisualStudio "Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"
$DevCmd = Join-Path $VisualStudio "Common7\Tools\VsDevCmd.bat"
if (-not (Test-Path -LiteralPath $CMake)) {
    throw "Visual Studio CMake was not found: $CMake"
}
if (-not (Test-Path -LiteralPath $Ninja)) {
    throw "Visual Studio Ninja was not found: $Ninja"
}
if (-not (Test-Path -LiteralPath $DevCmd)) {
    throw "Visual Studio developer environment was not found: $DevCmd"
}

# Import the x64 developer-command environment into this PowerShell process.
# Ninja avoids Visual Studio generator discovery hangs on custom VS install paths.
$EnvironmentLines = & cmd.exe /d /s /c "`"$DevCmd`" -arch=x64 -host_arch=x64 >nul && set"
foreach ($Line in $EnvironmentLines) {
    $Separator = $Line.IndexOf('=')
    if ($Separator -gt 0) {
        [Environment]::SetEnvironmentVariable(
            $Line.Substring(0, $Separator), $Line.Substring($Separator + 1), "Process")
    }
}

& $CMake -S $NativeRoot -B $BuildRoot -G Ninja "-DCMAKE_MAKE_PROGRAM=$Ninja" "-DCMAKE_BUILD_TYPE=$Configuration" "-DPython3_EXECUTABLE=$PythonExe"
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed: $LASTEXITCODE" }
& $CMake --build $BuildRoot
if ($LASTEXITCODE -ne 0) { throw "Native build failed: $LASTEXITCODE" }

Write-Host "Built native module in $NativeRoot\bin"
