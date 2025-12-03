# -----------------------------------------------------------------------------
# |                      '불장단타왕' 자동매매 봇 최종본                      |
# |    - ADX 전략 전환 / 모든 MA 전략 / 상세 로그 / 종료 알림 / 멀티 코인 / 선물    |
# -----------------------------------------------------------------------------
import ccxt
import pandas as pd
import time
import numpy as np
import requests
import sys

# -----------------------------------------------------------------------------
# |                      🚨 중요: API 키 및 웹훅 설정 🚨                      |
# -----------------------------------------------------------------------------
# 새로 발급받은 안전한 키와 URL을 입력하세요. (절대 외부에 노출 금지!)
access_key = "853QbSsVkx8wGSvq7zsAl7aHSGWpREkiz1PhA8mLiMtz0XjUXWXy5XJxQm0sMh7r"
secret_key = "eJ1Qa2rGUrxY8Fcbg4IHGutcga38xf5Z8GvphlVQL1QmxyWoyTk0Q0IDZXJGYRkd"
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1426270675777093834/GcqRg-v1VwuSLNiUaVy985-UPuYS0l-6dHoKHpe5XBiH8Lkgcj6-DgOuGHahi4vgd6cV"

# -----------------------------------------------------------------------------
# |                        매매 기본 설정 (수정 가능)                        |
# -----------------------------------------------------------------------------
target_symbols = ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'DOGE/USDT', 'SOL/USDT', 'ADA/USDT', 'BNB/USDT', 'SUI/USDT'] 
timeframe = '5m'
long_term_timeframe = '1h'
leverage = 5
ENTRY_BALANCE_PERCENTAGE = 0.99 # 진입 시 사용 가능한 잔고 비율 (0.99 = 99%)
CONFIRMATION_WINDOW = 9 # 신호 확인을 위한 봉 개수

# --- '불장단타왕' 전략 지표 상세 설정 ---
fee_rate = 0.0005 # 바이낸스 선물 수수료 (0.0005 = 0.05%) - 시장가/지정가 따라 다름 확인 필요
target_profit_ratio = 0.05 # 이익 비율
target_loss_ratio = 0.01 # 손실 비율
vwma_period = 14 # VWMA 기간
volume_multiplier = 1.5
ma_periods = [7, 15, 50, 100, 200, 400]
rsi_period = 14
rsi_overbought = 70
rsi_oversold = 30
bb_period = 20
bb_std_dev = 2
adx_period = 14
adx_threshold = 25

# --- 수수료 및 레버리지를 반영한 실제 손익절 비율 자동 계산 ---
actual_take_profit_ratio = 1 + (target_profit_ratio + fee_rate * 2) / leverage 
actual_stop_loss_ratio = 1 - (target_loss_ratio + fee_rate * 2) / leverage
actual_short_take_profit_ratio = 1 - (target_profit_ratio + fee_rate * 2) / leverage
actual_short_stop_loss_ratio = 1 + (target_loss_ratio + fee_rate * 2) / leverage

# -----------------------------------------------------------------------------
# |                         거래소 객체 생성 및 상태 변수                     |
# -----------------------------------------------------------------------------
exchange = ccxt.binance({'apiKey': access_key, 'secret': secret_key, 'options': {'defaultType': 'future'},'enableRateLimit': True})

signal_states = {
    symbol: {
        "is_observing": False, "candles_since_start": 0, "signal_type": None, "checklist": {}
    } for symbol in target_symbols
}

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
    except Exception as e:
        print(f"[{symbol}] 데이터 조회 오류: {e}")
        return None

