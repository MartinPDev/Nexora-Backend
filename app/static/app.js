const USERNAME = window.DASHBOARD_USERNAME;

const savedUser = localStorage.getItem("bot_username");
        const savedToken = localStorage.getItem("bot_token");

        if (!savedUser || !savedToken) {
            window.location.href = "/login";
       }

        function logout() {
            localStorage.removeItem("bot_username");
            localStorage.removeItem("bot_token");
            window.location.href = "/login";
       }

async function createRapidScalperPreview() {
    const payload = {
        symbol: document.getElementById("scalper_symbol").value,
        side: document.getElementById("scalper_side").value,
        amount_usd: parseFloat(document.getElementById("scalper_amount").value),
        scalp_target_percent: parseFloat(document.getElementById("scalper_target").value),
        mode: document.getElementById("scalper_mode").value
    };

    const res = await fetch("/elite/rapid-scalper/preview", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "x-plan": "elite"
        },
        body: JSON.stringify(payload)
    });

    const data = await res.json();

    const msg = document.getElementById("rapid_scalper_message");

    if (!res.ok) {
        msg.innerText = data.detail || "Request failed.";
        return;
    }

    msg.innerText = "Preview created successfully.";

    loadRapidScalperHistory();
}

    async function runRapidScalperPaper() {
        const payload = {
            symbol: document.getElementById("scalper_symbol").value,
            side: document.getElementById("scalper_side").value,
            amount_usd: parseFloat(document.getElementById("scalper_amount").value),
            scalp_target_percent: parseFloat(document.getElementById("scalper_target").value),
            mode: document.getElementById("scalper_mode").value
        };

        const res = await fetch("/elite/rapid-scalper/run-paper", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "x-plan": "elite"
            },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        const msg = document.getElementById("rapid_scalper_message");

        if (!res.ok) {
            msg.innerText = data.detail || "Paper trade failed.";
            return;
        }

        msg.innerText = `Paper trade complete | PnL: $${data.pnl_usd.toFixed(2)} (${
            data.pnl_percent.toFixed(2)
        }%)`;

        loadRapidScalperHistory();
    }


    async function loadRapidScalperHistory() {
        try {
            const res = await fetch("/elite/rapid-scalper/history", {
                headers: {
                    "x-plan": "elite"
                }
            });

            const text = await res.text();

            let data;
            try {
                data = JSON.parse(text);
            } catch {
                console.error("Non-JSON response:", text);
                document.getElementById("rapid_scalper_history").innerText = "Error loading data.";
                return;
            }

            const box = document.getElementById("rapid_scalper_history");

            if (!res.ok) {
                box.innerText = data.detail || "Could not load Rapid Scalper history.";
                return
            }

            if (!data.length) {
                box.innerText = "No Rapid Scalper setups yet.";
                return;

            }

            box.innerHTML = data.map(item => `
            <div style="
            padding:10px;
            border:1px solid #334155;
            border-radius:10px;
            margin-bottom:8px;
            background:#020617;
            ">
            <strong>${item.symbol}</strong>
            |
            ${item.side.toUpperCase()}
            |
            $${item.amount_usd}
            |
            Target ${item.scalp_target_percent}%
            |
            ${item.mode}
            <br>
            <span style="font-size:12px;color:#64748b;">
            ${item.status} • ${item.created_at}
            </span>
            </div>
            `).join("");

        } catch (err) {
            console.error(err);
            document.getElementById("rapid_scalper_history").innerText = "Failed to load.";
        }
    }

    async function loadBotStatus() {
        const res = await fetch('/bot-control/${USERNAME}');
        const data = await res.json();

        const status = document.getElementById('bot_status');
        const dot = document.getElementById('bot_dot');
        const text = document.getElementById('bot_status_text');

        if (data.bot_enabled === true) {
            status.innerText = 'Bot Status: RUNNING';
            status.style.color = '#22c55e';

            text.innerText = 'RUNNING';
            dot.style.background = '#22c55e';
            dot.style.boxShadow = '0 0 14px rgba(34,197,94,1)';
       } else {
            status.innerText = 'Bot Status: STOPPED';
            status.style.color = '#ef4444';

            text.innerText = 'STOPPED';
            dot.style.background = '#ef4444';
            dot.style.boxShadow = '0 0 14px rgba(239,68,68,1)';
       }
    }
    // loadRapidScalperHistory();

    async function startBot() {
        await fetch('/bot-control/${USERNAME}/start', {
            method: 'POST'
       });

        loadBotStatus();
   }

    async function stopBot() {
        await fetch('/bot-control/${USERNAME}/stop', {
            method: 'POST'
       });

        loadBotStatus();
   }


    async function loadDashboard() {
        const res = await fetch('/dashboard/${USERNAME}');
        const data = await res.json();
        await updateProfitTicker(data);

        animateValue('equity', data.equity);
        document.getElementById('cash').innerText = '$' + data.cash.toFixed(2);

        const pnlEl = document.getElementById('pnl');
        pnlEl.innerText = '$' + data.pnl.toFixed(2) + ' (' + data.pnl_percent.toFixed(2) + '%)';
        pnlEl.className = 'value ' + (data.pnl >= 0 ? 'profit' : 'loss');

        document.getElementById('open_positions').innerText = data.open_positions;

        const tbody = document.getElementById('positions');
        tbody.innerHTML = '';

        for (const [symbol, pos] of Object.entries(data.positions)) {
                    const row = document.createElement('tr');

            row.innerHTML = `
                <td>${symbol}</td>
                <td>${pos.entry}</td>
                <td>${pos.amount}</td>
                <td>${pos.peak ?? '-'}</td>
                <td>${pos.partial_taken === true ? 'Yes' : 'No'}</td>
                <td><span class="status">Active</span></td>
            `;

            tbody.appendChild(row);
        }
    }

    async function updateProfitTicker(data) {
        const content = document.getElementById("profit_ticker_content");
        const clone = document.getElementById("profit_ticker_content_clone");

        if (!content || !clone) {
            return;
        }

        const pnlClass = data.pnl >= 0 ? "ticker-profit" : "ticker-loss";
        const pnlSign = data.pnl >= 0 ? "+" : "";

        const tradeEvents = await loadTradeTickerEvents();

        const html = `
            <span>Equity: <strong>$${data.equity.toFixed(2)}</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            <span>Cash: <strong>$${data.cash.toFixed(2)}</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            <span>PnL: <strong class="${pnlClass}">${pnlSign}$${data.pnl.toFixed(2)} (${data.pnl_percent.toFixed(2)}%)</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            <span>Open Positions: <strong>${data.open_positions}</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            <span>Bot Feed: <strong>LIVE</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            ${tradeEvents}
            <span>Risk Engine: <strong>ACTIVE</strong></span>
            &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;

        `;

        content.innerHTML = html;
        clone.innerHTML = html;
        }

    async function loadTradeTickerEvents() {
        const res = await fetch('/trade-history/${USERNAME}');
        const trades = await res.json();

        if (!Array.isArray(trades) || trades.length === 0) {
            return "";
        }

        return trades.slice(0, 5).map(t => {
            const pnl = Number(t.pnl || 0);
            const resultClass = pnl >= 0 ? "ticker-profit" : "ticker-loss";
            const sign = pnl >= 0 ? "+" : "";

            return `
                <span>TRADE: <strong>${t.symbol || "N/A"}</strong></span>
                &nbsp;
                <span class="${resultClass}">${sign}$${pnl.toFixed(2)}</span>
                &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
            `;
        }).join("");
    }



    function animateValue(id, target) {
        const el = document.getElementById(id);
        const start = parseFloat(el.innerText.replace('$','')) || 0;
        const duration = 400;
        const startTime = performance.now();

        function update(now) {
            const progress = Math.min((now - startTime) / duration, 1);
            const value = start + (target - start) * progress;
            el.innerText = '$' + value.toFixed(2);

            if (progress < 1) {
                requestAnimationFrame(update);
            }
        }

        requestAnimationFrame(update);
    }

