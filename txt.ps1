Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Speech

if (-not ("Keyboard" -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Keyboard {
    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, int dwFlags, int dwExtraInfo);
    public const int KEYEVENTF_KEYDOWN = 0x0000;
    public const int KEYEVENTF_KEYUP = 0x0002;
    public const byte VK_LWIN = 0x5B;
    public const byte VK_H = 0x48;
}
"@
}

if (-not ("TablessTabControl" -as [type])) {
    # TCM_ADJUSTRECT (0x1328) normally reserves space for the tab strip and borders;
    # answering it lets the pages fill the whole control, so navigation can be custom.
    $tablessReferences = @(
        [Windows.Forms.TabControl].Assembly.Location,
        [Windows.Forms.Message].Assembly.Location,
        [System.ComponentModel.Component].Assembly.Location
    ) | Select-Object -Unique
    Add-Type -ReferencedAssemblies $tablessReferences -TypeDefinition @"
using System;
using System.Windows.Forms;
public class TablessTabControl : TabControl {
    protected override void WndProc(ref Message m) {
        if (m.Msg == 0x1328 && !DesignMode) {
            m.Result = (IntPtr)1;
            return;
        }
        base.WndProc(ref m);
    }
}
"@
}

if (-not ("OverlayScrollBar" -as [type])) {
    # Native Win32 scrollbars ignore WinForms colors and dark themes in this host, so the
    # editor hides its own bar and this thin, themed overlay mirrors and drives it.
    $overlayReferences = @(
        [Windows.Forms.Control].Assembly.Location,
        [Windows.Forms.Message].Assembly.Location,
        [System.ComponentModel.Component].Assembly.Location,
        [Drawing.Color].Assembly.Location,
        [Drawing.Graphics].Assembly.Location,
        [Drawing.Rectangle].Assembly.Location
    ) | Select-Object -Unique
    Add-Type -ReferencedAssemblies $overlayReferences -TypeDefinition @"
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public class OverlayScrollBar : Control {
    private const int EM_LINESCROLL = 0x00B6;
    private const int EM_GETLINECOUNT = 0x00BA;
    private const int EM_GETFIRSTVISIBLELINE = 0x00CE;

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr hwnd, int message, IntPtr wParam, IntPtr lParam);

    private readonly TextBox target;
    private readonly Timer syncTimer;
    private int firstLine;
    private int lineCount;
    private int visibleLines = 1;
    private bool hovering;
    private bool dragging;
    private int dragOffset;

    public Color TrackColor = Color.Transparent;
    public Color ThumbColor = Color.Gray;
    public Color ThumbActiveColor = Color.DarkGray;

    public OverlayScrollBar(TextBox target) {
        this.target = target;
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                 ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        Dock = DockStyle.Right;
        Width = 14;
        Cursor = Cursors.Default;
        // EM_* queries are cheap; polling keeps the thumb in sync with typing, wheel and caret moves.
        syncTimer = new Timer();
        syncTimer.Interval = 50;
        syncTimer.Tick += delegate { Sync(); };
        syncTimer.Start();
        // An edit control without WS_VSCROLL ignores the wheel, so the overlay scrolls it.
        target.MouseWheel += delegate(object sender, MouseEventArgs e) { WheelScroll(e.Delta); };
    }

    private void WheelScroll(int delta) {
        int current = Send(EM_GETFIRSTVISIBLELINE, 0, 0);
        int lines = SystemInformation.MouseWheelScrollLines;
        if (lines <= 0) {
            lines = visibleLines;
        }
        ScrollToLine(current - (delta * lines) / 120);
    }

    private int Send(int message, int wParam, int lParam) {
        return (int)SendMessage(target.Handle, message, (IntPtr)wParam, (IntPtr)lParam);
    }

    public void Sync() {
        if (!target.IsHandleCreated) {
            return;
        }
        int lineHeight = Math.Max(1, target.Font.Height);
        int visible = Math.Max(1, target.ClientSize.Height / lineHeight);
        int count = Send(EM_GETLINECOUNT, 0, 0);
        int first = Send(EM_GETFIRSTVISIBLELINE, 0, 0);
        bool needed = count > visible;
        if (Visible != needed) {
            Visible = needed;
        }
        if (first != firstLine || count != lineCount || visible != visibleLines) {
            firstLine = first;
            lineCount = count;
            visibleLines = visible;
            Invalidate();
        }
    }

    private int MaxFirstLine {
        get { return Math.Max(1, lineCount - visibleLines); }
    }

    private Rectangle TrackBounds {
        get { return new Rectangle(0, 4, Width, Math.Max(1, Height - 8)); }
    }

    private Rectangle ThumbBounds {
        get {
            Rectangle track = TrackBounds;
            int thumbHeight = Math.Max(32, (int)(track.Height * (double)visibleLines / Math.Max(1, lineCount)));
            thumbHeight = Math.Min(track.Height, thumbHeight);
            double position = Math.Min(firstLine, MaxFirstLine) / (double)MaxFirstLine;
            int top = track.Top + (int)((track.Height - thumbHeight) * position);
            int thumbWidth = (hovering || dragging) ? 8 : 5;
            return new Rectangle(Width - thumbWidth - 3, top, thumbWidth, thumbHeight);
        }
    }

    private void ScrollToLine(int line) {
        line = Math.Max(0, Math.Min(line, MaxFirstLine));
        int current = Send(EM_GETFIRSTVISIBLELINE, 0, 0);
        if (line != current) {
            Send(EM_LINESCROLL, 0, line - current);
        }
        Sync();
    }

    private int LineFromThumbTop(int thumbTop) {
        Rectangle track = TrackBounds;
        int travel = Math.Max(1, track.Height - ThumbBounds.Height);
        double ratio = (thumbTop - track.Top) / (double)travel;
        return (int)Math.Round(Math.Max(0.0, Math.Min(1.0, ratio)) * MaxFirstLine);
    }

    protected override void OnPaint(PaintEventArgs e) {
        e.Graphics.Clear(TrackColor == Color.Transparent ? BackColor : TrackColor);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        Rectangle thumb = ThumbBounds;
        int radius = thumb.Width;
        using (GraphicsPath path = new GraphicsPath())
        using (SolidBrush brush = new SolidBrush((hovering || dragging) ? ThumbActiveColor : ThumbColor)) {
            path.AddArc(thumb.Left, thumb.Top, radius, radius, 180, 90);
            path.AddArc(thumb.Right - radius, thumb.Top, radius, radius, 270, 90);
            path.AddArc(thumb.Right - radius, thumb.Bottom - radius, radius, radius, 0, 90);
            path.AddArc(thumb.Left, thumb.Bottom - radius, radius, radius, 90, 90);
            path.CloseFigure();
            e.Graphics.FillPath(brush, path);
        }
    }

    protected override void OnMouseEnter(EventArgs e) {
        hovering = true;
        Invalidate();
        base.OnMouseEnter(e);
    }

    protected override void OnMouseLeave(EventArgs e) {
        hovering = false;
        Invalidate();
        base.OnMouseLeave(e);
    }

    protected override void OnMouseDown(MouseEventArgs e) {
        if (e.Button != MouseButtons.Left) {
            return;
        }
        Rectangle thumb = ThumbBounds;
        if (e.Y >= thumb.Top && e.Y <= thumb.Bottom) {
            dragOffset = e.Y - thumb.Top;
        } else {
            // Clicking the track centers the thumb on the pointer, like modern editors.
            dragOffset = thumb.Height / 2;
            ScrollToLine(LineFromThumbTop(e.Y - dragOffset));
        }
        dragging = true;
        Capture = true;
        Invalidate();
    }

    protected override void OnMouseMove(MouseEventArgs e) {
        if (dragging) {
            ScrollToLine(LineFromThumbTop(e.Y - dragOffset));
        }
        base.OnMouseMove(e);
    }

    protected override void OnMouseUp(MouseEventArgs e) {
        dragging = false;
        Capture = false;
        Invalidate();
        base.OnMouseUp(e);
    }

    protected override void OnMouseWheel(MouseEventArgs e) {
        WheelScroll(e.Delta);
    }

    protected override void Dispose(bool disposing) {
        if (disposing) {
            syncTimer.Dispose();
        }
        base.Dispose(disposing);
    }
}
"@
}

if (-not ("WindowChrome" -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class WindowChrome {
    [DllImport("dwmapi.dll")]
    public static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);
}
"@
}

