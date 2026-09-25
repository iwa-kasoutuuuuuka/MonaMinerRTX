"""
Profitability and power efficiency calculation module.
Computes electricity cost, W/MH efficiency, and estimated MonaCoin rewards.
"""
from typing import Dict, Any


class ProfitCalculator:
    def __init__(self, electricity_rate_yen: float = 31.0, mona_jpy_price: float = 45.0):
        """
        :param electricity_rate_yen: Cost per 1 kWh in JPY (default ~31 JPY)
        :param mona_jpy_price: MonaCoin price in JPY (reference price)
        """
        self.electricity_rate_yen = electricity_rate_yen
        self.mona_jpy_price = mona_jpy_price

    def calculate(self, hashrate_mhs: float, power_watts: float) -> Dict[str, Any]:
        """
        Calculates efficiency, electricity costs, and rough estimates.
        """
        if hashrate_mhs <= 0.0 or power_watts <= 0.0:
            return {
                "watt_per_mh": 0.0,
                "hourly_cost_yen": 0.0,
                "daily_cost_yen": 0.0,
                "monthly_cost_yen": 0.0,
                "est_daily_mona": 0.0,
                "est_daily_revenue_yen": 0.0,
                "est_daily_profit_yen": 0.0,
            }

        # Energy consumption
        kwh_per_hour = power_watts / 1000.0
        hourly_cost = kwh_per_hour * self.electricity_rate_yen
        daily_cost = hourly_cost * 24.0
        monthly_cost = daily_cost * 30.5

        # Efficiency: W / MH
        watt_per_mh = power_watts / max(0.001, hashrate_mhs)

        # Rough Lyra2REv2 MonaCoin estimated yield
        # At typical network difficulty (~150-250), 100 MH/s yields ~0.3-0.6 MONA/day
        # We use a baseline formula: hashrate_mhs * 0.004 MONA/day per MH/s
        est_daily_mona = hashrate_mhs * 0.0042
        est_daily_revenue = est_daily_mona * self.mona_jpy_price
        est_daily_profit = est_daily_revenue - daily_cost

        return {
            "watt_per_mh": round(watt_per_mh, 3),
            "hourly_cost_yen": round(hourly_cost, 2),
            "daily_cost_yen": round(daily_cost, 1),
            "monthly_cost_yen": round(monthly_cost, 0),
            "est_daily_mona": round(est_daily_mona, 4),
            "est_daily_revenue_yen": round(est_daily_revenue, 1),
            "est_daily_profit_yen": round(est_daily_profit, 1),
        }
