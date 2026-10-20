# Throwaway WinForms app for the W3 run_steps live test. Never activates
# itself (ShowWithoutActivation + WS_EX_NOACTIVATE), so it never takes focus.
#   Main "W3 Batch Test": button "Open details", label "Result: none".
#   "Open details" shows "W3 Details" after 800 ms (non-modal). Its three
#   text boxes (Name, Email, Phone) enable after another 1000 ms. "Submit"
#   stays disabled until all three are filled, then slides in for ~600 ms.
#   Submit writes "Result: Saved <name> / <email> / <phone>" and closes it.
param([int]$ExitAfterSeconds = 300)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Windows.Forms;

public class QuietForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams {
        get { var cp = base.CreateParams; cp.ExStyle |= 0x08000000; return cp; } // WS_EX_NOACTIVATE
    }
}

public static class W3App {
    static QuietForm main;
    static Label result;
    static QuietForm details;

    static Timer After(int ms, Action action) {
        var t = new Timer { Interval = ms };
        t.Tick += (s, e) => { t.Stop(); t.Dispose(); action(); };
        t.Start();
        return t;
    }

    static void OpenDetails() {
        if (details != null) return;
        After(800, ShowDetails);
    }

    static void ShowDetails() {
        details = new QuietForm { Text = "W3 Details", StartPosition = FormStartPosition.Manual,
            Location = new Point(main.Left + 40, main.Top + 60), Size = new Size(360, 240) };
        var hint = new Label { Text = "Fill in all fields", Left = 10, Top = 8, Width = 300 };
        details.Controls.Add(hint);
        var boxes = new TextBox[3];
        string[] names = { "Name", "Email", "Phone" };
        for (int i = 0; i < 3; i++) {
            var tb = new TextBox { Left = 90, Top = 36 + 30 * i, Width = 220, Enabled = false,
                AccessibleName = names[i], Name = names[i] };
            details.Controls.Add(new Label { Text = names[i] + ":", Left = 10, Top = 38 + 30 * i, Width = 70 });
            details.Controls.Add(tb);
            boxes[i] = tb;
        }
        var submit = new Button { Text = "Submit", Left = 330, Top = 140, Width = 80, Enabled = false };
        var close = new Button { Text = "Close", Left = 230, Top = 175, Width = 80 };
        details.Controls.Add(submit);
        details.Controls.Add(close);
        // Submit slides from x=330 to x=130 over ~600 ms once it enables.
        var slide = new Timer { Interval = 50 };
        slide.Tick += (s, e) => {
            if (submit.IsDisposed) { slide.Stop(); return; }
            submit.Left = Math.Max(130, submit.Left - 17);
            if (submit.Left <= 130) { slide.Stop(); }
        };
        EventHandler changed = (s, e) => {
            bool ready = boxes[0].Text.Length > 0 && boxes[1].Text.Length > 0 && boxes[2].Text.Length > 0;
            if (ready && !submit.Enabled) slide.Start();
            submit.Enabled = ready;
        };
        foreach (var tb in boxes) tb.TextChanged += changed;
        submit.Click += (s, e) => {
            result.Text = "Result: Saved " + boxes[0].Text + " / " + boxes[1].Text + " / " + boxes[2].Text;
            var d = details; details = null; d.Close();
        };
        close.Click += (s, e) => { var d = details; details = null; d.Close(); };
        details.FormClosed += (s, e) => { details = null; };
        details.Show(main);
        After(1000, () => { foreach (var tb in boxes) if (!tb.IsDisposed) tb.Enabled = true; });
    }

    public static void Run(int exitAfterSeconds) {
        main = new QuietForm { Text = "W3 Batch Test", StartPosition = FormStartPosition.Manual,
            Location = new Point(40, 40), Size = new Size(420, 200) };
        var open = new Button { Text = "Open details", Left = 10, Top = 10, Width = 120 };
        open.Click += (s, e) => OpenDetails();
        result = new Label { Text = "Result: none", Left = 10, Top = 50, Width = 380 };
        main.Controls.Add(open);
        main.Controls.Add(result);
        After(exitAfterSeconds * 1000, () => main.Close());
        Application.Run(main);
    }
}
'@
[System.Windows.Forms.Application]::EnableVisualStyles()
[W3App]::Run($ExitAfterSeconds)
