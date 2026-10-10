param(
  [string]$WorkbookPath = ''
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $WorkbookPath) {
  $WorkbookPath = Join-Path $projectRoot 'outputs\01a0fff7-637c-7f00-84ac-e158b4fb55ac\应用统计择校模型_数据模板与审计.xlsx'
}
$WorkbookPath = [System.IO.Path]::GetFullPath($WorkbookPath)
$repairPath = Join-Path (Split-Path -Parent $WorkbookPath) '_audit_excel_compat.xlsx'

function Close-ComObject($value) {
  if ($null -ne $value) {
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($value) | Out-Null
  }
}

function Open-ExcelWorkbook([string]$path, [bool]$extractData) {
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  try {
    if ($extractData) {
      $book = $excel.Workbooks.Open($path, 0, $false, 5, '', '', $true, 1, $null, $false, $false, $null, $false, $true, 2)
    }
    else {
      $book = $excel.Workbooks.Open($path, 0, $false)
    }
    return @($excel, $book)
  }
  catch {
    $excel.Quit()
    Close-ComObject $excel
    throw
  }
}

$excel = $null
$book = $null
$needsRepair = $false
try {
  try {
    $opened = Open-ExcelWorkbook $WorkbookPath $false
    $excel, $book = $opened
  }
  catch {
    $needsRepair = $true
  }

  if ($needsRepair) {
    if (Test-Path -LiteralPath $repairPath) {
      Remove-Item -LiteralPath $repairPath -Force
    }
    $opened = Open-ExcelWorkbook $WorkbookPath $true
    $excel, $book = $opened
    $book.SaveAs($repairPath, 51)
    $book.Close($false)
    Close-ComObject $book
    $book = $null
    $excel.Quit()
    Close-ComObject $excel
    $excel = $null
    Copy-Item -LiteralPath $repairPath -Destination $WorkbookPath -Force
    Remove-Item -LiteralPath $repairPath -Force
    $opened = Open-ExcelWorkbook $WorkbookPath $false
    $excel, $book = $opened
  }

  $sheet = $book.Worksheets.Item('审计总览')
  try {
    $sheet.Range('A24:F24').UnMerge()
    $sheet.Range('A24:F24').Merge()
    foreach ($row in 25..30) {
      $range = $sheet.Range("A${row}:F${row}")
      $range.UnMerge()
      $range.Merge()
      $range.WrapText = $true
      $range.VerticalAlignment = -4108
      $range.RowHeight = 28
      Close-ComObject $range
    }
    $sheet.PageSetup.PrintArea = $sheet.Range('A1:I34').Address()
  }
  finally {
    Close-ComObject $sheet
  }

  $book.Save()
  Write-Output ([pscustomobject]@{
    WorkbookPath = $WorkbookPath
    CompatibilityRepairApplied = $needsRepair
    Sheets = $book.Worksheets.Count
  })
}
finally {
  if ($null -ne $book) {
    $book.Close($false)
    Close-ComObject $book
  }
  if ($null -ne $excel) {
    $excel.Quit()
    Close-ComObject $excel
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
