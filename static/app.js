function openBotInfo() {
  const modal = document.getElementById("botInfoModal");
  if (modal) modal.classList.add("active");
}

function closeBotInfo() {
  const modal = document.getElementById("botInfoModal");
  if (modal) modal.classList.remove("active");
}

document.addEventListener("click", function (event) {
  const modal = document.getElementById("botInfoModal");
  if (modal && event.target === modal) {
    closeBotInfo();
  }
});
const candleCharts = {};

function createCandleChart(chartNumber) {
    const container = document.getElementById(`candle-chart-${chartNumber}`);
    const select = document.getElementById(`chart-symbol-${chartNumber}`);
    const timeframeSelect = document.getElementById(`chart${chartNumber}Timeframe`);
    const ema9Toggle = document.getElementById(`chart${chartNumber}Ema9Toggle`);
    const ema20Toggle = document.getElementById(`chart${chartNumber}Ema20Toggle`);
    const ema50Toggle = document.getElementById(`chart${chartNumber}Ema50Toggle`);
    const ohlcInfo = document.getElementById(`chart${chartNumber}OhlcInfo`);
    const livePriceBadge = document.getElementById(`chart${chartNumber}LivePrice`);
    const currentOhlcInfo = document.getElementById(`chart${chartNumber}CurrentOhlc`);

    if (!container || !select) {
        return;
    }

    if (typeof LightweightCharts === "undefined") {
        console.error("LightweightCharts library is not loaded.");
        return;
    }

    const chart = LightweightCharts.createChart(container, {
        layout: {
            background: { color: "#020617" },
            textColor: "#cbd5f5"
        },
        grid: {
            vertLines: { color: "rgba(148, 163, 184, 0.1)" },
            horzLines: { color: "rgba(148, 163, 184, 0.1)" },
        },
        rightPriceScale: {
            borderColor: "rgba(148, 163, 184, 0.3)",
        },
        timeScale: {
            borderColor: "rgba(148, 163, 184, 0.3)",
            timeVisible: true,
            secondsVisible: false,
        },
        crosshair: {
            mode: 1
        },
    });

    const candleSeries = chart.addCandlestickSeries({
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444",
    });

    let volumeSeries = null;

    const volumeSeriesOptions = {
        priceFormat: {
            type: "volume",
        },
        priceScaleId: "",
        scaleMargins: {
            top: 0.8,
            bottom: 0,
        },
    };


    if (typeof chart.addHistogramSeries === "function") {
        volumeSeries = chart.addHistogramSeries(volumeSeriesOptions);
    } else if (
        typeof chart.addSeries === "function" &&
        typeof LightweightCharts.HistogramSeries !== "undefined"
    ) {
        volumeSeries = chart.addSeries(LightweightCharts.HistogramSeries, volumeSeriesOptions);
    } else {
        console.error(`Chart ${chartNumber} volume series is not supported by this Lightweight Charts build.`);
    }

    const ema9Series = chart.addLineSeries({
        color: "#facc15",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
    });

    const ema20Series = chart.addLineSeries({
        color: "#38bdf8",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
    });

    const ema50Series = chart.addLineSeries({
        color: "#a855f7",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
    });

    candleCharts[chartNumber] = {
        chart,
        candleSeries,
        volumeSeries,
        ema9Series,
        ema20Series,
        ema50Series,
        container,
        select,
        timeframeSelect,
        ema9Toggle,
        ema20Toggle,
        ema50Toggle,
        ohlcInfo,
        livePriceBadge,
        currentOhlcInfo,
        hasLoadedInitialData: false,
        lastCandleTime: null,
    };

    loadCandleData(chartNumber);

    select.addEventListener("change", function () {
        const chartData = candleCharts[chartNumber];

        if (chartData) {
            chartData.hasLoadedInitialData = false;
            chartData.lastCandleTime = null;
        }

        loadCandleData(chartNumber);
    });

    if (timeframeSelect) {
        timeframeSelect.addEventListener("change", function () {
            handleTimeframeChange(chartNumber);
        });
    }

    [ema9Toggle, ema20Toggle, ema50Toggle].forEach(toggle => {
        if (toggle) {
            toggle.addEventListener("change", function () {
                applyEmaVisibility(candleCharts[chartNumber]);
           });
        }
    });

    chart.subscribeCrosshairMove(function (param) {
        if (!ohlcInfo) {
            return;
        }

        if (!param || !param.time) {
            ohlcInfo.textContent = "O: -- H: -- L: -- C: --";
            return;
        }

        let candle = null;

        if (param.seriesData && param.seriesData.get) {
            candle = param.seriesData.get(candleSeries);
        }

        if (!candle) {
            ohlcInfo.textContent = "O: -- H: -- L: -- C: --";
            return;
        }

        ohlcInfo.textContent =
            `O: ${Number(candle.open).toFixed(2)} ` +
            `H: ${Number(candle.high).toFixed(2)} ` +
            `L: ${Number(candle.low).toFixed(2)} ` +
            `C: ${Number(candle.close).toFixed(2)}`;
    });

    window.addEventListener("resize", function () {
        chart.applyOptions({
            width: container.clientWidth,
            height: container.clientHeight,
        });
    });
}

