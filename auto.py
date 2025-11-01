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
    df['bb_mid'] = df['close'].rolling(window=bb_period).mean()
    df['bb_std'] = df['close'].rolling(window=bb_period).std()
    df['bb_width'] = ((df['bb_mid'] + (df['bb_std'] * bb_std_dev)) - (df['bb_mid'] - (df['bb_std'] * bb_std_dev))) / df['bb_mid']
    df['avg_volume'] = df['volume'].rolling(window=20).mean()
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
    best_signal, best_symbol, max_volume = 'hold', None, 0
    discord_messages = ["------------------ 🤖 스마트 전략 스캐너 작동 ------------------\n"]

    for symbol in symbols_to_scan:
        state = signal_states[symbol]
        df_long = get_market_data(symbol, long_term_timeframe, max(ma_periods) + 1)
        long_term_trend = get_long_term_trend(df_long)
        
        # add_indicators 호출은 한번만 하도록 수정
        if df_long is not None:
             df_long = add_indicators(df_long)
             current_adx = df_long.iloc[-1]['ADX'] if 'ADX' in df_long.columns and not pd.isna(df_long.iloc[-1]['ADX']) else 0
             market_condition = '돌파' if current_adx > adx_threshold else '반등'
        else:
             long_term_trend = 'hold' # 데이터 없으면 hold 처리
             current_adx = 0
             market_condition = '반등' # 기본값
        
        log_details = f"장기추세: {long_term_trend} | **매매법: {market_condition}**(ADX:{current_adx:.1f})"
        
        df_short = get_market_data(symbol, timeframe, max(ma_periods) + 20)
        if df_short is not None and len(df_short) >= max(ma_periods):
            df_short = add_indicators(df_short)
            if not df_short.iloc[-1].isnull().any():
                latest = df_short.iloc[-1]
                previous = df_short.iloc[-2]

                # --- 상세 분석 로그 생성 (항상 실행) ---
                volume_check = latest['volume'] > latest['avg_volume'] * volume_multiplier if not pd.isna(latest['avg_volume']) else False
                bb_check = latest['bb_width'] > df_short['bb_width'].iloc[-5:-1].mean() if not pd.isna(latest['bb_width']) else False
                
                # 로그 생성을 위한 변수 초기화
                ma_short_check_up = ma_short_check_down = False
                rsi_check_up = rsi_check_down = False
                vwma_breakout_up = vwma_breakout_down = False
                vwma_bounce_up = vwma_bounce_down = False

                if not pd.isna(latest['ma7']) and not pd.isna(latest['ma15']):
                    ma_short_check_up = latest['ma7'] > latest['ma15']
                    ma_short_check_down = latest['ma7'] < latest['ma15']
                if not pd.isna(latest['rsi']):
                    rsi_check_up = latest['rsi'] < rsi_overbought
                    rsi_check_down = latest['rsi'] > rsi_oversold
                if not pd.isna(latest['vwma']) and not pd.isna(previous['vwma']):
                    vwma_breakout_up = latest['close'] > latest['vwma'] and previous['close'] <= latest['vwma']
                    vwma_bounce_up = previous['close'] > previous['vwma'] and latest['low'] <= latest['vwma'] and latest['close'] > latest['vwma']
                    vwma_breakout_down = latest['close'] < latest['vwma'] and previous['close'] >= latest['vwma']
                    vwma_bounce_down = previous['close'] < previous['vwma'] and latest['high'] >= latest['vwma'] and latest['close'] < latest['vwma']

                if long_term_trend == 'up':
                    if market_condition == '돌파':
                        log_details += f" | MA(7>15):{'✅' if ma_short_check_up else '❌'} | VWMA(↗️):{'✅' if vwma_breakout_up else '❌'} | 거래량:{'✅' if volume_check else '❌'} | RSI(<70):{'✅' if rsi_check_up else '❌'} | BB확장:{'✅' if bb_check else '❌'}"
                    elif market_condition == '반등':
                        log_details += f" | MA(7>15):{'✅' if ma_short_check_up else '❌'} | VWMA(🤸):{'✅' if vwma_bounce_up else '❌'} | 거래량:{'✅' if volume_check else '❌'} | RSI(<70):{'✅' if rsi_check_up else '❌'} | BB확장:{'✅' if bb_check else '❌'}"
                elif long_term_trend == 'down':
                    if market_condition == '돌파':
                        log_details += f" | MA(7<15):{'✅' if ma_short_check_down else '❌'} | VWMA(↘️):{'✅' if vwma_breakout_down else '❌'} | 거래량:{'✅' if volume_check else '❌'} | RSI(>30):{'✅' if rsi_check_down else '❌'}"
                    elif market_condition == '반등':
                        log_details += f" | MA(7<15):{'✅' if ma_short_check_down else '❌'} | VWMA(🤕):{'✅' if vwma_bounce_down else '❌'} | 거래량:{'✅' if volume_check else '❌'} | RSI(>30):{'✅' if rsi_check_down else '❌'}"

                # --- 실제 진입 결정 ---
                if long_term_trend != 'hold':
                    signal_found = False
                    if market_condition == '돌파':
                        if long_term_trend == 'up' and ma_short_check_up and vwma_breakout_up and volume_check and rsi_check_up and bb_check: signal_found = True
                        elif long_term_trend == 'down' and ma_short_check_down and vwma_breakout_down and volume_check and rsi_check_down: signal_found = True
                    elif market_condition == '반등':
                        if long_term_trend == 'up' and ma_short_check_up and vwma_bounce_up and volume_check and rsi_check_up and bb_check: signal_found = True
                        elif long_term_trend == 'down' and ma_short_check_down and vwma_bounce_down and volume_check and rsi_check_down: signal_found = True
                    
                    if signal_found:
                        signal_type = 'long' if long_term_trend == 'up' else 'short'
                        current_volume = latest['volume'] if not pd.isna(latest['volume']) else 0
                        if current_volume > max_volume:
                            max_volume, best_signal, best_symbol = current_volume, signal_type, symbol
            else:
                 log_details += " | 5분봉 데이터 부족"
        else:
             log_details += " | 1시간봉 데이터 부족"


        terminal_log = f"[{symbol}] 스캔 중... {log_details}"
        print(terminal_log)
        discord_messages.append(f"**[{symbol}]** {log_details}")
        time.sleep(1) # API 요청 제한 방지 딜레이를 1초로 줄임 (enableRateLimit 사용 중이므로)
            
    if best_symbol:
        df_long_final = get_market_data(best_symbol, long_term_timeframe, max(ma_periods) + 1)
        # Check if df_long_final is valid before proceeding
        if df_long_final is not None and not df_long_final.empty:
            df_long_final = add_indicators(df_long_final)
            final_adx = df_long_final.iloc[-1]['ADX'] if 'ADX' in df_long_final.columns and not pd.isna(df_long_final.iloc[-1]['ADX']) else 0
            final_market_condition = '돌파' if final_adx > adx_threshold else '반등'
            result_message = f"✅ **최적 종목 발견:** `[{best_symbol}]` | **신호:** `{best_signal}` | **매매법:** `{final_market_condition}`"
        else:
             result_message = f"✅ **최적 종목 발견:** `[{best_symbol}]` | **신호:** `{best_signal}` | **매매법:** 정보 조회 불가"

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
                            # if signal == 'long':
                            #     exchange.create_market_buy_order(best_symbol, amount_to_order)
                            # elif signal == 'short':
                            #     exchange.create_market_sell_order(best_symbol, amount_to_order)

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
                         # if position["side"] == 'long':
                         #     exchange.create_market_sell_order(position['symbol'], position['amount'], {'reduceOnly': True})
                         # elif position["side"] == 'short':
                         #     exchange.create_market_buy_order(position['symbol'], position['amount'], {'reduceOnly': True})

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