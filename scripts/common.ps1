# Fonctions partagées par launcher.ps1, fetch-tools.ps1 et build-release.ps1 (à inclure avec « . »).

$ProgressPreference = 'SilentlyContinue'

# Erreur dont le message est destiné à l'utilisateur final (affiché tel quel, en français).
class UserError : System.Exception {
    UserError([string]$message) : base($message) {}
}

function Test-FileHash {
    param([string]$Path, [string]$Hash, [string]$Algorithm = 'SHA256')
    if (-not $Hash) { return $true }
    return ((Get-FileHash -LiteralPath $Path -Algorithm $Algorithm).Hash -ieq $Hash)
}

# Télécharge $Url vers $Out. Reprend un téléchargement interrompu (curl.exe, présent depuis Windows 10 1803).
# Le fichier n'apparaît sous son vrai nom qu'une fois complet, et vérifié si $Hash est fourni.
function Save-Download {
    param([string]$Url, [string]$Out, [string]$Hash = '', [string]$Algorithm = 'SHA256')
    if ((Test-Path -LiteralPath $Out) -and (Test-FileHash $Out $Hash $Algorithm)) { return }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
    $part = "$Out.part"
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    for ($try = 1; $try -le 3; $try++) {
        $ok = $false
        try {
            if (Test-Path -LiteralPath $curl) {
                & $curl -fL --retry 3 --retry-delay 3 -C - -o $part $Url
                $ok = ($LASTEXITCODE -eq 0)
            } else {
                Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $part
                $ok = $true
            }
        } catch { $ok = $false }
        if ($ok -and (Test-FileHash $part $Hash $Algorithm)) {
            Move-Item -Force -LiteralPath $part -Destination $Out
            return
        }
        # Fichier partiel incohérent : on repart de zéro à l'essai suivant.
        Remove-Item -Force -LiteralPath $part -ErrorAction SilentlyContinue
    }
    throw [UserError]::new("Téléchargement impossible ou fichier corrompu : $Url`nVérifiez votre connexion Internet puis relancez.")
}

# Arguments entre guillemets pour Start-Process (chemins avec espaces ou accents).
function Format-Arg([string]$Value) { return '"' + $Value + '"' }

# ---- Carte routière : région d'Antananarivo (voir docs/deployment.md) ----
$MapName = 'antananarivo'
# Rectangle couvert : latitude -19,20 à -18,60 ; longitude 47,20 à 47,80 (≈ 65 x 65 km autour de la capitale).
$MapBbox = @{ South = -19.20; West = 47.20; North = -18.60; East = 47.80 }
# Chemins RELATIFS au dossier de l'application, passés aux outils OSRM (qui rejettent un chemin absolu accentué).
$RelProfile = 'tools\osrm\profiles\car.lua'
$RelOsm = "osrm-data\$MapName.osm"
$RelMapBase = "osrm-data\$MapName.osrm"

function Get-LogTail([string]$Path, [int]$Lines = 8) {
    if (Test-Path -LiteralPath $Path) { return ((Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue) -join "`n") }
    return ''
}

# Lance un outil OSRM dans $WorkDir (chemins relatifs), journalise dans $Log, affiche le temps écoulé.
function Invoke-OsrmStep([string]$Label, [string]$Exe, [string[]]$Arguments, [string]$Log, [string]$WorkDir) {
    $p = Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $WorkDir -NoNewWindow -PassThru -RedirectStandardOutput $Log -RedirectStandardError "$Log.err"
    $null = $p.Handle   # nécessaire pour lire ExitCode d'un processus lancé avec -PassThru
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not $p.HasExited) {
        Write-Host -NoNewline ("`r   {0}… {1:mm\:ss}   " -f $Label, $clock.Elapsed)
        Start-Sleep -Seconds 1
    }
    $p.WaitForExit()
    Write-Host ''
    if ($p.ExitCode -ne 0) {
        $tail = (Get-LogTail "$Log.err") + "`n" + (Get-LogTail $Log)
        throw [UserError]::new("L'étape « $Label » a échoué (code $($p.ExitCode)). Cause possible : mémoire ou espace disque insuffisants.`nDétail : $Log`n$tail")
    }
}
