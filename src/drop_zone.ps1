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
# Result is read from a path file (not powershell stdout) so cmdlet error
# text like "Copy-Item" cannot poison the launch argument.
$shortPathPs1 = Join-Path $src "short_path.ps1"

function Get-SafeRomPath([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) { return $path }
    if (-not (Test-Path -LiteralPath $path)) { return $path }
    if (-not (Test-Path -LiteralPath $shortPathPs1)) {
        return $path
    }
    $pathFile = Join-Path $env:TEMP "nlpp_drop_path.txt"
    $env:NLPP_ROM = $path
    $env:NLPP_DROP_PATH_FILE = $pathFile
    $prevEap = $ErrorActionPreference
    try {
        if (Test-Path -LiteralPath $pathFile) {
            Remove-Item -LiteralPath $pathFile -Force -ErrorAction SilentlyContinue
        }
        # Child may write host messages; never let stderr NativeCommandError
        # become terminating under $ErrorActionPreference=Stop.
        $ErrorActionPreference = "Continue"
        $null = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $shortPathPs1 2>&1
        $ErrorActionPreference = $prevEap
        if (Test-Path -LiteralPath $pathFile) {
            $resolved = [IO.File]::ReadAllText($pathFile).Trim()
            Remove-Item -LiteralPath $pathFile -Force -ErrorAction SilentlyContinue
            if (-not [string]::IsNullOrWhiteSpace($resolved)) {
                return $resolved
            }
        }
    } finally {
        $ErrorActionPreference = $prevEap
        Remove-Item Env:NLPP_ROM -ErrorAction SilentlyContinue
        Remove-Item Env:NLPP_DROP_PATH_FILE -ErrorAction SilentlyContinue
    }
    return $path
}

$outDir = Join-Path $root "out"
$logPath = Join-Path $outDir "log.txt"
$ciaOut = Join-Path $outDir "NewLovePlusPlus-EN.cia"
# The bat only asks the gold-bake question in a git checkout; release zips
# always download the gold bake.
$isCheckout = Test-Path -LiteralPath (Join-Path $root ".git")