if (-not ("AudioProcessControl" -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class AudioProcessControl {
    [DllImport("ntdll.dll")]
    public static extern uint NtSuspendProcess(IntPtr processHandle);
    [DllImport("ntdll.dll")]
    public static extern uint NtResumeProcess(IntPtr processHandle);
}
"@
}

$form = New-Object Windows.Forms.Form
$form.Text = "Corrector de Prompt"
$form.Size = New-Object Drawing.Size(1200, 720)
$form.StartPosition = "CenterScreen"
$form.MinimumSize = New-Object Drawing.Size(1300, 600)
$form.WindowState = [Windows.Forms.FormWindowState]::Maximized
$appVersionPath = Join-Path $PSScriptRoot "VERSION"
$appVersion = if (Test-Path -LiteralPath $appVersionPath) {
    (Get-Content -LiteralPath $appVersionPath -Raw).Trim()
} else {
    "v:00.00.00-00.00"
}

$tabs = New-Object TablessTabControl
$tabs.Dock = "Fill"

$tabEditor = New-Object Windows.Forms.TabPage
$tabEditor.Text = "Editor"
$tabEditor.Padding = New-Object Windows.Forms.Padding(20, 16, 4, 16)

$tabPreview = New-Object Windows.Forms.TabPage
$tabPreview.Text = "Vista previa"

$tabSettings = New-Object Windows.Forms.TabPage
$tabSettings.Text = "Configuración"
$tabSettings.Padding = New-Object Windows.Forms.Padding(28)

$textBox = New-Object Windows.Forms.TextBox
$textBox.Multiline = $true
# 0 lifts the 32 767-character limit that applies to keyboard paste (Ctrl+V).
$textBox.MaxLength = 0
# The native bar stays hidden; OverlayScrollBar draws a themed one only when needed.
$textBox.ScrollBars = "None"
$textBox.Dock = "Fill"
$installedFontNames = @([Drawing.FontFamily]::Families | ForEach-Object { $_.Name })
$uiFontName = if ($installedFontNames -contains "Segoe UI Variable Text") { "Segoe UI Variable Text" } else { "Segoe UI" }
$uiStrongFontName = if ($installedFontNames -contains "Segoe UI Variable Text Semibold") { "Segoe UI Variable Text Semibold" } else { "Segoe UI Semibold" }
$editorFontName = if ($installedFontNames -contains "Cascadia Mono") { "Cascadia Mono" } else { "Consolas" }
$textBox.Font = New-Object Drawing.Font($editorFontName, 12)
$textBox.BorderStyle = [Windows.Forms.BorderStyle]::None
$tabEditor.Controls.Add($textBox)
# Added after the Fill editor so docking reserves the right edge for the overlay bar.
$editorScrollBar = New-Object OverlayScrollBar($textBox)
$tabEditor.Controls.Add($editorScrollBar)

$contextPanel = New-Object Windows.Forms.Panel
$contextPanel.Dock = "Top"
$contextPanel.Height = 46
$contextPanel.Padding = New-Object Windows.Forms.Padding(8, 6, 8, 6)
# Keep the default z-order: docking runs back to front, so this Top panel reserves its
# strip before the Fill editor. BringToFront() would dock it last, over the first lines.
$tabEditor.Controls.Add($contextPanel)

$preview = New-Object Windows.Forms.WebBrowser
$preview.Dock = "Fill"
$preview.ScriptErrorsSuppressed = $true
$tabPreview.Controls.Add($preview)

$tabs.TabPages.Add($tabEditor)
$tabs.TabPages.Add($tabPreview)
$tabs.TabPages.Add($tabSettings)
# The native tab strip cannot be themed; TablessTabControl hides it and the header
# segmented control below drives navigation instead.
$form.Controls.Add($tabs)

$statusPanel = New-Object Windows.Forms.Panel
$statusPanel.Dock = "Top"
$statusPanel.Height = 52
$statusPanel.Padding = New-Object Windows.Forms.Padding(14, 10, 14, 10)

$msgHost = New-Object Windows.Forms.Panel
$msgHost.Dock = "Fill"
$msgHost.Padding = New-Object Windows.Forms.Padding(16, 8, 8, 0)
$statusPanel.Controls.Add($msgHost)

$msgBox = New-Object Windows.Forms.TextBox
$msgBox.Multiline = $false
$msgBox.ReadOnly = $true
$msgBox.TabStop = $false
$msgBox.BorderStyle = [Windows.Forms.BorderStyle]::None
$msgBox.Dock = "Top"
$msgBox.Font = New-Object Drawing.Font($uiFontName, 10)
$msgHost.Controls.Add($msgBox)

$spinnerLabel = New-Object Windows.Forms.Label
$spinnerLabel.Dock = "Right"
$spinnerLabel.Width = 190
$spinnerLabel.TextAlign = [Drawing.ContentAlignment]::MiddleCenter
$spinnerLabel.Font = New-Object Drawing.Font($uiStrongFontName, 10)
$spinnerLabel.Visible = $false
$spinnerLabel.Tag = 0
$statusPanel.Controls.Add($spinnerLabel)

$navHost = New-Object Windows.Forms.Panel
$navHost.Dock = "Left"
$navHost.Width = 236
$statusPanel.Controls.Add($navHost)

$btnNavEditor = New-Object Windows.Forms.Button
$btnNavEditor.Text = "Editor"
$btnNavEditor.SetBounds(3, 3, 113, 26)
$navHost.Controls.Add($btnNavEditor)

$btnNavPreview = New-Object Windows.Forms.Button
$btnNavPreview.Text = "Vista previa"
$btnNavPreview.SetBounds(120, 3, 113, 26)
$navHost.Controls.Add($btnNavPreview)

$settingsNavHost = New-Object Windows.Forms.Panel
$settingsNavHost.Dock = "Right"
$settingsNavHost.Width = 560
$statusPanel.Controls.Add($settingsNavHost)

$btnNavSettings = New-Object Windows.Forms.Button
$btnNavSettings.Text = "Configuración"
$btnNavSettings.SetBounds(5, 3, 145, 26)
$settingsNavHost.Controls.Add($btnNavSettings)

$lblHeaderModel = New-Object Windows.Forms.Label
$lblHeaderModel.Text = "Modelo"
$lblHeaderModel.TextAlign = [Drawing.ContentAlignment]::MiddleRight
$lblHeaderModel.SetBounds(158, 3, 58, 26)
$settingsNavHost.Controls.Add($lblHeaderModel)

$spinnerFrames = @("● ○ ○", "○ ● ○", "○ ○ ●")
$spinnerTimer = New-Object Windows.Forms.Timer
$spinnerTimer.Interval = 100
$spinnerTimer.Add_Tick({
    $index = [int]$spinnerLabel.Tag
    $spinnerLabel.Text = "$($spinnerFrames[$index]) Procesando..."
    $busyLabel.Text = "$($spinnerFrames[$index]) $($busyForm.Tag)"
    $spinnerLabel.Tag = ($index + 1) % $spinnerFrames.Count
})

$form.Controls.Add($statusPanel)

$busyForm = New-Object Windows.Forms.Form
$busyForm.Text = "Procesando con IA"
$busyForm.Size = New-Object Drawing.Size(380, 145)
$busyForm.StartPosition = [Windows.Forms.FormStartPosition]::Manual
$busyForm.FormBorderStyle = [Windows.Forms.FormBorderStyle]::FixedDialog
$busyForm.ControlBox = $false
$busyForm.MaximizeBox = $false
$busyForm.MinimizeBox = $false
$busyForm.ShowInTaskbar = $false

$busyLabel = New-Object Windows.Forms.Label
$busyLabel.Dock = "Fill"
$busyLabel.TextAlign = [Drawing.ContentAlignment]::MiddleCenter
$busyLabel.Font = New-Object Drawing.Font($uiStrongFontName, 12)
$busyForm.Controls.Add($busyLabel)

$panel = New-Object Windows.Forms.Panel
$panel.Dock = "Bottom"
$panel.Height = 188
$form.Controls.Add($panel)

$btnPreguntar = New-Object Windows.Forms.Button
$btnPreguntar.Text = "Consultar IA"
$btnPreguntar.SetBounds(14, 12, 130, 34)
$panel.Controls.Add($btnPreguntar)

$btnResumir = New-Object Windows.Forms.Button
$btnResumir.Text = "Resumir con IA"
$btnResumir.SetBounds(152, 12, 140, 34)
$panel.Controls.Add($btnResumir)

$btnCorregir = New-Object Windows.Forms.Button
$btnCorregir.Text = "Corregir Gramática y Ortografía"
$btnCorregir.SetBounds(300, 12, 240, 34)
$panel.Controls.Add($btnCorregir)

$btnTraducirEs = New-Object Windows.Forms.Button
$btnTraducirEs.Text = "Traducir Inglés a Español"
$btnTraducirEs.SetBounds(548, 12, 210, 34)
$panel.Controls.Add($btnTraducirEs)

$btnTraducirEn = New-Object Windows.Forms.Button
$btnTraducirEn.Text = "Traducir Español a Inglés"
$btnTraducirEn.SetBounds(766, 12, 210, 34)
$panel.Controls.Add($btnTraducirEn)

$btnLeer = New-Object Windows.Forms.Button
$btnLeer.Text = "Play"
$btnLeer.SetBounds(668, 96, 80, 34)
$panel.Controls.Add($btnLeer)

$btnPauseVoice = New-Object Windows.Forms.Button
$btnPauseVoice.Text = "Pausar"
$btnPauseVoice.SetBounds(756, 96, 100, 34)
$panel.Controls.Add($btnPauseVoice)

$btnPegar = New-Object Windows.Forms.Button
$btnPegar.Text = "Pegar desde el portapapeles al editor"
$btnPegar.SetBounds(14, 54, 230, 34)
$panel.Controls.Add($btnPegar)

$btnCopyMd = New-Object Windows.Forms.Button
$btnCopyMd.Text = "Copiar MD"
$btnCopyMd.SetBounds(415, 54, 160, 34)
$panel.Controls.Add($btnCopyMd)

$btnCopyTxt = New-Object Windows.Forms.Button
$btnCopyTxt.Text = "Copiar TXT"
$btnCopyTxt.SetBounds(583, 54, 165, 34)
$panel.Controls.Add($btnCopyTxt)

$btnMic = New-Object Windows.Forms.Button
$btnMic.Text = [System.Text.Encoding]::UTF8.GetString([System.Text.Encoding]::Default.GetBytes("Micrófono"))
$btnMic.SetBounds(756, 54, 120, 34)
$panel.Controls.Add($btnMic)

$btnPdf = New-Object Windows.Forms.Button
$btnPdf.Text = "PDF"
$btnPdf.SetBounds(884, 54, 70, 34)
$panel.Controls.Add($btnPdf)

$btnMp3 = New-Object Windows.Forms.Button
$btnMp3.Text = "MP3"
$btnMp3.SetBounds(962, 54, 70, 34)
$panel.Controls.Add($btnMp3)

$btnLimpiar = New-Object Windows.Forms.Button
$btnLimpiar.Text = "Limpiar chat"
$btnLimpiar.SetBounds(1040, 54, 120, 34)
$panel.Controls.Add($btnLimpiar)

$btnTheme = New-Object Windows.Forms.Button
$btnTheme.Text = "Modo: Dark"
$btnTheme.Tag = $true
$btnTheme.SetBounds(984, 96, 150, 34)
$panel.Controls.Add($btnTheme)

$btnCerrar = New-Object Windows.Forms.Button
$btnCerrar.Text = "Cerrar"
$btnCerrar.SetBounds(1142, 96, 110, 34)
$panel.Controls.Add($btnCerrar)

$lblVoice = New-Object Windows.Forms.Label
$lblVoice.Text = "Voz"
$lblVoice.TextAlign = [Drawing.ContentAlignment]::MiddleLeft
$lblVoice.SetBounds(336, 96, 40, 34)
$panel.Controls.Add($lblVoice)

$voiceCombo = New-Object Windows.Forms.ComboBox
$voiceCombo.DropDownStyle = [Windows.Forms.ComboBoxStyle]::DropDownList
$voiceCombo.FlatStyle = [Windows.Forms.FlatStyle]::Flat
$voiceCombo.DropDownWidth = 430
$voiceCombo.SetBounds(378, 101, 280, 34)
$panel.Controls.Add($voiceCombo)

function New-ToggleGroup {
    param(
        [int]$left,
        [string[]]$labels
    )

    # Each group lives in its own container so the two radio sets stay independent.
    $group = New-Object Windows.Forms.Panel
    $group.SetBounds($left, 98, 152, 30)
    $buttons = @()
    for ($index = 0; $index -lt $labels.Count; $index++) {
        $toggle = New-Object Windows.Forms.RadioButton
        $toggle.Appearance = [Windows.Forms.Appearance]::Button
        $toggle.TextAlign = [Drawing.ContentAlignment]::MiddleCenter
        $toggle.FlatStyle = [Windows.Forms.FlatStyle]::Flat
        $toggle.Cursor = [Windows.Forms.Cursors]::Hand
        $toggle.Text = $labels[$index]
        $toggle.SetBounds($index * 76, 0, 76, 30)
        $group.Controls.Add($toggle)
        $buttons += $toggle
    }
    $panel.Controls.Add($group)
    return , $buttons
}

$genderToggles = New-ToggleGroup 14 @("Hombre", "Mujer")
$rbMale = $genderToggles[0]
$rbFemale = $genderToggles[1]
$languageToggles = New-ToggleGroup 174 @("Español", "Inglés")
$rbSpanish = $languageToggles[0]
$rbEnglish = $languageToggles[1]
$rbMale.Checked = $true
$rbSpanish.Checked = $true
$voiceToggles = @($rbMale, $rbFemale, $rbSpanish, $rbEnglish)

$btnStopVoice = New-Object Windows.Forms.Button
$btnStopVoice.Text = "Detener"
$btnStopVoice.SetBounds(864, 96, 100, 34)
$panel.Controls.Add($btnStopVoice)

$lblSpeed = New-Object Windows.Forms.Label
$lblSpeed.Text = "Velocidad de lectura"
$lblSpeed.TextAlign = [Drawing.ContentAlignment]::MiddleLeft
$lblSpeed.SetBounds(14, 138, 150, 34)
$panel.Controls.Add($lblSpeed)

$speedSlider = New-Object Windows.Forms.TrackBar
$speedSlider.Minimum = 50
$speedSlider.Maximum = 200
$speedSlider.Value = 100
$speedSlider.SmallChange = 5
$speedSlider.LargeChange = 25
$speedSlider.TickFrequency = 25
$speedSlider.AutoSize = $false
$speedSlider.SetBounds(172, 139, 250, 32)
$panel.Controls.Add($speedSlider)

$lblSpeedValue = New-Object Windows.Forms.Label
$lblSpeedValue.Text = "1,00x"
$lblSpeedValue.TextAlign = [Drawing.ContentAlignment]::MiddleLeft
$lblSpeedValue.SetBounds(430, 138, 65, 34)
$panel.Controls.Add($lblSpeedValue)

$versionLabel = New-Object Windows.Forms.Label
$versionLabel.Text = $appVersion
$versionLabel.TextAlign = [Drawing.ContentAlignment]::MiddleRight
$versionLabel.Anchor = [Windows.Forms.AnchorStyles]::Bottom -bor [Windows.Forms.AnchorStyles]::Right
$versionLabel.SetBounds(1060, 146, 180, 26)
$panel.Controls.Add($versionLabel)

$settingsTitle = New-Object Windows.Forms.Label
$settingsTitle.Text = "Configuración"
$settingsTitle.Font = New-Object Drawing.Font($uiStrongFontName, 18)
$settingsTitle.SetBounds(28, 24, 500, 40)
$tabSettings.Controls.Add($settingsTitle)

$settingsHint = New-Object Windows.Forms.Label
$settingsHint.Text = "La API key se cifra para tu usuario de Windows. Los modelos se consultan directamente desde Groq."
$settingsHint.SetBounds(30, 67, 570, 26)
$tabSettings.Controls.Add($settingsHint)

$lblAppVersion = New-Object Windows.Forms.Label
$lblAppVersion.Text = "Aplicación $appVersion"
$lblAppVersion.TextAlign = [Drawing.ContentAlignment]::MiddleLeft
$lblAppVersion.SetBounds(620, 25, 175, 30)
$tabSettings.Controls.Add($lblAppVersion)

$btnCheckUpdate = New-Object Windows.Forms.Button
$btnCheckUpdate.Text = "Buscar actualización"
$btnCheckUpdate.SetBounds(800, 24, 165, 32)
$tabSettings.Controls.Add($btnCheckUpdate)

$btnInstallUpdate = New-Object Windows.Forms.Button
$btnInstallUpdate.Text = "Actualizar ahora"
$btnInstallUpdate.SetBounds(975, 24, 160, 32)
$btnInstallUpdate.Visible = $false
$tabSettings.Controls.Add($btnInstallUpdate)

$lblUpdateStatus = New-Object Windows.Forms.Label
$lblUpdateStatus.Text = "Actualizaciones todavía no comprobadas."
$lblUpdateStatus.TextAlign = [Drawing.ContentAlignment]::MiddleLeft
$lblUpdateStatus.AutoEllipsis = $true
$lblUpdateStatus.SetBounds(620, 64, 515, 28)
$tabSettings.Controls.Add($lblUpdateStatus)

$lblApiKey = New-Object Windows.Forms.Label
$lblApiKey.Text = "API key"
$lblApiKey.SetBounds(30, 110, 100, 26)
$tabSettings.Controls.Add($lblApiKey)

$txtApiKey = New-Object Windows.Forms.TextBox
$txtApiKey.UseSystemPasswordChar = $true
$txtApiKey.SetBounds(140, 106, 470, 30)
$tabSettings.Controls.Add($txtApiKey)

$btnSaveSettings = New-Object Windows.Forms.Button
$btnSaveSettings.Text = "Guardar"
$btnSaveSettings.SetBounds(622, 104, 110, 32)
$tabSettings.Controls.Add($btnSaveSettings)

$btnRefreshModels = New-Object Windows.Forms.Button
$btnRefreshModels.Text = "Actualizar modelos"
$btnRefreshModels.SetBounds(742, 104, 165, 32)
$tabSettings.Controls.Add($btnRefreshModels)

$modelCombo = New-Object Windows.Forms.ComboBox
$modelCombo.DropDownStyle = [Windows.Forms.ComboBoxStyle]::DropDownList
$modelCombo.FlatStyle = [Windows.Forms.FlatStyle]::Flat
$modelCombo.SetBounds(220, 3, 330, 26)
$settingsNavHost.Controls.Add($modelCombo)

$checkWebSearch = New-Object Windows.Forms.CheckBox
$checkWebSearch.Text = "Usar web en la próxima consulta"
$checkWebSearch.SetBounds(120, 8, 245, 28)
$contextPanel.Controls.Add($checkWebSearch)

$btnAttachFiles = New-Object Windows.Forms.Button
$btnAttachFiles.Text = "Adjuntar archivos"
$btnAttachFiles.SetBounds(252, 54, 155, 34)
$panel.Controls.Add($btnAttachFiles)

$btnClearAttachments = New-Object Windows.Forms.Button
$btnClearAttachments.Text = "Quitar adjuntos"
$btnClearAttachments.Anchor = [Windows.Forms.AnchorStyles]::Top -bor [Windows.Forms.AnchorStyles]::Right
$btnClearAttachments.SetBounds(1000, 7, 135, 30)
$contextPanel.Controls.Add($btnClearAttachments)

$lblContextTitle = New-Object Windows.Forms.Label
$lblContextTitle.Text = "Contexto IA"
$lblContextTitle.TextAlign = [Drawing.ContentAlignment]::MiddleLeft
$lblContextTitle.SetBounds(8, 8, 105, 28)
$contextPanel.Controls.Add($lblContextTitle)

# Icons for what the selected model can do; rebuilt by Update-CapabilityBadges.
$capabilityBadgeHost = New-Object Windows.Forms.Panel
$capabilityBadgeHost.SetBounds(113, 8, 0, 28)
$contextPanel.Controls.Add($capabilityBadgeHost)
$capabilityIconFontName = if ($installedFontNames -contains "Segoe Fluent Icons") { "Segoe Fluent Icons" } else { "Segoe MDL2 Assets" }

$lblAttachments = New-Object Windows.Forms.Label
$lblAttachments.Text = "Sin archivos adjuntos para la próxima solicitud"
$lblAttachments.TextAlign = [Drawing.ContentAlignment]::MiddleLeft
$lblAttachments.AutoEllipsis = $true
# Left and width are computed by Update-ContextLayout after the badges change.
$lblAttachments.Anchor = [Windows.Forms.AnchorStyles]::Top -bor [Windows.Forms.AnchorStyles]::Left
$lblAttachments.SetBounds(378, 8, 610, 28)
$contextPanel.Controls.Add($lblAttachments)

$contextToolTip = New-Object Windows.Forms.ToolTip
$contextToolTip.AutoPopDelay = 12000

$modelsList = New-Object Windows.Forms.ListView
$modelsList.View = [Windows.Forms.View]::Details
$modelsList.FullRowSelect = $true
$modelsList.HideSelection = $false
$modelsList.MultiSelect = $false
$modelsList.Anchor = [Windows.Forms.AnchorStyles]::Top -bor [Windows.Forms.AnchorStyles]::Bottom -bor [Windows.Forms.AnchorStyles]::Left -bor [Windows.Forms.AnchorStyles]::Right
$modelsList.SetBounds(30, 154, 1120, 400)
[void]$modelsList.Columns.Add("Modelo", 330)
[void]$modelsList.Columns.Add("Proveedor", 140)
[void]$modelsList.Columns.Add("Contexto", 100)
[void]$modelsList.Columns.Add("Funciones", 500)
$tabSettings.Controls.Add($modelsList)

$settingsStatus = New-Object Windows.Forms.Label
$settingsStatus.Text = "Configurá una API key para actualizar la lista."
$settingsStatus.Anchor = [Windows.Forms.AnchorStyles]::Bottom -bor [Windows.Forms.AnchorStyles]::Left -bor [Windows.Forms.AnchorStyles]::Right
$settingsStatus.SetBounds(30, 564, 1120, 28)
$tabSettings.Controls.Add($settingsStatus)

$settingsDirectory = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "TXT Preview"
$settingsPath = Join-Path $settingsDirectory "settings.json"
$script:groqApiKey = ""
$script:selectedGroqModel = "openai/gpt-oss-120b"
$script:attachedFiles = [Collections.Generic.List[object]]::new()
$script:updateCheckCompleted = $false
$script:availableUpdateVersion = $null
$script:availableGroqModels = @(
    [pscustomobject]@{ id = "allam-2-7b"; owned_by = "SDAIA"; context_window = 4096; active = $true }
    [pscustomobject]@{ id = "canopylabs/orpheus-arabic-saudi"; owned_by = "Canopy Labs"; context_window = 4000; active = $true }
    [pscustomobject]@{ id = "canopylabs/orpheus-v1-english"; owned_by = "Canopy Labs"; context_window = 4000; active = $true }
    [pscustomobject]@{ id = "meta-llama/llama-prompt-guard-2-22m"; owned_by = "Meta"; context_window = 512; active = $true }
    [pscustomobject]@{ id = "meta-llama/llama-prompt-guard-2-86m"; owned_by = "Meta"; context_window = 512; active = $true }
    [pscustomobject]@{ id = "openai/gpt-oss-120b"; owned_by = "OpenAI"; context_window = 131072; active = $true }
    [pscustomobject]@{ id = "openai/gpt-oss-20b"; owned_by = "OpenAI"; context_window = 131072; active = $true }
    [pscustomobject]@{ id = "openai/gpt-oss-safeguard-20b"; owned_by = "OpenAI"; context_window = 131072; active = $true }
    [pscustomobject]@{ id = "qwen/qwen3.8-27b"; owned_by = "Alibaba Cloud"; context_window = 131072; active = $true }
    [pscustomobject]@{ id = "whisper-large-v3"; owned_by = "OpenAI"; context_window = 448; active = $true }
    [pscustomobject]@{ id = "whisper-large-v3-turbo"; owned_by = "OpenAI"; context_window = 448; active = $true }
)

function Get-GroqModelCapabilities {
    param([string]$modelId)

    if ($modelId -eq "qwen/qwen3.8-27b") {
        return [pscustomobject]@{
            Chat = $true; Reasoning = $true; Web = $false; Vision = $true; TextFiles = $true
            Summary = "Texto · Razonamiento · Visión · Imágenes (máx. 3) · Archivos de texto"
        }
    }
    if ($modelId -in @("openai/gpt-oss-120b", "openai/gpt-oss-20b")) {
        return [pscustomobject]@{
            Chat = $true; Reasoning = $true; Web = $true; Vision = $false; TextFiles = $true
            Summary = "Texto · Razonamiento · Búsqueda web · Archivos de texto"
        }
    }
    if ($modelId -eq "allam-2-7b") {
        return [pscustomobject]@{
            Chat = $true; Reasoning = $false; Web = $false; Vision = $false; TextFiles = $true
            Summary = "Texto · Árabe · Archivos de texto"
        }
    }
    if ($modelId -eq "openai/gpt-oss-safeguard-20b") {
        return [pscustomobject]@{
            Chat = $false; Reasoning = $false; Web = $true; Vision = $false; TextFiles = $false
            Summary = "Seguridad · Moderación · Búsqueda web"
        }
    }
    if ($modelId -like "whisper-*") {
        return [pscustomobject]@{
            Chat = $false; Reasoning = $false; Web = $false; Vision = $false; TextFiles = $false
            Summary = "Transcripción y traducción de audio"
        }
    }
    if ($modelId -like "canopylabs/orpheus-*") {
        return [pscustomobject]@{
            Chat = $false; Reasoning = $false; Web = $false; Vision = $false; TextFiles = $false
            Summary = "Texto a voz"
        }
    }
    if ($modelId -like "meta-llama/llama-prompt-guard-*") {
        return [pscustomobject]@{
            Chat = $false; Reasoning = $false; Web = $false; Vision = $false; TextFiles = $false
            Summary = "Clasificación de seguridad de prompts"
        }
    }
    return [pscustomobject]@{
        Chat = $false; Reasoning = $false; Web = $false; Vision = $false; TextFiles = $false
        Summary = "Capacidades no catalogadas"
    }
}

function Get-SelectedModelCapabilities {
    return Get-GroqModelCapabilities $script:selectedGroqModel
}

function Test-GroqInputAvailable {
    return -not [string]::IsNullOrWhiteSpace($textBox.Text) -or $script:attachedFiles.Count -gt 0
}

function Update-AttachmentSummary {
    if ($script:attachedFiles.Count -eq 0) {
        $lblAttachments.Text = "Sin archivos adjuntos para la próxima solicitud"
        $contextToolTip.SetToolTip($lblAttachments, "")
        $btnClearAttachments.Visible = $false
    } else {
        $names = @($script:attachedFiles | ForEach-Object { $_.Name })
        $attachmentText = "Se enviarán a Groq ($($names.Count)): " + ($names -join ", ")
        $lblAttachments.Text = $attachmentText
        $contextToolTip.SetToolTip($lblAttachments, $attachmentText)
        $btnClearAttachments.Visible = $true
    }
    Update-ContextLayout
}

function Update-ContextLayout {
    $gap = 8
    $titleWidth = [Windows.Forms.TextRenderer]::MeasureText($lblContextTitle.Text, $lblContextTitle.Font).Width
    $lblContextTitle.Width = $titleWidth + 4
    $capabilityBadgeHost.Left = $lblContextTitle.Right + 2
    $nextLeft = $capabilityBadgeHost.Right + $gap
    # Read the state, not .Visible: it reports false until the form is shown.
    if ((Get-SelectedModelCapabilities).Web) {
        $checkWebSearch.Left = $nextLeft
        $nextLeft = $checkWebSearch.Right + $gap
    }
    $rightLimit = $contextPanel.ClientSize.Width - $contextPanel.Padding.Right
    if ($script:attachedFiles.Count -gt 0) {
        $rightLimit -= $btnClearAttachments.Width + $gap
    }
    $lblAttachments.Left = $nextLeft
    $lblAttachments.Width = [Math]::Max(0, $rightLimit - $nextLeft)
}

function Update-CapabilityBadges {
    $capabilities = Get-SelectedModelCapabilities
    $badges = @(
        @{ Enabled = $capabilities.Chat; Glyph = 0xE8BD; Tip = "Chat de texto" }
        @{ Enabled = $capabilities.Reasoning; Glyph = 0xE82F; Tip = "Razonamiento" }
        @{ Enabled = $capabilities.Web; Glyph = 0xE774; Tip = "Navegación y búsqueda web" }
        @{ Enabled = $capabilities.Vision; Glyph = 0xE890; Tip = "Visión: entiende imágenes" }
        @{ Enabled = $capabilities.TextFiles; Glyph = 0xE723; Tip = "Archivos de texto adjuntos" }
    )

    $oldBadges = @($capabilityBadgeHost.Controls)
    $capabilityBadgeHost.Controls.Clear()
    foreach ($oldBadge in $oldBadges) {
        $oldBadge.Dispose()
    }

    $badgeWidth = 26
    $left = 0
    foreach ($badge in @($badges | Where-Object { $_.Enabled })) {
        $icon = New-Object Windows.Forms.Label
        $icon.Text = [string][char]$badge.Glyph
        $icon.Font = New-Object Drawing.Font($capabilityIconFontName, 12)
        $icon.TextAlign = [Drawing.ContentAlignment]::MiddleCenter
        $icon.ForeColor = Get-ThemeColor "Notice"
        $icon.BackColor = Get-ThemeColor "Elevated"
        $icon.SetBounds($left, 0, $badgeWidth, $capabilityBadgeHost.Height)
        $contextToolTip.SetToolTip($icon, $badge.Tip)
        $capabilityBadgeHost.Controls.Add($icon)
        $left += $badgeWidth
    }
    $capabilityBadgeHost.Width = $left
    $capabilityBadgeHost.BackColor = Get-ThemeColor "Elevated"
    Update-ContextLayout
}

function Update-ModelCapabilityControls {
    if ($modelCombo.SelectedIndex -ge 0) {
        $script:selectedGroqModel = [string]$modelCombo.SelectedItem
    }
    $capabilities = Get-SelectedModelCapabilities
    $checkWebSearch.Enabled = $capabilities.Web
    $checkWebSearch.Visible = $capabilities.Web
    if (-not $capabilities.Web) {
        $checkWebSearch.Checked = $false
    }
    $btnAttachFiles.Enabled = $capabilities.TextFiles -or $capabilities.Vision
    $btnAttachFiles.Visible = $btnAttachFiles.Enabled
    Set-StatusText $settingsStatus "$($script:selectedGroqModel) · $($capabilities.Summary)"

    $incompatible = @($script:attachedFiles | Where-Object { $_.Kind -eq "Image" -and -not $capabilities.Vision })
    foreach ($attachment in $incompatible) {
        [void]$script:attachedFiles.Remove($attachment)
    }
    Update-AttachmentSummary
    Update-CapabilityBadges
    Update-ToolbarLayout
}

$contextPanel.Add_Resize({ Update-ContextLayout })

function Show-GroqModels {
    param($models)

    $script:availableGroqModels = @($models | Sort-Object id)
    $modelsList.BeginUpdate()
    $modelsList.Items.Clear()
    $modelCombo.BeginUpdate()
    $modelCombo.Items.Clear()

    foreach ($model in $script:availableGroqModels) {
        $capabilities = Get-GroqModelCapabilities $model.id
        $context = if ($null -ne $model.context_window) { "{0:N0}" -f [int64]$model.context_window } else { "-" }
        $item = New-Object Windows.Forms.ListViewItem([string]$model.id)
        [void]$item.SubItems.Add([string]$model.owned_by)
        [void]$item.SubItems.Add($context)
        [void]$item.SubItems.Add($capabilities.Summary)
        $item.Tag = [string]$model.id
        [void]$modelsList.Items.Add($item)
        if ($capabilities.Chat) {
            [void]$modelCombo.Items.Add([string]$model.id)
        }
    }

    $modelCombo.EndUpdate()
    $modelsList.EndUpdate()
    $selectedIndex = $modelCombo.FindStringExact($script:selectedGroqModel)
    if ($selectedIndex -lt 0 -and $modelCombo.Items.Count -gt 0) {
        $selectedIndex = 0
    }
    if ($selectedIndex -ge 0) {
        $modelCombo.SelectedIndex = $selectedIndex
    }
    Update-ModelCapabilityControls
}

function Convert-SecureStringToPlainText {
    param([Security.SecureString]$secureValue)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Load-AppSettings {
    $environmentKey = [Environment]::GetEnvironmentVariable("GROQ_API_KEY", "User")
    if ([string]::IsNullOrWhiteSpace($environmentKey)) {
        $environmentKey = $env:GROQ_API_KEY
    }
    if ($environmentKey) {
        $script:groqApiKey = $environmentKey
        $txtApiKey.Text = $environmentKey
    }

    if (-not (Test-Path -LiteralPath $settingsPath)) {
        Show-GroqModels $script:availableGroqModels
        return
    }

    try {
        $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($settings.EncryptedApiKey) {
            $secureKey = ConvertTo-SecureString ([string]$settings.EncryptedApiKey)
            $script:groqApiKey = Convert-SecureStringToPlainText $secureKey
            $txtApiKey.Text = $script:groqApiKey
        }
        if ($settings.Model) {
            $script:selectedGroqModel = [string]$settings.Model
        }
        $checkWebSearch.Checked = [bool]$settings.WebSearch
    } catch {
        Set-StatusText $settingsStatus "No se pudo cargar la configuración: $($_.Exception.Message)" -Level Error
    }
    Show-GroqModels $script:availableGroqModels
}

function Save-AppSettings {
    $apiKey = $txtApiKey.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        throw "Ingresá una API key de Groq."
    }

    [void][IO.Directory]::CreateDirectory($settingsDirectory)
    $secureKey = ConvertTo-SecureString $apiKey -AsPlainText -Force
    $settings = [ordered]@{
        EncryptedApiKey = ConvertFrom-SecureString $secureKey
        Model          = $script:selectedGroqModel
        WebSearch      = $checkWebSearch.Checked
    }
    [IO.File]::WriteAllText(
        $settingsPath,
        ($settings | ConvertTo-Json),
        [Text.UTF8Encoding]::new($false)
    )
    $script:groqApiKey = $apiKey
}

function Compare-AppVersions {
    param(
        [string]$leftVersion,
        [string]$rightVersion
    )

    $versionPattern = '^v:\d{2}\.\d{2}\.\d{2}-\d{2}\.\d{2}$'
    if ($leftVersion -notmatch $versionPattern -or $rightVersion -notmatch $versionPattern) {
        throw "La versión publicada no usa el formato esperado v:yy.mm.dd-HH.mm."
    }
    $leftNumber = [long]($leftVersion -replace '\D', '')
    $rightNumber = [long]($rightVersion -replace '\D', '')
    return $leftNumber.CompareTo($rightNumber)
}

function Invoke-GitCommand {
    param([string[]]$arguments)

    $gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
    if (-not $gitCommand) {
        $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    }
    if (-not $gitCommand) {
        throw "Git no está instalado o no está disponible en PATH."
    }

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $gitCommand.Source
    $startInfo.WorkingDirectory = $PSScriptRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.EnvironmentVariables["GIT_TERMINAL_PROMPT"] = "0"
    # ProcessStartInfo.ArgumentList is unavailable in Windows PowerShell 5.1.
    # Every argument used here is a fixed Git token without spaces.
    $startInfo.Arguments = $arguments -join " "

    $process = [Diagnostics.Process]::Start($startInfo)
    try {
        $standardOutput = $process.StandardOutput.ReadToEnd()
        $standardError = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Output = $standardOutput.Trim()
            Error = $standardError.Trim()
        }
    } finally {
        $process.Dispose()
    }
}

