# Lanceur de l'application (appelé par lancer.bat). Au premier lancement : crée le compte administrateur
# (et prépare la carte routière si le dossier n'en contient pas : cas d'un simple clone du dépôt ; le ZIP
# de release la contient déjà). Ensuite : démarre OSRM et l'application.
#
# Variables facultatives (utilisateurs avancés) :
#   DELIVERYOPT_OSRM_URL   utiliser un OSRM existant au lieu de celui de ce dossier
#   DELIVERYOPT_PORT       port de l'application (8000 par défaut)
#   DELIVERYOPT_ADMIN_USER / DELIVERYOPT_ADMIN_PASSWORD   création du compte sans question
#   DELIVERYOPT_NO_BROWSER=1   n'ouvre pas le navigateur
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
. (Join-Path $PSScriptRoot 'common.ps1')

$OsrmPort = 5055
$MinFreeGb = 1   # marge de prudence pour le calcul de la carte (clone du dépôt uniquement)
$LogDir = Join-Path $Root 'logs'
$DataDir = Join-Path $Root 'data'
$MapDir = Join-Path $Root 'osrm-data'
$OsrmDir = Join-Path $Root 'tools\osrm'
$Routed = Join-Path $OsrmDir 'osrm-routed.exe'
$AppPort = if ($env:DELIVERYOPT_PORT) { [int]$env:DELIVERYOPT_PORT } else { 8000 }
$AppUrl = "http://127.0.0.1:$AppPort"

$script:AppProc = $null
$script:OsrmProc = $null

function Write-Step([string]$Text) { Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }

function Confirm-Yes([string]$Question) {
    $answer = Read-Host "$Question (O/N)"
    return ($answer -match '^(o|oui|y|yes)$')
}

function Wait-Http([string]$Url, [int]$TimeoutS, [System.Diagnostics.Process]$Watch) {
    $deadline = (Get-Date).AddSeconds($TimeoutS)
    while ((Get-Date) -lt $deadline) {
        if ($Watch -and $Watch.HasExited) { return $false }
        try { Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3 | Out-Null; return $true }
        catch { if ($_.Exception.Response) { return $true } }   # une réponse HTTP, même d'erreur : le serveur répond
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Find-Python {
    $embedded = Join-Path $Root 'tools\python\python.exe'
    if (Test-Path $embedded) { return $embedded }
    foreach ($candidate in @(@('py', '-3'), @('python'))) {
        $cmd = Get-Command $candidate[0] -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ((Test-Path $cmd.Source) -and ((Get-Item $cmd.Source).Length -eq 0)) { continue }   # alias du Microsoft Store, pas un vrai Python
        try {
            $extra = @($candidate | Select-Object -Skip 1)
            $path = & $cmd.Source @extra -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')" 2>$null
            if ($path -and (Test-Path ([string]$path).Trim())) { return ([string]$path).Trim() }
        } catch {}
    }
    return $null
}

function Initialize-Admin([string]$Python) {
    if (Test-Path (Join-Path $DataDir 'app.db')) { return }
    if ($env:DELIVERYOPT_ADMIN_USER -and $env:DELIVERYOPT_ADMIN_PASSWORD) { return }   # créé par « serve »
    Write-Step 'Première utilisation : création du compte administrateur'
    $user = Read-Host 'Nom du compte administrateur [admin]'
    if (-not $user) { $user = 'admin' }
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $p1 = [System.Net.NetworkCredential]::new('', (Read-Host 'Mot de passe (8 caractères minimum ; rien ne s''affiche pendant la frappe)' -AsSecureString)).Password
        $p2 = [System.Net.NetworkCredential]::new('', (Read-Host 'Retapez le mot de passe' -AsSecureString)).Password
        if ($p1.Length -lt 8) { Write-Host 'Mot de passe trop court (8 caractères minimum).' -ForegroundColor Yellow; continue }
        if ($p1 -ne $p2) { Write-Host 'Les deux mots de passe sont différents.' -ForegroundColor Yellow; continue }
        $env:DELIVERYOPT_PASSWORD = $p1
        try { & $Python run.py create-user $user --role admin } finally { Remove-Item Env:\DELIVERYOPT_PASSWORD -ErrorAction SilentlyContinue }
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -Force (Join-Path $DataDir 'app.db') -ErrorAction SilentlyContinue   # pas de base à moitié créée
            throw [UserError]::new('Le compte administrateur n''a pas pu être créé.')
        }
        return
    }
    throw [UserError]::new('Mot de passe non valide après 3 essais. Relancez lancer.bat.')
}