function calculateEMA(candles, period) {
    if (!Array.isArray(candles) || candles.length < period) {
        return [];
    }

    const multiplier = 2 / (period + 1);
    const emaData = [];

    let sum = 0;

    for (let i = 0; i < period; i++) {
        sum += Number(candles[i].close);
    }

    let previousEma = sum / period;

    emaData.push({
        time: Number(candles[period - 1].time),
        value: previousEma,
    });

    for (let i = period; i < candles.length; i++) {
        const close = Number(candles[i].close);
        const ema = (close - previousEma) * multiplier + previousEma;

        emaData.push({
            time: Number(candles[i].time),
            value: ema,
        });

        previousEma = ema;
    }

    return emaData;
}
function handleTimeframeChange(sourceChartNumber) {
    const sourceChartData = candleCharts[sourceChartNumber];

    if (!sourceChartData || !sourceChartData.timeframeSelect) {
        return;
    }

    const selectedTimeframe = sourceChartData.timeframeSelect.value;
    const syncToggle = document.getElementById("syncTimeframesToggle");

    if (!syncToggle || !syncToggle.checked) {
        sourceChartData.hasLoadedInitialData = false;
        sourceChartData.lastCandleTime = null;
        loadCandleData(sourceChartNumber);
        return;
    }

    Object.entries(candleCharts).forEach(([chartNumber, chartData]) => {
        if (!chartData || !chartData.timeframeSelect) {
            return;
        }

        chartData.timeframeSelect.value = selectedTimeframe;
        chartData.hasLoadedInitialData = false;
        chartData.lastCandleTime = null;
        loadCandleData(Number(chartNumber));
    });
}

function applyEmaVisibility(chartData) {
     if (!chartData) {
         return;
     }

     if (chartData.ema9Series && chartData.ema9Toggle) {
         chartData.ema9Series.applyOptions({
             visible: chartData.ema9Toggle.checked,
        });
    }

    if (chartData.ema20Series && chartData.ema20Toggle) {
        chartData.ema20Series.applyOptions({
            visible: chartData.ema20Toggle.checked,
       });
    }

    if (chartData.ema50Series && chartData.ema50Toggle) {
        chartData.ema50Series.applyOptions({
            visible: chartData.ema50Toggle.checked,
       });
    }
}