def add_indicators(df):
    for period in ma_periods:
        df[f'ma{period}'] = df['close'].rolling(window=period).mean()
    if len(df) >= vwma_period: 
        df['vwma'] = (df['close'] * df['volume']).rolling(vwma_period).sum() / df['volume'].rolling(vwma_period).sum()
    else: 
        df['vwma'] = np.nan
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))

    # <<< 여기부터 수정됨: 상단선(bb_upper)과 하단선(bb_lower)을 명시적으로 계산하여 저장 >>>
    df['bb_mid'] = df['close'].rolling(window=bb_period).mean()
    df['bb_std'] = df['close'].rolling(window=bb_period).std()
    
    df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * bb_std_dev) # 상단선 저장
    df['bb_lower'] = df['bb_mid'] - (df['bb_std'] * bb_std_dev) # 하단선 저장
    
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid'] # 저장된 값으로 폭 계산
    # <<< 수정 끝 >>>

    df['avg_volume'] = df['volume'].rolling(window=20).mean()
    
    # ADX 계산
    high_minus_low = df['high'] - df['low']
    high_minus_prev_close = abs(df['high'] - df['close'].shift(1))
    low_minus_prev_close = abs(df['low'] - df['close'].shift(1))
    tr_df = pd.DataFrame({'hl': high_minus_low, 'hpc': high_minus_prev_close, 'lpc': low_minus_prev_close})
    df['TR'] = tr_df.max(axis=1)
    df['ATR'] = df['TR'].ewm(alpha=1/adx_period, min_periods=adx_period, adjust=False).mean()
    up_move = df['high'] - df['high'].shift(1)
    down_move = df['low'].shift(1) - df['low']
    df['+DM'] = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    df['-DM'] = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    df['+DI'] = (df['+DM'].ewm(alpha=1/adx_period, min_periods=adx_period, adjust=False).mean() / df['ATR']) * 100
    df['-DI'] = (df['-DM'].ewm(alpha=1/adx_period, min_periods=adx_period, adjust=False).mean() / df['ATR']) * 100
    df['DX'] = (abs(df['+DI'] - df['-DI']) / (abs(df['+DI'] + df['-DI']) + 1e-6)) * 100
    df['ADX'] = df['DX'].ewm(alpha=1/adx_period, min_periods=adx_period, adjust=False).mean()
    
    return df

def get_long_term_trend(df):
    if df is None or len(df) < max(ma_periods): return 'hold'
    df = add_indicators(df)
    if df['ma200'].isnull().all(): return 'hold'
    latest = df.iloc[-1]
    if latest['ma50'] > latest['ma100'] and latest['ma100'] > latest['ma200']:
        return 'up'
    elif latest['ma50'] < latest['ma100'] and latest['ma100'] < latest['ma200']:
        return 'down'
    else:
        return 'hold'

def reset_signal_state(symbol):
    signal_states[symbol] = {"is_observing": False, "candles_since_start": 0, "signal_type": None, "checklist": {}}

