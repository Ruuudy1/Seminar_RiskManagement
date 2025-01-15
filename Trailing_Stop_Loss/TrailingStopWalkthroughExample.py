# Code implementation based on: Algorithmic Trading A-Z | The Complete Course
# 
# CODE MUST BE RUN USING QUANTCONNECT FRAMEWORK
#

from AlgorithmImports import *

class RangeBoundHedgingAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2024, 1, 1)
        self.SetCash(100000)
        
        # Trading pair setup
        self.symbol = self.AddForex("EURUSD", Resolution.Minute).Symbol
        
        # Strategy parameters
        self.r2r = 2  # Risk to reward ratio
        self.buyLine = None
        self.sellLine = None
        self.maxDrawdown = 0.02  # 2% maximum drawdown
        self.positionSize = 0.1  # 10% of portfolio per trade
        
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

        # Correct Bollinger Bands initialization
        self.bb = self.BB(self.symbol, 20, 2)
        self.range_bound_threshold = 0.8
        self.range_period = 20

        self.last_range_update = datetime.min
        self.range_update_interval = timedelta(hours=4)

    def IsRangeBound(self):
        if not self.bb.IsReady:
            return False
            
        price = self.Securities[self.symbol].Price
        upper_band = self.bb.UpperBand.Current.Value
        lower_band = self.bb.LowerBand.Current.Value
        middle_band = self.bb.MiddleBand.Current.Value
        
        # Prevent division by zero
        band_difference = upper_band - lower_band
        if abs(band_difference) < 0.00001:  # Use small epsilon for float comparison
            return False
            
        # Calculate band width for range detection
        band_width = band_difference / middle_band
        
        # Adjust thresholds for EURUSD typical ranges
        # Less restrictive range to catch more opportunities
        is_range = 0.0005 < band_width < 0.01
        
        # Calculate price position with zero division protection
        price_position = (price - lower_band) / band_difference
        within_bands = 0.1 < price_position < 0.9
        
        # Additional check for flat trend
        is_flat = abs(self.sma.Current.Value - middle_band) < self.atr.Current.Value * 0.5
        
        return is_range and within_bands and is_flat



    def OnData(self, data):
        if self.IsWarmingUp or not data.ContainsKey(self.symbol): 
            return

        if not self.IsRangeBound():
            return  # Exit if not range-bound
            
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
        """Calculate buy lot size with improved position sizing"""
        base_size = self.Portfolio.TotalPortfolioValue * 0.02  # Reduce from 10% to 2%
        
        if self.openBuyLots == 0 and self.openSellLots == 0:
            return base_size
            
        # Calculate based on R2R formula from image
        base_lots = ((self.r2r + 1) / self.r2r * self.openSellLots - self.openBuyLots) * 1.1
        return min(base_lots, base_size)

    def CalculateSellLots(self):
        """Calculate sell lot size with improved position sizing"""
        base_size = self.Portfolio.TotalPortfolioValue * 0.02
        
        if self.openBuyLots == 0 and self.openSellLots == 0:
            return base_size
            
        base_lots = ((self.r2r + 1) / self.r2r * self.openBuyLots - self.openSellLots) * 1.1
        return min(base_lots, base_size)


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
        """Improved volatility check"""
        if not self.atr.IsReady:
            return False
            
        try:
            # Get current ATR
            current_atr = self.atr.Current.Value
            
            # Calculate average ATR using available window values
            window_values = [x for x in self.atr.Window if x is not None]
            if len(window_values) < 20:
                return False
                
            avg_atr = sum(x.Value for x in window_values[:20]) / 20
            return current_atr > avg_atr * 1.2  # Compare to 20-period average
            
        except Exception as e:
            self.Debug(f"Volatility check error: {str(e)}")
            return False


    def CanTrade(self):
        """Enhanced trading conditions"""
        return (
            self.Portfolio.MarginRemaining > self.Portfolio.TotalPortfolioValue * 0.4 and  # Increased margin requirement
            not self.IsExcessiveDrawdown() and
            not self.IsVolatilityHigh() and
            self.IsRangeBound() and
            len(self.Transactions.GetOpenOrders()) < 6  # Limit open orders
        )

            
    def UpdateRangeLevels(self):
        if not all([self.high.IsReady, self.low.IsReady, self.atr.IsReady]):
            return
            
        current_time = self.Time
        
        # Update ranges every 4 hours or if not set
        if (self.buyLine is None or self.sellLine is None or 
            current_time - self.last_range_update >= self.range_update_interval):
            
            self.buyLine = self.low.Current.Value
            self.sellLine = self.high.Current.Value
            
            # Wider buffer for range levels
            range_buffer = self.atr.Current.Value * 1.0  # Increased from 0.5
            self.buyLine -= range_buffer
            self.sellLine += range_buffer
            
            self.last_range_update = current_time
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