async function loadCandleData(chartNumber) {
    const chartData = candleCharts[chartNumber];

    if (!chartData) {
        return;
    }

    const symbol = chartData.select.value;

    const timeframe = chartData.timeframeSelect ? chartData.timeframeSelect.value : "5m";

    const intervalMap = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "4h": "240",
        "1d": "1440",
    };

    const interval = intervalMap[timeframe] || "5";

    try {
        const safeSymbol = symbol.replace("/", "%2F");
        const response = await fetch(`/api/market/candles?symbol=${safeSymbol}&interval=${interval}`);

        if (!response.ok) {
            throw new Error(`Candle request failed with status ${response.status}`);
        }

        const data = await response.json();

        if (!data.candles || !Array.isArray(data.candles)) {
            chartData.candleSeries.setData([]);
            return;
        }

        const formattedData = data.candles.map(c => ({
            time: Number(c.time),
            open: Number(c.open),
            high: Number(c.high),
            low: Number(c.low),
            close: Number(c.close),
        }));

        const volumeData = data.candles.map(c => ({
            time: Number(c.time),
            value: Number(c.volume || 0),
            color: Number(c.close) >= Number(c.open)
                ? "rgba(34, 197, 94, 0.35)"
                : "rgba(239, 68, 68, 0.35)",
        }));


        const ema9Data = calculateEMA(formattedData, 9);
        const ema20Data = calculateEMA(formattedData, 20);
        const ema50Data = calculateEMA(formattedData, 50);

        chartData.candleSeries.setData(formattedData);

        if (chartData.volumeSeries) {
            chartData.volumeSeries.setData(volumeData);
        }

        if (chartData.ema9Series) {
            chartData.ema9Series.setData(ema9Data);
        }

        if (chartData.ema20Series) {
            chartData.ema20Series.setData(ema20Data);
        }

        if (chartData.ema50Series) {
            chartData.ema50Series.setData(ema50Data);
        }

        applyEmaVisibility(chartData);


    const latestCandle = formattedData[formattedData.length - 1];

    if (latestCandle && chartData.livePriceBadge) {
        chartData.livePriceBadge.textContent = `$${latestCandle.close.toFixed(2)}`;
    }

    if (latestCandle && chartData.currentOhlcInfo) {
        chartData.currentOhlcInfo.textContent =
            `Current: O ${latestCandle.open.toFixed(2)} ` +
            `H ${latestCandle.high.toFixed(2)} ` +
            `L ${latestCandle.low.toFixed(2)} ` +
            `C ${latestCandle.close.toFixed(2)}`;
    }

        chartData.chart.timeScale().fitContent();

    } catch (error) {
        console.error(`Chart ${chartNumber} candle error:`, error);
    }
}

function initTripleCandleCharts() {
    createCandleChart(1);
    createCandleChart(2);
    createCandleChart(3);

    setInterval(function () {
        loadCandleData(1);
        loadCandleData(2);
        loadCandleData(3);
    }, 5000);
}
function handleChartToolbarClick(event) {
    const button = event.target.closest(".chart-tool-btn");

    if (!button) {
        return;
    }

    const chartNumber = Number(button.dataset.chart);
    const action = button.dataset.action;
    const chartData = candleCharts[chartNumber];

    if (!chartData) {
        return;
    }


    if (action === "reset") {
        chartData.chart.timeScale().fitContent();
        return;
    }

    if (action === "refresh") {
        chartData.hasLoadedInitialData = false;
        chartData.lastCandleTime = null;
        loadCandleData(chartNumber);
        return;
    }

    if (action === "hide-emas") {
        const shouldHide =
            chartData.ema9Toggle?.checked ||
            chartData.ema20Toggle?.checked ||
            chartData.ema50Toggle?.checked;

        if (chartData.ema9Toggle) chartData.ema9Toggle.checked = !shouldHide;
        if (chartData.ema20Toggle) chartData.ema20Toggle.checked = !shouldHide;
        if (chartData.ema50Toggle) chartData.ema50Toggle.checked = !shouldHide;

        applyEmaVisibility(chartData);

        button.textContent = shouldHide ? "Show EMAs" : "Hide EMAs";
        return;
    }

    if (action === "fullscreen") {
        openChartFullscreen(chartNumber, button);
        return;
    }
}

let fullscreenChartState = {
    chartNumber: null,
    card: null,
    placeholder: null,
    originalParent: null,
    originalNextSibling: null,
};

function findChartCardFromButton(button) {
    if (!button) {
        return null;
    }

    return button.closest(
        ".candle-card, .candle-chart-card, .chart-card, .market-chart-card, .tradingview-chart-card"
    );
}
function resizeChartByNumber(chartNumber) {
    const chartData = candleCharts[chartNumber];

    if (!chartData || !chartData.chart || !chartData.container) {
        return;
    }

    setTimeout(() => {
        chartData.chart.applyOptions({
            width: chartData.container.clientWidth,
            height: chartData.container.clientHeight,
        });

        chartData.chart.timeScale().fitContent();
    }, 100);

    setTimeout(() => {
        chartData.chart.applyOptions({
            width: chartData.container.clientWidth,
            height: chartData.container.clientHeight,
        });

        chartData.chart.timeScale().fitContent();
    }, 400);
}