$uiCode = @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace NlppUi {
    public static class NlppTheme {
        public static readonly Color Bg = Color.FromArgb(22, 26, 42);
        public static readonly Color Panel = Color.FromArgb(33, 38, 58);
        public static readonly Color PanelEdge = Color.FromArgb(58, 66, 92);
        public static readonly Color Field = Color.FromArgb(16, 20, 34);
        public static readonly Color FieldEdge = Color.FromArgb(62, 70, 96);
        public static readonly Color Muted = Color.FromArgb(154, 162, 184);
        public static readonly Color Text = Color.FromArgb(244, 246, 252);
        public static readonly Color Caption = Color.FromArgb(214, 220, 234);
        public static readonly Color Dash = Color.FromArgb(118, 128, 158);
        public static readonly Color HotFill = Color.FromArgb(36, 48, 78);
        public static readonly Color HotEdge = Color.FromArgb(140, 196, 255);
        public static readonly Color ReadyEdge = Color.FromArgb(88, 186, 150);
        public static readonly Color Link = Color.FromArgb(146, 164, 255);
        public static readonly Color Pink = Color.FromArgb(236, 72, 168);
        public static readonly Color Violet = Color.FromArgb(138, 92, 246);
        public static readonly Color Cyan = Color.FromArgb(56, 214, 224);
        public static readonly Color OffTrack = Color.FromArgb(68, 74, 96);
        public static readonly Color DisabledFill = Color.FromArgb(54, 58, 74);
        public static readonly Color WarnFill = Color.FromArgb(52, 42, 30);
        public static readonly Color WarnEdge = Color.FromArgb(150, 108, 46);
        public static readonly Color WarnAccent = Color.FromArgb(255, 184, 76);
        public static readonly Color WarnText = Color.FromArgb(255, 222, 170);
    }

    public static class Geo {
        public static GraphicsPath Round(Rectangle r, int radius) {
            var p = new GraphicsPath();
            int d = Math.Max(2, radius * 2);
            int w = Math.Max(1, r.Width - 1);
            int h = Math.Max(1, r.Height - 1);
            if (d > w) d = w;
            if (d > h) d = h;
            if (d < 2) d = 2;
            p.AddArc(r.X, r.Y, d, d, 180, 90);
            p.AddArc(r.X + w - d, r.Y, d, d, 270, 90);
            p.AddArc(r.X + w - d, r.Y + h - d, d, d, 0, 90);
            p.AddArc(r.X, r.Y + h - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }

        public static void FillRound(Graphics g, Rectangle r, int radius, Brush brush) {
            using (var path = Round(r, radius)) g.FillPath(brush, path);
        }

        public static void DrawRound(Graphics g, Rectangle r, int radius, Pen pen) {
            using (var path = Round(r, radius)) g.DrawPath(pen, path);
        }
    }

    public static class NlppDwm {
        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

        public static void UseDarkTitle(IntPtr hwnd) {
            try {
                int use = 1;
                DwmSetWindowAttribute(hwnd, 20, ref use, 4);
                DwmSetWindowAttribute(hwnd, 19, ref use, 4);
            } catch (Exception) {
            }
        }
    }

    public class PatcherForm : Form {
        public PatcherForm() {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            DoubleBuffered = true;
            BackColor = NlppTheme.Bg;
            ForeColor = NlppTheme.Text;
        }

        protected override void OnHandleCreated(EventArgs e) {
            base.OnHandleCreated(e);
            NlppDwm.UseDarkTitle(Handle);
        }
    }

    public class DropZone : Panel {
        private bool _hot;
        private bool _ready;

        public DropZone() {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            BackColor = NlppTheme.Bg;
        }

        public bool Hot {
            get { return _hot; }
            set { if (_hot == value) return; _hot = value; Invalidate(); }
        }

        public bool Ready {
            get { return _ready; }
            set { if (_ready == value) return; _ready = value; Invalidate(); }
        }

        protected override void OnPaint(PaintEventArgs e) {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var box = new Rectangle(1, 11, Width - 3, Height - 14);
            if (_hot) {
                using (var fill = new SolidBrush(NlppTheme.HotFill)) Geo.FillRound(g, box, 12, fill);
            }
            var edge = _hot ? NlppTheme.HotEdge : (_ready ? NlppTheme.ReadyEdge : NlppTheme.Dash);
            using (var pen = new Pen(edge, _hot ? 1.6f : 1.25f))
            using (var path = Geo.Round(box, 12)) {
                path.Flatten(null, 0.5f);
                pen.DashPattern = new float[] { 2.5f, 3.2f };
                pen.DashCap = DashCap.Flat;
                g.DrawPath(pen, path);
            }
            string caption = "Game dump";
            var font = Font;
            var size = g.MeasureString(caption, font);
            var chip = new RectangleF(16, 2, size.Width + 10, size.Height);
            using (var bg = new SolidBrush(NlppTheme.Bg)) g.FillRectangle(bg, chip);
            using (var brush = new SolidBrush(NlppTheme.Caption)) g.DrawString(caption, font, brush, 21, 1);
        }
    }

    public class FieldWell : Panel {
        public FieldWell() {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            BackColor = NlppTheme.Field;
            Padding = new Padding(12, 8, 12, 6);
        }

        protected override void OnResize(EventArgs e) {
            base.OnResize(e);
            using (var path = Geo.Round(new Rectangle(0, 0, Width, Height), 10)) {
                Region = new Region(path);
            }
        }

        protected override void OnPaint(PaintEventArgs e) {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var pen = new Pen(NlppTheme.FieldEdge, 1f)) {
                Geo.DrawRound(e.Graphics, new Rectangle(0, 0, Width - 1, Height - 1), 10, pen);
            }
        }
    }

    public class OptionsCard : Panel {
        public OptionsCard() {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            BackColor = NlppTheme.Bg;
        }

        protected override void OnPaintBackground(PaintEventArgs e) {
            using (var bg = new SolidBrush(NlppTheme.Bg)) e.Graphics.FillRectangle(bg, ClientRectangle);
        }

        protected override void OnPaint(PaintEventArgs e) {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var box = new Rectangle(0, 0, Width - 1, Height - 1);
            using (var fill = new SolidBrush(NlppTheme.Panel)) Geo.FillRound(g, box, 14, fill);
            using (var pen = new Pen(NlppTheme.PanelEdge, 1f)) Geo.DrawRound(g, box, 14, pen);
            using (var brush = new SolidBrush(NlppTheme.Caption)) {
                g.DrawString("Patch options", Font, brush, 16, 10);
            }
        }
    }

    public class NoticeCard : Control {
        public NoticeCard() {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            BackColor = NlppTheme.Bg;
            ForeColor = NlppTheme.WarnText;
        }

        protected override void OnPaint(PaintEventArgs e) {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var box = new Rectangle(0, 0, Width - 1, Height - 1);
            using (var fill = new SolidBrush(NlppTheme.WarnFill)) Geo.FillRound(g, box, 12, fill);
            using (var pen = new Pen(NlppTheme.WarnEdge, 1f)) Geo.DrawRound(g, box, 12, pen);
            using (var bar = new SolidBrush(NlppTheme.WarnAccent)) Geo.FillRound(g, new Rectangle(8, 10, 4, Height - 20), 2, bar);
            int d = 22;
            var badge = new Rectangle(24, (Height - d) / 2, d, d);
            using (var b = new SolidBrush(NlppTheme.WarnAccent)) g.FillEllipse(b, badge);
            using (var bold = new Font(Font, FontStyle.Bold)) {
                TextRenderer.DrawText(g, "!", bold, badge, NlppTheme.WarnFill, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
            }
            var textBox = new Rectangle(badge.Right + 12, 6, Width - badge.Right - 24, Height - 12);
            TextRenderer.DrawText(g, Text, Font, textBox, ForeColor, TextFormatFlags.VerticalCenter | TextFormatFlags.WordBreak);
        }
    }

    public class GradientButton : Control {
        private bool _hover;
        private bool _pill = true;
        private int _radius = 12;

        public GradientButton() {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.StandardClick, true);
            Cursor = Cursors.Hand;
            ForeColor = Color.White;
            BackColor = NlppTheme.Bg;
            TabStop = true;
        }

        public bool Pill {
            get { return _pill; }
            set { _pill = value; Invalidate(); }
        }

        public int CornerRadius {
            get { return _radius; }
            set { _radius = value; Invalidate(); }
        }

        protected override void OnMouseEnter(EventArgs e) {
            base.OnMouseEnter(e);
            _hover = true;
            Invalidate();
        }

        protected override void OnMouseLeave(EventArgs e) {
            base.OnMouseLeave(e);
            _hover = false;
            Invalidate();
        }

        protected override void OnEnabledChanged(EventArgs e) {
            base.OnEnabledChanged(e);
            Invalidate();
        }

        protected override void OnPaint(PaintEventArgs e) {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            int inset = _pill ? 6 : 1;
            var box = new Rectangle(inset, inset, Math.Max(1, Width - inset * 2 - 1), Math.Max(1, Height - inset * 2 - 1));
            int radius = _pill ? box.Height / 2 : _radius;
            if (!Enabled) {
                using (var fill = new SolidBrush(NlppTheme.DisabledFill)) Geo.FillRound(g, box, radius, fill);
            } else {
                if (_pill) {
                    var glow = Rectangle.Inflate(box, 7, 6);
                    using (var glowBrush = new SolidBrush(Color.FromArgb(_hover ? 70 : 48, 170, 90, 210))) {
                        Geo.FillRound(g, glow, glow.Height / 2, glowBrush);
                    }
                }
                using (var brush = new LinearGradientBrush(box, NlppTheme.Pink, NlppTheme.Cyan, LinearGradientMode.Horizontal)) {
                    var blend = new ColorBlend();
                    blend.Colors = new Color[] { NlppTheme.Pink, NlppTheme.Violet, NlppTheme.Cyan };
                    blend.Positions = new float[] { 0f, 0.48f, 1f };
                    brush.InterpolationColors = blend;
                    Geo.FillRound(g, box, radius, brush);
                }
                if (_hover) {
                    using (var wash = new SolidBrush(Color.FromArgb(36, 255, 255, 255))) Geo.FillRound(g, box, radius, wash);
                }
            }
            var flags = TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis;
            var textColor = Enabled ? ForeColor : NlppTheme.Muted;
            TextRenderer.DrawText(g, Text, Font, box, textColor, flags);
        }
    }

    public class ToggleSwitch : Control {
        private bool _checked;
        private float _anim;
        private Timer _timer;

        public event EventHandler CheckedChanged;

        public ToggleSwitch() {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.StandardClick, true);
            Size = new Size(48, 26);
            Cursor = Cursors.Hand;
            BackColor = NlppTheme.Panel;
            TabStop = true;
            _timer = new Timer();
            _timer.Interval = 15;
            _timer.Tick += OnTick;
        }

        public bool Checked {
            get { return _checked; }
            set {
                if (_checked == value) return;
                _checked = value;
                if (!IsHandleCreated) {
                    _anim = value ? 1f : 0f;
                    Invalidate();
                } else if (!_timer.Enabled) {
                    _timer.Start();
                }
                var handler = CheckedChanged;
                if (handler != null) handler(this, EventArgs.Empty);
            }
        }

        protected override void OnClick(EventArgs e) {
            if (Enabled) Checked = !Checked;
            base.OnClick(e);
        }

        private void OnTick(object sender, EventArgs e) {
            float target = _checked ? 1f : 0f;
            _anim = _anim + (target - _anim) * 0.38f;
            if (Math.Abs(target - _anim) < 0.02f) {
                _anim = target;
                _timer.Stop();
            }
            Invalidate();
        }

        protected override void OnEnabledChanged(EventArgs e) {
            base.OnEnabledChanged(e);
            Invalidate();
        }

        protected override void Dispose(bool disposing) {
            if (disposing && _timer != null) _timer.Dispose();
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e) {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var track = new Rectangle(0, 2, Width - 1, Height - 5);
            int radius = track.Height / 2;
            if (!Enabled) {
                using (var fill = new SolidBrush(NlppTheme.DisabledFill)) Geo.FillRound(g, track, radius, fill);
            } else if (_anim < 0.04f) {
                using (var fill = new SolidBrush(NlppTheme.OffTrack)) Geo.FillRound(g, track, radius, fill);
            } else {
                using (var brush = new LinearGradientBrush(track, NlppTheme.Pink, NlppTheme.Cyan, LinearGradientMode.Horizontal)) {
                    Geo.FillRound(g, track, radius, brush);
                }
                if (_anim < 0.99f) {
                    using (var off = new SolidBrush(Color.FromArgb((int)((1f - _anim) * 180), NlppTheme.OffTrack))) {
                        Geo.FillRound(g, track, radius, off);
                    }
                }
            }
            int travel = track.Width - track.Height;
            int x = track.X + 2 + (int)(travel * _anim) - 1;
            var thumb = new Rectangle(x, track.Y + 2, track.Height - 4, track.Height - 4);
            using (var thumbBrush = new SolidBrush(Enabled ? Color.White : Color.FromArgb(180, 186, 198))) {
                g.FillEllipse(thumbBrush, thumb);
            }
        }
    }

    public class ClockMark : Control {
        public ClockMark() {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer, true);
            Size = new Size(16, 16);
            BackColor = NlppTheme.Bg;
        }

        protected override void OnPaint(PaintEventArgs e) {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var pen = new Pen(NlppTheme.Muted, 1.4f)) {
                g.DrawEllipse(pen, 1, 1, 13, 13);
                g.DrawLine(pen, 7.5f, 8f, 7.5f, 4.2f);
                g.DrawLine(pen, 7.5f, 8f, 10.6f, 9.4f);
            }
        }
    }
}
'@

