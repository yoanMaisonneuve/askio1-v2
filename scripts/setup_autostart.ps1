# setup_autostart.ps1 — Configure le demarrage automatique d'Askio1
# Compatible PowerShell 5.1 (Windows 10/11)
#
# Usage (PowerShell Admin) :
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\scripts\setup_autostart.ps1

$ProjectPath = "C:\Users\Utilisateur\Documents\openClaude\askio1_v2"
$LogPath     = "$ProjectPath\data\logs"
$TaskName    = "Askio1-Robot-Daemon"
$WslProject  = "/mnt/c/Users/Utilisateur/Documents/openClaude/askio1_v2"

Write-Host "=== Setup Askio1 Auto-Start ===" -ForegroundColor Cyan

# 1. Cree le repertoire de logs si manquant
New-Item -ItemType Directory -Force -Path $LogPath | Out-Null
Write-Host "OK repertoire logs : $LogPath" -ForegroundColor Green

# 2. Installe les dependances Python dans WSL
Write-Host "`nInstallation des dependances Python dans WSL..." -ForegroundColor Yellow
wsl -d Ubuntu-22.04 -- bash -c "cd '$WslProject' ; pip3 install python-dotenv pyyaml anthropic scikit-learn ddgs pybullet -q 2>/dev/null || pip3 install --user python-dotenv pyyaml anthropic scikit-learn ddgs pybullet -q"
Write-Host "OK dependances installees" -ForegroundColor Green

# 3. Test rapide — utilise chr() pour eviter les guillemets imbriques
# chr(46)=.  chr(79)+chr(75)="OK"
Write-Host "`nTest imports Python..." -ForegroundColor Yellow
$PyTest = "import sys; sys.path.insert(0, chr(46)); from askio1.simulation.urdf_generator import URDFGenerator; print(chr(79)+chr(75))"
wsl -d Ubuntu-22.04 -- bash -c "cd '$WslProject' ; python3 -c '$PyTest'"

# 4. Cree la tache planifiee Windows
Write-Host "`nCreation tache planifiee '$TaskName'..." -ForegroundColor Yellow

$BashCmd  = "cd '$WslProject' ; python3 run_continuous.py --interval 10 >> data/logs/daemon.log 2>&1"
$WslArgs  = "-d Ubuntu-22.04 -- bash -c `"$BashCmd`""

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

# 5. Verifie Ollama (optionnel) — backtick-dollar pour echapper $? de PowerShell
Write-Host "`nVerification Ollama (optionnel)..." -ForegroundColor Yellow
wsl -d Ubuntu-22.04 -- bash -c "curl -s --max-time 3 http://localhost:11434/api/tags > /dev/null 2>&1 ; if [ `$? -eq 0 ]; then echo 'Ollama UP'; else echo 'Ollama non disponible - optionnel'; fi"

Write-Host "`n=== Configuration terminee ===" -ForegroundColor Cyan
Write-Host "Askio1 demarrera automatiquement a la prochaine session Windows." -ForegroundColor Green
Write-Host "Pour le lancer maintenant, ouvre Ubuntu et colle :"
Write-Host "  cd $WslProject ; python3 run_continuous.py --interval 10"
