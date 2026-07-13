const delayMs = Math.max(0, Number(process.env.US_BALANCES_FAKE_UPDATE_DELAY_MS || 75));
await new Promise((resolve) => setTimeout(resolve, delayMs));
console.log("fake update completed without changing source data");