def scan_for_best_signal(symbols_to_scan):
    """상승/하락/횡보 모든 시장 상황에 맞춰 최적의 진입 신호를 찾습니다."""
    best_signal, best_symbol, max_volume = 'hold', None, 0
    discord_messages = ["------------------ 🤖 전천후(All-Weather) 스캐너 작동 ------------------\n"]

    for symbol in symbols_to_scan:
        # 1. 데이터 준비
        df_long = get_market_data(symbol, long_term_timeframe, max(ma_periods) + 1)
        long_term_trend = get_long_term_trend(df_long)
        
        df_long = add_indicators(df_long)
        current_adx = df_long.iloc[-1]['ADX'] if 'ADX' in df_long.columns and not pd.isna(df_long.iloc[-1]['ADX']) else 0
        
        # 시장 상황 판단 (추세장 vs 횡보장)
        market_condition = '돌파' if current_adx > adx_threshold else '반등'
        
        log_details = f"장기추세: {long_term_trend} | 모드: {market_condition}(ADX:{current_adx:.1f})"
        
        df_short = get_market_data(symbol, timeframe, max(ma_periods) + 20)
        
        if df_short is not None and len(df_short) >= max(ma_periods):
            df_short = add_indicators(df_short)
            if not df_short.iloc[-1].isnull().any():
                latest = df_short.iloc[-1]
                previous = df_short.iloc[-2]

                # --- 공통 지표 정의 ---
                # 거래량 체크 (횡보장에서는 거래량 조건 완화: 1.2배)
                vol_mult = volume_multiplier if long_term_trend != 'hold' else 1.2
                volume_check = latest['volume'] > latest['avg_volume'] * vol_mult
                bb_check = latest['bb_width'] > df_short['bb_width'].iloc[-5:-1].mean()
                
                # --- [상황 1] 상승장 (UP) ---
                if long_term_trend == 'up':
                    ma_short_check = latest['ma7'] > latest['ma15']
                    vwma_break = latest['close'] > latest['vwma'] and previous['close'] <= latest['vwma'] # 돌파
                    vwma_bounce = previous['close'] > previous['vwma'] and latest['low'] <= latest['vwma'] and latest['close'] > latest['vwma'] # 지지
                    
                    if market_condition == '돌파':
                        log_details += f" | 롱(돌파)대기.. VWMA(↗️):{'✅' if vwma_break else '❌'}"
                        if ma_short_check and vwma_break and volume_check and bb_check:
                            if latest['volume'] > max_volume: max_volume, best_signal, best_symbol = latest['volume'], 'long', symbol
                    elif market_condition == '반등':
                        log_details += f" | 롱(눌림)대기.. VWMA(🤸):{'✅' if vwma_bounce else '❌'}"
                        if ma_short_check and vwma_bounce and volume_check:
                            if latest['volume'] > max_volume: max_volume, best_signal, best_symbol = latest['volume'], 'long', symbol

                # --- [상황 2] 하락장 (DOWN) ---
                elif long_term_trend == 'down':
                    ma_short_check = latest['ma7'] < latest['ma15']
                    vwma_break = latest['close'] < latest['vwma'] and previous['close'] >= latest['vwma'] # 돌파
                    vwma_bounce = previous['close'] < previous['vwma'] and latest['high'] >= latest['vwma'] and latest['close'] < latest['vwma'] # 저항

                    if market_condition == '돌파':
                        log_details += f" | 숏(돌파)대기.. VWMA(↘️):{'✅' if vwma_break else '❌'}"
                        if ma_short_check and vwma_break and volume_check:
                            if latest['volume'] > max_volume: max_volume, best_signal, best_symbol = latest['volume'], 'short', symbol
                    elif market_condition == '반등':
                        log_details += f" | 숏(저항)대기.. VWMA(🤕):{'✅' if vwma_bounce else '❌'}"
                        if ma_short_check and vwma_bounce and volume_check:
                            if latest['volume'] > max_volume: max_volume, best_signal, best_symbol = latest['volume'], 'short', symbol

                # --- [상황 3] 횡보장 (HOLD) - 신규 추가된 박스권 매매 ---
                else:
                    long_term_trend == 'hold'
                    # 볼린저 밴드 역추세 매매 (하단 터치시 롱, 상단 터치시 숏)
                    bb_lower_hit = previous['close'] < previous['bb_lower'] and latest['close'] > latest['bb_lower'] # 하단 뚫고 복귀
                    bb_upper_hit = previous['close'] > previous['bb_upper'] and latest['close'] < latest['bb_upper'] # 상단 뚫고 복귀
                    rsi_low = latest['rsi'] < 35  # 과매도
                    rsi_high = latest['rsi'] > 65 # 과매수

                    # 횡보장에서는 ADX가 낮아야 안전함
                    if current_adx < 25:
                        if bb_lower_hit and rsi_low:
                            log_details += f" | 박스권 롱:{'✅'} (BB하단+과매도)"
                            if latest['volume'] > max_volume: max_volume, best_signal, best_symbol = latest['volume'], 'long', symbol
                        elif bb_upper_hit and rsi_high:
                            log_details += f" | 박스권 숏:{'✅'} (BB상단+과매수)"
                            if latest['volume'] > max_volume: max_volume, best_signal, best_symbol = latest['volume'], 'short', symbol
                        else:
                            log_details += f" | 박스권 관망 (BB터치대기)"
                    else:
                        log_details += f" | 혼조세 관망 (ADX높음)"

        terminal_log = f"[{symbol}] 스캔 중... {log_details}"
        print(terminal_log)
        discord_messages.append(f"**[{symbol}]** {log_details}")
        time.sleep(1)
            
    if best_symbol:
        result_message = f"✅ **최적 종목 발견:** `[{best_symbol}]` | **신호:** `{best_signal}`"
    else: 
        result_message = "...진입 가능한 종목 없음..."
    
    print(result_message)
    discord_messages.append(result_message)
    send_discord_message("\n".join(discord_messages))
    
    return best_signal, best_symbol