Add-Type -TypeDefinition $uiCode -ReferencedAssemblies System.Windows.Forms, System.Drawing

function Get-UiFamilyName([string[]]$preferred) {
    $have = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    foreach ($fam in [System.Drawing.FontFamily]::Families) {
        [void]$have.Add($fam.Name)
    }
    foreach ($name in $preferred) {
        if ($have.Contains($name)) { return $name }
    }
    return "Segoe UI"
}

$titleFamily = Get-UiFamilyName @("Segoe UI Variable Display", "Segoe UI Variable", "Segoe UI")
$bodyFamily = Get-UiFamilyName @("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI")

$bg = [NlppUi.NlppTheme]::Bg
$muted = [NlppUi.NlppTheme]::Muted
$text = [NlppUi.NlppTheme]::Text

$form = New-Object NlppUi.PatcherForm
$form.Text = "New Love Plus+ English Patcher"
$form.Font = New-Object System.Drawing.Font($bodyFamily, 9)
$form.StartPosition = "CenterScreen"
$form.AllowDrop = $true
$form.FormBorderStyle = "FixedSingle"
$form.MaximizeBox = $false
$form.MinimizeBox = $true

$tips = New-Object System.Windows.Forms.ToolTip
$tips.AutoPopDelay = 15000

$margin = 28
$innerW = 644
$formW = $innerW + ($margin * 2)

