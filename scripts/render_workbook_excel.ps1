param([string]$OnlySheet = '')

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = Join-Path $projectRoot 'outputs\01a0fff7-637c-7f00-84ac-e158b4fb55ac'
$workbookPath = Join-Path $outputRoot '应用统计择校模型_数据模板与审计.xlsx'
$pdfRoot = Join-Path $outputRoot 'workbook_previews_pdf'
New-Item -ItemType Directory -Path $pdfRoot -Force | Out-Null

$ranges = [ordered]@{
  '审计总览' = 'A1:I34'
  '预测结果' = 'A1:Q20'
  '复核队列' = 'A1:G25'
  '年度数据模板' = 'A1:Q24'
  '事件模板' = 'A1:P18'
  '回测明细' = 'A1:S22'
  '字段字典' = 'A1:H38'
  '来源台账' = 'A1:H20'
  '院校年度数据' = 'A1:Q22'
}

$excel = $null
$book = $null
try {
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  $book = $excel.Workbooks.Open($workbookPath, 0, $true)
  foreach ($entry in $ranges.GetEnumerator()) {
    if ($OnlySheet -and $entry.Key -ne $OnlySheet) { continue }
    $sheet = $book.Worksheets.Item($entry.Key)
    $sheet.PageSetup.PrintArea = $sheet.Range($entry.Value).Address()
    $sheet.PageSetup.Orientation = 2
    $sheet.PageSetup.Zoom = $false
    $sheet.PageSetup.FitToPagesWide = 1
    $sheet.PageSetup.FitToPagesTall = 1
    $sheet.PageSetup.LeftMargin = $excel.InchesToPoints(0.25)
    $sheet.PageSetup.RightMargin = $excel.InchesToPoints(0.25)
    $sheet.PageSetup.TopMargin = $excel.InchesToPoints(0.25)
    $sheet.PageSetup.BottomMargin = $excel.InchesToPoints(0.25)
    $pdfPath = Join-Path $pdfRoot ($entry.Key + '.pdf')
    $sheet.ExportAsFixedFormat(0, $pdfPath)
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($sheet) | Out-Null
  }
}
finally {
  if ($book -ne $null) {
    $book.Close($false)
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($book) | Out-Null
  }
  if ($excel -ne $null) {
    $excel.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}

Get-ChildItem -LiteralPath $pdfRoot -Filter '*.pdf' | Select-Object Name, Length