# -----------------------------------------------------------------------------
# |                         자동매매 메인 실행 루프                           |
# -----------------------------------------------------------------------------
def main():
    position = {"side": "none", "symbol": None, "entry_price": 0, "amount": 0, "order_amount_usdt": 0}
    send_discord_message("🔥 '단타왕' 최종 자동매매 봇이 시작되었습니다.")
    try:
        for symbol in target_symbols:
            try:
                exchange.set_margin_mode('ISOLATED', symbol)
                exchange.set_leverage(leverage, symbol)
                print(f"✅ [{symbol}] 격리 마진, 레버리지 {leverage}x 설정 완료.")
            except ccxt.DDoSProtection as e:
                print(f"[{symbol}] 초기 설정 중 API 속도 제한: {e}")
                time.sleep(5) 
            except ccxt.ExchangeError as e:
                print(f"[{symbol}] 초기 설정 중 거래소 오류: {e}")
            except Exception as e:
                 send_discord_message(f"⚠️ [{symbol}] 초기 설정 중 예측하지 못한 오류: {e}") 

    except Exception as e:
        send_discord_message(f"⚠️ 초기 설정 실패 (전체): {e}"); return
        
    try:
        while True:
            if position["side"] == 'none':
                signal, best_symbol = scan_for_best_signal(target_symbols)

                if isinstance(best_symbol, str) and signal != 'hold': 
                    try: 
                        balance = exchange.fetch_balance()
                        available_balance = balance['USDT']['free']
                        order_amount_usdt = available_balance * ENTRY_BALANCE_PERCENTAGE
                        if order_amount_usdt < 10:
                            print(f"⚠️ 진입 금액 부족 ({order_amount_usdt:.2f} USDT)."); time.sleep(60); continue

                        if isinstance(best_symbol, str):
                            current_price = exchange.fetch_ticker(best_symbol)['last'] 
                            amount_to_order = (order_amount_usdt * leverage) / current_price

                            # 실제 주문 실행 (주석 해제 필요)
                            if signal == 'long':
                                 exchange.create_market_buy_order(best_symbol, amount_to_order)
                            elif signal == 'short':
                                 exchange.create_market_sell_order(best_symbol, amount_to_order)

                            position = {"side": signal, "symbol": best_symbol, "entry_price": current_price, "amount": amount_to_order, "order_amount_usdt": order_amount_usdt}
                            message = f"**[🚀 포지션 진입]**\n- 종목: `{best_symbol}`\n- 포지션: `{signal.upper()}`\n- 진입가: `${current_price:,.4f}`\n- 진입 금액: `${order_amount_usdt:,.2f}`"
                            send_discord_message(message)
                        else:
                            print(f"⚠️ 진입 시점 오류: best_symbol이 유효하지 않음 ({best_symbol})")


                    except ccxt.InsufficientFunds as e:
                        print(f"⚠️ 주문 실행 오류: 잔고 부족 - {e}"); send_discord_message(f"🚨 주문 실패: 잔고 부족!"); time.sleep(60)
                    except ccxt.ExchangeError as e:
                        print(f"⚠️ 주문 실행 중 거래소 오류 ({best_symbol}): {e}"); send_discord_message(f"🚨 주문 실패 ({best_symbol}): {e}")
                    except Exception as e:
                         print(f"⚠️ 예측하지 못한 주문 오류: {e}"); send_discord_message(f"🚨 예측하지 못한 주문 오류: {e}")

            elif position["side"] != 'none' and isinstance(position["symbol"], str):
                 try: 
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

                         is_take_profit = (position["side"] == 'long' and current_price >= tp_price) or (position["side"] == 'short' and current_price <= tp_price)

                         # 실제 청산 주문 실행 (주석 해제 필요)
                         if position["side"] == 'long':
                              exchange.create_market_sell_order(position['symbol'], position['amount'], {'reduceOnly': True})
                         elif position["side"] == 'short':
                              exchange.create_market_buy_order(position['symbol'], position['amount'], {'reduceOnly': True})

                         if is_take_profit:
                             result_type = "🎉 익절"; profit_loss_usd = position["order_amount_usdt"] * target_profit_ratio
                             message = f"**[{result_type}]**\n- 종목: `{position['symbol']}`\n- **예상수익: `+${profit_loss_usd:.2f}`**"
                         else:
                             result_type = "📉 손절"; profit_loss_usd = position["order_amount_usdt"] * target_loss_ratio
                             message = f"**[{result_type}]**\n- 종목: `{position['symbol']}`\n- **예상손실: `-${profit_loss_usd:.2f}`**"

                         send_discord_message(message)
                         position = {"side": "none", "symbol": None, "entry_price": 0, "amount": 0, "order_amount_usdt": 0} 
                 except ccxt.ExchangeError as e:
                      print(f"⚠️ 가격 조회/청산 중 거래소 오류 ({position['symbol']}): {e}"); send_discord_message(f"🚨 가격 조회/청산 오류 ({position['symbol']}): {e}")
                 except Exception as e:
                      print(f"⚠️ 예측하지 못한 가격 조회/청산 오류: {e}"); send_discord_message(f"🚨 예측하지 못한 가격 조회/청산 오류: {e}")
            
            elif position["side"] != 'none' and position["symbol"] is None:
                 print("⚠️ 비정상 상태 감지: 포지션은 있으나 심볼이 없음. 상태 초기화.")
                 send_discord_message("🚨 비정상 상태 감지. 포지션 초기화.")
                 position = {"side": "none", "symbol": None, "entry_price": 0, "amount": 0, "order_amount_usdt": 0}


            sleep_time = 60 if position["side"] == 'none' else 10
            print(f"... {sleep_time}초 후 다음 작업 수행 ...")
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[Ctrl+C] 사용자가 프로그램을 수동으로 종료합니다.")
    except Exception as e:
        error_message = f"메인 루프 오류: {e}"
        print(error_message)
        send_discord_message(f"🚨 봇 오류 발생!\n{error_message}")
    finally:
        print("프로그램을 종료하며, 디스코드로 알림을 보냅니다.")
        send_discord_message("👋 자동매매 봇이 종료되었습니다.")
        sys.exit(0)

if __name__ == '__main__':
    main()