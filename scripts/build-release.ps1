# Fabrique le ZIP à distribuer aux utilisateurs Windows : dist\delivery-optimizer-v<version>-windows.zip
# Contient l'application, Python embeddable, les binaires OSRM, le LISEZMOI et la carte routière DÉJÀ PRÉPARÉE
# de la région d'Antananarivo (osrm-data\) : aucun calcul ni téléchargement de carte chez l'utilisateur.
# Le build télécharge les routes depuis Overpass (une fois ; mises en cache dans dist\cache, -RefreshMap pour renouveler).
#
#   powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
param([string]$Version, [switch]$RefreshMap)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')

if (-not $Version) {
    $Version = (Select-String -LiteralPath (Join-Path $Root 'pyproject.toml') -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
}
$Name = 'delivery-optimizer'
$Dist = Join-Path $Root 'dist'
$Stage = Join-Path $Dist "stage\$Name"
$Zip = Join-Path $Dist "$Name-v$Version-windows.zip"

if (Test-Path (Join-Path $Dist 'stage')) { Remove-Item -Recurse -Force (Join-Path $Dist 'stage') }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

Write-Host "Préparation des outils embarqués…"
& (Join-Path $PSScriptRoot 'fetch-tools.ps1') -Dest (Join-Path $Stage 'tools') -Cache (Join-Path $Dist 'cache') -RequireVcRuntime

Write-Host "Copie de l'application…"
foreach ($file in @('run.py', 'lancer.bat', 'LISEZMOI.txt', 'THIRD-PARTY-NOTICES.txt', '.env.example', 'LICENSE')) {
    Copy-Item -LiteralPath (Join-Path $Root $file) -Destination $Stage
}
Copy-Item -Recurse -LiteralPath (Join-Path $Root 'src') -Destination (Join-Path $Stage 'src')
Get-ChildItem -LiteralPath (Join-Path $Stage 'src') -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'scripts') | Out-Null
foreach ($script in @('launcher.ps1', 'fetch-tools.ps1', 'common.ps1', 'prepare-map.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $script) -Destination (Join-Path $Stage 'scripts')
}
# Carte routière préparée une fois, ici, avec les outils OSRM embarqués (même version que chez l'utilisateur).
$osmCache = Join-Path $Dist 'cache\antananarivo.osm'
$mapArgs = @{ Root = $Stage; KeepOsm = $true }
if ((Test-Path $osmCache) -and -not $RefreshMap) { $mapArgs.OsmFile = $osmCache; Write-Host "Carte : réutilisation de $osmCache" }
& (Join-Path $PSScriptRoot 'prepare-map.ps1') @mapArgs
$builtOsm = Join-Path $Stage 'osrm-data\antananarivo.osm'
if (Test-Path $builtOsm) { Move-Item -Force $builtOsm $osmCache }
Remove-Item -Recurse -Force (Join-Path $Stage 'logs') -ErrorAction SilentlyContinue
foreach ($ext in '*.osm', '*.part') { Get-ChildItem (Join-Path $Stage 'osrm-data') -Filter $ext -ErrorAction SilentlyContinue | Remove-Item -Force }

New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'docs') | Out-Null
Copy-Item -LiteralPath (Join-Path $Root 'docs\user-guide.md'), (Join-Path $Root 'docs\limitations.md'), (Join-Path $Root 'docs\business-rules.md') -Destination (Join-Path $Stage 'docs')

if (Test-Path $Zip) { Remove-Item -Force $Zip }
& (Join-Path $env:SystemRoot 'System32\tar.exe') -a -c -f $Zip -C (Join-Path $Dist 'stage') $Name   # bsdtar : zip avec des « / » dans les chemins
if ($LASTEXITCODE -ne 0) { throw 'Création du ZIP impossible.' }
Remove-Item -Recurse -Force (Join-Path $Dist 'stage')

$hash = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path -Leaf $Zip)" | Set-Content -Encoding ASCII -LiteralPath (Join-Path $Dist 'SHA256SUMS.txt')
Write-Host ''
Write-Host "ZIP prêt : $Zip ($([math]::Round((Get-Item $Zip).Length / 1MB, 1)) Mo)" -ForegroundColor Green
Write-Host "SHA-256  : $hash"
