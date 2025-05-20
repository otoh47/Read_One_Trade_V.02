import ta
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def apply_indicators(df):
    """Menerapkan indikator teknikal pada DataFrame candlestick."""
    try:
        if df.empty:
            logger.warning("DataFrame kosong diterima")
            return df

        required_columns = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_columns):
            logger.error(f"Kolom yang diperlukan tidak ada: {required_columns}")
            return df

        # MACD Indicators
        df['macd'] = ta.trend.macd(df['close'])
        df['macd_signal'] = ta.trend.macd_signal(df['close'])
        df['macd_histogram'] = ta.trend.macd_diff(df['close'])

        # Volume Spike
        df['volume_sma_20'] = df['volume'].rolling(window=20).mean()
        df['volume_spike'] = (df['volume'] > 2 * df['volume_sma_20']).astype(int)

        # RSI
        df['rsi'] = ta.momentum.rsi(df['close'], window=14)

        # Bollinger Bands
        df['bb_upper'] = ta.volatility.bollinger_hband(df['close'])
        df['bb_lower'] = ta.volatility.bollinger_lband(df['close'])

        return df

    except Exception as e:
        logger.error(f"Error dalam apply_indicators: {str(e)}", exc_info=True)
        return df