let liveMarketPoints = [];

async function loadLiveMarketPrice() {
    const symbol = document.getElementById("live_symbol").value;

    const res = await fetch(`/market/live-price/${symbol}`);
    const data = await res.json();

    if (!res.ok) {
        document.getElementById("live_price_label").innerText = "Price unavailable";
        return;
    }

    liveMarketPoints.push(data.price);

    if (liveMarketPoints.length > 60) {
        liveMarketPoints.shift();
    }

    document.getElementById("live_price_label").innerText =
        data.symbol + " $" + Number(data.price).toFixed(4);

    drawLiveMarketChart();
}


function drawLiveMarketChart() {
    const canvas = document.getElementById("live_market_chart");
    const ctx = canvas.getContext("2d");

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (liveMarketPoints.length < 2) {
        ctx.fillStyle = "#94a3b8";
        ctx.font = "16px Arial";
        ctx.fillText("Waiting for live price data...", 30, 40);
        return;
    }

    const min = Math.min(...liveMarketPoints);
    const max = Math.max(...liveMarketPoints);
    const range = max - min || 1;

    const padding = 35;
    const width = canvas.width;
    const height = canvas.height;

    const first = liveMarketPoints[0];
    const last = liveMarketPoints[liveMarketPoints.length - 1];
    const isUp = last >= first;
    const lineColor = isUp ? "#22c55e" : "#ef4444";

    ctx.fillStyle = "#020617";
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = "#1e293b";
    ctx.lineWidth = 1;

    for (let i = 1; i <= 4; i++) {
        const y = padding + (i / 5) * (height - padding * 2);
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke();
    }

    const coords = liveMarketPoints.map((price, i) => {
        const x = padding + (i / (liveMarketPoints.length - 1)) * (width - padding * 2);
        const y = height - padding - ((price - min) / range) * (height - padding * 2);
        return { x, y, price };
    });

    ctx.beginPath();
    ctx.moveTo(coords[0].x, coords[0].y);

    for (let i = 1; i < coords.length - 1; i++) {
        const midX = (coords[i].x + coords[i + 1].x) / 2;
        const midY = (coords[i].y + coords[i + 1].y) / 2;
        ctx.quadraticCurveTo(coords[i].x, coords[i].y, midX, midY);
    }

    const lastPoint = coords[coords.length - 1];
    ctx.lineTo(lastPoint.x, lastPoint.y);

    ctx.shadowColor = lineColor;
    ctx.shadowBlur = 14;
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.shadowBlur = 0;

    ctx.beginPath();
    ctx.arc(lastPoint.x, lastPoint.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.shadowColor = lineColor;
    ctx.shadowBlur = 18;
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.fillStyle = "#e5e7eb";
    ctx.font = "14px Arial";
    ctx.fillText("Live: $" + last.toFixed(4), padding, 22);

    ctx.fillStyle = lineColor;
    ctx.fillText(isUp ? "Up" : "Down", padding + 130, 22);
}


async function loadEquityChart() {
    const res = await fetch('/equity-history/${USERNAME}');
    const points = await res.json();

    const canvas = document.getElementById('equity_chart');
    const ctx = canvas.getContext('2d');

    ctx.clearRect(0, 0, canvas.width, canvas.height);


    const unique = [];
    let lastEquity = null;

    for (const p of points) {
        if (p.equity !== lastEquity) {
            unique.push(p);
            lastEquity = p.equity;
        }
    }

    if (unique.length < 2) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '16px Arial';
        ctx.fillText('No meaningful equity movement yet.', 30, 40);
        return;
    }

    const equities = unique.map(p => p.equity);
    const min = Math.min(...equities);
    const max = Math.max(...equities);
    const range = max - min || 1;

    const padding = 35;
    const width = canvas.width;
    const height = canvas.height;

    ctx.fillStyle = '#020617';
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 1;

    for (let i = 1; i <= 4; i++) {
        const y = padding + (i / 5) * (height - padding * 2);
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke()
    }

    const coords = unique.map((p, i) => {
        const x = padding + (i / (unique.length - 1)) * (width - padding * 2);
        const y = height - padding - ((p.equity - min) / range) * (height - padding * 2);
        return { x, y, equity: p.equity, pnl: p.pnl };
    });

    const last = coords[coords.length - 1];
    const first = coords[0];
    const isProfit = last.equity >= first.equity;

    const lineColor = isProfit ? '#22c55e' : '#ef4444';

    ctx.beginPath();
    ctx.moveTo(coords[0].x, coords[0].y);

    for (let i = 1; i < coords.length - 1; i++) {
        const midX = (coords[i].x + coords[i + 1].x) / 2;
        const midY = (coords[i].y + coords[i + 1].y) / 2;
        ctx.quadraticCurveTo(coords[i].x, coords[i].y, midX, midY);
    }

    ctx.lineTo(last.x, last.y);

    ctx.shadowColor = lineColor;
    ctx.shadowBlur = 14;
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 3;
    ctx.stroke();

    ctx.shadowBlur = 0;

    const gradient = ctx.createLinearGradient(0, padding, 0, height - padding);
    gradient.addColorStop(0, isProfit ? 'rgba(34,197,94,0.25)' : 'rgba(239,68,68,0.25)');
    gradient.addColorStop(1, 'rgba(2,6,23,0)');

    ctx.lineTo(width - padding, height - padding);
    ctx.lineTo(padding, height - padding);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    ctx.beginPath();
    ctx.arc(last.x, last.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.shadowColor = lineColor;
    ctx.shadowBlur = 18;
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.fillStyle = '#e5e7eb';
    ctx.font = '14px Arial';
    ctx.fillText('Equity: $' + last.equity.toFixed(2), padding, 22);

    ctx.fillStyle = isProfit ? '#22c55e' : '#ef4444';
    ctx.fillText('PnL: $' + unique[unique.length - 1].pnl.toFixed(2), padding + 140, 22);

    ctx.fillStyle = '#64748b';
    ctx.font = '12px Arial';
    ctx.fillText('$' + max.toFixed(2), width - 95, padding);
    ctx.fillText('$' + min.toFixed(2), width - 95, height - padding)
}

    async function loadTradeHistory() {
        const res = await fetch('/trade-history/${USERNAME}');
        const trades = await res.json();

        const tbody = document.getElementById('trade_history');
        tbody.innerHTML = '';

        for (const trade of trades.reverse()) {
            const row = document.createElement('tr');

            const pnl = parseFloat(trade.pnl || 0);
            const resultColor = pnl >= 0 ? '#22c55e' : '#ef4444';

            row.innerHTML = `
                <td>${trade.symbol}</td>
                <td>${trade.entry}</td>
                <td>${trade.exit}</td>
                <td>${trade.amount}</td>
                <td>${trade.score}</td>
                <td>${trade.prob}</td>
                <td style="color:${resultColor};">${pnl.toFixed(4)}</td>
                <td>${trade.result}</td>
            `;

            tbody.appendChild(row);
        }
    }

    async function loadSettings() {
        const res = await fetch('/settings/${USERNAME}');
        const data = await res.json();

        document.getElementById('risk_percent').value =
            data.risk_percent;

        document.getElementById('max_positions').value =
            data.max_positions;

        document.getElementById('stop_loss_percent').value =
            data.stop_loss_percent;

        document.getElementById('partial_take_profit_percent').value =
            data.partial_take_profit_percent;

        document.getElementById('trailing_stop_percent').value =
            data.trailing_stop_percent;

        document.getElementById('bot_mode').value =
            data.bot_mode;
    }

    async function saveSettings() {
        const settings = {
            risk_percent:
                parseFloat(document.getElementById('risk_percent').value),

            max_positions:
                parseInt(document.getElementById('max_positions').value),

            stop_loss_percent:
                parseFloat(document.getElementById('stop_loss_percent').value),

            partial_take_profit_percent:
                parseFloat(document.getElementById('partial_take_profit_percent').value),

            trailing_stop_percent:
                parseFloat(document.getElementById('trailing_stop_percent').value),

            bot_mode:
                document.getElementById('bot_mode').value
        };

        await fetch('/settings/${USERNAME}', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(settings)
        });

        document.getElementById('settings_status').innerText =
        'Settings saved';
    }

    async function loadBotLogs() {
        const res = await fetch('/bot-logs/${USERNAME}');
        const logs = await res.json();

        const box = document.getElementById('bot_logs');
        if (!box) return;

        if (!Array.isArray(logs) || logs.length === 0) {
            box.innerText = 'No logs found yet.';
            return;
        }


        const formatted = logs.slice(-80).map(line => {
            return '> ' + line;
        }).join('\\n');

        box.innerText = formatted;
        box.scrollTop = box.scrollHeight;

    }

    function toggleBotConsole() {
        const panel = document.getElementById("bot_console_panel");
        const arrow = document.getElementById("bot_console_arrow");

        if (!panel || !arrow) return;

        const isOpen = panel.classList.contains("open");

        if (isOpen) {
            panel.classList.remove("open");
            arrow.innerText = "▼";
            localStorage.setItem("bot_console_open", "false");
        } else {
            panel.classList.add("open");
            arrow.innerText = "▲";
            localStorage.setItem("bot_console_open", "false");
        }
    }

    function restoreBotConsoleState() {
        const panel = document.getElementById("bot_console_panel");
        const arrow = document.getElementById("bot_console_arrow");

        if (!panel || !arrow) return;

        const saved = localStorage.getItem("bot_console_open");

        if (saved === "false") {
            panel.classList.remove("open");
            arrow.innerText = "▼";
        } else {
            panel.classList.add("open");
            arrow.innerText = "▲";
        }
    }

    async function loadBilling() {
        const res = await fetch('/billing/${USERNAME}');
        const data = await res.json();

        document.getElementById('billing_plan').innerText =
            data.plan.toUpperCase();

        document.getElementById('billing_status').innerText =
            data.subscription_status.toUpperCase();

        const f = data.features;

        document.getElementById('billing_features').innerHTML = `
            Max Bots: ${f.max_bots}<br>
            Max Positions: ${f.max_positions}<br>
            Paper Trading: ${f.paper_trading ? 'Yes' : 'No'}<br>
            Live Trading: ${f.live_trading ? 'Yes' : 'No'}<br>
            Advanced AI: ${f.advanced_ai ? 'Yes' : 'No'}
        `;
    }

    async function changePlan(plan) {
    if (plan === 'basic') {
        const res = await fetch('/billing/${USERNAME}/checkout/basic', {
            method: 'POST'
        });

        const data = await res.json();

        if (data.checkout_url) {
            window.location.href = data.checkout_url;
            return;
        }

        alert(data.error || 'Checkout failed');
        return;
    }

    await fetch('/billing/${USERNAME}/set-plan/' + plan, {
        method: 'POST'
    });

    loadBilling();
}

    async function loadBots() {
        const res = await fetch('/bots/${USERNAME}');
        const bots = await res.json();

        const tbody = document.getElementById('my_bots');
        tbody.innerHTML = '';

        if (bots.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" style="color:#94a3b8;">
                        No bots created yet.
                    </td>
                </tr>
            `;
            return;
        }

        for (const bot of bots) {
            const row = document.createElement('tr');

            row.innerHTML = `
                <td>${bot.name}</td>
                <td>${bot.symbol}</td>
                <td>${bot.timeframe}</td>
                <td>${bot.risk_percent}</td>
                <td><span class="status">${bot.status}</span></td>
                <td>
                    <button
                        onclick="deleteBot('${bot.id}')"
                        style="
                        padding:8px 10px;
                        border:none;
                        border-radius:8px;
                        background:#ef4444;
                        color:white;
                        cursor:pointer;
                        "
                    >
                        Delete
                    </button>
                </td>
            `;

            tbody.appendChild(row);
        }
    }

    async function createBot() {
        const name = document.getElementById('new_bot_name').value || 'New Bot';
        const symbol = document.getElementById('new_bot_symbol').value || 'BTC/USD';

        const res = await fetch('/bots/${USERNAME}/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: name,
                symbol: symbol,
                timeframe: '15m',
                risk_percent: 1.0
            })
        });

        const data = await res.json();
        const status = document.getElementById('bot_create_status');

        if (data.error) {
            status.innerText = data.error + ' - upgrade required';
            status.style.color = '#ef4444';
            return;
        }

        status.innerText = 'Bot created';
        status.style.color = '#22c55e';

        document.getElementById('new_bot_name').value = '';
        document.getElementById('new_bot_symbol').value = '';

        loadBots();
    }

    async function deleteBot(botId) {
        await fetch('/bots/${USERNAME}/' + botId, {
            method: 'DELETE'
        });

        loadBots();
    }

    function toggleTradeHistory() {
        const panel = document.getElementById('trade_history_panel');

        if (panel.style.display === 'none') {
            panel.style.display = 'block';
        } else {
            panel.style.display = 'none';
        }
    }

    async function loadStrategies() {
        const res = await fetch('/strategies/${USERNAME}');
        const strategies = await res.json();

        const tbody = document.getElementById('strategies');
        tbody.innerHTML = '';

        if (strategies.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" style="color:#94a3b8;">
                        No strategies created yet.
                    </td>
                </tr>
            `;
            return;
        }

        for (const strategy of strategies) {
            const row = document.createElement('tr');

            row.innerHTML = `
                <td>${strategy.name}</td>
                <td>${strategy.mode}</td>
                <td>${strategy.min_score}</td>
                <td>${strategy.min_ai_probability}</td>
                <td>${strategy.stop_loss_percent}%</td>
                <td>${strategy.partial_take_profit_percent}%</td>
                <td>${strategy.trailing_stop_percent}%</td>
                <td>
                    <button
                        onclick="deleteStrategy('${strategy.id}')"
                        style="padding:8px 10px;border:none;border-radius:8px;background:#ef4444;color:white;cursor:pointer;"
                    >
                        Delete
                    </button>
                </td>
            `;

            tbody.appendChild(row);
        }
    }

    async function createStrategy() {
        const mode = document.getElementById('strategy_mode').value;

        let minScore = parseInt(document.getElementById('strategy_score').value || 55);
        let minAi = parseFloat(document.getElementById('strategy_ai').value || 0.40);

        if (mode === 'conservative') {
            minScore = minScore || 70;
            minAi = minAi || 0.60;
        }

        if (mode === 'aggressive') {
            minScore = minScore || 50;
            minAi = minAi || 0.35;
        }

        const payload = {
            name: document.getElementById('strategy_name').value || 'New Strategy',
            min_score: minScore,
            min_ai_probability: minAi,
            mode: mode,
            stop_loss_percent: 2.0,
            partial_take_profit_percent: 2.0,
            trailing_stop_percent: 1.5,
            cooldown_hours: 2
        };

        const res = await fetch('/strategies/${USERNAME}/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const data = await res.json();

        document.getElementById('strategy_status').innerText =
            data.error ? data.error : 'Strategy saved';

        document.getElementById('strategy_name').value = '';
        document.getElementById('strategy_score').value = '';
        document.getElementById('strategy_ai').value = '';

        loadStrategies();
    }

    async function deleteStrategy(strategyId) {
        await fetch('/strategies/${USERNAME}/' + strategyId, {
            method: 'DELETE'
        });

        loadStrategies();
    }



    loadDashboard();
    setInterval(loadDashboard, 5000);
    loadBotStatus();
    loadTradeHistory();
    loadSettings();
    loadBotLogs();
    loadEquityChart();
    loadBilling();
    loadBots();
    loadStrategies();
    loadLiveMarketPrice();
    restoreBotConsoleState();
    setInterval(loadLiveMarketPrice, 5000);

    document.getElementById("live_symbol").addEventListener("change", function() {
        liveMarketPoints = [];
        loadLiveMarketPrice();
    });

    setInterval(loadDashboard, 15000);
    setInterval(loadBotStatus, 15000);
    setInterval(loadTradeHistory, 15000);
    setInterval(loadBotLogs, 3000);
    setInterval(loadBilling, 30000);
    setInterval(loadBots, 15000);
    setInterval(loadStrategies, 15000);
    loadEquityChart();
