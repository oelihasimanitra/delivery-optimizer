@echo off
chcp 65001 > NUL
cd /d "%~dp0"
set PY=python
where py > NUL 2> NUL
if not errorlevel 1 set PY=py
if exist data\app.db goto lancer
echo Premier lancement : creez le compte administrateur.
set ADMIN=admin
set /p ADMIN=Identifiant administrateur [admin] : 
%PY% run.py create-user %ADMIN% --role admin
if errorlevel 1 goto erreur
:lancer
start "" http://127.0.0.1:8000
echo Application sur http://127.0.0.1:8000 - fermez cette fenetre pour l'arreter.
rem Distances routieres : serveur OSRM public de demonstration (usage leger, sans garantie). Pour un usage reel, voir docs/deployment.md
if not defined DELIVERYOPT_OSRM_URL set DELIVERYOPT_OSRM_URL=https://router.project-osrm.org
%PY% run.py serve
pause
exit /b 0
:erreur
echo Echec : Python 3.11 ou plus est-il installe ? (python.org)
pause