function openChartFullscreen(chartNumber, button) {
    const modal = document.getElementById("chartFullscreenModal");
    const mount = document.getElementById("chartFullscreenMount");
    const title = document.getElementById("chartFullscreenTitle");

    if (!modal || !mount || !title) {
        console.warn("Fullscreen modal elements are missing.");
        return;
    }

    const chartData = candleCharts[chartNumber];

    if (!chartData) {
        console.warn(`Chart ${chartNumber} was not found.`);
        return;
    }

    const card = findChartCardFromButton(button);

    if (!card) {
        console.warn(`Chart card for chart ${chartNumber} was not found.`);
        return;
    }

    if (fullscreenChartState.card) {
        closeChartFullscreen();
    }

    const placeholder = document.createElement("div");
    placeholder.className = "chart-fullscreen-placeholder";

    fullscreenChartState = {
        chartNumber,
        card,
        placeholder,
        originalParent: card.parentNode,
        originalNextSibling: card.nextSibling,
    };

    card.parentNode.insertBefore(placeholder, card);
    mount.innerHTML = "";
    mount.appendChild(card);

    card.classList.add("is-chart-fullscreen-card");
    modal.classList.add("is-open");
    document.body.classList.add("chart-fullscreen-active");

    const symbol = chartData.select ? chartData.select.value : `Chart ${chartNumber}`;
    const timeframe = chartData.timeframeSelect ? chartData.timeframeSelect.value : "";

    title.textContent = timeframe
        ? `${symbol} • ${timeframe} Fullscreen`
        : `${symbol} Fullscreen`;

    resizeChartByNumber(chartNumber);
    setTimeout(resizeAllCharts, 500);
}

function closeChartFullscreen() {
    const modal = document.getElementById("chartFullscreenModal");
    const mount = document.getElementById("chartFullscreenMount");

    if (!fullscreenChartState.card || !fullscreenChartState.originalParent) {
        if (modal) {
            modal.classList.remove("is-open");
        }

        document.body.classList.remove("chart-fullscreen-active");
        return;
    }

    const {
        chartNumber,
        card,
        placeholder,
        originalParent,
        originalNextSibling,
    } = fullscreenChartState;

    card.classList.remove("is-chart-fullscreen-card");

    if (originalNextSibling && originalNextSibling.parentNode === originalParent) {
        originalParent.insertBefore(card, originalNextSibling);
    } else {
        originalParent.appendChild(card);
    }

    if (placeholder && placeholder.parentNode) {
        placeholder.parentNode.removeChild(placeholder);
    }

    if (mount) {
        mount.innerHTML = "";
    }

    if (modal) {
        modal.classList.remove("is-open");
    }

    document.body.classList.remove("chart-fullscreen-active");

    fullscreenChartState = {
        chartNumber: null,
        card: null,
        placeholder: null,
        originalParent: null,
        originalNextSibling: null,
    };

    resizeChartByNumber(chartNumber);
}

document.addEventListener("click", function (event) {
    if (event.target && event.target.id === "closeChartFullscreen") {
        closeChartFullscreen();
    }

    if (event.target && event.target.id === "chartFullscreenModal") {
        closeChartFullscreen();
    }
});

document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
        closeChartFullscreen();
    }
});


function resizeAllCharts() {
    Object.values(candleCharts).forEach(chartData => {
        if (!chartData || !chartData.chart || !chartData.container) {
            return;
        }

        chartData.chart.applyOptions({
            width: chartData.container.clientWidth,
            height: chartData.container.clientHeight,
        });

        chartData.chart.timeScale().fitContent();
    });
}

document.addEventListener("click", handleChartToolbarClick);
document.addEventListener("DOMContentLoaded", initTripleCandleCharts);