function Get-AvailableAppUpdate {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot ".git"))) {
        throw "La aplicación no se ejecuta desde un clon Git; no se puede actualizar automáticamente."
    }

    $branchResult = Invoke-GitCommand @("branch", "--show-current")
    if ($branchResult.ExitCode -ne 0 -or $branchResult.Output -ne "main") {
        throw "La actualización automática requiere estar en la rama main."
    }

    $fetchResult = Invoke-GitCommand @("fetch", "--quiet", "origin", "main")
    if ($fetchResult.ExitCode -ne 0) {
        throw "No se pudo consultar origin/main. $($fetchResult.Error)"
    }
    $versionResult = Invoke-GitCommand @("show", "FETCH_HEAD:VERSION")
    if ($versionResult.ExitCode -ne 0) {
        throw "No se pudo leer VERSION desde origin/main."
    }

    $remoteVersion = $versionResult.Output.Trim()
    return [pscustomobject]@{
        Version = $remoteVersion
        Available = (Compare-AppVersions $remoteVersion $appVersion) -gt 0
    }
}

function Update-AppUpdateControls {
    $btnCheckUpdate.Enabled = $false
    $btnInstallUpdate.Visible = $false
    Set-StatusText $lblUpdateStatus "Buscando una versión nueva en origin/main..."
    [Windows.Forms.Application]::DoEvents()
    try {
        $update = Get-AvailableAppUpdate
        if ($update.Available) {
            $script:availableUpdateVersion = $update.Version
            Set-StatusText $lblUpdateStatus "Nueva versión $($update.Version) disponible."
            $btnInstallUpdate.Visible = $true
        } else {
            $script:availableUpdateVersion = $null
            Set-StatusText $lblUpdateStatus "La aplicación está actualizada ($appVersion)."
        }
    } catch {
        $script:availableUpdateVersion = $null
        Set-StatusText $lblUpdateStatus "No se pudo comprobar: $($_.Exception.Message)" -Level Error
    } finally {
        $script:updateCheckCompleted = $true
        $btnCheckUpdate.Enabled = $true
    }
}

function Install-AppUpdate {
    $branchResult = Invoke-GitCommand @("branch", "--show-current")
    if ($branchResult.ExitCode -ne 0 -or $branchResult.Output -ne "main") {
        throw "La actualización automática requiere estar en la rama main."
    }

    $statusResult = Invoke-GitCommand @("status", "--porcelain")
    if ($statusResult.ExitCode -ne 0) {
        throw "No se pudo revisar el estado del repositorio."
    }
    if (-not [string]::IsNullOrWhiteSpace($statusResult.Output)) {
        throw "Hay cambios locales. Guardalos o confirmalos antes de actualizar."
    }

    $pullResult = Invoke-GitCommand @("pull", "--ff-only", "origin", "main")
    if ($pullResult.ExitCode -ne 0) {
        throw "Git no pudo aplicar la actualización sin sobrescribir cambios. $($pullResult.Error)"
    }

    $installedVersion = (Get-Content -LiteralPath $appVersionPath -Raw).Trim()
    [void](Compare-AppVersions $installedVersion $appVersion)
    return $installedVersion
}

function Get-GroqModelsFromApi {
    $apiKey = $txtApiKey.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        throw "Ingresá una API key de Groq."
    }

    $client = [Net.Http.HttpClient]::new()
    $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, "https://api.groq.com/openai/v1/models")
    $response = $null
    try {
        $request.Headers.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $apiKey)
        $response = Wait-TaskWithEvents ($client.SendAsync($request))
        $responseText = Wait-TaskWithEvents ($response.Content.ReadAsStringAsync())
        if (-not $response.IsSuccessStatusCode) {
            throw "Groq devolvió el estado HTTP $([int]$response.StatusCode)."
        }
        return @((ConvertFrom-Json $responseText).data | Where-Object { $_.active -ne $false })
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        $request.Dispose()
        $client.Dispose()
    }
}

$speechSynth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$pythonCommand = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
$edgeTtsWordsScript = Join-Path $PSScriptRoot "edge_tts_words.py"
$ffplayCommand = (Get-Command ffplay.exe -ErrorAction SilentlyContinue).Source
$ffprobeCommand = (Get-Command ffprobe.exe -ErrorAction SilentlyContinue).Source

# Scoop devuelve un lanzador que crea otro proceso. Para que Pausar controle
# el audio verdadero, se resuelve el ejecutable indicado por el archivo .shim.
if ($ffplayCommand) {
    $ffplayShimFile = [IO.Path]::ChangeExtension($ffplayCommand, ".shim")
    if (Test-Path -LiteralPath $ffplayShimFile) {
        $ffplayShimContent = Get-Content -LiteralPath $ffplayShimFile -Raw
        if ($ffplayShimContent -match '(?m)^path\s*=\s*"(?<executable>[^"]+)"' -and (Test-Path -LiteralPath $Matches.executable)) {
            $ffplayCommand = $Matches.executable
        }
    }
}
$availableVoices = @(
    $speechSynth.GetInstalledVoices() |
        Where-Object {
            $_.Enabled -and (
                $_.VoiceInfo.Culture.Name -like "es-*" -or
                $_.VoiceInfo.Culture.Name -like "en-*"
            )
        }
)

$voiceNameByDisplay = @{}
$voiceCultureByDisplay = @{}
$voiceProviderByDisplay = @{}
$voiceGenderByDisplay = @{}
$allVoiceDisplays = [Collections.Generic.List[string]]::new()

if ($pythonCommand) {
    try {
        $voiceListStartInfo = [Diagnostics.ProcessStartInfo]::new()
        $voiceListStartInfo.FileName = $pythonCommand
        $voiceListStartInfo.UseShellExecute = $false
        $voiceListStartInfo.CreateNoWindow = $true
        $voiceListStartInfo.RedirectStandardOutput = $true
        $voiceListStartInfo.RedirectStandardError = $true
        [void]$voiceListStartInfo.ArgumentList.Add("-m")
        [void]$voiceListStartInfo.ArgumentList.Add("edge_tts")
        [void]$voiceListStartInfo.ArgumentList.Add("--list-voices")

        $voiceListProcess = [Diagnostics.Process]::Start($voiceListStartInfo)
        $voiceListOutput = $voiceListProcess.StandardOutput.ReadToEnd()
        $voiceListProcess.WaitForExit()

        if ($voiceListProcess.ExitCode -eq 0) {
            $edgeVoiceLines = $voiceListOutput -split "`r?`n"
            foreach ($voiceLine in $edgeVoiceLines) {
                if ($voiceLine -match '^(?<name>(?<culture>(?:es|en)-[A-Z]{2})-\S+)\s+(?<gender>Female|Male)\s+') {
                    $displayName = "Edge · {0} ({1})" -f $Matches.name, $Matches.gender
                    $voiceNameByDisplay[$displayName] = $Matches.name
                    $voiceCultureByDisplay[$displayName] = $Matches.culture
                    $voiceProviderByDisplay[$displayName] = "Edge"
                    $voiceGenderByDisplay[$displayName] = $Matches.gender
                    $allVoiceDisplays.Add($displayName)
                }
            }
        }
        $voiceListProcess.Dispose()
    } catch {
        # Si Edge TTS no está disponible, se mantienen las voces locales.
    }
}

foreach ($installedVoice in $availableVoices) {
    $displayName = "Windows · {0} [{1}]" -f $installedVoice.VoiceInfo.Name, $installedVoice.VoiceInfo.Culture.Name
    $voiceNameByDisplay[$displayName] = $installedVoice.VoiceInfo.Name
    $voiceCultureByDisplay[$displayName] = $installedVoice.VoiceInfo.Culture.Name
    $voiceProviderByDisplay[$displayName] = "Windows"
    $voiceGenderByDisplay[$displayName] = [string]$installedVoice.VoiceInfo.Gender
    $allVoiceDisplays.Add($displayName)
}

# Preferred voice for each language and gender filter, in priority order.
$defaultVoiceByFilter = @{
    "es|Male"   = @("Edge · es-CR-JuanNeural (Male)", "Edge · es-AR-TomasNeural (Male)", "Windows · Microsoft Pablo [es-ES]")
    "es|Female" = @("Edge · es-DO-RamonaNeural (Female)", "Edge · es-AR-ElenaNeural (Female)", "Windows · Microsoft Laura [es-ES]")
    "en|Male"   = @("Edge · en-US-AndrewMultilingualNeural (Male)", "Edge · en-US-GuyNeural (Male)", "Windows · Microsoft David Desktop [en-US]")
    "en|Female" = @("Edge · en-US-EmmaMultilingualNeural (Female)", "Edge · en-US-JennyNeural (Female)", "Windows · Microsoft Zira Desktop [en-US]")
}

function Update-VoiceFilter {
    $language = if ($rbEnglish.Checked) { "en" } else { "es" }
    $gender = if ($rbFemale.Checked) { "Female" } else { "Male" }

    $voiceCombo.BeginUpdate()
    $voiceCombo.Items.Clear()
    foreach ($displayName in $allVoiceDisplays) {
        if ($voiceCultureByDisplay[$displayName] -like "$language-*" -and $voiceGenderByDisplay[$displayName] -eq $gender) {
            [void]$voiceCombo.Items.Add($displayName)
        }
    }
    $voiceCombo.EndUpdate()

    if ($voiceCombo.Items.Count -eq 0) {
        $msgBox.Text = "No hay voces instaladas para ese idioma y género."
        return
    }

    $selectedIndex = 0
    foreach ($candidate in $defaultVoiceByFilter["$language|$gender"]) {
        $candidateIndex = $voiceCombo.FindStringExact($candidate)
        if ($candidateIndex -ge 0) {
            $selectedIndex = $candidateIndex
            break
        }
    }
    $voiceCombo.SelectedIndex = $selectedIndex
}

foreach ($toggle in $voiceToggles) {
    # CheckedChanged fires for both the old and the new option; react only once.
    $toggle.Add_CheckedChanged({
        param($sender)
        if ($sender.Checked) {
            Update-VoiceFilter
        }
        Set-ToggleTones
    })
}
Update-VoiceFilter

