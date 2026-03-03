@echo off
REM ============================================================
REM Text Expander - Atalho de Execução (Versão Atualizada)
REM ============================================================

REM Muda para o diretório onde o script está localizado
cd /d "%~dp0"

echo.
echo ============================================================
echo   Iniciando Text Expander - Verificando ambiente...
echo ============================================================
echo.

REM ------------------------------------------------------------
REM Verifica se o Python está instalado
REM ------------------------------------------------------------
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python não encontrado!
    echo Instale o Python em: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM ------------------------------------------------------------
REM Verifica se o arquivo txt_xpander.pyw existe
REM ------------------------------------------------------------
if not exist "txt_xpander.pyw" (
    echo [ERRO] Arquivo txt_xpander.pyw não encontrado!
    echo Certifique-se de que este arquivo .bat está na mesma pasta.
    echo.
    pause
    exit /b 1
)

REM ------------------------------------------------------------
REM Verifica dependências principais
REM ------------------------------------------------------------
echo Verificando dependências...

python -c "import pynput, pystray, PIL, yfinance, requests" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [AVISO] Dependências ausentes. Instalando...
    echo.

    python -m pip install --upgrade pip
    python -m pip install pynput pystray pillow yfinance requests --quiet

    if %errorlevel% neq 0 (
        echo.
        echo [ERRO] Falha ao instalar dependências!
        echo Execute manualmente:
        echo     pip install pynput pystray pillow yfinance requests
        echo.
        pause
        exit /b 1
    )

    echo [OK] Dependências instaladas com sucesso!
    echo.
) else (
    echo Todas as dependências já estão instaladas.
    echo.
)

REM ------------------------------------------------------------
REM Execução silenciosa do Text Expander usando pythonw
REM ------------------------------------------------------------
echo Iniciando Text Expander em modo silencioso...
echo.

start "" pythonw txt_xpander.pyw

REM Aguarda um momento e fecha a janela
timeout /t 2 /nobreak >nul
exit
