# WinForms drop target for New Love Plus+ CIA / 3DS patching.
# Drag a .cia / .3ds / .cci onto the window, or click Browse.
# Saved UTF-8 with BOM so Windows PowerShell 5.1 parses Unicode correctly.
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $src
$bat = Join-Path $root "Drop CIA or 3DS Here to Patch.bat"
if (-not (Test-Path -LiteralPath $bat)) {
    $bat = Join-Path $root "Drop CIA Here to Patch.bat"
}

# 8.3 / TEMP staging — Japanese names + parentheses break cmd.exe
# (e.g. "...NEWラブプラス＋ (CTR-P-BLPJ) (v0.2.0) (J).piratelegit.cia").
$shortPathPs1 = Join-Path $src "short_path.ps1"

function Get-SafeRomPath([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) { return $path }
    if (-not (Test-Path -LiteralPath $path)) { return $path }
    if (-not (Test-Path -LiteralPath $shortPathPs1)) {
        return $path
    }
    $env:NLPP_ROM = $path
    try {
        $resolved = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $shortPathPs1
        if ($resolved) {
            return [string]$resolved
        }
    } finally {
        Remove-Item Env:NLPP_ROM -ErrorAction SilentlyContinue
    }
    return $path
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "New Love Plus+ English Patcher"
$form.Size = New-Object System.Drawing.Size(520, 280)
$form.StartPosition = "CenterScreen"
$form.AllowDrop = $true
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(245, 247, 250)

$label = New-Object System.Windows.Forms.Label
$label.Text = "Drop a New Love Plus+ .cia / .3ds here"
$label.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$label.AutoSize = $false
$label.TextAlign = "MiddleCenter"
$label.Dock = "Top"
$label.Height = 70
$label.Padding = New-Object System.Windows.Forms.Padding(12)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = "CIA or 3DS dump -> decrypt -> inject -> out\NewLovePlusPlus-EN.cia"
$hint.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$hint.ForeColor = [System.Drawing.Color]::FromArgb(80, 90, 100)
$hint.AutoSize = $false
$hint.TextAlign = "MiddleCenter"
$hint.Dock = "Top"
$hint.Height = 40

$pathBox = New-Object System.Windows.Forms.TextBox
$pathBox.ReadOnly = $true
$pathBox.Font = New-Object System.Drawing.Font("Consolas", 9)
$pathBox.Dock = "Top"
$pathBox.Height = 28
$pathBox.Margin = New-Object System.Windows.Forms.Padding(16)
$pathBox.Text = "(no file selected)"

$panel = New-Object System.Windows.Forms.Panel
$panel.Dock = "Top"
$panel.Height = 56
$panel.Padding = New-Object System.Windows.Forms.Padding(16, 8, 16, 8)

$browse = New-Object System.Windows.Forms.Button
$browse.Text = "Browse..."
$browse.Width = 110
$browse.Height = 32
$browse.Left = 16
$browse.Top = 10

$go = New-Object System.Windows.Forms.Button
$go.Text = "Patch"
$go.Width = 110
$go.Height = 32
$go.Left = 140
$go.Top = 10
$go.Enabled = $false
$go.BackColor = [System.Drawing.Color]::FromArgb(40, 120, 200)
$go.ForeColor = [System.Drawing.Color]::White
$go.FlatStyle = "Flat"

$status = New-Object System.Windows.Forms.Label
$status.Text = "Waiting for a .cia / .3ds drop..."
$status.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$status.Dock = "Bottom"
$status.Height = 36
$status.TextAlign = "MiddleCenter"

$script:ciaPath = $null
$script:allowedExt = @(".cia", ".3ds", ".cci")

function Set-Cia([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        $status.Text = "File not found."
        return
    }
    $ext = [IO.Path]::GetExtension($path).ToLowerInvariant()
    if ($script:allowedExt -notcontains $ext) {
        $status.Text = "Please drop a .cia / .3ds / .cci file."
        return
    }
    $script:ciaPath = $path
    $pathBox.Text = $path
    $go.Enabled = $true
    $status.Text = "Ready - click Patch (or drop another dump)."
    $form.BackColor = [System.Drawing.Color]::FromArgb(230, 245, 235)
}

$form.Add_DragEnter({
    param($sender, $e)
    if ($e.Data.GetDataPresent([Windows.Forms.DataFormats]::FileDrop)) {
        $e.Effect = [Windows.Forms.DragDropEffects]::Copy
    }
})

$form.Add_DragDrop({
    param($sender, $e)
    $files = [string[]]$e.Data.GetData([Windows.Forms.DataFormats]::FileDrop)
    if ($files -and $files.Count -gt 0) {
        Set-Cia $files[0]
    }
})

$browse.Add_Click({
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Filter = "3DS dumps (*.cia;*.3ds;*.cci)|*.cia;*.3ds;*.cci|CIA (*.cia)|*.cia|3DS/CCI (*.3ds;*.cci)|*.3ds;*.cci|All files (*.*)|*.*"
    $dlg.Title = "Select New Love Plus+ dump"
    if ($dlg.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) {
        Set-Cia $dlg.FileName
    }
})

$go.Add_Click({
    if (-not $script:ciaPath) { return }
    $go.Enabled = $false
    $browse.Enabled = $false
    $status.Text = "Patching... a console window will show progress."
    $form.Refresh()
    $launchPath = Get-SafeRomPath $script:ciaPath
    # Pass as a single argument; staged path has no spaces/parens/Unicode.
    $p = Start-Process -FilePath $bat -ArgumentList @($launchPath) -WorkingDirectory $root -PassThru -Wait
    if ($p.ExitCode -eq 0) {
        $status.Text = "Done. See out\NewLovePlusPlus-EN.cia"
        [System.Windows.Forms.MessageBox]::Show(
            "Patched CIA written to:`n$root\out\NewLovePlusPlus-EN.cia`n`nScratch work files were cleaned up.",
            "Patch complete",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    } else {
        $status.Text = "Patch failed (exit $($p.ExitCode)). Check the console log."
    }
    $go.Enabled = $true
    $browse.Enabled = $true
})

$panel.Controls.Add($browse)
$panel.Controls.Add($go)
$form.Controls.Add($status)
$form.Controls.Add($panel)
$form.Controls.Add($pathBox)
$form.Controls.Add($hint)
$form.Controls.Add($label)

[void]$form.ShowDialog()
