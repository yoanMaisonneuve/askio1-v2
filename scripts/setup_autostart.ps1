# setup_autostart.ps1 — Configure le demarrage automatique d'Askio1
# Compatible PowerShell 5.1 (Windows 10/11)
#
# Usage (PowerShell Admin) :
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\scripts\setup_autostart.ps1

$ProjectPath = "C:\Users\Utilisateur\Documents\openClaude\askio1_v2"
$LogPath     = "$ProjectPath\data\logs"
$TaskName    = "Askio1-Robot-Daemon"

Write-Host "=== Setup Askio1 Auto-Start ===" -ForegroundColor Cyan

# 1. Cree le repertoire de logs si manquant
New-Item -ItemType Directory -Force -Path $LogPath | Out-Null
Write-Host "OK repertoire logs : $LogPath" -ForegroundColor Green

# 2. Installe les dependances Python dans WSL (appels separes, pas de &&)
Write-Host "`nInstallation des dependances Python dans WSL..." -ForegroundColor Yellow

wsl -d Ubuntu-22.04 -- bash -c "cd '/mnt/c/Users/Utilisateur/Documents/openClaude/askio1_v2' ; pip install python-dotenv pyyaml anthropic scikit-learn ddgs pybullet --break-system-packages -q"

Write-Host "OK dependances installees" -ForegroundColor Green

# 3. Test rapide
Write-Host "`nTest imports Python..." -ForegroundColor Yellow
wsl -d Ubuntu-22.04 -- bash -c "cd '/mnt/c/Users/Utilisateur/Documents/openClaude/askio1_v2' ; python -c 'import sys; sys.path.insert(0,\".\"); from askio1.simulation.urdf_generator import URDFGenerator; print(\"OK imports\")'"`

# 4. Cree la tache planifiee Windows
Write-Host "`nCreation tache planifiee '$TaskName'..." -ForegroundColor Yellow

$WslArgs = "-d Ubuntu-22.04 -- bash -c `"cd '/mnt/c/Users/Utilisateur/Documents/openClaude/askio1_v2' ; python run_continuous.py --interval 10 >> data/logs/daemon.log 2>&1`""

$Action = New-ScheduledTaskAction `
    -Execute "wsl.exe" `
    -Argument $WslArgs `
    -WorkingDirectory $ProjectPath

$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 23) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

# Supprime si deja existant
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Lance Askio1 v2 robot daemon dans WSL Ubuntu au demarrage" | Out-Null

Write-Host "OK tache '$TaskName' creee" -ForegroundColor Green

# 5. Verifie Ollama (optionnel)
Write-Host "`nVerification Ollama (optionnel)..." -ForegroundColor Yellow
wsl -d Ubuntu-22.04 -- bash -c "curl -s --max-time 3 http://localhost:11434/api/tags > /dev/null 2>&1 ; if [ $? -eq 0 ]; then echo 'Ollama UP'; else echo 'Ollama non disponible - optionnel'; fi"

Write-Host "`n=== Configuration terminee ===" -ForegroundColor Cyan
Write-Host "Askio1 demarrera automatiquement a la prochaine session Windows." -ForegroundColor Green
Write-Host "Pour le lancer maintenant, ouvre Ubuntu et colle :"
Write-Host "  cd /mnt/c/Users/Utilisateur/Documents/openClaude/askio1_v2 ; python run_continuous.py --interval 10"
