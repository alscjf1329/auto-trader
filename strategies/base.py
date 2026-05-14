from abc import ABC, abstractmethod


class BaseStrategy(ABC):

    def __init__(self):
        pass

    @abstractmethod
    def get_targets(self) -> list:
        """매매 대상 종목 코드 리스트"""
        pass

    @abstractmethod
    def should_buy(self, data: dict) -> bool:
        """매수 조건 - True 반환시 매수"""
        pass

    @abstractmethod
    def should_sell(self, data: dict, holding: dict) -> bool:
        """매도 조건 - True 반환시 매도"""
        pass
