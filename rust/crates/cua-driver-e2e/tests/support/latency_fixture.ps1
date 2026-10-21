param([string]$Dir = $PSScriptRoot)
# Throwaway WinForms fixture: 9 controls, shown without activation, restored
# (without activation) if anything minimizes it.
# Out-of-band mutations: write a line to $Dir\cmd.txt ("label <text>", "add <name>",
# "remove <name>", "disable <name>", "enable <name>", "value <text>"); the form applies it
# and appends "ok <n>" to $Dir\ack.txt.
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @"
using System;
using System.IO;
using System.Drawing;
using System.Windows.Forms;
public class LatencyFixture : Form {
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
    protected override bool ShowWithoutActivation { get { return true; } }
    string dir; int applied = 0; Label status; TextBox box; FlowLayoutPanel flow;
    public LatencyFixture(string dir) {
        this.dir = dir;
        Text = "Dove Latency Fixture";
        StartPosition = FormStartPosition.Manual;
        var wa = Screen.PrimaryScreen.WorkingArea;
        Bounds = new Rectangle(wa.Right - 440, wa.Bottom - 420, 420, 400);
        flow = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoScroll = true };
        status = new Label { Text = "Status: idle", Name = "status", AutoSize = true };
        box = new TextBox { Name = "entry", Width = 200, Text = "hello" };
        var save = new Button { Text = "Save", Name = "save" };
        var cancel = new Button { Text = "Cancel", Name = "cancel" };
        var add = new Button { Text = "Add row", Name = "addrow" };
        int n = 0;
        add.Click += (s, e) => { n++; flow.Controls.Add(new Button { Text = "Row " + n, Name = "row" + n }); };
        save.Click += (s, e) => { status.Text = "Status: saved"; };
        var check = new CheckBox { Text = "Remember", Name = "remember" };
        var combo = new ComboBox { Name = "mode", DropDownStyle = ComboBoxStyle.DropDownList };
        combo.Items.AddRange(new object[] { "Fast", "Slow" }); combo.SelectedIndex = 0;
        var list = new ListBox { Name = "items", Height = 40 };
        list.Items.AddRange(new object[] { "Alpha", "Beta" });
        flow.Controls.AddRange(new Control[] { status, box, save, cancel, add, check, combo, list });
        Controls.Add(flow);
        var t = new Timer { Interval = 25 };
        t.Tick += (s, e) => Poll();
        t.Start();
        Shown += (s, e) => File.WriteAllText(Path.Combine(dir, "fixture.json"),
            "{\"pid\":" + System.Diagnostics.Process.GetCurrentProcess().Id + ",\"hwnd\":" + Handle.ToInt64() + "}");
    }
    void Poll() {
        // A minimized WinForms window exposes no client area over UI Automation.
        // Show Desktop and similar minimize every window; come back without
        // taking focus (SW_SHOWNOACTIVATE).
        if (WindowState == FormWindowState.Minimized) ShowWindow(Handle, 4);
        var cmd = Path.Combine(dir, "cmd.txt");
        if (!File.Exists(cmd)) return;
        string[] lines;
        try { lines = File.ReadAllLines(cmd); File.Delete(cmd); } catch { return; }
        foreach (var raw in lines) {
            var line = raw.Trim(); if (line.Length == 0) continue;
            var sp = line.IndexOf(' '); var verb = sp < 0 ? line : line.Substring(0, sp); var arg = sp < 0 ? "" : line.Substring(sp + 1);
            Control c;
            switch (verb) {
                case "label": status.Text = arg; break;
                case "value": box.Text = arg; break;
                case "add": flow.Controls.Add(new Button { Text = arg, Name = arg }); break;
                case "remove": c = Find(arg); if (c != null) { flow.Controls.Remove(c); c.Dispose(); } break;
                case "disable": c = Find(arg); if (c != null) c.Enabled = false; break;
                case "enable": c = Find(arg); if (c != null) c.Enabled = true; break;
                case "quit": Close(); return;
            }
            applied++;
        }
        File.AppendAllText(Path.Combine(dir, "ack.txt"), "ok " + applied + "\n");
    }
    Control Find(string name) { foreach (Control c in flow.Controls) if (c.Name == name || c.Text == name) return c; return null; }
}
"@
[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::Run((New-Object LatencyFixture $Dir))
