# 下载 PaddleOCR 中文 检测/识别/方向分类 三个推理模型，解压到 models/ 目录。
# 由 build.bat 在 models/ 缺失时自动调用；模型文件用于离线 OCR，不进 git。
$ErrorActionPreference = "Stop"

$base      = Split-Path -Parent $MyInvocation.MyCommand.Path
$modelsDir = Join-Path $base "models"
New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null

$urls = @(
    "https://paddleocr.bj.bcebos.com/PP-OCRv4/chinese/ch_PP-OCRv4_det_infer.tar",
    "https://paddleocr.bj.bcebos.com/PP-OCRv4/chinese/ch_PP-OCRv4_rec_infer.tar",
    "https://paddleocr.bj.bcebos.com/dygraph_v2.0/ch/ch_ppocr_mobile_v2.0_cls_infer.tar"
)

foreach ($u in $urls) {
    $f   = Split-Path -Leaf $u
    $tmp = Join-Path $env:TEMP $f
    Write-Host "下载 $f ..."
    Invoke-WebRequest -Uri $u -OutFile $tmp -UseBasicParsing
    Write-Host "解压 $f ..."
    tar -xf $tmp -C $modelsDir
    Remove-Item $tmp -Force
}

Write-Host "OCR 模型就绪。"