# --- Header -------------------------------------------------------------
$label = New-Object System.Windows.Forms.Label
$label.Text = "Drop a New Love Plus+ .cia / .3ds here"
$label.Font = New-Object System.Drawing.Font($titleFamily, 18, [System.Drawing.FontStyle]::Bold)
$label.ForeColor = $text
$label.BackColor = $bg
$label.AutoSize = $false
$label.TextAlign = "MiddleCenter"
$label.SetBounds($margin, 16, $innerW, 40)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = "Decrypt your dump first. The patcher builds an installable CIA for FBI."
$hint.Font = New-Object System.Drawing.Font($bodyFamily, 9.5)
$hint.ForeColor = $muted
$hint.BackColor = $bg
$hint.AutoSize = $false
$hint.TextAlign = "MiddleCenter"
$hint.SetBounds($margin, 56, $innerW, 22)

# --- Zone 1: input ------------------------------------------------------
$drop = New-Object NlppUi.DropZone
$drop.Font = New-Object System.Drawing.Font($bodyFamily, 9)
$drop.SetBounds($margin, 88, $innerW, 108)

$field = New-Object NlppUi.FieldWell
$field.SetBounds(16, 34, ($innerW - 16 - 16 - 124), 44)

$pathBox = New-Object System.Windows.Forms.TextBox
$pathBox.ReadOnly = $true
$pathBox.BorderStyle = "None"
$pathBox.BackColor = [NlppUi.NlppTheme]::Field
$pathBox.ForeColor = $muted
$pathBox.Font = New-Object System.Drawing.Font($bodyFamily, 10)
$pathBox.Text = "(no file selected - drop it anywhere on this window)"
$pathBox.SetBounds(12, 12, ($field.Width - 24), 22)
$field.Controls.Add($pathBox)

