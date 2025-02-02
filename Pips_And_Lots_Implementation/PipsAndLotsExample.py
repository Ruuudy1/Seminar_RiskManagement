# Implementation based on: https://youtu.be/NGBPq_CSha8?feature=shared
# 
# MUST BE RUN ON USING THE QUANTCONNECT FRAMEWORK
#

from AlgorithmImports import *

class RangeBoundHedgingAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2019, 10, 20)
        self.SetEndDate(2019, 11, 25)
        self.SetCash(1000000)
        
        # Trading pair setup
        self.symbol = self.AddForex("EURUSD", Resolution.Minute).Symbol
        
        # Strategy parameters
        self.r2r = 2  # Risk to reward ratio
        self.buyLine = None
        self.sellLine = None
        self.maxDrawdown = 0.02  # 2% maximum drawdown
        self.positionSize = 0.01  # 1% of portfolio per trade
        
        # Position tracking
        self.openBuyLots = 0
        self.openSellLots = 0
        
        # Technical indicators
        self.sma = self.SMA(self.symbol, 20)
        self.atr = self.ATR(self.symbol, 14)
        self.high = self.MAX(self.symbol, 20)
        self.low = self.MIN(self.symbol, 20)
        
        # Risk management setup
        self.SetRiskManagement(RangeBoundRiskManagement(self.maxDrawdown))
        
        # Warm up period
        self.SetWarmUp(20)

    def OnData(self, data):
        if self.IsWarmingUp or not data.ContainsKey(self.symbol): 
            return

        self.UpdateRangeLevels()
        
        # Check if range levels are properly initialized
        if self.buyLine is None or self.sellLine is None:
            return
            
        current_price = data[self.symbol].Close
        
        # Risk checks
        if self.IsExcessiveDrawdown() or self.IsVolatilityHigh():
            self.LiquidatePositions() # Custom Liquidate function that also resets out variables
            return
            
        # Trading logic
        if current_price <= self.buyLine:
            buy_lots = self.CalculateBuyLots()
            if buy_lots > 0 and self.CanTrade():
                self.ExecuteBuyOrder(buy_lots)
                
        elif current_price >= self.sellLine:
            sell_lots = self.CalculateSellLots()
            if sell_lots > 0 and self.CanTrade():
                self.ExecuteSellOrder(sell_lots)

    def OnOrderEvent(self, orderEvent):
        if orderEvent.Status == OrderStatus.Filled:
            order = self.Transactions.GetOrderById(orderEvent.OrderId)
            # Update position tracking
            if order.Direction == OrderDirection.Buy:
                self.openBuyLots += abs(order.Quantity)
            else:
                self.openSellLots += abs(order.Quantity)

    def LiquidatePositions(self):
        self.Liquidate()
        self.openBuyLots = 0
        self.openSellLots = 0


    def CalculateBuyLots(self):
        """Calculate buy lot size with position sizing"""
        if self.openBuyLots == 0 and self.openSellLots == 0:
            # Initial trade size
            return self.Portfolio.TotalPortfolioValue * self.positionSize
        base_lots = ((self.r2r + 1) / self.r2r * self.openSellLots - self.openBuyLots) * 1.1
        return min(base_lots, self.Portfolio.TotalPortfolioValue * self.positionSize)

    def CalculateSellLots(self):
        """Calculate sell lot size with position sizing"""
        if self.openBuyLots == 0 and self.openSellLots == 0:
            # Initial trade size
            return self.Portfolio.TotalPortfolioValue * self.positionSize
        base_lots = ((self.r2r + 1) / self.r2r * self.openBuyLots - self.openSellLots) * 1.1
        return min(base_lots, self.Portfolio.TotalPortfolioValue * self.positionSize)

    def ExecuteBuyOrder(self, lots):
        """Execute buy order with risk management"""
        stop_price = self.buyLine - self.atr.Current.Value
        take_profit = self.buyLine + (self.atr.Current.Value * self.r2r)
        
        ticket = self.MarketOrder(self.symbol, lots)
        if ticket.Status == OrderStatus.Filled:
            self.openBuyLots += lots
            self.StopMarketOrder(self.symbol, -lots, stop_price)
            self.LimitOrder(self.symbol, -lots, take_profit)

    def ExecuteSellOrder(self, lots):
        """Execute sell order with risk management"""
        stop_price = self.sellLine + self.atr.Current.Value
        take_profit = self.sellLine - (self.atr.Current.Value * self.r2r)
        
        ticket = self.MarketOrder(self.symbol, -lots)
        if ticket.Status == OrderStatus.Filled:
            self.openSellLots += lots
            self.StopMarketOrder(self.symbol, lots, stop_price)
            self.LimitOrder(self.symbol, lots, take_profit)

    def IsExcessiveDrawdown(self):
        """Check if current drawdown exceeds threshold"""
        # Calculate unrealized profit percentage manually
        total_unrealized_profit_pct = (self.Portfolio.TotalUnrealizedProfit / 
                                    self.Portfolio.TotalPortfolioValue)
        return total_unrealized_profit_pct < -self.maxDrawdown

    def IsVolatilityHigh(self):
        """Check if current volatility is too high"""
        return self.atr.Current.Value > self.atr.Current.Value * 1.5  # Compare to historical average

    def CanTrade(self):
        """Check if trading conditions are met"""
        return (
            self.Portfolio.MarginRemaining > self.Portfolio.TotalPortfolioValue * 0.25 and
            not self.IsExcessiveDrawdown() and
            not self.IsVolatilityHigh()
        )

    def UpdateRangeLevels(self):
        """Update support and resistance levels"""
        if not all([self.high.IsReady, self.low.IsReady, self.atr.IsReady]):
            return
            
        # Only update range levels if they haven't been set or significant time has passed
        if self.buyLine is None or self.sellLine is None:
            self.buyLine = self.low.Current.Value
            self.sellLine = self.high.Current.Value
            
            # Add buffer to range levels using ATR
            range_buffer = self.atr.Current.Value * 0.5
            self.buyLine -= range_buffer
            self.sellLine += range_buffer
            
            self.Plot("Range Levels", "Support", self.buyLine)
            self.Plot("Range Levels", "Resistance", self.sellLine)


class RangeBoundRiskManagement(RiskManagementModel):
    def __init__(self, maximum_drawdown_percent):
        self.maximum_drawdown_percent = maximum_drawdown_percent
        self.exit_triggered = False
        
    def ManageRisk(self, algorithm, targets):
        # Calculate total unrealized profit percent
        total_unrealized_profit_pct = (algorithm.Portfolio.TotalUnrealizedProfit / 
                                     algorithm.Portfolio.TotalPortfolioValue)
        
        if total_unrealized_profit_pct < -self.maximum_drawdown_percent:
            self.exit_triggered = True
            return [PortfolioTarget(symbol, 0) for symbol in algorithm.Securities.Keys]
            
        if self.exit_triggered and total_unrealized_profit_pct >= 0:
            self.exit_triggered = False
            
        return targets
