@echo off
:: start_askio1.bat — Lance Askio1 v2 dans WSL au démarrage Windows
:: Ajouter dans le Task Scheduler Windows pour auto-démarrage
:: Chemin : C:\Users\Utilisateur\Documents\openClaude\askio1_v2\scripts\start_askio1.bat

set PROJECT_PATH=/mnt/c/Users/Utilisateur/Documents/openClaude/askio1_v2

:: Lance dans WSL Ubuntu en arrière-plan (fenêtre cachée)
wsl -d Ubuntu-22.04 bash -c "cd %PROJECT_PATH% && nohup python run_continuous.py --interval 10 > data/logs/daemon.log 2>&1 &"

echo Askio1 daemon démarré dans WSL.
echo Log : %PROJECT_PATH%/data/logs/daemon.log