$speechState = @{
    Mode                     = "Idle"
    Provider                 = $null
    VoiceDisplay             = $null
    VoiceName                = $null
    Chunks                   = @()
    CurrentIndex             = 0
    PlayerProcess            = $null
    PlayerStartedAt          = $null
    PauseStartedAt           = $null
    WindowsText              = ""
    WindowsCharacterPosition = 0
    HighlightTotalLength     = 0
    HighlightBaseOffset      = 0
    HighlightTotalWords      = 0
    HighlightBaseWordIndex   = 0
    HighlightTokenStarts     = [int[]]@()
    AlignWords               = [string[]]@()
    AlignCursor              = -1
    AlignMisses              = 0
    PendingSpokenWords       = [Collections.Generic.List[string]]::new()
    ControlState             = "Idle"
    SessionId                = 0
}

$edgeVoiceTimer = New-Object Windows.Forms.Timer
# 40 ms keeps the visual lag below one syllable; WinForms timers run on the UI thread.
$edgeVoiceTimer.Interval = 40
# Positive values move the highlight earlier to absorb timer and WebBrowser render latency.
$speechHighlightLeadSeconds = 0.06
# How many preview words ahead the aligner may look when a spoken word does not match.
$speechAlignmentWindow = 8

$actionButtons = @(
    $btnPreguntar, $btnResumir, $btnCorregir, $btnTraducirEs, $btnTraducirEn,
    $btnLeer, $btnPegar, $btnCopyMd, $btnCopyTxt, $btnMic, $btnPdf, $btnMp3, $btnLimpiar,
    $btnTheme, $btnCerrar, $btnPauseVoice, $btnStopVoice, $btnSaveSettings, $btnRefreshModels,
    $btnCheckUpdate, $btnInstallUpdate, $btnAttachFiles, $btnClearAttachments
)

$aiButtons = @($btnPreguntar, $btnResumir, $btnCorregir, $btnTraducirEs, $btnTraducirEn)

function Show-Message {
    param(
        [string]$texto,
        [ValidateSet("Info", "Warning", "Error")][string]$Level = "Info"
    )
    $text = [System.Text.Encoding]::UTF8.GetString([System.Text.Encoding]::Default.GetBytes($texto))
    Set-StatusText $msgBox $text -Level $Level
}

$themePalettes = @{
    Dark  = @{
        Window = "#0B0E14"; Surface = "#11151E"; Elevated = "#1A1F2B"; Hover = "#242A39"; Pressed = "#2E3547"
        Border = "#2A3142"; Text = "#E7EAF3"; Muted = "#8E97AD"; Editor = "#0E121A"
        Accent = "#8B93FF"; AccentHover = "#A3A9FF"; OnAccent = "#0B0E14"
        Play = "#34D399"; Pause = "#FBBF24"; Stop = "#FB7185"; OnState = "#0B0E14"
        Notice = "#6EE7B7"; Warning = "#FBBF24"; Danger = "#F87171"
        Code = "#151A25"; Heading = "#F3F5FB"; Link = "#A3A9FF"
        SpeechBackground = "#3B3F8F"; SpeechForeground = "#FFFFFF"
        Scrollbar = "#2A3142"; ScrollbarArrow = "#6B7490"
    }
    Light = @{
        Window = "#F4F5F9"; Surface = "#FFFFFF"; Elevated = "#F0F2F7"; Hover = "#E4E7F0"; Pressed = "#D7DBE7"
        Border = "#DCE0EA"; Text = "#161A26"; Muted = "#5E667A"; Editor = "#FFFFFF"
        Accent = "#5056E0"; AccentHover = "#6369EA"; OnAccent = "#FFFFFF"
        Play = "#059669"; Pause = "#D97706"; Stop = "#E11D48"; OnState = "#FFFFFF"
        Notice = "#047857"; Warning = "#B45309"; Danger = "#DC2626"
        Code = "#F3F4F8"; Heading = "#0F1220"; Link = "#4248D6"
        SpeechBackground = "#DDE0FF"; SpeechForeground = "#1A1D6B"
        Scrollbar = "#CDD2DE"; ScrollbarArrow = "#8A92A6"
    }
}
$activePalette = $themePalettes.Dark

function Get-ThemeColor {
    param([string]$name)

    return [Drawing.ColorTranslator]::FromHtml($activePalette[$name])
}

$infoFontSize = 9

# Last message level per control, so a theme change keeps errors red and warnings yellow.
$script:messageLevels = @{}

# Informational messages (status, updates, hints, attachments) share one font; the color
# follows the message level: Info uses Notice, Warning uses Warning, Error uses Danger.
function Set-InfoStyle {
    param($control)

    $level = if ($script:messageLevels.ContainsKey($control)) { $script:messageLevels[$control] } else { "Info" }
    $colorName = switch ($level) {
        "Error" { "Danger" }
        "Warning" { "Warning" }
        default { "Notice" }
    }
    $control.ForeColor = Get-ThemeColor $colorName
    $control.Font = New-Object Drawing.Font($uiStrongFontName, $infoFontSize)
}

function Set-StatusText {
    param(
        $control,
        [string]$text,
        [ValidateSet("Info", "Warning", "Error")][string]$Level = "Info"
    )

    $control.Text = $text
    $script:messageLevels[$control] = $Level
    Set-InfoStyle $control
}

function Set-WindowChrome {
    param(
        [Windows.Forms.Form]$window,
        [bool]$dark
    )

    # Reading Handle before the form is shown creates the native window at its initial
    # size, which leaves the maximized layout painting only that area; wait for Shown.
    if (-not $window.IsHandleCreated) {
        return
    }

    # Windows 11 title bar: dark mode flag plus caption colors that match the window.
    try {
        $darkFlag = [int]$dark
        [void][WindowChrome]::DwmSetWindowAttribute($window.Handle, 20, [ref]$darkFlag, 4)
        $captionColor = [Drawing.ColorTranslator]::ToWin32((Get-ThemeColor "Surface"))
        [void][WindowChrome]::DwmSetWindowAttribute($window.Handle, 35, [ref]$captionColor, 4)
        $captionTextColor = [Drawing.ColorTranslator]::ToWin32((Get-ThemeColor "Text"))
        [void][WindowChrome]::DwmSetWindowAttribute($window.Handle, 36, [ref]$captionTextColor, 4)
    } catch {
        # Older Windows builds ignore these attributes.
    }
}

function Set-ButtonTone {
    param(
        [Windows.Forms.Button]$button,
        [string]$background,
        [string]$foreground,
        [string]$hover,
        [string]$border
    )

    $button.BackColor = Get-ThemeColor $background
    $button.ForeColor = Get-ThemeColor $foreground
    $button.FlatAppearance.MouseOverBackColor = Get-ThemeColor $hover
    $button.FlatAppearance.MouseDownBackColor = Get-ThemeColor "Pressed"
    $button.FlatAppearance.BorderColor = Get-ThemeColor $border
}

function Set-ToggleTones {
    foreach ($toggle in $voiceToggles) {
        $toggle.FlatAppearance.BorderSize = 1
        $toggle.Font = New-Object Drawing.Font($uiStrongFontName, 9)
        $toggle.FlatAppearance.MouseDownBackColor = Get-ThemeColor "Pressed"
        $toggle.FlatAppearance.CheckedBackColor = Get-ThemeColor "Accent"
        if ($toggle.Checked) {
            $toggle.BackColor = Get-ThemeColor "Accent"
            $toggle.ForeColor = Get-ThemeColor "OnAccent"
            $toggle.FlatAppearance.BorderColor = Get-ThemeColor "Accent"
            $toggle.FlatAppearance.MouseOverBackColor = Get-ThemeColor "AccentHover"
        } else {
            $toggle.BackColor = Get-ThemeColor "Elevated"
            $toggle.ForeColor = Get-ThemeColor "Muted"
            $toggle.FlatAppearance.BorderColor = Get-ThemeColor "Border"
            $toggle.FlatAppearance.MouseOverBackColor = Get-ThemeColor "Hover"
        }
    }
}

function Update-NavigationState {
    foreach ($button in @($btnNavEditor, $btnNavPreview, $btnNavSettings)) {
        Set-ButtonTone $button "Elevated" "Muted" "Hover" "Elevated"
    }
    $activeNavigationButton = if ($tabs.SelectedTab -eq $tabPreview) {
        $btnNavPreview
    } elseif ($tabs.SelectedTab -eq $tabSettings) {
        $btnNavSettings
    } else {
        $btnNavEditor
    }
    Set-ButtonTone $activeNavigationButton "Accent" "OnAccent" "AccentHover" "Accent"
}

function Set-AudioControlState {
    param([ValidateSet("Idle", "Play", "Pause", "Stop")][string]$state)

    $speechState.ControlState = $state
    foreach ($button in @($btnLeer, $btnPauseVoice, $btnStopVoice)) {
        Set-ButtonTone $button "Elevated" "Text" "Hover" "Border"
    }

    $activeButton = switch ($state) {
        "Play" { $btnLeer }
        "Pause" { $btnPauseVoice }
        "Stop" { $btnStopVoice }
        default { $null }
    }
    if ($null -ne $activeButton) {
        $stateColor = switch ($state) {
            "Pause" { "Pause" }
            "Stop" { "Stop" }
            default { "Play" }
        }
        Set-ButtonTone $activeButton $stateColor "OnState" $stateColor $stateColor
    }
}

function Focus-SpeechPreview {
    if ($tabs.SelectedTab -ne $tabPreview) {
        $tabs.SelectedTab = $tabPreview
        $tabPreview.Select()
        [Windows.Forms.Application]::DoEvents()
    }
}

function Set-PreviewSpeechProgress {
    param([double]$ratio)

    if ($null -eq $preview.Document) {
        return
    }
    try {
        $boundedRatio = [Math]::Min(1.0, [Math]::Max(0.0, $ratio))
        [void]$preview.Document.InvokeScript("setSpeechProgress", [object[]]@($boundedRatio))
    } catch {
        # La siguiente actualización reintenta cuando el HTML termina de cargar.
    }
}

function Set-PreviewSpeechWordIndex {
    param([int]$wordIndex)

    if ($null -eq $preview.Document) {
        return
    }
    try {
        [void]$preview.Document.InvokeScript("setSpeechWordIndex", [object[]]@([Math]::Max(0, $wordIndex)))
    } catch {
        # La siguiente actualización reintenta cuando el HTML termina de cargar.
    }
}

function Clear-PreviewSpeechProgress {
    if ($null -eq $preview.Document) {
        return
    }
    try {
        [void]$preview.Document.InvokeScript("clearSpeechProgress")
    } catch {
        # La vista puede estar reconstruyéndose al cambiar de pestaña o tema.
    }
}

function Select-VoiceLanguage {
    param([ValidateSet("es", "en")][string]$language)

    # Switching the language toggle refilters the list and applies that filter's default voice.
    if ($language -eq "en") {
        $rbEnglish.Checked = $true
    } else {
        $rbSpanish.Checked = $true
    }
}

function Stop-TrackedProcess {
    param($process)

    if ($null -eq $process) {
        return
    }

    try {
        if (-not $process.HasExited) {
            $process.Kill()
            [void]$process.WaitForExit(2000)
        }
    } catch {
        # El proceso puede finalizar entre la comprobación y el cierre.
    } finally {
        $process.Dispose()
    }
}

function Remove-SpeechChunkFiles {
    foreach ($chunk in @($speechState.Chunks)) {
        Remove-Item -LiteralPath $chunk.TextFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $chunk.MediaFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $chunk.TimingFile -Force -ErrorAction SilentlyContinue
    }
}

function Stop-VoicePlayback {
    param(
        [ValidateSet("Idle", "Stop")][string]$ControlState = "Idle",
        [switch]$KeepHighlight
    )

    $edgeVoiceTimer.Stop()
    if ($speechSynth.State -eq [System.Speech.Synthesis.SynthesizerState]::Paused) {
        $speechSynth.Resume()
    }
    $speechSynth.SpeakAsyncCancelAll()

    Stop-TrackedProcess $speechState.PlayerProcess
    foreach ($chunk in @($speechState.Chunks)) {
        Stop-TrackedProcess $chunk.Process
        $chunk.Process = $null
    }

    Remove-SpeechChunkFiles
    $speechState.Mode = "Idle"
    $speechState.Provider = $null
    $speechState.VoiceDisplay = $null
    $speechState.VoiceName = $null
    $speechState.Chunks = @()
    $speechState.CurrentIndex = 0
    $speechState.PlayerProcess = $null
    $speechState.PlayerStartedAt = $null
    $speechState.PauseStartedAt = $null
    $speechState.WindowsText = ""
    $speechState.WindowsCharacterPosition = 0
    $btnPauseVoice.Text = "Pausar"
    if (-not $KeepHighlight) {
        $speechState.HighlightTotalLength = 0
        $speechState.HighlightBaseOffset = 0
        $speechState.HighlightTotalWords = 0
        $speechState.HighlightBaseWordIndex = 0
        $speechState.HighlightTokenStarts = [int[]]@()
        Reset-SpeechAlignment
        Clear-PreviewSpeechProgress
    }
    Set-AudioControlState $ControlState
}

function Split-TextIntoSpeechChunks {
    param(
        [string]$text,
        [int]$desiredChunks = 6
    )

    $paragraphs = @(
        [regex]::Split($text.Trim(), '(?:\r?\n)+') |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )

    if ($paragraphs.Count -eq 0) {
        return @()
    }

    $groupCount = [Math]::Min($desiredChunks, $paragraphs.Count)
    $groups = [Collections.Generic.List[string]]::new()
    $paragraphIndex = 0

    for ($groupIndex = 0; $groupIndex -lt $groupCount; $groupIndex++) {
        $remainingGroups = $groupCount - $groupIndex
        $remainingLength = 0
        for ($index = $paragraphIndex; $index -lt $paragraphs.Count; $index++) {
            $remainingLength += $paragraphs[$index].Length
        }
        $targetLength = [Math]::Ceiling($remainingLength / $remainingGroups)
        $parts = [Collections.Generic.List[string]]::new()
        $currentLength = 0

        while ($paragraphIndex -lt $paragraphs.Count) {
            $parts.Add($paragraphs[$paragraphIndex])
            $currentLength += $paragraphs[$paragraphIndex].Length
            $paragraphIndex++

            $paragraphsLeft = $paragraphs.Count - $paragraphIndex
            $groupsLeft = $groupCount - $groupIndex - 1
            if ($groupsLeft -gt 0 -and $currentLength -ge $targetLength -and $paragraphsLeft -ge $groupsLeft) {
                break
            }
            if ($paragraphsLeft -eq $groupsLeft) {
                break
            }
        }

        $groups.Add(($parts -join ([Environment]::NewLine + [Environment]::NewLine)))
    }

    return $groups.ToArray()
}

function Get-AudioDurationSeconds {
    param(
        [string]$mediaFile,
        [string]$text
    )

    if ($ffprobeCommand) {
        try {
            $probeStartInfo = [Diagnostics.ProcessStartInfo]::new()
            $probeStartInfo.FileName = $ffprobeCommand
            $probeStartInfo.UseShellExecute = $false
            $probeStartInfo.CreateNoWindow = $true
            $probeStartInfo.RedirectStandardOutput = $true
            $probeStartInfo.RedirectStandardError = $true
            foreach ($argument in @("-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", $mediaFile)) {
                [void]$probeStartInfo.ArgumentList.Add($argument)
            }

            $probeProcess = [Diagnostics.Process]::Start($probeStartInfo)
            $durationText = $probeProcess.StandardOutput.ReadToEnd().Trim()
            $probeProcess.WaitForExit()
            $probeProcess.Dispose()
            $duration = 0.0
            if ([double]::TryParse($durationText, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$duration)) {
                return $duration
            }
        } catch {
            # Se usa una estimación si ffprobe no puede leer el archivo.
        }
    }

    $wordCount = ([regex]::Matches($text, '\S+')).Count
    return [Math]::Max(1.0, $wordCount / 2.5)
}

function Start-EdgeChunkGeneration {
    param(
        $chunk,
        [string]$voiceName,
        [int]$ratePercent
    )

    [IO.File]::WriteAllText($chunk.TextFile, $chunk.Text, [Text.UTF8Encoding]::new($false))
    $generateStartInfo = [Diagnostics.ProcessStartInfo]::new()
    $generateStartInfo.FileName = $pythonCommand
    $generateStartInfo.UseShellExecute = $false
    $generateStartInfo.CreateNoWindow = $true
    $generateStartInfo.RedirectStandardError = $true
    foreach ($argument in @(
        $edgeTtsWordsScript,
        "--voice", $voiceName,
        "--rate", ([string]($ratePercent - 100)),
        "--text-file", $chunk.TextFile,
        "--media-file", $chunk.MediaFile,
        "--timings-file", $chunk.TimingFile
    )) {
        [void]$generateStartInfo.ArgumentList.Add($argument)
    }

    $chunk.Process = [Diagnostics.Process]::Start($generateStartInfo)
    $chunk.Status = "Generating"
}

function Start-CurrentEdgeChunk {
    if ($speechState.Mode -eq "Paused") {
        return
    }

    if ($null -ne $speechState.PlayerProcess) {
        return
    }

    if ($speechState.CurrentIndex -ge $speechState.Chunks.Count) {
        $edgeVoiceTimer.Stop()
        Remove-SpeechChunkFiles
        $speechState.Chunks = @()
        $speechState.Mode = "Idle"
        $speechState.Provider = $null
        $speechState.PauseStartedAt = $null
        $btnPauseVoice.Text = "Pausar"
        Set-PreviewSpeechProgress 1.0
        Set-AudioControlState "Idle"
        Clear-PreviewSpeechProgress
        Show-Message "Lectura con voz Edge finalizada."
        return
    }

    $chunk = $speechState.Chunks[$speechState.CurrentIndex]
    if ($chunk.Status -eq "Failed") {
        $detail = if ($chunk.ErrorText) { $chunk.ErrorText } else { "Edge no generó el bloque de audio." }
        Stop-VoicePlayback
        Show-Message "No se pudo generar la voz Edge: $detail" -Level Error
        return
    }
    if ($chunk.Status -ne "Ready") {
        $speechState.Mode = "Generating"
        return
    }

    try {
        $playStartInfo = [Diagnostics.ProcessStartInfo]::new()
        $playStartInfo.FileName = $ffplayCommand
        $playStartInfo.UseShellExecute = $false
        $playStartInfo.CreateNoWindow = $true
        $playStartInfo.RedirectStandardError = $true
        foreach ($argument in @("-nodisp", "-autoexit", "-loglevel", "error", $chunk.MediaFile)) {
            [void]$playStartInfo.ArgumentList.Add($argument)
        }

        $speechState.PlayerProcess = [Diagnostics.Process]::Start($playStartInfo)
        $speechState.PlayerStartedAt = [DateTime]::UtcNow
        $speechState.PauseStartedAt = $null
        $speechState.Mode = "Playing"
        $chunk.Status = "Playing"
        Show-Message "Reproduciendo bloque $($speechState.CurrentIndex + 1) de $($speechState.Chunks.Count) · $($speechState.VoiceDisplay)"
    } catch {
        Stop-VoicePlayback
        Show-Message "No se pudo reproducir el audio Edge: $($_.Exception.Message)" -Level Error
    }
}

