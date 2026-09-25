import os
import requests
import yfinance as yf
import pandas as pd
import numpy as np

BOT_TOKEN = "8896031421:AAFIeqDTKsH64aAnaCuiuW8F9aZxMTIEA9g"

# માન્ય યુઝર્સનું લિસ્ટ (અલ્પેશભાઈ + નવો યુઝર)
ALLOWED_USERS = [583221734, 1051774043]

def send_telegram_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Error sending message: {e}")

def get_updates():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        res = requests.get(url, timeout=10).json()
        return res.get("result", [])
    except:
        return []

def clear_updates(last_update_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"offset": last_update_id + 1}
    try:
        requests.get(url, params=params, timeout=10)
    except:
        pass

def backtest_car_stock(symbol_input, lot_size=5000, target_pct=0.0628):
    ticker = symbol_input.upper().replace('NSE:', '').replace('BSE:', '').strip()
    if not ticker.endswith('.NS') and not ticker.endswith('.BO'):
        ticker += '.NS'

    df = yf.download(ticker, period='2y', interval='1d', progress=False)
    if df.empty or len(df) < 100:
        return f"❌ '{symbol_input}' માટે પૂરતો ઐતિહાસિક ડેટા મળ્યો નથી. કૃપા કરીને સાચો સ્ટોક સિમ્બોલ આપો."

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    for col in ['Open', 'High', 'Low', 'Close']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=['Open', 'High', 'Low', 'Close'], inplace=True)

    if len(df) < 100:
        return f"❌ '{symbol_input}' માટે માન્ય ભાવ ડેટા મળ્યો નથી."

    # ૧. Year High (છેલ્લા ૨૫૦ દિવસનો હાઇ)
    df['Year_High'] = df['High'].rolling(window=250, min_periods=50).max()

    # ૨. Year High થી Cumulative Average ની ગણતરી
    highs = df['High'].values
    closes = df['Close'].values
    cum_avgs = np.zeros(len(df))

    current_high = -1.0
    running_sum = 0.0
    count = 0

    for i in range(len(df)):
        h = highs[i]
        c = closes[i]
        if h >= df['Year_High'].values[i]:
            current_high = h
            running_sum = c
            count = 1
        else:
            running_sum += c
            count += 1
        cum_avgs[i] = running_sum / count

    df['Cumulative_Avg'] = cum_avgs

    # ૩. CAR પોઝિટિવ: ૧૦ દિવસથી સતત વધારો
    avg_diff = df['Cumulative_Avg'].diff()
    df['CAR_Positive'] = (avg_diff > 0).rolling(window=10).apply(lambda s: (s == True).all(), raw=True).fillna(0).astype(bool)

    # ૪. વીકલી હાઇ (પાછલા સપ્તાહનો હાઇ)
    weekly_high = df['High'].resample('W').max().shift(1)
    df['Prev_Week_High'] = weekly_high.reindex(df.index, method='ffill')

    # છેલ્લા ૧ વર્ષનો ડેટા (૨૫૦ સેશન)
    backtest_df = df.iloc[-250:].copy()
    open_lots = []
    completed_trades = []

    for date, row in backtest_df.iterrows():
        # A. ટાર્ગેટ ચેક (6.28%)
        remaining_lots = []
        for lot in open_lots:
            target_price = lot['buy_price'] * (1 + target_pct)
            if row['High'] >= target_price:
                profit = lot['qty'] * (target_price - lot['buy_price'])
                completed_trades.append({'profit': profit})
            else:
                remaining_lots.append(lot)
        open_lots = remaining_lots

        # B. GTT Buy ટ્રિગર
        prev_h = row['Prev_Week_High']
        if row['CAR_Positive'] and not pd.isna(prev_h):
            if row['High'] >= prev_h:
                exec_price = max(float(prev_h), float(row['Open']))
                qty = int(lot_size // exec_price)
                if qty > 0:
                    open_lots.append({
                        'buy_date': date,
                        'buy_price': exec_price,
                        'qty': qty
                    })

    # CMP સચોટ છેલ્લો ભાવ
    valid_closes = backtest_df['Close'].dropna()
    if not valid_closes.empty:
        cmp = float(valid_closes.iloc[-1])
    else:
        cmp = float(df['Close'].dropna().iloc[-1])

    total_booked_profit = sum(t['profit'] for t in completed_trades)

    msg = f"📊 *બેકટેસ્ટ રિપોર્ટ: {ticker.replace('.NS', '')}* (છેલ્લા ૧ વર્ષ)\n"
    msg += f"──────────────────────\n"
    msg += f"🔹 *વર્તમાન કિંમત (CMP):* ₹{cmp:,.2f}\n"
    msg += f"✅ *સફળ ટ્રેડ્સ (Target 6.28%):* {len(completed_trades)} વાર\n"
    msg += f"💰 *કુલ બુક થયેલો નફો:* ₹{total_booked_profit:,.2f}\n\n"

    msg += f"📦 *ચાલુ હોલ્ડિંગ સ્થિતિ:*\n"
    if len(open_lots) == 0:
        msg += f"🎉 *કોઈ લોટ બાકી નથી!* તમામ ખરીદાયેલા લોટ 6.28% ના ટાર્ગેટ સાથે વેચાઈ ગયા છે.\n"
    else:
        total_open_qty = sum(l['qty'] for l in open_lots)
        total_open_inv = sum(l['qty'] * l['buy_price'] for l in open_lots)
        avg_price = total_open_inv / total_open_qty
        last_lot = open_lots[-1]
        current_val = total_open_qty * cmp
        unrealized_pnl = current_val - total_open_inv
        unrealized_pnl_pct = (unrealized_pnl / total_open_inv) * 100

        msg += f"• *ઊભા રહેલા ₹૫,૦૦૦ ના લોટ્સ:* {len(open_lots)}\n"
        msg += f"• *કુલ બાકી શેર:* {total_open_qty}\n"
        msg += f"• *ખરીદ સરેરાશ (Average):* ₹{avg_price:,.2f}\n"
        msg += f"• *છેલ્લા લોટની કિંમત:* ₹{last_lot['buy_price']:,.2f} ({last_lot['buy_date'].strftime('%d-%m-%Y')})\n"
        msg += f"• *કુલ રોકાણ:* ₹{total_open_inv:,.2f}\n"
        pnl_sign = "+" if unrealized_pnl >= 0 else ""
        msg += f"• *હાલનું P&L:* {pnl_sign}₹{unrealized_pnl:,.2f} ({pnl_sign}{unrealized_pnl_pct:.2f}%)\n"

    msg += f"──────────────────────\n"
    msg += f"⚙️ _CAR Positive + Weekly High GTT Trigger (Mahesh Kaushik Strategy)_"
    return msg

def main():
    updates = get_updates()
    if not updates:
        print("કોઈ નવો મેસેજ નથી.")
        return

    last_update_id = updates[-1]["update_id"]

    for u in updates:
        message = u.get("message", {})
        sender_id = message.get("from", {}).get("id")
        first_name = message.get("from", {}).get("first_name", "મિત્ર")
        text = message.get("text", "").strip()

        # બંનેમાંથી કોઈપણ માન્ય યુઝર હોય તો રિસ્પોન્સ આપશે
        if sender_id in ALLOWED_USERS and text:
            if text.startswith("/start"):
                send_telegram_msg(sender_id, f"નમસ્તે {first_name}! 🙏\nતમે મને કોઈપણ સ્ટોકનું નામ મોકલો (દા.ત. `TCS`, `BEL`, `PERSISTENT`). હું બેકટેસ્ટિંગ રિપોર્ટ મોકલી આપીશ.")
            else:
                ack_text = f"📩 *નિવેદન મળ્યું છે:* `{text}`\n⏳ બેકટેસ્ટિંગ શરૂ થઈ રહ્યું છે..."
                send_telegram_msg(sender_id, ack_text)

                report = backtest_car_stock(text)
                send_telegram_msg(sender_id, report)

    clear_updates(last_update_id)

if __name__ == "__main__":
    main()
