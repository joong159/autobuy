# -----------------------------------------------------------------------------
# |                      '불장단타왕' 자동매매 봇 최종본                      |
# |    - 멀티 코인 스캐너 / 선물(롱/숏) / 자동 복리 / 디스코드 알림 기능 포함    |
# -----------------------------------------------------------------------------
import ccxt
import pandas as pd
import time
import numpy as np
import requests

# -----------------------------------------------------------------------------
# |                      🚨 중요: API 키 및 웹훅 설정 🚨                      |
# -----------------------------------------------------------------------------
# 바이낸스 선물 거래 권한이 있는 API 키와 디스코드 웹훅 URL을 입력하세요.
access_key = "NrvO8Eb7n7T5vOTdMDdT7Oa4ihx81AQ3pWYSAJkHxZWwKEPUaPRWfQW67tuSk368"
secret_key = "8mmJszXqfNCxYUKUkPFcj0g4IzDE00B2lGdBrIPQJN1iiI9E4fx8I5vtTCjJpLWS"
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1426270675777093834/GcqRg-v1VwuSLNiUaVy985-UPuYS0l-6dHoKHpe5XBiH8Lkgcj6-DgOuGHahi4vgd6cV"

# -----------------------------------------------------------------------------
# |                        매매 기본 설정 (수정 가능)                        |
# -----------------------------------------------------------------------------
# 분석할 코인 목록 (바이낸스 선물 USDT 마켓에 상장된 심볼)
target_symbols = ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'DOGE/USDT', 'SOL/USDT'] 

# 매매 시간봉 설정
timeframe = '5m'            # 단기 진입/청산 기준봉
long_term_timeframe = '1h'  # 장기 추세 판단 기준봉

# 자금 관리 설정
leverage = 5                # 사용할 레버리지 배수
ENTRY_BALANCE_PERCENTAGE = 0.1  # 진입 시 사용할 잔고 비율 (0.1 = 10%)

# 손익절 설정
fee_rate = 0.0004           # 바이낸스 선물 시장가 수수료 (0.04%)
target_profit_ratio = 0.05  # 목표 순수익률 (+5%)
target_loss_ratio = 0.01    # 손절 순손실률 (-1%)

# --- '불장단타왕' 전략 지표 상세 설정 ---
vwma_period = 100
volume_multiplier = 1.5
ma_short_period = 50
ma_long_period = 200
rsi_period = 14
rsi_overbought = 70
rsi_oversold = 30
bb_period = 20
bb_std_dev = 2

# --- 수수료 및 레버리지를 반영한 실제 손익절 비율 자동 계산 ---
actual_take_profit_ratio = 1 + (target_profit_ratio + fee_rate * 2) / leverage
actual_stop_loss_ratio = 1 - (target_loss_ratio + fee_rate * 2) / leverage
actual_short_take_profit_ratio = 1 - (target_profit_ratio + fee_rate * 2) / leverage
actual_short_stop_loss_ratio = 1 + (target_loss_ratio + fee_rate * 2) / leverage

# -----------------------------------------------------------------------------
# |                         거래소 객체 생성 (Binance Futures)               |
# -----------------------------------------------------------------------------
exchange = ccxt.binance({
    'apiKey': access_key,
    'secret': secret_key,
    'options': {'defaultType': 'future'},
})

# -----------------------------------------------------------------------------
# |                          알림 및 전략 분석 함수                          |
# -----------------------------------------------------------------------------

def send_discord_message(message):
    """디스코드 웹훅으로 메시지를 전송합니다."""
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message})
    except Exception as e:
        print(f"디스코드 전송 오류: {e}")