function Initialize-Map {
    if (Test-Path (Join-Path $MapDir 'READY')) { return }
    # La carte est normalement livrée dans le ZIP. Ce cas ne se présente que pour un dossier cloné depuis git.
    Write-Step 'Préparation de la carte routière de la région d''Antananarivo'
    Write-Host 'Cette étape n''est faite qu''une fois : téléchargement d''environ 10 Mo puis calcul (quelques minutes).'
    Write-Host 'Une connexion Internet est nécessaire. Ne fermez pas cette fenêtre.'
    if (-not (Confirm-Yes 'Continuer ?')) { throw [UserError]::new('Préparation annulée.') }
    $free = $null
    try { $free = (Get-PSDrive -Name $Root.Substring(0, 1) -ErrorAction Stop).Free } catch {}
    if ($null -ne $free -and $free -lt ($MinFreeGb * 1GB)) {
        throw [UserError]::new("Espace disque insuffisant : $([math]::Round($free / 1GB, 1)) Go libres, au moins $MinFreeGb Go conseillés. Libérez de la place puis relancez.")
    }
    & (Join-Path $PSScriptRoot 'prepare-map.ps1') -Root $Root
}

function Start-Osrm {
    # Un ancien OSRM resté ouvert (fenêtre fermée de force) bloquerait le port : on ne ferme que celui de ce dossier.
    Get-Process -Name 'osrm-routed' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Routed } | Stop-Process -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $routedArgs = @('-a', 'mld', '-i', '127.0.0.1', '-p', "$OsrmPort", '--max-table-size', '200', (Format-Arg $RelMapBase))
    $script:OsrmProc = Start-Process -FilePath $Routed -ArgumentList $routedArgs -WorkingDirectory $Root -NoNewWindow -PassThru -RedirectStandardOutput (Join-Path $LogDir 'osrm.log') -RedirectStandardError (Join-Path $LogDir 'osrm.err.log')
    $null = $script:OsrmProc.Handle
    Write-Host 'Démarrage du service de routage…'
    if (-not (Wait-Http "http://127.0.0.1:$OsrmPort/nearest/v1/driving/47.5250,-18.9100" 120 $script:OsrmProc)) {
        throw [UserError]::new("Le service de routage OSRM ne démarre pas.`nDétail : $(Join-Path $LogDir 'osrm.err.log')`n$(Get-LogTail (Join-Path $LogDir 'osrm.err.log'))")
    }
    $env:DELIVERYOPT_OSRM_URL = "http://127.0.0.1:$OsrmPort"
}

function Initialize-Routing {
    if ($env:DELIVERYOPT_OSRM_URL) { Write-Host "Routage : OSRM externe ($($env:DELIVERYOPT_OSRM_URL))"; return }
    try {
        if (-not (Test-Path $Routed)) {
            Write-Host 'Outils de routage absents : téléchargement…'
            & (Join-Path $PSScriptRoot 'fetch-tools.ps1') -What osrm
        }
        if (-not ((Test-Path (Join-Path $OsrmDir 'msvcp140.dll')) -or (Test-Path (Join-Path $env:SystemRoot 'System32\msvcp140.dll')))) {
            throw [UserError]::new("Il manque « Microsoft Visual C++ Redistributable » sur cet ordinateur.`nInstallez-le (gratuit) : https://aka.ms/vs/17/release/vc_redist.x64.exe puis relancez.")
        }
        Initialize-Map
        Start-Osrm
        Write-Host 'Routage : distances routières réelles (OSRM local).' -ForegroundColor Green
    } catch {
        $message = if ($_.Exception -is [UserError]) { $_.Exception.Message } else { "Erreur inattendue : $($_.Exception.Message)" }
        Write-Host ''
        Write-Host $message -ForegroundColor Red
        Write-Host ''
        Write-Host 'Sans carte routière, l''application ne peut calculer que des distances ESTIMÉES (à vol d''oiseau x 1,4).'
        Write-Host 'Les tarifs calculés ne seraient PAS facturables.'
        if (-not (Confirm-Yes 'Continuer quand même en mode ESTIMATION ?')) { throw [UserError]::new('Arrêt : routage routier indisponible.') }
        Stop-Osrm
    }
}

