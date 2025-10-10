import ccxt
import pandas as pd
import time
import numpy as np
import requests

# -----------------------------------------------------------------------------
# |                      🚨 중요: API 키 및 웹훅 설정 🚨                      |
# -----------------------------------------------------------------------------
access_key = "NrvO8Eb7n7T5vOTdMDdT7Oa4ihx81AQ3pWYSAJkHxZWwKEPUaPRWfQW67tuSk368"
secret_key = "8mmJszXqfNCxYUKUkPFcj0g4IzDE00B2lGdBrIPQJN1iiI9E4fx8I5vtTCjJpLWS"
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1426270675777093834/GcqRg-v1VwuSLNiUaVy985-UPuYS0l-6dHoKHpe5XBiH8Lkgcj6-DgOuGHahi4vgd6cV"

# -----------------------------------------------------------------------------
# |                        매매 기본 설정 (수정 가능)                        |
# -----------------------------------------------------------------------------
target_symbols = ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'DOGE/USDT', 'SOL/USDT', 'ADA/USDT', 'MATIC/USDT', 'LTC/USDT', 'DOT/USDT', 'AVAX/USDT', 'LINK/USDT', 'TRX/USDT', 'UNI/USDT', 'BCH/USDT', 'XLM/USDT', 'ATOM/USDT', 'ETC/USDT', 'FIL/USDT', 'VET/USDT', 'THETA/USDT',  'ALGO/USDT', 'ICP/USDT', 'AAVE/USDT', 'EOS/USDT', 'KSM/USDT', 'MKR/USDT', 'ZEC/USDT', 'XTZ/USDT', 'DASH/USDT', 'ENJ/USDT', 'SAND/USDT', 'CHZ/USDT', 'GRT/USDT', '1INCH/USDT', 'CRV/USDT', 'SNX/USDT', 'COMP/USDT', 'YFI/USDT', 'BAL/USDT', 'LRC/USDT', 'REN/USDT', 'WAVES/USDT', 'KAVA/USDT', 'CELO/USDT', 'HNT/USDT', 'STX/USDT', 'AR/USDT', 'GLM/USDT', 'ANKR/USDT', 'COTI/USDT', 'IOTX/USDT', 'NKN/USDT', 'OCEAN/USDT', 'QTUM/USDT', 'RSR/USDT', 'SUSHI/USDT', 'TWT/USDT', 'UMA/USDT', 'ZIL/USDT'] 
timeframe = '5m'
leverage = 5
ENTRY_BALANCE_PERCENTAGE = 0.9  # 사용 가능 잔고의 90%를 증거금으로 사용

# --- 전략 지표 설정 ---
fee_rate = 0.0004
target_profit_ratio = 0.05
target_loss_ratio = 0.01
vwma_period = 100
volume_multiplier = 1.5
ma_short_period = 50
ma_long_period = 200
rsi_period = 14
rsi_overbought = 70
rsi_oversold = 30
bb_period = 20
bb_std_dev = 2

# --- 수수료 반영 손익절 비율 ---
actual_take_profit_ratio = 1 + (target_profit_ratio + fee_rate * 2) / leverage
actual_stop_loss_ratio = 1 - (target_loss_ratio + fee_rate * 2) / leverage
actual_short_take_profit_ratio = 1 - (target_profit_ratio + fee_rate * 2) / leverage
actual_short_stop_loss_ratio = 1 + (target_loss_ratio + fee_rate * 2) / leverage

# -----------------------------------------------------------------------------
# |                         거래소 객체 생성 (Binance Futures)               |
# -----------------------------------------------------------------------------
exchange = ccxt.binance({'apiKey': access_key, 'secret': secret_key, 'options': {'defaultType': 'future'}})

# -----------------------------------------------------------------------------
# |                          알림 및 전략 분석 함수                          |
# -----------------------------------------------------------------------------
def send_discord_message(message):
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message})
    except Exception as e:
        print(f"디스코드 전송 오류: {e}")

def get_market_data(symbol, timeframe, limit):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except Exception: return None

def add_indicators(df):
    """요청하신 모든 지표(MA, VWMA, RSI, BB)를 여기서 계산합니다."""
    # MA (Moving Averages)
    df[f'ma{ma_short_period}'] = df['close'].rolling(window=ma_short_period).mean()
    df[f'ma{ma_long_period}'] = df['close'].rolling(window=ma_long_period).mean()
    # VWMA
    if len(df) >= vwma_period: df['vwma'] = (df['close'] * df['volume']).rolling(vwma_period).sum() / df['volume'].rolling(vwma_period).sum()
    else: df['vwma'] = np.nan
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    # Bollinger Bands
    df['bb_mid'] = df['close'].rolling(window=bb_period).mean()
    df['bb_std'] = df['close'].rolling(window=bb_period).std()
    df['bb_width'] = ((df['bb_mid'] + (df['bb_std'] * bb_std_dev)) - (df['bb_mid'] - (df['bb_std'] * bb_std_dev))) / df['bb_mid']
    # Volume
    df['avg_volume'] = df['volume'].rolling(window=20).mean()
    return df

