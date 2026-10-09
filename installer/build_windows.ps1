# Monta a pasta do programa (build\ERP-Obras) com Python, dependências, Tesseract (OCR em português)
# e ffmpeg embutidos. Usado pelo GitHub Actions (windows-latest) antes do Inno Setup.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Resolve-Path "$PSScriptRoot\.."
$out = Join-Path $root "build\ERP-Obras"
$pyVersion = "3.12.7"

if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory $out | Out-Null

Write-Host "== Python $pyVersion (pacote NuGet, relocável)"
$nupkg = Join-Path $env:RUNNER_TEMP "python.zip"
Invoke-WebRequest "https://www.nuget.org/api/v2/package/python/$pyVersion" -OutFile $nupkg
$pyTmp = Join-Path $env:RUNNER_TEMP "python_pkg"
Expand-Archive $nupkg $pyTmp -Force
Move-Item (Join-Path $pyTmp "tools") (Join-Path $out "python")
$py = Join-Path $out "python\python.exe"
& $py -m ensurepip --upgrade
& $py -m pip install --no-warn-script-location --upgrade pip
& $py -m pip install --no-warn-script-location -r (Join-Path $root "requirements.txt") imageio-ffmpeg
if ($LASTEXITCODE -ne 0) { throw "pip install falhou" }

Write-Host "== Código do ERP"
Copy-Item (Join-Path $root "app.py"), (Join-Path $root "requirements.txt"), (Join-Path $root "README.md") $out
Copy-Item (Join-Path $root "erp") (Join-Path $out "erp") -Recurse
Copy-Item (Join-Path $root "sample_data") (Join-Path $out "sample_data") -Recurse
New-Item -ItemType Directory (Join-Path $out ".streamlit") | Out-Null
Copy-Item (Join-Path $root ".streamlit\config.toml") (Join-Path $out ".streamlit\config.toml")
Copy-Item (Join-Path $root "installer\erp_launcher.py") $out
Get-ChildItem $out -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
& $py (Join-Path $root "installer\make_icon.py")
Copy-Item (Join-Path $root "installer\erp_obras.ico") $out

Write-Host "== Tesseract OCR + idioma português"
choco install tesseract -y --no-progress | Out-Null
$tessSrc = "C:\Program Files\Tesseract-OCR"
if (-not (Test-Path "$tessSrc\tesseract.exe")) { throw "Tesseract não encontrado em $tessSrc" }
Copy-Item $tessSrc (Join-Path $out "tesseract") -Recurse
Invoke-WebRequest "https://github.com/tesseract-ocr/tessdata/raw/main/por.traineddata" `
  -OutFile (Join-Path $out "tesseract\tessdata\por.traineddata")

Write-Host "== ffmpeg (vídeo H.264 do time-lapse)"
$ff = & $py -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
New-Item -ItemType Directory (Join-Path $out "ffmpeg") | Out-Null
Copy-Item $ff (Join-Path $out "ffmpeg\ffmpeg.exe")

$size = (Get-ChildItem $out -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Pasta do programa pronta: {0:N0} MB" -f $size)