function Update-EdgeVoicePlayback {
    foreach ($chunk in @($speechState.Chunks)) {
        if ($chunk.Status -ne "Generating" -or $null -eq $chunk.Process -or -not $chunk.Process.HasExited) {
            continue
        }

        $exitCode = $chunk.Process.ExitCode
        $errorText = $chunk.Process.StandardError.ReadToEnd().Trim()
        $chunk.Process.Dispose()
        $chunk.Process = $null
        Remove-Item -LiteralPath $chunk.TextFile -Force -ErrorAction SilentlyContinue

        if (
            $exitCode -eq 0 -and
            (Test-Path -LiteralPath $chunk.MediaFile) -and
            (Test-Path -LiteralPath $chunk.TimingFile)
        ) {
            $chunk.DurationSeconds = Get-AudioDurationSeconds $chunk.MediaFile $chunk.Text
            $chunk.WordTimings = @(
                Get-Content -LiteralPath $chunk.TimingFile -Raw -Encoding UTF8 |
                    ConvertFrom-Json
            )
            Remove-Item -LiteralPath $chunk.TimingFile -Force -ErrorAction SilentlyContinue
            $chunk.WordMarks = @(Get-EdgeWordMarks $chunk.Text $chunk.WordTimings)
            $chunk.Status = "Ready"
        } else {
            $chunk.Status = "Failed"
            $chunk.ErrorText = if ($errorText) { ($errorText -split "`r?`n")[-1] } else { "El bloque $($chunk.Index + 1) no pudo generarse." }
        }
    }

    if ($null -ne $speechState.PlayerProcess -and $speechState.PlayerProcess.HasExited) {
        $playerExitCode = $speechState.PlayerProcess.ExitCode
        $playerError = $speechState.PlayerProcess.StandardError.ReadToEnd().Trim()
        $speechState.PlayerProcess.Dispose()
        $speechState.PlayerProcess = $null
        $speechState.PlayerStartedAt = $null
        $speechState.PauseStartedAt = $null

        $completedChunk = $speechState.Chunks[$speechState.CurrentIndex]
        if ($speechState.AlignWords.Count -gt 0) {
            Sync-EdgeChunkAlignment $completedChunk (@($completedChunk.WordMarks).Count - 1)
        }
        $completedChunk.Status = "Played"
        Remove-Item -LiteralPath $completedChunk.MediaFile -Force -ErrorAction SilentlyContinue

        if ($playerExitCode -ne 0) {
            $detail = if ($playerError) { ($playerError -split "`r?`n")[-1] } else { "El reproductor terminó con código $playerExitCode." }
            Stop-VoicePlayback
            Show-Message "No se pudo reproducir la voz Edge: $detail" -Level Error
            return
        }

        $speechState.CurrentIndex++
    }

    Start-CurrentEdgeChunk
}

function Start-EdgeSpeechSession {
    param(
        [string]$text,
        [string]$voiceDisplay,
        [string]$voiceName
    )

    if (-not $pythonCommand) {
        throw "No se encontró Python para generar la voz Edge."
    }
    if (-not (Test-Path -LiteralPath $edgeTtsWordsScript)) {
        throw "No se encontró el generador de sincronización WordBoundary."
    }
    if (-not $ffplayCommand) {
        throw "No se encontró ffplay para reproducir la voz Edge."
    }

    $speechState.SessionId++
    $speechState.Provider = "Edge"
    $speechState.VoiceDisplay = $voiceDisplay
    $speechState.VoiceName = $voiceName
    $speechState.CurrentIndex = 0
    $speechState.PlayerProcess = $null
    $speechState.PlayerStartedAt = $null
    $speechState.PauseStartedAt = $null
    $speechState.Chunks = @()
    $chunkTexts = @(Split-TextIntoSpeechChunks $text 6)
    $startWordIndex = 0

    for ($index = 0; $index -lt $chunkTexts.Count; $index++) {
        $baseName = "txt-preview-speech-$PID-$($speechState.SessionId)-$index"
        $speechState.Chunks += [pscustomobject]@{
            Index           = $index
            Text            = $chunkTexts[$index]
            TextFile        = Join-Path ([IO.Path]::GetTempPath()) "$baseName.txt"
            MediaFile       = Join-Path ([IO.Path]::GetTempPath()) "$baseName.mp3"
            TimingFile      = Join-Path ([IO.Path]::GetTempPath()) "$baseName.words.json"
            Process         = $null
            Status          = "Pending"
            ErrorText       = ""
            DurationSeconds = 0.0
            WordTimings     = @()
            WordMarks       = @()
            AlignedMarks    = 0
            StartWordIndex  = $startWordIndex
        }
        $startWordIndex += ([regex]::Matches($chunkTexts[$index], '\S+')).Count
    }

    foreach ($chunk in $speechState.Chunks) {
        Start-EdgeChunkGeneration $chunk $voiceName $speedSlider.Value
    }

    $speechState.Mode = "Generating"
    $btnPauseVoice.Text = "Pausar"
    Set-AudioControlState "Play"
    $edgeVoiceTimer.Start()
    Show-Message "Preparando $($speechState.Chunks.Count) bloques; el primero se reproducirá apenas esté listo..."
}

function Start-WindowsSpeechSession {
    param(
        [string]$text,
        [string]$voiceDisplay,
        [string]$voiceName
    )

    $speechState.Provider = "Windows"
    $speechState.VoiceDisplay = $voiceDisplay
    $speechState.VoiceName = $voiceName
    $speechState.WindowsText = $text
    $speechState.WindowsCharacterPosition = 0
    $speechState.Mode = "Playing"
    $speechState.PauseStartedAt = $null
    $btnPauseVoice.Text = "Pausar"
    Set-AudioControlState "Play"
    $edgeVoiceTimer.Start()
    $speechSynth.SelectVoice($voiceName)
    $rate = [Math]::Round((($speedSlider.Value / 100.0) - 1.0) * 10.0, [MidpointRounding]::AwayFromZero)
    $speechSynth.Rate = [int][Math]::Min(10, [Math]::Max(-10, $rate))
    $speechSynth.Volume = 100
    [void]$speechSynth.SpeakAsync($text)
    Show-Message "Reproduciendo con $voiceDisplay."
}

function Start-SelectedVoicePlayback {
    param(
        [string]$text,
        [switch]$ContinueHighlight
    )

    if (-not $ContinueHighlight) {
        $speechState.HighlightTotalLength = $text.Length
        $speechState.HighlightBaseOffset = 0
        $speechState.HighlightTotalWords = ([regex]::Matches($text, '\S+')).Count
        $speechState.HighlightBaseWordIndex = 0
        $speechState.HighlightTokenStarts = [int[]]@([regex]::Matches($text, '\S+') | ForEach-Object { $_.Index })
        Reset-SpeechAlignment
        Clear-PreviewSpeechProgress
    }

    $selectedDisplay = [string]$voiceCombo.SelectedItem
    $selectedVoiceName = $voiceNameByDisplay[$selectedDisplay]
    if ($voiceProviderByDisplay[$selectedDisplay] -eq "Edge") {
        Start-EdgeSpeechSession $text $selectedDisplay $selectedVoiceName
    } else {
        Start-WindowsSpeechSession $text $selectedDisplay $selectedVoiceName
    }
}

function Get-EdgeWordMarks {
    param(
        [string]$text,
        $wordTimings
    )

    # WordBoundary events carry each spoken word and its audio offset; locating the word
    # in the chunk text turns the audio clock into an exact character position.
    $marks = [Collections.Generic.List[object]]::new()
    $cursor = 0
    foreach ($timing in @($wordTimings)) {
        $word = [string]$timing.text
        if ([string]::IsNullOrEmpty($word)) {
            continue
        }
        $position = $text.IndexOf($word, $cursor, [StringComparison]::OrdinalIgnoreCase)
        if ($position -lt 0) {
            $position = $cursor
        } else {
            $cursor = $position + $word.Length
        }
        $marks.Add([pscustomobject]@{
            StartSeconds = [double]$timing.start_seconds
            Character    = $position
            Text         = $word
        })
    }
    return $marks.ToArray()
}

function Get-EdgeChunkElapsedSeconds {
    if ($null -eq $speechState.PlayerProcess -or $null -eq $speechState.PlayerStartedAt) {
        return $null
    }
    $positionTime = if ($null -ne $speechState.PauseStartedAt) { $speechState.PauseStartedAt } else { [DateTime]::UtcNow }
    return [Math]::Max(0.0, ($positionTime - $speechState.PlayerStartedAt).TotalSeconds)
}

function Get-EdgeMarkIndexAt {
    param(
        $chunk,
        [double]$elapsed
    )

    # Binary search for the last word whose audio onset has already been reached.
    $marks = @($chunk.WordMarks)
    $lookupTime = $elapsed + $speechHighlightLeadSeconds
    $low = 0
    $high = $marks.Count - 1
    $found = -1
    while ($low -le $high) {
        $middle = [int][Math]::Floor(($low + $high) / 2)
        if ($marks[$middle].StartSeconds -le $lookupTime) {
            $found = $middle
            $low = $middle + 1
        } else {
            $high = $middle - 1
        }
    }
    return $found
}

function Get-SpeechAlignmentKey {
    param([string]$word)

    return [regex]::Replace($word.ToLowerInvariant(), '[^\p{L}\p{N}]', '')
}

function Reset-SpeechAlignment {
    $speechState.AlignWords = [string[]]@()
    $speechState.AlignCursor = -1
    $speechState.AlignMisses = 0
    $speechState.PendingSpokenWords.Clear()
}

function Initialize-SpeechAlignment {
    if ($speechState.AlignWords.Count -gt 0) {
        return $true
    }
    if ($null -eq $preview.Document) {
        return $false
    }
    try {
        $rawWords = [string]$preview.Document.InvokeScript("getSpeechWords")
    } catch {
        return $false
    }
    if ([string]::IsNullOrEmpty($rawWords)) {
        return $false
    }
    $speechState.AlignWords = [string[]]@($rawWords -split "`n" | ForEach-Object { Get-SpeechAlignmentKey $_ })
    return $true
}

function Step-SpeechAlignment {
    param([string]$spokenWord)

    # Sequential text-to-DOM alignment: every engine word event advances a cursor over the
    # rendered preview words, so the highlight follows reading order instead of a ratio.
    $key = Get-SpeechAlignmentKey $spokenWord
    if (-not $key) {
        return
    }

    $words = $speechState.AlignWords
    $cursor = $speechState.AlignCursor
    $start = $cursor + 1
    if ($start -ge $words.Count) {
        return
    }

    # Skip preview tokens without letters or digits (emoji, dashes, bullets).
    $next = $start
    while ($next -lt $words.Count - 1 -and -not $words[$next]) {
        $next++
    }
    $nextWord = $words[$next]
    if ($nextWord -and ($nextWord -eq $key -or $nextWord.StartsWith($key) -or $key.StartsWith($nextWord))) {
        $speechState.AlignCursor = $next
        $speechState.AlignMisses = 0
        return
    }

    # Engines split compound tokens ("e-mail", "2026-10-04"); stay on the current word.
    if ($cursor -ge 0 -and $words[$cursor] -and $words[$cursor].Contains($key)) {
        return
    }

    $limit = [Math]::Min($words.Count - 1, $start + $speechAlignmentWindow)
    for ($index = $next + 1; $index -le $limit; $index++) {
        if ($words[$index] -eq $key) {
            $speechState.AlignCursor = $index
            $speechState.AlignMisses = 0
            return
        }
    }

    # Unmatched words (numbers read aloud, abbreviations) advance one step after two misses
    # so the highlight never freezes and never jumps far ahead.
    $speechState.AlignMisses++
    if ($speechState.AlignMisses -ge 2) {
        $speechState.AlignCursor = $next
        $speechState.AlignMisses = 0
    }
}

function Sync-EdgeChunkAlignment {
    param(
        $chunk,
        [int]$targetMark
    )

    $marks = @($chunk.WordMarks)
    $targetMark = [Math]::Min($targetMark, $marks.Count - 1)
    for ($index = $chunk.AlignedMarks; $index -le $targetMark; $index++) {
        Step-SpeechAlignment $marks[$index].Text
    }
    $chunk.AlignedMarks = [Math]::Max($chunk.AlignedMarks, $targetMark + 1)
}

function Sync-SpeechAlignment {
    if ($speechState.Provider -eq "Windows") {
        while ($speechState.PendingSpokenWords.Count -gt 0) {
            $spokenWord = $speechState.PendingSpokenWords[0]
            $speechState.PendingSpokenWords.RemoveAt(0)
            Step-SpeechAlignment $spokenWord
        }
        return
    }

    if ($speechState.Provider -ne "Edge" -or $speechState.CurrentIndex -ge $speechState.Chunks.Count) {
        return
    }
    $chunk = $speechState.Chunks[$speechState.CurrentIndex]
    $elapsed = Get-EdgeChunkElapsedSeconds
    if ($null -eq $elapsed -or @($chunk.WordMarks).Count -eq 0) {
        return
    }
    Sync-EdgeChunkAlignment $chunk (Get-EdgeMarkIndexAt $chunk $elapsed)
}

function Get-EdgeChunkCharacterPosition {
    param(
        $chunk,
        [double]$elapsed
    )

    $marks = @($chunk.WordMarks)
    if ($marks.Count -gt 0) {
        $found = Get-EdgeMarkIndexAt $chunk $elapsed
        if ($found -lt 0) {
            return 0
        }
        return $marks[$found].Character
    }

    if ($chunk.DurationSeconds -le 0) {
        return 0
    }
    $chunkRatio = [Math]::Min(1.0, $elapsed / $chunk.DurationSeconds)
    return [int]($chunk.Text.Length * $chunkRatio)
}

function Get-RemainingSpeechText {
    if ($speechState.Provider -eq "Windows") {
        $position = [Math]::Max(0, [Math]::Min($speechState.WindowsCharacterPosition, $speechState.WindowsText.Length))
        return $speechState.WindowsText.Substring($position).TrimStart()
    }

    if ($speechState.Provider -ne "Edge" -or $speechState.CurrentIndex -ge $speechState.Chunks.Count) {
        return ""
    }

    $remainingParts = [Collections.Generic.List[string]]::new()
    $currentChunk = $speechState.Chunks[$speechState.CurrentIndex]
    $currentText = $currentChunk.Text

    $elapsed = Get-EdgeChunkElapsedSeconds
    if ($null -ne $elapsed) {
        $characterIndex = [Math]::Min($currentText.Length, (Get-EdgeChunkCharacterPosition $currentChunk $elapsed))
        while ($characterIndex -lt $currentText.Length -and -not [char]::IsWhiteSpace($currentText[$characterIndex])) {
            $characterIndex++
        }
        $currentText = $currentText.Substring($characterIndex).TrimStart()
    }

    if ($currentText) {
        $remainingParts.Add($currentText)
    }
    for ($index = $speechState.CurrentIndex + 1; $index -lt $speechState.Chunks.Count; $index++) {
        $remainingParts.Add($speechState.Chunks[$index].Text)
    }

    return ($remainingParts -join ([Environment]::NewLine + [Environment]::NewLine))
}

function Get-CurrentSpeechCharacterOffset {
    if ($speechState.Provider -eq "Windows") {
        return $speechState.HighlightBaseOffset + $speechState.WindowsCharacterPosition
    }

    if ($speechState.Provider -ne "Edge" -or $speechState.Chunks.Count -eq 0) {
        return $speechState.HighlightBaseOffset
    }

    $sessionOffset = 0.0
    $lastCompletedIndex = [Math]::Min($speechState.CurrentIndex - 1, $speechState.Chunks.Count - 1)
    for ($index = 0; $index -le $lastCompletedIndex; $index++) {
        $sessionOffset += $speechState.Chunks[$index].Text.Length
    }

    if ($speechState.CurrentIndex -lt $speechState.Chunks.Count) {
        $currentChunk = $speechState.Chunks[$speechState.CurrentIndex]
        $elapsed = Get-EdgeChunkElapsedSeconds
        if ($null -ne $elapsed) {
            $sessionOffset += Get-EdgeChunkCharacterPosition $currentChunk $elapsed
        }
    }

    return $speechState.HighlightBaseOffset + $sessionOffset
}

function Update-SpeechHighlight {
    if ($speechState.Mode -eq "Idle" -or $speechState.HighlightTotalLength -le 0) {
        return
    }

    if (Initialize-SpeechAlignment) {
        Sync-SpeechAlignment
        if ($speechState.AlignCursor -ge 0) {
            Set-PreviewSpeechWordIndex $speechState.AlignCursor
        }
        return
    }

    $characterOffset = Get-CurrentSpeechCharacterOffset
    $tokenStarts = $speechState.HighlightTokenStarts
    if ($tokenStarts.Count -gt 0) {
        # Map in word space, not character space: long and short words otherwise skew
        # the preview by one or two words even when the character offset is exact.
        $searchIndex = [Array]::BinarySearch($tokenStarts, [int][Math]::Round($characterOffset))
        $tokenIndex = if ($searchIndex -ge 0) { $searchIndex } else { [Math]::Max(0, (-bnot $searchIndex) - 1) }
        Set-PreviewSpeechProgress (($tokenIndex + 0.5) / $tokenStarts.Count)
        return
    }
    Set-PreviewSpeechProgress ($characterOffset / $speechState.HighlightTotalLength)
}