def check_market_conditions():
    """토탈3, BTC.D 거시 지표를 여기서 확인합니다."""
    print("🔍 거시 경제 필터 확인 중...")
    try:
        # TOTAL3.D, BTC.D 심볼은 거래소 및 ccxt 라이브러리 지원에 따라 다를 수 있습니다.
        # 바이낸스 선물에서는 보통 'DEFI/USDT' (DeFi Index) 등으로 대체 분석하기도 합니다.
        # 여기서는 예시로 BTC.D만 확인합니다.
        df_btcd = get_market_data('BTC.D/USDT', '1h', 5)
        if df_btcd is not None and (df_btcd['close'].diff().iloc[-3:] > 0).all():
            print("👎 BTC 도미넌스 상승 중. 매수 보류.")
            return False
        print("👍 BTC 도미넌스 안정/하락 확인.")
        return True
    except Exception as e:
        print(f"거시 지표 확인 오류: {e}. 해당 필터 통과.")
        return True # 오류 시 일단 통과

def scan_for_best_signal(symbols_to_scan):
    best_signal, best_symbol, max_volume = 'hold', None, 0
    print("\n------------------ 멀티 코인 스캐너 작동 ------------------")
    for symbol in symbols_to_scan:
        # 장기 추세 확인
        df_1h = get_market_data(symbol, '1h', ma_long_period + 1)
        if df_1h is None: continue
        long_term_trend = 'up' if add_indicators(df_1h).iloc[-1][f'ma{ma_short_period}'] > add_indicators(df_1h).iloc[-1][f'ma{ma_long_period}'] else 'down'
        
        # 단기 신호 확인
        df_5m = get_market_data(symbol, '5m', vwma_period + 20)
        if df_5m is None: continue
        df_5m = add_indicators(df_5m)
        latest = df_5m.iloc[-1]; previous = df_5m.iloc[-2]
        
        signal, volume = 'hold', 0
        if long_term_trend == 'up' and latest['close'] > latest['vwma'] and previous['close'] <= latest['vwma'] and latest['volume'] > latest['avg_volume'] * volume_multiplier and latest['rsi'] < rsi_overbought and latest['bb_width'] > df_5m['bb_width'].iloc[-5:-1].mean():
            signal, volume = 'long', latest['volume']
        elif long_term_trend == 'down' and latest['close'] < latest['vwma'] and previous['close'] >= latest['vwma'] and latest['volume'] > latest['avg_volume'] * volume_multiplier and latest['rsi'] > rsi_oversold:
            signal, volume = 'short', latest['volume']
        
        print(f"[{symbol}] 스캔 중... 장기추세: {long_term_trend}, 단기신호: {signal}")
        if signal != 'hold' and volume > max_volume:
            max_volume, best_signal, best_symbol = volume, signal, symbol
        time.sleep(1)
            
    if best_symbol: print(f"✅ 최적 종목 발견: [{best_symbol}]")
    else: print("...진입 가능한 종목 없음...")
    return best_symbol, best_signal

# -----------------------------------------------------------------------------
# |                         자동매매 실행 루프                              |
# -----------------------------------------------------------------------------
def main():
    position = {"side": "none", "symbol": None, "entry_price": 0, "amount": 0}
    send_discord_message("🔥 자동매매 봇이 시작되었습니다.")
    
    while True:
        try:
            if position["side"] == 'none':
                # 거시 경제 필터링
                if not check_market_conditions():
                    time.sleep(300); continue
                
                best_symbol, signal = scan_for_best_signal(target_symbols)
                
                if best_symbol and signal != 'hold':
                    balance = exchange.fetch_balance()
                    available_balance = balance['USDT']['free']
                    order_amount_usdt = available_balance * ENTRY_BALANCE_PERCENTAGE
                    
                    if order_amount_usdt < 10:
                        print("⚠️ 진입 금액 부족"); time.sleep(60); continue

                    current_price = exchange.fetch_ticker(best_symbol)['last']
                    amount_to_order = (order_amount_usdt * leverage) / current_price
                    
                    message = f"**[🚀 매수 신호 발생]**\n- 종목: `{best_symbol}`\n- 포지션: `{signal.upper()}`..."
                    send_discord_message(message)
                    
                    position = {"side": signal, "symbol": best_symbol, "entry_price": current_price, "amount": amount_to_order}
            else:
                current_price = exchange.fetch_ticker(position["symbol"])['last']
                
                tp_price, sl_price = (0,0)
                if position["side"] == 'long':
                    tp_price = position["entry_price"] * actual_take_profit_ratio
                    sl_price = position["entry_price"] * actual_stop_loss_ratio
                else: # short
                    tp_price = position["entry_price"] * actual_short_take_profit_ratio
                    sl_price = position["entry_price"] * actual_short_stop_loss_ratio
                
                print(f"현재 보유 중 [{position['symbol']} {position['side'].upper()}]... 현재가: ${current_price:,.4f}")

                if (position["side"] == 'long' and (current_price >= tp_price or current_price <= sl_price)) or \
                   (position["side"] == 'short' and (current_price <= tp_price or current_price >= sl_price)):
                    
                    message = f"**[📈 포지션 종료]**\n- 종목: `{position['symbol']}`..."
                    send_discord_message(message)
                    position = {"side": "none", "symbol": None, "entry_price": 0, "amount": 0}

            sleep_time = 60 if position["side"] == 'none' else 10 #포지션이 없을때 1분 , 있을때 10초
            time.sleep(sleep_time)
        except Exception as e:
            send_discord_message(f"🚨 봇 작동 중 오류 발생!\n{e}")
            time.sleep(60)

if __name__ == "__main__":
    main()