# Prépare la carte routière OSRM de la région d'Antananarivo dans <Root>\osrm-data :
#   1. télécharge les routes de la zone depuis Overpass (API publique d'OpenStreetMap, ~10 Mo)
#   2. osrm-extract, osrm-partition, osrm-customize (profil voiture)
#   3. écrit osrm-data\READY et osrm-data\MAP-INFO.txt
# Utilisé au build (build-release.ps1 : la carte est alors livrée dans le ZIP) et, en secours, par le lanceur
# quand le dossier ne contient pas de carte prête (simple clone du dépôt).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$OsmFile,      # fichier .osm déjà téléchargé (évite de réinterroger Overpass)
    [switch]$KeepOsm       # conserve le .osm (build : mis en cache)
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$MapDir = Join-Path $Root 'osrm-data'
$LogDir = Join-Path $Root 'logs'
$OsrmDir = Join-Path $Root 'tools\osrm'
$Osm = Join-Path $Root $RelOsm
$Endpoints = @('https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter')
$UserAgent = 'deliveryopt-map/0.3'   # Overpass refuse les clients sans identification (HTTP 406)

foreach ($exe in 'osrm-extract.exe', 'osrm-partition.exe', 'osrm-customize.exe') {
    if (-not (Test-Path (Join-Path $OsrmDir $exe))) { throw [UserError]::new("Outil OSRM absent : $exe (lancez scripts\fetch-tools.ps1).") }
}
New-Item -ItemType Directory -Force -Path $MapDir, $LogDir | Out-Null

function Get-RegionData([string]$Dest) {
    $inv = [System.Globalization.CultureInfo]::InvariantCulture
    $bbox = '{0},{1},{2},{3}' -f $MapBbox.South.ToString($inv), $MapBbox.West.ToString($inv), $MapBbox.North.ToString($inv), $MapBbox.East.ToString($inv)
    # Routes carrossables + leurs nœuds (y compris hors zone, pour ne pas tronquer les routes qui sortent du cadre)
    # + restrictions de virage. Les chemins piétons, escaliers, pistes cyclables... n'ont aucun intérêt pour une moto.
    $query = @"
[out:xml][timeout:600][maxsize:2147483648][bbox:$bbox];
(
  way["highway"]["highway"!~"^(footway|path|steps|cycleway|pedestrian|bridleway|corridor|elevator|proposed|construction|bus_guideway|raceway|platform)$"];
  way["route"="ferry"];
)->.w;
(.w; >;)->.wn;
rel(bw.w)["type"="restriction"]->.r;
(.wn; .r;);
out body;
"@
    $queryFile = Join-Path $env:TEMP ('deliveryopt-query-' + [guid]::NewGuid().ToString('N') + '.txt')
    [System.IO.File]::WriteAllText($queryFile, $query, (New-Object System.Text.UTF8Encoding $false))
    $part = "$Dest.part"
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    try {
        # Overpass est un service public parfois saturé (HTTP 502/504 « at capacity ») : on réessaie en espaçant
        # (20 s puis 40 s), comme le demande sa documentation, en alternant les deux serveurs.
        for ($round = 1; $round -le 3; $round++) {
            foreach ($url in $Endpoints) {
                Remove-Item -Force -LiteralPath $part -ErrorAction SilentlyContinue
                & $curl -sS -m 300 --compressed -A $UserAgent -H 'Accept: */*' -o $part --data-urlencode "data@$queryFile" $url
                if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $part)) { continue }
                $len = (Get-Item -LiteralPath $part).Length
                if ($len -lt 1MB) { continue }   # une réponse d'erreur ne fait que quelques centaines d'octets
                # Réponse complète = se termine par </osm> et sans <remark> d'erreur d'Overpass (timeout, mémoire…)
                $fs = [System.IO.File]::OpenRead($part)
                try { $fs.Seek([Math]::Max(0, $len - 2048), 'Begin') | Out-Null; $buf = New-Object byte[] ([int][Math]::Min(2048, $len)); $null = $fs.Read($buf, 0, $buf.Length) } finally { $fs.Dispose() }
                $tail = [System.Text.Encoding]::UTF8.GetString($buf)
                if ($tail -match '</osm>' -and $tail -notmatch '<remark') { Move-Item -Force -LiteralPath $part -Destination $Dest; return }
            }
            if ($round -lt 3) {
                Write-Host "Service de cartes occupé : nouvelle tentative dans $($round * 20) s…"
                Start-Sleep -Seconds ($round * 20)
            }
        }
    } finally { Remove-Item -Force -LiteralPath $queryFile, $part -ErrorAction SilentlyContinue }
    throw [UserError]::new("Téléchargement de la carte impossible (service OpenStreetMap indisponible ou connexion coupée).`nVérifiez votre connexion Internet puis relancez.")
}

if ($OsmFile) {
    Copy-Item -Force -LiteralPath $OsmFile -Destination $Osm
} elseif (-not (Test-Path -LiteralPath $Osm)) {
    Write-Host 'Téléchargement des routes de la région d''Antananarivo (environ 10 Mo)…'
    Get-RegionData $Osm
}

# Étapes d'OSRM (algorithme MLD), profil voiture : voir docs/limitations.md.
$car = Join-Path $OsrmDir 'osrm-extract.exe'
Invoke-OsrmStep 'Analyse des routes (1/3)' $car @('-p', (Format-Arg $RelProfile), (Format-Arg $RelOsm)) (Join-Path $LogDir 'osrm-extract.log') $Root
Invoke-OsrmStep 'Découpage de la carte (2/3)' (Join-Path $OsrmDir 'osrm-partition.exe') @((Format-Arg $RelMapBase)) (Join-Path $LogDir 'osrm-partition.log') $Root
Invoke-OsrmStep 'Calcul des distances (3/3)' (Join-Path $OsrmDir 'osrm-customize.exe') @((Format-Arg $RelMapBase)) (Join-Path $LogDir 'osrm-customize.log') $Root

$osmBase = ''
$head = [System.Text.Encoding]::UTF8.GetString((Get-Content -LiteralPath $Osm -Encoding Byte -TotalCount 1200))
if ($head -match 'osm_base="([^"]+)"') { $osmBase = $Matches[1] }
@(
    "Carte routière : région d'Antananarivo",
    ("Zone couverte : latitude {0} à {1}, longitude {2} à {3}" -f $MapBbox.South, $MapBbox.North, $MapBbox.West, $MapBbox.East),
    "Données OpenStreetMap du : $osmBase (licence ODbL, © les contributeurs d'OpenStreetMap)",
    "Préparée le : $(Get-Date -Format 'yyyy-MM-dd')"
) | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $MapDir 'MAP-INFO.txt')
Set-Content -Encoding ASCII -LiteralPath (Join-Path $MapDir 'READY') -Value (Get-Date -Format 's')
if (-not $KeepOsm) { Remove-Item -Force -LiteralPath $Osm -ErrorAction SilentlyContinue }
Write-Host 'Carte prête.' -ForegroundColor Green