$browse = New-Object NlppUi.GradientButton
$browse.Text = "Browse..."
$browse.Pill = $false
$browse.CornerRadius = 10
$browse.Font = New-Object System.Drawing.Font($bodyFamily, 10, [System.Drawing.FontStyle]::Bold)
$browse.SetBounds(($innerW - 16 - 112), 34, 112, 44)

$drop.Controls.Add($field)
$drop.Controls.Add($browse)

# --- Zone 2: options ----------------------------------------------------
$rowH = 36
$rows = $(if ($isCheckout) { 2 } else { 1 })
$optH = 36 + ($rows * $rowH) + 14

$optBox = New-Object NlppUi.OptionsCard
$optBox.Font = New-Object System.Drawing.Font($bodyFamily, 9.5)
$optBox.SetBounds($margin, ($drop.Bottom + 16), $innerW, $optH)

$geminiText = New-Object System.Windows.Forms.Label
$geminiText.Text = "Include Gemini translations (Nene, Rinko, SMS) - machine pass, unreviewed"
$geminiText.Font = New-Object System.Drawing.Font($bodyFamily, 9.5)
$geminiText.ForeColor = $text
$geminiText.BackColor = [NlppUi.NlppTheme]::Panel
$geminiText.AutoSize = $false
$geminiText.TextAlign = "MiddleLeft"
$geminiText.SetBounds(18, 34, ($innerW - 18 - 72), $rowH)
$tips.SetToolTip($geminiText, "Off: community Nene/Rinko layer and Japanese SMS.`nOn: fill the rest with the Gemini machine pass.`nReviewed workbench lines ship either way and win over Gemini.")

$gemini = New-Object NlppUi.ToggleSwitch
$gemini.SetBounds(($innerW - 18 - 48), 40, 48, 26)
$gemini.Checked = ($env:NLPP_INCLUDE_GEMINI_NENE -ne "0")
$tips.SetToolTip($gemini, $tips.GetToolTip($geminiText))

$optBox.Controls.Add($geminiText)
$optBox.Controls.Add($gemini)

