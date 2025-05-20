import pandas as pd
import logging

logger = logging.getLogger(__name__)

def scan_signals(pair, df):
    """Scan sinyal trading berdasarkan indikator."""
    try:
        if df.empty:
            logger.warning("DataFrame kosong diterima")
            return pd.DataFrame()

        required_columns = ['macd', 'macd_signal', 'volume_spike', 'rsi', 'bb_upper', 'bb_lower', 'close']
        if not all(col in df.columns for col in required_columns):
            logger.error(f"Kolom indikator tidak lengkap: {required_columns}")
            return pd.DataFrame()

        signals = df.copy()

        # MACD Cross
        signals['macd_cross_flag'] = (
            (signals['macd'] > signals['macd_signal']) & 
            (signals['macd'].shift(1) <= signals['macd_signal'].shift(1))
        )
        signals['macd_signal_label'] = signals['macd_cross_flag'].map({True: "Bullish Cross", False: ""})

        # Volume Spike
        signals['volume_spike_label'] = signals['volume_spike'].map({1: "Volume Spike", 0: ""})

        # RSI Overbought/Oversold
        signals['rsi_signal'] = signals['rsi'].apply(
            lambda x: "Oversold" if x < 30 else ("Overbought" if x > 70 else "")
        )

        # Bollinger Band Breakout/Breakdown
        signals['bb_breakout'] = (signals['close'] > signals['bb_upper']).map({True: "Breakout", False: ""})
        signals['bb_breakdown'] = (signals['close'] < signals['bb_lower']).map({True: "Breakdown", False: ""})

        # Kombinasi Volume & Price Spike
        signals['price_change'] = signals['close'].pct_change() * 100
        signals['combo_spike'] = (
            (signals['volume_spike'] == 1) & (signals['price_change'] > 3)
        ).map({True: "Strong Up Spike", False: ""})

        signals['pair'] = pair
        signals['timestamp'] = signals.index

        return signals[['pair', 'timestamp', 'open', 'high', 'low', 'close', 
                        'macd', 'macd_signal_label', 'volume_spike_label', 'rsi_signal',
                        'bb_breakout', 'bb_breakdown', 'combo_spike']]

    except Exception as e:
        logger.error(f"Error dalam scan_signals: {str(e)}", exc_info=True)
        return pd.DataFrame()
