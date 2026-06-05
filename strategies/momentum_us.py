"""
strategies/momentum_us.py - 미국주식 52주 신고가 모멘텀 전략

매수: 현재가 >= 52주 최고가 (신고가 돌파)
매도: 익절 또는 손절 기준 도달

파라미터: settings.yaml → params.momentum_us
"""

from strategies.base_us import BaseStrategyUS
import settings


class MomentumStrategyUS(BaseStrategyUS):

    def __init__(self):
        super().__init__()
        p = settings.get_params("momentum_us")
        self.TAKE_PROFIT = p.get("take_profit",  8.0)
        self.STOP_LOSS   = p.get("stop_loss",   -5.0)

    def get_targets(self) -> list[str]:
        return settings.STOCK_US_CODES

    def should_buy(self, data: dict) -> bool:
        current  = data.get("current", 0)
        high_52w = data.get("high_52w", 0)
        if not high_52w:
            return False
        result = current >= high_52w
        if result:
            print(f"  [US모멘텀] {data.get('name', data.get('ticker'))} "
                  f"신고가 돌파 ${current:.2f} >= ${high_52w:.2f}")
        return result

    def should_sell(self, data: dict, holding: dict) -> bool:
        avg = float(holding.get("pchs_avg_pric", 0))
        if not avg:
            return False
        pct = (data["current"] - avg) / avg * 100
        if pct >= self.TAKE_PROFIT:
            print(f"  [US익절] {data.get('name', '')} {pct:+.2f}% >= {self.TAKE_PROFIT}%")
            return True
        if pct <= self.STOP_LOSS:
            print(f"  [US손절] {data.get('name', '')} {pct:+.2f}% <= {self.STOP_LOSS}%")
            return True
        return False
