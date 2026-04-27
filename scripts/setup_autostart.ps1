# setup_autostart.ps1 — Configure le démarrage automatique d'Askio1
# Lance ce script une seule fois en PowerShell Admin pour tout configurer.
# Ensuite Askio1 démarre tout seul à chaque allumage.
#
# Usage (PowerShell Admin) :
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\scripts\setup_autostart.ps1

$ProjectPath = "C:\Users\Utilisateur\Documents\openClaude\askio1_v2"
$TaskName    = "Askio1-Robot-Daemon"
$LogPath     = "$ProjectPath\data\logs"

Write-Host "=== Setup Askio1 Auto-Start ===" -ForegroundColor Cyan

# 1. Crée le répertoire de logs si manquant
New-Item -ItemType Directory -Force -Path $LogPath | Out-Null

# 2. Configure le Task Scheduler Windows
$Action  = New-ScheduledTaskAction `
    -Execute "wsl.exe" `
    -Argument "-d Ubuntu-22.04 bash -c `"cd /mnt/c/Users/Utilisateur/Documents/openClaude/askio1_v2 && python run_continuous.py --interval 10 >> data/logs/daemon.log 2>&1`""

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

# Supprime si déjà existant
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $Action `
    -Trigger  $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Lance le daemon Askio1 v2 (robot 3D) dans WSL Ubuntu au démarrage" | Out-Null

Write-Host "✓ Tâche '$TaskName' créée dans le Task Scheduler" -ForegroundColor Green

# 3. Installe les dépendances Python dans WSL si nécessaire
Write-Host "`nInstallation des dépendances Python dans WSL..." -ForegroundColor Yellow
wsl -d Ubuntu-22.04 bash -c "cd /mnt/c/Users/Utilisateur/Documents/openClaude/askio1_v2 && pip install python-dotenv pyyaml anthropic scikit-learn ddgs pybullet --break-system-packages -q && echo 'DEPS OK'"

# 4. Vérifie Ollama
Write-Host "`nVérification Ollama..." -ForegroundColor Yellow
$ollamaStatus = wsl -d Ubuntu-22.04 bash -c "curl -s http://localhost:11434/api/tags 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(\"Ollama UP —\", len(d.get(\"models\",[])), \"modèles\")' 2>/dev/null || echo 'Ollama non disponible (optionnel)'"
Write-Host $ollamaStatus

Write-Host "`n=== Configuration terminée ===" -ForegroundColor Cyan
Write-Host "Askio1 démarrera automatiquement à la prochaine session Windows." -ForegroundColor Green
Write-Host "Pour le lancer maintenant : .\scripts\start_askio1.bat"
Write-Host "Logs : $LogPath\daemon.log"
