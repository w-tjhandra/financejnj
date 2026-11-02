(function () {
  "use strict";

  var cashflowData = document.getElementById("dashboard-cashflow-data");
  if (!cashflowData) {
    return;
  }

  if (!window.Chart) {
    throw new Error("Chart.js is required to render the dashboard charts.");
  }

  var cashflow = JSON.parse(cashflowData.textContent);
  var categoryElement = document.getElementById("dashboard-category-data");
  var categories = categoryElement ? JSON.parse(categoryElement.textContent) : null;
  var translate = window.TelurFinanceTranslations
    ? window.TelurFinanceTranslations.text
    : function (text) {
        return text;
      };
  var fontFamily = "Helvetica, Arial, sans-serif";
  var money = new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "IDR",
    maximumFractionDigits: 0,
  });
  var compactMoney = new Intl.NumberFormat("id-ID", {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  var cashflowCanvas = document.getElementById("dashboard-cashflow-chart");

  if (cashflowCanvas) {
    new window.Chart(cashflowCanvas, {
      type: "line",
      data: {
        labels: cashflow.labels,
        datasets: [
          {
            label: translate("Pemasukan"),
            data: cashflow.income,
            borderColor: "#32804d",
            backgroundColor: "rgb(50 128 77 / 12%)",
            fill: true,
            tension: 0.35,
            pointRadius: 2,
            pointHoverRadius: 4,
          },
          {
            label: translate("Pengeluaran"),
            data: cashflow.expense,
            borderColor: "#c66555",
            backgroundColor: "rgb(198 101 85 / 8%)",
            fill: true,
            tension: 0.35,
            pointRadius: 2,
            pointHoverRadius: 4,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            position: "bottom",
            labels: { usePointStyle: true, boxWidth: 7, font: { family: fontFamily } },
          },
          tooltip: {
            callbacks: {
              label: function (context) {
                return context.dataset.label + ": " + money.format(context.raw);
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { maxTicksLimit: 8, font: { family: fontFamily } },
          },
          y: {
            beginAtZero: true,
            grid: { color: "#edf1ed" },
            ticks: {
              font: { family: fontFamily },
              callback: function (value) {
                return "Rp " + compactMoney.format(value);
              },
            },
          },
        },
      },
    });
  }

  var categoryCanvas = document.getElementById("dashboard-category-chart");
  if (categoryCanvas && categories) {
    new window.Chart(categoryCanvas, {
      type: "doughnut",
      data: {
        labels: categories.labels,
        datasets: [
          {
            data: categories.values,
            backgroundColor: ["#32804d", "#d9a441", "#6385a6", "#c66555", "#7d6ca8"],
            borderColor: "#fff",
            borderWidth: 3,
            hoverOffset: 5,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        cutout: "68%",
        plugins: {
          legend: {
            position: "bottom",
            labels: { usePointStyle: true, boxWidth: 7, padding: 14, font: { family: fontFamily } },
          },
          tooltip: {
            callbacks: {
              label: function (context) {
                return context.label + ": " + money.format(context.raw);
              },
            },
          },
        },
      },
    });
  }
})();
