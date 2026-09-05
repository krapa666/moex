(() => {
  function finite(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function calculate({ currentPrice, fairValue, fullReturn, signalStatus }) {
    if (!finite(currentPrice) || !finite(fairValue) || Number(currentPrice) <= 0) return null;

    const current = Number(currentPrice);
    const fair = Number(fairValue);
    const pricePotential = ((fair - current) / current) * 100;
    const pricePoints = clamp(pricePotential, 0, 60);
    const remainingDividendYield = finite(fullReturn)
      ? Math.max(Number(fullReturn) - pricePotential, 0)
      : 0;
    const dividendPoints = clamp(remainingDividendYield, 0, 15) * (25 / 15);
    const activityPoints = {
      signal: 15,
      above_range: 7,
    }[signalStatus] || 0;

    return {
      score: Math.round(clamp(pricePoints + dividendPoints + activityPoints, 0, 100)),
      pricePotential,
      remainingDividendYield,
      pricePoints,
      dividendPoints,
      activityPoints,
    };
  }

  window.MoexWatchlistScore = Object.freeze({ calculate });
})();