if ($isCheckout) {
    $goldText = New-Object System.Windows.Forms.Label
    $goldText.Text = "Download the gold bake from GitHub (fast; leaves out local edits)"
    $goldText.Font = New-Object System.Drawing.Font($bodyFamily, 9.5)
    $goldText.ForeColor = $text
    $goldText.BackColor = [NlppUi.NlppTheme]::Panel
    $goldText.AutoSize = $false
    $goldText.TextAlign = "MiddleLeft"
    $goldText.SetBounds(18, (34 + $rowH), ($innerW - 18 - 72), $rowH)
    $tips.SetToolTip($goldText, "The gold bake is built from main.`nTurn off to build from this checkout instead (~45 min) so your`nname-input / message-speed patches, UI PNGs, and TRB edits are included.")

    $gold = New-Object NlppUi.ToggleSwitch
    $gold.SetBounds(($innerW - 18 - 48), (40 + $rowH), 48, 26)
    $gold.Checked = ($env:NLPP_SKIP_GOLD_FETCH -ne "1")
    $tips.SetToolTip($gold, $tips.GetToolTip($goldText))

    $optBox.Controls.Add($goldText)
    $optBox.Controls.Add($gold)
}

# --- Zone 3: action -----------------------------------------------------
$go = New-Object NlppUi.GradientButton
$go.Text = "Patch"
$go.Font = New-Object System.Drawing.Font($bodyFamily, 13, [System.Drawing.FontStyle]::Bold)
$go.Enabled = $false
$goW = 236
$goH = 64
$backup = New-Object NlppUi.NoticeCard
$backup.Text = "Back up your save and extra data (extdata) first, e.g. with Checkpoint or JKSM.`nInstall the patched CIA over the existing game - do not delete it first."
$backup.Font = New-Object System.Drawing.Font($bodyFamily, 9.5)
$backup.SetBounds($margin, ($optBox.Bottom + 14), $innerW, 54)

$goTop = $backup.Bottom + 8
$go.SetBounds([int](($formW - $goW) / 2), $goTop, $goW, $goH)

# --- Status bar ---------------------------------------------------------
$statusTop = $go.Bottom + 4

$clock = New-Object NlppUi.ClockMark
$clock.SetBounds($margin, ($statusTop + 3), 16, 16)

$status = New-Object System.Windows.Forms.Label
$status.Text = "Waiting for a .cia / .3ds drop..."
$status.Font = New-Object System.Drawing.Font($bodyFamily, 9)
$status.ForeColor = $muted
$status.BackColor = $bg
$status.AutoSize = $false
$status.TextAlign = "MiddleLeft"
$status.SetBounds(($margin + 22), $statusTop, 420, 22)

$openLog = New-Object System.Windows.Forms.Label
$openLog.Text = "Open patch log"
$openLog.Font = New-Object System.Drawing.Font($bodyFamily, 9, [System.Drawing.FontStyle]::Underline)
$openLog.ForeColor = [NlppUi.NlppTheme]::Link
$openLog.BackColor = $bg
$openLog.AutoSize = $false
$openLog.TextAlign = "MiddleRight"
$openLog.Cursor = [System.Windows.Forms.Cursors]::Hand
$openLog.SetBounds(($formW - $margin - 140), $statusTop, 140, 22)

$form.ClientSize = New-Object System.Drawing.Size($formW, ($status.Bottom + 16))

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
    $pathBox.ForeColor = $text
    $pathBox.SelectionStart = $pathBox.Text.Length
    $go.Enabled = $true
    $drop.Ready = $true
    $drop.Hot = $false
    $status.Text = "Ready - click Patch (or drop another dump)."
}

$onDragEnter = {
    param($sender, $e)
    if ($e.Data.GetDataPresent([Windows.Forms.DataFormats]::FileDrop)) {
        $e.Effect = [Windows.Forms.DragDropEffects]::Copy
        $drop.Hot = $true
    }
}
$onDragLeave = {
    $pt = $form.PointToClient([System.Windows.Forms.Cursor]::Position)
    if (-not $form.ClientRectangle.Contains($pt)) {
        $drop.Hot = $false
    }
}
$onDragDrop = {
    param($sender, $e)
    $drop.Hot = $false
    $files = [string[]]$e.Data.GetData([Windows.Forms.DataFormats]::FileDrop)
    if ($files -and $files.Count -gt 0) {
        Set-Cia $files[0]
    }
}
# Child controls swallow drags, so every surface takes the drop.
$dropTargets = @($form, $label, $hint, $drop, $field, $pathBox, $optBox, $geminiText, $gemini, $backup, $clock, $status)
if ($isCheckout) {
    $dropTargets += @($goldText, $gold)
}
foreach ($c in $dropTargets) {
    $c.AllowDrop = $true
    $c.Add_DragEnter($onDragEnter)
    $c.Add_DragLeave($onDragLeave)
    $c.Add_DragDrop($onDragDrop)
}

