from pathlib import Path
import re

path = Path("main.py")
text = path.read_text()

path.with_suffix(".py.backup").write_text(text)

new_css = r'''
        * {{
            box-sizing: border-box;
        }}

        body {{
            font-family: Arial, sans-serif;
            background:
                radial-gradient(circle at top left, rgba(56,189,248,0.16), transparent 28%),
                radial-gradient(circle at top right, rgba(34,197,94,0.12), transparent 24%),
                #020617;
            color: white;
            margin: 0;
            padding: 24px;
        }}

        .premium-topbar,
        .card,
        .profit-ticker,
        .terminal-pill {{
            background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid rgba(148,163,184,0.18);
            border-radius: 16px;
            box-shadow: 0 12px 30px rgba(0,0,0,0.35);
        }}

        .premium-topbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 25px;
            margin-bottom: 25px;
        }}

        h1 {{
            font-size: 34px;
            margin: 0;
        }}

        h2 {{
            font-size: 20px;
            margin-top: 0;
            color: #e2e8f0;
        }}

        .sub,
        .label {{
            color: #94a3b8;
        }}

        .label {{
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 12px;
        }}

        .value {{
            font-size: 30px;
            font-weight: bold;
            margin-top: 8px;
            color: #e2e8f0;
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 20px;
            margin-bottom: 25px;
        }}

        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 25px;
        }}

        @media (max-width: 900px) {{
            .grid,
            .grid-2 {{
                grid-template-columns: 1fr;
            }}
        }}

        .card {{
            padding: 22px;
            margin-bottom: 25px;
            overflow: hidden;
            position: relative;
            z-index: 0;
        }}

        .card:hover {{
            border-color: rgba(56,189,248,0.45);
        }}

        input,
        select {{
            background: #020617;
            color: white;
            border: 1px solid #334155 !important;
            outline: none;
        }}

        button {{
            transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
        }}

        button:hover {{
            transform: translateY(-2px);
            opacity: 0.95;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            background: #020617;
            border: 1px solid #1e293b;
            border-radius: 14px;
            overflow: hidden;
        }}

        th,
        td {{
            padding: 14px;
            text-align: left;
            border-bottom: 1px solid #334155;
            color: #e2e8f0;
        }}

        th {{
            color: #94a3b8;
            font-size: 14px;
        }}

        .terminal-bg {{
            background-size: 28px 28px;
        }}

        .terminal-strip {{
            display: flex;
            gap: 14px;
            flex-wrap: wrap;
            margin-bottom: 25px;
        }}

        .terminal-pill {{
            display: inline-block;
            color: #cbd5e1;
            padding: 10px 14px;
            border-radius: 999px;
            font-size: 13px;
            margin: 4px;
        }}

        .terminal-pill strong {{
            color: #38bdf8;
        }}

        .premium-badge {{
            padding: 8px 12px;
            border-radius: 999px;
            background: rgba(56,189,248,0.15);
            color: #7dd3fc;
            border: 1px solid rgba(56,189,248,0.35);
            font-size: 13px;
            font-weight: bold;
        }}

        .live-dot {{
            display: inline-block;
            width: 9px;
            height: 9px;
            background: #22c55e;
            border-radius: 50%;
            margin-right: 8px;
            box-shadow: 0 0 14px rgba(34,197,94,0.9);
        }}

        .profit-ticker {{
            width: 100%;
            overflow: hidden;
            white-space: nowrap;
            margin: 10px 0 20px 0;
            height: 28px;
            line-height: 28px;
            font-size: 12px;
            padding: 0 12px;
        }}

        .profit-ticker-track {{
            display: flex;
            gap: 60px;
            width: max-content;
        }}

        .profit-ticker-content {{
            color: #cbd5e1;
            font-size: 12px;
            white-space: nowrap;
        }}

        .ticker-profit {{
            color: #22c55e !important;
        }}

        .ticker-loss {{
            color: #ef4444 !important;
        }}

        .console-card {{
            padding: 0;
            overflow: hidden;
            margin-bottom: 25px;
        }}

        .console-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 18px 22px;
            cursor: pointer;
            border-bottom: 1px solid rgba(56,189,248,0.16);
            background: linear-gradient(90deg, rgba(15,23,42,0.95), rgba(2,6,23,0.95));
        }}

        .console-header h2 {{
            margin: 0;
        }}

        .console-subtitle {{
            margin-top: 6px;
            font-size: 12px;
            color: #94a3b8;
        }}

        .console-panel {{
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
        }}

        .console-panel.open {{
            max-height: 320px;
        }}

        .log-console {{
            margin: 0;
            background: #020617;
            border-top: 1px solid rgba(56,189,248,0.12);
            padding: 14px;
            height: 260px;
            overflow-y: auto;
            font-family: Consolas, monospace;
            font-size: 12px;
            color: #94a3b8;
            white-space: pre-wrap;
        }}

        .log-console-live {{
            color: #22c55e;
        }}
'''

pattern = r'(def dashboard_ui\(username: str\):\s+return f""".*?<style>\n)(.*?)(\n\s*</style>)'
text = re.sub(pattern, lambda m: m.group(1) + new_css + m.group(3), text, count=1, flags=re.S)

text = text.replace("<th>Symbol</th\n", "<th>Symbol</th>\n")

text = text.replace(
'''    </span>

    </div>

    <div class="grid">''',
'''    </span>

    <div class="grid">'''
)

text = text.replace(
'''        <span id="settings_status" style="margin-left:15px;color:#94a3b8;"></span>
    </div>
</div>

<div class="card" style="margin-top:25px;">
    <h2>Subscription</h2>''',
'''        <span id="settings_status" style="margin-left:15px;color:#94a3b8;"></span>
    </div>

<div class="card" style="margin-top:25px;">
    <h2>Subscription</h2>'''
)

path.write_text(text)
print("Dashboard CSS and broken HTML repaired. Backup saved as main.py.backup")