def get_market_data(symbol, timeframe, limit):
    """거래소에서 OHLCV 데이터를 가져와 DataFrame으로 반환합니다."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except Exception as e:
        print(f"[{symbol}] 데이터 조회 오류: {e}")
        return None

def add_indicators(df):
    """DataFrame에 모든 기술적 보조지표를 계산하여 추가합니다."""
    df[f'ma{ma_short_period}'] = df['close'].rolling(window=ma_short_period).mean()
    df[f'ma{ma_long_period}'] = df['close'].rolling(window=ma_long_period).mean()
    if len(df) >= vwma_period: 
        df['vwma'] = (df['close'] * df['volume']).rolling(vwma_period).sum() / df['volume'].rolling(vwma_period).sum()
    else: 
        df['vwma'] = np.nan
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    df['bb_mid'] = df['close'].rolling(window=bb_period).mean()
    df['bb_std'] = df['close'].rolling(window=bb_period).std()
    df['bb_width'] = ((df['bb_mid'] + (df['bb_std'] * bb_std_dev)) - (df['bb_mid'] - (df['bb_std'] * bb_std_dev))) / df['bb_mid']
    df['avg_volume'] = df['volume'].rolling(window=20).mean()
    return df

def get_long_term_trend(df):
    """장기 시간봉 DataFrame을 받아 추세를 'up', 'down', 'hold'로 반환합니다."""
    if df is None or len(df) < ma_long_period or df[f'ma{ma_long_period}'].isnull().all(): 
        return 'hold'
    df = add_indicators(df)
    latest = df.iloc[-1]
    if latest[f'ma{ma_short_period}'] > latest[f'ma{ma_long_period}']: 
        return 'up'
    else: 
        return 'down'

def get_short_term_signal(df, long_term_trend):
    """단기 시간봉 DataFrame과 장기 추세를 받아 'long', 'short', 'hold' 신호를 반환합니다."""
    df = add_indicators(df)
    if df.isnull().values.any(): return 'hold', 0
    latest = df.iloc[-1]
    previous = df.iloc[-2]
    
    # 롱 진입 조건: 장기 추세 상승 + VWMA 상향 돌파 + 거래량 급증 + RSI 과매수 아님 + 볼린저밴드 확장
    if long_term_trend == 'up':
        if (latest['close'] > latest['vwma'] and previous['close'] <= latest['vwma'] and
            latest['volume'] > latest['avg_volume'] * volume_multiplier and
            latest['rsi'] < rsi_overbought and
            latest['bb_width'] > df['bb_width'].iloc[-5:-1].mean()):
            return 'long', latest['volume']
            
    # 숏 진입 조건: 장기 추세 하락 + VWMA 하향 돌파 + 거래량 급증 + RSI 과매도 아님
    if long_term_trend == 'down':
        if (latest['close'] < latest['vwma'] and previous['close'] >= latest['vwma'] and
            latest['volume'] > latest['avg_volume'] * volume_multiplier and
            latest['rsi'] > rsi_oversold):
            return 'short', latest['volume']
            
    return 'hold', 0
    
def scan_for_best_signal(symbols_to_scan):
    """코인 목록을 스캔하여 가장 거래량이 많은 최적의 진입 신호를 찾습니다."""
    best_signal, best_symbol, max_volume = 'hold', None, 0
    print("\n------------------ 멀티 코인 스캐너 작동 ------------------")
    for symbol in symbols_to_scan:
        df_long = get_market_data(symbol, long_term_timeframe, ma_long_period + 1)
        long_term_trend = get_long_term_trend(df_long)
        
        short_term_signal = 'hold'
        current_volume = 0
        
        if long_term_trend != 'hold':
            df_short = get_market_data(symbol, timeframe, vwma_period + 20)
            if df_short is not None:
                short_term_signal, current_volume = get_short_term_signal(df_short, long_term_trend)
                if short_term_signal != 'hold' and current_volume > max_volume:
                    max_volume, best_signal, best_symbol = current_volume, short_term_signal, symbol

        print(f"[{symbol}] 스캔 중... 장기추세: {long_term_trend}, 단기신호: {short_term_signal}")
        time.sleep(1) # API 과호출 방지
            
    if best_symbol: 
        print(f"✅ 최적 종목 발견: [{best_symbol}] | 신호: {best_signal}")
    else: 
        print("...진입 가능한 종목 없음...")
    return best_symbol, best_signal

# -----------------------------------------------------------------------------
# |                         자동매매 메인 실행 루프                           |
# -----------------------------------------------------------------------------
def main():
    position = {"side": "none", "symbol": None, "entry_price": 0, "amount": 0}
    send_discord_message("🔥 '불장단타왕' 최종 자동매매 봇이 시작되었습니다.")
    
    try:
        for symbol in target_symbols:
            exchange.set_leverage(leverage, symbol)
            print(f"✅ [{symbol}] 레버리지 {leverage}x 설정 완료.")
    except Exception as e:
        send_discord_message(f"⚠️ 레버리지 설정 실패: {e}"); return

    while True:
        try:
            # --- 1. 포지션이 없을 경우: 스캔하여 진입 ---
            if position["side"] == 'none':
                best_symbol, signal = scan_for_best_signal(target_symbols)
                
                if best_symbol and signal != 'hold':
                    balance = exchange.fetch_balance()
                    available_balance = balance['USDT']['free']
                    order_amount_usdt = available_balance * ENTRY_BALANCE_PERCENTAGE
                    
                    if order_amount_usdt < 10: # 최소 주문 금액 체크
                        print(f"⚠️ 진입 금액 부족 ({order_amount_usdt:.2f} USDT). 60초 후 재시도."); time.sleep(60); continue

                    current_price = exchange.fetch_ticker(best_symbol)['last']
                    amount_to_order = (order_amount_usdt * leverage) / current_price
                    
                    # (실제 주문 로직 - 주석 해제 후 사용)
                    # if signal == 'long':
                    #     exchange.create_market_buy_order(best_symbol, amount_to_order)
                    # elif signal == 'short':
                    #     exchange.create_market_sell_order(best_symbol, amount_to_order)
                    
                    # 상태 업데이트 및 알림
                    position = {"side": signal, "symbol": best_symbol, "entry_price": current_price, "amount": amount_to_order}
                    message = f"**[🚀 포지션 진입]**\n- 종목: `{best_symbol}`\n- 포지션: `{signal.upper()}`\n- 진입가: `${current_price:,.4f}`\n- 진입 금액: `${order_amount_usdt:,.2f}` (잔고의 {ENTRY_BALANCE_PERCENTAGE*100}%)"
                    send_discord_message(message)
            
            # --- 2. 포지션이 있을 경우: 익절/손절 감시 ---
            else:
                current_price = exchange.fetch_ticker(position["symbol"])['last']
                
                tp_price, sl_price = (0,0)
                if position["side"] == 'long':
                    tp_price = position["entry_price"] * actual_take_profit_ratio
                    sl_price = position["entry_price"] * actual_stop_loss_ratio
                else: # short
                    tp_price = position["entry_price"] * actual_short_take_profit_ratio
                    sl_price = position["entry_price"] * actual_short_stop_loss_ratio
                
                print(f"현재 보유 중 [{position['symbol']} {position['side'].upper()}]... 현재가: ${current_price:,.4f} | 익절가: ${tp_price:,.4f} | 손절가: ${sl_price:,.4f}")

                if (position["side"] == 'long' and (current_price >= tp_price or current_price <= sl_price)) or \
                   (position["side"] == 'short' and (current_price <= tp_price or current_price >= sl_price)):
                    
                    result_type, profit_loss_percent, profit_loss_usd = "", 0, 0
                    is_take_profit = (position["side"] == 'long' and current_price >= tp_price) or (position["side"] == 'short' and current_price <= tp_price)
                    
                    # (실제 주문 로직 - 주석 해제 후 사용)
                    # if position["side"] == 'long':
                    #     exchange.create_market_sell_order(position["symbol"], position["amount"], {'reduceOnly': True})
                    # elif position["side"] == 'short':
                    #     exchange.create_market_buy_order(position["symbol"], position["amount"], {'reduceOnly': True})

                    # 결과 계산 및 알림
                    if is_take_profit:
                        result_type = "🎉 익절"
                        profit_loss_percent = target_profit_ratio * 100
                        profit_loss_usd = order_amount_usdt * target_profit_ratio
                        message = f"**[{result_type}]**\n- 종목: `{position['symbol']}`\n- 포지션: `{position['side'].upper()}`\n- 진입가: `${position['entry_price']:,.4f}`\n- 청산가: `${current_price:,.4f}`\n- **예상수익: `+${profit_loss_usd:.2f}`**"
                    else:
                        result_type = "📉 손절"
                        profit_loss_percent = target_loss_ratio * 100
                        profit_loss_usd = order_amount_usdt * target_loss_ratio
                        message = f"**[{result_type}]**\n- 종목: `{position['symbol']}`\n- 포지션: `{position['side'].upper()}`\n- 진입가: `${position['entry_price']:,.4f}`\n- 청산가: `${current_price:,.4f}`\n- **예상손실: `-${profit_loss_usd:.2f}`**"
                        
                    send_discord_message(message)
                    position = {"side": "none", "symbol": None, "entry_price": 0, "amount": 0}

            # --- 3. 다음 루프까지 대기 ---
            sleep_time = 60 if position["side"] == 'none' else 10
            print(f"... {sleep_time}초 후 다음 작업 수행 ...")
            time.sleep(sleep_time)

        except Exception as e:
            error_message = f"메인 루프 오류 발생: {e}"
            print(error_message)
            send_discord_message(f"🚨 봇 작동 중단 가능성!\n{error_message}")
            time.sleep(60)

if __name__ == "__main__":
    main()