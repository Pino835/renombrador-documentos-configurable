# -*- coding: utf-8 -*-
# instalar_python.ps1
# -------------------------------------------------------------------------
# Se encarga de UNA sola cosa: asegurar que Python este instalado en el
# equipo. Esto NO se puede hacer desde "instalar_dependencias.py" porque
# ese archivo es un script de Python -- necesita que Python ya exista
# para poder ejecutarse. Por eso este paso previo esta en PowerShell, que
# viene incluido en Windows.
#
# Una vez que Python esta listo (ya estaba, o se acaba de instalar), este
# script llama a "instalar_dependencias.py", que es el que instala las
# librerias de Python y el motor de OCR (Tesseract-OCR).
# -------------------------------------------------------------------------

function Escribir-Titulo($texto) {
    Write-Host ""
    Write-Host ("=" * 64)
    Write-Host $texto
    Write-Host ("=" * 64)
}

function Tiene-Comando($nombre) {
    return [bool](Get-Command $nombre -ErrorAction SilentlyContinue)
}

function Buscar-Python {
    if (Tiene-Comando "py") { return "py" }
    if (Tiene-Comando "python") { return "python" }
    $candidatos = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python313\python.exe"
    )
    foreach ($c in $candidatos) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

Escribir-Titulo "0. Verificando Python"

$python = Buscar-Python

if ($python) {
    Write-Host "OK - Python ya esta instalado ($python)."
} else {
    Write-Host "No se encontro Python en este equipo. Se va a instalar automaticamente..."
    $instalado = $false

    if (Tiene-Comando "winget") {
        Write-Host "`n-> Instalando Python con winget (puede tardar varios minutos)..."
        winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { $instalado = $true }
        else { Write-Host "winget no pudo instalarlo; se intenta por descarga directa." }
    }

    if (-not $instalado) {
        $urlPython = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"
        $destino = Join-Path $env:TEMP "python-3.12.9-amd64.exe"
        try {
            Write-Host "`n-> Descargando el instalador oficial de Python desde:`n   $urlPython"
            Invoke-WebRequest -Uri $urlPython -OutFile $destino -UseBasicParsing
            Write-Host "-> Instalando (silencioso, sin necesitar permisos de administrador)..."
            Start-Process -FilePath $destino -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
            $instalado = $true
        } catch {
            Write-Host "ERROR: no se pudo descargar/instalar Python automaticamente: $_"
        }
    }

    if ($instalado) {
        # El instalador deja el PATH actualizado en el registro, pero esta
        # misma sesion de PowerShell ya estaba abierta desde antes: se
        # refresca aqui para poder seguir sin tener que cerrar la consola.
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + `
                    [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $python = Buscar-Python
    }

    if ($python) {
        Write-Host "`nOK - Python quedo instalado correctamente."
    } else {
        Write-Host "`nATENCION: no se pudo instalar Python automaticamente."
        Write-Host "Instalelo manualmente desde https://www.python.org/downloads/"
        Write-Host "(marcando la casilla 'Add python.exe to PATH' en el instalador)"
        Write-Host "y vuelva a ejecutar 'ejecutar_1_instalar_dependencias.bat'."
        exit 1
    }
}

Escribir-Titulo "Continuando con instalar_dependencias.py"
& $python "instalar_dependencias.py"