$browse.Add_Click({
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Filter = "3DS dumps (*.cia;*.3ds;*.cci)|*.cia;*.3ds;*.cci|CIA (*.cia)|*.cia|3DS/CCI (*.3ds;*.cci)|*.3ds;*.cci|All files (*.*)|*.*"
    $dlg.Title = "Select New Love Plus+ dump"
    if ($dlg.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) {
        Set-Cia $dlg.FileName
    }
})

$openLog.Add_Click({
    if (Test-Path -LiteralPath $logPath) {
        Start-Process -FilePath $logPath
    } elseif (Test-Path -LiteralPath $outDir) {
        Start-Process -FilePath explorer.exe -ArgumentList "`"$outDir`""
    } else {
        $status.Text = "No patch log yet - it appears in out\log.txt after a run."
    }
})

$go.Add_Click({
    if (-not $script:ciaPath) { return }
    $answer = [System.Windows.Forms.MessageBox]::Show(
        "Have you backed up your save and extra data (extdata)?`n`nUse Checkpoint or JKSM on 3DS, or on Azahar:`n    python tools\restore_azahar_extdata.py backup`n`nInstall the patched CIA over the existing game - do not delete it first.",
        "Back up your save first",
        [Windows.Forms.MessageBoxButtons]::YesNo,
        [Windows.Forms.MessageBoxIcon]::Warning,
        [Windows.Forms.MessageBoxDefaultButton]::Button2
    )
    if ($answer -ne [Windows.Forms.DialogResult]::Yes) {
        $status.Text = "Cancelled - back up your save and extdata first."
        [System.Windows.Forms.MessageBox]::Show(
            "Patching cancelled.`n`nBack up your save and extdata first, then click Patch again.",
            "Back up your save first",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
        return
    }
    $go.Enabled = $false
    $browse.Enabled = $false
    $optBox.Enabled = $false
    $status.Text = "Patching... a console window will show progress."
    $form.Refresh()
    # The bat skips its console questions when these are preset.
    $env:NLPP_BACKUP_CONFIRMED = "1"
    $env:NLPP_INCLUDE_GEMINI_NENE = $(if ($gemini.Checked) { "1" } else { "0" })
    if ($isCheckout) {
        $env:NLPP_SKIP_GOLD_FETCH = $(if ($gold.Checked) { "0" } else { "1" })
    }
    $launchPath = Get-SafeRomPath $script:ciaPath
    # Quote explicitly — Start-Process ArgumentList does not protect spaces/parens.
    # Go through "cmd /c call": a .bat started directly loses "exit /b 1" from
    # inside nested if-blocks and reports 0, so failures showed "Patch complete".
    $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/d /c call `"$bat`" `"$launchPath`"" -WorkingDirectory $root -PassThru -Wait
    if ($p.ExitCode -eq 0) {
        $status.Text = "Done. Install out\NewLovePlusPlus-EN.cia with FBI."
        [System.Windows.Forms.MessageBox]::Show(
            "Patched CIA (install with FBI):`n$ciaOut`n`nBefore installing, back up your save and extdata (Checkpoint / JKSM).`nInstall over the existing game; do not delete it first.`n`nPatch log (PATCH SUMMARY):`n$logPath`n`nScratch work files were cleaned up.",
            "Patch complete",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    } else {
        $status.Text = "Patch failed (exit $($p.ExitCode)). Check the console or the patch log."
    }
    $go.Enabled = $true
    $browse.Enabled = $true
    $optBox.Enabled = $true
})

$form.Controls.Add($label)
$form.Controls.Add($hint)
$form.Controls.Add($drop)
$form.Controls.Add($optBox)
$form.Controls.Add($backup)
$form.Controls.Add($go)
$form.Controls.Add($clock)
$form.Controls.Add($status)
$form.Controls.Add($openLog)
# Keep the placeholder path from opening highlighted.
$form.ActiveControl = $browse

[void]$form.ShowDialog()