function Restart-ActiveSpeechPlayback {
    param([string]$successMessage)

    $wasPaused = $speechState.Mode -eq "Paused"
    $resumeHighlightOffset = Get-CurrentSpeechCharacterOffset
    $highlightTotalLength = $speechState.HighlightTotalLength
    $remainingText = Get-RemainingSpeechText
    Stop-VoicePlayback -KeepHighlight
    if ([string]::IsNullOrWhiteSpace($remainingText)) {
        Show-Message "La lectura ya había finalizado." -Level Warning
        return
    }

    try {
        $speechState.HighlightTotalLength = $highlightTotalLength
        $speechState.HighlightBaseOffset = $resumeHighlightOffset
        Start-SelectedVoicePlayback $remainingText -ContinueHighlight
        if ($wasPaused) {
            Pause-VoicePlayback
            Show-Message "$successMessage La lectura permanece pausada."
        } else {
            Show-Message "$successMessage Continuando desde la posición actual."
        }
    } catch {
        Stop-VoicePlayback
        Show-Message "No se pudo actualizar la lectura: $($_.Exception.Message)" -Level Error
    }
}

function Switch-ActiveSpeechVoice {
    if ($speechState.Mode -eq "Idle" -or $voiceCombo.SelectedIndex -lt 0) {
        return
    }

    $newDisplay = [string]$voiceCombo.SelectedItem
    $newVoiceName = $voiceNameByDisplay[$newDisplay]
    if ($newVoiceName -eq $speechState.VoiceName) {
        return
    }

    Restart-ActiveSpeechPlayback "Voz cambiada a $newDisplay."
}

$script:appliedSpeechSpeed = $speedSlider.Value

function Update-SpeechSpeedLabel {
    $factor = $speedSlider.Value / 100.0
    $lblSpeedValue.Text = $factor.ToString("0.00", [Globalization.CultureInfo]::GetCultureInfo("es-AR")) + "x"
}

function Apply-SpeechSpeed {
    $newSpeed = $speedSlider.Value
    if ($newSpeed -eq $script:appliedSpeechSpeed) {
        return
    }

    $script:appliedSpeechSpeed = $newSpeed
    $speedText = $lblSpeedValue.Text
    if ($speechState.Mode -eq "Idle") {
        Show-Message "Velocidad de lectura: $speedText."
        return
    }

    Restart-ActiveSpeechPlayback "Velocidad cambiada a $speedText."
}

$speedSlider.Add_ValueChanged({ Update-SpeechSpeedLabel })
$speedSlider.Add_MouseUp({ Apply-SpeechSpeed })
$speedSlider.Add_MouseWheel({ Apply-SpeechSpeed })
$speedSlider.Add_KeyUp({ Apply-SpeechSpeed })

function Pause-VoicePlayback {
    if ($speechState.Mode -eq "Idle") {
        Show-Message "No hay una lectura activa para pausar." -Level Warning
        return
    }

    try {
        if ($speechState.Provider -eq "Windows") {
            $speechSynth.Pause()
        } elseif ($null -ne $speechState.PlayerProcess -and -not $speechState.PlayerProcess.HasExited) {
            $result = [AudioProcessControl]::NtSuspendProcess($speechState.PlayerProcess.Handle)
            if ($result -ne 0) {
                throw "Windows devolvió el código $result al pausar el audio."
            }
            $speechState.PauseStartedAt = [DateTime]::UtcNow
        }

        $speechState.Mode = "Paused"
        $btnPauseVoice.Text = "Continuar"
        Set-AudioControlState "Pause"
        Update-SpeechHighlight
        Show-Message "Lectura pausada."
    } catch {
        Show-Message "No se pudo pausar la lectura: $($_.Exception.Message)" -Level Error
    }
}

function Resume-VoicePlayback {
    if ($speechState.Mode -ne "Paused") {
        Show-Message "La lectura no está pausada." -Level Warning
        return
    }

    try {
        if ($speechState.Provider -eq "Windows") {
            $speechSynth.Resume()
            $speechState.Mode = "Playing"
        } elseif ($null -ne $speechState.PlayerProcess -and -not $speechState.PlayerProcess.HasExited) {
            $result = [AudioProcessControl]::NtResumeProcess($speechState.PlayerProcess.Handle)
            if ($result -ne 0) {
                throw "Windows devolvió el código $result al continuar el audio."
            }
            if ($null -ne $speechState.PauseStartedAt -and $null -ne $speechState.PlayerStartedAt) {
                $speechState.PlayerStartedAt = $speechState.PlayerStartedAt + ([DateTime]::UtcNow - $speechState.PauseStartedAt)
            }
            $speechState.PauseStartedAt = $null
            $speechState.Mode = "Playing"
        } else {
            $speechState.Mode = "Generating"
            Start-CurrentEdgeChunk
        }

        $btnPauseVoice.Text = "Pausar"
        Set-AudioControlState "Play"
        Show-Message "Continuando la lectura desde la posición pausada."
    } catch {
        Show-Message "No se pudo continuar la lectura: $($_.Exception.Message)" -Level Error
    }
}

$edgeVoiceTimer.Add_Tick({
    if ($speechState.Provider -eq "Edge") {
        Update-EdgeVoicePlayback
    } elseif (
        $speechState.Provider -eq "Windows" -and
        $speechState.Mode -ne "Paused" -and
        $speechSynth.State -eq [System.Speech.Synthesis.SynthesizerState]::Ready
    ) {
        $speechState.WindowsCharacterPosition = $speechState.WindowsText.Length
        Update-SpeechHighlight
        $speechState.Mode = "Idle"
        $speechState.Provider = $null
        $edgeVoiceTimer.Stop()
        $btnPauseVoice.Text = "Pausar"
        Set-AudioControlState "Idle"
        Clear-PreviewSpeechProgress
        Show-Message "Lectura con voz de Windows finalizada."
    }
    Update-SpeechHighlight
})
$voiceCombo.Add_SelectedIndexChanged({ Switch-ActiveSpeechVoice })

$speechSynth.add_SpeakProgress({
    param($sender, $eventArgs)
    if ($speechState.Provider -eq "Windows") {
        $speechState.WindowsCharacterPosition = $eventArgs.CharacterPosition
        $speechState.PendingSpokenWords.Add([string]$eventArgs.Text)
    }
})

$speechSynth.add_SpeakCompleted({
    param($sender, $eventArgs)
    if ($speechState.Provider -eq "Windows" -and -not $eventArgs.Cancelled) {
        $speechState.WindowsCharacterPosition = $speechState.WindowsText.Length
    }
})

function Start-Busy {
    param([string]$message)

    Show-Message $message
    $busyForm.Tag = $message
    $busyLabel.Text = "| $message"
    $spinnerLabel.Tag = 0
    $spinnerLabel.Text = "| Procesando..."
    $spinnerLabel.Visible = $true
    $spinnerTimer.Start()
    foreach ($button in $aiButtons) {
        $button.Enabled = $false
    }
    $modalX = $form.Left + [Math]::Max(0, [int](($form.Width - $busyForm.Width) / 2))
    $modalY = $form.Top + [Math]::Max(0, [int](($form.Height - $busyForm.Height) / 2))
    $busyForm.Location = New-Object Drawing.Point($modalX, $modalY)
    $busyForm.Show($form)
    $form.Enabled = $false
    [Windows.Forms.Application]::DoEvents()
}

function Stop-Busy {
    $spinnerTimer.Stop()
    $spinnerLabel.Visible = $false
    $busyForm.Hide()
    $form.Enabled = $true
    foreach ($button in $aiButtons) {
        $button.Enabled = $true
    }
    $form.Activate()
    [Windows.Forms.Application]::DoEvents()
}

