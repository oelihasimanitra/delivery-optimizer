# Prépare les outils embarqués dans le dossier tools\ :
#   python : Python « embeddable » (aucune installation, aucun droit administrateur)
#   osrm   : binaires OSRM pour Windows + profils de routage + bibliothèques Visual C++
# Versions épinglées et vérifiées par SHA-256 (sauf les profils Lua : archive source GitHub).
#
# Utilisé par build-release.ps1 (pour fabriquer le ZIP) et, en secours, par launcher.ps1
# quand on lance l'application depuis un simple clone du dépôt.
param(
    [string[]]$What = @('python', 'osrm'),
    [string]$Dest = (Join-Path (Split-Path -Parent $PSScriptRoot) 'tools'),
    [string]$Cache = (Join-Path $env:TEMP 'deliveryopt-cache'),
    [switch]$Force,
    [switch]$RequireVcRuntime   # build : échoue si les DLL Visual C++ sont introuvables sur cette machine
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$PythonVersion = '3.13.17'
$PythonSha256 = '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38'
$OsrmTag = 'v26.11.0'
$OsrmFile = 'node_osrm-v26.11.0-8-win32-x64-Release.tar.gz'
$OsrmSha256 = 'a94d8b02b4df0fb3436fc3891de862a132bf5b8f90d5697ddbad63ce82559921'
$OsrmExes = @('osrm-routed.exe', 'osrm-extract.exe', 'osrm-partition.exe', 'osrm-customize.exe')
$VcDlls = @('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')

New-Item -ItemType Directory -Force -Path $Dest, $Cache | Out-Null

function Install-EmbeddedPython {
    $target = Join-Path $Dest 'python'
    if ((Test-Path (Join-Path $target 'python.exe')) -and -not $Force) { return }
    Write-Host "Téléchargement de Python $PythonVersion (une dizaine de Mo)…"
    $zip = Join-Path $Cache "python-$PythonVersion-embed-amd64.zip"
    Save-Download "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" $zip $PythonSha256
    if (Test-Path $target) { Remove-Item -Recurse -Force $target }
    Expand-Archive -LiteralPath $zip -DestinationPath $target -Force
}

function Install-Osrm {
    $target = Join-Path $Dest 'osrm'
    $complete = (Test-Path (Join-Path $target 'osrm-routed.exe')) -and (Test-Path (Join-Path $target 'profiles\car.lua'))
    if ($complete -and -not $Force) { return }
    Write-Host "Téléchargement des outils de routage OSRM $OsrmTag (une vingtaine de Mo)…"
    $tgz = Join-Path $Cache $OsrmFile
    Save-Download "https://github.com/Project-OSRM/osrm-backend/releases/download/$OsrmTag/$OsrmFile" $tgz $OsrmSha256
    $profilesZip = Join-Path $Cache "osrm-backend-$OsrmTag-source.zip"
    Save-Download "https://github.com/Project-OSRM/osrm-backend/archive/refs/tags/$OsrmTag.zip" $profilesZip

    $work = Join-Path $Cache ('osrm-work-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    try {
        $bin = Join-Path $work 'bin'
        New-Item -ItemType Directory -Force -Path $bin | Out-Null
        & (Join-Path $env:SystemRoot 'System32\tar.exe') -xzf $tgz -C $bin
        if ($LASTEXITCODE -ne 0) { throw [UserError]::new('Impossible de décompresser les outils OSRM.') }
        $src = Join-Path $work 'src'
        Expand-Archive -LiteralPath $profilesZip -DestinationPath $src -Force
        $profiles = Get-ChildItem -LiteralPath $src -Directory | ForEach-Object { Join-Path $_.FullName 'profiles' } | Where-Object { Test-Path (Join-Path $_ 'car.lua') } | Select-Object -First 1
        if (-not $profiles) { throw [UserError]::new('Profils de routage OSRM introuvables dans l''archive source.') }

        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        foreach ($exe in $OsrmExes) {
            $found = Get-ChildItem -LiteralPath $bin -Recurse -Filter $exe | Select-Object -First 1
            if (-not $found) { throw [UserError]::new("$exe absent de l'archive OSRM.") }
            Copy-Item -LiteralPath $found.FullName -Destination $target
        }
        Copy-Item -Recurse -LiteralPath $profiles -Destination (Join-Path $target 'profiles')
    } finally {
        Remove-Item -Recurse -Force -LiteralPath $work -ErrorAction SilentlyContinue
    }

    # Les exécutables OSRM ont besoin de MSVCP140.dll (Python embeddable ne la fournit pas) : sur un Windows
    # vierge elle peut manquer. On l'embarque à côté des exécutables (déploiement « app-local »).
    $missing = @()
    foreach ($dll in $VcDlls) {
        $sys = Join-Path $env:SystemRoot "System32\$dll"
        if (Test-Path $sys) { Copy-Item -LiteralPath $sys -Destination $target } else { $missing += $dll }
    }
    if ($missing -and $RequireVcRuntime) { throw [UserError]::new("DLL Visual C++ introuvables sur cette machine : $($missing -join ', ')") }

    @(
        "Python embeddable $PythonVersion (sha256 $PythonSha256)",
        "OSRM $OsrmTag : $OsrmFile (sha256 $OsrmSha256) + profils de l'archive source du même tag",
        "Bibliothèques Visual C++ copiées depuis System32 : $(($VcDlls | Where-Object { $_ -notin $missing }) -join ', ')"
    ) | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $Dest 'VERSIONS.txt')
}

if ($What -contains 'python') { Install-EmbeddedPython }
if ($What -contains 'osrm') { Install-Osrm }