function Stop-Osrm {
    if ($script:OsrmProc -and -not $script:OsrmProc.HasExited) { Stop-Process -Id $script:OsrmProc.Id -Force -ErrorAction SilentlyContinue }
}

function Stop-All {
    if ($script:AppProc -and -not $script:AppProc.HasExited) { Stop-Process -Id $script:AppProc.Id -Force -ErrorAction SilentlyContinue }
    Stop-Osrm
}

try {
    if ($Root -like '*.zip\*') {
        throw [UserError]::new('Le dossier est encore dans le ZIP. Faites un clic droit sur le fichier ZIP > « Extraire tout… », puis lancez lancer.bat depuis le dossier extrait.')
    }
    New-Item -ItemType Directory -Force -Path $DataDir, $LogDir | Out-Null
    Write-Host 'Delivery Optimizer' -ForegroundColor Cyan

    $python = Find-Python
    if (-not $python) {
        Write-Host 'Python 3.11 ou plus introuvable : téléchargement d''une copie locale…'
        & (Join-Path $PSScriptRoot 'fetch-tools.ps1') -What python
        $python = Find-Python
        if (-not $python) { throw [UserError]::new('Python n''a pas pu être préparé.') }
    }
    $env:PYTHONUTF8 = '1'

    # Application déjà ouverte ? On ouvre simplement le navigateur dessus.
    if (Wait-Http "$AppUrl/api/health" 2 $null) {
        Write-Host "L'application est déjà lancée : $AppUrl"
        if ($env:DELIVERYOPT_NO_BROWSER -ne '1') { Start-Process $AppUrl }
        exit 0
    }

    Initialize-Admin $python
    Initialize-Routing

    Write-Step 'Démarrage de l''application'
    $appLog = Join-Path $LogDir 'app.log'
    $script:AppProc = Start-Process -FilePath $python -ArgumentList @('run.py', 'serve', '--port', "$AppPort") -WorkingDirectory $Root -NoNewWindow -PassThru -RedirectStandardOutput $appLog -RedirectStandardError (Join-Path $LogDir 'app.err.log')
    $null = $script:AppProc.Handle
    if (-not (Wait-Http "$AppUrl/api/health" 30 $script:AppProc)) {
        throw [UserError]::new("L'application ne démarre pas (le port $AppPort est peut-être déjà utilisé).`nDétail : $(Join-Path $LogDir 'app.err.log')`n$(Get-LogTail (Join-Path $LogDir 'app.err.log'))")
    }
    Write-Host ''
    Write-Host "Application prête : $AppUrl" -ForegroundColor Green
    Write-Host 'Gardez cette fenêtre ouverte pendant l''utilisation. Pour arrêter : fermez-la.'
    if ($env:DELIVERYOPT_NO_BROWSER -ne '1') { Start-Process $AppUrl }
    $script:AppProc.WaitForExit()
    if ($script:AppProc.ExitCode -ne 0) {
        throw [UserError]::new("L'application s'est arrêtée de façon inattendue.`nDétail : $(Join-Path $LogDir 'app.err.log')`n$(Get-LogTail (Join-Path $LogDir 'app.err.log'))")
    }
} catch {
    $message = if ($_.Exception -is [UserError]) { $_.Exception.Message } else { "Erreur inattendue : $($_.Exception.Message)" }
    Write-Host ''
    Write-Host $message -ForegroundColor Red
    exit 1
} finally {
    Stop-All
}