function Wait-TaskWithEvents {
    param([System.Threading.Tasks.Task]$task)

    while (-not $task.IsCompleted) {
        [Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 25
    }

    return $task.GetAwaiter().GetResult()
}

function Select-ExportPath {
    param(
        [string]$title,
        [string]$filter,
        [string]$extension
    )

    $dialog = New-Object Windows.Forms.SaveFileDialog
    $dialog.Title = $title
    $dialog.Filter = $filter
    $dialog.DefaultExt = $extension
    $dialog.AddExtension = $true
    $dialog.OverwritePrompt = $true
    $dialog.InitialDirectory = [Environment]::GetFolderPath("MyDocuments")
    $dialog.FileName = "lectura-{0:yyyyMMdd-HHmm}.{1}" -f (Get-Date), $extension
    try {
        if ($dialog.ShowDialog($form) -eq [Windows.Forms.DialogResult]::OK) {
            return $dialog.FileName
        }
        return $null
    } finally {
        $dialog.Dispose()
    }
}

function Invoke-ProcessWithEvents {
    param(
        [string]$fileName,
        [string[]]$arguments
    )

    # Keeps the UI responsive (busy spinner) while an external tool runs.
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $fileName
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.RedirectStandardOutput = $true
    foreach ($argument in $arguments) {
        [void]$startInfo.ArgumentList.Add($argument)
    }

    $process = [Diagnostics.Process]::Start($startInfo)
    $errorTask = $process.StandardError.ReadToEndAsync()
    $outputTask = $process.StandardOutput.ReadToEndAsync()
    while (-not $process.HasExited) {
        [Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 50
    }
    $process.WaitForExit()
    $result = [pscustomobject]@{
        ExitCode = $process.ExitCode
        Error    = $errorTask.GetAwaiter().GetResult().Trim()
        Output   = $outputTask.GetAwaiter().GetResult().Trim()
    }
    $process.Dispose()
    return $result
}

function Get-EdgeBrowserPath {
    foreach ($candidate in @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
    )) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return $null
}

function Export-PreviewPdf {
    if ([string]::IsNullOrWhiteSpace($textBox.Text)) {
        Show-Message "No hay contenido para exportar a PDF." -Level Warning
        return
    }
    $edgePath = Get-EdgeBrowserPath
    if (-not $edgePath) {
        Show-Message "No se encontró Microsoft Edge para generar el PDF." -Level Error
        return
    }
    $targetPath = Select-ExportPath "Guardar Vista previa como PDF" "Documento PDF (*.pdf)|*.pdf" "pdf"
    if (-not $targetPath) {
        return
    }

    # Edge can keep its private profile locked briefly after printing, so leftovers from
    # earlier exports are removed here instead of failing the current cleanup.
    Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Directory -Filter "txt-pdf-*" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    $workDirectory = Join-Path ([IO.Path]::GetTempPath()) "txt-pdf-$PID"
    $htmlPath = Join-Path $workDirectory "preview.html"
    $profilePath = Join-Path $workDirectory "edge-profile"
    [void][IO.Directory]::CreateDirectory($workDirectory)
    [IO.File]::WriteAllText($htmlPath, (Get-MarkdownPreviewHtml $textBox.Text), [Text.UTF8Encoding]::new($false))

    Start-Busy "Generando PDF..."
    try {
        # The save dialog already confirmed the overwrite; removing the old file keeps the
        # completion check below from mistaking it for the new PDF.
        Remove-Item -LiteralPath $targetPath -Force -ErrorAction SilentlyContinue
        # Headless Edge prints with a modern engine; a private profile avoids clashing
        # with an Edge window the user already has open.
        $result = Invoke-ProcessWithEvents $edgePath @(
            "--headless",
            "--disable-gpu",
            "--no-first-run",
            "--user-data-dir=$profilePath",
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            "--print-to-pdf=$targetPath",
            ([Uri]$htmlPath).AbsoluteUri
        )

        # msedge.exe is a launcher that exits at once; a child process writes the PDF
        # later, so wait until the file exists and its size stops changing.
        $deadline = [DateTime]::UtcNow.AddSeconds(45)
        $lastSize = -1
        while ([DateTime]::UtcNow -lt $deadline) {
            [Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 250
            if (Test-Path -LiteralPath $targetPath) {
                $size = (Get-Item -LiteralPath $targetPath).Length
                if ($size -gt 0 -and $size -eq $lastSize) {
                    break
                }
                $lastSize = $size
            }
        }

        if (Test-Path -LiteralPath $targetPath) {
            Show-Message "PDF guardado en $targetPath"
        } else {
            $detail = if ($result.Error) { ($result.Error -split "`r?`n")[-1] } else { "Edge terminó con código $($result.ExitCode)." }
            Show-Message "No se pudo generar el PDF: $detail" -Level Error
        }
    } catch {
        Show-Message "No se pudo generar el PDF: $($_.Exception.Message)" -Level Error
    } finally {
        Stop-Busy
        Remove-Item -LiteralPath $workDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Export-SpeechMp3 {
    $speechText = Convert-MarkdownToText $textBox.Text
    if ([string]::IsNullOrWhiteSpace($speechText)) {
        Show-Message "No hay contenido para exportar a MP3." -Level Warning
        return
    }
    if ($voiceCombo.SelectedIndex -lt 0) {
        Show-Message "No hay una voz seleccionada para generar el MP3." -Level Warning
        return
    }

    $voiceDisplay = [string]$voiceCombo.SelectedItem
    $voiceName = $voiceNameByDisplay[$voiceDisplay]
    $isEdgeVoice = $voiceProviderByDisplay[$voiceDisplay] -eq "Edge"
    if ($isEdgeVoice -and -not $pythonCommand) {
        Show-Message "No se encontró Python para generar el MP3 con la voz Edge." -Level Error
        return
    }
    $ffmpegCommand = (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
    if (-not $isEdgeVoice -and -not $ffmpegCommand) {
        Show-Message "Las voces de Windows necesitan ffmpeg para convertir el audio a MP3." -Level Warning
        return
    }

    $targetPath = Select-ExportPath "Guardar lectura como MP3" "Audio MP3 (*.mp3)|*.mp3" "mp3"
    if (-not $targetPath) {
        return
    }

    $workDirectory = Join-Path ([IO.Path]::GetTempPath()) "txt-mp3-$PID"
    [void][IO.Directory]::CreateDirectory($workDirectory)
    Start-Busy "Generando MP3 con $voiceDisplay..."
    try {
        if ($isEdgeVoice) {
            $textPath = Join-Path $workDirectory "speech.txt"
            [IO.File]::WriteAllText($textPath, $speechText, [Text.UTF8Encoding]::new($false))
            $result = Invoke-ProcessWithEvents $pythonCommand @(
                "-m", "edge_tts", "--voice", $voiceName, "--file", $textPath, "--write-media", $targetPath
            )
        } else {
            # System.Speech only writes WAV, so the file is rendered first and then encoded.
            $wavePath = Join-Path $workDirectory "speech.wav"
            $fileSynth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
            try {
                $fileSynth.SelectVoice($voiceName)
                $fileSynth.SetOutputToWaveFile($wavePath)
                $prompt = $fileSynth.SpeakAsync($speechText)
                while (-not $prompt.IsCompleted) {
                    [Windows.Forms.Application]::DoEvents()
                    Start-Sleep -Milliseconds 50
                }
            } finally {
                $fileSynth.Dispose()
            }
            $result = Invoke-ProcessWithEvents $ffmpegCommand @(
                "-y", "-loglevel", "error", "-i", $wavePath, "-codec:a", "libmp3lame", "-q:a", "2", $targetPath
            )
        }

        if ($result.ExitCode -eq 0 -and (Test-Path -LiteralPath $targetPath)) {
            Show-Message "MP3 guardado en $targetPath"
        } else {
            $detail = if ($result.Error) { ($result.Error -split "`r?`n")[-1] } else { "El proceso terminó con código $($result.ExitCode)." }
            Show-Message "No se pudo generar el MP3: $detail" -Level Error
        }
    } catch {
        Show-Message "No se pudo generar el MP3: $($_.Exception.Message)" -Level Error
    } finally {
        Stop-Busy
        Remove-Item -LiteralPath $workDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-GroqRequest {
    param(
        [hashtable]$headers,
        [string]$body
    )

    $client = [Net.Http.HttpClient]::new()
    $request = [Net.Http.HttpRequestMessage]::new(
        [Net.Http.HttpMethod]::Post,
        "https://api.groq.com/openai/v1/chat/completions"
    )
    $httpResponse = $null

    try {
        $token = $headers["Authorization"] -replace '^Bearer\s+', ''
        $request.Headers.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $token)
        $request.Content = [Net.Http.StringContent]::new($body, [Text.Encoding]::UTF8, "application/json")

        $httpResponse = Wait-TaskWithEvents ($client.SendAsync($request))
        $responseText = Wait-TaskWithEvents ($httpResponse.Content.ReadAsStringAsync())

        if (-not $httpResponse.IsSuccessStatusCode) {
            throw "Groq devolvió el estado HTTP $([int]$httpResponse.StatusCode)."
        }

        return $responseText | ConvertFrom-Json
    } finally {
        if ($null -ne $httpResponse) {
            $httpResponse.Dispose()
        }
        $request.Dispose()
        $client.Dispose()
    }
}

function Get-GroqHeaders {
    $apiKey = $script:groqApiKey
    if ([string]::IsNullOrWhiteSpace($apiKey) -and $null -ne $txtApiKey) {
        $apiKey = $txtApiKey.Text.Trim()
    }
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        throw "Falta configurar la API key de Groq."
    }

    return @{
        "Content-Type"  = "application/json"
        "Authorization" = "Bearer $apiKey"
    }
}

function Get-ImageMediaType {
    param([string]$extension)

    switch ($extension.ToLowerInvariant()) {
        ".png" { return "image/png" }
        ".webp" { return "image/webp" }
        ".gif" { return "image/gif" }
        default { return "image/jpeg" }
    }
}

function New-GroqRequestJson {
    param([string]$prompt)

    $textParts = [Collections.Generic.List[string]]::new()
    $textParts.Add($prompt)
    foreach ($attachment in $script:attachedFiles) {
        if ($attachment.Kind -eq "Text") {
            $textParts.Add("---`nArchivo adjunto: $($attachment.Name)`n---`n$($attachment.Content)")
        }
    }
    $combinedText = $textParts -join "`n`n"

    $images = @($script:attachedFiles | Where-Object { $_.Kind -eq "Image" })
    if ($images.Count -gt 0) {
        $content = [Collections.Generic.List[object]]::new()
        $content.Add([ordered]@{ type = "text"; text = $combinedText })
        foreach ($imageAttachment in $images) {
            $base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($imageAttachment.Path))
            $mediaType = Get-ImageMediaType ([IO.Path]::GetExtension($imageAttachment.Path))
            $content.Add([ordered]@{
                type      = "image_url"
                image_url = [ordered]@{ url = "data:$mediaType;base64,$base64" }
            })
        }
        $messageContent = $content.ToArray()
    } else {
        $messageContent = $combinedText
    }

    $body = [ordered]@{
        model    = $script:selectedGroqModel
        messages = @([ordered]@{ role = "user"; content = $messageContent })
    }
    $capabilities = Get-SelectedModelCapabilities
    if ($checkWebSearch.Checked -and $capabilities.Web) {
        $body.tools = @([ordered]@{ type = "browser_search" })
        $body.tool_choice = "auto"
    }
    return $body | ConvertTo-Json -Depth 10
}

function Set-Theme {
    param($enabled)

    $script:activePalette = if ($enabled) { $themePalettes.Dark } else { $themePalettes.Light }
    $btnTheme.Text = if ($enabled) { "Tema: Oscuro" } else { "Tema: Claro" }

    $form.BackColor = Get-ThemeColor "Window"
    $panel.BackColor = Get-ThemeColor "Surface"
    $statusPanel.BackColor = Get-ThemeColor "Surface"
    $navHost.BackColor = Get-ThemeColor "Elevated"
    $settingsNavHost.BackColor = Get-ThemeColor "Elevated"
    $msgHost.BackColor = Get-ThemeColor "Surface"
    $tabs.BackColor = Get-ThemeColor "Window"
    $tabEditor.BackColor = Get-ThemeColor "Editor"
    $tabPreview.BackColor = Get-ThemeColor "Window"
    $tabSettings.BackColor = Get-ThemeColor "Window"
    $textBox.BackColor = Get-ThemeColor "Editor"
    $textBox.ForeColor = Get-ThemeColor "Text"
    $msgBox.BackColor = Get-ThemeColor "Surface"
    $spinnerLabel.BackColor = Get-ThemeColor "Surface"
    $spinnerLabel.ForeColor = Get-ThemeColor "Accent"
    $lblVoice.BackColor = Get-ThemeColor "Surface"
    $lblVoice.ForeColor = Get-ThemeColor "Muted"
    $lblVoice.Font = New-Object Drawing.Font($uiStrongFontName, 9)
    foreach ($label in @($lblSpeed, $lblSpeedValue)) {
        $label.BackColor = Get-ThemeColor "Surface"
        $label.ForeColor = Get-ThemeColor "Muted"
        $label.Font = New-Object Drawing.Font($uiStrongFontName, 9)
    }
    $speedSlider.BackColor = Get-ThemeColor "Surface"
    $speedSlider.ForeColor = Get-ThemeColor "Accent"
    $versionLabel.BackColor = Get-ThemeColor "Surface"
    foreach ($label in @($settingsTitle, $settingsHint, $lblApiKey, $settingsStatus, $lblAppVersion, $lblUpdateStatus)) {
        $label.BackColor = Get-ThemeColor "Window"
    }
    $settingsTitle.ForeColor = Get-ThemeColor "Heading"
    $lblApiKey.ForeColor = Get-ThemeColor "Muted"
    foreach ($inputControl in @($txtApiKey, $modelCombo)) {
        $inputControl.BackColor = Get-ThemeColor "Elevated"
        $inputControl.ForeColor = Get-ThemeColor "Text"
        $inputControl.Font = New-Object Drawing.Font($uiFontName, 10)
    }
    $contextPanel.BackColor = Get-ThemeColor "Elevated"
    $lblContextTitle.BackColor = Get-ThemeColor "Elevated"
    $lblContextTitle.ForeColor = Get-ThemeColor "Accent"
    $lblContextTitle.Font = New-Object Drawing.Font($uiStrongFontName, 9)
    $lblAttachments.BackColor = Get-ThemeColor "Elevated"
    $infoControls = @($msgBox, $settingsHint, $settingsStatus, $lblAppVersion, $lblUpdateStatus, $lblAttachments, $versionLabel)
    foreach ($control in $infoControls) {
        Set-InfoStyle $control
    }
    Update-CapabilityBadges
    $checkWebSearch.BackColor = Get-ThemeColor "Elevated"
    $checkWebSearch.ForeColor = Get-ThemeColor "Text"
    $lblHeaderModel.BackColor = Get-ThemeColor "Elevated"
    $lblHeaderModel.ForeColor = Get-ThemeColor "Muted"
    $lblHeaderModel.Font = New-Object Drawing.Font($uiStrongFontName, 9)
    $modelsList.BackColor = Get-ThemeColor "Editor"
    $modelsList.ForeColor = Get-ThemeColor "Text"
    $modelsList.Font = New-Object Drawing.Font($uiFontName, 9.5)
    $voiceCombo.BackColor = Get-ThemeColor "Elevated"
    $voiceCombo.ForeColor = Get-ThemeColor "Text"
    $voiceCombo.Font = New-Object Drawing.Font($uiFontName, 9.75)
    $busyForm.BackColor = Get-ThemeColor "Surface"
    $busyLabel.BackColor = Get-ThemeColor "Surface"
    $busyLabel.ForeColor = Get-ThemeColor "Text"

    $buttonFont = New-Object Drawing.Font($uiStrongFontName, 9)
    foreach ($button in @($actionButtons + $btnNavEditor + $btnNavPreview + $btnNavSettings)) {
        $button.FlatStyle = [Windows.Forms.FlatStyle]::Flat
        $button.FlatAppearance.BorderSize = 1
        $button.Font = $buttonFont
        $button.Cursor = [Windows.Forms.Cursors]::Hand
        Set-ButtonTone $button "Elevated" "Text" "Hover" "Border"
    }
    # The primary action gets the accent fill; everything else stays tonal.
    Set-ButtonTone $btnPreguntar "Accent" "OnAccent" "AccentHover" "Accent"

    Set-WindowChrome $form ([bool]$enabled)
    Set-WindowChrome $busyForm ([bool]$enabled)
    foreach ($toggle in $voiceToggles) {
        $toggle.Parent.BackColor = Get-ThemeColor "Surface"
    }
    Set-ToggleTones
    $editorScrollBar.BackColor = Get-ThemeColor "Editor"
    $editorScrollBar.TrackColor = Get-ThemeColor "Editor"
    $editorScrollBar.ThumbColor = Get-ThemeColor "Scrollbar"
    $editorScrollBar.ThumbActiveColor = Get-ThemeColor "ScrollbarArrow"
    $editorScrollBar.Invalidate()
    Update-NavigationState
    Set-AudioControlState $speechState.ControlState
}

function Get-MarkdownPreviewHtml {
    param([string]$markdown)

    if ([string]::IsNullOrWhiteSpace($markdown)) {
        $bodyHtml = "<p><em>No hay contenido para mostrar.</em></p>"
    } elseif (Get-Command ConvertFrom-Markdown -ErrorAction SilentlyContinue) {
        $bodyHtml = (ConvertFrom-Markdown -InputObject $markdown).Html
    } else {
        $bodyHtml = "<pre>" + [Net.WebUtility]::HtmlEncode($markdown) + "</pre>"
    }

    # El motor WebBrowser no representa bien las secuencias emoji de teclas (1️⃣, 2️⃣, etc.).
    $keycapPattern = '([0-9#*])(?:&#xFE0F;|️)?(?:&#x20E3;|⃣)'
    $bodyHtml = [regex]::Replace(
        $bodyHtml,
        $keycapPattern,
        '<span class="emoji-keycap">$1</span>'
    )

    $background = $activePalette.Window
    $foreground = $activePalette.Text
    $muted = $activePalette.Muted
    $codeBackground = $activePalette.Code
    $border = $activePalette.Border
    $heading = $activePalette.Heading
    $accent = $activePalette.Accent
    $link = $activePalette.Link
    $scrollbar = $activePalette.Scrollbar
    $scrollbarArrow = $activePalette.ScrollbarArrow
    $speechActiveBackground = $activePalette.SpeechBackground
    $speechActiveForeground = $activePalette.SpeechForeground

    return @"
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<style>
html { background: $background; overflow-y: auto; scrollbar-face-color: $scrollbar; scrollbar-track-color: $background; scrollbar-arrow-color: $scrollbarArrow; scrollbar-shadow-color: $scrollbar; scrollbar-highlight-color: $scrollbar; scrollbar-3dlight-color: $background; scrollbar-darkshadow-color: $background; }
body { background: $background; color: $foreground; font-family: "Segoe UI Variable Text", "Segoe UI", "Segoe UI Emoji", "Segoe UI Symbol", Arial, sans-serif; font-size: 17px; line-height: 1.75; margin: 0; padding: 40px 32px 160px; }
body > * { margin-left: auto; margin-right: auto; max-width: 1280px; }
h1, h2, h3, h4 { color: $heading; font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif; font-weight: 600; letter-spacing: -.01em; line-height: 1.3; margin-top: 1.7em; margin-bottom: .55em; }
h1 { font-size: 2em; }
h2 { border-bottom: 1px solid $border; font-size: 1.45em; padding-bottom: .35em; }
h3 { font-size: 1.2em; }
p { margin-top: 0; margin-bottom: 1em; }
ul, ol { padding-left: 1.4em; }
li { margin: .3em 0; }
strong { color: $heading; font-weight: 600; }
code { background: $codeBackground; border: 1px solid $border; border-radius: 6px; font-family: "Cascadia Code", Consolas, "Segoe UI Emoji", monospace; font-size: .88em; padding: .12em .4em; }
pre { background: $codeBackground; border: 1px solid $border; border-radius: 12px; overflow-x: auto; padding: 16px 18px; white-space: pre-wrap; }
pre code { background: transparent; border: 0; padding: 0; }
table { border: 1px solid $border; border-collapse: separate; border-radius: 10px; border-spacing: 0; overflow: hidden; width: 100%; }
th { background: $codeBackground; font-weight: 600; }
th, td { border-bottom: 1px solid $border; padding: 10px 14px; text-align: left; }
blockquote { background: $codeBackground; border-left: 3px solid $accent; border-radius: 0 10px 10px 0; color: $muted; margin-top: 1.2em; margin-bottom: 1.2em; padding: .7em 1.1em; }
hr { border: 0; border-top: 1px solid $border; margin-top: 2.2em; margin-bottom: 2.2em; }
a { border-bottom: 1px solid $border; color: $link; text-decoration: none; }
.emoji-keycap { background: $accent; border-radius: 6px; color: $background; display: inline-block; font-family: "Segoe UI", Arial, sans-serif; font-size: .78em; font-weight: 700; line-height: 1.35; margin-right: .28em; min-width: 1.35em; padding: .05em .16em; text-align: center; vertical-align: .12em; }
.speech-word { border-radius: 5px; transition: background-color .14s ease-out, color .14s ease-out, box-shadow .14s ease-out; }
.speech-active { background: $speechActiveBackground; box-shadow: 0 0 0 3px $speechActiveBackground; color: $speechActiveForeground; }
@page { margin: 0; }
@media print {
    html, body { -webkit-print-color-adjust: exact; print-color-adjust: exact; background: $background; }
    html { min-height: 100%; }
    body { padding: 18mm 16mm; }
    pre, blockquote, table, h1, h2, h3 { break-inside: avoid; }
}
</style>
<script>
var speechWords = [];
var activeSpeechWord = null;

function collectSpeechTextNodes(node, output) {
    var children = [];
    var child;
    for (child = node.firstChild; child; child = child.nextSibling) {
        children.push(child);
    }
    for (var index = 0; index < children.length; index++) {
        child = children[index];
        if (child.nodeType === 3 && /\S/.test(child.nodeValue)) {
            output.push(child);
        } else if (child.nodeType === 1 && child.tagName !== "SCRIPT" && child.tagName !== "STYLE") {
            collectSpeechTextNodes(child, output);
        }
    }
}

function prepareSpeechTracking() {
    speechWords = [];
    activeSpeechWord = null;
    var textNodes = [];
    collectSpeechTextNodes(document.body, textNodes);
    for (var nodeIndex = 0; nodeIndex < textNodes.length; nodeIndex++) {
        var textNode = textNodes[nodeIndex];
        var parts = textNode.nodeValue.split(/(\s+)/);
        var fragment = document.createDocumentFragment();
        for (var partIndex = 0; partIndex < parts.length; partIndex++) {
            var part = parts[partIndex];
            if (!part) { continue; }
            if (/^\s+$/.test(part)) {
                fragment.appendChild(document.createTextNode(part));
            } else {
                var span = document.createElement("span");
                span.className = "speech-word";
                span.appendChild(document.createTextNode(part));
                fragment.appendChild(span);
                speechWords.push(span);
            }
        }
        textNode.parentNode.replaceChild(fragment, textNode);
    }
}

function getSpeechWords() {
    if (!speechWords.length) { prepareSpeechTracking(); }
    var words = [];
    for (var index = 0; index < speechWords.length; index++) {
        words.push(speechWords[index].firstChild ? speechWords[index].firstChild.nodeValue : "");
    }
    return words.join("\n");
}

function keepSpeechWordInView(element) {
    var rect = element.getBoundingClientRect();
    var viewHeight = document.documentElement.clientHeight;
    if (rect.top < viewHeight * 0.2 || rect.bottom > viewHeight * 0.7) {
        var currentTop = window.pageYOffset || document.documentElement.scrollTop;
        window.scrollTo(0, Math.max(0, currentTop + rect.top - viewHeight * 0.38));
    }
}

function setSpeechProgress(ratio) {
    if (!speechWords.length) { prepareSpeechTracking(); }
    if (!speechWords.length) { return; }
    var bounded = Math.max(0, Math.min(1, Number(ratio)));
    var wordIndex = Math.min(speechWords.length - 1, Math.floor(bounded * speechWords.length));
    setSpeechWordIndex(wordIndex);
}

function setSpeechWordIndex(wordIndex) {
    if (!speechWords.length) { prepareSpeechTracking(); }
    if (!speechWords.length) { return; }
    wordIndex = Math.max(0, Math.min(speechWords.length - 1, Number(wordIndex)));
    if (activeSpeechWord === speechWords[wordIndex]) { return; }
    if (activeSpeechWord) { activeSpeechWord.className = "speech-word"; }
    activeSpeechWord = speechWords[wordIndex];
    activeSpeechWord.className = "speech-word speech-active";
    keepSpeechWordInView(activeSpeechWord);
}

function clearSpeechProgress() {
    if (activeSpeechWord) { activeSpeechWord.className = "speech-word"; }
    activeSpeechWord = null;
}

window.onload = prepareSpeechTracking;
</script>
</head>
<body>$bodyHtml</body>
</html>
"@
}

function Show-MarkdownPreview {
    param([string]$markdown)

    $preview.DocumentText = Get-MarkdownPreviewHtml $markdown
}

function Open-MarkdownPreview {
    param([string]$markdown)

    $tabs.SelectedTab = $tabPreview
    $tabPreview.Select()
    [Windows.Forms.Application]::DoEvents()
    Show-MarkdownPreview $markdown
    [Windows.Forms.Application]::DoEvents()
}

function Convert-MarkdownToText {
    param([string]$markdown)

    if ([string]::IsNullOrWhiteSpace($markdown)) {
        return ""
    }

    if (Get-Command ConvertFrom-Markdown -ErrorAction SilentlyContinue) {
        $html = (ConvertFrom-Markdown -InputObject $markdown).Html
        $html = [regex]::Replace($html, '(?i)<br\s*/?>', [Environment]::NewLine)
        $html = [regex]::Replace($html, '(?i)</(p|h[1-6]|li|pre|tr|blockquote)>', [Environment]::NewLine)
        $plainText = [regex]::Replace($html, '<[^>]+>', '')
        return [Net.WebUtility]::HtmlDecode($plainText).Trim()
    }

    return $markdown
}

function Invoke-Translation {
    param(
        [string]$sourceLanguage,
        [string]$targetLanguage
    )

    $Texto = $textBox.Text
    if (-not (Test-GroqInputAvailable)) {
        Show-Message "Ingresá texto en el Editor o adjuntá al menos un archivo." -Level Warning
        return
    }

    $headers = Get-GroqHeaders

    $prompt = @"
Traducí el siguiente texto del $sourceLanguage al $targetLanguage.
Conservá el significado, el tono, el formato y los saltos de línea.
Devolvé solamente la traducción, sin explicaciones, etiquetas ni comentarios.

Texto original:
$Texto
"@

    $body = New-GroqRequestJson $prompt

    Start-Busy "Traduciendo con IA..."
    try {
        $response = Invoke-GroqRequest -Headers $headers -Body $body
        $traducido = [System.Text.Encoding]::UTF8.GetString([System.Text.Encoding]::Default.GetBytes($response.choices[0].message.content))
        $textBox.Text = $traducido
        if ($targetLanguage -eq "inglés") {
            Select-VoiceLanguage "en"
        } else {
            Select-VoiceLanguage "es"
        }
        Open-MarkdownPreview $traducido
        Show-Message "Traducción lista en Vista previa."
    } catch {
        Show-Message "Error al conectar con la API." -Level Error
    } finally {
        Stop-Busy
    }
}

# Each toolbar row keeps its designed spacing and is centered as a group in the panel.
$toolbarRowHeight = 42
$toolbarBaseLeft = @{}
foreach ($control in $panel.Controls) {
    if ($control -eq $versionLabel) {
        continue
    }
    $toolbarBaseLeft[$control] = $control.Left
}

function Update-ToolbarLayout {
    # Close the gap left by the contextual attachment button when it is hidden.
    $attachmentOffset = if ($btnAttachFiles.Visible) { 163 } else { 0 }
    $toolbarBaseLeft[$btnCopyMd] = 252 + $attachmentOffset
    $toolbarBaseLeft[$btnCopyTxt] = 420 + $attachmentOffset
    $toolbarBaseLeft[$btnMic] = 593 + $attachmentOffset
    $toolbarBaseLeft[$btnPdf] = 721 + $attachmentOffset
    $toolbarBaseLeft[$btnMp3] = 799 + $attachmentOffset
    $toolbarBaseLeft[$btnLimpiar] = 877 + $attachmentOffset

    $rows = @{}
    foreach ($control in $panel.Controls) {
        if ($control -eq $versionLabel -or -not $control.Visible) {
            continue
        }
        $rowIndex = [int][Math]::Floor($control.Top / $toolbarRowHeight)
        if (-not $rows.ContainsKey($rowIndex)) {
            $rows[$rowIndex] = [Collections.Generic.List[object]]::new()
        }
        $rows[$rowIndex].Add($control)
    }

    foreach ($rowControls in $rows.Values) {
        $rowLeft = ($rowControls | ForEach-Object { $toolbarBaseLeft[$_] } | Measure-Object -Minimum).Minimum
        $rowRight = ($rowControls | ForEach-Object { $toolbarBaseLeft[$_] + $_.Width } | Measure-Object -Maximum).Maximum
        $offset = [Math]::Max(0, [int](($panel.ClientSize.Width - ($rowRight - $rowLeft)) / 2)) - $rowLeft
        foreach ($control in $rowControls) {
            $control.Left = $toolbarBaseLeft[$control] + $offset
        }
    }
}

$panel.Add_Resize({ Update-ToolbarLayout })
Update-ToolbarLayout

$modelCombo.Add_SelectedIndexChanged({ Update-ModelCapabilityControls })

$modelsList.Add_DoubleClick({
    if ($modelsList.SelectedItems.Count -eq 0) {
        return
    }
    $modelId = [string]$modelsList.SelectedItems[0].Tag
    $capabilities = Get-GroqModelCapabilities $modelId
    if (-not $capabilities.Chat) {
        Set-StatusText $settingsStatus "$modelId no es un modelo de chat para las acciones del editor." -Level Warning
        return
    }
    $index = $modelCombo.FindStringExact($modelId)
    if ($index -ge 0) {
        $modelCombo.SelectedIndex = $index
    }
})

$btnSaveSettings.Add_Click({
    try {
        Save-AppSettings
        Set-StatusText $settingsStatus "Configuración guardada de forma segura para este usuario de Windows."
    } catch {
        Set-StatusText $settingsStatus "No se pudo guardar: $($_.Exception.Message)" -Level Error
    }
})

$btnRefreshModels.Add_Click({
    $btnRefreshModels.Enabled = $false
    Set-StatusText $settingsStatus "Consultando modelos activos de Groq..."
    [Windows.Forms.Application]::DoEvents()
    try {
        $models = Get-GroqModelsFromApi
        $script:groqApiKey = $txtApiKey.Text.Trim()
        Show-GroqModels $models
        Save-AppSettings
        Set-StatusText $settingsStatus "$($models.Count) modelos activos cargados desde Groq."
    } catch {
        Set-StatusText $settingsStatus "No se pudieron actualizar los modelos: $($_.Exception.Message)"
    } finally {
        $btnRefreshModels.Enabled = $true
    }
})

$btnCheckUpdate.Add_Click({
    Update-AppUpdateControls
})

$btnInstallUpdate.Add_Click({
    $confirmation = [Windows.Forms.MessageBox]::Show(
        "Se actualizará TXT Preview a $script:availableUpdateVersion desde origin/main. La aplicación deberá reiniciarse.",
        "Actualizar TXT Preview",
        [Windows.Forms.MessageBoxButtons]::YesNo,
        [Windows.Forms.MessageBoxIcon]::Question
    )
    if ($confirmation -ne [Windows.Forms.DialogResult]::Yes) {
        return
    }

    $btnCheckUpdate.Enabled = $false
    $btnInstallUpdate.Enabled = $false
    Set-StatusText $lblUpdateStatus "Aplicando la actualización..."
    [Windows.Forms.Application]::DoEvents()
    try {
        $installedVersion = Install-AppUpdate
        $script:appVersion = $installedVersion
        $versionLabel.Text = $installedVersion
        $lblAppVersion.Text = "Aplicación $installedVersion"
        $script:availableUpdateVersion = $null
        $btnInstallUpdate.Visible = $false
        Set-StatusText $lblUpdateStatus "Actualización instalada. Cerrá y abrí la aplicación."
        [void][Windows.Forms.MessageBox]::Show(
            "TXT Preview se actualizó a $installedVersion. Cerrá y volvé a abrir la aplicación para usar el código nuevo.",
            "Actualización completada",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        )
    } catch {
        Set-StatusText $lblUpdateStatus "No se pudo actualizar: $($_.Exception.Message)" -Level Error
    } finally {
        $btnCheckUpdate.Enabled = $true
        $btnInstallUpdate.Enabled = $true
    }
})

$btnAttachFiles.Add_Click({
    $capabilities = Get-SelectedModelCapabilities
    $dialog = New-Object Windows.Forms.OpenFileDialog
    $dialog.Multiselect = $true
    $dialog.Title = "Adjuntar archivos para $($script:selectedGroqModel)"
    $dialog.Filter = if ($capabilities.Vision) {
        "Documentos e imágenes|*.txt;*.md;*.json;*.csv;*.xml;*.html;*.htm;*.ps1;*.py;*.js;*.ts;*.yaml;*.yml;*.png;*.jpg;*.jpeg;*.webp;*.gif|Todos los archivos|*.*"
    } else {
        "Documentos de texto|*.txt;*.md;*.json;*.csv;*.xml;*.html;*.htm;*.ps1;*.py;*.js;*.ts;*.yaml;*.yml|Todos los archivos|*.*"
    }

    try {
        if ($dialog.ShowDialog($form) -ne [Windows.Forms.DialogResult]::OK) {
            return
        }
        $imageExtensions = @(".png", ".jpg", ".jpeg", ".webp", ".gif")
        $textExtensions = @(".txt", ".md", ".json", ".csv", ".xml", ".html", ".htm", ".ps1", ".py", ".js", ".ts", ".yaml", ".yml")
        foreach ($path in $dialog.FileNames) {
            if (@($script:attachedFiles | Where-Object { $_.Path -eq $path }).Count -gt 0) {
                continue
            }
            $extension = [IO.Path]::GetExtension($path).ToLowerInvariant()
            $fileInfo = Get-Item -LiteralPath $path
            if ($extension -in $imageExtensions) {
                if (-not $capabilities.Vision) {
                    throw "El modelo elegido no admite imágenes."
                }
                $currentImages = @($script:attachedFiles | Where-Object { $_.Kind -eq "Image" })
                if ($currentImages.Count -ge 3) {
                    throw "Qwen admite como máximo tres imágenes por solicitud."
                }
                $imageBytes = ($currentImages | Measure-Object -Property Size -Sum).Sum + $fileInfo.Length
                if ($imageBytes -gt 14MB) {
                    throw "Las imágenes superan el límite seguro de 14 MB para una solicitud codificada."
                }
                $script:attachedFiles.Add([pscustomobject]@{
                    Name = $fileInfo.Name; Path = $fileInfo.FullName; Kind = "Image"; Size = $fileInfo.Length; Content = $null
                })
            } elseif ($extension -in $textExtensions) {
                if (-not $capabilities.TextFiles) {
                    throw "El modelo elegido no admite documentos de texto en esta aplicación."
                }
                if ($fileInfo.Length -gt 2MB) {
                    throw "$($fileInfo.Name) supera el límite de 2 MB para documentos de texto."
                }
                $script:attachedFiles.Add([pscustomobject]@{
                    Name = $fileInfo.Name; Path = $fileInfo.FullName; Kind = "Text"; Size = $fileInfo.Length
                    Content = [IO.File]::ReadAllText($fileInfo.FullName)
                })
            } else {
                throw "Tipo de archivo no compatible: $extension"
            }
        }
        Update-AttachmentSummary
        $tabs.SelectedTab = $tabEditor
        $tabEditor.Select()
        Show-Message "Los adjuntos visibles sobre el editor se enviarán en la próxima acción de IA."
    } catch {
        Set-StatusText $settingsStatus "No se pudo adjuntar: $($_.Exception.Message)" -Level Error
        Show-Message "No se pudo adjuntar: $($_.Exception.Message)" -Level Error
    } finally {
        $dialog.Dispose()
    }
})

$btnClearAttachments.Add_Click({
    $script:attachedFiles.Clear()
    Update-AttachmentSummary
    $tabs.SelectedTab = $tabEditor
    Show-Message "Se quitaron los archivos adjuntos del contexto."
})

Load-AppSettings
Set-Theme ([bool]$btnTheme.Tag)
$btnTheme.Add_Click({
    $btnTheme.Tag = -not [bool]$btnTheme.Tag
    Set-Theme ([bool]$btnTheme.Tag)
    if ($tabs.SelectedTab -eq $tabPreview) {
        Show-MarkdownPreview $textBox.Text
    }
})

$btnNavEditor.Add_Click({ $tabs.SelectedTab = $tabEditor })
$btnNavPreview.Add_Click({ $tabs.SelectedTab = $tabPreview })
$btnNavSettings.Add_Click({
    $tabs.SelectedTab = $tabSettings
    if (-not $script:updateCheckCompleted) {
        Update-AppUpdateControls
    }
})

$tabs.Add_SelectedIndexChanged({
    Update-NavigationState
    if ($tabs.SelectedTab -eq $tabPreview) {
        Show-MarkdownPreview $textBox.Text
    }
})

$btnCorregir.Add_Click({
    $Texto = $textBox.Text
    if (-not (Test-GroqInputAvailable)) {
        Show-Message "Ingresá texto en el Editor o adjuntá al menos un archivo." -Level Warning
        return
    }

    $headers = Get-GroqHeaders

    $prompt = @"
Actúa como un corrector experto en redacción en español.
Tu tarea es revisar y mejorar el texto que te voy a dar,
asegurándote de que la gramática, la ortografía y la sintaxis sean impecables.

Corrige únicamente la ortografía, la gramática y la puntuación del siguiente texto en español.
No agregues contenido, no inventes contexto, no cambies el significado ni el tono.
Mantén la estructura original tanto como sea posible.
No reescribas con estilo narrativo, emocional ni conversacional.
No añadas frases nuevas, ni introducciones, ni cierres.
Dame solo el texto corregido, sin explicaciones ni comentarios.

Texto original:
$Texto
"@

    $body = New-GroqRequestJson $prompt

    Start-Busy "Corrigiendo gramática y ortografía..."
    try {
        $response = Invoke-GroqRequest -Headers $headers -Body $body
        $corregido = [System.Text.Encoding]::UTF8.GetString([System.Text.Encoding]::Default.GetBytes($response.choices[0].message.content))
        $textBox.Text = $corregido
        $corregido | Set-Clipboard
        Open-MarkdownPreview $corregido
        Show-Message "Se copió al portapapeles. Usá Ctrl+V para pegarlo en cualquier lugar."
    } catch {
        Show-Message "Error al conectar con la API." -Level Error
    } finally {
        Stop-Busy
    }
})

$btnTraducirEs.Add_Click({ Invoke-Translation "inglés" "español" })
$btnTraducirEn.Add_Click({ Invoke-Translation "español" "inglés" })

$btnPegar.Add_Click({
    try {
        $contenido = Get-Clipboard -Raw
        if ([string]::IsNullOrWhiteSpace($contenido)) {
            Show-Message "El portapapeles no contiene texto." -Level Warning
            return
        }

        $textBox.Text = $contenido
        $tabs.SelectedTab = $tabEditor
        $textBox.Focus()
        $textBox.SelectionStart = $textBox.Text.Length
        $textBox.SelectionLength = 0
        Show-Message "Texto pegado desde el portapapeles."
    } catch {
        Show-Message "No se pudo leer el portapapeles." -Level Error
    }
})

$btnCopyMd.Add_Click({
    if ([string]::IsNullOrWhiteSpace($textBox.Text)) {
        Show-Message "No hay contenido para copiar." -Level Warning
        return
    }

    $textBox.Text | Set-Clipboard
    Show-Message "Markdown copiado al portapapeles."
})

$btnCopyTxt.Add_Click({
    if ([string]::IsNullOrWhiteSpace($textBox.Text)) {
        Show-Message "No hay contenido para copiar." -Level Warning
        return
    }

    Convert-MarkdownToText $textBox.Text | Set-Clipboard
    Show-Message "Texto sin formato copiado al portapapeles."
})

$btnLeer.Add_Click({
    $textoParaLeer = Convert-MarkdownToText $textBox.Text
    if ([string]::IsNullOrWhiteSpace($textoParaLeer)) {
        Show-Message "No hay contenido en Vista previa para leer." -Level Warning
        return
    }

    if ($voiceCombo.SelectedIndex -lt 0) {
        Show-Message "No hay una voz disponible para leer el contenido." -Level Warning
        return
    }

    try {
        Open-MarkdownPreview $textBox.Text
        Stop-VoicePlayback
        Start-SelectedVoicePlayback $textoParaLeer
    } catch {
        Stop-VoicePlayback
        Show-Message "No se pudo iniciar la lectura en voz alta: $($_.Exception.Message)" -Level Error
    }
})

$btnStopVoice.Add_Click({
    Focus-SpeechPreview
    Stop-VoicePlayback -ControlState "Stop"
    Show-Message "Lectura detenida."
})

$btnPauseVoice.Add_Click({
    Focus-SpeechPreview
    if ($speechState.Mode -eq "Paused") {
        Resume-VoicePlayback
    } else {
        Pause-VoicePlayback
    }
})

$btnPreguntar.Add_Click({
    $Texto = $textBox.Text
    if (-not (Test-GroqInputAvailable)) {
        Show-Message "Ingresá una consulta en el Editor o adjuntá al menos un archivo." -Level Warning
        return
    }

    $headers = Get-GroqHeaders

    $prompt = @"
Respondé de manera clara, precisa y útil la siguiente consulta.
Devolvé solamente la respuesta, sin introducciones innecesarias.

Consulta:
$Texto
"@

    $body = New-GroqRequestJson $prompt

    Start-Busy "Consultando a la IA..."
    try {
        $response = Invoke-GroqRequest -Headers $headers -Body $body
        $respuesta = [System.Text.Encoding]::UTF8.GetString([System.Text.Encoding]::Default.GetBytes($response.choices[0].message.content))
        $textBox.Text = $respuesta
        Open-MarkdownPreview $respuesta
        Show-Message "Respuesta lista. Elegí copiar como MD o TXT."
    } catch {
        Show-Message "Error al conectar con la API." -Level Error
    } finally {
        Stop-Busy
    }
})

$btnResumir.Add_Click({
    $Texto = $textBox.Text
    if (-not (Test-GroqInputAvailable)) {
        Show-Message "Ingresá contenido en el Editor o adjuntá al menos un archivo." -Level Warning
        return
    }

    $headers = Get-GroqHeaders

    $prompt = @"
Actuá como analista profesional, clasificador y ejemplificador experto.
Creá un resumen de nivel profesional del contenido proporcionado.

Requisitos:
- Identificá el tema, el tipo de información y su objetivo principal.
- Organizá las ideas en categorías claras y jerárquicas.
- Destacá conceptos, datos y conclusiones esenciales.
- Agregá ejemplos concretos cuando ayuden a comprender el contenido.
- Conservá los detalles técnicos importantes y no inventes información.
- Adaptá la extensión del resumen a la complejidad del material.
- Entregá el resultado en Markdown claro y bien estructurado.

Contenido:
$Texto
"@

    $body = New-GroqRequestJson $prompt

    Start-Busy "Creando resumen profesional..."
    try {
        $response = Invoke-GroqRequest -Headers $headers -Body $body
        $resumen = [System.Text.Encoding]::UTF8.GetString([System.Text.Encoding]::Default.GetBytes($response.choices[0].message.content))
        $textBox.Text = $resumen
        Open-MarkdownPreview $resumen
        Show-Message "Resumen profesional listo en Vista previa."
    } catch {
        Show-Message "Error al conectar con la API." -Level Error
    } finally {
        Stop-Busy
    }
})

$btnLimpiar.Add_Click({
    $textBox.Clear()
    $script:attachedFiles.Clear()
    Update-AttachmentSummary
    $tabs.SelectedTab = $tabEditor
    Show-Message "Editor y adjuntos limpiados."
})

$btnCerrar.Add_Click({
    $form.Close()
})

$btnPdf.Add_Click({ Export-PreviewPdf })
$btnMp3.Add_Click({ Export-SpeechMp3 })

$btnMic.Add_Click({
    [Keyboard]::keybd_event([Keyboard]::VK_LWIN, 0, [Keyboard]::KEYEVENTF_KEYDOWN, 0)
    [Keyboard]::keybd_event([Keyboard]::VK_H, 0, [Keyboard]::KEYEVENTF_KEYDOWN, 0)
    Start-Sleep -Milliseconds 100
    [Keyboard]::keybd_event([Keyboard]::VK_H, 0, [Keyboard]::KEYEVENTF_KEYUP, 0)
    [Keyboard]::keybd_event([Keyboard]::VK_LWIN, 0, [Keyboard]::KEYEVENTF_KEYUP, 0)

    $btnMic.Text = [System.Text.Encoding]::UTF8.GetString([System.Text.Encoding]::Default.GetBytes("Mic <Esc>"))
    $textBox.Focus()
    $textBox.SelectionStart = $textBox.Text.Length
    $textBox.SelectionLength = 0
    Show-Message "Dictado activado. Presioná Esc para detenerlo."
})

$form.Add_FormClosed({
    $spinnerTimer.Stop()
    Stop-VoicePlayback
    $speechSynth.Dispose()
    if (-not $busyForm.IsDisposed) {
        $busyForm.Dispose()
    }
})

$form.Add_Shown({
    $form.WindowState = [Windows.Forms.FormWindowState]::Maximized
    # Visible is only reliable after Shown; center the rows using the final window width.
    $form.PerformLayout()
    Update-ToolbarLayout
    Set-WindowChrome $form ([bool]$btnTheme.Tag)
})
$busyForm.Add_Shown({
    Set-WindowChrome $busyForm ([bool]$btnTheme.Tag)
})

$form.Add_Resize({
    if ($busyForm.Visible) {
        $modalX = $form.Left + [Math]::Max(0, [int](($form.Width - $busyForm.Width) / 2))
        $modalY = $form.Top + [Math]::Max(0, [int](($form.Height - $busyForm.Height) / 2))
        $busyForm.Location = New-Object Drawing.Point($modalX, $modalY)
    }
})

if ($env:TXT_PREVIEW_TEST_MODE -ne "1") {
    [void]$form.ShowDialog()
}
